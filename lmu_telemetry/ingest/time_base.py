"""Reconstruct, validate and correct the session's time base.

Continuous channels carry no timestamp. Time is implicit in the row index:

    t[i] = t0 + i / frequency

Two facts established by inspecting real session files shape this module.

**The declared frequency is not trustworthy.** `channelsList.frequency` is an
INTEGER column, so a channel whose true rate is not a whole number is stored
truncated. Two channels declared at 7 Hz actually run at 7.017 Hz. The rate is
therefore derived from the data instead:

    f = (n_samples - 1) / span

**`GPS Time` is a real clock on the same timeline as everything else.** It is
recorded as an ordinary continuous channel at 100 Hz, and event `ts` values
share its origin exactly (both start at 26.5125 s in the Le Mans race session
inspected). That makes it the reference against which the index-derived time
can be checked.

Why the check is mandatory rather than a nicety: if the game stalls or pauses
during recording, index and time stop corresponding. Nothing raises an error -
the arrays are still the right length and full of plausible numbers - but every
lap comparison built on them is quietly wrong. `GPS Time` is the only way to
see it happen.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import duckdb
import numpy as np

from lmu_telemetry.core.config import Config, load_config
from lmu_telemetry.core.errors import TimeBaseError
from lmu_telemetry.ingest import duckdb_reader
from lmu_telemetry.ingest.channel_registry import (
    VALUE_COLUMN,
    ChannelInfo,
    continuous_channels,
)
from lmu_telemetry.logging_config import get_logger
from lmu_telemetry.ui import strings

logger = get_logger(__name__)

#: Channel carrying the reference clock.
REFERENCE_CLOCK_CHANNEL = "GPS Time"


class TimeBaseSource(str, Enum):
    """How sample times are produced."""

    #: `GPS Time` was present, uniform, and agreed with the index-derived time.
    #: Sample times are computed as a uniform ramp - the normal case.
    UNIFORM = "uniform"

    #: `GPS Time` was present but not uniform: the game stalled during
    #: recording. Sample times are read from the clock itself.
    GPS_CORRECTED = "gps_corrected"

    #: No usable `GPS Time`. The index-derived time is used unvalidated, and
    #: the user is warned that it cannot be trusted.
    UNVALIDATED = "unvalidated"


@dataclass(frozen=True, slots=True)
class TimeBase:
    """The session's clock, and how much it can be trusted.

    Attributes:
        t0: Time of the first sample, in the session's own clock. Not zero:
            recording starts partway into the session, so `GPS Time` begins at
            whatever the session clock reads then. Keeping the native origin
            means event `ts` values need no shifting.
        span_s: Time from the first sample to the last.
        source: How sample times are produced. See `TimeBaseSource`.
        max_drift_s: Largest disagreement found between the index-derived time
            and the reference clock.
        reference_times: The clock's own samples, kept only when a correction
            was needed.
        warnings: User-facing messages, already in Portuguese, to surface in
            the interface.
    """

    t0: float
    span_s: float
    source: TimeBaseSource
    max_drift_s: float = 0.0
    reference_times: np.ndarray | None = field(default=None, repr=False)
    warnings: tuple[str, ...] = ()

    @property
    def t_end(self) -> float:
        return self.t0 + self.span_s

    @property
    def was_corrected(self) -> bool:
        return self.source is TimeBaseSource.GPS_CORRECTED

    @property
    def is_validated(self) -> bool:
        return self.source is not TimeBaseSource.UNVALIDATED


def sample_times(n_samples: int, time_base: TimeBase) -> np.ndarray:
    """Return the sample times of a continuous channel with `n_samples` rows.

    All continuous channels describe the same recording, so a channel with `n`
    samples has them spread evenly across the session's span. That is the
    definition used here, rather than the declared frequency:

        t[i] = t0 + i * span / (n - 1)

    which is equivalent to `t[i] = t0 + i / f` with `f = (n-1)/span`, the
    empirical rate. It sidesteps the truncated INTEGER frequency entirely.

    When the time base was corrected, the ramp is replaced by a lookup into the
    reference clock at the same relative position, so a stall shifts every
    channel consistently.

    Args:
        n_samples: Number of rows in the channel's table.
        time_base: The session time base.

    Returns:
        Array of shape `(n_samples,)`, float64. Timestamps accumulate over a
        whole session, and float32 would quantise them to about a millisecond
        after an hour of running.
    """
    if n_samples <= 0:
        return np.empty(0, dtype=np.float64)
    if n_samples == 1:
        return np.array([time_base.t0], dtype=np.float64)

    positions = np.arange(n_samples, dtype=np.float64) / (n_samples - 1)

    if time_base.source is TimeBaseSource.GPS_CORRECTED:
        reference = time_base.reference_times
        assert reference is not None  # guaranteed by build_time_base
        # Map relative position -> index into the clock -> real time. Channels
        # stop producing samples while the game is frozen just as the clock
        # does, so equal relative positions correspond to equal real times.
        clock_index = positions * (len(reference) - 1)
        return np.interp(clock_index, np.arange(len(reference)), reference)

    return time_base.t0 + positions * time_base.span_s


def effective_frequency(n_samples: int, time_base: TimeBase) -> float:
    """Empirical sample rate of a channel with `n_samples` rows, in Hz."""
    if n_samples < 2 or time_base.span_s <= 0:
        return float("nan")
    return (n_samples - 1) / time_base.span_s


def build_time_base(
    con: duckdb.DuckDBPyConnection,
    registry: dict[str, ChannelInfo],
    config: Config | None = None,
) -> TimeBase:
    """Build the session time base and validate it against `GPS Time`.

    Raises:
        TimeBaseError: No continuous channel has enough samples to establish
            any timeline at all.
    """
    config = config or load_config()
    max_drift_s = float(config.get("ingest.time_base.max_drift_s"))
    min_gps_samples = int(config.get("ingest.time_base.min_gps_samples"))

    clock = registry.get(REFERENCE_CLOCK_CHANNEL)

    if clock is None or clock.n_samples < min_gps_samples:
        return _unvalidated_time_base(registry)

    reference = duckdb_reader.read_columns(
        con, clock.name, (VALUE_COLUMN,), dtype=np.float64
    )
    finite = reference[np.isfinite(reference)]
    if finite.size < min_gps_samples:
        logger.warning("GPS Time has too few usable samples; time base unvalidated")
        return _unvalidated_time_base(registry)

    t0 = float(finite[0])
    span = float(finite[-1] - finite[0])
    if span <= 0:
        logger.warning("GPS Time spans no time; time base unvalidated")
        return _unvalidated_time_base(registry)

    # The comparison. A uniform ramp over the clock's own sample count is what
    # the index-derived time would produce; the difference against the clock's
    # real readings is the drift.
    uniform = t0 + np.arange(finite.size, dtype=np.float64) * span / (finite.size - 1)
    drift = np.abs(finite - uniform)
    observed_drift = float(drift.max())

    n_backwards = int((np.diff(finite) < 0).sum())
    if n_backwards:
        logger.warning(
            "GPS Time is not monotonic (%d backward steps); using it as a "
            "reference anyway, but the recording is suspect",
            n_backwards,
        )

    if observed_drift <= max_drift_s:
        logger.info(
            "Time base validated against GPS Time: max drift %.4f s over %.1f s",
            observed_drift, span,
        )
        return TimeBase(
            t0=t0,
            span_s=span,
            source=TimeBaseSource.UNIFORM,
            max_drift_s=observed_drift,
        )

    # Past tolerance the index no longer maps linearly to time. Fall back to
    # reading the clock directly, and say so - loudly, in the interface.
    warning = strings.WARN_TIME_BASE_DRIFT.format(drift=observed_drift)
    logger.warning(
        "Time base drifted %.4f s (tolerance %.4f s); corrected from GPS Time",
        observed_drift, max_drift_s,
    )
    return TimeBase(
        t0=t0,
        span_s=span,
        source=TimeBaseSource.GPS_CORRECTED,
        max_drift_s=observed_drift,
        reference_times=finite,
        warnings=(warning,),
    )


def _unvalidated_time_base(registry: dict[str, ChannelInfo]) -> TimeBase:
    """Build a time base without a reference clock.

    The declared frequency is all there is, so the longest continuous channel
    defines the span. Every downstream result stays usable, but the user is told
    that a stall during recording would be invisible.
    """
    candidates = [
        info for info in continuous_channels(registry)
        if info.has_usable_frequency and info.n_samples > 1
    ]
    if not candidates:
        raise TimeBaseError(
            "No continuous channel with a usable frequency: cannot establish a "
            "time base for this session."
        )

    longest = max(candidates, key=lambda info: info.n_samples)
    logger.warning(
        "No usable GPS Time; time base derived from %r and left unvalidated",
        longest.name,
    )
    return TimeBase(
        t0=0.0,
        span_s=longest.implicit_span_s,
        source=TimeBaseSource.UNVALIDATED,
        max_drift_s=float("nan"),
        warnings=(strings.WARN_TIME_BASE_NO_GPS,),
    )


def common_grid(time_base: TimeBase, config: Config | None = None) -> np.ndarray:
    """Build the uniform time grid every channel is resampled onto.

    100 Hz by default, which is at or above the fastest channel in the file, so
    resampling only ever interpolates a slow channel up - it never has to
    decimate a fast one and lose detail.
    """
    config = config or load_config()
    target_hz = float(config.get("ingest.target_hz"))
    n_points = int(np.floor(time_base.span_s * target_hz)) + 1
    return time_base.t0 + np.arange(n_points, dtype=np.float64) / target_hz


def resample_to_grid(
    values: np.ndarray,
    source_times: np.ndarray,
    grid: np.ndarray,
    *,
    discrete: bool,
) -> np.ndarray:
    """Put one channel onto the common time grid.

    Args:
        values: Shape `(n,)` or `(n, 4)`.
        source_times: Shape `(n,)`, the channel's own sample times.
        grid: Target time grid.
        discrete: Forward-fill instead of interpolating. Required for gears,
            flags, tyre compounds, surface types and traction control state -
            interpolating them would invent a gear 3.5 and a surface halfway
            between asphalt and kerb.

    Returns:
        Shape `(len(grid),)` or `(len(grid), 4)`.
    """
    if values.ndim == 2:
        columns = [
            resample_to_grid(values[:, i], source_times, grid, discrete=discrete)
            for i in range(values.shape[1])
        ]
        return np.column_stack(columns)

    if source_times.size == 0:
        return np.full(grid.shape, np.nan)

    if discrete:
        return step_interpolate(values, source_times, grid)

    # np.interp clamps outside the source range rather than extrapolating,
    # which is what we want: inventing values beyond the recording would be
    # worse than repeating the edge sample.
    return np.interp(grid, source_times, values)


def step_interpolate(
    values: np.ndarray,
    source_times: np.ndarray,
    grid: np.ndarray,
) -> np.ndarray:
    """Zero-order hold: each grid point takes the last value at or before it.

    Grid points before the first sample have no defined value and become NaN,
    rather than silently borrowing the first sample and inventing history.
    """
    indices = np.searchsorted(source_times, grid, side="right") - 1
    before_start = indices < 0
    indices = np.clip(indices, 0, len(values) - 1)

    result = values[indices].astype(np.float64, copy=True)
    result[before_start] = np.nan
    return result
