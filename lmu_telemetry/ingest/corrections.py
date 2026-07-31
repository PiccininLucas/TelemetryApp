"""Known defects in the recorded data, and the corrections for them.

File-format defects belong in `ingest` and nowhere else. Everything above this
layer receives correctly labelled physical quantities, so no formula in
`analysis` ever has to know that the game writes a channel wrong.

Raw channels stay reachable under their file names through `Session.channel`.
This module only adds the corrected, semantically named accessors.

--------------------------------------------------------------------------
DEFECT 1: `G Force Lat` and `G Force Long` are swapped, and both are negated
--------------------------------------------------------------------------

The two accelerations can be derived from other channels without using the G
channels at all:

    longitudinal   a_x = dV/dt                     from Ground Speed
    lateral        a_y = V * omega,  omega = (v_left - v_right) / track_width
                                                   from Wheel Speed

Correlating each G channel against both references over full race sessions at
two tracks with two different cars gives:

    channel         vs a_x      vs a_y
    G Force Lat     -0.997      -0.075      -> is longitudinal, negated
    G Force Long    -0.074      -0.987      -> is lateral, negated
    G Force Vert    +0.058      +0.164      -> neither; genuinely vertical

A 0.5 s moving average changes the correlations by less than 0.01, so this is
not a noise artefact. Two independent sanity checks agree: through a sustained
70 km/h corner at constant speed, `G Force Lat` stays near zero (correct for a
longitudinal channel) while `G Force Long` holds -1.5 g (correct for a lateral
one); and under heavy straight-line braking `G Force Long` averages -0.02 g,
which only makes sense for a lateral channel.

This matters beyond tidiness. The g-g diagram would plot longitudinal
acceleration on its lateral axis, and the track-map reconstruction from
`omega = a_y / V` would integrate the wrong channel and produce a trajectory
with no relation to the circuit.

Sign convention adopted here (SAE, y positive to the right):

    longitudinal_g   positive accelerating, negative braking
    lateral_g        positive in a right-hand corner
"""

from __future__ import annotations

from typing import Final

import numpy as np

from lmu_telemetry.logging_config import get_logger

logger = get_logger(__name__)

# --- raw channel names, as the file spells them ------------------------------
RAW_LATERAL_CHANNEL: Final = "G Force Lat"
RAW_LONGITUDINAL_CHANNEL: Final = "G Force Long"
RAW_VERTICAL_CHANNEL: Final = "G Force Vert"

#: Which raw channel actually holds each physical quantity, and the sign to
#: apply. Written as data rather than as branches so the correction is auditable
#: at a glance and directly testable.
ACCELERATION_SOURCES: Final[dict[str, tuple[str, float]]] = {
    # physical quantity  : (raw channel, sign)
    "longitudinal": (RAW_LATERAL_CHANNEL, -1.0),
    "lateral": (RAW_LONGITUDINAL_CHANNEL, -1.0),
    "vertical": (RAW_VERTICAL_CHANNEL, +1.0),
}


def corrected_acceleration(raw_values: np.ndarray, quantity: str) -> np.ndarray:
    """Apply the sign correction for one acceleration component.

    Args:
        raw_values: The raw channel named by `ACCELERATION_SOURCES[quantity]`.
        quantity: "longitudinal", "lateral" or "vertical".

    Returns:
        Acceleration in g, in the sign convention documented above.
    """
    if quantity not in ACCELERATION_SOURCES:
        raise KeyError(f"Unknown acceleration component: {quantity!r}")
    _channel, sign = ACCELERATION_SOURCES[quantity]
    return raw_values * sign


def source_channel(quantity: str) -> str:
    """Name of the raw channel that actually carries `quantity`."""
    return ACCELERATION_SOURCES[quantity][0]


def reference_longitudinal_g(
    speed_ms: np.ndarray,
    times_s: np.ndarray,
) -> np.ndarray:
    """Longitudinal acceleration derived from speed, in g.

    `a_x = dV/dt`. Independent of the G channels, which is what makes it usable
    as the reference that identified the swap - and as the check that keeps it
    identified if a game update ever fixes the labelling.
    """
    from lmu_telemetry.core.units import STANDARD_GRAVITY

    return np.gradient(speed_ms, times_s) / STANDARD_GRAVITY


def reference_lateral_g(
    speed_ms: np.ndarray,
    wheel_speeds_ms: np.ndarray,
    track_width_m: float = 1.6,
) -> np.ndarray:
    """Lateral acceleration derived from the wheel-speed asymmetry, in g.

    In a corner the outside wheels run a larger radius and turn faster. The
    difference gives the yaw rate, and multiplying by forward speed gives the
    centripetal acceleration:

        omega = (v_left - v_right) / track_width
        a_y   = V * omega

    Assumes small slip angles and no wheelspin, so it is a cross-check rather
    than a replacement for the recorded channel. `track_width_m` scales the
    magnitude but not the sign, and the sign is what this is used for.

    Args:
        speed_ms: Forward speed, aligned with `wheel_speeds_ms`.
        wheel_speeds_ms: Shape `(n, 4)`, in FL, FR, RL, RR order.
        track_width_m: Track width. The default is representative of a GT3.

    Returns:
        Lateral acceleration in g, positive in a right-hand corner.
    """
    from lmu_telemetry.core.units import STANDARD_GRAVITY

    left = wheel_speeds_ms[:, [0, 2]].mean(axis=1)
    right = wheel_speeds_ms[:, [1, 3]].mean(axis=1)
    omega = (left - right) / track_width_m
    return speed_ms * omega / STANDARD_GRAVITY
