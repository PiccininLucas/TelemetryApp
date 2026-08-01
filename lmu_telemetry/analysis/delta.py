"""Delta-t: where one lap gains or loses time against another.

With `t(s)` the elapsed time at distance `s` since the lap began,

    delta(s) = t_lap(s) - t_reference(s)

Positive means the lap is behind at that point. The slope matters more than the
value: a rising delta is where time is being lost right now, while a flat delta
at a high value means the loss happened earlier and is simply being carried.

Working in the distance domain is what makes this meaningful. Comparing two laps
at equal *times* compares different parts of the circuit, so the difference
would say nothing.

This module takes numpy arrays and returns numbers. It imports nothing from the
rest of the application.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from lmu_telemetry.analysis import resample


@dataclass(frozen=True, slots=True)
class DeltaResult:
    """The time difference between two laps along the distance they share.

    Attributes:
        grid_m: Distance grid the comparison is evaluated on.
        delta_s: Time difference at each point. Positive means slower.
        reference_time_s: Elapsed time of the reference lap on the grid.
        lap_time_s: Elapsed time of the compared lap on the grid.
    """

    grid_m: np.ndarray
    delta_s: np.ndarray
    reference_time_s: np.ndarray
    lap_time_s: np.ndarray

    @property
    def final_delta_s(self) -> float:
        """The difference at the finish line: the lap-time gap."""
        return float(self.delta_s[-1]) if len(self.delta_s) else 0.0

    @property
    def worst_loss_s(self) -> float:
        """Largest amount the lap was ever behind."""
        return float(np.nanmax(self.delta_s)) if len(self.delta_s) else 0.0

    @property
    def worst_loss_distance_m(self) -> float:
        """Where that happened."""
        if not len(self.delta_s):
            return 0.0
        return float(self.grid_m[int(np.nanargmax(self.delta_s))])

    def gain_rate(self) -> np.ndarray:
        """Rate of change of the delta, in seconds per metre.

        Where the lap is actually losing time, as opposed to where it is still
        carrying a loss from earlier. This is what points at the corner to work
        on: a flat delta after a big step means the step is the problem.
        """
        if len(self.delta_s) < 2:
            return np.zeros_like(self.delta_s)
        return np.gradient(self.delta_s, self.grid_m)


def elapsed_time(
    distance_m: np.ndarray,
    times_s: np.ndarray,
    grid_m: np.ndarray,
) -> np.ndarray:
    """Elapsed time since the lap began, as a function of distance.

    Args:
        distance_m: Distance travelled at each sample.
        times_s: Sample times, in any consistent origin.
        grid_m: Distance grid to evaluate on.

    Returns:
        Seconds since the lap started, at each grid distance.
    """
    times_s = np.asarray(times_s, dtype=np.float64)
    if times_s.size == 0:
        return np.full(np.shape(grid_m), np.nan, dtype=np.float64)

    # Re-zero the origin here rather than requiring the caller to: the session
    # clock does not start at the lap, and a forgotten subtraction would show up
    # as a constant offset that looks exactly like a real time loss.
    since_start = times_s - times_s[0]
    return resample.resample(since_start, distance_m, grid_m)


def delta_time(
    reference_distance_m: np.ndarray,
    reference_times_s: np.ndarray,
    lap_distance_m: np.ndarray,
    lap_times_s: np.ndarray,
    step_m: float = 1.0,
) -> DeltaResult:
    """Compare two laps in the distance domain.

    The grid runs to the shorter of the two laps: past that point one of them
    was never measured, and extrapolating would manufacture a difference.

    Args:
        reference_distance_m: Distance along the reference lap.
        reference_times_s: Sample times of the reference lap.
        lap_distance_m: Distance along the lap being compared.
        lap_times_s: Sample times of that lap.
        step_m: Grid spacing.

    Returns:
        The delta and both elapsed-time curves.
    """
    reference_length = _length_of(reference_distance_m)
    lap_length = _length_of(lap_distance_m)
    shared_length = min(reference_length, lap_length)

    grid = resample.distance_grid(shared_length, step_m)

    reference_elapsed = elapsed_time(reference_distance_m, reference_times_s, grid)
    lap_elapsed = elapsed_time(lap_distance_m, lap_times_s, grid)

    return DeltaResult(
        grid_m=grid,
        delta_s=lap_elapsed - reference_elapsed,
        reference_time_s=reference_elapsed,
        lap_time_s=lap_elapsed,
    )


def delta_against_reference_curve(
    reference_grid_m: np.ndarray,
    reference_elapsed_s: np.ndarray,
    lap_distance_m: np.ndarray,
    lap_times_s: np.ndarray,
) -> DeltaResult:
    """Compare a lap against an already-computed elapsed-time curve.

    Used when the reference is not a real lap - the theoretical ideal lap is
    stitched from segments of several laps, so it exists only as a curve.
    """
    lap_elapsed = elapsed_time(lap_distance_m, lap_times_s, reference_grid_m)
    reference_elapsed = np.asarray(reference_elapsed_s, dtype=np.float64)

    return DeltaResult(
        grid_m=np.asarray(reference_grid_m, dtype=np.float64),
        delta_s=lap_elapsed - reference_elapsed,
        reference_time_s=reference_elapsed,
        lap_time_s=lap_elapsed,
    )


def time_lost_between(
    result: DeltaResult,
    start_m: float,
    end_m: float,
) -> float:
    """Time lost or gained over one stretch of the lap.

    The delta's *change* across the window, not its value: what matters for a
    corner is what happened inside it, not the deficit carried into it.
    """
    if not len(result.grid_m):
        return 0.0
    start = int(np.searchsorted(result.grid_m, start_m, side="left"))
    end = int(np.searchsorted(result.grid_m, end_m, side="right")) - 1
    start = max(0, min(start, len(result.delta_s) - 1))
    end = max(0, min(end, len(result.delta_s) - 1))
    return float(result.delta_s[end] - result.delta_s[start])


def _length_of(distance_m: np.ndarray) -> float:
    values = resample.make_monotonic(distance_m)
    return float(values[-1]) if values.size else 0.0
