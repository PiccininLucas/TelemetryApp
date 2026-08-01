"""A synthetic lap with exactly known properties, for testing the analysis.

A rectangular circuit with rounded corners: four straights and four 90-degree
turns, all in the same direction, so one lap is exactly one full rotation and
the path closes.

The lap is built to be *physically self-consistent* rather than merely
plausible, so the tests check real relationships instead of plumbing:

- The speed profile comes from a quasi-steady lap simulation: a forward pass
  limits acceleration, a backward pass limits braking, and a cornering limit
  caps speed by `v = sqrt(a_lat_max * R)`. The result obeys the same physics the
  analysis assumes.
- Lateral acceleration is `v^2 / R` inside a corner and zero on a straight, so
  the g-g envelope has a shape that can be predicted in advance.
- Longitudinal acceleration is `v dv/ds`, the exact companion of the speed
  profile, so integrating it must return the speed it came from.
- Time comes from `dt = ds / v`, so distance reconstructed by integrating speed
  must return the geometry the lap was built from.

Every quantity is therefore checkable against a closed form, which is what makes
a failure informative rather than merely red.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

STANDARD_GRAVITY = 9.80665


@dataclass(frozen=True)
class SyntheticLap:
    """One lap of the synthetic circuit, on a 1 m distance grid.

    Attributes:
        distance_m: Distance around the lap, uniformly spaced.
        times_s: Time at each point, starting at zero.
        speed_ms: Forward speed.
        lateral_g: Lateral acceleration, positive in a right-hand corner.
        longitudinal_g: Longitudinal acceleration, positive accelerating.
        brake: Brake position, 0-1.
        throttle: Throttle position, 0-1.
        x_m: Exact path, eastward.
        y_m: Exact path, northward.
        heading_rad: Exact heading, clockwise from the start direction.
        latitude_deg: The exact path expressed as GPS coordinates.
        longitude_deg: Likewise.
        corner_apex_distances_m: Where the four corners' midpoints fall.
        lap_length_m: Exact perimeter.
        corner_radius_m: Corner radius.
    """

    distance_m: np.ndarray
    times_s: np.ndarray
    speed_ms: np.ndarray
    lateral_g: np.ndarray
    longitudinal_g: np.ndarray
    brake: np.ndarray
    throttle: np.ndarray
    x_m: np.ndarray
    y_m: np.ndarray
    heading_rad: np.ndarray
    latitude_deg: np.ndarray
    longitude_deg: np.ndarray
    corner_apex_distances_m: np.ndarray
    lap_length_m: float
    corner_radius_m: float

    @property
    def lap_time_s(self) -> float:
        return float(self.times_s[-1])


def make_lap(
    straight_length_m: float = 200.0,
    corner_radius_m: float = 50.0,
    step_m: float = 1.0,
    max_speed_ms: float = 70.0,
    max_lateral_g: float = 1.4,
    max_acceleration_g: float = 0.5,
    max_braking_g: float = 1.3,
    speed_scale: float = 1.0,
    origin_lat_deg: float = 47.95,
    origin_lon_deg: float = 0.22,
) -> SyntheticLap:
    """Build one lap of the synthetic circuit.

    Args:
        straight_length_m: Length of each of the four straights.
        corner_radius_m: Radius of each of the four corners.
        step_m: Distance grid spacing.
        max_speed_ms: Speed the car would reach on an infinite straight.
        max_lateral_g: Cornering limit, which sets the corner speed.
        max_acceleration_g: Traction limit out of a corner.
        max_braking_g: Braking limit into one.
        speed_scale: Multiplies the whole speed profile. Values slightly below 1
            produce a slower but otherwise identical lap, for delta-t tests.
        origin_lat_deg: Latitude the synthetic GPS trace is centred on. The
            default is Le Mans, where `cos(lat)` is far enough from 1 that a
            projection ignoring it would be visibly wrong.
        origin_lon_deg: Longitude likewise.
    """
    arc_length = 0.5 * np.pi * corner_radius_m
    lap_length = 4.0 * (straight_length_m + arc_length)

    n_points = int(round(lap_length / step_m)) + 1
    distance = np.arange(n_points, dtype=np.float64) * step_m

    in_corner, curvature, heading = _geometry(
        distance, straight_length_m, corner_radius_m, arc_length
    )

    speed = _speed_profile(
        distance, in_corner, corner_radius_m, step_m,
        max_speed_ms, max_lateral_g, max_acceleration_g, max_braking_g,
    ) * speed_scale

    # dt = ds / v, integrated with the trapezoidal rule for consistency with
    # how the analysis integrates speed back into distance.
    inverse_speed = 1.0 / np.clip(speed, 1e-6, None)
    times = np.zeros_like(speed)
    times[1:] = np.cumsum(
        0.5 * (inverse_speed[1:] + inverse_speed[:-1]) * np.diff(distance)
    )

    # a_lat = v^2 / R inside a corner, zero on a straight.
    lateral = speed**2 * curvature / STANDARD_GRAVITY

    # a_long = v dv/ds, the exact companion of the speed profile.
    longitudinal = speed * np.gradient(speed, distance) / STANDARD_GRAVITY

    brake, throttle = _pedals(longitudinal, max_acceleration_g, max_braking_g)
    x, y = _path(distance, heading, step_m)
    latitude, longitude = _to_gps(x, y, origin_lat_deg, origin_lon_deg)

    apexes = _apex_distances(straight_length_m, arc_length)

    return SyntheticLap(
        distance_m=distance,
        times_s=times,
        speed_ms=speed,
        lateral_g=lateral,
        longitudinal_g=longitudinal,
        brake=brake,
        throttle=throttle,
        x_m=x,
        y_m=y,
        heading_rad=heading,
        latitude_deg=latitude,
        longitude_deg=longitude,
        corner_apex_distances_m=apexes,
        lap_length_m=lap_length,
        corner_radius_m=corner_radius_m,
    )


def _geometry(
    distance: np.ndarray,
    straight_length_m: float,
    corner_radius_m: float,
    arc_length: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Where the corners are, how tight, and which way the car points.

    The lap repeats a straight-then-corner unit four times. Position within that
    unit decides everything, which keeps the construction exact.
    """
    unit_length = straight_length_m + arc_length
    position_in_unit = np.mod(distance, unit_length)

    in_corner = position_in_unit >= straight_length_m
    curvature = np.where(in_corner, 1.0 / corner_radius_m, 0.0)

    # Heading is the integral of curvature along the path. Doing it in closed
    # form rather than numerically keeps the rectangle exactly square: each
    # corner turns exactly 90 degrees, so the lap closes exactly.
    completed_units = np.floor(distance / unit_length)
    arc_travelled = np.clip(position_in_unit - straight_length_m, 0.0, arc_length)
    heading = (completed_units * (np.pi / 2.0)
               + arc_travelled / corner_radius_m)

    return in_corner, curvature, heading


def _speed_profile(
    distance: np.ndarray,
    in_corner: np.ndarray,
    corner_radius_m: float,
    step_m: float,
    max_speed_ms: float,
    max_lateral_g: float,
    max_acceleration_g: float,
    max_braking_g: float,
) -> np.ndarray:
    """Quasi-steady lap simulation.

    Three limits, applied in the classic order:

    1. **Cornering.** In a corner the car cannot exceed `sqrt(a_lat * R)`,
       straight from `a_lat = v^2 / R`.
    2. **Traction**, forward pass. Leaving a corner, speed can only rise as fast
       as `v^2 = v0^2 + 2 a ds` allows.
    3. **Braking**, backward pass. Approaching a corner, speed must already be
       low enough to reach the corner speed under the braking limit.

    Both passes are run twice around the lap so the profile is periodic: the
    braking zone for the first corner depends on speed carried from the last.
    """
    cornering_limit = np.sqrt(
        max_lateral_g * STANDARD_GRAVITY * corner_radius_m
    )
    speed = np.where(in_corner, cornering_limit, max_speed_ms)

    acceleration = max_acceleration_g * STANDARD_GRAVITY
    braking = max_braking_g * STANDARD_GRAVITY
    n = len(speed)

    for _pass in range(2):
        # Forward: traction limit, wrapping so the lap start inherits the end.
        for i in range(1, n):
            speed[i] = min(
                speed[i], np.sqrt(speed[i - 1] ** 2 + 2 * acceleration * step_m)
            )
        speed[0] = min(speed[0], speed[-1])

        # Backward: braking limit.
        for i in range(n - 2, -1, -1):
            speed[i] = min(
                speed[i], np.sqrt(speed[i + 1] ** 2 + 2 * braking * step_m)
            )
        speed[-1] = min(speed[-1], speed[0])

    return speed


def _pedals(
    longitudinal_g: np.ndarray,
    max_acceleration_g: float,
    max_braking_g: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Derive pedal positions from longitudinal acceleration.

    A driver braking at the limit has the brake fully applied; one accelerating
    at the limit is at full throttle. Proportional in between, which is a
    caricature of a real trace but has exactly the property the tests need: the
    pedals agree with the acceleration.
    """
    brake = np.clip(-longitudinal_g / max_braking_g, 0.0, 1.0)
    throttle = np.clip(longitudinal_g / max_acceleration_g, 0.0, 1.0)
    # A car holding speed through a corner is on a maintenance throttle, not
    # coasting; without this the coasting measure would be meaningless.
    holding = (brake < 0.02) & (throttle < 0.02)
    throttle[holding] = 0.25
    return brake, throttle


def _path(
    distance: np.ndarray, heading: np.ndarray, step_m: float
) -> tuple[np.ndarray, np.ndarray]:
    """Integrate the exact heading into an exact path.

    Heading is measured clockwise from north, so east is `sin` and north is
    `cos` - the same convention `analysis.trackmap` uses.
    """
    dx = np.sin(heading) * step_m
    dy = np.cos(heading) * step_m

    x = np.zeros_like(distance)
    y = np.zeros_like(distance)
    x[1:] = np.cumsum(0.5 * (dx[1:] + dx[:-1]))
    y[1:] = np.cumsum(0.5 * (dy[1:] + dy[:-1]))
    return x, y


def _to_gps(
    x_m: np.ndarray,
    y_m: np.ndarray,
    origin_lat_deg: float,
    origin_lon_deg: float,
    earth_radius_m: float = 6378137.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Express a local path as GPS coordinates.

    The exact inverse of the equirectangular projection in `analysis.trackmap`,
    so projecting these coordinates must return the path they came from.
    """
    lat0 = np.radians(origin_lat_deg)
    latitude = np.degrees(lat0 + y_m / earth_radius_m)
    longitude = np.degrees(
        np.radians(origin_lon_deg) + x_m / (earth_radius_m * np.cos(lat0))
    )
    return latitude, longitude


def _apex_distances(straight_length_m: float, arc_length: float) -> np.ndarray:
    """Where each corner's midpoint falls around the lap."""
    unit_length = straight_length_m + arc_length
    return np.array([
        i * unit_length + straight_length_m + arc_length / 2.0
        for i in range(4)
    ])
