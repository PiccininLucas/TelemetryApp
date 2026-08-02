"""The speed trace.

`pyqtgraph` rather than `matplotlib`: a Le Mans lap on a 1 m grid is 13 600
points and a whole session is far more, and panning and zooming has to stay
fluid. `matplotlib` is kept for export, where print quality matters more than
interactivity.

Phase 5 draws one channel. The panel is built so phase 6 can stack more plots on
a shared X axis without restructuring it: the axis mode and the cursor already
live here rather than in the plot.
"""

from __future__ import annotations

from enum import Enum

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets

from lmu_telemetry.ui import strings, theme


class AxisMode(str, Enum):
    """What the X axis measures."""

    #: Distance around the lap. The only mode in which two laps can be
    #: meaningfully compared, and therefore the default.
    DISTANCE = "distance"
    #: Time since the lap started. Useful for reading a single lap's rhythm.
    TIME = "time"


class SpeedChart(QtWidgets.QWidget):
    """Speed against distance or time, for one lap."""

    #: Emitted as the cursor moves, carrying the X position under the mouse.
    cursor_moved = QtCore.Signal(float)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._axis_mode = AxisMode.DISTANCE
        self._x_values: np.ndarray | None = None
        self._speed_kmh: np.ndarray | None = None
        self._build()

    def _build(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.plot = pg.PlotWidget()
        self.plot.setBackground(theme.BACKGROUND)
        self.plot.showGrid(x=True, y=True, alpha=theme.GRID_ALPHA)
        self.plot.setLabel("left", strings.CHART_AXIS_SPEED)
        self.plot.setLabel("bottom", strings.CHART_AXIS_DISTANCE)
        self.plot.setMouseEnabled(x=True, y=False)
        # Y is fixed to the data and X is what the user explores; letting the Y
        # axis pan too makes a trace easy to lose off-screen.
        self.plot.setMenuEnabled(False)

        # Downsample on the fly and only render what is visible. Without this a
        # full session's trace redraws every point on every pan.
        self.plot.setDownsampling(auto=True, mode="peak")
        self.plot.setClipToView(True)

        self._curve = self.plot.plot(
            pen=pg.mkPen(theme.TRACE_REFERENCE, width=1.5)
        )

        self._cursor = pg.InfiniteLine(
            angle=90, movable=False,
            pen=pg.mkPen(theme.TEXT_MUTED, width=1,
                         style=QtCore.Qt.PenStyle.DashLine),
        )
        self._cursor.setVisible(False)
        self.plot.addItem(self._cursor, ignoreBounds=True)

        self._readout = pg.TextItem(color=theme.TEXT, anchor=(0, 1))
        self._readout.setVisible(False)
        self.plot.addItem(self._readout, ignoreBounds=True)

        self.plot.scene().sigMouseMoved.connect(self._on_mouse_moved)
        layout.addWidget(self.plot, stretch=1)

        self.placeholder = QtWidgets.QLabel(strings.CHART_NO_DATA)
        self.placeholder.setProperty("role", "placeholder")
        self.placeholder.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.placeholder)
        self.placeholder.hide()

    # -- data --------------------------------------------------------------

    def show_lap(
        self,
        distance_m: np.ndarray,
        elapsed_s: np.ndarray,
        speed_ms: np.ndarray,
        title: str = "",
    ) -> None:
        """Draw one lap.

        Args:
            distance_m: Distance grid.
            elapsed_s: Elapsed time on the same grid, for the time axis.
            speed_ms: Speed in m/s. Converted to km/h for display - the
                application works in SI internally and shows km/h, which is what
                a driver reads.
            title: Shown above the plot.
        """
        self._distance_m = np.asarray(distance_m, dtype=np.float64)
        self._elapsed_s = np.asarray(elapsed_s, dtype=np.float64)
        self._speed_kmh = np.asarray(speed_ms, dtype=np.float64) * 3.6

        self.placeholder.hide()
        self.plot.show()
        self.plot.setTitle(title, color=theme.TEXT_MUTED, size="10pt")
        self._redraw()

    def clear(self) -> None:
        self._distance_m = None
        self._elapsed_s = None
        self._speed_kmh = None
        self._curve.setData([], [])
        self._cursor.setVisible(False)
        self._readout.setVisible(False)
        self.plot.hide()
        self.placeholder.show()

    def set_axis_mode(self, mode: AxisMode) -> None:
        """Switch between the distance and time axes, keeping the data."""
        if mode is self._axis_mode:
            return
        self._axis_mode = mode
        self.plot.setLabel(
            "bottom",
            strings.CHART_AXIS_DISTANCE if mode is AxisMode.DISTANCE
            else strings.CHART_AXIS_TIME,
        )
        self._redraw()

    @property
    def axis_mode(self) -> AxisMode:
        return self._axis_mode

    def _redraw(self) -> None:
        if self._speed_kmh is None:
            return
        self._x_values = (
            self._distance_m if self._axis_mode is AxisMode.DISTANCE
            else self._elapsed_s
        )
        self._curve.setData(self._x_values, self._speed_kmh)
        self.plot.enableAutoRange()

    # -- cursor ------------------------------------------------------------

    def _on_mouse_moved(self, position) -> None:
        if self._x_values is None or self._speed_kmh is None:
            return
        if not self.plot.sceneBoundingRect().contains(position):
            self._cursor.setVisible(False)
            self._readout.setVisible(False)
            return

        point = self.plot.plotItem.vb.mapSceneToView(position)
        x = float(point.x())

        index = int(np.clip(np.searchsorted(self._x_values, x), 0,
                            len(self._x_values) - 1))
        snapped = float(self._x_values[index])
        speed = float(self._speed_kmh[index])

        self._cursor.setPos(snapped)
        self._cursor.setVisible(True)
        self._readout.setText(
            strings.CHART_CURSOR_READOUT.format(
                distance=self._distance_m[index], speed=speed
            )
        )
        self._readout.setPos(snapped, speed)
        self._readout.setVisible(True)

        self.cursor_moved.emit(snapped)
