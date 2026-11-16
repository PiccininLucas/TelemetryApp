"""A table header with a band of group labels above the column labels.

Qt has no grouped header, and the usual substitutes cost more than they give:
a second header view stacked above the first has to be kept in step with every
resize and scroll by hand, and spanning header items do not exist for
`QTableWidget`. This is one `QHeaderView` that is a band taller than it would
be: each section paints its own label in the lower part, and the band is
painted over the top from the sections' current geometry.

Because the band is computed from the sections every time it is painted, it
follows everything the sections do - horizontal scrolling, resizing, hidden
columns - with nothing to keep in sync. A group whose columns are all hidden
draws nothing; a group partly hidden spans the columns still showing.

The header is no wider than before: a group label is elided to its columns,
never allowed to widen them.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from PySide6 import QtCore, QtGui, QtWidgets

from lmu_telemetry.presentation import theme

#: Space around a group label, and between two groups' rules, in pixels.
_PAD_X = 6
_PAD_Y = 2
_GAP = 3


@dataclass(frozen=True, slots=True)
class ColumnGroup:
    """Columns that read together, under one label.

    Attributes:
        label: What the band says above them.
        columns: Their logical indices, adjacent and in display order.
    """

    label: str
    columns: tuple[int, ...]


class GroupedHeader(QtWidgets.QHeaderView):
    """A horizontal header with a group band above the column labels."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(QtCore.Qt.Orientation.Horizontal, parent)
        self._groups: tuple[ColumnGroup, ...] = ()
        self._band = theme.header_band()
        # A resize anywhere in a group moves its centre and its elision, and
        # Qt only repaints the sections right of the one that changed.
        self.sectionResized.connect(self._repaint)
        self.geometriesChanged.connect(self._repaint)

    def set_groups(self, groups: Sequence[ColumnGroup]) -> None:
        self._groups = tuple(groups)
        self.updateGeometries()
        self._repaint()

    @property
    def groups(self) -> tuple[ColumnGroup, ...]:
        return self._groups

    def band_height(self) -> int:
        """Height of the group band; nothing when there are no groups."""
        if not self._groups:
            return 0
        return QtGui.QFontMetrics(self._band.font).height() + 2 * _PAD_Y + 1

    def group_span(self, group: ColumnGroup) -> tuple[int, int] | None:
        """`(left, right)` of a group in viewport pixels, over the columns still
        showing; None when they are all hidden."""
        edges = [
            (self.sectionViewportPosition(column),
             self.sectionViewportPosition(column) + self.sectionSize(column))
            for column in group.columns
            if not self.isSectionHidden(column)
        ]
        if not edges:
            return None
        return min(left for left, _ in edges), max(right for _, right in edges)

    def group_label_at(self, x: int) -> str | None:
        """The group over a viewport position, for tooltips and tests."""
        for group in self._groups:
            span = self.group_span(group)
            if span is not None and span[0] <= x < span[1]:
                return group.label
        return None

    # -- Qt overrides --------------------------------------------------------

    def sizeHint(self) -> QtCore.QSize:  # noqa: N802 - Qt override
        hint = super().sizeHint()
        hint.setHeight(hint.height() + self.band_height())
        return hint

    def paintSection(  # noqa: N802 - Qt override
        self, painter: QtGui.QPainter, rect: QtCore.QRect, logical_index: int
    ) -> None:
        super().paintSection(
            painter, rect.adjusted(0, self.band_height(), 0, 0), logical_index
        )

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: N802
        super().paintEvent(event)
        if not self._groups:
            return
        band = self.band_height()
        painter = QtGui.QPainter(self.viewport())
        try:
            painter.setFont(self._band.font)
            metrics = painter.fontMetrics()
            for group in self._groups:
                span = self.group_span(group)
                if span is None:
                    continue
                left, right = span[0] + _GAP, span[1] - _GAP
                if right - left < 2 * _PAD_X:
                    continue
                label_rect = QtCore.QRect(left, 0, right - left, band - 1)
                text = metrics.elidedText(
                    group.label, QtCore.Qt.TextElideMode.ElideRight,
                    label_rect.width() - 2 * _PAD_X,
                )
                painter.setPen(self._band.text)
                painter.drawText(label_rect, QtCore.Qt.AlignmentFlag.AlignCenter, text)
                painter.setPen(self._band.rule)
                painter.drawLine(left, band - 1, right - 1, band - 1)
        finally:
            painter.end()

    def viewportEvent(self, event: QtCore.QEvent) -> bool:  # noqa: N802
        # The band's tooltip names the group, so an elided label can still be
        # read in full. Help events reach a header through its viewport.
        if event.type() == QtCore.QEvent.Type.ToolTip and isinstance(event, QtGui.QHelpEvent):
            if event.pos().y() < self.band_height():
                label = self.group_label_at(event.pos().x())
                if label is not None:
                    QtWidgets.QToolTip.showText(event.globalPos(), label, self)
                    return True
        return super().viewportEvent(event)

    def _repaint(self, *_args) -> None:
        self.viewport().update()
