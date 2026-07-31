"""Cut a session into laps and classify each one.

How the game records lap structure, established by inspecting real sessions:

- **`Lap`** fires at every start/finish crossing, carrying the new lap number.
  Its `ts` is the crossing time, on the same clock as `GPS Time`. Lap *k* runs
  from its own event to the next one.

- **`Lap Time`** fires at the same instants and carries the time of the lap that
  just *ended*. For a complete lap it matches the gap between crossings to
  within 0.02 s. **A value of exactly zero means the game invalidated the lap.**

- **`Last Sector1` and `Last Sector2` are cumulative**, not per-sector. Verified
  against `Current Sector` transitions: in one Le Mans lap, sector 1 measured
  39.68 s from the transitions and `Last Sector1` read 39.685, while sector 2
  measured 95.52 s and `Last Sector2` read 135.207 - which is 39.685 + 95.52.
  So the durations are `S1`, `S2 - S1`, `LapTime - S2`. Reading `Last Sector2`
  as a sector duration would overstate sector 2 by the whole of sector 1.

The first lap of a session is essentially always partial: recording begins mid
lap, so the gap between the first two crossings covers more than one lap. At Le
Mans the first "lap" spanned 428.9 s against an official 263.7 s. The last lap
is partial for the mirror reason - recording stops before the next crossing.
That is the normal case and is flagged, not discarded.
"""

from __future__ import annotations

import duckdb
import numpy as np

from lmu_telemetry.core.config import Config, load_config
from lmu_telemetry.core.models import Lap, LapFlag
from lmu_telemetry.ingest import events
from lmu_telemetry.ingest.channel_registry import ChannelInfo
from lmu_telemetry.ingest.time_base import TimeBase, sample_times
from lmu_telemetry.logging_config import get_logger
from lmu_telemetry.ui import strings

logger = get_logger(__name__)

LAP_CHANNEL = "Lap"
LAP_TIME_CHANNEL = "Lap Time"
SECTOR1_CHANNEL = "Last Sector1"
SECTOR2_CHANNEL = "Last Sector2"
IN_PITS_CHANNEL = "In Pits"
SURFACE_CHANNEL = "SurfaceTypes"

#: Tolerance when matching an event timestamp to a lap boundary. Boundaries come
#: from the same instant in several channels, but the stored values differ in
#: the last decimal (26.5125 against 26.512), so an exact match fails.
_TS_MATCH_TOLERANCE_S = 0.01


def split_laps(
    con: duckdb.DuckDBPyConnection,
    registry: dict[str, ChannelInfo],
    time_base: TimeBase,
    config: Config | None = None,
) -> tuple[list[Lap], list[str]]:
    """Split a session into classified laps.

    Returns:
        `(laps, warnings)`. Warnings are user-facing Portuguese messages for
        anything that had to degrade - a missing channel disables one kind of
        classification without failing the load.
    """
    config = config or load_config()
    warnings: list[str] = []

    lap_events = events.try_read_event_series(con, registry, LAP_CHANNEL)
    if lap_events is None or lap_events.is_empty:
        logger.warning("No Lap channel: cannot split this session into laps")
        return [], [strings.WARN_NO_LAP_CHANNEL]

    boundaries = lap_events.times
    numbers = lap_events.values.astype(int)

    if len(boundaries) < 2:
        logger.warning("Only one lap marker: no complete lap was recorded")
        warnings.append(strings.WARN_SINGLE_LAP_MARKER)

    lap_times = events.try_read_event_series(con, registry, LAP_TIME_CHANNEL)
    sector1 = events.try_read_event_series(con, registry, SECTOR1_CHANNEL)
    sector2 = events.try_read_event_series(con, registry, SECTOR2_CHANNEL)

    pit_flags, pit_warning = _read_pit_state(con, registry, boundaries)
    if pit_warning:
        warnings.append(pit_warning)

    off_track, surface_warning = _off_track_fractions(
        con, registry, time_base, boundaries, config
    )
    if surface_warning:
        warnings.append(surface_warning)

    max_mismatch = float(config.get("laps.max_time_mismatch_s"))
    min_off_track = float(config.get("surfaces.min_off_track_fraction"))

    laps: list[Lap] = []
    for index in range(len(boundaries) - 1):
        t_start = float(boundaries[index])
        t_end = float(boundaries[index + 1])

        official = _value_at_boundary(lap_times, t_end)
        s_cumulative_1 = _value_at_boundary(sector1, t_end)
        s_cumulative_2 = _value_at_boundary(sector2, t_end)

        flags = _classify(
            official=official,
            measured=t_end - t_start,
            max_mismatch=max_mismatch,
            off_track_fraction=off_track[index],
            min_off_track=min_off_track,
            pit_flags=pit_flags[index],
        )

        laps.append(Lap(
            index=index,
            number=int(numbers[index]),
            t_start=t_start,
            t_end=t_end,
            official_time_s=official,
            sector_times_s=_sector_durations(
                s_cumulative_1, s_cumulative_2, official
            ),
            flags=flags,
            off_track_fraction=off_track[index],
        ))

    # The recording continues past the final crossing, so the tail is a real but
    # incomplete lap. Included and flagged rather than dropped: it still holds
    # usable telemetry, it just cannot be timed.
    tail_start = float(boundaries[-1])
    if time_base.t_end - tail_start > 0:
        laps.append(Lap(
            index=len(boundaries) - 1,
            number=int(numbers[-1]),
            t_start=tail_start,
            t_end=time_base.t_end,
            official_time_s=None,
            flags=frozenset({LapFlag.PARTIAL}),
        ))

    logger.info(
        "Split session into %d laps (%d comparable)",
        len(laps), sum(lap.is_comparable for lap in laps),
    )
    return laps, warnings


def _classify(
    *,
    official: float | None,
    measured: float,
    max_mismatch: float,
    off_track_fraction: float,
    min_off_track: float,
    pit_flags: frozenset[LapFlag],
) -> frozenset[LapFlag]:
    """Decide a lap's flags.

    The ordering of the rules matters. A lap whose recording is incomplete is
    partial regardless of what the game reported, because a truncated recording
    cannot be compared against anything.
    """
    flags: set[LapFlag] = set(pit_flags)

    if official is None:
        # No `Lap Time` event closed this lap. Seen in qualifying, where the
        # out lap gets no time at all.
        flags.add(LapFlag.PARTIAL)
    elif official == 0.0:
        # The game's own verdict on track limits. Nothing in the telemetry
        # reproduces the ruling, so it is taken as authoritative.
        flags.add(LapFlag.INVALIDATED)
    elif abs(measured - official) > max_mismatch:
        # The crossings are further apart than the lap actually took: recording
        # started partway through. This is how the first lap of every session
        # identifies itself.
        flags.add(LapFlag.PARTIAL)
    else:
        flags.add(LapFlag.VALID)

    if off_track_fraction >= min_off_track:
        flags.add(LapFlag.OFF_TRACK)

    return frozenset(flags)


def _sector_durations(
    cumulative_1: float | None,
    cumulative_2: float | None,
    lap_time: float | None,
) -> tuple[float | None, float | None, float | None]:
    """Convert the cumulative sector marks into three durations.

    `Last Sector1` is the elapsed time at the first split and `Last Sector2` the
    elapsed time at the second, both measured from the start of the lap. The
    durations are therefore S1, S2-S1 and LapTime-S2.

    A zero is the game's "not set" marker, the same convention it uses for an
    invalidated lap time, so zeros become None rather than a 0.0 s sector.
    """
    first = cumulative_1 if cumulative_1 else None
    second = cumulative_2 if cumulative_2 else None
    total = lap_time if lap_time else None

    s1 = first
    s2 = second - first if (second is not None and first is not None) else None
    s3 = total - second if (total is not None and second is not None) else None
    return (s1, s2, s3)


def _value_at_boundary(
    series: events.EventSeries | None,
    boundary_ts: float,
) -> float | None:
    """Read the value an event channel reported *at* a lap boundary.

    Deliberately not a forward fill. `Lap Time` reports the completed lap only
    at the crossing itself; carrying that value forward would attribute the
    previous lap's time to the next one. So the event has to sit on the
    boundary, within the tolerance that covers the files' differing rounding.
    """
    if series is None or series.is_empty or series.values.ndim != 1:
        return None

    position = int(np.argmin(np.abs(series.times - boundary_ts)))
    if abs(series.times[position] - boundary_ts) > _TS_MATCH_TOLERANCE_S:
        return None
    return float(series.values[position])


def _read_pit_state(
    con: duckdb.DuckDBPyConnection,
    registry: dict[str, ChannelInfo],
    boundaries: np.ndarray,
) -> tuple[list[frozenset[LapFlag]], str | None]:
    """Classify pit involvement per lap, degrading when the channel is absent.

    A constant `In Pits` is the common case in a race the driver finished
    without stopping. That is not a failure: there is simply nothing to detect,
    and the session is one stint. It is logged at info level rather than warned
    about, because warning about it in every race would train the user to
    ignore warnings.
    """
    n_laps = max(len(boundaries) - 1, 0)
    empty = [frozenset[LapFlag]()] * n_laps

    pits = events.try_read_event_series(con, registry, IN_PITS_CHANNEL)
    if pits is None or pits.is_empty:
        logger.warning("In Pits not recorded; in/out laps cannot be identified")
        return empty, strings.WARN_NO_PIT_CHANNEL

    if pits.is_constant:
        logger.info(
            "In Pits never changed over the session; treating it as one stint"
        )
        # Still classify: a session recorded entirely inside the pit lane would
        # be constant at 1, which every lap should be flagged for.
        if float(pits.values[0]) == 0.0:
            return empty, None

    return _pit_flags_per_lap(pits, boundaries), None


def _pit_flags_per_lap(
    pits: events.EventSeries,
    boundaries: np.ndarray,
) -> list[frozenset[LapFlag]]:
    """Work out which laps involve the pit lane.

    `In Pits` is 1 while the car is in the pit lane. A lap containing a 1 -> 0
    transition is an out lap, one containing 0 -> 1 is an in lap, and any lap
    holding a 1 at any point touched the pits.
    """
    exits = pits.transitions(0.0)
    entries = pits.transitions(1.0)

    flags: list[frozenset[LapFlag]] = []
    for index in range(len(boundaries) - 1):
        t_start, t_end = boundaries[index], boundaries[index + 1]
        lap_flags: set[LapFlag] = set()

        # A transition at the very start of the recording is not a pit event,
        # it is the channel reporting its initial state.
        if np.any((exits > t_start) & (exits < t_end)):
            lap_flags.add(LapFlag.OUT_LAP)
        if np.any((entries > t_start) & (entries < t_end)):
            lap_flags.add(LapFlag.IN_LAP)

        # Sample the state through the lap rather than only at its edges: a
        # short pit visit could begin and end between two boundaries.
        probe = np.linspace(t_start, t_end, 50)
        state = pits.value_at(probe)
        if np.nanmax(state, initial=0.0) > 0.0:
            lap_flags.add(LapFlag.IN_PITS)

        flags.append(frozenset(lap_flags))

    return flags


def _off_track_fractions(
    con: duckdb.DuckDBPyConnection,
    registry: dict[str, ChannelInfo],
    time_base: TimeBase,
    boundaries: np.ndarray,
    config: Config,
) -> tuple[list[float], str | None]:
    """Fraction of each lap's wheel-samples spent on grass, dirt or gravel.

    `SurfaceTypes` is a continuous per-wheel channel of integer codes at 5 Hz,
    so its sample times come from the time base like any other continuous
    channel. The codes were identified empirically - see `config/defaults.toml`.

    This is reported, never used to invalidate a lap. Measured across two full
    race sessions the two do not agree: a Monza lap with a near-stationary
    excursion onto grass was still rated valid by the game, while laps with no
    off-track sample at all were invalidated. Track limits are about kerbs and
    white lines, which no channel in this file records.
    """
    n_laps = max(len(boundaries) - 1, 0)
    info = registry.get(SURFACE_CHANNEL)
    if info is None:
        logger.info("SurfaceTypes not recorded; off-track detection disabled")
        return [0.0] * n_laps, strings.WARN_NO_SURFACE_CHANNEL

    from lmu_telemetry.ingest import channel_registry

    codes = channel_registry.read_channel(con, registry, SURFACE_CHANNEL)
    times = sample_times(len(codes), time_base)
    off_track_codes = set(config.get("surfaces.off_track_codes"))

    is_off = np.isin(codes.astype(int), list(off_track_codes))

    fractions: list[float] = []
    for index in range(n_laps):
        window = (times >= boundaries[index]) & (times < boundaries[index + 1])
        wheel_samples = int(window.sum()) * codes.shape[1]
        fractions.append(
            float(is_off[window].sum() / wheel_samples) if wheel_samples else 0.0
        )
    return fractions, None
