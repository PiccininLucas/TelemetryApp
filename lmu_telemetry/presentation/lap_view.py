"""What one lap looks like on screen, worked out without a widget.

Opening a lap is a chain of decisions: which lap it is compared against, whether
that comparison means anything (same circuit? same car?), the delta between
them, the corners, the ideal lap, the stint, the map and the friction circle.
None of that needs a window, and kept in one it could only be tested by opening
one. So the chain lives here and ends in a `LapView`: plain values, one per
panel, which the window hands out and nothing more.

The window's only remaining questions are *where* each figure goes, never what
it is.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

from lmu_telemetry.application import pipeline
from lmu_telemetry.domain.analysis.delta import DeltaResult
from lmu_telemetry.domain.analysis.ideal_lap import IdealLap
from lmu_telemetry.domain.models import Lap
from lmu_telemetry.presentation.chart_panel import LapTrace
from lmu_telemetry.presentation.lap_list import best_lap, best_sectors
from lmu_telemetry.presentation.session_browser import LapSelection
from lmu_telemetry.presentation.session_header import SectorFigure, SessionSummary
from lmu_telemetry.presentation.session_state import (
    ComparisonMode, CurrentView, OpenSession, SessionPool,
)
from lmu_telemetry.shared import strings
from lmu_telemetry.shared.errors import TelemetryError
from lmu_telemetry.shared.formatting import format_gap, format_lap_time
from lmu_telemetry.shared.logging_config import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class MapFigure:
    """The track map's path, coloured both ways, and the dead-reckoned overlay."""

    x_m: np.ndarray
    y_m: np.ndarray
    grid_m: np.ndarray
    pedal_states: np.ndarray
    #: Where time moved against the reference; None without a comparison.
    loss_classes: np.ndarray | None
    caption: str
    #: The path integrated from speed and yaw, aligned onto the GPS one - the
    #: check that the GPS trace can be trusted. None when it cannot be built.
    integrated: tuple[np.ndarray, np.ndarray] | None


@dataclass(frozen=True, slots=True)
class FrictionFigure:
    """What the g-g diagram draws."""

    envelope: object
    lateral_g: np.ndarray
    longitudinal_g: np.ndarray
    grid_m: np.ndarray
    transition_quality: object


@dataclass(frozen=True, slots=True)
class LapFigures:
    """Everything drawn for a lap that could be analysed."""

    #: What an export reads: recorded rather than re-derived, see `CurrentView`.
    current: CurrentView
    primary_trace: LapTrace
    benchmark_trace: LapTrace | None
    #: `(apex distance, short label)` per corner, for the traces and the map.
    corner_marks: tuple[tuple[float, str], ...]
    #: Where the ideal lap joins one lap to the next; only in the ideal mode.
    seams: tuple[float, ...]
    ideal_summary: str
    stints: tuple
    #: The stint the lap belongs to, so the consistency panel opens on the run
    #: the driver is asking about.
    stint_index: int
    #: The reference's row in this session's lap list; None when it is the
    #: ideal lap or a lap of another session.
    reference_index: int | None
    summary: SessionSummary
    track_map: MapFigure | None
    friction: FrictionFigure | None
    #: The resting line of the status bar.
    status: str

    @property
    def comparing(self) -> bool:
        """Whether a second trace is drawn - a lap or the ideal lap."""
        return self.benchmark_trace is not None

    @property
    def has_benchmark_lap(self) -> bool:
        """Whether the comparison is against a real lap (not the ideal one)."""
        return self.current.benchmark is not None


@dataclass(frozen=True, slots=True)
class LapView:
    """A lap as the window shows it."""

    selection: LapSelection
    #: Every lap of the lap's session, for the lap list - shown even when this
    #: lap cannot be drawn, because it is how the user gets to one that can.
    laps: tuple[Lap, ...]
    #: Things the user must be told: a corrected clock, a refused comparison.
    notes: tuple[str, ...]
    #: None when the lap has too little data to analyse.
    figures: LapFigures | None


def compose(
    sessions: SessionPool,
    selection: LapSelection,
    mode: ComparisonMode,
    pinned: LapSelection | None,
) -> LapView:
    """Work out everything shown for `selection`.

    Raises:
        TelemetryError: when the lap's own session cannot be opened. A
            reference that cannot be opened is not an error: the lap is shown
            on its own.
    """
    opened = sessions.get(selection)
    laps = tuple(opened.session.laps)
    # Before analysing: a session whose clock was corrected must say so whether
    # or not this particular lap can be drawn.
    notes: list[str] = list(opened.session.warnings)

    primary = opened.analysis_for(selection.lap_index)
    if primary is None:
        return LapView(selection, laps, tuple(notes), None)

    # The whole session is analysed either way: it costs about 16 ms per lap,
    # and it is what the corner table's "what is this corner worth" column is
    # computed from. Cached on the open session, so this is paid once per file
    # rather than once per lap viewed.
    analysis = opened.session_analysis()
    ideal = analysis.ideal

    benchmark: pipeline.LapAnalysis | None = None
    benchmark_selection: LapSelection | None = None
    benchmark_trace: LapTrace | None = None
    delta: DeltaResult | None = None

    if mode is ComparisonMode.IDEAL:
        if ideal is None:
            notes.append(strings.IDEAL_UNAVAILABLE)
        else:
            delta = pipeline.delta_against_ideal(ideal, primary)
            benchmark_trace = LapTrace(
                label=strings.CHART_LEGEND_IDEAL.format(
                    time=format_lap_time(ideal.total_time_s),
                    gap=format_gap(delta.final_delta_s),
                ),
                grid_m=ideal.grid_m,
                elapsed_s=ideal.elapsed_s,
                key=strings.CHART_KEY_IDEAL,
                # Only speed is stitched: the ideal lap has no pedal or steering
                # trace, because no one ever drove it. Showing an invented one
                # would be the first lie in the application.
                channels={"Ground Speed": ideal.speed_ms},
            )
    else:
        benchmark, benchmark_selection = _load_benchmark(
            sessions, opened, selection, mode, pinned, notes
        )
        if benchmark is not None:
            delta = pipeline.delta_between(benchmark, primary)
            benchmark_trace = _trace(
                strings.CHART_LEGEND_BENCHMARK.format(
                    number=benchmark_selection.lap_number,
                    time=format_lap_time(benchmark.time_s),
                    gap=format_gap(delta.final_delta_s),
                ),
                benchmark,
                key=strings.CHART_KEY_BENCHMARK.format(
                    number=benchmark_selection.lap_number),
            )

    primary_label = strings.CHART_LEGEND_PRIMARY.format(
        number=selection.lap_number, time=format_lap_time(primary.time_s)
    )
    corner_rows = pipeline.corner_rows(primary, benchmark, ideal)
    stint = analysis.stint_of(selection.lap_index)

    current = CurrentView(
        selection=selection,
        primary=primary,
        primary_label=primary_label,
        benchmark=benchmark,
        benchmark_label="" if benchmark_trace is None else benchmark_trace.label,
        benchmark_summary=benchmark_summary(benchmark, benchmark_selection, ideal, mode),
        delta=delta,
        ideal=ideal,
        corner_rows=corner_rows,
        consistency=None if stint is None else stint.report,
    )

    seams: tuple[float, ...] = ()
    if ideal is not None and mode is ComparisonMode.IDEAL:
        seams = tuple(seam.distance_m for seam in pipeline.significant_seams(ideal))

    # The reference is only marked in the lap list when it is a lap of this
    # session; a pinned lap from another day has no row there.
    reference_index = (
        benchmark_selection.lap_index
        if benchmark_selection is not None
        and benchmark_selection.session_id == selection.session_id
        else None
    )

    figures = LapFigures(
        current=current,
        primary_trace=_trace(primary_label, primary, key=strings.CHART_KEY_PRIMARY.format(
            number=selection.lap_number)),
        benchmark_trace=benchmark_trace,
        corner_marks=tuple(
            (corner.apex_distance_m, short_label(corner.label))
            for corner in primary.corners
        ),
        seams=seams,
        ideal_summary=ideal_summary(ideal),
        stints=tuple(analysis.stints),
        stint_index=0 if stint is None else stint.index,
        reference_index=reference_index,
        summary=session_summary(
            opened, selection, primary, benchmark, benchmark_selection, ideal,
            delta, mode,
        ),
        track_map=map_figure(primary, delta),
        friction=friction_figure(primary),
        status=status_text(selection, primary, benchmark_selection, delta),
    )
    return LapView(selection, laps, tuple(notes), figures)


# --------------------------------------------------------------------------- #
# The comparison
# --------------------------------------------------------------------------- #

def benchmark_selection_for(
    opened: OpenSession,
    selection: LapSelection,
    mode: ComparisonMode,
    pinned: LapSelection | None,
) -> LapSelection | None:
    """Which lap `selection` is compared against, or None.

    `opened` is the selection's own session, already open: the session-best
    lap is read from its lap list.
    """
    if mode is ComparisonMode.NONE or mode is ComparisonMode.IDEAL:
        return None

    if mode is ComparisonMode.PINNED:
        if pinned is None:
            return None
        if (pinned.session_id == selection.session_id
                and pinned.lap_index == selection.lap_index):
            return None
        return pinned

    best = opened.best_comparable_lap(exclude_index=selection.lap_index)
    if best is None:
        return None
    return LapSelection(
        session_id=selection.session_id,
        source_path=selection.source_path,
        lap_index=best.index,
        lap_number=best.number,
        track_name=selection.track_name,
        car_name=selection.car_name,
        time_s=best.time_s,
        is_comparable=True,
        session_started_at=selection.session_started_at,
        session_type_code=selection.session_type_code,
    )


def _load_benchmark(
    sessions: SessionPool,
    opened: OpenSession,
    selection: LapSelection,
    mode: ComparisonMode,
    pinned: LapSelection | None,
    notes: list[str],
) -> tuple[pipeline.LapAnalysis | None, LapSelection | None]:
    """The benchmark lap's analysis, refusing comparisons that cannot mean
    anything."""
    chosen = benchmark_selection_for(opened, selection, mode, pinned)
    if chosen is None:
        return None, None

    # A distance grid only compares two laps if they ran the same track.
    # 4 000 m into Monza and 4 000 m into Le Mans are different corners, and the
    # delta between them would be a number with no referent.
    if chosen.track_name != selection.track_name:
        notes.append(strings.WARN_COMPARE_DIFFERENT_TRACK.format(
            track_a=selection.track_name, track_b=chosen.track_name
        ))
        return None, None

    if (chosen.car_name or "?") != (selection.car_name or "?"):
        # Not refused: comparing two cars around one circuit is a legitimate
        # thing to want. Only flagged, because the delta then measures the car
        # as much as the driving.
        notes.append(strings.WARN_COMPARE_DIFFERENT_CAR.format(
            car_a=selection.car_name or "?", car_b=chosen.car_name or "?",
        ))

    try:
        reference_session = sessions.get(chosen)
    except TelemetryError as exc:
        logger.warning("Could not open the reference session: %s", exc)
        return None, None

    analysis = reference_session.analysis_for(chosen.lap_index)
    return (analysis, chosen) if analysis is not None else (None, None)


# --------------------------------------------------------------------------- #
# Figures
# --------------------------------------------------------------------------- #

def map_figure(
    primary: pipeline.LapAnalysis, delta: DeltaResult | None
) -> MapFigure | None:
    """The track map for a lap, or None when the lap has no usable GPS path."""
    gps, integrated = pipeline.track_paths(primary)
    if gps is None or not len(gps.x_m):
        return None

    caption = strings.MAP_EXTENT.format(
        width=gps.extent_m[0], height=gps.extent_m[1], closure=gps.closure_error_m,
    )
    overlay = None
    if integrated is not None:
        aligned = pipeline.align_paths(gps, integrated)
        overlay = (aligned.x_m, aligned.y_m)
        comparison = pipeline.compare_track_paths(gps, integrated)
        caption += "\n" + strings.MAP_INTEGRATED_ERROR.format(
            mean=comparison.mean_error_m, max=comparison.max_error_m
        )

    return MapFigure(
        x_m=gps.x_m,
        y_m=gps.y_m,
        grid_m=primary.grid_m,
        pedal_states=pipeline.pedal_states(primary),
        loss_classes=(None if delta is None
                      else pipeline.loss_classes_on(primary.grid_m, delta)),
        caption=caption,
        integrated=overlay,
    )


def friction_figure(primary: pipeline.LapAnalysis) -> FrictionFigure | None:
    """The g-g diagram for a lap, or None without a valid envelope."""
    envelope = pipeline.friction_envelope(primary)
    if envelope is None or not envelope.is_valid:
        return None
    return FrictionFigure(
        envelope=envelope,
        lateral_g=primary.lateral_g,
        longitudinal_g=primary.longitudinal_g,
        grid_m=primary.grid_m,
        transition_quality=pipeline.transition_quality(primary),
    )


def status_text(
    selection: LapSelection,
    primary: pipeline.LapAnalysis,
    benchmark_selection: LapSelection | None,
    delta: DeltaResult | None,
) -> str:
    """The status bar's resting line: the lap, and where it lost the most."""
    if delta is None:
        return strings.STATUS_LAP_LOADED.format(
            number=selection.lap_number,
            time=format_lap_time(primary.time_s),
            length=primary.length_m,
            n_corners=len(primary.corners),
        )
    reference = (
        strings.STATUS_REFERENCE_IDEAL if benchmark_selection is None
        else strings.STATUS_REFERENCE_LAP.format(number=benchmark_selection.lap_number)
    )
    return strings.STATUS_LAP_COMPARED.format(
        number=selection.lap_number,
        time=format_lap_time(primary.time_s),
        gap=format_gap(delta.final_delta_s),
        reference=reference,
        loss=format_gap(delta.worst_loss_s),
        loss_at=delta.worst_loss_distance_m,
    )


#: An official turn number as the corner label begins: T6, T4.1.
_OFFICIAL_NUMBER = re.compile(r"^T\d+(?:\.\d+)?$")


def short_label(label: str) -> str:
    """The form of a corner's label that fits on a map or above a trace.

    "T6 Hairpin" becomes "T6": sixteen full names on the map would cover the
    circuit, and the full name is one glance away in the corner card. A name
    the user gave, or a detector's "C4", is already short and stays whole.
    """
    first = label.split(" ", 1)[0]
    return first if _OFFICIAL_NUMBER.match(first) else label


def session_summary(
    opened: OpenSession,
    selection: LapSelection,
    primary: pipeline.LapAnalysis,
    benchmark: pipeline.LapAnalysis | None,
    benchmark_selection: LapSelection | None,
    ideal: IdealLap | None,
    delta: DeltaResult | None,
    mode: ComparisonMode,
) -> SessionSummary:
    """What the header shows for the lap on screen."""
    info = opened.session.info
    laps = opened.session.laps
    details = tuple(
        part for part in (
            selection.car_name or info.car_name, info.car_class,
            info.session_type_label, info.weather,
        )
        if part
    )

    reference = None
    if mode is ComparisonMode.IDEAL and ideal is not None and delta is not None:
        reference = strings.HEADER_REFERENCE_IDEAL.format(
            time=format_lap_time(ideal.total_time_s)
        )
    elif benchmark is not None and benchmark_selection is not None:
        reference = strings.HEADER_REFERENCE_LAP.format(
            number=benchmark_selection.lap_number,
            time=format_lap_time(benchmark.time_s),
        )

    lap = next((each for each in laps if each.index == selection.lap_index), None)
    own = lap.sector_times_s if lap is not None else (None, None, None)
    sectors = tuple(
        SectorFigure(time_s, best_s)
        for time_s, best_s in zip(own[:3], best_sectors(laps), strict=False)
    )
    best = best_lap(laps)

    return SessionSummary(
        track=selection.track_name,
        details=details,
        lap_number=selection.lap_number,
        lap_time_s=primary.time_s,
        reference=reference,
        delta_s=None if delta is None else delta.final_delta_s,
        sectors=sectors,
        best_lap_number=None if best is None else best.number,
        best_lap_time_s=None if best is None else best.time_s,
        ideal_time_s=None if ideal is None else ideal.total_time_s,
    )


def benchmark_summary(
    benchmark: pipeline.LapAnalysis | None,
    benchmark_selection: LapSelection | None,
    ideal: IdealLap | None,
    mode: ComparisonMode,
) -> str:
    """Name the reference plainly, for prose that states the gap separately."""
    if mode is ComparisonMode.IDEAL and ideal is not None:
        return f"{strings.STATUS_REFERENCE_IDEAL} · {format_lap_time(ideal.total_time_s)}"
    if benchmark is None or benchmark_selection is None:
        return ""
    return (
        f"{strings.STATUS_REFERENCE_LAP.format(number=benchmark_selection.lap_number)}"
        f" · {format_lap_time(benchmark.time_s)}"
    )


def ideal_summary(ideal: IdealLap | None) -> str:
    """The one-line verdict beside the corner table's heading.

    States how many laps contribute, because that is what says how optimistic
    the target is: one contributing lap means the ideal lap *is* a real lap and
    is therefore achievable; five means five different things went right on five
    different occasions.
    """
    if ideal is None:
        return strings.IDEAL_UNAVAILABLE
    gain = ideal.gain_over_best_real_s
    if gain is None or ideal.best_real_time_s is None:
        return ""
    return strings.IDEAL_SUMMARY.format(
        time=format_lap_time(ideal.total_time_s),
        gain=f"{gain:.3f}",
        best=format_lap_time(ideal.best_real_time_s),
        n_laps=ideal.n_contributing_laps,
    )


def _trace(label: str, analysis: pipeline.LapAnalysis, *, key: str = "") -> LapTrace:
    """Turn an analysed lap into what the chart draws.

    The chart layer takes numpy arrays and a label, nothing else - that is what
    lets it be tested without a session file.
    """
    return LapTrace(
        label=label,
        grid_m=analysis.grid_m,
        elapsed_s=analysis.elapsed_s,
        channels=analysis.channels,
        key=key,
    )
