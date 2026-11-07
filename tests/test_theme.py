"""The visual identity's guarantees.

These do not judge taste. They hold the properties the identity was chosen for:
text that can be read, an accent that cannot be mistaken for a lap, and a
stylesheet Qt can actually parse.
"""

from __future__ import annotations

import colorsys
import math
import os
import re
from pathlib import Path

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


# --- nothing styled outside the theme -----------------------------------------

PRESENTATION = Path(theme.__file__).parent

#: A colour written as a string: "#4da3ff", "#fff", "rgba(...)", "rgb(...)".
COLOUR_LITERAL = re.compile(r"""["']#[0-9a-fA-F]{3,8}["']|\brgba?\(""")


def _panel_sources() -> list[Path]:
    return sorted(p for p in PRESENTATION.glob("*.py") if p.name != "theme.py")


@pytest.mark.parametrize("path", _panel_sources(), ids=lambda p: p.name)
def test_no_panel_names_a_colour(path):
    """Every colour comes from the theme, so the look changes in one file."""
    hits = [
        f"{number}: {line.strip()}"
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if COLOUR_LITERAL.search(line)
    ]
    assert hits == []


@pytest.mark.parametrize("path", _panel_sources(), ids=lambda p: p.name)
def test_no_panel_carries_its_own_stylesheet(path):
    """A per-widget stylesheet is style the theme cannot see: a label coloured
    with one keeps that colour whatever the palette becomes. Panels give a
    widget a role or a tone instead."""
    assert "setStyleSheet(" not in path.read_text(encoding="utf-8")


# --- type scale ----------------------------------------------------------------


def test_the_type_scale_grows_step_by_step():
    sizes = [getattr(theme.TYPE, step) for step in theme.TypeScale.__slots__]
    assert sizes == sorted(sizes)
    assert len(set(sizes)) == len(sizes), "two steps of the scale are the same size"


def test_every_font_size_in_the_stylesheet_is_a_step_of_the_scale():
    sheet = theme._stylesheet(theme.PALETTE)
    used = {int(size) for size in re.findall(r"font-size:\s*(\d+)px", sheet)}
    steps = {getattr(theme.TYPE, step) for step in theme.TypeScale.__slots__}
    assert used and used <= steps


def test_body_text_is_the_body_step():
    sheet = theme._stylesheet(theme.PALETTE)
    widget_rule = re.search(r"QWidget \{([^}]*)\}", sheet).group(1)
    assert f"font-size: {theme.TYPE.body}px" in widget_rule


# --- tones ---------------------------------------------------------------------


@pytest.mark.parametrize("tone", list(theme.Tone))
def test_every_tone_has_a_colour_and_a_stylesheet_rule(tone):
    colour = theme.TONE_COLOURS[tone]
    assert QtGui.QColor(colour).isValid()
    assert f'QLabel[tone="{tone.value}"] {{ color: {colour}; }}' in theme._stylesheet(
        theme.PALETTE
    )


@pytest.mark.parametrize(("value", "higher_is_better", "expected"), [
    (-0.2, False, theme.Tone.GAIN),     # less time: better
    (+0.2, False, theme.Tone.LOSS),
    (+3.0, True, theme.Tone.GAIN),      # more speed: better
    (-3.0, True, theme.Tone.LOSS),
    (0.0, False, None),
    (None, True, None),
    (float("nan"), False, None),
    (float("inf"), True, None),
])
def test_the_verdict_rule(value, higher_is_better, expected):
    assert theme.verdict(value, higher_is_better=higher_is_better) is expected


def test_a_tone_reaches_the_drawn_colour_and_can_be_taken_back():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    theme.apply(app)
    label = QtWidgets.QLabel("x")
    label.setProperty("role", "stat")

    def drawn() -> str:
        label.ensurePolished()
        return label.palette().color(label.foregroundRole()).name()

    theme.set_tone(label, theme.Tone.LOSS)
    assert drawn() == theme.LOSS
    theme.set_tone(label, None)
    assert drawn() == theme.TEXT


def test_the_delta_fills_are_the_gain_and_loss_colours():
    assert QtGui.QColor(*theme.FILL_LOSS[:3]).name() == theme.LOSS
    assert QtGui.QColor(*theme.FILL_GAIN[:3]).name() == theme.GAIN


def test_the_map_loss_scale_keeps_neutral_dimmest():
    """Most of a lap is neutral; a bright neutral would hide the stretches that
    matter."""
    neutral = _luminance(theme.LOSS_SCALE[0])
    assert all(_luminance(theme.LOSS_SCALE[step]) > neutral for step in (-2, +2))
    assert sorted(theme.LOSS_SCALE) == [-2, -1, 0, 1, 2]


def test_rich_text_escapes_what_it_is_given():
    markup = theme.rich("<b>Volta 3</b>", theme.TEXT)
    assert "<b>" not in markup and "&lt;b&gt;" in markup


# --- colour blindness ------------------------------------------------------------

#: Machado, Oliveira & Fernandes (2009), severity 1.0, applied in linear RGB.
DICHROMACY = {
    "protanopia": ((0.152286, 1.052583, -0.204868),
                   (0.114503, 0.786281, 0.099216),
                   (-0.003882, -0.048116, 1.051998)),
    "deuteranopia": ((0.367322, 0.860646, -0.227968),
                     (0.280085, 0.672501, 0.047413),
                     (-0.011820, 0.042940, 0.968881)),
    "tritanopia": ((1.255528, -0.076749, -0.178779),
                   (-0.078411, 0.930809, 0.147602),
                   (0.004733, 0.691367, 0.303900)),
}


def _lab_as_seen(hex_colour: str, matrix) -> tuple[float, float, float]:
    colour = QtGui.QColor(hex_colour)

    def linear(value: float) -> float:
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    rgb = [linear(c) for c in (colour.redF(), colour.greenF(), colour.blueF())]
    seen = [min(max(sum(m * c for m, c in zip(row, rgb)), 0.0), 1.0) for row in matrix]
    xyz = (
        (0.4124 * seen[0] + 0.3576 * seen[1] + 0.1805 * seen[2]) / 0.95047,
        0.2126 * seen[0] + 0.7152 * seen[1] + 0.0722 * seen[2],
        (0.0193 * seen[0] + 0.1192 * seen[1] + 0.9505 * seen[2]) / 1.08883,
    )
    f = [v ** (1 / 3) if v > 0.008856 else 7.787 * v + 16 / 116 for v in xyz]
    return 116 * f[1] - 16, 500 * (f[0] - f[1]), 200 * (f[1] - f[2])


@pytest.mark.parametrize("kind", sorted(DICHROMACY))
def test_reference_and_comparison_survive_colour_blindness(kind):
    """The two laps are told apart by colour on every trace, so the pair must
    stay far apart for the three dichromacies, not just the common one. 40 in
    CIE76 is well past "obviously different" (about 20); the pair sits at 84 or
    more."""
    matrix = DICHROMACY[kind]
    a = _lab_as_seen(theme.TRACE_REFERENCE, matrix)
    b = _lab_as_seen(theme.TRACE_COMPARISON, matrix)
    assert math.dist(a, b) >= 40.0
