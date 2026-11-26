"""The banner above the traces: what the user must know before trusting them.

It speaks rarely and only about the lap on screen - a clock that had to be
corrected, a comparison that was refused, a session that could not be opened -
so when it appears it is read. Two rules keep it that way:

- **one note per line.** Notes are separate facts; run together into one
  paragraph the second is lost in the first.
- **two levels.** A *warning* says the figures are drawn but carry a caveat; an
  *error* says there is nothing to trust. They look different, so the reader
  knows which before reading a word.

It can be dismissed, and stays dismissed until the next lap brings notes of its
own: a caveat the user has read does not need to keep half an inch of the
traces.
"""

from __future__ import annotations

from enum import StrEnum

from PySide6 import QtCore, QtWidgets

from lmu_telemetry.shared import strings


class Severity(StrEnum):
    WARNING = "warning"
    ERROR = "error"


class NoticeBanner(QtWidgets.QFrame):
    """Notes about the lap on screen, with a severity and a dismiss button."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("notice")
        self.setProperty("role", "notice")
        self._notes: list[str] = []
        self.severity = Severity.WARNING
        self._apply_severity(Severity.WARNING)

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 6, 8)
        layout.setSpacing(10)

        self.title = QtWidgets.QLabel()
        self.title.setObjectName("notice_title")
        self.title.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
        self.body = QtWidgets.QLabel()
        self.body.setObjectName("notice_body")
        self.body.setWordWrap(True)
        self.body.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.dismiss = QtWidgets.QToolButton()
        self.dismiss.setObjectName("notice_dismiss")
        self.dismiss.setText("✕")
        self.dismiss.setToolTip(strings.NOTICE_DISMISS)
        self.dismiss.setAccessibleName(strings.NOTICE_DISMISS)
        self.dismiss.setAutoRaise(True)
        self.dismiss.clicked.connect(self.hide)

        layout.addWidget(self.title)
        layout.addWidget(self.body, stretch=1)
        layout.addWidget(self.dismiss, alignment=QtCore.Qt.AlignmentFlag.AlignTop)
        self.hide()

    @property
    def notes(self) -> list[str]:
        return list(self._notes)

    def show_notes(self, notes: list[str] | tuple[str, ...],
                   severity: Severity = Severity.WARNING) -> None:
        """Show `notes`, or hide the banner when there are none."""
        self._notes = [note for note in notes if note]
        if not self._notes:
            self.hide()
            return
        self._apply_severity(severity)
        self.title.setText(
            strings.NOTICE_ERROR if severity is Severity.ERROR else strings.NOTICE_WARNING
        )
        self.body.setText("\n".join(
            note if len(self._notes) == 1 else f"• {note}" for note in self._notes
        ))
        self.setAccessibleName(f"{self.title.text()}: {' '.join(self._notes)}")
        self.show()

    def clear(self) -> None:
        self.show_notes([])

    def _apply_severity(self, severity: Severity) -> None:
        self.severity = severity
        if self.property("severity") == severity.value:
            return
        self.setProperty("severity", severity.value)
        # Children select on the frame's property too, so all are re-polished.
        for widget in (self, *self.findChildren(QtWidgets.QWidget)):
            widget.style().unpolish(widget)
            widget.style().polish(widget)
