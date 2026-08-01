"""Tests for the theoretical ideal lap."""

from __future__ import annotations

import numpy as np
import pytest

from lmu_telemetry.analysis import ideal_lap
from lmu_telemetry.core.models import Corner


def make_corner(index: int, apex: float) -> Corner:
    return Corner(index=index, apex_distance_m=apex, minimum_speed_ms=30.0)


def constant_speed_lap(grid: np.ndarray, speed: float):
    """Elapsed time and speed for a lap driven at one speed throughout."""
    return grid / speed, np.full_like(grid, speed)


# --------------------------------------------------------------------------- #
# Segment boundaries
# --------------------------------------------------------------------------- #

def test_boundaries_fall_between_apexes_never_on_them():
    """A boundary at an apex would split a corner across two segments, so its
    entry could be credited to one lap and its exit to another - and a corner is
    driven as one action."""
    corners = [make_corner(0, 100.0), make_corner(1, 500.0), make_corner(2, 900.0)]

    boundaries = ideal_lap.segment_boundaries(corners, lap_length_m=1000.0)

    assert boundaries.tolist() == [0.0, 300.0, 700.0, 1000.0]
    for corner in corners:
        assert corner.apex_distance_m not in boundaries.tolist()


def test_each_segment_contains_exactly_one_apex():
    corners = [make_corner(0, 100.0), make_corner(1, 500.0), make_corner(2, 900.0)]
    boundaries = ideal_lap.segment_boundaries(corners, 1000.0)

    for corner in corners:
        inside = np.sum(
            (boundaries[:-1] <= corner.apex_distance_m)
            & (boundaries[1:] > corner.apex_distance_m)
        )
        assert inside == 1


def test_boundary_position_is_configurable():
    corners = [make_corner(0, 100.0), make_corner(1, 500.0)]

    early = ideal_lap.segment_boundaries(corners, 1000.0, boundary_position=0.25)
    assert early[1] == pytest.approx(200.0)


def test_a_lap_with_no_corners_is_one_segment():
    boundaries = ideal_lap.segment_boundaries([], 1000.0)
    assert boundaries.tolist() == [0.0, 1000.0]


def test_boundaries_on_the_synthetic_circuit(synthetic_lap):
    from lmu_telemetry.analysis import corners as corner_detection

    found = corner_detection.detect_corners(
        synthetic_lap.speed_ms, synthetic_lap.distance_m,
        synthetic_lap.brake, synthetic_lap.throttle,
    )
    boundaries = ideal_lap.segment_boundaries(found, synthetic_lap.lap_length_m)

    # Four corners give four segments.
    assert len(boundaries) == 5
    # Every boundary must land on a straight, where the car is fast.
    for boundary in boundaries[1:-1]:
        index = int(np.searchsorted(synthetic_lap.distance_m, boundary))
        assert synthetic_lap.speed_ms[index] > synthetic_lap.speed_ms.max() * 0.85


# --------------------------------------------------------------------------- #
# Assembly
# --------------------------------------------------------------------------- #

def test_ideal_lap_is_never_slower_than_the_best_real_lap():
    """It takes the best of every segment, so by construction it cannot lose."""
    grid = np.arange(0.0, 1001.0)
    corners = [make_corner(0, 250.0), make_corner(1, 750.0)]

    elapsed_a, speed_a = constant_speed_lap(grid, 50.0)
    elapsed_b, speed_b = constant_speed_lap(grid, 45.0)

    result = ideal_lap.build_ideal_lap(
        {0: elapsed_a, 1: elapsed_b}, {0: speed_a, 1: speed_b}, grid, corners
    )

    assert result.total_time_s <= result.best_real_time_s + 1e-9


def test_ideal_lap_takes_the_best_segment_from_each_contributor():
    """Lap A is quicker in the first half, lap B in the second. The ideal lap
    must be faster than either, and must draw on both."""
    grid = np.arange(0.0, 1001.0)
    corners = [make_corner(0, 250.0), make_corner(1, 750.0)]
    boundary = 500

    # Lap A: fast then slow. Lap B: slow then fast.
    speed_a = np.where(grid < boundary, 60.0, 40.0)
    speed_b = np.where(grid < boundary, 40.0, 60.0)
    elapsed_a = np.concatenate([[0.0], np.cumsum(np.diff(grid) / speed_a[1:])])
    elapsed_b = np.concatenate([[0.0], np.cumsum(np.diff(grid) / speed_b[1:])])

    result = ideal_lap.build_ideal_lap(
        {0: elapsed_a, 1: elapsed_b}, {0: speed_a, 1: speed_b}, grid, corners
    )

    assert result.n_contributing_laps == 2
    assert result.total_time_s < result.best_real_time_s
    assert result.gain_over_best_real_s > 0


def test_one_contributing_lap_means_the_target_is_achievable():
    """When a single lap wins every segment, the ideal lap *is* that lap and is
    therefore known to be physically possible."""
    grid = np.arange(0.0, 1001.0)
    corners = [make_corner(0, 250.0), make_corner(1, 750.0)]

    elapsed_a, speed_a = constant_speed_lap(grid, 50.0)
    elapsed_b, speed_b = constant_speed_lap(grid, 45.0)

    result = ideal_lap.build_ideal_lap(
        {0: elapsed_a, 1: elapsed_b}, {0: speed_a, 1: speed_b}, grid, corners
    )

    assert result.n_contributing_laps == 1
    assert result.total_time_s == pytest.approx(result.best_real_time_s, rel=1e-6)


def test_segment_times_are_differences_not_absolute_times():
    """Otherwise a lap that was quick early would win every later segment simply
    by having arrived there sooner."""
    grid = np.arange(0.0, 1001.0)
    corners = [make_corner(0, 250.0), make_corner(1, 750.0)]

    fast_start = np.where(grid < 500, 100.0, 20.0)
    slow_start = np.where(grid < 500, 20.0, 100.0)
    elapsed_fast = np.concatenate([[0.0], np.cumsum(np.diff(grid) / fast_start[1:])])
    elapsed_slow = np.concatenate([[0.0], np.cumsum(np.diff(grid) / slow_start[1:])])

    result = ideal_lap.build_ideal_lap(
        {0: elapsed_fast, 1: elapsed_slow}, {0: fast_start, 1: slow_start},
        grid, corners,
    )

    assert result.segments[0].best_lap_index == 0
    assert result.segments[-1].best_lap_index == 1


def test_no_laps_yields_nothing():
    assert ideal_lap.build_ideal_lap({}, {}, np.arange(10.0), []) is None


def test_segment_spread_reports_the_range():
    segment = ideal_lap.Segment(
        index=0, start_m=0.0, end_m=100.0, best_lap_index=1,
        best_time_s=2.0, times_s={0: 2.5, 1: 2.0, 2: 2.2},
    )
    assert segment.spread_s == pytest.approx(0.5)
    assert segment.length_m == pytest.approx(100.0)


# --------------------------------------------------------------------------- #
# The discontinuities, which must be visible rather than smoothed
# --------------------------------------------------------------------------- #

def discontinuous_pair(grid: np.ndarray):
    """Two laps whose winning segments do not meet at the same speed.

    Lap A is quicker in the first half and lap B in the second, but A is doing
    60 m/s where it hands over and B is doing 45 - so the stitched lap gains
    speed instantaneously, which no car can do.

    Constructed deliberately: two laps that happen to be travelling at the same
    speed at the seam produce a continuous ideal lap, which is a legitimate
    outcome and would test nothing here.
    """
    speed_a = np.where(grid < 500, 60.0, 25.0)
    speed_b = np.where(grid < 500, 25.0, 45.0)
    elapsed_a = np.concatenate([[0.0], np.cumsum(np.diff(grid) / speed_a[1:])])
    elapsed_b = np.concatenate([[0.0], np.cumsum(np.diff(grid) / speed_b[1:])])
    return (
        {0: elapsed_a, 1: elapsed_b},
        {0: speed_a, 1: speed_b},
    )


def test_stitching_different_laps_creates_speed_discontinuities():
    """The evidence that the target is synthetic. Where two segments from
    different laps meet, the speed jumps - no car can do that."""
    grid = np.arange(0.0, 1001.0)
    corners = [make_corner(0, 250.0), make_corner(1, 750.0)]
    elapsed, speeds = discontinuous_pair(grid)

    result = ideal_lap.build_ideal_lap(elapsed, speeds, grid, corners)

    assert result.n_contributing_laps == 2
    significant = ideal_lap.significant_discontinuities(result, threshold_ms=1.0)
    assert significant
    assert any(abs(seam.jump_ms) == pytest.approx(15.0) for seam in significant)


def test_no_discontinuity_when_one_lap_wins_everything():
    grid = np.arange(0.0, 1001.0)
    corners = [make_corner(0, 250.0), make_corner(1, 750.0)]

    elapsed_a, speed_a = constant_speed_lap(grid, 50.0)
    elapsed_b, speed_b = constant_speed_lap(grid, 45.0)

    result = ideal_lap.build_ideal_lap(
        {0: elapsed_a, 1: elapsed_b}, {0: speed_a, 1: speed_b}, grid, corners
    )

    assert ideal_lap.significant_discontinuities(result, threshold_ms=1.0) == []


def test_discontinuities_are_not_smoothed_away():
    """The stitched speed trace must keep its jumps: smoothing them would hide
    exactly the evidence that the lap never happened."""
    grid = np.arange(0.0, 1001.0)
    corners = [make_corner(0, 250.0), make_corner(1, 750.0)]
    elapsed, speeds = discontinuous_pair(grid)

    result = ideal_lap.build_ideal_lap(elapsed, speeds, grid, corners)

    jumps = np.abs(np.diff(result.speed_ms[~np.isnan(result.speed_ms)]))
    assert np.nanmax(jumps) == pytest.approx(15.0)


def test_the_caveat_is_stated_on_the_object():
    """The specification requires the optimism to be documented wherever the
    ideal lap is used, so it travels with the value rather than living only in
    a docstring."""
    assert "not guaranteed" in ideal_lap.IdealLap.CAVEAT
    assert "target" in ideal_lap.IdealLap.CAVEAT


# --------------------------------------------------------------------------- #
# On the synthetic circuit
# --------------------------------------------------------------------------- #

def test_ideal_lap_of_identical_laps_equals_the_lap(synthetic_lap):
    """Two identical laps cannot produce a faster ideal lap. Anything else would
    mean the segment arithmetic is inventing time."""
    from lmu_telemetry.analysis import corners as corner_detection, delta

    found = corner_detection.detect_corners(
        synthetic_lap.speed_ms, synthetic_lap.distance_m,
        synthetic_lap.brake, synthetic_lap.throttle,
    )
    grid = synthetic_lap.distance_m
    elapsed = delta.elapsed_time(grid, synthetic_lap.times_s, grid)

    result = ideal_lap.build_ideal_lap(
        {0: elapsed, 1: elapsed.copy()},
        {0: synthetic_lap.speed_ms, 1: synthetic_lap.speed_ms.copy()},
        grid, found,
    )

    assert result.total_time_s == pytest.approx(synthetic_lap.lap_time_s, rel=1e-3)
    assert ideal_lap.significant_discontinuities(result) == []
