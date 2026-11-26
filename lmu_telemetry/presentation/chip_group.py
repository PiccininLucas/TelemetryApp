"""A row of chips of which exactly one is chosen.

The channel chips above the traces are switches - any number on. This is the
other kind: a choice among a few options, all of them in view, where a combo
box would hide every option but the current one behind a click. It wears the
same `role="chip"` the theme styles, so the two read as one family.

Keyboard: as a group of radio buttons, which Qt does for any exclusive
`QButtonGroup` - Tab stops only on the chosen chip, and the arrow keys move the
choice along the row. Each chip carries the full name of its option as its
accessible name and tooltip, since its own text is short.

The chips wrap onto a second line rather than widen their panel: a long stint
list must not set the window's minimum width.
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6 import QtCore, QtWidgets


class ChipGroup(QtWidgets.QWidget):
    """Exclusive chips. `chosen(index)` when the user picks one."""

    chosen = QtCore.Signal(int)

    def __init__(
        self, accessible_name: str, parent: QtWidgets.QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setAccessibleName(accessible_name)
        self._layout = FlowLayout(self, spacing=4)
        self._group = QtWidgets.QButtonGroup(self)
        self._group.setExclusive(True)
        self._group.idClicked.connect(self.chosen)
        self._chips: list[QtWidgets.QToolButton] = []

    def set_options(
        self,
        labels: Sequence[str],
        descriptions: Sequence[str] | None = None,
        current: int = 0,
    ) -> None:
        """Replace the chips, without emitting `chosen`.

        Args:
            labels: The chips' text, short.
            descriptions: Each option's full name, for its tooltip and screen
                readers; the label when omitted.
            current: The chip to start chosen.
        """
        for chip in self._chips:
            self._group.removeButton(chip)
            self._layout.removeWidget(chip)
            chip.deleteLater()
        self._chips = []
        descriptions = list(descriptions) if descriptions is not None else list(labels)
        for index, (label, description) in enumerate(
            zip(labels, descriptions, strict=True)
        ):
            chip = QtWidgets.QToolButton(self)
            chip.setProperty("role", "chip")
            chip.setText(label)
            chip.setToolTip(description)
            chip.setAccessibleName(description)
            chip.setCheckable(True)
            chip.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
            self._group.addButton(chip, index)
            self._layout.addWidget(chip)
            self._chips.append(chip)
        self.set_current_index(current)
        self.updateGeometry()

    def count(self) -> int:
        return len(self._chips)

    def chips(self) -> list[QtWidgets.QToolButton]:
        return list(self._chips)

    def current_index(self) -> int:
        """The chosen chip, or -1 when there are none."""
        return self._group.checkedId()

    def set_current_index(self, index: int) -> None:
        """Choose a chip without emitting `chosen`, which is for the user's
        choices only."""
        if 0 <= index < len(self._chips):
            self._chips[index].setChecked(True)


class FlowLayout(QtWidgets.QLayout):
    """Items left to right, wrapping to a new line when the width runs out.

    Its minimum width is its widest item, and its height follows its width
    (`heightForWidth`), so a parent layout gives it the extra line when it has
    to wrap and takes it back when it does not.
    """

    def __init__(self, parent: QtWidgets.QWidget | None = None, spacing: int = 4) -> None:
        super().__init__(parent)
        self._items: list[QtWidgets.QLayoutItem] = []
        self._gap = spacing
        self.setContentsMargins(0, 0, 0, 0)

    # -- QLayout -------------------------------------------------------------

    def addItem(self, item: QtWidgets.QLayoutItem) -> None:  # noqa: N802
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QtWidgets.QLayoutItem | None:  # noqa: N802
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> QtWidgets.QLayoutItem | None:  # noqa: N802
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self) -> QtCore.Qt.Orientation:  # noqa: N802
        return QtCore.Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._arrange(QtCore.QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QtCore.QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._arrange(rect, apply=True)

    def sizeHint(self) -> QtCore.QSize:  # noqa: N802
        """Everything on one line."""
        visible = self._visible()
        if not visible:
            return QtCore.QSize(0, 0)
        width = sum(item.sizeHint().width() for item in visible)
        width += self._gap * (len(visible) - 1)
        height = max(item.sizeHint().height() for item in visible)
        return self._with_margins(QtCore.QSize(width, height))

    def minimumSize(self) -> QtCore.QSize:  # noqa: N802
        """The widest item: anything narrower than that cannot wrap further."""
        size = QtCore.QSize(0, 0)
        for item in self._visible():
            size = size.expandedTo(item.minimumSize())
        return self._with_margins(size)

    # -- layout ----------------------------------------------------------------

    def _visible(self) -> list[QtWidgets.QLayoutItem]:
        return [item for item in self._items if not item.isEmpty()]

    def _with_margins(self, size: QtCore.QSize) -> QtCore.QSize:
        margins = self.contentsMargins()
        return size + QtCore.QSize(margins.left() + margins.right(),
                                   margins.top() + margins.bottom())

    def _arrange(self, rect: QtCore.QRect, *, apply: bool) -> int:
        """Place the items within `rect` (or only measure); returns the height."""
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(),
                             -margins.right(), -margins.bottom())
        x, y, line_height = area.x(), area.y(), 0
        for item in self._visible():
            hint = item.sizeHint()
            if x > area.x() and x + hint.width() > area.right() + 1:
                x = area.x()
                y += line_height + self._gap
                line_height = 0
            if apply:
                item.setGeometry(QtCore.QRect(QtCore.QPoint(x, y), hint))
            x += hint.width() + self._gap
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y() + margins.bottom()
