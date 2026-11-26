"""The corner table: every corner of the lap, measured, named and ranked.

This is where a debrief actually happens. The traces show what the lap looked
like; the table says which corner to work on next, and how much it is worth.

Three groups of columns, each appearing only when it has something to say, and
each under a band in the header that names the question it answers:

- **Nesta volta** (always) — where the apex is, minimum and entry speed, how
  long the braking zone was, how far braking continued past turn-in, and how
  long the car spent on neither pedal. Coasting is the one that pays: it is the cost of an
  unresolved decision between brake and throttle, and it is invisible on a
  speed trace.
- **Contra a referência** — the time and minimum speed this corner gave away
  against the reference lap.
- **Contra a volta ideal** — which lap of the session drove this corner best,
  and what matching it would be worth. That column, ranked, *is* the list of
  things to practise.

The rows stay in lap order, because a ranking would destroy the reading. The
one corner to work on next is marked instead: a bar at its left edge, every
cell emphasised and a mark before its name. `pipeline.costliest_corner` picks
it, the same rule the corner card uses.

Corner names are the user's and are stored per track, anchored to a distance
from the line rather than to a corner number - see
`analysis.corners.apply_names_by_distance` for why that distinction is not
cosmetic.
"""

from __future__ import annotations

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from lmu_telemetry.application.pipeline import (
    CornerRow, CostBasis, CostliestCorner, costliest_corner,
)
from lmu_telemetry.presentation import theme
from lmu_telemetry.presentation.grouped_header import ColumnGroup, GroupedHeader
from lmu_telemetry.shared import strings
from lmu_telemetry.shared.formatting import (
    MISSING, format_distance, format_gap, format_seconds, format_speed,
)

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

LAP_COLUMNS = frozenset({COLUMN_APEX, COLUMN_MIN_SPEED, COLUMN_ENTRY_SPEED,
                         COLUMN_BRAKING, COLUMN_TRAIL, COLUMN_COASTING})
COMPARISON_COLUMNS = frozenset({COLUMN_SPEED_DELTA, COLUMN_DELTA})
IDEAL_COLUMNS = frozenset({COLUMN_BEST_LAP, COLUMN_GAIN})

_INDEX_OF = {key: position for position, (key, _label) in enumerate(COLUMNS)}

#: The header's bands. The name column has none: it says which corner, not
#: anything measured about it.
GROUPS: tuple[ColumnGroup, ...] = tuple(
    ColumnGroup(label, tuple(sorted(_INDEX_OF[key] for key in keys)))
    for label, keys in (
        (strings.CORNERS_GROUP_LAP, LAP_COLUMNS),
        (strings.CORNERS_GROUP_REFERENCE, COMPARISON_COLUMNS),
        (strings.CORNERS_GROUP_IDEAL, IDEAL_COLUMNS),
    )
)

#: Item data marking the costliest row's name cell for `_MarkDelegate`.
_MARK_ROLE = QtCore.Qt.ItemDataRole.UserRole + 1


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
        self._rows: list[CornerRow] = []
        self._costliest: CostliestCorner | None = None
        self._loading = False
        self._build()

    def _build(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # No heading of its own: the dock's title already says "Curvas", and a
        # second one inside it only costs a row of the table.
        header = QtWidgets.QHBoxLayout()
        header.setContentsMargins(0, 0, 8, 0)
        self.ideal_summary = QtWidgets.QLabel()
        self.ideal_summary.setProperty("role", "heading")
        self.ideal_summary.setToolTip(strings.IDEAL_CAVEAT)
        # Wraps rather than set the dock's minimum width, which it alone did.
        self.ideal_summary.setWordWrap(True)
        header.addWidget(self.ideal_summary, stretch=1)
        layout.addLayout(header)

        self.table = QtWidgets.QTableWidget(0, len(COLUMNS))
        # The grouped header replaces the default one, keeping what the table
        # gave that one: clickable sections that highlight with the selection.
        self.header = GroupedHeader(self.table)
        self.header.setSectionsClickable(True)
        self.header.setHighlightSections(True)
        self.table.setHorizontalHeader(self.header)
        self.table.setHorizontalHeaderLabels([label for _key, label in COLUMNS])
        for group in GROUPS:
            for column in group.columns:
                # The group's name follows its columns into the tooltip, so it
                # is read even where the band elides it.
                self.table.horizontalHeaderItem(column).setToolTip(
                    f"{group.label} · {COLUMNS[column][1]}"
                )
        self.header.set_groups(GROUPS)
        self.table.setItemDelegateForColumn(
            _INDEX_OF[COLUMN_NAME], _MarkDelegate(self.table)
        )
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

        # Every column as wide as its contents, the spare width to the last.
        # Stretching the name column instead gave it whatever the window had
        # left and pushed the measurements off the side of a bottom-row dock,
        # which is exactly where the figures are needed.
        header_view = self.table.horizontalHeader()
        header_view.setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeMode.ResizeToContents
        )
        header_view.setStretchLastSection(True)

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
        rows: list[CornerRow],
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

    @property
    def costliest(self) -> CostliestCorner | None:
        """The row marked as the corner to work on."""
        return self._costliest

    def clear(self) -> None:
        self._rows = []
        self._costliest = None
        self._loading = True
        try:
            self.table.setRowCount(0)
        finally:
            self._loading = False
        self.ideal_summary.clear()
        self.table.hide()
        self.placeholder.show()

    def _fill(self, rows: list[CornerRow]) -> None:
        self.table.setRowCount(len(rows))
        self._costliest = costliest_corner(rows)

        for position, row in enumerate(rows):
            corner = row.corner
            self._set(position, COLUMN_NAME, corner.label,
                      editable=True, tooltip=strings.CORNERS_TOOLTIP_NAME)
            self._set(position, COLUMN_APEX, format_distance(corner.apex_distance_m))
            self._set(position, COLUMN_MIN_SPEED, format_speed(corner.minimum_speed_ms))
            self._set(position, COLUMN_ENTRY_SPEED, format_speed(corner.entry_speed_ms))
            self._set(position, COLUMN_BRAKING, format_distance(corner.braking_length_m))
            self._set(position, COLUMN_TRAIL, format_distance(corner.trail_braking_m))
            self._set(position, COLUMN_COASTING,
                      format_seconds(corner.coasting_time_s, 2),
                      tone=coasting_tone(corner.coasting_time_s))

            self._set(position, COLUMN_SPEED_DELTA,
                      format_speed(row.speed_delta_ms, signed=True),
                      tone=theme.verdict(row.speed_delta_ms, higher_is_better=True))
            self._set(position, COLUMN_DELTA, format_gap(row.delta_s),
                      tone=theme.verdict(row.delta_s, higher_is_better=False))

            self._set(position, COLUMN_BEST_LAP,
                      MISSING if row.best_lap_index is None
                      else str(row.best_lap_index))
            self._set(position, COLUMN_GAIN, format_seconds(row.gain_s),
                      tooltip=strings.CORNERS_TOOLTIP_GAIN)

        if self._costliest is not None:
            self._mark(self._costliest)

    def _mark(self, costliest: CostliestCorner) -> None:
        """Make the costliest row stand out without moving it.

        Three cues, so colour is never the only one: a warning-coloured bar at
        the row's left edge, the emphasis weight on every cell, and a mark
        before the name (both drawn by `_MarkDelegate`). The figure it was
        chosen by takes the warning tone - unless it is the time lost to the
        comparison, which keeps the loss colour that says "slower".
        """
        position = costliest.position
        for column in range(self.table.columnCount()):
            item = self.table.item(position, column)
            if item is not None:
                item.setFont(theme.emphasised(self.table.font()))

        name = self.table.item(position, _INDEX_OF[COLUMN_NAME])
        name.setData(_MARK_ROLE, True)
        name.setToolTip(
            strings.CORNERS_TOOLTIP_COSTLIEST.format(
                mark=strings.COSTLIEST_MARK, cost=costliest_cost(costliest),
            ) + "\n\n" + strings.CORNERS_TOOLTIP_NAME
        )
        if costliest.basis is CostBasis.IDEAL:
            gain = self.table.item(position, _INDEX_OF[COLUMN_GAIN])
            gain.setForeground(QtGui.QColor(theme.tone_colour(theme.Tone.WARNING)))

    def _set(
        self,
        row: int,
        key: str,
        text: str,
        *,
        editable: bool = False,
        tone: theme.Tone | None = None,
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
        if tone is not None:
            item.setForeground(QtGui.QColor(theme.tone_colour(tone)))
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


class _MarkDelegate(QtWidgets.QStyledItemDelegate):
    """Draws the costliest corner's bar and mark beside its name.

    Both are added when the cell is drawn, not written into it: the name is
    the user's and editable, and a mark stored in the text would land in the
    editor and from there in the catalog.
    """

    def paint(
        self,
        painter: QtGui.QPainter,
        option: QtWidgets.QStyleOptionViewItem,
        index: QtCore.QModelIndex,
    ) -> None:
        super().paint(painter, option, index)
        if index.data(_MARK_ROLE):
            rect = option.rect
            painter.fillRect(
                QtCore.QRect(rect.left(), rect.top(),
                             theme.STANDOUT_BAR_WIDTH, rect.height()),
                theme.standout_brush(),
            )

    def initStyleOption(  # noqa: N802 - Qt override
        self, option: QtWidgets.QStyleOptionViewItem, index: QtCore.QModelIndex
    ) -> None:
        super().initStyleOption(option, index)
        if index.data(_MARK_ROLE):
            option.text = f"{strings.COSTLIEST_MARK} {option.text}"
            # Clear of the bar.
            option.rect.adjust(theme.STANDOUT_BAR_WIDTH, 0, 0, 0)

    def sizeHint(  # noqa: N802 - Qt override
        self, option: QtWidgets.QStyleOptionViewItem, index: QtCore.QModelIndex
    ) -> QtCore.QSize:
        # The mark is in the text measured; the bar beside it is not.
        hint = super().sizeHint(option, index)
        if index.data(_MARK_ROLE):
            hint.setWidth(hint.width() + theme.STANDOUT_BAR_WIDTH)
        return hint


def costliest_cost(costliest: CostliestCorner) -> str:
    """What the costliest corner costs, in words: the table's tooltip and the
    card's flag say it the same way."""
    template = (strings.COSTLIEST_IDEAL if costliest.basis is CostBasis.IDEAL
                else strings.COSTLIEST_COMPARISON)
    return template.format(seconds=format_seconds(costliest.seconds))


#: Time on neither pedal past which a corner is flagged, here and on the card.
COASTING_WARNING_S = 0.25


def coasting_tone(seconds: float | None) -> theme.Tone | None:
    """Flag a corner where the car spent real time on neither pedal.

    A tenth is the transition between the pedals and is unavoidable. Beyond
    about a quarter of a second the driver is waiting rather than transferring,
    and that is time given away for nothing.
    """
    if seconds is None or not np.isfinite(seconds):
        return None
    return theme.Tone.WARNING if seconds >= COASTING_WARNING_S else None
