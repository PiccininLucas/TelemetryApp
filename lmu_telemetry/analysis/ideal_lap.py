"""The theoretical ideal lap: the best of every segment, stitched together.

The lap is cut into segments and, for each one, the fastest time any valid lap
achieved is taken. The sum is the ideal lap.

**Segment boundaries sit midway along the straight between one corner and the
next, never at an apex.** Putting a boundary at an apex would split a corner
across two segments, so the entry could be credited to one lap and the exit to
another - and since a corner is driven as one action, that would compare
fragments of it that never happened together.

**This lap is not physically guaranteed, and the code says so wherever it is
used.** Exit speed from one segment sets entry speed into the next, so a lap
that was quickest through segment 3 may have been quickest precisely because it
sacrificed the entry to segment 4. Stitching the best pieces produces a target
that is very likely optimistic. It is a target, not a record.

The consequence is visible: where two segments meet, the stitched speed trace
usually jumps, because the lap that owned the segment before was travelling at a
different speed from the lap that owns the segment after. **Those discontinuities
are reported so they can be drawn, not smoothed away** - smoothing them would
hide exactly the evidence that the lap is synthetic.

This module takes numpy arrays and returns numbers. It imports nothing from the
rest of the application beyond the `Corner` value object.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from lmu_telemetry.core.models import Corner


@dataclass(frozen=True, slots=True)
class Segment:
    """One stretch of the lap, owned by whichever lap was quickest through it.

    Attributes:
        index: Position around the lap.
        start_m: Where the segment begins.
        end_m: Where it ends.
        best_lap_index: Which lap was fastest here.
        best_time_s: That lap's time through the segment.
        times_s: Every lap's time through it, by lap index, for the spread.
        corner_index: The corner this segment contains, if any.
    """

    index: int
    start_m: float
    end_m: float
    best_lap_index: int
    best_time_s: float
    times_s: dict[int, float]
    corner_index: int | None = None

    @property
    def length_m(self) -> float:
        return self.end_m - self.start_m

    @property
    def spread_s(self) -> float:
        """Slowest minus fastest: how much this segment varies lap to lap."""
        if len(self.times_s) < 2:
            return 0.0
        values = list(self.times_s.values())
        return float(max(values) - min(values))


@dataclass(frozen=True, slots=True)
class Discontinuity:
    """A speed jump where two segments from different laps meet.

    Attributes:
        distance_m: Where the seam falls.
        speed_before_ms: Speed at the end of the preceding segment.
        speed_after_ms: Speed at the start of the following one.
        from_lap_index: Which lap owned the preceding segment.
        to_lap_index: Which lap owns the following one.
    """

    distance_m: float
    speed_before_ms: float
    speed_after_ms: float
    from_lap_index: int
    to_lap_index: int

    @property
    def jump_ms(self) -> float:
        """Signed size of the jump. A positive value means the stitched lap
        gains speed instantaneously, which no car can do."""
        return self.speed_after_ms - self.speed_before_ms


@dataclass(frozen=True, slots=True)
class IdealLap:
    """A lap assembled from the best segment of each contributing lap.

    Attributes:
        segments: The segments, in order.
        grid_m: Distance grid the stitched traces are on.
        elapsed_s: Cumulative time along the ideal lap.
        speed_ms: Stitched speed trace, discontinuous at the seams by nature.
        discontinuities: The seams where speed jumps.
        total_time_s: The ideal lap time.
        best_real_lap_index: Fastest lap actually driven.
        best_real_time_s: Its time.
    """

    segments: list[Segment]
    grid_m: np.ndarray
    elapsed_s: np.ndarray
    speed_ms: np.ndarray
    discontinuities: list[Discontinuity]
    total_time_s: float
    best_real_lap_index: int | None
    best_real_time_s: float | None

    #: Stated wherever the ideal lap is displayed or exported.
    CAVEAT = (
        "Stitched from the best segment of each lap. Exit speed from one segment "
        "conditions entry into the next, so this target is not guaranteed to be "
        "physically achievable - it is a target, not a record."
    )

    @property
    def gain_over_best_real_s(self) -> float | None:
        """How much the ideal lap is faster than the best real one."""
        if self.best_real_time_s is None:
            return None
        return self.best_real_time_s - self.total_time_s

    @property
    def n_contributing_laps(self) -> int:
        """How many different laps the ideal lap draws on.

        One means the ideal lap *is* a real lap and is therefore achievable. The
        more laps contribute, the more optimistic the target.
        """
        return len({segment.best_lap_index for segment in self.segments})


def segment_boundaries(
    corners: list[Corner],
    lap_length_m: float,
    boundary_position: float = 0.5,
) -> np.ndarray:
    """Place the segment boundaries between corners.

    Each boundary sits a fraction of the way along the straight from one
    corner's apex to the next - the middle by default. Never at an apex, so a
    corner's braking, apex and exit always stay in one segment.

    Args:
        corners: The lap's corners, ordered by distance.
        lap_length_m: Length of the lap.
        boundary_position: Where along the gap to cut, 0 to 1.

    Returns:
        Boundaries including 0 and `lap_length_m`, so there are
        `len(corners)` segments when corners are present.
    """
    if not corners:
        return np.array([0.0, lap_length_m])

    apexes = np.array([corner.apex_distance_m for corner in corners])
    interior = apexes[:-1] + (apexes[1:] - apexes[:-1]) * boundary_position
    return np.concatenate([[0.0], interior, [lap_length_m]])


def build_ideal_lap(
    lap_elapsed_s: dict[int, np.ndarray],
    lap_speed_ms: dict[int, np.ndarray],
    grid_m: np.ndarray,
    corners: list[Corner],
    boundary_position: float = 0.5,
) -> IdealLap | None:
    """Assemble the ideal lap from several laps already on one distance grid.

    Args:
        lap_elapsed_s: Lap index -> elapsed time at each grid distance.
        lap_speed_ms: Lap index -> speed at each grid distance.
        grid_m: The shared distance grid.
        corners: Corners of the lap, used to place segment boundaries.
        boundary_position: Where between apexes to cut.

    Returns:
        The ideal lap, or None when no lap was supplied.
    """
    if not lap_elapsed_s:
        return None

    grid_m = np.asarray(grid_m, dtype=np.float64)
    lap_length = float(grid_m[-1]) if grid_m.size else 0.0
    boundaries = segment_boundaries(corners, lap_length, boundary_position)
    edges = np.searchsorted(grid_m, boundaries).clip(0, len(grid_m) - 1)

    segments: list[Segment] = []
    for index in range(len(edges) - 1):
        start, end = int(edges[index]), int(edges[index + 1])
        if end <= start:
            continue

        # Time through a segment is the elapsed-time difference across it, which
        # removes whatever the lap had accumulated before reaching it.
        times = {
            lap_index: float(elapsed[end] - elapsed[start])
            for lap_index, elapsed in lap_elapsed_s.items()
            if np.isfinite(elapsed[end]) and np.isfinite(elapsed[start])
        }
        if not times:
            continue

        best_lap = min(times, key=times.__getitem__)
        segments.append(Segment(
            index=len(segments),
            start_m=float(grid_m[start]),
            end_m=float(grid_m[end]),
            best_lap_index=best_lap,
            best_time_s=times[best_lap],
            times_s=times,
            corner_index=index if index < len(corners) else None,
        ))

    if not segments:
        return None

    speed, elapsed, discontinuities = _stitch(
        segments, lap_speed_ms, grid_m, edges
    )

    real_times = {
        lap_index: float(elapsed_curve[-1])
        for lap_index, elapsed_curve in lap_elapsed_s.items()
        if np.isfinite(elapsed_curve[-1])
    }
    best_real = min(real_times, key=real_times.__getitem__) if real_times else None

    return IdealLap(
        segments=segments,
        grid_m=grid_m,
        elapsed_s=elapsed,
        speed_ms=speed,
        discontinuities=discontinuities,
        total_time_s=float(sum(segment.best_time_s for segment in segments)),
        best_real_lap_index=best_real,
        best_real_time_s=real_times.get(best_real) if best_real is not None else None,
    )


def _stitch(
    segments: list[Segment],
    lap_speed_ms: dict[int, np.ndarray],
    grid_m: np.ndarray,
    edges: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, list[Discontinuity]]:
    """Splice the winning laps' speed traces and accumulate the ideal time."""
    speed = np.full(len(grid_m), np.nan, dtype=np.float64)
    elapsed = np.zeros(len(grid_m), dtype=np.float64)
    discontinuities: list[Discontinuity] = []

    running_time = 0.0
    previous_end_speed: float | None = None
    previous_lap: int | None = None

    for position, segment in enumerate(segments):
        start, end = int(edges[position]), int(edges[position + 1])
        source = lap_speed_ms.get(segment.best_lap_index)
        if source is None:
            continue

        speed[start:end] = source[start:end]

        # Time accumulates piecewise: within a segment the winning lap's own
        # profile is used, offset so the lap's clock runs continuously.
        span = end - start
        if span > 0:
            fraction = np.linspace(0.0, 1.0, span, endpoint=False)
            elapsed[start:end] = running_time + fraction * segment.best_time_s
            running_time += segment.best_time_s

        if previous_end_speed is not None and previous_lap is not None:
            discontinuities.append(Discontinuity(
                distance_m=float(grid_m[start]),
                speed_before_ms=previous_end_speed,
                speed_after_ms=float(source[start]),
                from_lap_index=previous_lap,
                to_lap_index=segment.best_lap_index,
            ))

        previous_end_speed = float(source[end - 1])
        previous_lap = segment.best_lap_index

    elapsed[-1] = running_time
    return speed, elapsed, discontinuities


def significant_discontinuities(
    ideal: IdealLap, threshold_ms: float = 1.0
) -> list[Discontinuity]:
    """The seams worth drawing attention to.

    A seam between two laps that were doing the same speed is harmless. One
    where the stitched lap instantaneously gains 15 km/h is the clearest
    evidence that the target is not achievable, and belongs on the chart.
    """
    return [
        seam for seam in ideal.discontinuities
        if abs(seam.jump_ms) >= threshold_ms
    ]
