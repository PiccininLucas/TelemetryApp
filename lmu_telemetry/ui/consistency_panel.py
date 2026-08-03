"""How repeatable the driver is, corner by corner, over a stint.

Lap times hide this. Two drivers with the same average lap time can be very
different: one repeats the same lap, the other alternates a good lap with a bad
one. Only the second has something easy to gain, and only a per-corner
measurement shows where.

The panel is a ranked table beside a lap-by-lap plot, and the pairing is the
whole point. **A drift and a scatter have the same standard deviation and
completely different causes.** A braking point creeping 15 m later over eight
laps is tyre or fuel state changing; the same 15 m jumping about at random is
the driver. The table gives the number, the plot says which of the two it is,
and the "Padrão" column states the answer so it cannot be missed.

Consistency is measured per stint. Across a pit stop, fuel load and tyre age
both step, so the dispersion would be measuring the car's state rather than the
driver's repeatability.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from lmu_telemetry.analysis.consistency import Exclusion
from lmu_telemetry.ui import strings, theme
from lmu_telemetry.ui.formatting import format_lap_time

COLUMN_CORNER = 0
COLUMN_LAPS = 1
COLUMN_BRAKING_STD = 2
COLUMN_SPEED_STD = 3
COLUMN_THROTTLE_STD = 4
COLUMN_TIME_LOST = 5
COLUMN_PATTERN = 6

COLUMN_LABELS = (
    strings.CONSISTENCY_COLUMN_CORNER,
    strings.CONSISTENCY_COLUMN_LAPS,
    strings.CONSISTENCY_COLUMN_BRAKING_STD,
    strings.CONSISTENCY_COLUMN_SPEED_STD,
    strings.CONSISTENCY_COLUMN_THROTTLE_STD,
    strings.CONSISTENCY_COLUMN_TIME_LOST,
    strings.CONSISTENCY_COLUMN_PATTERN,
)


@dataclass(frozen=True, slots=True)
class Metric:
    """One thing that can be plotted lap by lap.

    Attributes:
        label: What the selector calls it.
        attribute: Name of the per-lap array on `CornerConsistency`.
        scale: Multiplier to display units.
    """

    label: str
    attribute: str
    scale: float = 1.0


METRICS: tuple[Metric, ...] = (
    Metric(strings.CONSISTENCY_METRIC_BRAKING, "braking_points_m"),
    Metric(strings.CONSISTENCY_METRIC_SPEED, "minimum_speeds_ms", 3.6),
    Metric(strings.CONSISTENCY_METRIC_THROTTLE, "throttle_points_m"),
)

#: Above this, a corner's dispersion is worth acting on. A braking point that
#: moves five metres between laps is normal; twenty is a decision not yet made
#: the same way twice.
BRAKING_STD_WARNING_M = 15.0
#: Two km/h of apex-speed spread is repeatable driving; five is not.
SPEED_STD_WARNING_KMH = 5.0


class ConsistencyPanel(QtWidgets.QWidget):
    """The ranked table, its stint selector, and the lap-by-lap plot."""

    #: Apex distance of the corner selected in the table.
    corner_selected = QtCore.Signal(float)
    #: Index of the stint the user switched to.
    stint_changed = QtCore.Signal(int)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._corners: list = []
        self._lap_numbers: list[int] = []
        self._build()

    def _build(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        header = QtWidgets.QHBoxLayout()
        header.setContentsMargins(8, 2, 8, 2)
        self.stint_selector = QtWidgets.QComboBox()
        self.stint_selector.currentIndexChanged.connect(self._on_stint_changed)
        self.summary = QtWidgets.QLabel()
        header.addWidget(self.stint_selector)
        header.addWidget(self.summary, stretch=1)

        self.metric_selector = QtWidgets.QComboBox()
        self.metric_selector.addItems([metric.label for metric in METRICS])
        self.metric_selector.currentIndexChanged.connect(lambda _i: self._redraw())
        header.addWidget(self.metric_selector)
        layout.addLayout(header)

        self.excluded = QtWidgets.QLabel()
        self.excluded.setProperty("role", "placeholder")
        self.excluded.setContentsMargins(8, 0, 8, 0)
        self.excluded.setWordWrap(True)
        layout.addWidget(self.excluded)

        self.splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)

        self.table = QtWidgets.QTableWidget(0, len(COLUMN_LABELS))
        self.table.setHorizontalHeaderLabels(list(COLUMN_LABELS))
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection
        )
        self.table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(False)
        # Already sorted worst first by the analysis, and that ranking is the
        # deliverable: a driver cannot work on twelve corners at once.
        self.table.setSortingEnabled(False)
        self.table.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(
            COLUMN_CORNER, QtWidgets.QHeaderView.ResizeMode.Stretch
        )
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.splitter.addWidget(self.table)

        self.plot = pg.PlotWidget()
        self.plot.setBackground(theme.BACKGROUND)
        self.plot.setMenuEnabled(False)
        self.plot.showGrid(x=True, y=True, alpha=theme.GRID_ALPHA)
        self.plot.setLabel("bottom", strings.CONSISTENCY_PLOT_AXIS_LAP)
        for side in ("left", "bottom"):
            self.plot.getAxis(side).enableAutoSIPrefix(False)

        # The +-1 sigma band, drawn first so the points sit on top of it.
        self._band = pg.LinearRegionItem(
            orientation="horizontal", movable=False,
            brush=pg.mkBrush(77, 163, 255, 28), pen=pg.mkPen(None),
        )
        self._band.setZValue(-10)
        self.plot.addItem(self._band)
        self._mean = pg.InfiniteLine(
            angle=0, movable=False,
            pen=pg.mkPen(theme.TEXT_MUTED, width=1,
                         style=QtCore.Qt.PenStyle.DashLine),
        )
        self.plot.addItem(self._mean, ignoreBounds=True)
        # Line and points together: the line is what makes a drift visible at a
        # glance, the points are what make a single outlier attributable.
        self._series = self.plot.plot(
            pen=pg.mkPen(theme.TRACE_REFERENCE, width=1.4),
            symbol="o", symbolSize=7,
            symbolBrush=pg.mkBrush(theme.TRACE_REFERENCE),
            symbolPen=pg.mkPen(theme.BACKGROUND, width=1),
        )
        self.splitter.addWidget(self.plot)
        self.splitter.setSizes([620, 420])
        layout.addWidget(self.splitter, stretch=1)

        self.placeholder = QtWidgets.QLabel(strings.CONSISTENCY_UNAVAILABLE)
        self.placeholder.setProperty("role", "placeholder")
        self.placeholder.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.placeholder.setWordWrap(True)
        layout.addWidget(self.placeholder, stretch=1)

        self.clear()

    # -- data --------------------------------------------------------------

    def show_stints(self, stints: list, current_index: int = 0) -> None:
        """Fill the stint selector and show one of them.

        Args:
            stints: `pipeline.StintAnalysis` objects.
            current_index: Which to show, usually the one the current lap is in.
        """
        blocked = self.stint_selector.blockSignals(True)
        try:
            self.stint_selector.clear()
            for stint in stints:
                self.stint_selector.addItem(
                    strings.CONSISTENCY_STINT.format(
                        number=stint.index + 1, n_laps=len(stint.lap_indices)
                    ),
                    userData=stint.index,
                )
            self.stint_selector.setVisible(len(stints) > 1)
            if 0 <= current_index < len(stints):
                self.stint_selector.setCurrentIndex(current_index)
        finally:
            self.stint_selector.blockSignals(blocked)

        stint = stints[current_index] if 0 <= current_index < len(stints) else None
        self.show_report(None if stint is None else stint.report,
                         [] if stint is None else list(stint.lap_indices))

    def show_report(self, report, lap_numbers: list[int]) -> None:
        """Fill the table and plot for one stint's report."""
        if report is None or not report.is_measurable:
            self.clear()
            return

        self._corners = list(report.corners)
        self._lap_numbers = list(report.lap_indices)

        self.summary.setText(strings.CONSISTENCY_SUMMARY.format(
            n_laps=len(report.lap_indices),
            median=format_lap_time(report.median_lap_time_s),
            std=report.lap_time_std_s,
            gain=report.total_estimated_gain_s,
        ))
        self.excluded.setText(_excluded_text(report.excluded_laps))
        self.excluded.setVisible(bool(report.excluded_laps))

        self._fill(self._corners)
        self.placeholder.hide()
        self.splitter.show()
        self.summary.show()
        self.metric_selector.show()

        # Open on the worst corner: it is the ranking's whole purpose, and
        # leaving the plot empty until the user clicks wastes the answer.
        self.table.selectRow(0)

    def clear(self) -> None:
        self._corners = []
        self._lap_numbers = []
        self.table.setRowCount(0)
        self._series.setData([], [])
        self.summary.clear()
        self.excluded.clear()
        self.excluded.hide()
        self.splitter.hide()
        self.summary.hide()
        self.metric_selector.hide()
        self.stint_selector.hide()
        self.placeholder.show()

    def _fill(self, corners: list) -> None:
        self.table.setRowCount(len(corners))
        for row, corner in enumerate(corners):
            self._set(row, COLUMN_CORNER, corner.corner_label, align_left=True)
            self._set(row, COLUMN_LAPS, str(corner.n_laps))
            self._set(
                row, COLUMN_BRAKING_STD, f"{corner.braking_point_std_m:.1f}",
                colour=_warn(corner.braking_point_std_m, BRAKING_STD_WARNING_M),
            )
            self._set(
                row, COLUMN_SPEED_STD, f"{corner.minimum_speed_std_kmh:.1f}",
                colour=_warn(corner.minimum_speed_std_kmh, SPEED_STD_WARNING_KMH),
            )
            self._set(row, COLUMN_THROTTLE_STD,
                      f"{corner.throttle_point_std_m:.1f}")
            self._set(
                row, COLUMN_TIME_LOST, f"{corner.estimated_time_lost_s:.3f}",
                # The worst corner is first, by construction.
                colour=theme.WARNING if row == 0 and
                corner.estimated_time_lost_s > 0 else None,
                tooltip=strings.CONSISTENCY_TOOLTIP_TIME_LOST,
            )
            self._set(
                row, COLUMN_PATTERN, _pattern_label(corner),
                tooltip=strings.CONSISTENCY_TOOLTIP_PATTERN,
            )

    def _set(
        self,
        row: int,
        column: int,
        text: str,
        *,
        align_left: bool = False,
        colour: str | None = None,
        tooltip: str | None = None,
    ) -> None:
        item = QtWidgets.QTableWidgetItem(text)
        if not align_left:
            item.setTextAlignment(
                QtCore.Qt.AlignmentFlag.AlignRight
                | QtCore.Qt.AlignmentFlag.AlignVCenter
            )
        if colour is not None:
            item.setForeground(QtGui.QColor(colour))
        if tooltip is not None:
            item.setToolTip(tooltip)
        self.table.setItem(row, column, item)

    # -- plot --------------------------------------------------------------

    def _on_selection_changed(self) -> None:
        self._redraw()
        corner = self._selected_corner()
        if corner is not None:
            self.corner_selected.emit(corner.apex_distance_m)

    def _on_stint_changed(self, index: int) -> None:
        if index >= 0:
            self.stint_changed.emit(index)

    def _selected_corner(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        row = rows[0].row()
        return self._corners[row] if row < len(self._corners) else None

    def _redraw(self) -> None:
        corner = self._selected_corner()
        if corner is None:
            self._series.setData([], [])
            self.plot.setTitle(strings.CONSISTENCY_PLOT_EMPTY,
                               color=theme.TEXT_MUTED, size="9pt")
            return

        metric = METRICS[max(self.metric_selector.currentIndex(), 0)]
        values = np.asarray(getattr(corner, metric.attribute),
                            dtype=np.float64) * metric.scale
        laps = np.asarray(self._lap_numbers, dtype=np.float64)

        finite = np.isfinite(values)
        if not np.any(finite):
            self._series.setData([], [])
            self._band.setVisible(False)
            self._mean.setVisible(False)
            return

        # Gaps are dropped rather than zeroed: a lap that never braked here has
        # no braking point, and plotting it at zero would invent an outlier.
        self._series.setData(laps[finite], values[finite])

        mean = float(np.mean(values[finite]))
        std = float(np.std(values[finite], ddof=1)) if finite.sum() > 1 else 0.0
        self._mean.setPos(mean)
        self._mean.setVisible(True)
        self._band.setRegion((mean - std, mean + std))
        self._band.setVisible(std > 0.0)

        self.plot.setLabel("left", metric.label)
        self.plot.setTitle(
            strings.CONSISTENCY_PLOT_TITLE.format(
                corner=corner.corner_label, mean=mean, std=std
            ),
            color=theme.TEXT_MUTED, size="9pt",
        )
        self.plot.enableAutoRange()


def _pattern_label(corner) -> str:
    """Whether the braking point drifts or scatters.

    A drift is a different problem from scatter and usually not a driving
    problem at all, so saying which is more useful than the number alone.
    """
    if corner.braking_point_std_m <= 0.0:
        return strings.CONSISTENCY_PATTERN_NONE
    return (strings.CONSISTENCY_PATTERN_DRIFT if corner.has_trend
            else strings.CONSISTENCY_PATTERN_SCATTER)


def _warn(value: float, threshold: float) -> str | None:
    return theme.WARNING if value >= threshold else None


def _excluded_text(excluded: dict) -> str:
    if not excluded:
        return ""
    parts = []
    for lap_index in sorted(excluded):
        entry = excluded[lap_index]
        if entry.reason is Exclusion.TOO_SLOW:
            parts.append(strings.CONSISTENCY_EXCLUDED_TOO_SLOW.format(
                number=lap_index, excess=entry.excess_s
            ))
        else:
            parts.append(strings.CONSISTENCY_EXCLUDED_TOO_FEW.format(
                number=lap_index
            ))
    return strings.CONSISTENCY_EXCLUDED.format(laps=", ".join(parts))
