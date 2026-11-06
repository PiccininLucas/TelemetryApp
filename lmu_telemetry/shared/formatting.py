"""Number formatting for the interface.

Kept apart from the widgets because the same formats are read in three places -
the session tree, the chart legend and the status bar - and a lap time that
reads differently in two of them looks like two different laps.
"""

from __future__ import annotations

import math


def format_lap_time(seconds: float | None) -> str:
    """m:ss.mmm, the way a timing screen shows it."""
    if seconds is None or not math.isfinite(seconds) or seconds <= 0:
        return "--"
    minutes, remainder = divmod(seconds, 60.0)
    return f"{int(minutes)}:{remainder:06.3f}"


def format_gap(seconds: float | None) -> str:
    """A signed time difference, in seconds: +1.161, -0.284.

    Always signed, including when it is a gain. An unsigned "0.284" next to a
    lap time is ambiguous in exactly the case that matters most.
    """
    if seconds is None or not math.isfinite(seconds):
        return "--"
    return f"{seconds:+.3f}"


def format_value(value: float | None, decimals: int) -> str:
    """One channel reading for the cursor readout."""
    if value is None or not math.isfinite(value):
        return "--"
    return f"{value:.{decimals}f}"
