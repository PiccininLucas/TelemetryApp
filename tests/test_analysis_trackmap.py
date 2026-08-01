"""Tests for the track map: GPS projection and heading integration."""

from __future__ import annotations

import numpy as np
import pytest

from lmu_telemetry.analysis import trackmap


# --------------------------------------------------------------------------- #
# GPS projection
# --------------------------------------------------------------------------- #

def test_projection_returns_the_synthetic_path_it_came_from(synthetic_lap):
    """The synthetic GPS trace is the exact inverse of this projection, so a
    round trip must return the original geometry to sub-millimetre precision."""
    path = trackmap.project_gps(
        synthetic_lap.latitude_deg, synthetic_lap.longitude_deg
    )

    assert np.allclose(path.x_m, synthetic_lap.x_m, atol=1e-6)
    assert np.allclose(path.y_m, synthetic_lap.y_m, atol=1e-6)


def test_projected_lap_closes(synthetic_lap):
    """A lap ends where it started. This is the specification's "closed map"."""
    path = trackmap.project_gps(
        synthetic_lap.latitude_deg, synthetic_lap.longitude_deg
    )

    assert path.closure_error_m < 1.0


def test_projected_extent_matches_the_circuit(synthetic_lap):
    """200 m straights with 50 m corner radii give a 300 m square."""
    path = trackmap.project_gps(
        synthetic_lap.latitude_deg, synthetic_lap.longitude_deg
    )
    width, height = path.extent_m

    assert width == pytest.approx(300.0, abs=1.0)
    assert height == pytest.approx(300.0, abs=1.0)


def test_projected_path_length_matches_the_perimeter(synthetic_lap):
    path = trackmap.project_gps(
        synthetic_lap.latitude_deg, synthetic_lap.longitude_deg
    )
    assert path.path_length_m == pytest.approx(synthetic_lap.lap_length_m, rel=1e-3)


def test_longitude_is_scaled_by_cos_latitude():
    """Without the `cos(lat0)` factor a circuit at Le Mans, 47 degrees north,
    would come out stretched east-west by about 47%."""
    latitude = np.array([47.95, 47.95])
    longitude = np.array([0.22, 0.23])

    path = trackmap.project_gps(latitude, longitude)

    expected = (
        trackmap.EARTH_RADIUS_M * np.radians(0.01) * np.cos(np.radians(47.95))
    )
    assert path.x_m[1] == pytest.approx(expected)
    # A projection ignoring the factor would give this instead.
    assert path.x_m[1] < trackmap.EARTH_RADIUS_M * np.radians(0.01)


def test_origin_is_the_first_point():
    path = trackmap.project_gps(np.array([10.0, 11.0]), np.array([20.0, 21.0]))

    assert path.x_m[0] == 0.0
    assert path.y_m[0] == 0.0
    assert path.origin_lat_deg == 10.0
    assert path.origin_lon_deg == 20.0


def test_projection_of_nothing():
    path = trackmap.project_gps(np.array([]), np.array([]))
    assert path.x_m.size == 0
    assert path.closure_error_m == 0.0
    assert path.extent_m == (0.0, 0.0)


# --------------------------------------------------------------------------- #
# Heading integration
# --------------------------------------------------------------------------- #

def test_straight_line_keeps_its_heading():
    times = np.linspace(0.0, 10.0, 101)
    heading = trackmap.integrate_heading(
        np.zeros_like(times), np.full_like(times, 50.0), times
    )
    assert np.allclose(heading, 0.0)


def test_steady_cornering_turns_at_the_expected_rate():
    """`omega = a_y / V`. At 1 g and 30 m/s that is 0.327 rad/s, so after 4.8 s
    the car has turned a quarter circle."""
    times = np.linspace(0.0, 4.8, 481)
    speed = np.full_like(times, 30.0)
    lateral_g = np.ones_like(times)

    heading = trackmap.integrate_heading(lateral_g, speed, times)

    expected_rate = trackmap.STANDARD_GRAVITY / 30.0
    assert heading[-1] == pytest.approx(expected_rate * 4.8, rel=1e-6)
    assert heading[-1] == pytest.approx(np.pi / 2, rel=0.02)


def test_positive_lateral_g_turns_right():
    """Sign convention: positive lateral acceleration is a right-hand corner,
    and the path must bend toward +x."""
    times = np.linspace(0.0, 5.0, 501)
    speed = np.full_like(times, 30.0)

    path = trackmap.reconstruct_from_lateral_g(
        np.ones_like(times), speed, times
    )

    assert path.x_m[-1] > 0.0


def test_low_speed_samples_do_not_inject_rotation():
    """`omega = a_y / V` blows up as speed approaches zero, and one such sample
    would rotate every point that follows by an arbitrary amount."""
    times = np.linspace(0.0, 10.0, 1001)
    speed = np.full_like(times, 30.0)
    speed[500:510] = 0.01
    lateral_g = np.zeros_like(times)
    lateral_g[500:510] = 1.0

    heading = trackmap.integrate_heading(lateral_g, speed, times, min_speed_ms=5.0)

    assert np.all(np.abs(heading) < 1e-9)


def test_a_full_circle_closes():
    """Integrating a constant yaw rate for exactly one revolution returns the
    car to its starting point."""
    radius, speed_ms = 50.0, 30.0
    period = 2 * np.pi * radius / speed_ms
    times = np.linspace(0.0, period, 20001)

    lateral_g = np.full_like(times, speed_ms**2 / radius / trackmap.STANDARD_GRAVITY)
    path = trackmap.reconstruct_from_lateral_g(
        lateral_g, np.full_like(times, speed_ms), times
    )

    assert path.closure_error_m < 0.5
    assert np.ptp(path.x_m) == pytest.approx(2 * radius, rel=1e-3)


def test_heading_integration_of_nothing():
    assert trackmap.integrate_heading(np.array([]), np.array([]), np.array([])).size == 0
    assert trackmap.integrate_path(np.array([]), np.array([]), np.array([])).x_m.size == 0


# --------------------------------------------------------------------------- #
# Comparing the two reconstructions
# --------------------------------------------------------------------------- #

def test_the_two_reconstructions_agree_on_the_synthetic_lap(synthetic_lap):
    """The synthetic lap satisfies the quasi-steady assumption exactly - it has
    no sideslip and no transients - so the integrated path must reproduce the
    GPS one closely. On real data it will not, which is the point of measuring.
    """
    gps = trackmap.project_gps(
        synthetic_lap.latitude_deg, synthetic_lap.longitude_deg
    )
    integrated = trackmap.reconstruct_from_lateral_g(
        synthetic_lap.lateral_g, synthetic_lap.speed_ms, synthetic_lap.times_s
    )

    comparison = trackmap.compare_paths(gps, integrated)

    assert comparison.mean_error_m < 5.0
    assert comparison.integrated_closure_error_m < 10.0


def test_comparison_is_insensitive_to_the_initial_heading(synthetic_lap):
    """The initial heading is unknowable from the data, so a fixed rotation is
    not an error in the reconstruction and must be aligned away."""
    gps = trackmap.project_gps(
        synthetic_lap.latitude_deg, synthetic_lap.longitude_deg
    )

    aligned_north = trackmap.reconstruct_from_lateral_g(
        synthetic_lap.lateral_g, synthetic_lap.speed_ms, synthetic_lap.times_s,
        initial_heading_rad=0.0,
    )
    rotated = trackmap.reconstruct_from_lateral_g(
        synthetic_lap.lateral_g, synthetic_lap.speed_ms, synthetic_lap.times_s,
        initial_heading_rad=1.234,
    )

    first = trackmap.compare_paths(gps, aligned_north)
    second = trackmap.compare_paths(gps, rotated)

    assert first.mean_error_m == pytest.approx(second.mean_error_m, rel=1e-6)


def test_comparison_of_mismatched_lengths_is_nan_not_a_crash():
    a = trackmap.TrackPath(np.zeros(10), np.zeros(10))
    b = trackmap.TrackPath(np.zeros(5), np.zeros(5))

    comparison = trackmap.compare_paths(a, b)
    assert np.isnan(comparison.mean_error_m)


# --------------------------------------------------------------------------- #
# Presentation helpers
# --------------------------------------------------------------------------- #

def test_pedal_state_classification():
    brake = np.array([0.5, 0.0, 0.0, 0.4])
    throttle = np.array([0.0, 0.0, 0.8, 0.9])

    state = trackmap.pedal_state(brake, throttle)

    assert state.tolist() == [-1, 0, 1, -1]


def test_braking_wins_when_both_pedals_are_applied():
    """Left-foot braking into a corner is braking, whatever the throttle does."""
    state = trackmap.pedal_state(np.array([0.5]), np.array([0.9]))
    assert state[0] == -1


def test_position_at_distance_interpolates_along_the_path():
    path = trackmap.TrackPath(np.array([0.0, 10.0, 20.0]), np.array([0.0, 0.0, 0.0]))
    positions = np.array([0.0, 100.0, 200.0])

    x, y = trackmap.position_at_distance(path, positions, 50.0)

    assert x == pytest.approx(5.0)
    assert y == pytest.approx(0.0)


def test_position_at_distance_of_an_empty_path_is_nan():
    empty = trackmap.TrackPath(np.array([]), np.array([]))
    x, y = trackmap.position_at_distance(empty, np.array([]), 10.0)
    assert np.isnan(x) and np.isnan(y)
