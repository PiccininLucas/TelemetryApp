"""Tests for the g-g diagram and the grip envelope."""

from __future__ import annotations

import numpy as np
import pytest

from lmu_telemetry.analysis import friction


def circle(radius: float, n: int = 200) -> tuple[np.ndarray, np.ndarray]:
    """Points on a circle: a car using its grip equally in every direction."""
    angle = np.linspace(0.0, 2 * np.pi, n, endpoint=False)
    return radius * np.cos(angle), radius * np.sin(angle)


# --------------------------------------------------------------------------- #
# Envelope geometry
# --------------------------------------------------------------------------- #

def test_hull_area_of_a_circle_matches_pi_r_squared():
    """The convex hull of a sampled circle approaches its area from below,
    since the hull is the inscribed polygon."""
    lateral, longitudinal = circle(1.5, n=360)
    envelope = friction.compute_envelope(lateral, longitudinal)

    assert envelope.hull_area_g2 == pytest.approx(np.pi * 1.5**2, rel=1e-3)
    assert envelope.is_valid


def test_a_circle_fills_its_reference_ellipse():
    """A driver using all the grip in every direction fills the envelope."""
    lateral, longitudinal = circle(1.5, n=360)
    envelope = friction.compute_envelope(lateral, longitudinal)

    assert envelope.fill_fraction == pytest.approx(1.0, rel=1e-3)


def test_a_cross_shape_leaves_the_envelope_hollow():
    """The signature of braking and turning as separate actions.

    Pure braking and pure cornering only, with nothing in the diagonals: the
    hull is a diamond, whose area is 2*r^2 against the ellipse's pi*r^2, so
    about 64%.
    """
    pure_braking = np.zeros(50), np.linspace(-1.5, 0.0, 50)
    pure_cornering = np.linspace(-1.5, 1.5, 50), np.zeros(50)
    pure_acceleration = np.zeros(50), np.linspace(0.0, 1.5, 50)

    lateral = np.concatenate([pure_braking[0], pure_cornering[0], pure_acceleration[0]])
    longitudinal = np.concatenate(
        [pure_braking[1], pure_cornering[1], pure_acceleration[1]]
    )

    envelope = friction.compute_envelope(lateral, longitudinal)

    assert envelope.fill_fraction < 0.7
    assert envelope.fill_fraction == pytest.approx(2.0 / np.pi, rel=0.02)


def test_extremes_are_reported_separately():
    lateral = np.array([-1.8, 1.6, 0.0, 0.0])
    longitudinal = np.array([0.0, 0.0, -2.2, 0.9])

    envelope = friction.compute_envelope(lateral, longitudinal)

    assert envelope.max_lateral_g == pytest.approx(1.8)
    assert envelope.max_braking_g == pytest.approx(2.2)
    assert envelope.max_acceleration_g == pytest.approx(0.9)


def test_hull_is_returned_closed_for_drawing():
    lateral, longitudinal = circle(1.0, n=50)
    envelope = friction.compute_envelope(lateral, longitudinal)

    assert envelope.hull_lateral_g[0] == pytest.approx(envelope.hull_lateral_g[-1])
    assert envelope.hull_longitudinal_g[0] == pytest.approx(
        envelope.hull_longitudinal_g[-1]
    )


# --------------------------------------------------------------------------- #
# Degenerate input
# --------------------------------------------------------------------------- #

def test_empty_input_yields_an_invalid_envelope_not_an_exception():
    """A lap spent entirely in the pit lane is a reasonable thing to ask about
    and an unreasonable thing to crash on."""
    envelope = friction.compute_envelope(np.array([]), np.array([]))

    assert not envelope.is_valid
    assert envelope.n_points == 0
    assert envelope.fill_fraction == 0.0


def test_collinear_points_have_no_hull():
    """Qhull raises for a degenerate cloud; the caller gets zero area."""
    lateral = np.linspace(-1.0, 1.0, 50)
    envelope = friction.compute_envelope(lateral, np.zeros_like(lateral))

    assert envelope.hull_area_g2 == 0.0
    assert not envelope.is_valid


def test_two_points_have_no_hull():
    envelope = friction.compute_envelope(np.array([0.0, 1.0]), np.array([0.0, 1.0]))
    assert envelope.hull_area_g2 == 0.0


def test_non_finite_samples_are_dropped():
    lateral = np.array([1.0, np.nan, -1.0, 0.0, np.inf])
    longitudinal = np.array([0.0, 0.5, 0.0, -1.0, 0.2])

    envelope = friction.compute_envelope(lateral, longitudinal)

    assert envelope.n_points == 3
    assert np.all(np.isfinite(envelope.lateral_g))


def test_low_speed_samples_are_excluded():
    """A stationary car registers accelerometer noise that would appear as grip
    it never generated."""
    lateral = np.array([0.5, 0.5, 2.0, 2.0])
    longitudinal = np.array([0.5, 0.5, 2.0, 2.0])
    speed = np.array([50.0, 40.0, 0.5, 1.0])

    envelope = friction.compute_envelope(
        lateral, longitudinal, speed_ms=speed, min_speed_ms=10.0
    )

    assert envelope.n_points == 2
    assert envelope.max_lateral_g == pytest.approx(0.5)


# --------------------------------------------------------------------------- #
# Real-lap behaviour, on the synthetic circuit
# --------------------------------------------------------------------------- #

def test_synthetic_lap_envelope_is_coherent(synthetic_lap):
    """The circuit is built to a 1.4 g cornering limit, 1.3 g braking and
    0.5 g traction, so the envelope must reproduce exactly those."""
    envelope = friction.compute_envelope(
        synthetic_lap.lateral_g,
        synthetic_lap.longitudinal_g,
        synthetic_lap.speed_ms,
    )

    assert envelope.is_valid
    assert envelope.max_lateral_g == pytest.approx(1.4, rel=0.01)
    assert envelope.max_braking_g == pytest.approx(1.3, rel=0.01)
    assert envelope.max_acceleration_g == pytest.approx(0.5, rel=0.01)


def test_synthetic_lap_never_blends_the_two_axes(synthetic_lap):
    """The synthetic driver brakes in a straight line and turns at constant
    speed, never both at once - the pattern the g-g diagram exists to expose.
    Its envelope must therefore be far from filled."""
    envelope = friction.compute_envelope(
        synthetic_lap.lateral_g,
        synthetic_lap.longitudinal_g,
        synthetic_lap.speed_ms,
    )

    assert envelope.fill_fraction < 0.6
    assert friction.transition_quality(
        synthetic_lap.lateral_g, synthetic_lap.longitudinal_g
    ) < 0.1


def test_transition_quality_rewards_blending():
    """A driver trailing the brake into the corner loads both axes at once."""
    angle = np.linspace(0.0, 2 * np.pi, 400)
    blended_lateral = 1.5 * np.cos(angle)
    blended_longitudinal = 1.5 * np.sin(angle)

    separate_lateral = np.concatenate([np.zeros(200), np.linspace(-1.5, 1.5, 200)])
    separate_longitudinal = np.concatenate([np.linspace(-1.5, 1.5, 200), np.zeros(200)])

    blended = friction.transition_quality(blended_lateral, blended_longitudinal)
    separate = friction.transition_quality(separate_lateral, separate_longitudinal)

    assert blended > separate
    assert blended > 0.5
    assert separate < 0.1


def test_transition_quality_of_a_stationary_car_is_zero():
    assert friction.transition_quality(np.zeros(100), np.zeros(100)) == 0.0


# --------------------------------------------------------------------------- #
# Windowing
# --------------------------------------------------------------------------- #

def test_envelope_can_be_restricted_to_one_corner(synthetic_lap):
    """The whole-lap envelope is dominated by the best corner; a single
    corner's envelope shows whether the limit was approached there."""
    corner_start = synthetic_lap.corner_apex_distances_m[0] - 40.0
    corner_end = synthetic_lap.corner_apex_distances_m[0] + 40.0

    envelope = friction.envelope_for_window(
        synthetic_lap.lateral_g,
        synthetic_lap.longitudinal_g,
        synthetic_lap.distance_m,
        corner_start,
        corner_end,
        synthetic_lap.speed_ms,
    )

    assert envelope.n_points > 0
    assert envelope.n_points < len(synthetic_lap.lateral_g)
    assert envelope.max_lateral_g == pytest.approx(1.4, rel=0.02)


def test_combined_magnitude_is_the_vector_sum():
    lateral = np.array([3.0, 0.0, 1.0])
    longitudinal = np.array([4.0, 2.0, 0.0])

    assert friction.combined_magnitude(lateral, longitudinal).tolist() == \
        pytest.approx([5.0, 2.0, 1.0])
