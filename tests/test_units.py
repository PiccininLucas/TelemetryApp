"""Tests for unit conversion.

The conversions matter more than they look. Every threshold in the analysis
layer is expressed in canonical units - a braking point is "Brake Pos > 0.03",
and the file stores brake position as a percentage from 0 to 100. Get the
factor wrong and the braking point is detected at 3% of the way through the
session's pedal range instead of 3% pedal travel, with no error anywhere.
"""

from __future__ import annotations

import numpy as np
import pytest

from lmu_telemetry.core import units


# --------------------------------------------------------------------------- #
# Token normalisation
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("km/h", "km/h"),
        (" KM/H ", "km/h"),
        ("kph", "km/h"),
        ("Degrees", "deg"),
        ("°", "deg"),
        ("C", "degc"),
        ("°C", "degc"),
        ("m/s^2", "m/s2"),
        ("%", "pct"),
        ("Nm", "n.m"),
        ("On/Off", "on/off"),
        ("", ""),
        (None, ""),
        ("N/A", ""),
    ],
)
def test_normalise_unit_token(raw, expected):
    assert units.normalise_unit_token(raw) == expected


# --------------------------------------------------------------------------- #
# Conversions
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    ("value", "unit", "expected", "canonical"),
    [
        # Speed. Ground Speed is declared in km/h in the real files, so this
        # factor is on the path of every distance and delta-t computation.
        (360.0, "km/h", 100.0, "m/s"),
        (100.0, "m/s", 100.0, "m/s"),
        (60.0, "mph", 26.8224, "m/s"),
        # Pedals arrive as 0-100 and every threshold assumes 0-1.
        (100.0, "%", 1.0, ""),
        (3.0, "%", 0.03, ""),
        # Angles.
        (np.pi, "rad", 180.0, "deg"),
        (45.0, "deg", 45.0, "deg"),
        # Acceleration.
        (9.80665, "m/s2", 1.0, "g"),
        (1.5, "G", 1.5, "g"),
        # Temperature needs the offset, not just a factor.
        (212.0, "degF", 100.0, "degC"),
        (32.0, "degF", 0.0, "degC"),
        (273.15, "K", 0.0, "degC"),
        (85.0, "C", 85.0, "degC"),
        # Pressure. Turbo Boost Pressure is declared in Pa.
        (101325.0, "Pa", 101.325, "kPa"),
        (1.0, "bar", 100.0, "kPa"),
        (170.0, "kPa", 170.0, "kPa"),
        # Distance and time.
        (1.5, "km", 1500.0, "m"),
        (250.0, "ms", 0.25, "s"),
    ],
)
def test_convert(value, unit, expected, canonical):
    converted, result_unit = units.convert(np.array([value]), unit, channel="test")
    assert converted[0] == pytest.approx(expected, rel=1e-6)
    assert result_unit == canonical


def test_unknown_unit_passes_through_unchanged(caplog):
    """An unrecognised unit is never guessed at.

    A wrong factor is undetectable downstream; an unconverted value is at least
    obviously off by a round factor when plotted.
    """
    original = np.array([1.0, 2.0, 3.0])
    converted, unit = units.convert(original, "furlongs/fortnight", channel="X")

    assert np.array_equal(converted, original)
    assert unit == "furlongs/fortnight"
    assert any("furlongs" in record.message for record in caplog.records)


def test_convert_does_not_mutate_input():
    """Ingestion keeps the raw array for diagnostics, so conversion is
    out-of-place."""
    original = np.array([360.0, 720.0])
    copy = original.copy()
    units.convert(original, "km/h")
    assert np.array_equal(original, copy)


def test_canonical_unit_falls_back_to_the_raw_string():
    assert units.canonical_unit("km/h") == "m/s"
    assert units.canonical_unit("bananas") == "bananas"


def test_temperature_conversion_is_affine_not_multiplicative():
    """Treating degF as a pure factor is wrong by 32 degrees at every reading."""
    converted, _ = units.convert(np.array([32.0, 212.0]), "degF")
    assert converted.tolist() == pytest.approx([0.0, 100.0])


# --------------------------------------------------------------------------- #
# Every unit the real files declare must be recognised
# --------------------------------------------------------------------------- #

#: The complete set of unit strings found by inspecting real session files
#: across Practice, Qualifying and Race, for a GT3 and an LMP3 car.
UNITS_FOUND_IN_REAL_FILES = [
    "", "%", "C", "G", "L", "Nm", "On/Off", "Pa",
    "RPM", "deg", "kPa", "kW", "km/h", "m", "m/s", "s",
]


@pytest.mark.parametrize("unit", UNITS_FOUND_IN_REAL_FILES)
def test_every_real_unit_is_recognised(unit):
    """Regression guard: a future game version adding a unit should fail here,
    not silently ship unconverted values into an analysis."""
    assert units.lookup(unit) is not None, f"unit {unit!r} would pass unconverted"
