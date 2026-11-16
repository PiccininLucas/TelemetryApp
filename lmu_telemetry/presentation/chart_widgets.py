"""Small widgets the plots are read through: line keys and cursor readouts.

They replace rich-text labels. A line of HTML could say "this lap is blue", but
not "and dashed", and every number in it shifted its neighbours whenever it
changed width. These draw the actual line style next to its name, and give each
figure a cell of fixed width, so the readout holds still while the cursor
moves.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6 import QtCore, QtGui, QtWidgets

from lmu_telemetry.presentation import theme


@dataclass(frozen=True, slots=True)
class LineStyle:
    """How a curve is drawn, so its key can be drawn the same way."""

    colour: str
    width: float = 1.6
    dashed: bool = False

    def pen(self) -> QtGui.QPen:
        pen = QtGui.QPen(QtGui.QColor(self.colour))
        pen.setWidthF(self.width)
        # Width in pixels, whatever the plot's scale. Without it a "2.4" path
        # on a 1.2 km circuit is 2.4 metres wide - under a pixel - and a trace
        # thins and breaks wherever the axes are stretched.
        pen.setCosmetic(True)
        pen.setCapStyle(QtCore.Qt.PenCapStyle.FlatCap)
        if self.dashed:
            pen.setStyle(QtCore.Qt.PenStyle.DashLine)
        return pen


class LineSwatch(QtWidgets.QWidget):
    """A short sample of a line: its colour, its width and whether it is dashed.

    The key to a chart has to show every cue the chart uses, not only the
    colour - otherwise a reader who cannot tell the colours apart has no key.
    """

    def __init__(self, style: LineStyle, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._style = style
        self.setFixedSize(22, 12)

    @property
    def line_style(self) -> LineStyle:
        return self._style

    def set_line_style(self, style: LineStyle) -> None:
        self._style = style
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QtGui.QPainter(self)
        # A thicker pen than the curve's: at 22 px a 1.3 px dash pattern is
        # too fine to read as dashed.
        pen = self._style.pen()
        pen.setWidthF(max(self._style.width, 2.0))
        painter.setPen(pen)
        y = self.height() / 2
        painter.drawLine(QtCore.QPointF(1, y), QtCore.QPointF(self.width() - 1, y))
        painter.end()


class LineKey(QtWidgets.QWidget):
    """A swatch and the name of what it stands for."""

    def __init__(
        self, style: LineStyle, text: str = "", parent: QtWidgets.QWidget | None = None
    ) -> None:
        super().__init__(parent)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.swatch = LineSwatch(style)
        self.label = QtWidgets.QLabel(text)
        layout.addWidget(self.swatch)
        layout.addWidget(self.label)

    def set(self, style: LineStyle, text: str) -> None:
        self.swatch.set_line_style(style)
        self.label.setText(text)


class ReadoutCell(QtWidgets.QWidget):
    """One quantity under the cursor: a caption over one or two values.

    The second value is the comparison lap's. Each value has a minimum width
    measured from the widest figure it can show, so the cells do not jostle
    as the cursor moves - the desktop equivalent of a web page's animated
    number: the figure changes, the layout does not.
    """

    def __init__(
        self, caption: str, widest: str = "-0000.0",
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.caption = QtWidgets.QLabel(caption)
        self.caption.setProperty("role", "caption")
        layout.addWidget(self.caption)

        values = QtWidgets.QHBoxLayout()
        values.setSpacing(4)
        self.primary = self._value(widest)
        self.separator = QtWidgets.QLabel("/")
        self.separator.setProperty("role", "caption")
        self.comparison = self._value(widest)
        values.addWidget(self.primary)
        values.addWidget(self.separator)
        values.addWidget(self.comparison)
        values.addStretch(1)
        layout.addLayout(values)
        self.show_values(None)

    def _value(self, widest: str) -> QtWidgets.QLabel:
        label = QtWidgets.QLabel("--")
        label.setFont(theme.figures(label.font()))
        label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight
                           | QtCore.Qt.AlignmentFlag.AlignVCenter)
        self._widest = widest
        return label

    def ensure_width(self) -> None:
        """Size the values for the widest figure, in the font they end up in
        (the style sheet's, known only once polished)."""
        for label in (self.primary, self.comparison):
            label.ensurePolished()
            label.setMinimumWidth(label.fontMetrics().horizontalAdvance(self._widest))

    def show_values(
        self,
        primary: str | None,
        comparison: str | None = None,
        *,
        primary_series: str | None = None,
        comparison_series: str | None = None,
        comparison_italic: bool = False,
        tone: theme.Tone | None = None,
    ) -> None:
        """Show the values; None shows "--" (no cursor) or hides the second.

        Args:
            primary_series, comparison_series: Keys of `theme.SERIES_COLOURS`:
                each value takes the colour of the curve it was read from.
            comparison_italic: Where the chart tells the laps apart by line
                style rather than colour (the pedals), the readout has no line
                to dash, so the comparison's figure is set in italic instead.
            tone: Overrides the colour with a meaning (gain, loss) - the delta.
        """
        self.primary.setText("--" if primary is None else primary)
        theme.set_series(self.primary, primary_series)
        theme.set_tone(self.primary, tone)

        has_comparison = comparison is not None
        self.separator.setVisible(has_comparison)
        self.comparison.setVisible(has_comparison)
        if has_comparison:
            self.comparison.setText(comparison)
            theme.set_series(self.comparison, comparison_series)
            font = self.comparison.font()
            font.setItalic(comparison_italic)
            self.comparison.setFont(font)
