"""Tests for distance reconstruction and distance-domain resampling."""

from __future__ import annotations

import numpy as np
import pytest

from lmu_telemetry.analysis import distance, resample


# --------------------------------------------------------------------------- #
# Integration
# --------------------------------------------------------------------------- #

def test_constant_speed_gives_exact_distance():
    """The simplest closed form: 20 m/s for 10 s is 200 m."""
    times = np.linspace(0.0, 10.0, 1001)
    speed = np.full_like(times, 20.0)

    result = distance.cumulative_distance(speed, times)

    assert result[0] == 0.0
    assert result[-1] == pytest.approx(200.0)


def test_constant_acceleration_matches_the_kinematic_equation():
    """s = v0*t + a*t^2/2. The trapezoidal rule is exact for linear speed, so
    this must agree to machine precision, not merely closely."""
    times = np.linspace(0.0, 10.0, 1001)
    v0, acceleration = 10.0, 2.0
    speed = v0 + acceleration * times

    result = distance.cumulative_distance(speed, times)
    expected = v0 * times + 0.5 * acceleration * times**2

    assert np.allclose(result, expected, atol=1e-9)


def test_integration_handles_degenerate_input():
    assert distance.cumulative_distance(np.array([]), np.array([])).size == 0
    assert distance.cumulative_distance(np.array([5.0]), np.array([0.0])) == 0.0


def test_mismatched_lengths_are_rejected():
    with pytest.raises(ValueError, match="same shape"):
        distance.cumulative_distance(np.zeros(5), np.zeros(4))


def test_round_trip_through_differentiation():
    """Differentiating the reconstructed distance must return the speed.

    Compared on the interior only. `np.gradient` uses a second-order central
    difference inside the array but falls back to a one-sided first-order
    difference at each end, so the two endpoints are systematically less
    accurate - a property of the derivative, not of the reconstruction.
    """
    times = np.linspace(0.0, 20.0, 2001)
    speed = 30.0 + 10.0 * np.sin(times / 3.0)

    reconstructed = distance.cumulative_distance(speed, times)
    recovered = distance.speed_from_distance(reconstructed, times)

    assert np.allclose(recovered[1:-1], speed[1:-1], atol=1e-3)


# --------------------------------------------------------------------------- #
# Scale correction
# --------------------------------------------------------------------------- #

def test_scale_correction_closes_the_lap_on_its_known_length():
    """Integration drifts; the known lap length pulls it back."""
    times = np.linspace(0.0, 100.0, 10001)
    speed = np.full_like(times, 50.0)  # integrates to 5000 m

    result = distance.reconstruct(speed, times, reference_length_m=5100.0)

    assert result.correction_applied
    assert result.scale_factor == pytest.approx(5100.0 / 5000.0)
    assert result.corrected_m[-1] == pytest.approx(5100.0)
    assert result.integrated_length_m == pytest.approx(5000.0)
    assert result.drift_m == pytest.approx(-100.0)


def test_correction_distributes_the_drift_proportionally():
    """Right when the error is a bias rather than a single event: halfway
    around the lap, half the correction has been applied."""
    times = np.linspace(0.0, 100.0, 10001)
    speed = np.full_like(times, 50.0)

    result = distance.reconstruct(speed, times, reference_length_m=5100.0)
    midpoint = len(result.corrected_m) // 2

    assert result.corrected_m[midpoint] == pytest.approx(2550.0, rel=1e-3)


def test_raw_distance_is_kept_alongside_the_correction():
    """Both versions are kept so the correction can be plotted and defended."""
    times = np.linspace(0.0, 100.0, 10001)
    speed = np.full_like(times, 50.0)

    result = distance.reconstruct(speed, times, reference_length_m=5100.0)

    assert result.raw_m[-1] == pytest.approx(5000.0)
    assert result.corrected_m[-1] == pytest.approx(5100.0)
    assert not np.allclose(result.raw_m, result.corrected_m)


def test_no_reference_means_no_correction():
    times = np.linspace(0.0, 100.0, 1001)
    speed = np.full_like(times, 50.0)

    result = distance.reconstruct(speed, times, reference_length_m=None)

    assert not result.correction_applied
    assert result.scale_factor == 1.0
    assert np.array_equal(result.raw_m, result.corrected_m)


@pytest.mark.parametrize("reference_length", [2000.0, 20000.0])
def test_an_implausible_scale_factor_is_refused(reference_length):
    """A factor far from 1 means something upstream is wrong - most likely a
    partial lap being scaled to a full lap's length. Stretching it anyway would
    produce a distance axis that looks fine and is silently a lie."""
    times = np.linspace(0.0, 100.0, 1001)
    speed = np.full_like(times, 50.0)  # 5000 m

    result = distance.reconstruct(speed, times, reference_length_m=reference_length)

    assert not result.correction_applied
    assert np.array_equal(result.corrected_m, result.raw_m)


def test_reconstruction_recovers_the_synthetic_lap_length(synthetic_lap):
    """The synthetic lap's geometry is exact, and its times come from
    `dt = ds/v`, so integrating the speed back must return the perimeter.

    Not to machine precision: the lap's times were built as the trapezoidal
    integral of `1/v` over distance, and the reconstruction is the trapezoidal
    integral of `v` over time. Two trapezoidal approximations are not exact
    inverses, and each contributes an error of order `h^2` per step. Over
    1114 steps that accumulates to about 0.15 m, or 0.014% - which is far below
    the drift the scale correction exists to remove, and is the reason the
    correction is expressed as a ratio rather than an offset.
    """
    result = distance.reconstruct(synthetic_lap.speed_ms, synthetic_lap.times_s)

    assert result.integrated_length_m == pytest.approx(
        synthetic_lap.lap_length_m, rel=1e-3
    )
    error_m = abs(result.integrated_length_m - synthetic_lap.lap_length_m)
    assert error_m < 0.5


def test_lap_length_from_channel():
    lap_distance = np.array([0.0, 100.0, 4000.0, 5792.0, 0.0, 50.0])
    assert distance.lap_length_from_channel(lap_distance) == pytest.approx(5792.0)


def test_lap_length_from_channel_rejects_useless_input():
    assert distance.lap_length_from_channel(np.array([])) is None
    assert distance.lap_length_from_channel(np.array([np.nan, np.nan])) is None
    assert distance.lap_length_from_channel(np.array([0.0, 0.0])) is None


# --------------------------------------------------------------------------- #
# Resampling
# --------------------------------------------------------------------------- #

def test_distance_grid_spans_the_lap():
    grid = resample.distance_grid(100.0, step_m=1.0)
    assert grid[0] == 0.0
    assert grid[-1] == 100.0
    assert len(grid) == 101


def test_distance_grid_rejects_nonsense():
    assert resample.distance_grid(0.0).size == 0
    assert resample.distance_grid(-5.0).size == 0
    assert resample.distance_grid(100.0, step_m=0.0).size == 0


def test_make_monotonic_turns_a_reversal_into_a_flat_section():
    """A spin or a reverse out of gravel produces a genuine decrease, and
    interpolation needs an increasing axis. A running maximum says the car never
    un-drove a metre it had already driven."""
    raw = np.array([0.0, 10.0, 20.0, 15.0, 12.0, 25.0, 30.0])
    result = resample.make_monotonic(raw)

    assert np.all(np.diff(result) >= 0)
    assert result.tolist() == [0.0, 10.0, 20.0, 20.0, 20.0, 25.0, 30.0]


def test_make_monotonic_leaves_a_clean_series_alone():
    clean = np.array([0.0, 1.0, 2.0, 3.0])
    assert np.array_equal(resample.make_monotonic(clean), clean)


def test_resample_interpolates_continuous_channels():
    values = np.array([0.0, 10.0, 20.0])
    positions = np.array([0.0, 100.0, 200.0])
    grid = np.array([0.0, 50.0, 150.0, 200.0])

    result = resample.resample(values, positions, grid)
    assert result.tolist() == pytest.approx([0.0, 5.0, 15.0, 20.0])


def test_resample_holds_discrete_channels():
    """Between gear 3 and gear 4 there is no gear 3.5."""
    gears = np.array([3.0, 4.0, 5.0])
    positions = np.array([0.0, 100.0, 200.0])
    grid = np.array([0.0, 50.0, 99.0, 100.0, 150.0])

    result = resample.resample(gears, positions, grid, discrete=True)

    assert result.tolist() == [3.0, 3.0, 3.0, 4.0, 4.0]
    assert set(np.unique(result)) <= {3.0, 4.0, 5.0}


def test_resample_handles_per_wheel_channels():
    values = np.array([[1.0, 2.0, 3.0, 4.0], [5.0, 6.0, 7.0, 8.0]])
    positions = np.array([0.0, 100.0])
    grid = np.array([0.0, 50.0, 100.0])

    result = resample.resample(values, positions, grid)

    assert result.shape == (3, 4)
    assert result[1].tolist() == pytest.approx([3.0, 4.0, 5.0, 6.0])


def test_resample_clamps_rather_than_extrapolating():
    """Beyond the lap, repeating the edge sample beats inventing values."""
    result = resample.resample(
        np.array([10.0, 20.0]), np.array([0.0, 100.0]),
        np.array([-50.0, 150.0]),
    )
    assert result.tolist() == [10.0, 20.0]


def test_resample_survives_a_non_monotonic_distance():
    """The real reason `make_monotonic` exists: np.interp silently returns
    nonsense for a decreasing x axis rather than raising."""
    values = np.array([0.0, 10.0, 20.0, 30.0])
    positions = np.array([0.0, 100.0, 90.0, 200.0])

    result = resample.resample(values, positions, np.array([0.0, 100.0, 200.0]))

    assert np.all(np.isfinite(result))
    assert result[0] == pytest.approx(0.0)
    assert result[-1] == pytest.approx(30.0)


def test_resample_channels_applies_step_semantics_selectively():
    positions = np.array([0.0, 100.0])
    grid = np.array([0.0, 50.0, 100.0])
    channels = {
        "Ground Speed": np.array([50.0, 60.0]),
        "Gear": np.array([3.0, 4.0]),
    }

    result = resample.resample_channels(
        channels, positions, grid, discrete_names=frozenset({"Gear"})
    )

    assert result["Ground Speed"][1] == pytest.approx(55.0)
    assert result["Gear"][1] == 3.0


def test_align_to_common_grid_uses_the_shortest_lap():
    """Extending a lap past where it was measured would mean extrapolating."""
    laps = [
        (np.array([0.0, 10.0]), np.array([0.0, 1000.0])),
        (np.array([0.0, 10.0]), np.array([0.0, 900.0])),
    ]
    grid, resampled = resample.align_to_common_grid(laps, step_m=10.0)

    assert grid[-1] == pytest.approx(900.0)
    assert all(len(values) == len(grid) for values in resampled)


def test_align_to_common_grid_handles_no_laps():
    grid, resampled = resample.align_to_common_grid([])
    assert grid.size == 0
    assert resampled == []
