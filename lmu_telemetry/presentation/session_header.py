"""The strip across the top of the window: what is open, and how it went.

Every other panel answers a question about one part of the lap. This one answers
the question asked before any of them - which lap is this, against what, and is
it any good - so it is always visible and never needs reading twice: the track,
the car, the lap time against its reference, the three sectors against the
session's best, the session's best lap and the theoretical ideal.

It only displays. `SessionSummary` is assembled by the window from data it
already holds, and nothing here reaches into a session.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6 import QtCore, QtWidgets

from lmu_telemetry.presentation import theme
from lmu_telemetry.shared import strings
from lmu_telemetry.shared.formatting import (
    format_gap, format_lap_time, format_sector_time,
)


@dataclass(frozen=True, slots=True)
class SectorFigure:
    """One sector of the lap on screen, against the session's best.

    Attributes:
        time_s: This lap's sector time, or None when the game reported none.
        best_s: The session's best for this sector among comparable laps.
    """

    time_s: float | None
    best_s: float | None = None

    @property
    def is_best(self) -> bool:
        """True when this lap set the session's best for the sector."""
        return (
            self.time_s is not None and self.best_s is not None
            and self.time_s <= self.best_s + 1e-6
        )

    @property
    def gap_s(self) -> float | None:
        if self.time_s is None or self.best_s is None:
            return None
        return self.time_s - self.best_s


@dataclass(frozen=True, slots=True)
class SessionSummary:
    """Everything the header shows, already decided.

    Attributes:
        track: Circuit name as the game gives it.
        details: Car, class, session type and weather, those that are known.
        lap_number: The lap on screen.
        lap_time_s: Its time.
        reference: What it is compared against, already worded; None when
            nothing is.
        delta_s: Lap time minus the reference's. Negative is faster.
        sectors: The three sectors.
        best_lap_number: The session's best comparable lap.
        best_lap_time_s: Its time.
        ideal_time_s: The stitched ideal lap, when there are enough laps.
    """

    track: str
    details: tuple[str, ...]
    lap_number: int
    lap_time_s: float | None
    reference: str | None = None
    delta_s: float | None = None
    sectors: tuple[SectorFigure, ...] = field(default_factory=tuple)
    best_lap_number: int | None = None
    best_lap_time_s: float | None = None
    ideal_time_s: float | None = None

    @property
    def ideal_gain_s(self) -> float | None:
        """How far the ideal lap is below the session's best."""
        if self.ideal_time_s is None or self.best_lap_time_s is None:
            return None
        return self.ideal_time_s - self.best_lap_time_s


class _Stat(QtWidgets.QWidget):
    """A caption over a figure: the unit every block of the header is made of."""

    def __init__(self, caption: str, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)
        self.caption = QtWidgets.QLabel(caption)
        self.caption.setProperty("role", "caption")
        self.value = QtWidgets.QLabel("--")
        self.value.setProperty("role", "stat")
        self.value.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.caption)
        layout.addWidget(self.value)

    def set(self, text: str, *, tone: theme.Tone | None = None, tooltip: str = "") -> None:
        self.value.setText(text)
        theme.set_tone(self.value, tone)
        self.setToolTip(tooltip)


def _divider() -> QtWidgets.QFrame:
    line = QtWidgets.QFrame()
    line.setProperty("role", "divider")
    line.setFixedWidth(1)
    line.setSizePolicy(
        QtWidgets.QSizePolicy.Policy.Fixed, QtWidgets.QSizePolicy.Policy.Expanding
    )
    return line


class SessionHeader(QtWidgets.QWidget):
    """The summary strip. `show_summary` fills it, `clear` empties it."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._build()
        self.clear()

    def _build(self) -> None:
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # The figures scroll sideways in a narrow window instead of setting its
        # minimum width: a strip of ten figures is wider than a laptop screen
        # once the window is split, and a header must never be the reason the
        # window cannot be made smaller.
        content = QtWidgets.QWidget()
        content.setObjectName("header_content")
        layout = QtWidgets.QHBoxLayout(content)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(18)

        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setObjectName("header_scroll")
        self.scroll.setWidget(content)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll.setMinimumWidth(120)
        self.scroll.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed
        )
        outer.addWidget(self.scroll)
        self._content = content

        identity = QtWidgets.QWidget()
        identity_layout = QtWidgets.QVBoxLayout(identity)
        identity_layout.setContentsMargins(0, 0, 0, 0)
        identity_layout.setSpacing(1)
        self.track = QtWidgets.QLabel()
        self.track.setProperty("role", "title")
        self.details = QtWidgets.QLabel()
        self.details.setProperty("role", "caption")
        identity_layout.addWidget(self.track)
        identity_layout.addWidget(self.details)
        layout.addWidget(identity)

        dividers = [_divider() for _ in range(3)]
        layout.addWidget(dividers[0])
        self.lap = _Stat(strings.HEADER_LAP.format(number=""))
        self.reference = _Stat(strings.HEADER_REFERENCE)
        self.delta = _Stat(strings.HEADER_DELTA)
        for stat in (self.lap, self.reference, self.delta):
            layout.addWidget(stat)

        layout.addWidget(dividers[1])
        self.sectors = [
            _Stat(strings.HEADER_SECTOR.format(n=n)) for n in (1, 2, 3)
        ]
        for stat in self.sectors:
            layout.addWidget(stat)

        layout.addWidget(dividers[2])
        self.best = _Stat(strings.HEADER_BEST)
        self.ideal = _Stat(strings.HEADER_IDEAL)
        layout.addWidget(self.best)
        layout.addWidget(self.ideal)
        layout.addStretch(1)

        self.placeholder = QtWidgets.QLabel(strings.HEADER_EMPTY)
        self.placeholder.setProperty("role", "placeholder")
        layout.addWidget(self.placeholder)

        self._figures: list[QtWidgets.QWidget] = [
            self.track, self.details, *dividers, self.lap, self.reference,
            self.delta, *self.sectors, self.best, self.ideal,
        ]
        self._fit_height()

    def _fit_height(self) -> None:
        """Tall enough for the figures plus a scrollbar, so a scrollbar that
        appears in a narrow window never covers them."""
        bar = self.scroll.horizontalScrollBar().sizeHint().height()
        self.scroll.setFixedHeight(self._content.sizeHint().height() + bar)

    # -- data --------------------------------------------------------------

    def show_summary(self, summary: SessionSummary) -> None:
        self.track.setText(summary.track)
        self.details.setText("  ·  ".join(summary.details))

        self.lap.caption.setText(strings.HEADER_LAP.format(number=summary.lap_number))
        self.lap.set(format_lap_time(summary.lap_time_s))

        self.reference.set(summary.reference or strings.HEADER_REFERENCE_NONE)
        self.delta.set(
            format_gap(summary.delta_s),
            tone=theme.verdict(summary.delta_s, higher_is_better=False),
            tooltip=strings.HEADER_DELTA_TOOLTIP,
        )

        for number, (stat, sector) in enumerate(
            zip(self.sectors, _three(summary.sectors), strict=True), start=1
        ):
            self._show_sector(stat, number, sector)

        self.best.set(
            "--" if summary.best_lap_number is None
            else strings.HEADER_BEST_VALUE.format(
                time=format_lap_time(summary.best_lap_time_s),
                number=summary.best_lap_number,
            )
        )
        self.ideal.set(
            "--" if summary.ideal_time_s is None
            else strings.HEADER_IDEAL_VALUE.format(
                time=format_lap_time(summary.ideal_time_s),
                gain=format_gap(summary.ideal_gain_s),
            )
        )

        self.placeholder.hide()
        for widget in self._figures:
            widget.show()

    def _show_sector(self, stat: _Stat, number: int, sector: SectorFigure) -> None:
        text = format_sector_time(sector.time_s)
        if sector.is_best:
            # Session-best sectors in the "faster" colour: the one fact a timing
            # screen shows about a sector before any other.
            stat.set(text, tone=theme.Tone.BEST,
                     tooltip=strings.HEADER_SECTOR_BEST_TOOLTIP.format(n=number, time=text))
            return
        gap = sector.gap_s
        stat.set(
            text if gap is None else f"{text}  {format_gap(gap)}",
            tooltip=(
                "" if gap is None else strings.HEADER_SECTOR_TOOLTIP.format(
                    n=number, time=text, best=format_sector_time(sector.best_s),
                    gap=format_gap(gap),
                )
            ),
        )

    def clear(self) -> None:
        for widget in self._figures:
            widget.hide()
        self.placeholder.show()


def _three(sectors: tuple[SectorFigure, ...]) -> tuple[SectorFigure, ...]:
    """Exactly three sectors, padding with empty ones."""
    padded = tuple(sectors[:3])
    return padded + tuple(SectorFigure(None) for _ in range(3 - len(padded)))
