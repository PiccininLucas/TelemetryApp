"""Dark theme.

Dark by default, as the specification asks. It is also the right choice for the
job: telemetry traces are thin bright lines, and thin lines on a dark ground
carry far better than on white - which is why every timing screen in a pit lane
looks like this.

Colours are defined once here so the charts and the widgets agree. `pyqtgraph`
keeps its own global background and foreground settings, separate from Qt's
palette, so both have to be set.
"""

from __future__ import annotations

import pyqtgraph as pg
from PySide6 import QtGui, QtWidgets

# --- Surfaces ---------------------------------------------------------------
BACKGROUND = "#1a1c20"
SURFACE = "#22252b"
SURFACE_RAISED = "#2b2f36"
BORDER = "#3a3f47"

# --- Text -------------------------------------------------------------------
TEXT = "#e6e8ea"
TEXT_MUTED = "#9aa0a8"
TEXT_DISABLED = "#5f656d"

# --- Accents ----------------------------------------------------------------
ACCENT = "#4da3ff"
WARNING = "#f0b132"
ERROR = "#e5484d"

#: Trace colours. The first two are the reference and comparison laps, chosen to
#: stay distinguishable for the most common form of colour blindness - a
#: red/green pair would not.
TRACE_REFERENCE = "#4da3ff"
TRACE_COMPARISON = "#f5a524"
TRACE_IDEAL = "#30c48d"

#: Pedal states, for colouring the track map and the pedal traces.
COLOUR_BRAKE = "#e5484d"
COLOUR_THROTTLE = "#30c48d"
COLOUR_COAST = "#9aa0a8"

#: Fill under the delta-t curve. Red where the lap is behind the reference,
#: green where it is ahead - the one place in the interface where a red/green
#: pair is used, because the sign is also given by which side of zero the fill
#: sits on, so the colour is never the only cue.
FILL_LOSS = (229, 72, 77, 70)
FILL_GAIN = (48, 196, 141, 70)

GRID_ALPHA = 0.15

#: Fixed width of every plot's left axis, in pixels. Stacked plots each size
#: their own axis to their own tick labels, so "1200" and "6" would put the two
#: traces at different left edges and destroy the vertical alignment that makes
#: reading a braking point across rows possible.
AXIS_WIDTH = 62


def apply(app: QtWidgets.QApplication) -> None:
    """Apply the dark theme to an application."""
    app.setStyle("Fusion")
    app.setPalette(_palette())
    app.setStyleSheet(_stylesheet())
    configure_pyqtgraph()


def configure_pyqtgraph() -> None:
    """Point pyqtgraph's globals at the same colours as the widgets.

    Set before any plot is constructed; pyqtgraph reads these at widget
    creation and does not restyle existing plots.
    """
    pg.setConfigOption("background", BACKGROUND)
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
    palette.setColor(role.HighlightedText, QtGui.QColor(BACKGROUND))
    palette.setColor(role.ToolTipBase, QtGui.QColor(SURFACE_RAISED))
    palette.setColor(role.ToolTipText, QtGui.QColor(TEXT))
    palette.setColor(role.PlaceholderText, QtGui.QColor(TEXT_DISABLED))

    for state in (group.Disabled,):
        palette.setColor(state, role.Text, QtGui.QColor(TEXT_DISABLED))
        palette.setColor(state, role.ButtonText, QtGui.QColor(TEXT_DISABLED))
        palette.setColor(state, role.WindowText, QtGui.QColor(TEXT_DISABLED))

    return palette


def _stylesheet() -> str:
    return f"""
    QWidget {{
        background-color: {BACKGROUND};
        color: {TEXT};
        font-size: 13px;
    }}
    QTreeWidget, QTreeView {{
        background-color: {SURFACE};
        alternate-background-color: {SURFACE};
        border: 1px solid {BORDER};
        outline: none;
    }}
    QTreeWidget::item {{
        padding: 3px 2px;
        border: none;
    }}
    QTreeWidget::item:selected {{
        background-color: {ACCENT};
        color: {BACKGROUND};
    }}
    QTreeWidget::item:hover:!selected {{
        background-color: {SURFACE_RAISED};
    }}
    QHeaderView::section {{
        background-color: {SURFACE_RAISED};
        color: {TEXT_MUTED};
        border: none;
        border-bottom: 1px solid {BORDER};
        padding: 5px 6px;
    }}
    QSplitter::handle {{
        background-color: {BORDER};
    }}
    QSplitter::handle:horizontal {{ width: 1px; }}
    QSplitter::handle:vertical {{ height: 1px; }}
    QStatusBar {{
        background-color: {SURFACE};
        color: {TEXT_MUTED};
        border-top: 1px solid {BORDER};
    }}
    QMenuBar {{
        background-color: {SURFACE};
        border-bottom: 1px solid {BORDER};
    }}
    QMenuBar::item:selected {{
        background-color: {SURFACE_RAISED};
    }}
    QMenu {{
        background-color: {SURFACE_RAISED};
        border: 1px solid {BORDER};
    }}
    QMenu::item:selected {{
        background-color: {ACCENT};
        color: {BACKGROUND};
    }}
    QLabel[role="warning"] {{
        background-color: #3a2f18;
        color: {WARNING};
        border: 1px solid {WARNING};
        border-radius: 3px;
        padding: 6px 10px;
    }}
    QLabel[role="heading"] {{
        color: {TEXT_MUTED};
        font-weight: 600;
        padding: 6px 4px 4px 4px;
    }}
    QLabel[role="placeholder"] {{
        color: {TEXT_DISABLED};
    }}
    """
