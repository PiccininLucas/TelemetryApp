"""Putting a channel onto a common time grid.

Pure numpy, so it lives in the domain: both the ingestion of event channels and
the application-level pipeline need it, and neither may depend on the other.
"""

from __future__ import annotations

import numpy as np


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
