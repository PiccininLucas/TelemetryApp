"""Empirical checks of two assumptions the file does not document.

Both run against a real session and skip when none is available. They are the
kind of test that earns its keep: each one caught, or confirmed, something that
no amount of reading the schema could have settled.

1. **Wheel index order** (specification section 4.8). Nothing in the file says
   which of `value1`..`value4` is which wheel.

2. **What the G Force channels contain.** They are mislabelled, and the
   correction has to keep being verified in case a game update fixes them.
"""

from __future__ import annotations

import numpy as np
import pytest

from lmu_telemetry.ingest import channel_registry, corrections
from lmu_telemetry.ingest.session_loader import load_session

# Minimum correlation for a claim about a channel's identity to stand. The
# measured values are above 0.97; 0.8 leaves room for a different car or track
# without letting a genuinely wrong channel through.
MIN_IDENTIFICATION_CORRELATION = 0.8


@pytest.fixture(scope="module")
def session(real_session_path):
    with load_session(real_session_path, with_hash=False) as loaded:
        yield loaded


def _require(session, *channels):
    missing = session.missing(*channels)
    if missing:
        pytest.skip(f"Session lacks {missing}")


# --------------------------------------------------------------------------- #
# 1. Wheel order: FL, FR, RL, RR
# --------------------------------------------------------------------------- #

def test_wheels_1_and_2_are_the_front_axle(session):
    """Brake temperature separates the axles beyond argument.

    The front brakes do most of the work on every GT and prototype car, so they
    run far hotter. Measured: 283 C front against 223 C rear at Le Mans, 387
    against 330 at Monza - a 60 C gap, not a marginal call.
    """
    _require(session, "Brakes Temp")
    brakes = session.channel("Brakes Temp")

    front = np.nanmean(brakes[:, [0, 1]])
    rear = np.nanmean(brakes[:, [2, 3]])

    assert front > rear + 20.0, (
        f"Wheels 1,2 average {front:.1f} C and wheels 3,4 {rear:.1f} C. "
        f"The front axle must run hotter; the assumed index order is wrong."
    )


def test_wheels_1_and_3_are_the_left_side(session):
    """Cornering kinematics settle left from right.

    The outside wheels run a larger radius and therefore turn faster. Grouping
    by the sign of the steering input, the wheel-speed asymmetry has to flip
    with it - and it does, by about 0.7 m/s in both directions across every
    session tested.

    Steering is the reference here rather than `G Force Lat`, which does not
    contain lateral acceleration at all - see the tests below.
    """
    _require(session, "Wheel Speed", "Steering Pos", "Ground Speed")

    wheel_speed = session.channel("Wheel Speed")
    times = session.channel_times("Wheel Speed")
    steering = _on_grid(session, "Steering Pos", times)
    speed = _on_grid(session, "Ground Speed", times)

    left = wheel_speed[:, [0, 2]].mean(axis=1)
    right = wheel_speed[:, [1, 3]].mean(axis=1)
    asymmetry = left - right

    # Above pit speed and past a clear steering threshold, to exclude
    # straight-line noise and transients.
    fast = speed > 100.0 / 3.6
    turning_left = (steering < -0.2) & fast
    turning_right = (steering > 0.2) & fast

    if turning_left.sum() < 100 or turning_right.sum() < 100:
        pytest.skip("Not enough sustained cornering in this session")

    in_left_corners = asymmetry[turning_left].mean()
    in_right_corners = asymmetry[turning_right].mean()

    assert in_left_corners < 0, (
        "In a left-hand corner the right wheels are outside and must run "
        f"faster, so (1,3)-(2,4) should be negative; got {in_left_corners:+.4f}"
    )
    assert in_right_corners > 0, (
        "In a right-hand corner the left wheels are outside and must run "
        f"faster; got {in_right_corners:+.4f}"
    )


def test_declared_wheel_order_matches_what_was_verified():
    """Guards the constant itself against being edited without re-checking."""
    assert channel_registry.WHEEL_ORDER == ("FL", "FR", "RL", "RR")


# --------------------------------------------------------------------------- #
# 2. The G Force channels are swapped and negated
# --------------------------------------------------------------------------- #

def _on_grid(session, channel: str, target_times: np.ndarray) -> np.ndarray:
    """Interpolate a channel onto another channel's sample times."""
    return np.interp(
        target_times, session.channel_times(channel), session.channel(channel)
    )


@pytest.fixture(scope="module")
def acceleration_references(session):
    """Both accelerations derived without touching the G channels."""
    _require(session, "Ground Speed", "Wheel Speed", "G Force Lat", "G Force Long")

    times = session.channel_times("Ground Speed")
    speed = session.channel("Ground Speed")  # already converted to m/s
    wheel_speed = _wheels_on_grid(session, times)

    return {
        "times": times,
        "speed": speed,
        "longitudinal": corrections.reference_longitudinal_g(speed, times),
        "lateral": corrections.reference_lateral_g(speed, wheel_speed),
        "moving": speed > 20.0,
    }


def _wheels_on_grid(session, target_times: np.ndarray) -> np.ndarray:
    source_times = session.channel_times("Wheel Speed")
    wheel_speed = session.channel("Wheel Speed")
    return np.column_stack([
        np.interp(target_times, source_times, wheel_speed[:, i]) for i in range(4)
    ])


def _correlate(session, channel: str, reference: np.ndarray,
               references: dict) -> float:
    values = np.interp(
        references["times"], session.channel_times(channel),
        session.channel(channel),
    )
    moving = references["moving"]
    return float(np.corrcoef(values[moving], reference[moving])[0, 1])


def test_g_force_lat_actually_holds_longitudinal_acceleration(
    session, acceleration_references
):
    """`G Force Lat` correlates -0.99 with dV/dt and -0.08 with lateral g."""
    against_longitudinal = _correlate(
        session, "G Force Lat",
        acceleration_references["longitudinal"], acceleration_references,
    )
    against_lateral = _correlate(
        session, "G Force Lat",
        acceleration_references["lateral"], acceleration_references,
    )

    assert abs(against_longitudinal) > MIN_IDENTIFICATION_CORRELATION, (
        f"'G Force Lat' vs dV/dt correlation is {against_longitudinal:+.3f}. "
        f"It was measured at -0.99; the game may have fixed the labelling, in "
        f"which case ingest/corrections.py must be revisited."
    )
    assert abs(against_longitudinal) > abs(against_lateral)
    assert against_longitudinal < 0, "the channel is negated as well as swapped"


def test_g_force_long_actually_holds_lateral_acceleration(
    session, acceleration_references
):
    """`G Force Long` correlates -0.99 with V*omega and -0.07 with dV/dt."""
    against_lateral = _correlate(
        session, "G Force Long",
        acceleration_references["lateral"], acceleration_references,
    )
    against_longitudinal = _correlate(
        session, "G Force Long",
        acceleration_references["longitudinal"], acceleration_references,
    )

    assert abs(against_lateral) > MIN_IDENTIFICATION_CORRELATION, (
        f"'G Force Long' vs V*omega correlation is {against_lateral:+.3f}; "
        f"it was measured at -0.99."
    )
    assert abs(against_lateral) > abs(against_longitudinal)
    assert against_lateral < 0


def test_corrected_accessor_returns_physically_correct_longitudinal_g(session):
    """Braking must show negative longitudinal acceleration.

    The whole point of the correction: with the raw channel this assertion
    fails, because the raw channel is neither longitudinal nor correctly signed.
    """
    _require(session, "Brake Pos", "Ground Speed", "G Force Lat")

    times = session.acceleration_times("longitudinal")
    longitudinal = session.acceleration("longitudinal")
    brake = _on_grid(session, "Brake Pos", times)
    speed = _on_grid(session, "Ground Speed", times)

    heavy_braking = (brake > 0.6) & (speed > 30.0)
    if heavy_braking.sum() < 50:
        pytest.skip("Not enough heavy braking in this session")

    assert longitudinal[heavy_braking].mean() < -0.3, (
        "Under heavy braking the corrected longitudinal acceleration must be "
        "clearly negative."
    )


def test_corrected_accessor_returns_physically_correct_lateral_g(session):
    """Positive lateral g must mean a right-hand corner."""
    _require(session, "Steering Pos", "Ground Speed", "G Force Long")

    times = session.acceleration_times("lateral")
    lateral = session.acceleration("lateral")
    steering = _on_grid(session, "Steering Pos", times)
    speed = _on_grid(session, "Ground Speed", times)

    fast = speed > 100.0 / 3.6
    left = (steering < -0.2) & fast
    right = (steering > 0.2) & fast

    if left.sum() < 50 or right.sum() < 50:
        pytest.skip("Not enough sustained cornering in this session")

    assert lateral[right].mean() > 0, "right-hand corners must give positive g"
    assert lateral[left].mean() < 0, "left-hand corners must give negative g"


def test_vertical_acceleration_is_left_alone(session, acceleration_references):
    """`G Force Vert` correlates with neither reference, so it is what it says."""
    _require(session, "G Force Vert")

    against_longitudinal = _correlate(
        session, "G Force Vert",
        acceleration_references["longitudinal"], acceleration_references,
    )
    against_lateral = _correlate(
        session, "G Force Vert",
        acceleration_references["lateral"], acceleration_references,
    )

    assert abs(against_longitudinal) < 0.5
    assert abs(against_lateral) < 0.5
    assert corrections.ACCELERATION_SOURCES["vertical"] == ("G Force Vert", +1.0)
