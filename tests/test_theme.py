"""The visual identity's guarantees.

These do not judge taste. They hold the properties the identity was chosen for:
text that can be read, an accent that cannot be mistaken for a lap, and a
stylesheet Qt can actually parse.
"""

from __future__ import annotations

import colorsys
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

from lmu_telemetry.presentation import theme  # noqa: E402

#: WCAG 2.2 AA for normal text.
AA = 4.5

#: Colours that carry meaning on the traces, the map and the delta fill.
DATA_COLOURS = {
    "reference lap": theme.TRACE_REFERENCE,
    "comparison lap": theme.TRACE_COMPARISON,
    "ideal lap": theme.TRACE_IDEAL,
    "brake": theme.COLOUR_BRAKE,
    "throttle": theme.COLOUR_THROTTLE,
}


def _luminance(hex_colour: str) -> float:
    colour = QtGui.QColor(hex_colour)

    def channel(value: float) -> float:
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    return (0.2126 * channel(colour.redF())
            + 0.7152 * channel(colour.greenF())
            + 0.0722 * channel(colour.blueF()))


def contrast(a: str, b: str) -> float:
    lighter, darker = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def hue_degrees(hex_colour: str) -> float:
    colour = QtGui.QColor(hex_colour)
    hue, _l, _s = colorsys.rgb_to_hls(colour.redF(), colour.greenF(), colour.blueF())
    return hue * 360.0


def hue_distance(a: str, b: str) -> float:
    gap = abs(hue_degrees(a) - hue_degrees(b)) % 360.0
    return min(gap, 360.0 - gap)


# --- palette -----------------------------------------------------------------


def test_every_palette_colour_is_a_valid_colour():
    palette = theme.PALETTE
    for name in ("background", "surface", "raised", "border", "text", "text_muted",
                 "text_disabled", "accent", "on_accent"):
        assert QtGui.QColor(getattr(palette, name)).isValid(), name


def test_accent_rgb_matches_the_accent():
    """The tint used for selections is derived from the accent by hand."""
    r, g, b = (int(part) for part in theme.PALETTE.accent_rgb.split(","))
    accent = QtGui.QColor(theme.PALETTE.accent)
    assert (accent.red(), accent.green(), accent.blue()) == (r, g, b)


def test_semantic_roles_come_from_the_palette():
    assert theme.BACKGROUND == theme.PALETTE.background
    assert theme.SURFACE == theme.PALETTE.surface
    assert theme.PLOT_BACKGROUND == theme.PALETTE.surface
    assert theme.ACCENT == theme.PALETTE.accent


def test_panels_are_lighter_than_the_window_and_raised_lighter_than_panels():
    """The depth the cards rely on: window < panel < raised."""
    assert (_luminance(theme.BACKGROUND)
            < _luminance(theme.SURFACE)
            < _luminance(theme.SURFACE_RAISED))


# --- legibility --------------------------------------------------------------


@pytest.mark.parametrize("ground", ["BACKGROUND", "SURFACE", "SURFACE_RAISED"])
@pytest.mark.parametrize("text", ["TEXT", "TEXT_MUTED"])
def test_text_meets_aa_on_every_surface(text, ground):
    ratio = contrast(getattr(theme, text), getattr(theme, ground))
    assert ratio >= AA, f"{text} on {ground}: {ratio:.1f}:1"


def test_the_accent_meets_aa_on_panels_because_it_is_used_as_text():
    """The session browser draws a few labels in the accent."""
    assert contrast(theme.ACCENT, theme.SURFACE) >= AA


def test_traces_stand_out_from_the_plot_background():
    for name, colour in DATA_COLOURS.items():
        assert contrast(colour, theme.PLOT_BACKGROUND) >= 3.0, name


# --- the accent is never a data colour ---------------------------------------


@pytest.mark.parametrize("name", sorted(DATA_COLOURS))
def test_the_accent_is_not_a_data_colour(name):
    """A highlighted row, an active button or a focus ring must not read as a
    lap. Hue is what the eye separates first, so the accent keeps well clear of
    every colour that means something on a trace."""
    gap = hue_distance(theme.ACCENT, DATA_COLOURS[name])
    assert gap >= 30.0, f"accent is only {gap:.0f} degrees from the {name} colour"


def test_the_reference_and_comparison_traces_are_not_a_red_green_pair():
    """The pair was chosen to survive the most common colour blindness."""
    assert hue_distance(theme.TRACE_REFERENCE, theme.TRACE_COMPARISON) > 90.0


# --- stylesheet --------------------------------------------------------------


def test_the_stylesheet_parses_without_complaint():
    """Qt reports a stylesheet it cannot parse as a warning and then ignores the
    rule, which is how a typo quietly un-styles half the window."""
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    messages: list[str] = []

    def handler(_kind, _context, message):
        messages.append(message)

    previous = QtCore.qInstallMessageHandler(handler)
    try:
        theme.apply(app)
        # Parsing happens when a widget polishes, not when the sheet is set.
        probe = QtWidgets.QWidget()
        probe.ensurePolished()
        probe.deleteLater()
    finally:
        QtCore.qInstallMessageHandler(previous)

    # Qt says two things about a sheet it dislikes: it cannot parse it at all, or
    # a property name is not one it knows (a typo). Empty values and a missing
    # colon pass silently, which is why the placeholder test below exists too.
    complaints = [m for m in messages
                  if "could not parse" in m.lower() or "unknown property" in m.lower()]
    assert complaints == []


def test_the_stylesheet_braces_balance():
    sheet = theme._stylesheet(theme.PALETTE)
    assert sheet.count("{") == sheet.count("}")


#: The Qt style sheet properties the theme uses. A name outside this list is
#: almost certainly a typo, which Qt only reports when a widget of that selector
#: happens to be polished - a tooltip rule is never exercised by a test widget.
#: Adding a legitimate property means adding it here.
KNOWN_QSS_PROPERTIES = frozenset({
    "alternate-background-color", "background", "background-color", "border",
    "border-bottom", "border-bottom-color", "border-color", "border-radius",
    "border-top", "color", "font-family", "font-size", "gridline-color", "height",
    "margin", "min-height", "min-width", "outline", "padding", "selection-background-color",
    "selection-color", "spacing", "text-align", "width",
})


def test_the_stylesheet_uses_only_known_properties():
    import re

    sheet = theme._stylesheet(theme.PALETTE)
    declared = set()
    for body in re.findall(r"\{([^{}]*)\}", sheet):
        for declaration in body.split(";"):
            if ":" in declaration:
                declared.add(declaration.split(":", 1)[0].strip())
    unknown = sorted(declared - KNOWN_QSS_PROPERTIES)
    assert unknown == [], f"unknown style sheet properties (typo?): {unknown}"


def test_the_stylesheet_has_no_empty_values():
    """`color: ;` is silently ignored by Qt, so a token that came out empty would
    un-style a rule without a word."""
    import re

    sheet = theme._stylesheet(theme.PALETTE)
    assert re.findall(r":\s*;", sheet) == []


def test_the_stylesheet_has_no_unresolved_placeholders():
    sheet = theme._stylesheet(theme.PALETTE)
    assert "{d." not in sheet
    assert "{PALETTE" not in sheet
    assert "{{" not in sheet and "}}" not in sheet


def test_the_stylesheet_names_every_palette_surface():
    sheet = theme._stylesheet(theme.PALETTE)
    for colour in (theme.BACKGROUND, theme.SURFACE, theme.SURFACE_RAISED,
                   theme.BORDER, theme.ACCENT):
        assert colour in sheet, colour


def test_pyqtgraph_follows_the_theme():
    import pyqtgraph as pg

    theme.configure_pyqtgraph()
    assert pg.getConfigOption("background") == theme.PLOT_BACKGROUND
    assert pg.getConfigOption("foreground") == theme.TEXT_MUTED
    assert pg.getConfigOption("antialias") is False
