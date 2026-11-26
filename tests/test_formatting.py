"""The number formats every panel shares.

One table per helper, each with the cases that break formatting code: nothing,
NaN, both infinities, zero, negatives, and a value that rounds to zero.
"""

from __future__ import annotations

import math

import pytest

from lmu_telemetry.shared.formatting import (
    MISSING, format_distance, format_gap, format_lap_time, format_sector_time,
    format_seconds, format_speed, format_value,
)

NAN = float("nan")
INF = float("inf")

#: What no helper may ever show: Python's own spelling of a missing number.
NOT_A_FIGURE = ("nan", "inf", "None")

UNSHOWABLE = [None, NAN, INF, -INF]


@pytest.mark.parametrize(("seconds", "expected"), [
    (103.564, "1:43.564"),
    (59.9994, "0:59.999"),
    (245.0, "4:05.000"),
    (0.0, MISSING),          # not a lap
    (-3.0, MISSING),
    *[(value, MISSING) for value in UNSHOWABLE],
])
def test_format_lap_time(seconds, expected):
    assert format_lap_time(seconds) == expected


@pytest.mark.parametrize(("seconds", "expected"), [
    (28.111, "28.111"),
    (75.203, "1:15.203"),
    (0.0, MISSING),
    (-1.0, MISSING),
    *[(value, MISSING) for value in UNSHOWABLE],
])
def test_format_sector_time(seconds, expected):
    assert format_sector_time(seconds) == expected


@pytest.mark.parametrize(("seconds", "decimals", "expected"), [
    (0.31, 3, "0.310"),
    (0.25, 2, "0.25"),
    (1.537, 2, "1.54"),
    (0.0, 3, "0.000"),
    (-0.2, 3, "-0.200"),     # unsigned, but a negative is still shown as one
    *[(value, 3, MISSING) for value in UNSHOWABLE],
])
def test_format_seconds(seconds, decimals, expected):
    assert format_seconds(seconds, decimals) == expected


@pytest.mark.parametrize(("seconds", "expected"), [
    (1.1610001, "+1.161"),
    (-0.2836, "-0.284"),
    (0.0, "+0.000"),
    (-0.0, "+0.000"),
    (-0.0004, "+0.000"),     # rounds to nothing: no minus sign on a zero
    (0.0004, "+0.000"),
    (-0.0005001, "-0.001"),
    *[(value, MISSING) for value in UNSHOWABLE],
])
def test_format_gap(seconds, expected):
    """Always signed: an unsigned "0.284" next to a lap time is ambiguous in
    exactly the case that matters most."""
    assert format_gap(seconds) == expected


def test_format_gap_takes_its_precision():
    assert format_gap(-0.04, 1) == "+0.0"
    assert format_gap(2.25, 2) == "+2.25"


@pytest.mark.parametrize(("speed_ms", "signed", "expected"), [
    (20.0, False, "72.0"),
    (17.3889, False, "62.6"),
    (0.0, False, "0.0"),
    (-1.0, False, "-3.6"),
    (0.5, True, "+1.8"),
    (-0.5, True, "-1.8"),
    (0.0, True, "+0.0"),
    (-0.01, True, "+0.0"),   # -0.036 km/h shows as a level, not a loss
    *[(value, signed, MISSING) for value in UNSHOWABLE for signed in (False, True)],
])
def test_format_speed_converts_to_kmh(speed_ms, signed, expected):
    assert format_speed(speed_ms, signed=signed) == expected


@pytest.mark.parametrize(("metres", "decimals", "expected"), [
    (762.4, 0, "762"),
    (762.5, 0, "762"),       # banker's rounding, as f-strings do
    (77.06, 1, "77.1"),
    (0.0, 0, "0"),
    (-3.6, 0, "-4"),
    *[(value, 0, MISSING) for value in UNSHOWABLE],
])
def test_format_distance(metres, decimals, expected):
    assert format_distance(metres, decimals) == expected


@pytest.mark.parametrize(("value", "decimals", "expected"), [
    (218.44, 1, "218.4"),
    (0.0, 0, "0"),
    (-12.25, 2, "-12.25"),
    *[(value, 1, MISSING) for value in UNSHOWABLE],
])
def test_format_value(value, decimals, expected):
    assert format_value(value, decimals) == expected


@pytest.mark.parametrize("helper", [
    format_lap_time, format_sector_time, format_seconds, format_gap,
    format_speed, format_distance, lambda v: format_value(v, 1),
])
@pytest.mark.parametrize("value", [None, NAN, INF, -INF, 0.0, -0.0, -7.5, 1e9])
def test_no_helper_ever_spells_a_number_the_python_way(helper, value):
    text = helper(value)
    assert text and not any(word in text for word in NOT_A_FIGURE)


def test_missing_is_the_same_everywhere():
    assert {format_seconds(None), format_gap(math.nan), format_speed(None),
            format_distance(math.inf), format_lap_time(None)} == {MISSING}
