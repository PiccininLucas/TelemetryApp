"""The circuit drawn from the lap's own GPS trace, coloured by what happened.

The map answers the question a trace cannot: *where*. A delta row says a lap
lost 0.19 s somewhere around 990 m; the map says it lost it at the first
chicane. Reading a distance off an axis and translating it into a corner is
work the driver should not have to do.

**Two colourings, because there are two questions.**

- *Pedals* — braking red, coasting grey, throttle green. Coasting is the one
  that matters: as a number it is 2% of a lap and easy to dismiss, and as a
  stretch of tarmac between the brake release and the throttle it is obviously
  a corner entered too slowly or a brake released too early.
- *Gain and loss* — where the compared lap is gaining or losing against its
  reference. Coloured by the **slope** of the delta, never its value: colouring
  by value paints the whole second half of the lap red because of one mistake
  at turn one.

Both are integer classes, so the path is drawn as runs of constant colour -
one polyline per run. That keeps a 13 600-point Le Mans lap to a few hundred
items instead of 13 600 coloured points, and it draws as a line rather than a
string of dots at any zoom.

**Equal aspect ratio, always.** A circuit stretched to fill a panel is not a
circuit. Monza's bounding box is 1257 x 2169 m and it has to stay that shape.
"""

from __future__ import annotations

from enum import Enum

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets

from lmu_telemetry.ui import strings, theme


class MapColour(str, Enum):
    """What the path's colour encodes."""

    #: Braking, coasting, on throttle. Always available.
    PEDALS = "pedals"
    #: Where the lap gains or loses against its reference. Needs a comparison.
    DELTA = "delta"


#: Colour of each pedal class, keyed by the value `trackmap.pedal_state`
#: returns.
PEDAL_COLOURS: dict[int, str] = {
    -1: theme.COLOUR_BRAKE,
    0: theme.COLOUR_COAST,
    +1: theme.COLOUR_THROTTLE,
}

#: Colour of each loss class from `analysis.delta.loss_classes`. Neutral is
#: deliberately dim: most of a lap is neutral, and a bright neutral would drown
#: out the few stretches worth looking at.
LOSS_COLOURS: dict[int, str] = {
    -2: "#ff4d52",
    -1: "#a8383c",
    0: "#4a5058",
    +1: "#2a8f68",
    +2: "#3ce09f",
}

#: Legend entries per mode: (class value, label).
PEDAL_LEGEND = (
    (-1, strings.MAP_LEGEND_BRAKE),
    (0, strings.MAP_LEGEND_COAST),
    (+1, strings.MAP_LEGEND_THROTTLE),
)
LOSS_LEGEND = (
    (-2, strings.MAP_LEGEND_LOSS),
    (0, strings.MAP_LEGEND_NEUTRAL),
    (+2, strings.MAP_LEGEND_GAIN),
)


class TrackMap(QtWidgets.QWidget):
    """The lap's path, coloured by pedal state or by where time moved."""

    #: Emitted when the mouse picks a point on the path, carrying its distance
    #: around the lap. Lets the map drive the traces as well as follow them.
    distance_picked = QtCore.Signal(float)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._mode = MapColour.PEDALS
        self._x: np.ndarray | None = None
        self._y: np.ndarray | None = None
        self._grid_m: np.ndarray | None = None
        self._classes: dict[MapColour, np.ndarray] = {}
        self._runs: list[pg.PlotDataItem] = []
        self._build()

    def _build(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        heading = QtWidgets.QLabel(strings.MAP_TITLE)
        heading.setProperty("role", "heading")
        layout.addWidget(heading)

        self.plot = pg.PlotWidget()
        self.plot.setBackground(theme.BACKGROUND)
        self.plot.setMenuEnabled(False)
        self.plot.hideAxis("left")
        self.plot.hideAxis("bottom")
        # A circuit stretched to fill the panel is not a circuit.
        self.plot.setAspectLocked(True)
        layout.addWidget(self.plot, stretch=1)

        # The reconstructed path, drawn under everything and off by default.
        self._integrated = self.plot.plot(
            pen=pg.mkPen(theme.TEXT_DISABLED, width=1,
                         style=QtCore.Qt.PenStyle.DashLine)
        )
        self._integrated.setVisible(False)

        # Start and finish, so the map has an orientation.
        self._start = pg.ScatterPlotItem(
            size=9, pen=pg.mkPen(theme.BACKGROUND, width=1),
            brush=pg.mkBrush(theme.TEXT),
        )
        self.plot.addItem(self._start)

        self._cursor = pg.ScatterPlotItem(
            size=11, pen=pg.mkPen(theme.TEXT, width=2),
            brush=pg.mkBrush(theme.BACKGROUND),
        )
        self._cursor.setVisible(False)
        self.plot.addItem(self._cursor)

        self.legend = QtWidgets.QLabel()
        self.legend.setTextFormat(QtCore.Qt.TextFormat.RichText)
        self.legend.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.legend)

        self.caption = QtWidgets.QLabel()
        self.caption.setProperty("role", "placeholder")
        self.caption.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.caption.setWordWrap(True)
        layout.addWidget(self.caption)

        self.placeholder = QtWidgets.QLabel(strings.MAP_NO_DATA)
        self.placeholder.setProperty("role", "placeholder")
        self.placeholder.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.placeholder.setWordWrap(True)
        layout.addWidget(self.placeholder, stretch=1)

        self.plot.scene().sigMouseMoved.connect(self._on_mouse_moved)
        self.clear()

    # -- data --------------------------------------------------------------

    def show_path(
        self,
        x_m: np.ndarray,
        y_m: np.ndarray,
        grid_m: np.ndarray,
        pedal_states: np.ndarray | None = None,
        loss_classes: np.ndarray | None = None,
        caption: str = "",
    ) -> None:
        """Draw one lap's path.

        Args:
            x_m: Eastward position at each grid point.
            y_m: Northward position.
            grid_m: Distance around the lap, same length.
            pedal_states: -1 braking, 0 coasting, +1 throttle.
            loss_classes: -2..+2 from `analysis.delta.loss_classes`.
            caption: Shown under the map.
        """
        self._x = np.asarray(x_m, dtype=np.float64)
        self._y = np.asarray(y_m, dtype=np.float64)
        self._grid_m = np.asarray(grid_m, dtype=np.float64)

        self._classes = {}
        if pedal_states is not None:
            self._classes[MapColour.PEDALS] = np.asarray(pedal_states, dtype=np.int8)
        if loss_classes is not None:
            self._classes[MapColour.DELTA] = np.asarray(loss_classes, dtype=np.int8)

        # Fall back rather than showing an uncoloured map: the mode may have
        # been left on delta by a previous lap that had a comparison.
        if self._mode not in self._classes and MapColour.PEDALS in self._classes:
            self._mode = MapColour.PEDALS

        self.placeholder.hide()
        self.plot.show()
        self.legend.show()
        self.caption.show()
        self.caption.setText(caption)
        self._redraw()

    def show_integrated(self, x_m: np.ndarray, y_m: np.ndarray) -> None:
        """Overlay the path reconstructed from lateral acceleration alone.

        Drawn dashed and dim because it is a cross-check, not a measurement:
        it uses no position data, so how far it strays is a statement about the
        `omega = a_y / V` assumption rather than about the lap.
        """
        self._integrated.setData(np.asarray(x_m), np.asarray(y_m))

    def set_integrated_visible(self, visible: bool) -> None:
        self._integrated.setVisible(visible)

    def clear(self) -> None:
        self._x = self._y = self._grid_m = None
        self._classes = {}
        self._clear_runs()
        self._integrated.setData([], [])
        self._start.setData([], [])
        self._cursor.setVisible(False)
        self.plot.hide()
        self.legend.hide()
        self.caption.hide()
        self.placeholder.show()

    @property
    def colour_mode(self) -> MapColour:
        return self._mode

    def available_modes(self) -> set[MapColour]:
        return set(self._classes)

    def set_colour_mode(self, mode: MapColour) -> None:
        if mode is self._mode or mode not in self._classes:
            return
        self._mode = mode
        self._redraw()

    # -- drawing -----------------------------------------------------------

    def _clear_runs(self) -> None:
        for item in self._runs:
            self.plot.removeItem(item)
        self._runs = []

    def _redraw(self) -> None:
        self._clear_runs()
        if self._x is None or not len(self._x):
            return

        classes = self._classes.get(self._mode)
        colours = (PEDAL_COLOURS if self._mode is MapColour.PEDALS
                   else LOSS_COLOURS)

        if classes is None or len(classes) != len(self._x):
            self._runs.append(
                self.plot.plot(self._x, self._y,
                               pen=pg.mkPen(theme.TEXT_MUTED, width=2))
            )
        else:
            for start, end, value in _runs_of(classes):
                # Extend each run by one point so consecutive runs share an
                # endpoint; without it the path shows a gap at every colour
                # change, which on a pedal map is every braking point.
                stop = min(end + 1, len(self._x))
                self._runs.append(self.plot.plot(
                    self._x[start:stop], self._y[start:stop],
                    pen=pg.mkPen(colours.get(int(value), theme.TEXT_MUTED),
                                 width=2.4),
                ))

        self._start.setData([self._x[0]], [self._y[0]])
        self._update_legend()
        self.plot.enableAutoRange()

    def _update_legend(self) -> None:
        entries = (PEDAL_LEGEND if self._mode is MapColour.PEDALS
                   else LOSS_LEGEND)
        colours = (PEDAL_COLOURS if self._mode is MapColour.PEDALS
                   else LOSS_COLOURS)
        self.legend.setText("   ".join(
            f'<span style="color:{colours[value]}">&#9632;</span> {label}'
            for value, label in entries
        ))

    # -- cursor ------------------------------------------------------------

    def set_cursor_distance(self, distance_m: float) -> None:
        """Put the marker at a distance around the lap."""
        if self._grid_m is None or not len(self._grid_m):
            return
        index = int(np.clip(
            np.searchsorted(self._grid_m, distance_m), 0, len(self._grid_m) - 1
        ))
        self._cursor.setData([self._x[index]], [self._y[index]])
        self._cursor.setVisible(True)

    def _on_mouse_moved(self, position) -> None:
        """Pick the nearest point on the path and report its distance.

        Brute force over every point rather than a spatial index: a Le Mans lap
        is 13 600 points, one hypot over them is well under a millisecond, and
        an index would need rebuilding on every lap change.
        """
        if self._x is None or not len(self._x):
            return
        if not self.plot.sceneBoundingRect().contains(position):
            return

        point = self.plot.plotItem.vb.mapSceneToView(position)
        index = int(np.argmin(
            np.hypot(self._x - point.x(), self._y - point.y())
        ))
        self.distance_picked.emit(float(self._grid_m[index]))


def _runs_of(classes: np.ndarray) -> list[tuple[int, int, int]]:
    """Split a class array into maximal runs of one value.

    Returns:
        `(start, end_exclusive, value)` per run.
    """
    if not len(classes):
        return []
    boundaries = np.flatnonzero(np.diff(classes)) + 1
    starts = np.concatenate(([0], boundaries))
    ends = np.concatenate((boundaries, [len(classes)]))
    return [
        (int(start), int(end), int(classes[start]))
        for start, end in zip(starts, ends, strict=True)
    ]
