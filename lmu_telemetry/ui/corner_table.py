"""The corner table: every corner of the lap, measured, named and ranked.

This is where a debrief actually happens. The traces show what the lap looked
like; the table says which corner to work on next, and how much it is worth.

Three groups of columns, each appearing only when it has something to say:

- **Always** — where the apex is, minimum and entry speed, how long the braking
  zone was, how far braking continued past turn-in, and how long the car spent
  on neither pedal. Coasting is the one that pays: it is the cost of an
  unresolved decision between brake and throttle, and it is invisible on a
  speed trace.
- **With a comparison** — the time and minimum speed this corner gave away
  against the reference lap.
- **With an ideal lap** — which lap of the session drove this corner best, and
  what matching it would be worth. That column, sorted, *is* the list of things
  to practise.

Corner names are the user's and are stored per track, anchored to a distance
from the line rather than to a corner number - see
`analysis.corners.apply_names_by_distance` for why that distinction is not
cosmetic.
"""

from __future__ import annotations

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from lmu_telemetry.ui import strings, theme
from lmu_telemetry.ui.formatting import format_gap, format_value

#: Column keys, in display order. The groups are hidden as a block.
COLUMN_NAME = "name"
COLUMN_APEX = "apex"
COLUMN_MIN_SPEED = "min_speed"
COLUMN_ENTRY_SPEED = "entry_speed"
COLUMN_BRAKING = "braking"
COLUMN_TRAIL = "trail"
COLUMN_COASTING = "coasting"
COLUMN_SPEED_DELTA = "speed_delta"
COLUMN_DELTA = "delta"
COLUMN_BEST_LAP = "best_lap"
COLUMN_GAIN = "gain"

COLUMNS: tuple[tuple[str, str], ...] = (
    (COLUMN_NAME, strings.CORNERS_COLUMN_NAME),
    (COLUMN_APEX, strings.CORNERS_COLUMN_APEX),
    (COLUMN_MIN_SPEED, strings.CORNERS_COLUMN_MIN_SPEED),
    (COLUMN_ENTRY_SPEED, strings.CORNERS_COLUMN_ENTRY_SPEED),
    (COLUMN_BRAKING, strings.CORNERS_COLUMN_BRAKING),
    (COLUMN_TRAIL, strings.CORNERS_COLUMN_TRAIL),
    (COLUMN_COASTING, strings.CORNERS_COLUMN_COASTING),
    (COLUMN_SPEED_DELTA, strings.CORNERS_COLUMN_SPEED_DELTA),
    (COLUMN_DELTA, strings.CORNERS_COLUMN_DELTA),
    (COLUMN_BEST_LAP, strings.CORNERS_COLUMN_BEST_LAP),
    (COLUMN_GAIN, strings.CORNERS_COLUMN_GAIN),
)

COMPARISON_COLUMNS = frozenset({COLUMN_SPEED_DELTA, COLUMN_DELTA})
IDEAL_COLUMNS = frozenset({COLUMN_BEST_LAP, COLUMN_GAIN})

_INDEX_OF = {key: position for position, (key, _label) in enumerate(COLUMNS)}


class CornerTable(QtWidgets.QWidget):
    """One row per corner, with the user's names editable in place."""

    #: `(corner_index, apex_distance_m, name)` when the user renames a corner.
    corner_renamed = QtCore.Signal(int, float, str)
    #: Apex distance of the selected corner, for moving the shared cursor.
    corner_selected = QtCore.Signal(float)
    #: `(start_m, end_m)` of a corner the user asked to look at closely.
    corner_zoomed = QtCore.Signal(float, float)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: list = []
        self._loading = False
        self._build()

    def _build(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QtWidgets.QHBoxLayout()
        header.setContentsMargins(8, 2, 8, 2)
        heading = QtWidgets.QLabel(strings.CORNERS_TITLE)
        heading.setProperty("role", "heading")
        self.ideal_summary = QtWidgets.QLabel()
        self.ideal_summary.setToolTip(strings.IDEAL_CAVEAT)
        self.ideal_summary.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter
        )
        header.addWidget(heading)
        header.addWidget(self.ideal_summary, stretch=1)
        layout.addLayout(header)

        self.table = QtWidgets.QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels([label for _key, label in COLUMNS])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection
        )
        self.table.setAlternatingRowColors(False)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        # Order around the lap is the meaning of the row order, so sorting the
        # table would destroy the one thing it is telling you.
        self.table.setSortingEnabled(False)

        header_view = self.table.horizontalHeader()
        header_view.setStretchLastSection(False)
        header_view.setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeMode.ResizeToContents
        )
        header_view.setSectionResizeMode(
            _INDEX_OF[COLUMN_NAME], QtWidgets.QHeaderView.ResizeMode.Stretch
        )

        self.table.itemChanged.connect(self._on_item_changed)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.itemDoubleClicked.connect(self._on_double_clicked)
        layout.addWidget(self.table, stretch=1)

        self.placeholder = QtWidgets.QLabel(strings.CORNERS_EMPTY)
        self.placeholder.setProperty("role", "placeholder")
        self.placeholder.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.placeholder, stretch=1)

        self.clear()

    # -- data --------------------------------------------------------------

    def show_corners(
        self,
        rows: list,
        ideal_summary: str = "",
        show_comparison: bool = False,
        show_ideal: bool = False,
    ) -> None:
        """Fill the table.

        Args:
            rows: `pipeline.CornerRow` objects, in lap order.
            ideal_summary: Line shown beside the heading.
            show_comparison: Reveal the comparison columns.
            show_ideal: Reveal the ideal-lap columns.
        """
        self._rows = list(rows)
        if not self._rows:
            self.clear()
            self.ideal_summary.setText(ideal_summary)
            return

        # Suppressed while filling, or every cell written counts as an edit and
        # fires a rename for a name the user never typed.
        self._loading = True
        try:
            self._fill(self._rows)
        finally:
            self._loading = False

        for key in COMPARISON_COLUMNS:
            self.table.setColumnHidden(_INDEX_OF[key], not show_comparison)
        for key in IDEAL_COLUMNS:
            self.table.setColumnHidden(_INDEX_OF[key], not show_ideal)

        self.ideal_summary.setText(ideal_summary)
        self.placeholder.hide()
        self.table.show()

    def clear(self) -> None:
        self._rows = []
        self._loading = True
        try:
            self.table.setRowCount(0)
        finally:
            self._loading = False
        self.ideal_summary.clear()
        self.table.hide()
        self.placeholder.show()

    def _fill(self, rows: list) -> None:
        self.table.setRowCount(len(rows))

        # The corner with the most to gain gets marked: with the ideal lap on,
        # that single cell is the answer to "what do I practise next".
        gains = [row.gain_s for row in rows if row.gain_s is not None]
        worst_gain = max(gains) if gains else None

        for position, row in enumerate(rows):
            corner = row.corner
            self._set(position, COLUMN_NAME, corner.label,
                      editable=True, tooltip=strings.CORNERS_TOOLTIP_NAME)
            self._set(position, COLUMN_APEX, f"{corner.apex_distance_m:.0f}")
            self._set(position, COLUMN_MIN_SPEED,
                      format_value(corner.minimum_speed_ms * 3.6, 1))
            self._set(position, COLUMN_ENTRY_SPEED,
                      format_value(_kmh(corner.entry_speed_ms), 1))
            self._set(position, COLUMN_BRAKING,
                      format_value(corner.braking_length_m, 0))
            self._set(position, COLUMN_TRAIL, f"{corner.trail_braking_m:.0f}")
            self._set(position, COLUMN_COASTING, f"{corner.coasting_time_s:.2f}",
                      colour=_coasting_colour(corner.coasting_time_s))

            self._set(position, COLUMN_SPEED_DELTA,
                      _signed(_kmh(row.speed_delta_ms), 1),
                      colour=_delta_colour(row.speed_delta_ms, higher_is_better=True))
            self._set(position, COLUMN_DELTA, _signed(row.delta_s, 3),
                      colour=_delta_colour(row.delta_s, higher_is_better=False))

            self._set(position, COLUMN_BEST_LAP,
                      "--" if row.best_lap_index is None
                      else str(row.best_lap_index))
            self._set(
                position, COLUMN_GAIN,
                "--" if row.gain_s is None else f"{row.gain_s:.3f}",
                colour=(theme.WARNING
                        if worst_gain is not None and row.gain_s == worst_gain
                        and worst_gain > 0 else None),
                tooltip=strings.CORNERS_TOOLTIP_GAIN,
            )

    def _set(
        self,
        row: int,
        key: str,
        text: str,
        *,
        editable: bool = False,
        colour: str | None = None,
        tooltip: str | None = None,
    ) -> None:
        item = QtWidgets.QTableWidgetItem(text)
        flags = QtCore.Qt.ItemFlag.ItemIsEnabled | QtCore.Qt.ItemFlag.ItemIsSelectable
        if editable:
            flags |= QtCore.Qt.ItemFlag.ItemIsEditable
        else:
            item.setTextAlignment(
                QtCore.Qt.AlignmentFlag.AlignRight
                | QtCore.Qt.AlignmentFlag.AlignVCenter
            )
        item.setFlags(flags)
        if colour is not None:
            item.setForeground(QtGui.QColor(colour))
        if tooltip is not None:
            item.setToolTip(tooltip)
        self.table.setItem(row, _INDEX_OF[key], item)

    # -- interaction -------------------------------------------------------

    def _on_item_changed(self, item: QtWidgets.QTableWidgetItem) -> None:
        if self._loading or item.column() != _INDEX_OF[COLUMN_NAME]:
            return
        if item.row() >= len(self._rows):
            return
        corner = self._rows[item.row()].corner
        name = item.text().strip()
        if name and name != corner.label:
            self.corner_renamed.emit(
                corner.index, corner.apex_distance_m, name
            )

    def _on_selection_changed(self) -> None:
        row = self._selected_row()
        if row is not None:
            self.corner_selected.emit(row.corner.apex_distance_m)

    def _on_double_clicked(self, item: QtWidgets.QTableWidgetItem) -> None:
        # Double-clicking the name column starts an edit; everywhere else it
        # means "show me this corner".
        if item.column() == _INDEX_OF[COLUMN_NAME]:
            return
        if item.row() < len(self._rows):
            corner = self._rows[item.row()].corner
            self.corner_zoomed.emit(
                corner.start_distance_m, corner.end_distance_m
            )

    def _selected_row(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        index = rows[0].row()
        return self._rows[index] if index < len(self._rows) else None

    def select_corner_at(self, distance_m: float) -> None:
        """Highlight the corner containing a distance, without re-emitting.

        Called when the cursor moves elsewhere in the window, so the table
        follows the traces as well as driving them.
        """
        if not self._rows:
            return
        apexes = np.array([row.corner.apex_distance_m for row in self._rows])
        nearest = int(np.argmin(np.abs(apexes - distance_m)))

        blocked = self.table.blockSignals(True)
        try:
            self.table.selectRow(nearest)
        finally:
            self.table.blockSignals(blocked)


def _kmh(speed_ms: float | None) -> float | None:
    return None if speed_ms is None else speed_ms * 3.6


def _signed(value: float | None, decimals: int) -> str:
    if value is None or not np.isfinite(value):
        return "--"
    return f"{value:+.{decimals}f}"


def _delta_colour(value: float | None, *, higher_is_better: bool) -> str | None:
    """Green where the lap on screen is better, red where it is worse."""
    if value is None or not np.isfinite(value) or value == 0.0:
        return None
    better = value > 0 if higher_is_better else value < 0
    return theme.COLOUR_THROTTLE if better else theme.COLOUR_BRAKE


def _coasting_colour(seconds: float) -> str | None:
    """Flag a corner where the car spent real time on neither pedal.

    A tenth is the transition between the pedals and is unavoidable. Beyond
    about a quarter of a second the driver is waiting rather than transferring,
    and that is time given away for nothing.
    """
    return theme.WARNING if seconds >= 0.25 else None
