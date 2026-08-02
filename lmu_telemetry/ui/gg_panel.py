"""The g-g diagram: how much of the tyres' grip the lap actually used.

Lateral acceleration on one axis, longitudinal on the other. The tyre can
produce roughly a fixed total force in any direction, so the reachable points
fill a rounded region and the driver's job is to live on its edge. The shape of
the cloud is the diagnosis:

- a **hollow between the bottom and the sides** means the brake is released
  before the car is turned, instead of the two being blended;
- **a small cloud** means the limit was never approached;
- **outliers past the edge** are not extra grip, they are the moment it ran out.

Drawn as a scatter with the convex hull outlined over it. The hull is what the
numbers under the plot are computed from, so outlining it makes those numbers
auditable by eye rather than something the panel asserts.

Equal aspect ratio, and 1 g gridlines: a diagram where one g of braking is
taller than one g of cornering makes a circular envelope look elliptical, which
is the single thing the reader is trying to judge.
"""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets

from lmu_telemetry.ui import strings, theme


class FrictionPanel(QtWidgets.QWidget):
    """Scatter of accelerations with the friction envelope drawn over it."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._lateral: np.ndarray | None = None
        self._longitudinal: np.ndarray | None = None
        self._grid_m: np.ndarray | None = None
        self._build()

    def _build(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        heading = QtWidgets.QLabel(strings.GG_TITLE)
        heading.setProperty("role", "heading")
        layout.addWidget(heading)

        self.plot = pg.PlotWidget()
        self.plot.setBackground(theme.BACKGROUND)
        self.plot.setMenuEnabled(False)
        self.plot.setLabel("left", strings.GG_AXIS_LONGITUDINAL)
        self.plot.setLabel("bottom", strings.GG_AXIS_LATERAL)
        self.plot.showGrid(x=True, y=True, alpha=theme.GRID_ALPHA)
        # One g of braking must be as tall as one g of cornering, or a circular
        # envelope reads as an elliptical one.
        self.plot.setAspectLocked(True)
        for side in ("left", "bottom"):
            self.plot.getAxis(side).enableAutoSIPrefix(False)
            self.plot.getAxis(side).setTickSpacing(major=1.0, minor=0.5)
        layout.addWidget(self.plot, stretch=1)

        for angle in (0, 90):
            self.plot.addItem(
                pg.InfiniteLine(pos=0.0, angle=angle, movable=False,
                                pen=pg.mkPen(theme.BORDER, width=1)),
                ignoreBounds=True,
            )

        # Small, translucent dots: the cloud's *density* is as informative as
        # its outline, and opaque markers at 13 600 points would be a solid
        # blob with no interior structure at all.
        self._points = pg.ScatterPlotItem(
            size=2.5, pen=None,
            brush=pg.mkBrush(77, 163, 255, 60), pxMode=True,
        )
        self.plot.addItem(self._points)

        self._hull = self.plot.plot(
            pen=pg.mkPen(theme.TRACE_COMPARISON, width=1.6)
        )

        self._cursor = pg.ScatterPlotItem(
            size=10, pen=pg.mkPen(theme.TEXT, width=2),
            brush=pg.mkBrush(theme.BACKGROUND),
        )
        self._cursor.setVisible(False)
        self.plot.addItem(self._cursor)

        self.summary = QtWidgets.QLabel()
        self.summary.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.summary)

        self.detail = QtWidgets.QLabel()
        self.detail.setProperty("role", "placeholder")
        self.detail.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.detail.setToolTip(strings.GG_FILL_TOOLTIP)
        layout.addWidget(self.detail)

        self.placeholder = QtWidgets.QLabel(strings.GG_NO_DATA)
        self.placeholder.setProperty("role", "placeholder")
        self.placeholder.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.placeholder.setWordWrap(True)
        layout.addWidget(self.placeholder, stretch=1)

        self.clear()

    # -- data --------------------------------------------------------------

    def show_envelope(
        self,
        envelope,
        lateral_on_grid: np.ndarray,
        longitudinal_on_grid: np.ndarray,
        grid_m: np.ndarray,
        transition_quality: float,
    ) -> None:
        """Draw one lap's envelope.

        Args:
            envelope: An `analysis.friction.FrictionEnvelope`.
            lateral_on_grid: Lateral acceleration on the lap's distance grid.
                Kept alongside the envelope's own filtered arrays so the cursor
                can find the point at a given distance - the envelope drops
                low-speed samples and no longer lines up with the grid.
            longitudinal_on_grid: Likewise.
            grid_m: The distance grid.
            transition_quality: Fraction of the working time with both axes
                loaded.
        """
        self._lateral = np.asarray(lateral_on_grid, dtype=np.float64)
        self._longitudinal = np.asarray(longitudinal_on_grid, dtype=np.float64)
        self._grid_m = np.asarray(grid_m, dtype=np.float64)

        self.placeholder.hide()
        self.plot.show()
        self.summary.show()
        self.detail.show()

        self._points.setData(envelope.lateral_g, envelope.longitudinal_g)
        self._hull.setData(envelope.hull_lateral_g, envelope.hull_longitudinal_g)

        self.summary.setText(strings.GG_SUMMARY.format(
            lateral=envelope.max_lateral_g,
            braking=envelope.max_braking_g,
            acceleration=envelope.max_acceleration_g,
        ))
        self.detail.setText(strings.GG_FILL.format(
            fill=envelope.fill_fraction, transitions=transition_quality
        ))
        self.plot.enableAutoRange()

    def clear(self) -> None:
        self._lateral = self._longitudinal = self._grid_m = None
        self._points.setData([], [])
        self._hull.setData([], [])
        self._cursor.setVisible(False)
        self.plot.hide()
        self.summary.hide()
        self.detail.hide()
        self.placeholder.show()

    # -- cursor ------------------------------------------------------------

    def set_cursor_distance(self, distance_m: float) -> None:
        """Mark the acceleration the car was generating at one point of the lap.

        This is what ties the diagram to the rest of the window: a point on the
        edge of the envelope is a corner where the limit was found, and the
        marker says which corner that was.
        """
        if self._grid_m is None or not len(self._grid_m):
            return
        index = int(np.clip(
            np.searchsorted(self._grid_m, distance_m), 0, len(self._grid_m) - 1
        ))
        lateral = float(self._lateral[index])
        longitudinal = float(self._longitudinal[index])
        if not (np.isfinite(lateral) and np.isfinite(longitudinal)):
            self._cursor.setVisible(False)
            return

        self._cursor.setData([lateral], [longitudinal])
        self._cursor.setVisible(True)
        self._cursor.setToolTip(strings.GG_CURSOR.format(
            lateral=lateral, longitudinal=longitudinal,
            total=float(np.hypot(lateral, longitudinal)),
        ))
