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

The stint and the plotted measure are chosen with chips, not combo boxes: there
are only ever a few of each, and a chip row shows every option at once. The
stint chips appear only when there is more than one stint, and the measure
chosen survives a change of stint - comparing one measure across stints is the
reason to switch.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from lmu_telemetry.domain.analysis.consistency import Exclusion
from lmu_telemetry.presentation import plotting, theme
from lmu_telemetry.presentation.chip_group import ChipGroup
from lmu_telemetry.shared import strings
from lmu_telemetry.shared.config import load_config
from lmu_telemetry.shared.formatting import (
    format_distance, format_gap, format_lap_time, format_seconds, format_speed,
    format_value,
)

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
        label: Its full name with the unit: the plot's axis, and what a screen
            reader says for its chip.
        chip: The chip's text, worded like the table's column, with the unit.
        unit: The unit alone, for the plot's title.
        attribute: Name of the per-lap array on `CornerConsistency`.
        scale: Multiplier to display units.
    """

    label: str
    chip: str
    unit: str
    attribute: str
    scale: float = 1.0


METRICS: tuple[Metric, ...] = (
    Metric(strings.CONSISTENCY_METRIC_BRAKING, strings.CONSISTENCY_CHIP_BRAKING,
           strings.CONSISTENCY_UNIT_M, "braking_points_m"),
    Metric(strings.CONSISTENCY_METRIC_SPEED, strings.CONSISTENCY_CHIP_SPEED,
           strings.CONSISTENCY_UNIT_KMH, "minimum_speeds_ms", 3.6),
    Metric(strings.CONSISTENCY_METRIC_THROTTLE, strings.CONSISTENCY_CHIP_THROTTLE,
           strings.CONSISTENCY_UNIT_M, "throttle_points_m"),
)

# The spread above which a corner's dispersion is marked as worth acting on comes
# from `ui.consistency.*_warning_*` in the configuration, see its comment.


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

        # One row of controls, as above the traces: the stint on the left, the
        # measure the plot shows on the right, over the plot. The summary gets
        # a line of its own below instead of the width the chips leave over.
        # Chips and summary wrap rather than widen the panel: this row used to
        # set the window's minimum width.
        controls = QtWidgets.QHBoxLayout()
        controls.setContentsMargins(8, 4, 8, 0)
        controls.setSpacing(12)
        self.stint_selector = ChipGroup(strings.CONSISTENCY_STINT_NAME)
        self.stint_selector.chosen.connect(self._on_stint_changed)
        controls.addWidget(self.stint_selector, alignment=QtCore.Qt.AlignmentFlag.AlignTop)
        controls.addStretch(1)
        self.metric_selector = ChipGroup(strings.CONSISTENCY_METRIC_NAME)
        self.metric_selector.set_options(
            [metric.chip for metric in METRICS],
            [metric.label for metric in METRICS],
        )
        self.metric_selector.chosen.connect(lambda _index: self._redraw())
        controls.addWidget(self.metric_selector, alignment=QtCore.Qt.AlignmentFlag.AlignTop)
        layout.addLayout(controls)

        self.summary = QtWidgets.QLabel()
        self.summary.setWordWrap(True)
        self.summary.setContentsMargins(8, 0, 8, 0)
        layout.addWidget(self.summary)

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
        # Every column as wide as its contents and the spare width to the last,
        # as in the corner table: a stretched name column was the one squeezed
        # to "T1..." when the panel was narrow.
        self.table.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.splitter.addWidget(self.table)

        self.plot = plotting.make_plot(bottom=strings.CONSISTENCY_PLOT_AXIS_LAP)

        # The +-1 sigma band, drawn first so the points sit on top of it.
        self._band = pg.LinearRegionItem(
            orientation="horizontal", movable=False,
            brush=pg.mkBrush(*theme.TRACE_REFERENCE_RGB, 28), pen=pg.mkPen(None),
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
            symbolPen=pg.mkPen(theme.PLOT_BACKGROUND, width=1),
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
        self.stint_selector.set_options(
            [strings.CONSISTENCY_STINT.format(number=stint.index + 1,
                                              n_laps=len(stint.lap_indices))
             for stint in stints],
            [_stint_description(stint) for stint in stints],
            current=current_index,
        )
        # A session driven without stopping is one stint, and a selector with
        # one entry is furniture.
        self.stint_selector.setVisible(len(stints) > 1)

        stint = stints[current_index] if 0 <= current_index < len(stints) else None
        self.show_report(None if stint is None else stint.report,
                         [] if stint is None else list(stint.lap_indices))

    def show_report(self, report, lap_numbers: list[int]) -> None:
        """Fill the table and plot for one stint's report.

        A stint too short to measure shows the placeholder but keeps the stint
        chips: they are the way back to the stints that can be measured.
        """
        if report is None or not report.is_measurable:
            self._clear_report()
            return

        self._corners = list(report.corners)
        self._lap_numbers = list(report.lap_indices)

        self.summary.setText(strings.CONSISTENCY_SUMMARY.format(
            n_laps=len(report.lap_indices),
            median=format_lap_time(report.median_lap_time_s),
            std=format_seconds(report.lap_time_std_s),
            gain=format_seconds(report.total_estimated_gain_s, 2),
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
        """Nothing to show: no report and no stints."""
        self._clear_report()
        self.stint_selector.hide()

    def _clear_report(self) -> None:
        self._corners = []
        self._lap_numbers = []
        self.table.setRowCount(0)
        self._series.setData([], [])
        self.summary.clear()
        self.excluded.clear()
        self.excluded.hide()
        self.splitter.hide()
        self.summary.hide()
        # Hidden, not reset: the measure chosen is still chosen when a lap with
        # enough laps around it comes back.
        self.metric_selector.hide()
        self.placeholder.show()

    def _fill(self, corners: list) -> None:
        limits = load_config().section("ui").get("consistency", {})
        braking_limit = float(limits["braking_std_warning_m"])
        speed_limit = float(limits["speed_std_warning_kmh"])

        self.table.setRowCount(len(corners))
        for row, corner in enumerate(corners):
            self._set(row, COLUMN_CORNER, corner.corner_label, align_left=True)
            self._set(row, COLUMN_LAPS, str(corner.n_laps))
            self._set(
                row, COLUMN_BRAKING_STD, format_distance(corner.braking_point_std_m, 1),
                tone=_warn(corner.braking_point_std_m, braking_limit),
            )
            self._set(
                row, COLUMN_SPEED_STD, format_speed(corner.minimum_speed_std_ms),
                tone=_warn(corner.minimum_speed_std_kmh, speed_limit),
            )
            self._set(row, COLUMN_THROTTLE_STD,
                      format_distance(corner.throttle_point_std_m, 1))
            self._set(
                row, COLUMN_TIME_LOST, format_seconds(corner.estimated_time_lost_s),
                # The worst corner is first, by construction.
                tone=theme.Tone.WARNING if row == 0 and
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
        tone: theme.Tone | None = None,
        tooltip: str | None = None,
    ) -> None:
        item = QtWidgets.QTableWidgetItem(text)
        if not align_left:
            item.setTextAlignment(
                QtCore.Qt.AlignmentFlag.AlignRight
                | QtCore.Qt.AlignmentFlag.AlignVCenter
            )
        if tone is not None:
            item.setForeground(QtGui.QColor(theme.tone_colour(tone)))
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

    @property
    def metric(self) -> Metric:
        """The measure the plot shows."""
        return METRICS[max(self.metric_selector.current_index(), 0)]

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
                               color=theme.TEXT_MUTED, size=theme.PLOT_TEXT_SIZE)
            return

        metric = self.metric
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

        plotting.set_label(self.plot, "left", metric.label)
        self.plot.setTitle(
            strings.CONSISTENCY_PLOT_TITLE.format(
                corner=corner.corner_label, unit=metric.unit,
                mean=format_value(mean, 1), std=format_value(std, 1),
            ),
            color=theme.TEXT_MUTED, size=theme.PLOT_TEXT_SIZE,
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


def _warn(value: float, threshold: float) -> theme.Tone | None:
    return theme.Tone.WARNING if value >= threshold else None


def _stint_description(stint) -> str:
    laps = stint.lap_indices
    if not laps:
        return strings.CONSISTENCY_STINT_NAME
    return strings.CONSISTENCY_STINT_TOOLTIP.format(first=laps[0], last=laps[-1])


def _excluded_text(excluded: dict) -> str:
    if not excluded:
        return ""
    parts = []
    for lap_index in sorted(excluded):
        entry = excluded[lap_index]
        if entry.reason is Exclusion.TOO_SLOW:
            parts.append(strings.CONSISTENCY_EXCLUDED_TOO_SLOW.format(
                number=lap_index, excess=format_gap(entry.excess_s)
            ))
        else:
            parts.append(strings.CONSISTENCY_EXCLUDED_TOO_FEW.format(
                number=lap_index
            ))
    return strings.CONSISTENCY_EXCLUDED.format(laps=", ".join(parts))
