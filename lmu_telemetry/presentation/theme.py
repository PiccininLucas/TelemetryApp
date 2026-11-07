"""Dark theme.

Dark by default, as the specification asks. It is also the right choice for the
job: telemetry traces are thin bright lines, and thin lines on a dark ground
carry far better than on white - which is why every timing screen in a pit lane
looks like this.

Two layers, so a look can change without touching a panel:

1. **The `Palette`** - the raw ingredients of the identity: four surface steps,
   three text steps, one accent, the corner radius, the type.
2. **Semantic roles** - `BACKGROUND`, `SURFACE`, `TEXT_MUTED`, `ACCENT`... - which
   the panels use. They are read from the palette.

Data colours are *not* part of the palette. The reference and comparison laps,
the pedal states and the gain/loss fill mean the same thing whatever the
chrome looks like, so they are fixed below. That gives the one rule the whole
identity rests on: **the accent is never a data colour.** Blue, orange, green,
red and grey already carry meaning on the traces; the accent lives in the hues
the data does not use, so a highlighted row can never be mistaken for a lap.

pyqtgraph keeps its own global background and foreground settings, separate from
Qt's palette, so both have to be set.
"""

from __future__ import annotations

import html
import math
from dataclasses import dataclass
from enum import StrEnum

import pyqtgraph as pg
from PySide6 import QtGui, QtWidgets


@dataclass(frozen=True, slots=True)
class TypeScale:
    """Font sizes, in pixels, smallest first.

    Six steps and no more: a size outside this list is a size nobody chose. The
    panels name a step, never a number, so the whole interface scales from here.
    """

    #: Marks drawn among other marks on a plot - the turn numbers on the map,
    #: where four labels can sit within a few pixels of each other.
    micro: int
    #: The caption over a figure, a section rule inside a card.
    caption: int
    #: Column headers, dock titles, plot titles.
    label: int
    #: Everything else.
    body: int
    #: A figure in the session header.
    stat: int
    #: The one line that names what is open.
    title: int


@dataclass(frozen=True, slots=True)
class Palette:
    """The ingredients of the visual identity."""

    #: The window itself, seen between and around the panels.
    background: str
    #: A panel: the dock bodies, the plots, the tables.
    surface: str
    #: Something sitting on a panel: headers, buttons, menus, hover.
    raised: str
    border: str
    text: str
    text_muted: str
    text_disabled: str
    accent: str
    #: The accent as a tint, for selections: `r, g, b` for `rgba()`.
    accent_rgb: str
    #: Text drawn on a solid accent.
    on_accent: str
    radius: int
    #: Vertical and horizontal padding of buttons and tabs, in pixels.
    pad: tuple[int, int]
    font_ui: str
    font_display: str
    sizes: TypeScale


#: Night stint: ink-violet surfaces, rounded, one violet accent.
#:
#: Segoe UI Variable ships with Windows 11 and Bahnschrift with Windows 10 and
#: later; each font list ends in a generic family, so any other system degrades
#: to whatever it has.
PALETTE = Palette(
    background="#0c0d14", surface="#141521", raised="#1d1f30", border="#2a2c42",
    text="#e9eaf5", text_muted="#9fa2bd", text_disabled="#5d6080",
    accent="#8f7cff", accent_rgb="143, 124, 255", on_accent="#0c0d14",
    radius=8, pad=(7, 12),
    font_ui='"Segoe UI Variable Text", "Segoe UI", "Helvetica Neue", Arial, sans-serif',
    font_display='"Bahnschrift", "Segoe UI Semibold", sans-serif',
    sizes=TypeScale(micro=10, caption=11, label=12, body=13, stat=15, title=17),
)

# --- Semantic roles ---------------------------------------------------------
BACKGROUND = PALETTE.background
SURFACE = PALETTE.surface
SURFACE_RAISED = PALETTE.raised
BORDER = PALETTE.border

#: What the plots are painted on. A panel colour, not the window's, so a chart
#: reads as a card sitting on the background.
PLOT_BACKGROUND = PALETTE.surface

TEXT = PALETTE.text
TEXT_MUTED = PALETTE.text_muted
TEXT_DISABLED = PALETTE.text_disabled

ACCENT = PALETTE.accent
WARNING = "#f0b132"
ERROR = "#e5484d"

#: The type scale, by step: `TYPE.caption`, `TYPE.body`...
TYPE = PALETTE.sizes
#: Text pyqtgraph draws itself (plot titles), as the CSS size it expects.
PLOT_TEXT_SIZE = f"{TYPE.label}px"

# --- Data colours (fixed: they are not part of the palette) -----------------
#: Trace colours. The first two are the reference and comparison laps, chosen to
#: stay distinguishable for the most common form of colour blindness - a
#: red/green pair would not.
TRACE_REFERENCE = "#4da3ff"
TRACE_COMPARISON = "#f5a524"
TRACE_IDEAL = "#30c48d"
#: The reference trace as `r, g, b`, for translucent fills.
TRACE_REFERENCE_RGB = (77, 163, 255)

#: Pedal states, for colouring the track map and the pedal traces.
COLOUR_BRAKE = "#e5484d"
COLOUR_THROTTLE = "#30c48d"
COLOUR_COAST = "#9aa0a8"

#: Better and worse than the reference. They reuse the pedal hues - green is
#: the car going, red is time spent - and are the only red/green pair in the
#: interface. Every place that uses them also prints the sign (or puts the fill
#: on one side of zero), so the colour is never the only cue.
GAIN = "#30c48d"
LOSS = "#e5484d"
#: The session's best lap and best sectors: the ideal lap's colour, because the
#: ideal lap is made of exactly these.
BEST = TRACE_IDEAL

#: Loss classes from `analysis.delta.loss_classes`, for the track map: two
#: steps each way. Neutral is deliberately dim - most of a lap is neutral, and a
#: bright neutral would drown out the few stretches worth looking at.
LOSS_SCALE: dict[int, str] = {
    -2: "#ff4d52",
    -1: "#a8383c",
    0: "#4a5058",
    +1: "#2a8f68",
    +2: "#3ce09f",
}


def _rgb(hex_colour: str) -> tuple[int, int, int]:
    value = hex_colour.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


#: Fill under the delta-t curve: the loss and gain colours, translucent.
FILL_LOSS = (*_rgb(LOSS), 70)
FILL_GAIN = (*_rgb(GAIN), 70)

GRID_ALPHA = 0.15

#: Fixed width of every plot's left axis, in pixels. Stacked plots each size
#: their own axis to their own tick labels, so "1200" and "6" would put the two
#: traces at different left edges and destroy the vertical alignment that makes
#: reading a braking point across rows possible.
AXIS_WIDTH = 62


# --- Tones: what a coloured figure means ------------------------------------


class Tone(StrEnum):
    """Why a figure is coloured.

    Panels say what a value *means* - better, worse, best, worth a look, not
    comparable - and the theme decides what that looks like. On a label the tone
    is a dynamic property the stylesheet reads (`set_tone`); on a table or tree
    item, which a stylesheet cannot reach, it is a foreground (`tone_colour`).
    """

    GAIN = "gain"
    LOSS = "loss"
    BEST = "best"
    WARNING = "warning"
    DIM = "dim"


TONE_COLOURS: dict[Tone, str] = {
    Tone.GAIN: GAIN,
    Tone.LOSS: LOSS,
    Tone.BEST: BEST,
    Tone.WARNING: WARNING,
    Tone.DIM: TEXT_DISABLED,
}


def verdict(value: float | None, *, higher_is_better: bool) -> Tone | None:
    """Gain where the lap on screen is better than its reference, loss where worse.

    The one rule for every delta in the interface - the corner table, the corner
    card, the header and the trace readout - so they can never disagree. Zero,
    missing and non-finite values are no verdict at all.
    """
    if value is None or not math.isfinite(value) or value == 0.0:
        return None
    better = value > 0 if higher_is_better else value < 0
    return Tone.GAIN if better else Tone.LOSS


def tone_colour(tone: Tone | None, default: str = TEXT) -> str:
    """The colour of a tone, or `default` for no tone."""
    return default if tone is None else TONE_COLOURS[tone]


def set_tone(widget: QtWidgets.QWidget, tone: Tone | None) -> None:
    """Give a label a tone; `None` returns it to its role's colour.

    Qt does not restyle a widget when a property the stylesheet selects on
    changes, so the widget is re-polished here.
    """
    value = "" if tone is None else tone.value
    if widget.property("tone") == value:
        return
    widget.setProperty("tone", value)
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)


def emphasised(font: QtGui.QFont) -> QtGui.QFont:
    """The weight for a row that stands above its neighbours: a track heading,
    the best lap."""
    font.setWeight(QtGui.QFont.Weight.DemiBold)
    return font


def font(size_px: int) -> QtGui.QFont:
    """A font at one step of `TYPE`, for text drawn on a plot, which no
    stylesheet reaches."""
    result = QtGui.QFont()
    result.setPixelSize(size_px)
    return result


def rich(text: str, colour: str, *, italic: bool = False) -> str:
    """Coloured rich text for a `QLabel`: legends and readouts that mix colours
    in one line, which a stylesheet cannot do."""
    style = f"color:{colour}" + (";font-style:italic" if italic else "")
    return f'<span style="{style}">{html.escape(text)}</span>'


def apply(app: QtWidgets.QApplication) -> None:
    """Apply the dark theme to an application."""
    app.setStyle("Fusion")
    app.setPalette(_palette())
    app.setStyleSheet(_stylesheet(PALETTE))
    configure_pyqtgraph()


def configure_pyqtgraph() -> None:
    """Point pyqtgraph's globals at the same colours as the widgets.

    Set before any plot is constructed; pyqtgraph reads these at widget
    creation and does not restyle existing plots.
    """
    pg.setConfigOption("background", PLOT_BACKGROUND)
    pg.setConfigOption("foreground", TEXT_MUTED)
    # Anti-aliasing costs redraw time on traces of hundreds of thousands of
    # points, which is exactly the case here, so it stays off. Downsampling in
    # the plot widgets is what keeps the lines readable.
    pg.setConfigOption("antialias", False)


def _palette() -> QtGui.QPalette:
    palette = QtGui.QPalette()
    role = QtGui.QPalette.ColorRole
    group = QtGui.QPalette.ColorGroup

    palette.setColor(role.Window, QtGui.QColor(BACKGROUND))
    palette.setColor(role.WindowText, QtGui.QColor(TEXT))
    palette.setColor(role.Base, QtGui.QColor(SURFACE))
    palette.setColor(role.AlternateBase, QtGui.QColor(SURFACE_RAISED))
    palette.setColor(role.Text, QtGui.QColor(TEXT))
    palette.setColor(role.Button, QtGui.QColor(SURFACE_RAISED))
    palette.setColor(role.ButtonText, QtGui.QColor(TEXT))
    palette.setColor(role.Highlight, QtGui.QColor(ACCENT))
    palette.setColor(role.HighlightedText, QtGui.QColor(PALETTE.on_accent))
    palette.setColor(role.ToolTipBase, QtGui.QColor(SURFACE_RAISED))
    palette.setColor(role.ToolTipText, QtGui.QColor(TEXT))
    palette.setColor(role.PlaceholderText, QtGui.QColor(TEXT_DISABLED))

    for state in (group.Disabled,):
        palette.setColor(state, role.Text, QtGui.QColor(TEXT_DISABLED))
        palette.setColor(state, role.ButtonText, QtGui.QColor(TEXT_DISABLED))
        palette.setColor(state, role.WindowText, QtGui.QColor(TEXT_DISABLED))

    return palette


def _stylesheet(d: Palette) -> str:
    """The whole look, from the palette.

    Widgets are transparent by default and take their colour from whatever they
    sit on, so the only places that name a surface are the window, the panels
    (docks and the centre) and the few widgets Qt paints itself. That is what
    lets a panel be a card without every label inside it carrying a background.
    """
    r = d.radius
    t = d.sizes
    warning_tint = f"rgba({', '.join(map(str, _rgb(WARNING)))}, 0.12)"
    py, px = d.pad
    tint = f"rgba({d.accent_rgb}, 0.18)"
    tint_hover = f"rgba({d.accent_rgb}, 0.10)"
    return f"""
    QWidget {{
        background-color: transparent;
        color: {d.text};
        font-family: {d.font_ui};
        font-size: {t.body}px;
    }}
    QMainWindow, QDialog, QMessageBox {{
        background-color: {d.background};
    }}
    QMainWindow::separator {{
        background-color: {d.background};
        width: 8px;
        height: 8px;
    }}

    /* Panels: the docks and the centre are cards on the background. */
    QDockWidget {{
        background-color: {d.surface};
        border: 1px solid {d.border};
        color: {d.text_muted};
    }}
    QDockWidget::title {{
        background-color: {d.surface};
        border-bottom: 1px solid {d.border};
        padding: {py + 2}px {px}px;
        text-align: left;
        font-family: {d.font_display};
        font-size: {t.label}px;
    }}
    QDockWidget::close-button, QDockWidget::float-button {{
        background: transparent;
        border: none;
        padding: 2px;
        border-radius: {max(r - 2, 1)}px;
    }}
    QDockWidget::close-button:hover, QDockWidget::float-button:hover {{
        background-color: {d.raised};
    }}
    QWidget#central {{
        background-color: {d.surface};
        border: 1px solid {d.border};
    }}

    /* Toolbar and menus. */
    QMenuBar {{
        background-color: {d.background};
        padding: 2px 6px;
    }}
    QMenuBar::item {{
        padding: 5px 9px;
        border-radius: {r}px;
    }}
    QMenuBar::item:selected {{
        background-color: {d.raised};
    }}
    QMenu {{
        background-color: {d.raised};
        border: 1px solid {d.border};
        padding: 4px;
    }}
    QMenu::item {{
        padding: 6px 22px 6px 14px;
        border-radius: {max(r - 2, 1)}px;
    }}
    QMenu::item:selected {{
        background-color: {tint};
    }}
    QMenu::separator {{
        height: 1px;
        background: {d.border};
        margin: 4px 6px;
    }}
    QToolBar {{
        background-color: {d.background};
        border: none;
        padding: 4px 8px 8px 8px;
        spacing: 2px;
    }}
    QToolBar::separator {{
        background-color: {d.border};
        width: 1px;
        margin: 5px 6px;
    }}
    QToolButton {{
        background-color: transparent;
        color: {d.text_muted};
        border: 1px solid transparent;
        border-radius: {r}px;
        padding: {py}px {max(px - 6, 5)}px;
    }}
    QToolButton:hover {{
        background-color: {d.raised};
        color: {d.text};
    }}
    QToolButton:checked {{
        background-color: {tint};
        border-color: {d.accent};
        color: {d.text};
    }}
    QToolButton:disabled {{
        color: {d.text_disabled};
    }}
    QStatusBar {{
        background-color: {d.background};
        color: {d.text_muted};
        border-top: 1px solid {d.border};
    }}
    QStatusBar::item {{
        border: none;
    }}

    /* Tabs: an underline, not a box. */
    QTabWidget::pane {{
        border: none;
        border-top: 1px solid {d.border};
    }}
    QTabBar::tab {{
        background-color: transparent;
        color: {d.text_muted};
        padding: {py + 1}px {px + 4}px;
        border: none;
        border-bottom: 2px solid transparent;
        font-family: {d.font_display};
    }}
    QTabBar::tab:hover {{
        color: {d.text};
    }}
    QTabBar::tab:selected {{
        color: {d.text};
        border-bottom-color: {d.accent};
    }}

    /* Lists and tables. */
    QTreeWidget, QTreeView, QTableWidget, QTableView {{
        background-color: {d.surface};
        alternate-background-color: {d.surface};
        border: none;
        outline: none;
        gridline-color: {d.border};
        selection-background-color: {tint};
        selection-color: {d.text};
    }}
    QTreeWidget::item {{
        padding: 4px 2px;
        border: none;
    }}
    QTreeWidget::item:selected {{
        background-color: {tint};
        color: {d.text};
    }}
    QTreeWidget::item:hover:!selected {{
        background-color: {tint_hover};
    }}
    QHeaderView::section {{
        background-color: {d.surface};
        color: {d.text_muted};
        border: none;
        border-bottom: 1px solid {d.border};
        padding: {py}px {px - 2}px;
        font-family: {d.font_display};
        font-size: {t.label}px;
    }}

    /* Controls. */
    QComboBox {{
        background-color: {d.raised};
        border: 1px solid {d.border};
        border-radius: {r}px;
        padding: {max(py - 2, 2)}px {px}px;
        min-height: 18px;
    }}
    QComboBox:hover, QComboBox:focus {{
        border-color: {d.accent};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 22px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {d.raised};
        border: 1px solid {d.border};
        selection-background-color: {tint};
        selection-color: {d.text};
        outline: none;
    }}
    QLineEdit {{
        background-color: {d.raised};
        border: 1px solid {d.accent};
        border-radius: {max(r - 2, 1)}px;
        padding: 2px 6px;
        selection-background-color: {d.accent};
        selection-color: {d.on_accent};
    }}
    QPushButton {{
        background-color: {d.raised};
        border: 1px solid {d.border};
        border-radius: {r}px;
        padding: {py}px {px + 4}px;
    }}
    QPushButton:hover {{
        border-color: {d.accent};
    }}
    QPushButton:disabled {{
        color: {d.text_disabled};
    }}
    QToolTip {{
        background-color: {d.raised};
        color: {d.text};
        border: 1px solid {d.border};
        padding: 4px 8px;
    }}

    QScrollBar:vertical {{
        background: transparent;
        width: 11px;
        margin: 0;
    }}
    QScrollBar:horizontal {{
        background: transparent;
        height: 11px;
        margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: {d.border};
        border-radius: 4px;
        min-height: 28px;
        margin: 2px;
    }}
    QScrollBar::handle:horizontal {{
        background: {d.border};
        border-radius: 4px;
        min-width: 28px;
        margin: 2px;
    }}
    QScrollBar::handle:hover {{
        background: {d.text_disabled};
    }}
    QScrollBar::add-line, QScrollBar::sub-line {{
        width: 0;
        height: 0;
    }}
    QScrollBar::add-page, QScrollBar::sub-page {{
        background: transparent;
    }}

    QSplitter::handle {{
        background-color: {d.border};
    }}
    QSplitter::handle:horizontal {{ width: 1px; }}
    QSplitter::handle:vertical {{ height: 1px; }}

    /* Roles set from code with `setProperty("role", ...)`. */
    QLabel[role="warning"] {{
        background-color: {warning_tint};
        color: {WARNING};
        border: 1px solid {WARNING};
        border-radius: {r}px;
        margin: 8px 8px 0 8px;
        padding: 6px 10px;
    }}
    QLabel[role="heading"] {{
        color: {d.text_muted};
        font-family: {d.font_display};
        padding: 6px 4px 4px 4px;
    }}
    QLabel[role="placeholder"] {{
        color: {d.text_disabled};
    }}

    /* The session header: a strip of figures across the top of the window. */
    QToolBar#toolbar_header {{
        background-color: {d.surface};
        border-top: 1px solid {d.border};
        border-bottom: 1px solid {d.border};
        padding: 6px 12px;
    }}
    QScrollArea#header_scroll, QWidget#header_content,
    QScrollArea#detail_scroll, QWidget#detail_content {{
        background: transparent;
        border: none;
    }}
    QLabel[role="title"] {{
        color: {d.text};
        font-family: {d.font_display};
        font-size: {t.title}px;
    }}
    QLabel[role="caption"] {{
        color: {d.text_muted};
        font-size: {t.caption}px;
    }}
    QLabel[role="stat"] {{
        color: {d.text};
        font-family: {d.font_display};
        font-size: {t.stat}px;
    }}
    QLabel[role="section"] {{
        color: {d.text_muted};
        font-family: {d.font_display};
        font-size: {t.caption}px;
        padding: 8px 0 3px 0;
        border-bottom: 1px solid {d.border};
    }}
    QFrame[role="divider"] {{
        background-color: {d.border};
        border: none;
    }}
    """ + _tone_rules()


def _tone_rules() -> str:
    """One rule per tone. Last in the sheet so a tone wins over a label's role,
    which selects with the same specificity."""
    return "".join(
        f'\n    QLabel[tone="{tone.value}"] {{ color: {colour}; }}'
        for tone, colour in TONE_COLOURS.items()
    ) + "\n"
