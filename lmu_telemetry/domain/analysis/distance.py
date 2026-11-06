"""Reconstruct distance travelled along a lap.

Why not use `Lap Dist` directly: it is recorded at 10 Hz. At 250 km/h that is
one sample every 6.9 m, and a braking point located to the nearest 7 m is not a
braking point - two laps braking 5 m apart would look identical. `Ground Speed`
is recorded at 100 Hz, giving about 0.7 m between samples.

So distance is rebuilt by integrating speed:

    s(t) = integral of V dt

evaluated with the trapezoidal rule, which is exact for the linear speed change
between two samples and is the natural choice for evenly sampled data.

Integration drifts. Any small bias in the speed signal accumulates over a lap,
so by the finish line the integrated distance is off by metres. The fix is that
the true lap length is known - from `Lap Dist`, or from the catalog's measured
track length - so the integrated distance is rescaled to close on it:

    s_corrected(t) = s_raw(t) * (L_reference / s_raw(end))

This distributes the drift proportionally along the lap, which is right when the
error is a bias rather than a single event. Both versions are kept so the
correction can be plotted and defended rather than taken on trust.

This module takes numpy arrays and returns numbers. It imports nothing from the
rest of the application.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class DistanceReconstruction:
    """Distance along a lap, before and after the closure correction.

    Attributes:
        raw_m: Cumulative integral of speed, zeroed at the lap start.
        corrected_m: The same, rescaled to close on the reference length.
        scale_factor: `reference_length_m / integrated_length_m`. A value far
            from 1 means the integration or the reference is wrong.
        integrated_length_m: Lap length according to the integration alone.
        reference_length_m: The length the lap was scaled to, or None when no
            reference was available and no correction was applied.
        correction_applied: False when the result is the raw integration.
    """

    raw_m: np.ndarray
    corrected_m: np.ndarray
    scale_factor: float
    integrated_length_m: float
    reference_length_m: float | None
    correction_applied: bool

    @property
    def length_m(self) -> float:
        """Length of the reconstructed lap."""
        return float(self.corrected_m[-1]) if len(self.corrected_m) else 0.0

    @property
    def drift_m(self) -> float:
        """How far the raw integration missed the reference by."""
        if self.reference_length_m is None:
            return 0.0
        return self.integrated_length_m - self.reference_length_m


def cumulative_distance(speed_ms: np.ndarray, times_s: np.ndarray) -> np.ndarray:
    """Integrate speed over time, cumulatively, starting from zero.

    Trapezoidal rule: between two samples the speed is taken to vary linearly,
    so the distance covered is the mean of the two speeds times the interval.
    Exact for constant acceleration, which at 100 Hz is a very good description
    of what a car does between samples.

    Args:
        speed_ms: Forward speed in m/s.
        times_s: Sample times in seconds, ascending, same length as `speed_ms`.

    Returns:
        Cumulative distance in metres, starting at 0.

    Raises:
        ValueError: The inputs disagree in length.
    """
    speed_ms = np.asarray(speed_ms, dtype=np.float64)
    times_s = np.asarray(times_s, dtype=np.float64)

    if speed_ms.shape != times_s.shape:
        raise ValueError(
            f"speed and time must have the same shape, got {speed_ms.shape} "
            f"and {times_s.shape}"
        )
    if speed_ms.size == 0:
        return np.empty(0, dtype=np.float64)
    if speed_ms.size == 1:
        return np.zeros(1, dtype=np.float64)

    intervals = np.diff(times_s)
    mean_speed = 0.5 * (speed_ms[1:] + speed_ms[:-1])
    steps = mean_speed * intervals

    distance = np.empty_like(speed_ms)
    distance[0] = 0.0
    np.cumsum(steps, out=distance[1:])
    return distance


def reconstruct(
    speed_ms: np.ndarray,
    times_s: np.ndarray,
    reference_length_m: float | None = None,
    *,
    min_scale_factor: float = 0.9,
    max_scale_factor: float = 1.1,
) -> DistanceReconstruction:
    """Rebuild distance along one lap, corrected to close on a known length.

    Args:
        speed_ms: Forward speed in m/s over the lap.
        times_s: Sample times in seconds.
        reference_length_m: The lap's true length. Without it no correction is
            applied and the raw integration is returned.
        min_scale_factor: Reject a correction below this.
        max_scale_factor: Reject a correction above this.

    Returns:
        Both versions of the distance and the factor between them.

    The scale factor is bounded because a factor far from 1 does not mean the
    lap needs stretching - it means something upstream is wrong, most likely a
    partial lap being scaled to a full lap's length. Stretching it anyway would
    produce a plausible-looking distance axis that is silently a lie, so the
    correction is refused and the raw integration returned instead.
    """
    raw = cumulative_distance(speed_ms, times_s)
    integrated_length = float(raw[-1]) if len(raw) else 0.0

    if (
        reference_length_m is None
        or reference_length_m <= 0.0
        or integrated_length <= 0.0
    ):
        return DistanceReconstruction(
            raw_m=raw,
            corrected_m=raw,
            scale_factor=1.0,
            integrated_length_m=integrated_length,
            reference_length_m=reference_length_m,
            correction_applied=False,
        )

    scale = reference_length_m / integrated_length

    if not (min_scale_factor <= scale <= max_scale_factor):
        return DistanceReconstruction(
            raw_m=raw,
            corrected_m=raw,
            scale_factor=scale,
            integrated_length_m=integrated_length,
            reference_length_m=reference_length_m,
            correction_applied=False,
        )

    return DistanceReconstruction(
        raw_m=raw,
        corrected_m=raw * scale,
        scale_factor=scale,
        integrated_length_m=integrated_length,
        reference_length_m=reference_length_m,
        correction_applied=True,
    )


def lap_length_from_channel(lap_distance_m: np.ndarray) -> float | None:
    """Read a lap's length off the game's own `Lap Dist` channel.

    The channel climbs to the lap length and resets at the line, so within one
    lap the maximum is the length reached. Coarse - 10 Hz means it misses the
    last few metres - but it is an independent reference, which is the point:
    it is used to correct the integration, not to replace it.

    Returns:
        The maximum, or None when the channel holds nothing usable.
    """
    values = np.asarray(lap_distance_m, dtype=np.float64)
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return None
    maximum = float(finite.max())
    return maximum if maximum > 0.0 else None


def speed_from_distance(
    distance_m: np.ndarray, times_s: np.ndarray
) -> np.ndarray:
    """Differentiate distance to recover speed, in m/s.

    The inverse of `cumulative_distance`, used to check the reconstruction
    against the recorded speed: a round trip that does not return the original
    signal means the integration lost something.
    """
    return np.gradient(
        np.asarray(distance_m, dtype=np.float64),
        np.asarray(times_s, dtype=np.float64),
    )
