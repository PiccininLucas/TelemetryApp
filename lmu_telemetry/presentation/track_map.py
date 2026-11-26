"""The circuit drawn from the lap's own GPS trace, coloured by what happened.

The map answers the question a trace cannot: *where*. A delta row says a lap
lost 0.19 s somewhere around 990 m; the map says it lost it at the first
chicane. Reading a distance off an axis and translating it into a corner is
work the driver should not have to do.

**Two colourings, because there are two questions.**

- *Pedals* — braking red and thick, coasting grey and dashed, throttle green
  and thin. Coasting is the one
  that matters: as a number it is 2% of a lap and easy to dismiss, and as a
  stretch of tarmac between the brake release and the throttle it is obviously
  a corner entered too slowly or a brake released too early.
- *Gain and loss* — where the compared lap is gaining or losing against its
  reference. Coloured by the **slope** of the delta, never its value: colouring
  by value paints the whole second half of the lap red because of one mistake
  at turn one. Losing is a solid line, thicker the faster time goes; gaining
  is dashed.

**Colour is never the only cue.** Red and green are the pair the commonest
colour blindness confuses, and both colourings rest on them. So every class
also has its own width and dash, and the key under the map draws each line
exactly as it is drawn on the circuit.

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

from lmu_telemetry.presentation import plotting, theme
from lmu_telemetry.presentation.chart_widgets import LineKey, LineStyle
from lmu_telemetry.shared import strings


class MapColour(str, Enum):
    """What the path's colour encodes."""

    #: Braking, coasting, on throttle. Always available.
    PEDALS = "pedals"
    #: Where the lap gains or loses against its reference. Needs a comparison.
    DELTA = "delta"


#: How each pedal class is drawn, keyed by the value `trackmap.pedal_state`
#: returns. Braking stands out by width as well as colour; coasting - the
#: class worth finding - is the only dashed one.
PEDAL_STYLES: dict[int, LineStyle] = {
    -1: LineStyle(theme.COLOUR_BRAKE, 3.6),
    0: LineStyle(theme.COLOUR_COAST, 2.4, dashed=True),
    +1: LineStyle(theme.COLOUR_THROTTLE, 2.4),
}

#: How each loss class from `analysis.delta.loss_classes` is drawn: losing
#: solid and thicker the faster time goes, gaining dashed. Neutral is dim but
#: as wide as a plain path - it is most of the lap, and it is what draws the
#: circuit's shape; the classes that matter are wider than it, not it thinner.
LOSS_STYLES: dict[int, LineStyle] = {
    -2: LineStyle(theme.LOSS_SCALE[-2], 4.2),
    -1: LineStyle(theme.LOSS_SCALE[-1], 3.2),
    0: LineStyle(theme.LOSS_SCALE[0], 2.4),
    +1: LineStyle(theme.LOSS_SCALE[+1], 2.4, dashed=True),
    +2: LineStyle(theme.LOSS_SCALE[+2], 3.2, dashed=True),
}

#: The colours alone, for anything that only needs those.
PEDAL_COLOURS: dict[int, str] = {k: v.colour for k, v in PEDAL_STYLES.items()}
LOSS_COLOURS: dict[int, str] = {k: v.colour for k, v in LOSS_STYLES.items()}

#: Unclassified path: no colouring available for this mode.
PLAIN_STYLE = LineStyle(theme.TEXT_MUTED, 2.4)

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
        self._corner_marks: list[tuple[float, str]] = []
        self._corner_items: list[pg.TextItem] = []
        self._build()

    def _build(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)


        self.plot = plotting.make_plot(axes=False)
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
            size=9, pen=pg.mkPen(theme.PLOT_BACKGROUND, width=1),
            brush=pg.mkBrush(theme.TEXT),
        )
        self.plot.addItem(self._start)

        # Corner apexes: a small dot and the corner's number, so a point on the
        # map can be named without reading a distance off an axis.
        self._apexes = pg.ScatterPlotItem(
            size=5, pen=pg.mkPen(None), brush=pg.mkBrush(theme.TEXT_MUTED),
        )
        self.plot.addItem(self._apexes)

        self._cursor = pg.ScatterPlotItem(
            size=11, pen=pg.mkPen(theme.TEXT, width=2),
            brush=pg.mkBrush(theme.PLOT_BACKGROUND),
        )
        self._cursor.setVisible(False)
        self.plot.addItem(self._cursor)

        # The key: each class's line drawn as it is on the circuit.
        self.legend = QtWidgets.QWidget()
        legend_layout = QtWidgets.QHBoxLayout(self.legend)
        legend_layout.setContentsMargins(8, 4, 8, 0)
        legend_layout.setSpacing(14)
        legend_layout.addStretch(1)
        self.legend_keys = [LineKey(PLAIN_STYLE) for _ in range(3)]
        for key in self.legend_keys:
            legend_layout.addWidget(key)
        legend_layout.addStretch(1)
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

    def set_corner_labels(self, distances_m, labels) -> None:
        """Name the corners on the map, at their apexes.

        Labels should be short - "T6", not "T6 Hairpin" - because sixteen full
        names on a map the size of a dock are unreadable; the full name is in
        the corner card and the table.
        """
        self._corner_marks = list(zip(
            (float(d) for d in distances_m), labels, strict=True
        ))
        self._draw_corner_labels()

    @property
    def corner_labels(self) -> list[str]:
        """The labels currently drawn, for tests."""
        return [item.textItem.toPlainText() for item in self._corner_items]

    def _draw_corner_labels(self) -> None:
        for item in self._corner_items:
            self.plot.removeItem(item)
        self._corner_items = []
        self._apexes.setData([], [])
        if self._x is None or self._grid_m is None or not len(self._x):
            return
        if not self._corner_marks:
            return

        distances = np.array([d for d, _label in self._corner_marks])
        xs = np.interp(distances, self._grid_m, self._x)
        ys = np.interp(distances, self._grid_m, self._y)
        self._apexes.setData(xs, ys)
        # Smaller than the interface text: on a tight complex - Fuji's Dunlop,
        # Le Mans's Ford chicanes - four labels sit within a few pixels.
        font = theme.font(theme.TYPE.micro)
        for x, y, (_distance, label) in zip(xs, ys, self._corner_marks, strict=True):
            text = pg.TextItem(label, color=theme.TEXT_MUTED, anchor=(0.5, 1.3))
            text.setFont(font)
            text.setPos(float(x), float(y))
            self.plot.addItem(text, ignoreBounds=True)
            self._corner_items.append(text)

    def set_integrated_visible(self, visible: bool) -> None:
        self._integrated.setVisible(visible)

    def clear(self) -> None:
        self._x = self._y = self._grid_m = None
        self._classes = {}
        self._clear_runs()
        self._corner_marks = []
        self._draw_corner_labels()
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
        styles = PEDAL_STYLES if self._mode is MapColour.PEDALS else LOSS_STYLES

        if classes is None or len(classes) != len(self._x):
            self._runs.append(self.plot.plot(self._x, self._y, pen=PLAIN_STYLE.pen()))
        else:
            for start, end, value in _runs_of(classes):
                # Extend each run by one point so consecutive runs share an
                # endpoint; without it the path shows a gap at every colour
                # change, which on a pedal map is every braking point.
                stop = min(end + 1, len(self._x))
                style = styles.get(int(value), PLAIN_STYLE)
                self._runs.append(self.plot.plot(
                    self._x[start:stop], self._y[start:stop], pen=style.pen(),
                ))
        # The path stays put while the cursor dot moves over it.
        plotting.freeze(*self._runs)

        self._start.setData([self._x[0]], [self._y[0]])
        self._draw_corner_labels()
        self._update_legend()
        self.plot.enableAutoRange()

    def _update_legend(self) -> None:
        entries = (PEDAL_LEGEND if self._mode is MapColour.PEDALS
                   else LOSS_LEGEND)
        styles = PEDAL_STYLES if self._mode is MapColour.PEDALS else LOSS_STYLES
        for key, (value, label) in zip(self.legend_keys, entries, strict=True):
            key.set(styles[value], label)

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
