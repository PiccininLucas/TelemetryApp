"""Build the track's shape, two independent ways.

**1. Projected GPS.** An equirectangular projection about the lap's first point:

    x = R * (lon - lon0) * cos(lat0)
    y = R * (lat - lat0)

with angles in radians and `R` the WGS-84 equatorial radius. The projection
treats a small patch of the globe as flat and scales longitude by `cos(lat0)`
to account for meridians converging. Over a circuit - at most about 14 km across
at Le Mans - the distortion is far below the metre, so this is exact for the
purpose. It is the trustworthy reconstruction.

**2. Integrated heading.** A cross-check that uses no position data at all. The
game does not record yaw rate, so it is inferred from the steady-state cornering
relation

    omega = a_y / V

and the heading integrated from it, with the path following from speed:

    psi(t) = psi_0 + integral of (a_y / V) dt
    x(t)   = integral of V*sin(psi) dt,   y(t) = integral of V*cos(psi) dt

**The assumptions, and where they fail.** `omega = a_y / V` is the quasi-steady
cornering relation: it holds when the car is following a circular path at
constant radius with a negligible sideslip angle. It is wrong

- during transients, where the car is rotating but lateral acceleration has not
  built up yet, so the true yaw rate leads the estimate;
- whenever the car is sliding, since sideslip means the velocity vector and the
  heading have parted company - exactly what the relation assumes away;
- at low speed, where dividing by `V` amplifies any error without bound;
- under braking and traction, where longitudinal load transfer alters the
  relation between lateral acceleration and path curvature.

Integration compounds all of it: a small heading bias becomes a growing position
error, so the reconstructed lap does not close. **The point is not to replace
the GPS trace but to quantify the disagreement**, which is why the comparison
returns the error rather than an opinion.

This module takes numpy arrays and returns numbers. It imports nothing from the
rest of the application.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

#: WGS-84 equatorial radius, in metres.
EARTH_RADIUS_M = 6378137.0

#: Standard gravity, for converting accelerations expressed in g.
STANDARD_GRAVITY = 9.80665


@dataclass(frozen=True, slots=True)
class TrackPath:
    """A planar path, in metres from the lap's starting point.

    Attributes:
        x_m: Eastward from the origin.
        y_m: Northward from the origin.
        origin_lat_deg: Latitude the projection is centred on, when it came
            from GPS.
        origin_lon_deg: Longitude likewise.
    """

    x_m: np.ndarray
    y_m: np.ndarray
    origin_lat_deg: float | None = None
    origin_lon_deg: float | None = None

    @property
    def closure_error_m(self) -> float:
        """Distance between the path's first and last points.

        A lap ends where it started, so this is the accumulated error - near
        zero for the GPS projection, and the headline number for the integrated
        reconstruction.
        """
        if len(self.x_m) < 2:
            return 0.0
        return float(np.hypot(self.x_m[-1] - self.x_m[0],
                              self.y_m[-1] - self.y_m[0]))

    @property
    def extent_m(self) -> tuple[float, float]:
        """Width and height of the bounding box."""
        if not len(self.x_m):
            return (0.0, 0.0)
        return (
            float(np.ptp(self.x_m)),
            float(np.ptp(self.y_m)),
        )

    @property
    def path_length_m(self) -> float:
        """Length travelled along the path."""
        if len(self.x_m) < 2:
            return 0.0
        return float(np.sum(np.hypot(np.diff(self.x_m), np.diff(self.y_m))))


@dataclass(frozen=True, slots=True)
class PathComparison:
    """How far the integrated reconstruction strays from the GPS trace.

    Attributes:
        errors_m: Distance between the two paths at each sample, after the
            integrated path is aligned to the GPS one.
        mean_error_m: Mean of those.
        max_error_m: Worst of those.
        integrated_closure_error_m: How far the integrated lap misses closing.
        gps_closure_error_m: The same for the GPS trace, as a control.
    """

    errors_m: np.ndarray
    mean_error_m: float
    max_error_m: float
    integrated_closure_error_m: float
    gps_closure_error_m: float

    @property
    def relative_error(self) -> float:
        """Mean error as a fraction of the lap's own size."""
        return self.mean_error_m


def project_gps(
    latitude_deg: np.ndarray,
    longitude_deg: np.ndarray,
    earth_radius_m: float = EARTH_RADIUS_M,
) -> TrackPath:
    """Project GPS coordinates onto a local plane in metres.

    Equirectangular about the first point. The `cos(lat0)` factor accounts for
    meridians converging away from the equator; without it a circuit at Le Mans,
    at 47 degrees north, would come out stretched east-west by about 47%.

    Args:
        latitude_deg: Latitudes in degrees.
        longitude_deg: Longitudes in degrees.
        earth_radius_m: Sphere radius.

    Returns:
        The path, with x eastward and y northward from the first sample.
    """
    latitude = np.asarray(latitude_deg, dtype=np.float64)
    longitude = np.asarray(longitude_deg, dtype=np.float64)

    if latitude.size == 0:
        return TrackPath(np.empty(0), np.empty(0))

    lat_rad = np.radians(latitude)
    lon_rad = np.radians(longitude)
    lat0, lon0 = float(lat_rad[0]), float(lon_rad[0])

    x = earth_radius_m * (lon_rad - lon0) * np.cos(lat0)
    y = earth_radius_m * (lat_rad - lat0)

    return TrackPath(
        x_m=x, y_m=y,
        origin_lat_deg=float(latitude[0]),
        origin_lon_deg=float(longitude[0]),
    )


def integrate_heading(
    lateral_g: np.ndarray,
    speed_ms: np.ndarray,
    times_s: np.ndarray,
    initial_heading_rad: float = 0.0,
    min_speed_ms: float = 5.0,
) -> np.ndarray:
    """Integrate yaw rate from lateral acceleration to get heading.

    Uses `omega = a_y / V`, valid for quasi-steady cornering with a small
    sideslip angle. See the module docstring for where that breaks down.

    Below `min_speed_ms` the yaw rate is held at zero rather than computed: the
    division blows up as speed approaches zero, and one such sample would inject
    an arbitrary rotation into every point that follows.

    Args:
        lateral_g: Lateral acceleration in g, positive in a right-hand corner.
        speed_ms: Forward speed in m/s.
        times_s: Sample times in seconds.
        initial_heading_rad: Heading at the first sample. Unknowable from the
            data; it only rotates the result.
        min_speed_ms: Speed floor.

    Returns:
        Heading in radians at each sample, measured clockwise from the initial
        direction so that a positive lateral acceleration turns right.
    """
    lateral = np.asarray(lateral_g, dtype=np.float64) * STANDARD_GRAVITY
    speed = np.asarray(speed_ms, dtype=np.float64)
    times = np.asarray(times_s, dtype=np.float64)

    if lateral.size == 0:
        return np.empty(0, dtype=np.float64)

    yaw_rate = np.zeros_like(lateral)
    moving = speed >= min_speed_ms
    yaw_rate[moving] = lateral[moving] / speed[moving]

    heading = np.empty_like(lateral)
    heading[0] = initial_heading_rad
    if lateral.size > 1:
        intervals = np.diff(times)
        # Trapezoidal, consistent with the distance integration elsewhere.
        mean_rate = 0.5 * (yaw_rate[1:] + yaw_rate[:-1])
        np.cumsum(mean_rate * intervals, out=heading[1:])
        heading[1:] += initial_heading_rad

    return heading


def integrate_path(
    speed_ms: np.ndarray,
    heading_rad: np.ndarray,
    times_s: np.ndarray,
) -> TrackPath:
    """Build a path by projecting speed along an integrated heading.

    Heading is measured clockwise from the initial direction, so x is
    `sin(psi)` and y is `cos(psi)`: the car starts heading along +y and a
    positive heading swings it toward +x, which is to the right.
    """
    speed = np.asarray(speed_ms, dtype=np.float64)
    heading = np.asarray(heading_rad, dtype=np.float64)
    times = np.asarray(times_s, dtype=np.float64)

    if speed.size == 0:
        return TrackPath(np.empty(0), np.empty(0))

    velocity_x = speed * np.sin(heading)
    velocity_y = speed * np.cos(heading)

    x = np.zeros_like(speed)
    y = np.zeros_like(speed)
    if speed.size > 1:
        intervals = np.diff(times)
        np.cumsum(0.5 * (velocity_x[1:] + velocity_x[:-1]) * intervals, out=x[1:])
        np.cumsum(0.5 * (velocity_y[1:] + velocity_y[:-1]) * intervals, out=y[1:])

    return TrackPath(x_m=x, y_m=y)


def reconstruct_from_lateral_g(
    lateral_g: np.ndarray,
    speed_ms: np.ndarray,
    times_s: np.ndarray,
    initial_heading_rad: float = 0.0,
    min_speed_ms: float = 5.0,
) -> TrackPath:
    """Rebuild the track's shape without using position data at all."""
    heading = integrate_heading(
        lateral_g, speed_ms, times_s, initial_heading_rad, min_speed_ms
    )
    return integrate_path(speed_ms, heading, times_s)


def compare_paths(gps: TrackPath, integrated: TrackPath) -> PathComparison:
    """Measure how far the integrated reconstruction departs from the GPS one.

    The integrated path is first rotated and scaled onto the GPS path, because
    its absolute orientation is arbitrary - the initial heading is unknowable -
    and a fixed rotation offset is not an error in the reconstruction. What
    remains after alignment is the part the method genuinely got wrong.
    """
    if len(gps.x_m) != len(integrated.x_m) or len(gps.x_m) < 2:
        empty = np.empty(0, dtype=np.float64)
        return PathComparison(
            errors_m=empty, mean_error_m=float("nan"), max_error_m=float("nan"),
            integrated_closure_error_m=integrated.closure_error_m,
            gps_closure_error_m=gps.closure_error_m,
        )

    aligned_x, aligned_y = _align(gps, integrated)
    errors = np.hypot(aligned_x - gps.x_m, aligned_y - gps.y_m)

    return PathComparison(
        errors_m=errors,
        mean_error_m=float(np.mean(errors)),
        max_error_m=float(np.max(errors)),
        integrated_closure_error_m=integrated.closure_error_m,
        gps_closure_error_m=gps.closure_error_m,
    )


def align_paths(gps: TrackPath, integrated: TrackPath) -> TrackPath:
    """Rotate the integrated path onto the GPS one, for drawing them together.

    The reconstruction's absolute orientation is arbitrary - the initial
    heading is unknowable from the data - so an unaligned overlay shows a
    rotation that is not an error. Aligning first leaves only what the method
    genuinely got wrong on screen.
    """
    if len(gps.x_m) != len(integrated.x_m) or len(gps.x_m) < 2:
        return integrated
    x, y = _align(gps, integrated)
    return TrackPath(x_m=x, y_m=y)


def _align(gps: TrackPath, integrated: TrackPath) -> tuple[np.ndarray, np.ndarray]:
    """Rotate the integrated path onto the GPS path about their shared origin.

    Solves for the single rotation that minimises the squared distance between
    the two - the 2-D Procrustes problem without scaling, since both are already
    in metres. The optimal angle follows in closed form from the cross and dot
    products of the two point sets.
    """
    gx = gps.x_m - gps.x_m[0]
    gy = gps.y_m - gps.y_m[0]
    ix = integrated.x_m - integrated.x_m[0]
    iy = integrated.y_m - integrated.y_m[0]

    cross = float(np.sum(ix * gy - iy * gx))
    dot = float(np.sum(ix * gx + iy * gy))
    angle = np.arctan2(cross, dot)

    cos_a, sin_a = np.cos(angle), np.sin(angle)
    return (
        gps.x_m[0] + ix * cos_a - iy * sin_a,
        gps.y_m[0] + ix * sin_a + iy * cos_a,
    )


def pedal_state(
    brake: np.ndarray,
    throttle: np.ndarray,
    brake_threshold: float = 0.03,
    throttle_threshold: float = 0.05,
) -> np.ndarray:
    """Classify each sample as braking, coasting or on the throttle.

    Colours the track map, which is where coasting becomes visible as a
    stretch of the circuit rather than a number.

    Returns:
        -1 braking, 0 coasting, +1 on throttle.
    """
    brake = np.asarray(brake, dtype=np.float64)
    throttle = np.asarray(throttle, dtype=np.float64)

    state = np.zeros(brake.shape, dtype=np.int8)
    state[throttle > throttle_threshold] = 1
    # Braking wins when both are applied: left-foot braking into a corner is
    # braking, whatever the throttle is doing.
    state[brake > brake_threshold] = -1
    return state


def position_at_distance(
    path: TrackPath,
    distance_m: np.ndarray,
    query_m: float,
) -> tuple[float, float]:
    """Point on the path at a given distance around the lap.

    Places the chart cursor's marker on the map, and the two markers when
    comparing laps.
    """
    distance = np.asarray(distance_m, dtype=np.float64)
    if len(path.x_m) == 0 or distance.size != len(path.x_m):
        return (float("nan"), float("nan"))
    return (
        float(np.interp(query_m, distance, path.x_m)),
        float(np.interp(query_m, distance, path.y_m)),
    )
