"""Tests for corner detection and per-corner measurement."""

from __future__ import annotations

import numpy as np
import pytest

from lmu_telemetry.analysis import corners
from lmu_telemetry.analysis.corners import CornerDetectionSettings
from lmu_telemetry.core.models import Corner


def detect(lap, **overrides):
    settings = CornerDetectionSettings(**overrides)
    return corners.detect_corners(
        lap.speed_ms, lap.distance_m, lap.brake, lap.throttle, settings
    )


# --------------------------------------------------------------------------- #
# The property the specification names
# --------------------------------------------------------------------------- #

def test_four_corners_are_found_on_the_rectangular_circuit(synthetic_lap):
    """The circuit has exactly four corners, by construction."""
    found = detect(synthetic_lap)
    assert len(found) == 4


def test_apexes_land_on_the_real_corners(synthetic_lap):
    """Each detected apex must fall within the corner it belongs to.

    The arc is 78.5 m long, so half of it - about 39 m - is the furthest a
    correctly identified apex can be from the geometric midpoint.
    """
    found = detect(synthetic_lap)
    detected = np.array([c.apex_distance_m for c in found])
    expected = synthetic_lap.corner_apex_distances_m

    assert np.allclose(detected, expected, atol=40.0)


def test_minimum_speed_matches_the_cornering_limit(synthetic_lap):
    """Corner speed is set by `v = sqrt(a_lat * R)`, which for the synthetic
    lap is sqrt(1.4 * 9.80665 * 50) = 26.2 m/s."""
    found = detect(synthetic_lap)
    expected = np.sqrt(1.4 * 9.80665 * 50.0)

    for corner in found:
        assert corner.minimum_speed_ms == pytest.approx(expected, rel=0.02)


# --------------------------------------------------------------------------- #
# Detection behaviour
# --------------------------------------------------------------------------- #

def test_a_flat_lap_has_no_corners():
    grid = np.arange(0.0, 1000.0)
    speed = np.full_like(grid, 60.0)
    found = corners.detect_corners(
        speed, grid, np.zeros_like(grid), np.ones_like(grid)
    )
    assert found == []


def test_a_shallow_dip_is_not_a_corner():
    """Above the speed threshold, a dip is a kink to be driven through, not a
    corner to analyse."""
    grid = np.arange(0.0, 1000.0)
    speed = np.full_like(grid, 60.0)
    speed[500:520] = 58.0  # a 3% dip, well above 85% of maximum

    found = corners.detect_corners(
        speed, grid, np.zeros_like(grid), np.ones_like(grid)
    )
    assert found == []


def test_two_close_minima_are_one_corner():
    """A double apex is one corner to a driver."""
    grid = np.arange(0.0, 1000.0)
    speed = np.full_like(grid, 60.0)
    speed[480:500] = 30.0
    speed[510:530] = 30.0  # 30 m apart, below the 50 m separation threshold

    found = corners.detect_corners(
        speed, grid, np.zeros_like(grid), np.ones_like(grid),
        CornerDetectionSettings(min_separation_m=50.0),
    )
    assert len(found) == 1


def test_separated_minima_are_two_corners():
    grid = np.arange(0.0, 1000.0)
    speed = np.full_like(grid, 60.0)
    speed[300:320] = 30.0
    speed[600:620] = 30.0

    found = corners.detect_corners(
        speed, grid, np.zeros_like(grid), np.ones_like(grid),
        CornerDetectionSettings(min_separation_m=50.0),
    )
    assert len(found) == 2


def test_detection_is_robust_to_noise(synthetic_lap):
    """Savitzky-Golay smoothing exists for this: sample noise must not create
    corners, and must not move the ones that are real."""
    rng = np.random.default_rng(seed=20260731)
    noisy = synthetic_lap.speed_ms + rng.normal(0.0, 0.3, synthetic_lap.speed_ms.shape)

    found = corners.detect_corners(
        noisy, synthetic_lap.distance_m,
        synthetic_lap.brake, synthetic_lap.throttle,
    )

    assert len(found) == 4
    detected = np.array([c.apex_distance_m for c in found])
    assert np.allclose(detected, synthetic_lap.corner_apex_distances_m, atol=40.0)


def test_smoothing_does_not_move_a_minimum():
    """A moving average would shift and flatten extrema; the position of the
    minimum is exactly what is being measured."""
    grid = np.arange(0.0, 400.0)
    speed = 60.0 - 30.0 * np.exp(-((grid - 200.0) ** 2) / 800.0)

    smoothed = corners.smooth_speed(speed, 1.0, CornerDetectionSettings())

    assert int(np.argmin(smoothed)) == pytest.approx(200, abs=3)


def test_degenerate_input_is_handled():
    assert corners.detect_corners(np.array([]), np.array([]), np.array([]), np.array([])) == []
    tiny = np.ones(3)
    assert corners.detect_corners(tiny, np.arange(3.0), tiny, tiny) == []
    # Mismatched lengths must not raise.
    assert corners.detect_corners(np.ones(10), np.arange(5.0), np.ones(10), np.ones(10)) == []


# --------------------------------------------------------------------------- #
# Per-corner measurement
# --------------------------------------------------------------------------- #

def test_braking_point_precedes_the_apex(synthetic_lap):
    found = detect(synthetic_lap)
    for corner in found:
        assert corner.braking_distance_m is not None
        assert corner.braking_distance_m < corner.apex_distance_m


def test_entry_speed_exceeds_apex_speed(synthetic_lap):
    """The car is slowing between the braking point and the apex."""
    found = detect(synthetic_lap)
    for corner in found:
        assert corner.entry_speed_ms > corner.minimum_speed_ms


def test_throttle_point_follows_the_apex(synthetic_lap):
    found = detect(synthetic_lap)
    for corner in found:
        assert corner.throttle_distance_m is not None
        assert corner.throttle_distance_m >= corner.apex_distance_m


def test_a_single_noisy_sample_is_not_a_braking_point():
    """Sustained application is what separates braking from a twitch."""
    grid = np.arange(0.0, 600.0)
    speed = np.full_like(grid, 60.0)
    speed[280:320] = 30.0
    brake = np.zeros_like(grid)
    brake[100] = 1.0  # one isolated sample, far from the corner
    brake[240:280] = 0.8  # the real braking zone

    found = corners.detect_corners(
        speed, grid, brake, np.zeros_like(grid),
        CornerDetectionSettings(brake_min_duration_s=0.1),
    )

    assert len(found) == 1
    assert found[0].braking_distance_m >= 240.0


def test_a_corner_taken_without_braking_reports_no_braking_point():
    grid = np.arange(0.0, 600.0)
    speed = np.full_like(grid, 60.0)
    speed[280:320] = 30.0

    found = corners.detect_corners(
        speed, grid, np.zeros_like(grid), np.zeros_like(grid)
    )

    assert len(found) == 1
    assert found[0].braking_distance_m is None
    assert found[0].entry_speed_ms is None
    assert found[0].braking_length_m is None


def test_coasting_is_measured_in_seconds():
    """Neither pedal applied, converted from metres to time by local speed."""
    grid = np.arange(0.0, 600.0)
    speed = np.full_like(grid, 30.0)
    speed[280:320] = 15.0
    brake = np.zeros_like(grid)
    throttle = np.zeros_like(grid)

    found = corners.detect_corners(speed, grid, brake, throttle)

    assert len(found) == 1
    # The whole 600 m window is coasting; at 30 m/s that is about 20 s.
    assert found[0].coasting_time_s > 15.0


def test_full_throttle_means_no_coasting(synthetic_lap):
    found = detect(synthetic_lap)
    # The synthetic driver is always on one pedal or the other.
    for corner in found:
        assert corner.coasting_time_s < 1.0


# --------------------------------------------------------------------------- #
# Windows and matching
# --------------------------------------------------------------------------- #

def test_corner_windows_tile_the_lap_without_overlap():
    windows = corners.corner_windows(np.array([100, 300, 700]), 1000)

    assert windows[0][0] == 0
    assert windows[-1][1] == 1000
    for (_start, end), (next_start, _next_end) in zip(windows, windows[1:]):
        assert end == next_start


def test_corner_windows_of_an_empty_lap():
    assert corners.corner_windows(np.array([], dtype=int), 1000) == []


def make_corner(index: int, apex: float) -> Corner:
    return Corner(index=index, apex_distance_m=apex, minimum_speed_ms=30.0)


def test_corners_match_across_laps_by_distance():
    """Corner identity is by distance from the line, which is what lets a corner
    keep the name the user gave it."""
    reference = [make_corner(0, 100.0), make_corner(1, 500.0), make_corner(2, 900.0)]
    this_lap = [make_corner(0, 103.0), make_corner(1, 495.0), make_corner(2, 904.0)]

    assert corners.match_corners(this_lap, reference, tolerance_m=50.0) == {0: 0, 1: 1, 2: 2}


def test_an_unmatched_corner_is_omitted():
    """A corner the detector missed on one lap must not be silently paired with
    the wrong one."""
    reference = [make_corner(0, 100.0), make_corner(1, 500.0)]
    this_lap = [make_corner(0, 105.0)]

    assert corners.match_corners(this_lap, reference, tolerance_m=50.0) == {0: 0}


def test_matching_respects_the_tolerance():
    reference = [make_corner(0, 100.0)]
    this_lap = [make_corner(0, 400.0)]

    assert corners.match_corners(this_lap, reference, tolerance_m=50.0) == {}


def test_matching_handles_empty_input():
    assert corners.match_corners([], [make_corner(0, 100.0)]) == {}
    assert corners.match_corners([make_corner(0, 100.0)], []) == {}


def test_labels_fall_back_to_a_number():
    assert make_corner(0, 100.0).label == "C1"
    assert corners.apply_names([make_corner(0, 100.0)], {0: "Parabolica"})[0].label \
        == "Parabolica"


def test_apply_names_leaves_unnamed_corners_alone():
    result = corners.apply_names([make_corner(0, 1.0), make_corner(1, 2.0)], {1: "Lesmo"})
    assert result[0].label == "C1"
    assert result[1].label == "Lesmo"
