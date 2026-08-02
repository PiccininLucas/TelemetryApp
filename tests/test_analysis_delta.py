"""Tests for delta-t between laps."""

from __future__ import annotations

import numpy as np
import pytest

from lmu_telemetry.analysis import delta


def constant_speed_lap(speed_ms: float, length_m: float = 1000.0, n: int = 1001):
    """A lap at constant speed: distance and time both known in closed form."""
    positions = np.linspace(0.0, length_m, n)
    times = positions / speed_ms
    return positions, times


# --------------------------------------------------------------------------- #
# The property the specification names
# --------------------------------------------------------------------------- #

def test_a_lap_against_itself_is_exactly_zero(synthetic_lap):
    """The headline invariant. Any offset here is a bug in the alignment, and
    it would masquerade as a real time difference everywhere else."""
    result = delta.delta_time(
        synthetic_lap.distance_m, synthetic_lap.times_s,
        synthetic_lap.distance_m, synthetic_lap.times_s,
    )

    assert np.allclose(result.delta_s, 0.0, atol=1e-9)
    assert result.final_delta_s == pytest.approx(0.0, abs=1e-9)


def test_a_lap_against_itself_is_zero_with_a_shifted_time_origin(synthetic_lap):
    """The session clock does not start at the lap. A forgotten subtraction
    would show up as a constant offset that looks exactly like a real loss."""
    shifted = synthetic_lap.times_s + 1234.5

    result = delta.delta_time(
        synthetic_lap.distance_m, synthetic_lap.times_s,
        synthetic_lap.distance_m, shifted,
    )

    assert np.allclose(result.delta_s, 0.0, atol=1e-9)


# --------------------------------------------------------------------------- #
# Sign and magnitude
# --------------------------------------------------------------------------- #

def test_a_slower_lap_gives_a_positive_delta():
    """Positive means losing time, which is the convention every chart assumes."""
    fast_d, fast_t = constant_speed_lap(50.0)
    slow_d, slow_t = constant_speed_lap(45.0)

    result = delta.delta_time(fast_d, fast_t, slow_d, slow_t)

    assert result.final_delta_s > 0
    assert np.all(result.delta_s >= -1e-9)


def test_a_faster_lap_gives_a_negative_delta():
    fast_d, fast_t = constant_speed_lap(55.0)
    reference_d, reference_t = constant_speed_lap(50.0)

    result = delta.delta_time(reference_d, reference_t, fast_d, fast_t)

    assert result.final_delta_s < 0


def test_delta_matches_the_closed_form_for_constant_speeds():
    """Over 1000 m at 50 and 45 m/s the gap is 1000*(1/45 - 1/50) = 2.222 s."""
    reference_d, reference_t = constant_speed_lap(50.0)
    lap_d, lap_t = constant_speed_lap(45.0)

    result = delta.delta_time(reference_d, reference_t, lap_d, lap_t)

    expected = 1000.0 * (1.0 / 45.0 - 1.0 / 50.0)
    assert result.final_delta_s == pytest.approx(expected, rel=1e-6)


def test_delta_grows_linearly_when_the_deficit_is_uniform():
    """A constant speed ratio means time is lost at a constant rate, so the
    delta is a straight line - and its slope is what a chart reads as "losing
    time here"."""
    reference_d, reference_t = constant_speed_lap(50.0)
    lap_d, lap_t = constant_speed_lap(45.0)

    result = delta.delta_time(reference_d, reference_t, lap_d, lap_t)
    rate = result.gain_rate()

    assert np.allclose(rate[5:-5], rate[len(rate) // 2], rtol=1e-6)


def test_slower_synthetic_lap_loses_time_everywhere(
    synthetic_lap, slower_synthetic_lap
):
    """Same circuit, 3% slower everywhere: the delta must rise monotonically."""
    result = delta.delta_time(
        synthetic_lap.distance_m, synthetic_lap.times_s,
        slower_synthetic_lap.distance_m, slower_synthetic_lap.times_s,
    )

    assert result.final_delta_s > 0
    assert np.all(np.diff(result.delta_s) >= -1e-9)
    # 3% slower over a 34 s lap is about 1 s.
    assert result.final_delta_s == pytest.approx(
        synthetic_lap.lap_time_s * (1 / 0.97 - 1), rel=0.02
    )


# --------------------------------------------------------------------------- #
# Grid handling
# --------------------------------------------------------------------------- #

def test_the_grid_stops_at_the_shorter_lap():
    """Past that point one lap was never measured, and extrapolating would
    manufacture a difference out of nothing."""
    long_d, long_t = constant_speed_lap(50.0, length_m=1000.0)
    short_d, short_t = constant_speed_lap(50.0, length_m=600.0)

    result = delta.delta_time(long_d, long_t, short_d, short_t)

    assert result.grid_m[-1] == pytest.approx(600.0)


def test_elapsed_time_is_measured_from_the_lap_start():
    positions = np.array([0.0, 500.0, 1000.0])
    times = np.array([100.0, 110.0, 120.0])
    grid = np.array([0.0, 500.0, 1000.0])

    elapsed = delta.elapsed_time(positions, times, grid)

    assert elapsed.tolist() == pytest.approx([0.0, 10.0, 20.0])


def test_elapsed_time_of_an_empty_lap_is_nan():
    result = delta.elapsed_time(np.array([]), np.array([]), np.array([0.0, 1.0]))
    assert np.all(np.isnan(result))


# --------------------------------------------------------------------------- #
# Locating the loss
# --------------------------------------------------------------------------- #

def test_worst_loss_is_located_where_it_happens():
    """A lap identical to the reference apart from one slow section must show
    the loss at that section."""
    positions = np.linspace(0.0, 1000.0, 1001)
    reference_speed = np.full(1001, 50.0)
    lap_speed = reference_speed.copy()
    lap_speed[400:600] = 25.0  # slow through the middle

    reference_t = np.concatenate([[0.0], np.cumsum(np.diff(positions) / reference_speed[1:])])
    lap_t = np.concatenate([[0.0], np.cumsum(np.diff(positions) / lap_speed[1:])])

    result = delta.delta_time(positions, reference_t, positions, lap_t)

    # All the loss accrues inside the slow section and is carried afterwards.
    # The tolerance covers one grid step at the boundary: the interval ending at
    # 400 m is already driven at the slow speed, which is worth 0.02 s.
    assert result.worst_loss_distance_m >= 590.0
    assert delta.time_lost_between(result, 0.0, 400.0) == pytest.approx(0.0, abs=0.05)
    assert delta.time_lost_between(result, 400.0, 600.0) > 3.0
    assert delta.time_lost_between(result, 600.0, 1000.0) == pytest.approx(0.0, abs=0.05)


def test_time_lost_between_measures_change_not_level():
    """What matters for a corner is what happened inside it, not the deficit
    carried into it."""
    result = delta.DeltaResult(
        grid_m=np.array([0.0, 100.0, 200.0, 300.0]),
        delta_s=np.array([0.0, 2.0, 2.0, 3.0]),
        reference_time_s=np.zeros(4),
        lap_time_s=np.zeros(4),
    )

    assert delta.time_lost_between(result, 0.0, 100.0) == pytest.approx(2.0)
    # Already 2 s behind, but nothing further was lost here.
    assert delta.time_lost_between(result, 100.0, 200.0) == pytest.approx(0.0)
    assert delta.time_lost_between(result, 200.0, 300.0) == pytest.approx(1.0)


def test_time_lost_between_handles_an_empty_result():
    empty = delta.DeltaResult(
        grid_m=np.array([]), delta_s=np.array([]),
        reference_time_s=np.array([]), lap_time_s=np.array([]),
    )
    assert delta.time_lost_between(empty, 0.0, 100.0) == 0.0
    assert empty.final_delta_s == 0.0
    assert empty.worst_loss_s == 0.0


def test_delta_against_a_synthetic_reference_curve():
    """The ideal lap is stitched from segments, so it exists only as a curve and
    never as a lap that can be passed in as distance plus time."""
    grid = np.linspace(0.0, 1000.0, 1001)
    reference_elapsed = grid / 50.0

    lap_d, lap_t = constant_speed_lap(45.0)
    result = delta.delta_against_reference_curve(
        grid, reference_elapsed, lap_d, lap_t
    )

    expected = 1000.0 * (1.0 / 45.0 - 1.0 / 50.0)
    assert result.final_delta_s == pytest.approx(expected, rel=1e-6)


# --------------------------------------------------------------------------- #
# Where the time moved
# --------------------------------------------------------------------------- #

def test_gain_rate_survives_a_noisy_delta():
    """Two laps sampled a metre apart differ by microseconds; differentiating
    that raw makes the sign flip every few metres."""
    grid = np.arange(0.0, 1000.0)
    rng = np.random.default_rng(7)
    # A clean 1 s loss over the whole lap, plus sub-millisecond sampling noise.
    clean = grid * 0.001
    noisy = clean + rng.normal(0.0, 2e-4, grid.size)

    smoothed = delta.smoothed_gain_rate(noisy, grid, smoothing_window_m=25.0)
    raw = np.gradient(noisy, grid) * 1000.0

    # The true rate is 1 s/km everywhere.
    assert smoothed.mean() == pytest.approx(1.0, abs=0.05)
    assert np.abs(smoothed - 1.0).max() < np.abs(raw - 1.0).max() / 5.0
    assert np.all(smoothed > 0.0)  # never flips sign; the raw derivative does


def test_loss_classes_mark_the_corner_not_the_rest_of_the_lap():
    """Colouring by the delta's *value* paints the whole second half of the lap
    red because of one mistake at turn one. The slope marks the corner."""
    grid = np.arange(0.0, 3000.0)
    # Flat, then 0.5 s lost over a 150 m braking zone, then flat again.
    lost = np.clip((grid - 1000.0) / 150.0, 0.0, 1.0) * 0.5

    classes = delta.loss_classes(lost, grid, mild_threshold_s_per_km=0.5,
                                 strong_threshold_s_per_km=2.0)

    marked = np.flatnonzero(classes < 0)
    assert marked.size > 0
    assert 950 < marked[0] < 1050
    assert 1100 < marked[-1] < 1250
    # Everything after the mistake is carried, not lost, so it stays neutral.
    assert np.all(classes[1400:] == 0)


def test_loss_classes_are_signed_the_way_the_delta_is():
    grid = np.arange(0.0, 500.0)
    assert np.any(delta.loss_classes(grid * 0.01, grid) < 0)    # rising: losing
    assert np.any(delta.loss_classes(-grid * 0.01, grid) > 0)   # falling: gaining
    assert np.all(delta.loss_classes(np.zeros_like(grid), grid) == 0)


def test_gain_rate_of_a_degenerate_delta():
    grid = np.arange(0.0, 3.0)
    assert delta.smoothed_gain_rate(np.array([]), np.array([])).size == 0
    assert np.all(delta.smoothed_gain_rate(np.zeros(3), grid) == 0.0)
