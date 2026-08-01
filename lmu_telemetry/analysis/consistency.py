"""How repeatable the driver is, corner by corner, over a stint.

Lap times hide this. Two drivers with the same average lap time can be very
different: one repeats the same lap, the other alternates a good lap with a bad
one. Only the second has something easy to gain, and only a per-corner
measurement shows where.

For each corner, across the laps of a stint:

    standard deviation of the braking point       (metres)
    standard deviation of the minimum speed       (m/s, shown as km/h)
    standard deviation of the throttle point      (metres)

and an estimate of the time that dispersion costs.

**The ranking is the deliverable.** A driver cannot work on twelve corners at
once; they can work on the two worst.

Sample standard deviation (`ddof=1`) is used throughout, not the population
form: these laps are a sample of how the driver drives, not the entire
population of their laps.

This module takes numpy arrays and returns numbers. It imports nothing from the
rest of the application beyond the value objects.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from lmu_telemetry.core.models import Corner


@dataclass(frozen=True, slots=True)
class CornerConsistency:
    """Dispersion of one corner across the laps of a stint.

    Attributes:
        corner_index: Which corner.
        corner_label: Its name, or its number.
        apex_distance_m: Where it is, for ordering and for the chart.
        n_laps: How many laps contributed.
        braking_point_std_m: Spread of the braking point.
        minimum_speed_std_ms: Spread of the apex speed.
        throttle_point_std_m: Spread of the throttle resumption point.
        braking_points_m: The individual values, so a chart can show the points
            and not only the box - a drift across the stint and random scatter
            have the same standard deviation and very different causes.
        minimum_speeds_ms: Likewise.
        throttle_points_m: Likewise.
        estimated_time_lost_s: Time attributable to this dispersion.
    """

    corner_index: int
    corner_label: str
    apex_distance_m: float
    n_laps: int
    braking_point_std_m: float
    minimum_speed_std_ms: float
    throttle_point_std_m: float
    braking_points_m: tuple[float, ...]
    minimum_speeds_ms: tuple[float, ...]
    throttle_points_m: tuple[float, ...]
    estimated_time_lost_s: float

    @property
    def minimum_speed_std_kmh(self) -> float:
        """Apex speed spread in km/h, which is how a driver reads it."""
        return self.minimum_speed_std_ms * 3.6

    @property
    def has_trend(self) -> bool:
        """True when the braking point drifts steadily rather than scattering.

        A drift is a different problem from scatter: it usually means tyre or
        fuel state changing through the stint, not inconsistent driving.
        """
        return _has_trend(self.braking_points_m)


@dataclass(frozen=True, slots=True)
class ConsistencyReport:
    """Consistency across a stint, ranked worst first.

    Attributes:
        corners: Per-corner results, ordered by estimated time lost.
        lap_indices: Which laps were measured.
        excluded_lap_indices: Which were dropped, and why, by lap index.
        lap_time_std_s: Spread of the lap times themselves.
        median_lap_time_s: Median lap time of the measured laps.
    """

    corners: list[CornerConsistency]
    lap_indices: tuple[int, ...]
    excluded_lap_indices: dict[int, str]
    lap_time_std_s: float
    median_lap_time_s: float

    @property
    def total_estimated_gain_s(self) -> float:
        """Time available if every corner were driven to its own best."""
        return float(sum(c.estimated_time_lost_s for c in self.corners))

    def worst(self, n: int = 3) -> list[CornerConsistency]:
        """The `n` corners costing the most. What to work on next."""
        return self.corners[:n]


def select_laps(
    lap_times_s: dict[int, float],
    max_lap_time_excess: float = 0.05,
    min_laps: int = 3,
) -> tuple[list[int], dict[int, str]]:
    """Choose which laps of a stint to measure.

    A lap spoiled by traffic or a mistake says nothing about repeatability, and
    including it would attribute someone else's overtake to the driver's
    inconsistency. Laps slower than the median by more than the allowed excess
    are dropped.

    The median, not the mean: one very slow lap drags a mean upward and would
    then justify keeping itself.

    Args:
        lap_times_s: Lap index -> lap time. Callers pass only comparable laps.
        max_lap_time_excess: Allowed fraction above the median.
        min_laps: Below this many laps, dispersion is not meaningful.

    Returns:
        `(kept_lap_indices, excluded_with_reason)`.
    """
    if not lap_times_s:
        return [], {}

    times = np.array(list(lap_times_s.values()), dtype=np.float64)
    indices = list(lap_times_s.keys())
    median = float(np.median(times))
    ceiling = median * (1.0 + max_lap_time_excess)

    kept, excluded = [], {}
    for lap_index, time_s in zip(indices, times, strict=True):
        if time_s <= ceiling:
            kept.append(lap_index)
        else:
            excluded[lap_index] = (
                f"{time_s - median:+.3f} s acima da mediana"
            )

    if len(kept) < min_laps:
        return [], {
            **excluded,
            **{i: "poucas voltas no stint" for i in kept},
        }

    return kept, excluded


def _std(values: list[float]) -> float:
    """Sample standard deviation, or 0 when there is not enough to measure."""
    finite = [v for v in values if v is not None and np.isfinite(v)]
    if len(finite) < 2:
        return 0.0
    return float(np.std(finite, ddof=1))


def _has_trend(values: tuple[float, ...], threshold: float = 0.7) -> bool:
    """Whether a series drifts monotonically rather than scattering.

    Correlation of the values against lap order. A strong correlation means the
    braking point is moving steadily through the stint - tyre or fuel state -
    rather than the driver being erratic.
    """
    if len(values) < 4:
        return False
    order = np.arange(len(values), dtype=np.float64)
    series = np.asarray(values, dtype=np.float64)
    if np.std(series) == 0.0:
        return False
    return bool(abs(np.corrcoef(order, series)[0, 1]) >= threshold)


def time_lost_from_segment_times(segment_times_s: list[float]) -> float:
    """Time this corner costs per lap, measured rather than modelled.

    Each lap's time through the corner's own stretch of track is compared
    against the driver's own best through that stretch, and the mean shortfall
    is the answer:

        loss = mean(t_lap) - min(t_lap)

    This is what "the time available if every corner were driven to its own
    best" actually means, and it needs no model of how a speed deficit
    propagates down the following straight.

    An earlier version estimated the loss from apex speed as
    `L * (1/V - 1/V_best)`. On real data it produced 26 s of loss in a single
    corner of a 107 s lap, because the corner's window spans the whole stretch
    of track between its neighbours - about 1400 m at Monza - and the model
    assumed the speed deficit was carried over all of it. Measuring the time
    directly has no such failure mode.

    Returns:
        Mean seconds lost per lap, or 0 when there is nothing to compare.
    """
    times = np.array(
        [t for t in segment_times_s if t is not None and np.isfinite(t) and t > 0],
        dtype=np.float64,
    )
    if times.size < 2:
        return 0.0
    return float(times.mean() - times.min())


def estimate_time_lost_from_speed(
    minimum_speeds_ms: list[float],
    corner_length_m: float = 100.0,
) -> float:
    """Fallback estimate from apex speed alone, when segment times are absent.

    First-order: a speed deficit at the apex is carried over a representative
    length `L` of corner and exit,

        dt = L * (1/V_lap - 1/V_best)

    `L` is deliberately the corner itself, not the stretch to the next corner.
    It ignores the traction limit on exit and the fact that a slower apex
    sometimes buys a better exit line, so it is a rough indication and the
    measured form above is always preferred.

    Braking-point scatter is deliberately not added on top: a braking point that
    moves without changing apex speed means the driver adjusted successfully,
    and adding both terms would double-count one mistake.
    """
    speeds = np.array(
        [v for v in minimum_speeds_ms if v is not None and np.isfinite(v) and v > 0],
        dtype=np.float64,
    )
    if speeds.size < 2:
        return 0.0

    best = float(speeds.max())
    return float(np.mean(corner_length_m * (1.0 / speeds - 1.0 / best)))


def analyse(
    corners_per_lap: dict[int, list[Corner]],
    lap_times_s: dict[int, float],
    reference_corners: list[Corner],
    *,
    segment_times_s: dict[int, dict[int, float]] | None = None,
    max_lap_time_excess: float = 0.05,
    min_laps: int = 3,
    match_tolerance_m: float = 50.0,
) -> ConsistencyReport:
    """Measure per-corner consistency across a stint.

    Args:
        corners_per_lap: Lap index -> that lap's detected corners.
        lap_times_s: Lap index -> lap time, for lap selection.
        reference_corners: The corner set to report against, usually detected
            on the best lap. Corners are matched to it by apex distance so the
            same corner keeps the same identity on every lap.
        segment_times_s: Lap index -> corner index -> time through that corner's
            stretch of track. When given, the time lost is measured from these
            rather than estimated from apex speed, which is both exact and free
            of the model's failure modes.
        max_lap_time_excess: Allowed fraction above the median lap time.
        min_laps: Minimum laps for the result to mean anything.
        match_tolerance_m: How far an apex may move between laps.

    Returns:
        The report, ranked by time lost.
    """
    from lmu_telemetry.analysis.corners import match_corners

    kept, excluded = select_laps(lap_times_s, max_lap_time_excess, min_laps)
    kept = [i for i in kept if i in corners_per_lap]

    if not kept or not reference_corners:
        return ConsistencyReport(
            corners=[], lap_indices=tuple(kept), excluded_lap_indices=excluded,
            lap_time_std_s=0.0, median_lap_time_s=0.0,
        )

    # Gather each reference corner's measurements across the kept laps.
    braking: dict[int, list[float]] = {c.index: [] for c in reference_corners}
    speeds: dict[int, list[float]] = {c.index: [] for c in reference_corners}
    throttle: dict[int, list[float]] = {c.index: [] for c in reference_corners}

    for lap_index in kept:
        lap_corners = corners_per_lap[lap_index]
        matches = match_corners(lap_corners, reference_corners, match_tolerance_m)
        for local_index, reference_index in matches.items():
            corner = lap_corners[local_index]
            key = reference_corners[reference_index].index
            if corner.braking_distance_m is not None:
                braking[key].append(corner.braking_distance_m)
            if corner.throttle_distance_m is not None:
                throttle[key].append(corner.throttle_distance_m)
            speeds[key].append(corner.minimum_speed_ms)

    results = []
    for corner in reference_corners:
        key = corner.index

        if segment_times_s is not None:
            through = [
                segment_times_s[lap][key]
                for lap in kept
                if lap in segment_times_s and key in segment_times_s[lap]
            ]
            time_lost = time_lost_from_segment_times(through)
        else:
            # No measured times available: fall back to the speed model, over
            # the corner itself rather than the whole window between corners.
            time_lost = estimate_time_lost_from_speed(
                speeds[key],
                corner_length_m=min(
                    max(corner.end_distance_m - corner.start_distance_m, 1.0),
                    200.0,
                ),
            )

        results.append(CornerConsistency(
            corner_index=key,
            corner_label=corner.label,
            apex_distance_m=corner.apex_distance_m,
            n_laps=len(speeds[key]),
            braking_point_std_m=_std(braking[key]),
            minimum_speed_std_ms=_std(speeds[key]),
            throttle_point_std_m=_std(throttle[key]),
            braking_points_m=tuple(braking[key]),
            minimum_speeds_ms=tuple(speeds[key]),
            throttle_points_m=tuple(throttle[key]),
            estimated_time_lost_s=time_lost,
        ))

    results.sort(key=lambda c: c.estimated_time_lost_s, reverse=True)

    kept_times = [lap_times_s[i] for i in kept if i in lap_times_s]
    return ConsistencyReport(
        corners=results,
        lap_indices=tuple(kept),
        excluded_lap_indices=excluded,
        lap_time_std_s=_std(kept_times),
        median_lap_time_s=float(np.median(kept_times)) if kept_times else 0.0,
    )


def detect_stints(
    lap_indices: list[int],
    in_pits_per_lap: dict[int, bool],
) -> list[tuple[int, ...]]:
    """Split a session's laps into stints at every pit visit.

    A stint is a run of consecutive laps between two visits to the pit lane.

    When the driver never pitted, `In Pits` never changes and there is nothing
    to split on. That is the common case in a race finished without stopping,
    and the right answer is one stint containing everything - not zero stints.
    Returning nothing there would silently disable the consistency panel for
    most sessions.
    """
    stints: list[tuple[int, ...]] = []
    current: list[int] = []

    for lap_index in lap_indices:
        if in_pits_per_lap.get(lap_index, False):
            if current:
                stints.append(tuple(current))
                current = []
            continue
        current.append(lap_index)

    if current:
        stints.append(tuple(current))

    return stints
