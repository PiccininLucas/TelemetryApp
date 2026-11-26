"""Number formatting for the interface.

Kept apart from the widgets because the same formats are read in many places -
the session list, the lap list, the header, the chart readout, the corner table,
the corner card and the consistency panel - and a figure that reads differently
in two of them looks like two different figures.

Every helper returns the number alone, without its unit: a table puts the unit
in the column header, a card in a template from `strings`. A value that is
missing, NaN or infinite is `MISSING` ("--") everywhere, never "nan" or "0".

Signed forms never show "-0.000": a difference that rounds to nothing is
"+0.000", because a minus sign on a zero reads as a loss that is not there.
"""

from __future__ import annotations

import math

#: What every helper shows for a value it cannot show.
MISSING = "--"

#: Metres per second to kilometres per hour. Duplicated from `domain.units`
#: because `shared` imports nothing from the layers above it.
_KMH_PER_MS = 3.6


def _finite(value: float | None) -> bool:
    return value is not None and math.isfinite(value)


def _number(value: float | None, decimals: int, *, signed: bool = False) -> str:
    if not _finite(value):
        return MISSING
    if signed:
        # Round first, so a value that shows as zero carries the zero's sign.
        rounded = round(value, decimals)
        return f"{(rounded if rounded != 0.0 else 0.0):+.{decimals}f}"
    return f"{value:.{decimals}f}"


def format_lap_time(seconds: float | None) -> str:
    """m:ss.mmm, the way a timing screen shows it."""
    if not _finite(seconds) or seconds <= 0:
        return MISSING
    minutes, remainder = divmod(seconds, 60.0)
    return f"{int(minutes)}:{remainder:06.3f}"


def format_sector_time(seconds: float | None) -> str:
    """A sector time: plain seconds (28.111), or m:ss.mmm past a minute.

    Le Mans sectors run well over a minute, and "75.203" there would make the
    reader do the arithmetic the lap-time form already does.
    """
    if not _finite(seconds) or seconds <= 0:
        return MISSING
    if seconds >= 60.0:
        return format_lap_time(seconds)
    return f"{seconds:.3f}"


def format_seconds(seconds: float | None, decimals: int = 3) -> str:
    """A duration or an amount of time, unsigned: 0.310, 0.25.

    For what is a time in itself - time to gain, time lost per lap, time on
    neither pedal - rather than a difference between two laps.
    """
    return _number(seconds, decimals)


def format_gap(seconds: float | None, decimals: int = 3) -> str:
    """A signed time difference, in seconds: +1.161, -0.284.

    Always signed, including when it is a gain. An unsigned "0.284" next to a
    lap time is ambiguous in exactly the case that matters most.
    """
    return _number(seconds, decimals, signed=True)


def format_speed(speed_ms: float | None, *, signed: bool = False) -> str:
    """A speed given in m/s, shown in km/h to a tenth: 62.6, or +1.8 signed.

    The data is in m/s everywhere; km/h is how a driver reads it, so the
    conversion happens here, at the last moment, and nowhere else.
    """
    kmh = speed_ms * _KMH_PER_MS if _finite(speed_ms) else None
    return _number(kmh, 1, signed=signed)


def format_distance(metres: float | None, decimals: int = 0) -> str:
    """A distance in metres: whole metres for a position on the lap, a tenth
    for a spread between laps."""
    return _number(metres, decimals)


def format_value(value: float | None, decimals: int) -> str:
    """One channel reading for the cursor readout, already in display units."""
    return _number(value, decimals)
