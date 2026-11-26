"""The status bar: what is open, interrupted briefly by what just happened.

A status bar that only ever shows its latest message answers the wrong
question. Export a file and "Salvo em ..." stays there for the rest of the
session, long after the lap it was about has changed. So there are two kinds of
line:

- the **resting line** describes the lap on screen and stays until another lap
  replaces it;
- a **notice** ("Layout padrão restaurado", "Salvo em ...") interrupts it for a
  few seconds and then gives way, so the bar always comes back to the lap.

How long the analysis took is a fact about the application, not about the lap,
so it sits apart on the right, muted, where it is there for whoever wants it
and in nobody's way.
"""

from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from lmu_telemetry.shared import strings

#: How long a notice interrupts the resting line, in milliseconds. Long enough
#: to read a file path, short enough not to be mistaken for the lap's line.
NOTICE_MS = 6000


class StatusLine(QtWidgets.QStatusBar):
    """A status bar with a resting line, brief notices and a timing figure."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._resting = strings.STATUS_READY
        self.timing = QtWidgets.QLabel()
        self.timing.setProperty("role", "caption")
        self.timing.setToolTip(strings.STATUS_TIMING_TOOLTIP)
        # Permanent: a notice does not hide it.
        self.addPermanentWidget(self.timing)
        self.messageChanged.connect(self._on_message_changed)
        self.showMessage(self._resting)

    @property
    def resting(self) -> str:
        return self._resting

    def rest(self, text: str) -> None:
        """Set the line that describes what is on screen, and show it now."""
        self._resting = text
        self.showMessage(text)

    def notify(self, text: str, *, sticky: bool = False) -> None:
        """Interrupt the resting line.

        Args:
            sticky: Stay until replaced, for something still under way - an
                import in progress - whose end will say so itself.
        """
        self.showMessage(text, 0 if sticky else NOTICE_MS)

    def set_timing(self, elapsed_ms: float | None) -> None:
        self.timing.setText(
            "" if elapsed_ms is None else strings.STATUS_TIMING.format(elapsed=elapsed_ms)
        )

    def _on_message_changed(self, text: str) -> None:
        # A notice timing out clears the bar; the lap's line comes back.
        if not text and self._resting:
            self.showMessage(self._resting)
