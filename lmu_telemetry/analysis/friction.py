"""The g-g diagram: how much of the tyres' grip the driver actually uses.

Plotting lateral against longitudinal acceleration maps the friction the car
generated. The tyre can produce roughly a fixed total, so the achievable points
fill a rounded region - the friction ellipse - and the driver's job is to live
on its edge.

What the shape says:

- **A hollow in the middle of the transitions**, between pure braking at the
  bottom and pure cornering at the sides, means the driver releases the brake
  before starting to turn instead of blending the two. That is the most common
  and most recoverable pattern in an amateur trace.
- **Points beyond the usual envelope** are not extra grip; they are the moment
  it was exceeded, and are usually followed by a correction.
- **A small envelope overall** at one corner means the limit was never
  approached there.

The envelope is the convex hull of the points, and the filled fraction is the
area of the hull divided by the area of an ellipse with the same reach. That
ratio is the summary number: how much of what the car offered was used.

Requires correctly labelled accelerations. The game's own `G Force Lat` and
`G Force Long` channels are swapped and negated; `ingest.corrections` fixes that
before anything reaches this module.

This module takes numpy arrays and returns numbers. It imports nothing from the
rest of the application.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.spatial import ConvexHull, QhullError


@dataclass(frozen=True, slots=True)
class FrictionEnvelope:
    """The grip envelope of a set of acceleration samples.

    Attributes:
        lateral_g: The samples used, lateral component.
        longitudinal_g: The samples used, longitudinal component.
        hull_lateral_g: Lateral coordinates of the hull boundary, closed.
        hull_longitudinal_g: Longitudinal coordinates of the hull, closed.
        hull_area_g2: Area enclosed by the hull, in g squared.
        max_lateral_g: Largest lateral magnitude reached.
        max_braking_g: Largest deceleration reached, as a positive number.
        max_acceleration_g: Largest forward acceleration reached.
        n_points: How many samples went in.
    """

    lateral_g: np.ndarray
    longitudinal_g: np.ndarray
    hull_lateral_g: np.ndarray
    hull_longitudinal_g: np.ndarray
    hull_area_g2: float
    max_lateral_g: float
    max_braking_g: float
    max_acceleration_g: float
    n_points: int

    @property
    def reference_area_g2(self) -> float:
        """Area of the ellipse the car's own extremes describe.

        Semi-axes are the largest lateral and largest longitudinal magnitudes
        observed, so the comparison is against what this car and driver reached,
        not against an assumed tyre model.
        """
        longitudinal_reach = max(self.max_braking_g, self.max_acceleration_g)
        return float(np.pi * self.max_lateral_g * longitudinal_reach)

    @property
    def fill_fraction(self) -> float:
        """Share of the reference ellipse the hull covers, 0 to 1.

        A driver who blends braking into cornering fills more of it. Values near
        1 are not expected: the ellipse is an outer bound, and the hull of real
        data is always inside it.
        """
        reference = self.reference_area_g2
        if reference <= 0.0:
            return 0.0
        return float(min(self.hull_area_g2 / reference, 1.0))

    @property
    def is_valid(self) -> bool:
        return self.n_points >= 3 and self.hull_area_g2 > 0.0


def filter_samples(
    lateral_g: np.ndarray,
    longitudinal_g: np.ndarray,
    speed_ms: np.ndarray | None = None,
    min_speed_ms: float = 10.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Drop samples that would distort the envelope.

    Non-finite values, and anything below a speed floor: a stationary car still
    registers accelerometer noise, and at a standstill that noise would appear
    as grip the car never generated.
    """
    lateral = np.asarray(lateral_g, dtype=np.float64)
    longitudinal = np.asarray(longitudinal_g, dtype=np.float64)

    keep = np.isfinite(lateral) & np.isfinite(longitudinal)
    if speed_ms is not None:
        speed = np.asarray(speed_ms, dtype=np.float64)
        keep &= np.isfinite(speed) & (speed >= min_speed_ms)

    return lateral[keep], longitudinal[keep]


def compute_envelope(
    lateral_g: np.ndarray,
    longitudinal_g: np.ndarray,
    speed_ms: np.ndarray | None = None,
    min_speed_ms: float = 10.0,
) -> FrictionEnvelope:
    """Build the g-g envelope for a set of samples.

    Args:
        lateral_g: Lateral acceleration in g, positive in a right-hand corner.
        longitudinal_g: Longitudinal acceleration in g, positive accelerating.
        speed_ms: Speed, used only to exclude low-speed noise.
        min_speed_ms: Speed floor.

    Returns:
        The envelope. Degenerate input yields a result with `is_valid` false
        rather than an exception - a lap spent entirely in the pit lane is a
        reasonable thing to ask about and an unreasonable thing to crash on.
    """
    lateral, longitudinal = filter_samples(
        lateral_g, longitudinal_g, speed_ms, min_speed_ms
    )

    empty = np.empty(0, dtype=np.float64)
    if lateral.size == 0:
        return FrictionEnvelope(
            lateral_g=empty, longitudinal_g=empty,
            hull_lateral_g=empty, hull_longitudinal_g=empty,
            hull_area_g2=0.0, max_lateral_g=0.0,
            max_braking_g=0.0, max_acceleration_g=0.0, n_points=0,
        )

    max_lateral = float(np.max(np.abs(lateral)))
    max_braking = float(-np.min(longitudinal)) if longitudinal.min() < 0 else 0.0
    max_acceleration = float(np.max(longitudinal)) if longitudinal.max() > 0 else 0.0

    hull_lateral, hull_longitudinal, area = _convex_hull(lateral, longitudinal)

    return FrictionEnvelope(
        lateral_g=lateral,
        longitudinal_g=longitudinal,
        hull_lateral_g=hull_lateral,
        hull_longitudinal_g=hull_longitudinal,
        hull_area_g2=area,
        max_lateral_g=max_lateral,
        max_braking_g=max_braking,
        max_acceleration_g=max_acceleration,
        n_points=int(lateral.size),
    )


def _convex_hull(
    x: np.ndarray, y: np.ndarray
) -> tuple[np.ndarray, np.ndarray, float]:
    """Convex hull of a 2-D point cloud, returned closed, with its area.

    Degenerate clouds - fewer than three points, or all collinear - have no
    hull. Qhull raises for those, and the caller gets an empty hull with zero
    area rather than an exception, because both are legitimate inputs.
    """
    if x.size < 3:
        return np.empty(0), np.empty(0), 0.0

    points = np.column_stack([x, y])
    try:
        hull = ConvexHull(points)
    except QhullError:
        return np.empty(0), np.empty(0), 0.0

    vertices = hull.vertices
    # Close the ring so a plot draws the last edge.
    closed = np.append(vertices, vertices[0])
    # For a 2-D hull, Qhull's `volume` is the enclosed area.
    return points[closed, 0], points[closed, 1], float(hull.volume)


def envelope_for_window(
    lateral_g: np.ndarray,
    longitudinal_g: np.ndarray,
    distance_m: np.ndarray,
    start_m: float,
    end_m: float,
    speed_ms: np.ndarray | None = None,
    min_speed_ms: float = 10.0,
) -> FrictionEnvelope:
    """Build the envelope for one stretch of the lap.

    Filtering by corner is what turns the diagram from a summary into a
    diagnosis: the whole-lap envelope is dominated by the best corner, while a
    single corner's envelope shows whether the limit was approached *there*.
    """
    distance = np.asarray(distance_m, dtype=np.float64)
    window = (distance >= start_m) & (distance <= end_m)

    return compute_envelope(
        np.asarray(lateral_g)[window],
        np.asarray(longitudinal_g)[window],
        np.asarray(speed_ms)[window] if speed_ms is not None else None,
        min_speed_ms,
    )


def combined_magnitude(
    lateral_g: np.ndarray, longitudinal_g: np.ndarray
) -> np.ndarray:
    """Total acceleration magnitude, `sqrt(a_lat^2 + a_long^2)`, in g.

    How hard the tyres are working at each instant, regardless of direction.
    """
    lateral = np.asarray(lateral_g, dtype=np.float64)
    longitudinal = np.asarray(longitudinal_g, dtype=np.float64)
    return np.hypot(lateral, longitudinal)


def transition_quality(
    lateral_g: np.ndarray,
    longitudinal_g: np.ndarray,
    min_magnitude_g: float = 0.3,
) -> float:
    """How much of the time both axes are loaded at once, 0 to 1.

    The measurable form of "does the driver blend braking into turning". Of the
    samples where the car is working at all, the fraction where neither axis is
    dominating the other - the diagonal regions of the diagram that a
    brake-then-turn driver leaves empty.
    """
    lateral = np.abs(np.asarray(lateral_g, dtype=np.float64))
    longitudinal = np.abs(np.asarray(longitudinal_g, dtype=np.float64))

    magnitude = np.hypot(lateral, longitudinal)
    working = magnitude >= min_magnitude_g
    if not np.any(working):
        return 0.0

    # Both axes contributing meaningfully: the smaller component is at least a
    # third of the larger.
    smaller = np.minimum(lateral, longitudinal)[working]
    larger = np.maximum(lateral, longitudinal)[working]
    blended = smaller >= larger / 3.0
    return float(np.mean(blended))
