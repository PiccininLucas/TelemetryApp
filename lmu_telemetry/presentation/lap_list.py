"""Every lap of the open session, with its sectors.

The session tree answers "which session"; this answers "which lap of it", with
the figures a driver picks a lap by: the time, the three sectors, how far it is
off the best, and whether it can be compared at all. The session's best lap and
best sectors are marked, and so is the lap being used as the reference, so the
table also says what the traces are being measured against.

Rows stay in the order the laps were driven. Sorting by time would put the best
lap at the top and lose the shape of the stint, which is what this list shows
that a single best lap cannot.
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6 import QtCore, QtGui, QtWidgets

from lmu_telemetry.domain.models import Lap
from lmu_telemetry.presentation import theme
from lmu_telemetry.shared import strings
from lmu_telemetry.shared.formatting import (
    format_gap, format_lap_time, format_sector_time,
)

COLUMN_LAP, COLUMN_TIME, COLUMN_S1, COLUMN_S2, COLUMN_S3, COLUMN_GAP, COLUMN_STATUS = range(7)
SECTOR_COLUMNS = (COLUMN_S1, COLUMN_S2, COLUMN_S3)


def best_lap(laps: Sequence[Lap]) -> Lap | None:
    """The fastest lap that can be compared, the same rule the comparison uses."""
    comparable = [lap for lap in laps if lap.is_comparable]
    return min(comparable, key=lambda lap: lap.time_s) if comparable else None


def best_sectors(laps: Sequence[Lap]) -> tuple[float | None, float | None, float | None]:
    """The session's best time in each sector, among comparable laps.

    Only comparable laps count: an out-lap's first sector starts in the pit lane
    and an invalidated lap's sector may have been bought by cutting a corner,
    and either would make every other lap's sector look slow.
    """
    best: list[float | None] = [None, None, None]
    for lap in laps:
        if not lap.is_comparable:
            continue
        for i, sector in enumerate(lap.sector_times_s[:3]):
            if sector is not None and sector > 0 and (best[i] is None or sector < best[i]):
                best[i] = sector
    return (best[0], best[1], best[2])


class LapList(QtWidgets.QWidget):
    """The lap table. Emits `lap_chosen` with a lap index when one is picked."""

    lap_chosen = QtCore.Signal(int)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._laps: list[Lap] = []
        self._build()
        self.clear()

    def _build(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.summary = QtWidgets.QLabel()
        self.summary.setProperty("role", "heading")
        layout.addWidget(self.summary)

        self.table = QtWidgets.QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels([
            strings.LAPS_COLUMN_LAP, strings.LAPS_COLUMN_TIME,
            *(strings.LAPS_COLUMN_SECTOR.format(n=n) for n in (1, 2, 3)),
            strings.LAPS_COLUMN_GAP, strings.LAPS_COLUMN_STATUS,
        ])
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection
        )
        self.table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers
        )
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)
        self.table.setAccessibleName(strings.DOCK_LAPS)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.table, stretch=1)

        self.placeholder = QtWidgets.QLabel(strings.LAPS_EMPTY)
        self.placeholder.setProperty("role", "placeholder")
        self.placeholder.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.placeholder.setWordWrap(True)
        layout.addWidget(self.placeholder, stretch=1)

    # -- data --------------------------------------------------------------

    def show_laps(
        self,
        laps: Sequence[Lap],
        current_index: int | None = None,
        reference_index: int | None = None,
    ) -> None:
        """Fill the table with one session's laps.

        Args:
            laps: Every lap of the session, in order.
            current_index: The lap on screen, selected without emitting.
            reference_index: The lap it is compared against, when that is a lap
                of this session.
        """
        self._laps = list(laps)
        best = best_lap(self._laps)
        sectors = best_sectors(self._laps)

        blocked = self.table.blockSignals(True)
        try:
            self.table.clearContents()
            self.table.setRowCount(len(self._laps))
            for row, lap in enumerate(self._laps):
                self._fill_row(row, lap, best, sectors, reference_index)
            self._select(current_index)
        finally:
            self.table.blockSignals(blocked)

        comparable = sum(lap.is_comparable for lap in self._laps)
        self.summary.setText(strings.LAPS_SUMMARY.format(
            n=len(self._laps), comparable=comparable,
            best=format_lap_time(None if best is None else best.time_s),
        ))
        self.placeholder.hide()
        self.summary.show()
        self.table.show()

    def _fill_row(
        self,
        row: int,
        lap: Lap,
        best: Lap | None,
        sectors: tuple[float | None, ...],
        reference_index: int | None,
    ) -> None:
        is_best = best is not None and lap.index == best.index
        is_reference = reference_index is not None and lap.index == reference_index
        # A lap that cannot be compared is still listed - it is part of the
        # session - but dimmed, so it never reads as a candidate.
        dim = None if lap.is_comparable else theme.TEXT_DISABLED

        number = str(lap.number)
        if is_reference:
            number = f"{number}  {strings.LAPS_MARK_REFERENCE}"
        self._set(row, COLUMN_LAP, number, colour=dim,
                  tooltip=strings.LAPS_TOOLTIP_REFERENCE if is_reference else "")

        self._set(
            row, COLUMN_TIME, format_lap_time(lap.time_s),
            colour=theme.TRACE_IDEAL if is_best else dim, bold=is_best,
            tooltip=strings.LAPS_TOOLTIP_BEST if is_best else "",
        )

        for column, sector, best_sector in zip(
            SECTOR_COLUMNS, _three(lap.sector_times_s), sectors, strict=True
        ):
            is_best_sector = (
                lap.is_comparable and sector is not None and best_sector is not None
                and sector <= best_sector + 1e-6
            )
            self._set(
                row, column, format_sector_time(sector),
                colour=theme.TRACE_IDEAL if is_best_sector else dim,
                tooltip=strings.LAPS_TOOLTIP_SECTOR_BEST if is_best_sector else "",
            )

        gap = (
            lap.time_s - best.time_s
            if best is not None and lap.is_comparable and not is_best else None
        )
        self._set(row, COLUMN_GAP, strings.LAPS_MARK_BEST if is_best else format_gap(gap),
                  colour=theme.TRACE_IDEAL if is_best else dim)

        flags = [flag.value for flag in lap.flags]
        self._set(row, COLUMN_STATUS, strings.primary_lap_flag(flags), colour=dim,
                  tooltip=", ".join(lap.flag_labels()), align_right=False)

    def _set(
        self,
        row: int,
        column: int,
        text: str,
        *,
        colour: str | None = None,
        bold: bool = False,
        tooltip: str = "",
        align_right: bool = True,
    ) -> None:
        item = QtWidgets.QTableWidgetItem(text)
        if align_right:
            item.setTextAlignment(
                QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter
            )
        if colour is not None:
            item.setForeground(QtGui.QColor(colour))
        if bold:
            font = item.font()
            font.setBold(True)
            item.setFont(font)
        item.setToolTip(tooltip or strings.LAPS_TOOLTIP_ROW)
        self.table.setItem(row, column, item)

    def clear(self) -> None:
        self._laps = []
        blocked = self.table.blockSignals(True)
        try:
            self.table.setRowCount(0)
        finally:
            self.table.blockSignals(blocked)
        self.summary.hide()
        self.table.hide()
        self.placeholder.show()

    # -- selection ---------------------------------------------------------

    def select_lap(self, lap_index: int | None) -> None:
        """Mark the lap on screen, without emitting."""
        blocked = self.table.blockSignals(True)
        try:
            self._select(lap_index)
        finally:
            self.table.blockSignals(blocked)

    def _select(self, lap_index: int | None) -> None:
        self.table.clearSelection()
        for row, lap in enumerate(self._laps):
            if lap.index == lap_index:
                self.table.selectRow(row)
                self.table.scrollToItem(self.table.item(row, COLUMN_LAP))
                return

    def _on_selection_changed(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        row = rows[0].row()
        if 0 <= row < len(self._laps):
            self.lap_chosen.emit(self._laps[row].index)


def _three(values: Sequence[float | None]) -> tuple[float | None, ...]:
    padded = tuple(values[:3])
    return padded + (None,) * (3 - len(padded))
