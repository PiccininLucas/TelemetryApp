"""Unit conversion, driven by what the file declares.

The `channelsList` catalog carries a `unit` column per channel, so the
application never guesses a channel's unit from its name. Writing a hand-made
"Ground Speed is in km/h" table would be wrong the day the game changes it, and
would silently produce plausible-but-false numbers - the worst failure mode in
an analysis tool.

Canonical internal units, per the specification:

    speed         m/s      (displayed as km/h)
    distance      m
    time          s
    angle         deg
    pedal         fraction 0-1
    acceleration  g

Plus the ones the specification does not name but the data needs. Choices and
their reasons:

    temperature   degC     what every tyre/brake engineer reads
    pressure      kPa      the unit LMU itself uses for tyre pressures
    rot. speed    rpm      already how engine speed is reasoned about

An unrecognised unit is passed through **unchanged** with a warning. It is never
guessed at: a wrong factor is undetectable downstream, whereas an unconverted
value is at least off by an obvious factor when plotted.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from lmu_telemetry.logging_config import get_logger
from lmu_telemetry.ui import strings

logger = get_logger(__name__)

# Physical constants.
STANDARD_GRAVITY = 9.80665  # m/s^2, CGPM definition
KMH_TO_MS = 1.0 / 3.6
MPH_TO_MS = 0.44704


@dataclass(frozen=True, slots=True)
class UnitSpec:
    """An affine conversion to a canonical unit: `y = x * factor + offset`.

    Affine rather than a plain factor because temperature needs the offset
    (degF -> degC), and treating it as multiplicative only would be wrong by
    32 degrees at every reading.
    """

    canonical: str
    factor: float = 1.0
    offset: float = 0.0

    @property
    def is_identity(self) -> bool:
        return self.factor == 1.0 and self.offset == 0.0


#: Conversions keyed by the *normalised* unit token (see `normalise_unit_token`).
#:
#: Deliberately broad: the exact spelling the game uses is only known once
#: `scripts/inspect_schema.py` reports the distinct units found in a real file,
#: and different builds have been seen to differ in casing and symbols.
_CONVERSIONS: dict[str, UnitSpec] = {
    # --- dimensionless ------------------------------------------------------
    "": UnitSpec(""),
    "-": UnitSpec(""),
    "ratio": UnitSpec(""),
    "fraction": UnitSpec(""),
    "normalized": UnitSpec(""),
    "pct": UnitSpec("", factor=0.01),  # pedals arrive as 0-100 in some builds
    # --- speed --------------------------------------------------------------
    "m/s": UnitSpec("m/s"),
    "km/h": UnitSpec("m/s", factor=KMH_TO_MS),
    "mph": UnitSpec("m/s", factor=MPH_TO_MS),
    # --- distance -----------------------------------------------------------
    "m": UnitSpec("m"),
    "km": UnitSpec("m", factor=1000.0),
    "cm": UnitSpec("m", factor=0.01),
    "mm": UnitSpec("m", factor=0.001),
    "ft": UnitSpec("m", factor=0.3048),
    "in": UnitSpec("m", factor=0.0254),
    # --- time ---------------------------------------------------------------
    "s": UnitSpec("s"),
    "ms": UnitSpec("s", factor=0.001),
    "min": UnitSpec("s", factor=60.0),
    # --- angle --------------------------------------------------------------
    "deg": UnitSpec("deg"),
    "rad": UnitSpec("deg", factor=180.0 / np.pi),
    # --- acceleration -------------------------------------------------------
    "g": UnitSpec("g"),
    "m/s2": UnitSpec("g", factor=1.0 / STANDARD_GRAVITY),
    # --- temperature --------------------------------------------------------
    "degc": UnitSpec("degC"),
    "degf": UnitSpec("degC", factor=5.0 / 9.0, offset=-32.0 * 5.0 / 9.0),
    "k": UnitSpec("degC", offset=-273.15),
    # --- pressure -----------------------------------------------------------
    "kpa": UnitSpec("kPa"),
    "pa": UnitSpec("kPa", factor=0.001),
    "bar": UnitSpec("kPa", factor=100.0),
    "psi": UnitSpec("kPa", factor=6.894757293168361),
    # --- rotational speed ---------------------------------------------------
    "rpm": UnitSpec("rpm"),
    "rad/s": UnitSpec("rpm", factor=60.0 / (2.0 * np.pi)),
    # --- force, torque, mass, volume ---------------------------------------
    "n": UnitSpec("N"),
    "kn": UnitSpec("N", factor=1000.0),
    "n.m": UnitSpec("N.m"),
    "kg": UnitSpec("kg"),
    "l": UnitSpec("L"),
    "ml": UnitSpec("L", factor=0.001),
    # --- power --------------------------------------------------------------
    # Regen Rate is declared in kW. Kept in kW rather than W: a hybrid recovers
    # on the order of 100 kW, and W would put six digits on every axis label.
    "kw": UnitSpec("kW"),
    "w": UnitSpec("kW", factor=0.001),
    "hp": UnitSpec("kW", factor=0.7456998715822702),
    # --- boolean ------------------------------------------------------------
    # eventsList declares "On/Off" for Headlights State. Already 0/1 in the
    # data, so the conversion is identity - it is listed only so the unit is
    # recognised and does not trigger a spurious warning.
    "on/off": UnitSpec(""),
}

#: Spelling variants folded onto a canonical token before lookup.
_ALIASES: dict[str, str] = {
    "mps": "m/s",
    "kph": "km/h",
    "kmh": "km/h",
    "km/hr": "km/h",
    "meter": "m",
    "meters": "m",
    "metre": "m",
    "metres": "m",
    "sec": "s",
    "secs": "s",
    "second": "s",
    "seconds": "s",
    "millisecond": "ms",
    "milliseconds": "ms",
    "msec": "ms",
    "degree": "deg",
    "degrees": "deg",
    "degs": "deg",
    "°": "deg",
    "radian": "rad",
    "radians": "rad",
    "rads": "rad",
    "m/s^2": "m/s2",
    "m/s²": "m/s2",
    "mss": "m/s2",
    "gs": "g",
    "g's": "g",
    "°c": "degc",
    "c": "degc",
    "celsius": "degc",
    "degreec": "degc",
    "°f": "degf",
    "f": "degf",
    "fahrenheit": "degf",
    "kelvin": "k",
    "%": "pct",
    "percent": "pct",
    "percentage": "pct",
    "nm": "n.m",
    "n*m": "n.m",
    "newton": "n",
    "newtons": "n",
    "newton-meter": "n.m",
    "liter": "l",
    "liters": "l",
    "litre": "l",
    "litres": "l",
    "revs": "rpm",
    "rev/min": "rpm",
    "r/min": "rpm",
    "kilowatt": "kw",
    "kilowatts": "kw",
    "watt": "w",
    "watts": "w",
    "onoff": "on/off",
    "on-off": "on/off",
    "bool": "on/off",
    "boolean": "on/off",
    "none": "",
    "n/a": "",
    "unitless": "",
    "dimensionless": "",
}


def normalise_unit_token(unit: str | None) -> str:
    """Fold a raw unit string into a lookup token.

    Lowercases, trims, drops internal whitespace and resolves known spelling
    variants. Done as a separate step so that the conversion table stays a plain
    readable list of physics, and all the string messiness lives in one place.

    >>> normalise_unit_token(" KM/H ")
    'km/h'
    >>> normalise_unit_token("Degrees")
    'deg'
    """
    if unit is None:
        return ""
    token = "".join(str(unit).split()).lower()
    return _ALIASES.get(token, token)


def lookup(unit: str | None) -> UnitSpec | None:
    """Return the conversion for a raw unit string, or None if unrecognised."""
    return _CONVERSIONS.get(normalise_unit_token(unit))


def canonical_unit(unit: str | None) -> str:
    """Return the canonical unit a raw unit converts to.

    Falls back to the raw string when unrecognised, so a plot axis still shows
    something honest instead of a blank.
    """
    spec = lookup(unit)
    return spec.canonical if spec is not None else (unit or "")


def convert(
    values: np.ndarray,
    unit: str | None,
    *,
    channel: str = "?",
) -> tuple[np.ndarray, str]:
    """Convert an array to canonical units.

    Args:
        values: Raw samples as read from the file.
        unit: The channel's declared unit, verbatim from `channelsList`.
        channel: Channel name, used only to make the warning actionable.

    Returns:
        `(converted_values, canonical_unit)`. When the unit is unrecognised the
        array is returned untouched alongside the original unit string, and a
        warning is logged - never a guessed conversion.
    """
    spec = lookup(unit)
    if spec is None:
        logger.warning(
            strings.WARN_UNKNOWN_UNIT.format(unit=unit, channel=channel)
        )
        return values, (unit or "")

    if spec.is_identity:
        return values, spec.canonical

    # Out-of-place so the caller's raw array stays intact; ingestion keeps both
    # raw and converted versions available for diagnostics.
    return values * spec.factor + spec.offset, spec.canonical


def known_units() -> list[str]:
    """Every unit token the converter recognises. Used by the schema report."""
    return sorted(set(_CONVERSIONS) | set(_ALIASES))
