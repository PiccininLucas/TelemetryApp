"""Resample a lap onto a fixed distance grid.

Every lap-to-lap comparison happens in the distance domain, never in time. Two
laps of the same circuit cover the same metres; they do not cover the same
seconds, so comparing them at equal times compares different corners.

The grid is a fixed step - 1 m by default - from the start of the lap to its
end. At 1 m, a braking point is located to within a metre, which is finer than
any driver's repeatability.

This module takes numpy arrays and returns numbers. It imports nothing from the
rest of the application.
"""

from __future__ import annotations

import numpy as np


def distance_grid(length_m: float, step_m: float = 1.0) -> np.ndarray:
    """Build the distance grid for a lap.

    Args:
        length_m: Lap length.
        step_m: Grid spacing.

    Returns:
        Distances from 0 to `length_m` inclusive. Empty when the length or step
        is not positive.
    """
    if length_m <= 0.0 or step_m <= 0.0:
        return np.empty(0, dtype=np.float64)
    n_points = int(np.floor(length_m / step_m)) + 1
    return np.arange(n_points, dtype=np.float64) * step_m


def make_monotonic(distance_m: np.ndarray) -> np.ndarray:
    """Force a distance series to be non-decreasing.

    Interpolation needs a strictly increasing x axis, and a real lap does not
    always provide one: a stopped car produces a flat run, and a spin or a
    reverse out of a gravel trap produces a genuine decrease.

    A running maximum is the right repair rather than sorting or dropping
    samples. It says "the car never un-drove a metre it had already driven",
    which keeps every sample in its original order and turns a reversal into a
    flat section - exactly what it means for progress around the lap.
    """
    return np.maximum.accumulate(np.asarray(distance_m, dtype=np.float64))


def resample(
    values: np.ndarray,
    distance_m: np.ndarray,
    grid_m: np.ndarray,
    *,
    discrete: bool = False,
) -> np.ndarray:
    """Put one channel onto a distance grid.

    Args:
        values: Channel samples, shape `(n,)` or `(n, k)`.
        distance_m: Distance at each sample, same length as `values`.
        grid_m: Target distance grid.
        discrete: Hold the previous value instead of interpolating. Required
            for gear, flags, tyre compound and surface type - interpolating
            them would invent a gear 3.5.

    Returns:
        Shape `(len(grid_m),)` or `(len(grid_m), k)`.
    """
    values = np.asarray(values)
    distance_m = np.asarray(distance_m, dtype=np.float64)
    grid_m = np.asarray(grid_m, dtype=np.float64)

    if values.ndim == 2:
        columns = [
            resample(values[:, i], distance_m, grid_m, discrete=discrete)
            for i in range(values.shape[1])
        ]
        return np.column_stack(columns)

    if values.size == 0 or grid_m.size == 0:
        return np.full(grid_m.shape, np.nan, dtype=np.float64)

    monotonic = make_monotonic(distance_m)

    if discrete:
        indices = np.searchsorted(monotonic, grid_m, side="right") - 1
        indices = np.clip(indices, 0, len(values) - 1)
        return values[indices].astype(np.float64)

    # np.interp clamps outside the sampled range rather than extrapolating.
    # Beyond the lap, repeating the edge sample beats inventing values.
    return np.interp(grid_m, monotonic, values.astype(np.float64))


def resample_channels(
    channels: dict[str, np.ndarray],
    distance_m: np.ndarray,
    grid_m: np.ndarray,
    discrete_names: frozenset[str] = frozenset(),
) -> dict[str, np.ndarray]:
    """Resample several channels at once onto the same grid.

    Args:
        channels: Channel name -> samples.
        distance_m: Distance at each sample. All channels must already share
            these sample positions, which is what the common time grid is for.
        grid_m: Target distance grid.
        discrete_names: Which channels to hold rather than interpolate.
    """
    return {
        name: resample(
            values, distance_m, grid_m, discrete=name in discrete_names
        )
        for name, values in channels.items()
    }


def align_to_common_grid(
    laps: list[tuple[np.ndarray, np.ndarray]],
    step_m: float = 1.0,
) -> tuple[np.ndarray, list[np.ndarray]]:
    """Put several laps of one channel onto one shared distance grid.

    Laps of the same circuit differ slightly in reconstructed length, so the
    shortest sets the grid: extending the others would mean extrapolating past
    where they were measured.

    Args:
        laps: One `(values, distance_m)` pair per lap.
        step_m: Grid spacing.

    Returns:
        `(grid_m, resampled_per_lap)`.
    """
    if not laps:
        return np.empty(0, dtype=np.float64), []

    shortest = min(
        float(make_monotonic(distance)[-1])
        for _values, distance in laps
        if len(distance)
    )
    grid = distance_grid(shortest, step_m)
    return grid, [resample(values, distance, grid) for values, distance in laps]
