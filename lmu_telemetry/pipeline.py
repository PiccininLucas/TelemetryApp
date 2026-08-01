"""Joining ingestion to analysis.

`analysis` may not import `ingest` - that is what lets every formula be tested
without the game installed. Something still has to put the two together, and
this is it: a module above both that may import either. The UI and the export
layer work through here rather than reaching into `ingest` themselves.

The per-lap pipeline, in order:

1. Slice the session's 100 Hz time grid to the lap's window.
2. Resample the channels the analysis needs onto that grid - linearly for
   continuous ones, held for discrete ones.
3. Rebuild distance by integrating speed, corrected to close on the lap length.
4. Resample everything again onto a 1 m distance grid, which is where every
   lap-to-lap comparison happens.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from lmu_telemetry.analysis import (
    consistency, corners, delta, distance, friction, ideal_lap, resample,
    trackmap,
)
from lmu_telemetry.analysis.corners import CornerDetectionSettings
from lmu_telemetry.core.config import Config, load_config
from lmu_telemetry.core.models import Corner, Lap
from lmu_telemetry.ingest import time_base
from lmu_telemetry.ingest.session_loader import Session
from lmu_telemetry.logging_config import get_logger

logger = get_logger(__name__)

#: Channels the analysis needs, and whether they must be held rather than
#: interpolated when resampled.
CONTINUOUS_CHANNELS = (
    "Ground Speed", "Brake Pos", "Throttle Pos", "Steering Pos", "Engine RPM",
    "Lap Dist", "GPS Latitude", "GPS Longitude",
)
DISCRETE_CHANNELS = ("Gear",)


@dataclass(slots=True)
class LapAnalysis:
    """One lap, reduced to the distance domain and measured.

    Attributes:
        lap: The lap this describes.
        grid_m: 1 m distance grid from the start of the lap.
        channels: Channel name -> values on `grid_m`.
        elapsed_s: Time since the lap started, on `grid_m`.
        reconstruction: Distance rebuilt from speed, with its correction.
        corners: Corners detected on this lap.
        lateral_g: Corrected lateral acceleration on `grid_m`.
        longitudinal_g: Corrected longitudinal acceleration on `grid_m`.
    """

    lap: Lap
    grid_m: np.ndarray
    channels: dict[str, np.ndarray]
    elapsed_s: np.ndarray
    reconstruction: distance.DistanceReconstruction
    corners: list[Corner] = field(default_factory=list)
    lateral_g: np.ndarray | None = None
    longitudinal_g: np.ndarray | None = None

    @property
    def speed_ms(self) -> np.ndarray:
        return self.channels["Ground Speed"]

    @property
    def length_m(self) -> float:
        return float(self.grid_m[-1]) if len(self.grid_m) else 0.0

    @property
    def time_s(self) -> float:
        return float(self.elapsed_s[-1]) if len(self.elapsed_s) else 0.0


@dataclass(slots=True)
class SessionAnalysis:
    """Every analysable lap of a session, plus what needs all of them at once."""

    laps: dict[int, LapAnalysis]
    reference_corners: list[Corner]
    ideal: ideal_lap.IdealLap | None
    consistency: consistency.ConsistencyReport | None
    best_lap_index: int | None

    @property
    def best(self) -> LapAnalysis | None:
        if self.best_lap_index is None:
            return None
        return self.laps.get(self.best_lap_index)


def _settings_from(config: Config) -> CornerDetectionSettings:
    section = config.section("analysis").get("corners", {})
    return CornerDetectionSettings(**section)


def analyse_lap(
    session: Session,
    lap: Lap,
    track_length_m: float | None = None,
    config: Config | None = None,
) -> LapAnalysis | None:
    """Reduce one lap to the distance domain and measure its corners.

    Returns:
        The analysis, or None when the lap lacks the channels it needs. A lap
        without `Ground Speed` cannot have its distance rebuilt, and there is
        nothing to fall back to.
    """
    config = config or load_config()

    if not session.has("Ground Speed"):
        logger.warning("Lap %d: no Ground Speed channel", lap.number)
        return None

    times = _lap_time_grid(session, lap, config)
    if times.size < 10:
        logger.info("Lap %d: too short to analyse", lap.number)
        return None

    on_time_grid = _channels_on(session, times)
    speed_ms = on_time_grid["Ground Speed"]

    reference_length = track_length_m
    if reference_length is None and "Lap Dist" in on_time_grid:
        reference_length = distance.lap_length_from_channel(on_time_grid["Lap Dist"])

    reconstruction = distance.reconstruct(
        speed_ms, times, reference_length,
        min_scale_factor=float(config.get("analysis.distance.min_scale_factor")),
        max_scale_factor=float(config.get("analysis.distance.max_scale_factor")),
    )

    step_m = float(config.get("analysis.resample.step_m"))
    grid_m = resample.distance_grid(reconstruction.length_m, step_m)
    if grid_m.size < 10:
        return None

    on_distance = {
        name: resample.resample(
            values, reconstruction.corrected_m, grid_m,
            discrete=name in DISCRETE_CHANNELS,
        )
        for name, values in on_time_grid.items()
    }
    elapsed = delta.elapsed_time(reconstruction.corrected_m, times, grid_m)

    lateral, longitudinal = _accelerations_on(session, times, reconstruction, grid_m)

    detected = corners.detect_corners(
        on_distance["Ground Speed"],
        grid_m,
        on_distance.get("Brake Pos", np.zeros_like(grid_m)),
        on_distance.get("Throttle Pos", np.zeros_like(grid_m)),
        _settings_from(config),
    )

    return LapAnalysis(
        lap=lap,
        grid_m=grid_m,
        channels=on_distance,
        elapsed_s=elapsed,
        reconstruction=reconstruction,
        corners=detected,
        lateral_g=lateral,
        longitudinal_g=longitudinal,
    )


def _lap_time_grid(session: Session, lap: Lap, config: Config) -> np.ndarray:
    """The session's common time grid, restricted to one lap."""
    target_hz = float(config.get("ingest.target_hz"))
    n_points = int(np.floor((lap.t_end - lap.t_start) * target_hz)) + 1
    return lap.t_start + np.arange(max(n_points, 0), dtype=np.float64) / target_hz


def _channels_on(session: Session, times: np.ndarray) -> dict[str, np.ndarray]:
    """Resample the analysis channels onto a time grid, in canonical units."""
    result: dict[str, np.ndarray] = {}

    for name in (*CONTINUOUS_CHANNELS, *DISCRETE_CHANNELS):
        if name not in session.registry:
            continue
        info = session.registry[name]
        values = session.channel(name)
        source_times = session.channel_times(name)
        result[name] = time_base.resample_to_grid(
            values, source_times, times,
            discrete=info.is_discrete or name in DISCRETE_CHANNELS,
        )

    return result


def _accelerations_on(
    session: Session,
    times: np.ndarray,
    reconstruction: distance.DistanceReconstruction,
    grid_m: np.ndarray,
) -> tuple[np.ndarray | None, np.ndarray | None]:
    """Corrected accelerations, on the distance grid.

    Uses `session.acceleration`, which undoes the file's swapped and negated
    G channels. Reading `G Force Lat` directly here would put longitudinal
    acceleration on the g-g diagram's lateral axis.
    """
    outputs = []
    for quantity in ("lateral", "longitudinal"):
        try:
            values = session.acceleration(quantity)
            source_times = session.acceleration_times(quantity)
        except Exception:  # noqa: BLE001 - a missing channel disables one feature
            outputs.append(None)
            continue
        on_time = time_base.resample_to_grid(
            values, source_times, times, discrete=False
        )
        outputs.append(
            resample.resample(on_time, reconstruction.corrected_m, grid_m)
        )
    return outputs[0], outputs[1]


def analyse_session(
    session: Session,
    track_length_m: float | None = None,
    config: Config | None = None,
    lap_indices: list[int] | None = None,
) -> SessionAnalysis:
    """Analyse every comparable lap of a session.

    Args:
        session: An open session.
        track_length_m: Known track length, used to correct each lap's distance.
        config: Configuration override.
        lap_indices: Restrict to these laps. Defaults to the comparable ones -
            a partial or pit-limited lap has no meaningful distance axis.
    """
    config = config or load_config()

    candidates = (
        [lap for lap in session.laps if lap.index in set(lap_indices)]
        if lap_indices is not None
        else session.comparable_laps
    )

    analysed: dict[int, LapAnalysis] = {}
    for lap in candidates:
        result = analyse_lap(session, lap, track_length_m, config)
        if result is not None:
            analysed[lap.index] = result

    if not analysed:
        return SessionAnalysis({}, [], None, None, None)

    best_index = min(analysed, key=lambda i: analysed[i].time_s)
    reference_corners = analysed[best_index].corners

    return SessionAnalysis(
        laps=analysed,
        reference_corners=reference_corners,
        ideal=_build_ideal(analysed, reference_corners, config),
        consistency=_build_consistency(analysed, reference_corners, config),
        best_lap_index=best_index,
    )


def _build_ideal(
    analysed: dict[int, LapAnalysis],
    reference_corners: list[Corner],
    config: Config,
) -> ideal_lap.IdealLap | None:
    """Stitch the ideal lap, after putting every lap on one shared grid."""
    if len(analysed) < 2:
        return None

    shortest = min(a.length_m for a in analysed.values())
    step_m = float(config.get("analysis.resample.step_m"))
    grid = resample.distance_grid(shortest, step_m)

    elapsed = {
        index: resample.resample(a.elapsed_s, a.grid_m, grid)
        for index, a in analysed.items()
    }
    speeds = {
        index: resample.resample(a.speed_ms, a.grid_m, grid)
        for index, a in analysed.items()
    }

    return ideal_lap.build_ideal_lap(
        elapsed, speeds, grid, reference_corners,
        float(config.get("analysis.ideal_lap.boundary_position")),
    )


def _corner_segment_times(
    analysed: dict[int, LapAnalysis],
    reference_corners: list[Corner],
) -> dict[int, dict[int, float]]:
    """Each lap's time through each corner's own stretch of track.

    Read straight off the elapsed-time curves, so the consistency report can
    measure the time a corner costs rather than model it from apex speed.
    """
    result: dict[int, dict[int, float]] = {}

    for lap_index, analysis in analysed.items():
        per_corner: dict[int, float] = {}
        for corner in reference_corners:
            start = float(
                np.interp(corner.start_distance_m, analysis.grid_m, analysis.elapsed_s)
            )
            end = float(
                np.interp(corner.end_distance_m, analysis.grid_m, analysis.elapsed_s)
            )
            if np.isfinite(start) and np.isfinite(end) and end > start:
                per_corner[corner.index] = end - start
        result[lap_index] = per_corner

    return result


def _build_consistency(
    analysed: dict[int, LapAnalysis],
    reference_corners: list[Corner],
    config: Config,
) -> consistency.ConsistencyReport | None:
    if not reference_corners:
        return None

    return consistency.analyse(
        {index: a.corners for index, a in analysed.items()},
        {index: a.time_s for index, a in analysed.items()},
        reference_corners,
        segment_times_s=_corner_segment_times(analysed, reference_corners),
        max_lap_time_excess=float(
            config.get("analysis.consistency.max_lap_time_excess")
        ),
        min_laps=int(config.get("analysis.consistency.min_laps")),
    )


def delta_between(
    reference: LapAnalysis,
    lap: LapAnalysis,
    config: Config | None = None,
) -> delta.DeltaResult:
    """Delta-t between two analysed laps.

    Both already carry an elapsed-time curve on their own distance grid, so the
    comparison only needs a shared grid - it must not go back to the time-domain
    arrays, which are a different length.

    The grid stops at the shorter lap: past that point one of them was never
    measured.
    """
    config = config or load_config()
    step_m = float(config.get("analysis.resample.step_m"))
    grid = resample.distance_grid(min(reference.length_m, lap.length_m), step_m)

    reference_elapsed = resample.resample(reference.elapsed_s, reference.grid_m, grid)
    lap_elapsed = resample.resample(lap.elapsed_s, lap.grid_m, grid)

    return delta.DeltaResult(
        grid_m=grid,
        delta_s=lap_elapsed - reference_elapsed,
        reference_time_s=reference_elapsed,
        lap_time_s=lap_elapsed,
    )


def delta_against_ideal(
    ideal: ideal_lap.IdealLap,
    lap: LapAnalysis,
) -> delta.DeltaResult:
    """Delta-t of a lap against the theoretical ideal lap.

    The ideal lap is stitched from segments and exists only as a curve, never as
    a lap with its own distance and time arrays.
    """
    return delta.delta_against_reference_curve(
        ideal.grid_m, ideal.elapsed_s, lap.grid_m, lap.elapsed_s
    )


def friction_envelope(
    analysis: LapAnalysis, config: Config | None = None
) -> friction.FrictionEnvelope | None:
    """The g-g envelope for one analysed lap."""
    if analysis.lateral_g is None or analysis.longitudinal_g is None:
        return None
    config = config or load_config()
    return friction.compute_envelope(
        analysis.lateral_g, analysis.longitudinal_g, analysis.speed_ms,
        float(config.get("analysis.friction.min_speed_ms")),
    )


def track_paths(
    analysis: LapAnalysis, config: Config | None = None
) -> tuple[trackmap.TrackPath | None, trackmap.TrackPath | None]:
    """The GPS-projected path and the independently integrated one.

    Returns `(gps, integrated)`, either of which may be None when its inputs are
    missing.
    """
    config = config or load_config()

    gps = None
    if {"GPS Latitude", "GPS Longitude"} <= analysis.channels.keys():
        gps = trackmap.project_gps(
            analysis.channels["GPS Latitude"],
            analysis.channels["GPS Longitude"],
            float(config.get("analysis.trackmap.earth_radius_m")),
        )

    integrated = None
    if analysis.lateral_g is not None:
        integrated = trackmap.reconstruct_from_lateral_g(
            analysis.lateral_g, analysis.speed_ms, analysis.elapsed_s,
            min_speed_ms=float(config.get("analysis.trackmap.min_speed_ms")),
        )

    return gps, integrated
