"""Stacked traces sharing one X axis, with a delta-t row.

Phase 5 drew one channel. This is the instrument a lap is actually read on:
speed, pedals, steering, gear and engine speed stacked vertically, all sharing
one X axis, plus the delta-t against a reference lap at the bottom.

Three decisions carry the design.

**One shared X axis, not one plot per window.** A braking point is a
relationship between rows - the brake goes down here, the speed breaks there,
the downshifts follow. Reading it requires the rows to be vertically aligned to
the metre, which is why every plot's left axis is pinned to the same width and
every X range is linked to the first row's.

**Distance, not time, whenever two laps are shown.** Two laps at the same
*time* are at different places on the circuit, so any difference between them
means nothing. Comparison therefore only exists on the distance axis; the time
axis stays available for looking at a single lap's rhythm, and the window
disables it while a comparison is drawn.

**Delta-t is a slope, not a value.** `delta(s) = t_lap(s) - t_reference(s)`
only grows where time is being lost *right now*; a flat delta at a high value is
a loss that already happened and is simply being carried. The row is filled to
zero so the eye follows the slope rather than the level.

This module takes numpy arrays. It knows nothing about sessions, files or the
analysis pipeline, which is what lets it be tested with three-point arrays.
"""

from __future__ import annotations

import functools
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets

from lmu_telemetry.ui import strings, theme
from lmu_telemetry.ui.formatting import format_value


class AxisMode(str, Enum):
    """What the X axis measures."""

    #: Distance around the lap. The only mode in which two laps can be
    #: meaningfully compared, and therefore the default.
    DISTANCE = "distance"
    #: Time since the lap started. Useful for reading a single lap's rhythm.
    TIME = "time"


class Role(str, Enum):
    """Which of the two laps a curve belongs to."""

    #: The lap the user selected. Drawn in the primary colour, thicker.
    PRIMARY = "primary"
    #: The lap it is being compared against.
    BENCHMARK = "benchmark"


# --------------------------------------------------------------------------- #
# What each row contains
# --------------------------------------------------------------------------- #

@dataclass(frozen=True, slots=True)
class Series:
    """One curve within a row.

    Attributes:
        channel: Key into a lap's channel mapping. Values are in the
            application's canonical SI units.
        label: Short name for the cursor readout.
        scale: Multiplier from canonical units to display units. Speed is held
            in m/s and shown in km/h; pedals are held as a 0-1 fraction and
            shown as a percentage. The conversion lives here, at the edge, so
            nothing upstream ever has to remember which unit it is holding.
        decimals: Digits after the point in the readout.
        colour: Fixed colour, when the row uses colour to tell *channels* apart
            rather than laps. None means the curve takes its lap's colour.
    """

    channel: str
    label: str
    scale: float = 1.0
    decimals: int = 0
    colour: str | None = None


@dataclass(frozen=True, slots=True)
class RowSpec:
    """One stacked plot.

    Attributes:
        key: Stable identifier, used by the menu that toggles rows.
        axis_label: Left-axis label, carrying the unit.
        series: Curves drawn in this row.
        y_range: Fixed Y range, or None to autoscale. Fixed where the channel
            has a physical range - a pedal trace autoscaled to 0-40% looks like
            full throttle.
        zero_line: Draw a horizontal line at zero. For signed quantities, where
            the sign is the whole point.
        stretch: Relative vertical share of the stack.
    """

    key: str
    axis_label: str
    series: tuple[Series, ...] = ()
    y_range: tuple[float, float] | None = None
    zero_line: bool = False
    stretch: int = 2


ROW_SPEED = "speed"
ROW_PEDALS = "pedals"
ROW_STEERING = "steering"
ROW_GEAR = "gear"
ROW_RPM = "rpm"
ROW_DELTA = "delta"

#: The rows, in the order they are stacked. Speed first because it is what a
#: lap is read from; delta-t last because it is a conclusion drawn from
#: everything above it.
ROW_SPECS: tuple[RowSpec, ...] = (
    RowSpec(
        ROW_SPEED, strings.CHART_ROW_SPEED,
        (Series("Ground Speed", strings.CHART_SERIES_SPEED, 3.6, 1),),
        stretch=3,
    ),
    RowSpec(
        ROW_PEDALS, strings.CHART_ROW_PEDALS,
        (
            Series("Throttle Pos", strings.CHART_SERIES_THROTTLE, 100.0, 0,
                   theme.COLOUR_THROTTLE),
            Series("Brake Pos", strings.CHART_SERIES_BRAKE, 100.0, 0,
                   theme.COLOUR_BRAKE),
        ),
        # Pedals are bounded at 0 and 100% by construction. Autoscaling would
        # turn a lap that never used more than 40% brake into one that looks
        # like it locked the wheels at every corner.
        y_range=(-3.0, 103.0),
        stretch=2,
    ),
    RowSpec(
        ROW_STEERING, strings.CHART_ROW_STEERING,
        (Series("Steering Pos", strings.CHART_SERIES_STEERING, 100.0, 1),),
        zero_line=True, stretch=2,
    ),
    RowSpec(
        ROW_GEAR, strings.CHART_ROW_GEAR,
        (Series("Gear", strings.CHART_SERIES_GEAR, 1.0, 0),),
        stretch=1,
    ),
    RowSpec(
        ROW_RPM, strings.CHART_ROW_RPM,
        (Series("Engine RPM", strings.CHART_SERIES_RPM, 1.0, 0),),
        stretch=2,
    ),
    # No series: the delta is computed from two laps, not read from a channel.
    RowSpec(ROW_DELTA, strings.CHART_ROW_DELTA, (), zero_line=True, stretch=2),
)

#: Shown on opening. Speed and pedals answer most questions on their own, and a
#: stack of six rows on a laptop screen gives every one of them too little
#: height to read. The rest are one menu item away.
DEFAULT_ROWS: tuple[str, ...] = (ROW_SPEED, ROW_PEDALS, ROW_DELTA)


@dataclass(frozen=True, slots=True)
class LapTrace:
    """One lap, ready to draw.

    Attributes:
        label: What the legend calls it.
        grid_m: Distance grid, from the start of the lap.
        elapsed_s: Elapsed time on the same grid.
        channels: Channel name -> values on `grid_m`, in canonical units.
    """

    label: str
    grid_m: np.ndarray
    elapsed_s: np.ndarray
    channels: Mapping[str, np.ndarray]

    def x_for(self, mode: AxisMode) -> np.ndarray:
        return self.grid_m if mode is AxisMode.DISTANCE else self.elapsed_s

    def sample(self, channel: str, x: float, mode: AxisMode) -> float | None:
        """The value of one channel at an X position, snapped to a sample."""
        values = self.channels.get(channel)
        if values is None or not len(values):
            return None
        index = _nearest_index(self.x_for(mode), x)
        if index is None or index >= len(values):
            return None
        return float(values[index])


# --------------------------------------------------------------------------- #
# One row
# --------------------------------------------------------------------------- #

class _Row:
    """A single plot in the stack, with its curves and its cursor line."""

    def __init__(self, spec: RowSpec) -> None:
        self.spec = spec
        self.plot = pg.PlotWidget()
        self.plot.setBackground(theme.BACKGROUND)
        self.plot.showGrid(x=True, y=True, alpha=theme.GRID_ALPHA)
        self.plot.setLabel("left", spec.axis_label)
        self.plot.setMenuEnabled(False)
        # Y stays put and X is what the user explores. Letting Y pan too makes
        # a trace easy to lose off-screen, and there is no reason to want it:
        # every row's Y range is meaningful in itself.
        self.plot.setMouseEnabled(x=True, y=False)
        # Render only what is visible, decimated. A Le Mans lap is 13 600
        # points per curve and the stack holds up to ten curves at once.
        self.plot.setDownsampling(auto=True, mode="peak")
        self.plot.setClipToView(True)
        self.plot.getAxis("left").setWidth(theme.AXIS_WIDTH)

        # Every quantity here is read at its natural magnitude: 7000 rpm, 268
        # km/h, a delta of -0.51 s. pyqtgraph's automatic SI prefix would
        # relabel those "7 (x1000)" and "-510 (x0.001)", which is exactly the
        # extra arithmetic a driver comparing two laps does not need.
        for side in ("left", "bottom"):
            self.plot.getAxis(side).enableAutoSIPrefix(False)

        if spec.y_range is not None:
            self.plot.setYRange(*spec.y_range, padding=0.0)

        if spec.zero_line:
            self.plot.addItem(
                pg.InfiniteLine(
                    pos=0.0, angle=0, movable=False,
                    pen=pg.mkPen(theme.BORDER, width=1),
                ),
                ignoreBounds=True,
            )

        self.curves: dict[tuple[str, Role], pg.PlotDataItem] = {}
        for series in spec.series:
            for role in Role:
                self.curves[(series.channel, role)] = self.plot.plot(
                    pen=_pen(series, role)
                )

        # The delta row's three items: the losing and gaining fills, and the
        # curve itself drawn over them so the slope stays legible where the
        # fill is dense.
        self.delta_loss: pg.PlotDataItem | None = None
        self.delta_gain: pg.PlotDataItem | None = None
        self.delta_curve: pg.PlotDataItem | None = None
        if spec.key == ROW_DELTA:
            self.delta_loss = self.plot.plot(
                pen=None, fillLevel=0.0, brush=pg.mkBrush(*theme.FILL_LOSS)
            )
            self.delta_gain = self.plot.plot(
                pen=None, fillLevel=0.0, brush=pg.mkBrush(*theme.FILL_GAIN)
            )
            self.delta_curve = self.plot.plot(
                pen=pg.mkPen(theme.TEXT, width=1.4)
            )

        self.cursor = pg.InfiniteLine(
            angle=90, movable=False,
            pen=pg.mkPen(theme.TEXT_MUTED, width=1,
                         style=QtCore.Qt.PenStyle.DashLine),
        )
        self.cursor.setVisible(False)
        self.plot.addItem(self.cursor, ignoreBounds=True)

        #: Corner apexes and ideal-lap seams, rebuilt whenever they change.
        self.markers: list[pg.InfiniteLine] = []

    def clear_markers(self) -> None:
        for line in self.markers:
            self.plot.removeItem(line)
        self.markers = []

    def clear_curves(self) -> None:
        for curve in self.curves.values():
            curve.setData([], [])
        for item in (self.delta_loss, self.delta_gain, self.delta_curve):
            if item is not None:
                item.setData([], [])


def _pen(series: Series, role: Role) -> pg.mkPen:
    """The pen for one curve.

    Colour tells laps apart, except in a row that already spends colour telling
    *channels* apart. Throttle and brake must stay green and red - that reading
    is instant and universal - so on that row the second lap is dashed instead.
    Using colour for both at once would leave four curves no one can attribute.
    """
    if series.colour is not None:
        style = (QtCore.Qt.PenStyle.SolidLine if role is Role.PRIMARY
                 else QtCore.Qt.PenStyle.DashLine)
        return pg.mkPen(series.colour, width=1.4, style=style)

    colour = (theme.TRACE_REFERENCE if role is Role.PRIMARY
              else theme.TRACE_COMPARISON)
    return pg.mkPen(colour, width=1.6 if role is Role.PRIMARY else 1.3)


# --------------------------------------------------------------------------- #
# The stack
# --------------------------------------------------------------------------- #

class ChartStack(QtWidgets.QWidget):
    """Every row, sharing one X axis and one cursor."""

    #: Emitted as the cursor moves, carrying the **distance around the lap** in
    #: metres - not the raw X position. Distance is the coordinate the track map
    #: and the g-g diagram are indexed by, and it is well defined in both axis
    #: modes, so converting once here saves every listener from knowing which
    #: mode the stack happens to be in.
    cursor_moved = QtCore.Signal(float)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._axis_mode = AxisMode.DISTANCE
        self._primary: LapTrace | None = None
        self._benchmark: LapTrace | None = None
        self._delta_grid_m: np.ndarray | None = None
        self._delta_s: np.ndarray | None = None
        self._enabled_rows: set[str] = set(DEFAULT_ROWS)
        self._rows: dict[str, _Row] = {}
        self._corner_markers: list[tuple[float, str]] = []
        self._seam_markers: list[float] = []
        self._build()

    # -- construction ------------------------------------------------------

    def _build(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        header = QtWidgets.QHBoxLayout()
        header.setContentsMargins(8, 4, 8, 0)
        self.legend = QtWidgets.QLabel()
        self.legend.setTextFormat(QtCore.Qt.TextFormat.RichText)
        self.readout = QtWidgets.QLabel()
        self.readout.setTextFormat(QtCore.Qt.TextFormat.RichText)
        self.readout.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter
        )
        header.addWidget(self.legend, stretch=1)
        header.addWidget(self.readout, stretch=1)
        layout.addLayout(header)

        self.plots = QtWidgets.QWidget()
        self._plot_layout = QtWidgets.QVBoxLayout(self.plots)
        self._plot_layout.setContentsMargins(0, 0, 0, 0)
        self._plot_layout.setSpacing(1)

        anchor: _Row | None = None
        for spec in ROW_SPECS:
            row = _Row(spec)
            if anchor is None:
                anchor = row
            else:
                # Pan or zoom one row and every row follows. Without this the
                # stack is six unrelated charts that happen to sit together.
                row.plot.setXLink(anchor.plot)
            row.plot.scene().sigMouseMoved.connect(
                functools.partial(self._on_mouse_moved, row)
            )
            self._rows[spec.key] = row
            self._plot_layout.addWidget(row.plot, stretch=spec.stretch)

        self._anchor = anchor
        layout.addWidget(self.plots, stretch=1)

        self.placeholder = QtWidgets.QLabel(strings.CHART_NO_DATA)
        self.placeholder.setProperty("role", "placeholder")
        self.placeholder.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.placeholder, stretch=1)

        self._relayout()
        self.clear()

    # -- data --------------------------------------------------------------

    def show_laps(
        self,
        primary: LapTrace,
        benchmark: LapTrace | None = None,
        delta_grid_m: np.ndarray | None = None,
        delta_s: np.ndarray | None = None,
    ) -> None:
        """Draw one lap, optionally against a second.

        Args:
            primary: The lap the user selected.
            benchmark: The lap it is compared against, or None.
            delta_grid_m: Distance grid the delta was computed on.
            delta_s: `t_primary - t_benchmark` at each grid distance. Positive
                means the primary lap is behind.
        """
        self._primary = primary
        self._benchmark = benchmark
        self._delta_grid_m = (
            None if delta_grid_m is None else np.asarray(delta_grid_m, dtype=np.float64)
        )
        self._delta_s = (
            None if delta_s is None else np.asarray(delta_s, dtype=np.float64)
        )

        self.placeholder.hide()
        self.plots.show()
        self._redraw()
        self._relayout()
        self._update_legend()

    def clear(self) -> None:
        self._primary = None
        self._benchmark = None
        self._delta_grid_m = None
        self._delta_s = None
        self._corner_markers = []
        self._seam_markers = []
        for row in self._rows.values():
            row.clear_curves()
            row.clear_markers()
            row.cursor.setVisible(False)
        self.legend.clear()
        self.readout.clear()
        self.plots.hide()
        self.placeholder.show()

    @property
    def axis_mode(self) -> AxisMode:
        return self._axis_mode

    def set_axis_mode(self, mode: AxisMode) -> None:
        """Switch between the distance and time axes, keeping the data."""
        if mode is self._axis_mode:
            return
        self._axis_mode = mode
        self._redraw()
        self._relayout()

    # -- which rows are shown ----------------------------------------------

    def available_rows(self) -> set[str]:
        """Rows whose data the loaded lap actually carries.

        A session recorded without `Steering Pos` must not offer an empty
        steering plot: an empty axis reads as "the driver never steered".
        """
        available: set[str] = set()
        if self._primary is not None:
            for spec in ROW_SPECS:
                if any(s.channel in self._primary.channels for s in spec.series):
                    available.add(spec.key)
        if self._delta_s is not None and len(self._delta_s):
            available.add(ROW_DELTA)
        return available

    def set_row_enabled(self, key: str, enabled: bool) -> None:
        """Turn a row on or off. It still only appears if its data exists."""
        if enabled:
            self._enabled_rows.add(key)
        else:
            self._enabled_rows.discard(key)
        self._relayout()

    def is_row_enabled(self, key: str) -> bool:
        return key in self._enabled_rows

    def visible_rows(self) -> list[str]:
        """The rows actually on screen, top to bottom."""
        available = self.available_rows()
        return [
            spec.key for spec in ROW_SPECS
            if spec.key in self._enabled_rows and spec.key in available
        ]

    # -- drawing -----------------------------------------------------------

    def _redraw(self) -> None:
        for spec in ROW_SPECS:
            row = self._rows[spec.key]
            if spec.key == ROW_DELTA:
                self._redraw_delta(row)
                continue
            for series in spec.series:
                self._set_curve(row, series, Role.PRIMARY, self._primary)
                self._set_curve(row, series, Role.BENCHMARK, self._benchmark)
            if spec.y_range is None:
                row.plot.enableAutoRange(axis="y")

        if self._anchor is not None and self._primary is not None:
            x = self._primary.x_for(self._axis_mode)
            if len(x):
                self._anchor.plot.setXRange(float(x[0]), float(x[-1]), padding=0.01)

    def _set_curve(
        self, row: _Row, series: Series, role: Role, trace: LapTrace | None
    ) -> None:
        curve = row.curves[(series.channel, role)]
        values = None if trace is None else trace.channels.get(series.channel)
        if trace is None or values is None or not len(values):
            curve.setData([], [])
            return
        curve.setData(trace.x_for(self._axis_mode), np.asarray(values) * series.scale)

    def _redraw_delta(self, row: _Row) -> None:
        """The delta row: two fills either side of zero, and the curve on top."""
        drawable = (
            self._delta_s is not None
            and self._delta_grid_m is not None
            and len(self._delta_s) > 1
            and self._axis_mode is AxisMode.DISTANCE
        )
        if not drawable:
            row.clear_curves()
            return

        grid, delta = self._delta_grid_m, self._delta_s
        # Split at zero rather than filling the whole curve one colour: the
        # sign is the difference between losing and gaining time, and a single
        # brush would make a lap that gains 0.4 s look exactly like one that
        # loses it.
        row.delta_loss.setData(grid, np.where(delta > 0.0, delta, 0.0))
        row.delta_gain.setData(grid, np.where(delta < 0.0, delta, 0.0))
        row.delta_curve.setData(grid, delta)
        row.plot.enableAutoRange(axis="y")

    def _relayout(self) -> None:
        """Show the enabled rows, and put the X axis under the last of them."""
        visible = self.visible_rows()
        for spec in ROW_SPECS:
            row = self._rows[spec.key]
            row.plot.setVisible(spec.key in visible)

        label = (strings.CHART_AXIS_DISTANCE if self._axis_mode is AxisMode.DISTANCE
                 else strings.CHART_AXIS_TIME)
        for position, key in enumerate(visible):
            row = self._rows[key]
            is_last = position == len(visible) - 1
            # Only the bottom row spells out the X axis. Repeating the same
            # numbers under every plot costs the height the traces need and
            # tells the reader nothing new - the axes are linked.
            row.plot.getAxis("bottom").setStyle(showValues=is_last)
            row.plot.setLabel("bottom", label if is_last else "")

        # Which row carries the marker labels depends on which rows are shown,
        # and the markers themselves only exist on the distance axis.
        self._rebuild_markers()

    # -- markers -----------------------------------------------------------

    def set_corner_markers(self, distances_m, labels) -> None:
        """Draw a faint line at each corner's apex, labelled on the top row.

        Without them, reading a trace means converting metres into corners in
        your head. The lines are deliberately dim: they are a coordinate
        system, not data, and must never be mistaken for the traces.
        """
        self._corner_markers = list(zip(distances_m, labels, strict=True))
        self._rebuild_markers()

    def set_seam_markers(self, distances_m) -> None:
        """Mark where the ideal lap is stitched from a different lap.

        These are the evidence that the target is synthetic, so they are drawn
        rather than smoothed away.
        """
        self._seam_markers = list(distances_m)
        self._rebuild_markers()

    def _rebuild_markers(self) -> None:
        top = self.visible_rows()[0] if self.visible_rows() else None

        for key, row in self._rows.items():
            row.clear_markers()
            if self._axis_mode is not AxisMode.DISTANCE or self._primary is None:
                continue

            for distance, label in self._corner_markers:
                line = pg.InfiniteLine(
                    pos=float(distance), angle=90, movable=False,
                    pen=pg.mkPen(theme.BORDER, width=1,
                                 style=QtCore.Qt.PenStyle.DotLine),
                    label=label if key == top else None,
                    labelOpts={"position": 0.04, "color": theme.TEXT_DISABLED,
                               "movable": False},
                )
                row.plot.addItem(line, ignoreBounds=True)
                row.markers.append(line)

            for distance in self._seam_markers:
                line = pg.InfiniteLine(
                    pos=float(distance), angle=90, movable=False,
                    pen=pg.mkPen(theme.WARNING, width=1,
                                 style=QtCore.Qt.PenStyle.DashLine),
                )
                row.plot.addItem(line, ignoreBounds=True)
                row.markers.append(line)

    def zoom_to(self, start_m: float, end_m: float, margin_fraction: float = 0.3) -> None:
        """Frame one stretch of the lap, with room either side.

        The margin is what makes the view useful: a corner shown edge to edge
        hides the braking that set it up and the exit that pays for it.
        """
        if self._anchor is None or self._primary is None or end_m <= start_m:
            return
        margin = (end_m - start_m) * margin_fraction
        if self._axis_mode is AxisMode.DISTANCE:
            self._anchor.plot.setXRange(start_m - margin, end_m + margin,
                                        padding=0.0)
            return
        elapsed = self._primary.elapsed_s
        grid = self._primary.grid_m
        low = float(np.interp(start_m - margin, grid, elapsed))
        high = float(np.interp(end_m + margin, grid, elapsed))
        self._anchor.plot.setXRange(low, high, padding=0.0)

    # -- legend and cursor -------------------------------------------------

    def _update_legend(self) -> None:
        if self._primary is None:
            self.legend.clear()
            return
        parts = [_coloured(self._primary.label, theme.TRACE_REFERENCE)]
        parts.append(
            _coloured(self._benchmark.label, theme.TRACE_COMPARISON)
            if self._benchmark is not None
            else _coloured(strings.CHART_LEGEND_NO_BENCHMARK, theme.TEXT_DISABLED)
        )
        self.legend.setText(strings.CHART_READOUT_SEPARATOR.join(parts))

    def _on_mouse_moved(self, row: _Row, position) -> None:
        if self._primary is None or not row.plot.isVisible():
            return
        if not row.plot.sceneBoundingRect().contains(position):
            self._hide_cursor()
            return

        x = float(row.plot.plotItem.vb.mapSceneToView(position).x())
        index = _nearest_index(self._primary.x_for(self._axis_mode), x)
        if index is None:
            return

        self._place_cursor(index)
        self.cursor_moved.emit(float(self._primary.grid_m[index]))

    def set_cursor_distance(self, distance_m: float) -> None:
        """Move the cursor to a distance around the lap, without re-emitting.

        Called when something else - the track map - drives the cursor. Staying
        silent is what keeps the two panels from bouncing the signal between
        them forever.
        """
        if self._primary is None:
            return
        index = _nearest_index(self._primary.grid_m, distance_m)
        if index is not None:
            self._place_cursor(index)

    def _place_cursor(self, index: int) -> None:
        x = float(self._primary.x_for(self._axis_mode)[index])
        for row in self._rows.values():
            row.cursor.setPos(x)
            row.cursor.setVisible(row.plot.isVisible())
        self.readout.setText(self._readout_text(x))

    def _hide_cursor(self) -> None:
        for row in self._rows.values():
            row.cursor.setVisible(False)
        self.readout.clear()

    def _readout_text(self, x: float) -> str:
        """Every visible channel's value at the cursor, both laps side by side."""
        if self._primary is None:
            return ""

        parts = [
            strings.CHART_READOUT_DISTANCE.format(distance=x)
            if self._axis_mode is AxisMode.DISTANCE
            else strings.CHART_READOUT_TIME.format(time=x)
        ]

        for key in self.visible_rows():
            spec = next(s for s in ROW_SPECS if s.key == key)
            if key == ROW_DELTA:
                parts.append(self._delta_readout(x))
                continue
            for series in spec.series:
                parts.append(self._series_readout(series, x))

        return strings.CHART_READOUT_SEPARATOR.join(p for p in parts if p)

    def _series_readout(self, series: Series, x: float) -> str:
        primary = self._primary.sample(series.channel, x, self._axis_mode)
        if primary is None:
            return ""
        text = _coloured(
            format_value(primary * series.scale, series.decimals),
            series.colour or theme.TRACE_REFERENCE,
        )
        if self._benchmark is not None:
            other = self._benchmark.sample(series.channel, x, self._axis_mode)
            if other is not None:
                # A readout has no line style to spend, so where the plot tells
                # the two laps apart by dashing it italicises here instead.
                # Without this, "acel 0/0" is two green numbers with nothing
                # saying which lap either belongs to.
                text += "/" + _coloured(
                    format_value(other * series.scale, series.decimals),
                    series.colour or theme.TRACE_COMPARISON,
                    italic=series.colour is not None,
                )
        return f"{series.label} {text}"

    def _delta_readout(self, x: float) -> str:
        if self._delta_s is None or self._delta_grid_m is None:
            return ""
        if not len(self._delta_s):
            return ""
        index = _nearest_index(self._delta_grid_m, x)
        if index is None:
            return ""
        value = float(self._delta_s[index])
        colour = theme.COLOUR_BRAKE if value > 0 else theme.COLOUR_THROTTLE
        return f"{strings.CHART_SERIES_DELTA} {_coloured(f'{value:+.3f}', colour)}"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _nearest_index(x_values: np.ndarray, x: float) -> int | None:
    """Index of the sample closest to `x`, or None when there are none.

    `searchsorted` gives the insertion point, which is the sample *after* x;
    the one before is as often the nearer of the two, and on a 1 m grid taking
    the wrong one puts the readout a metre from the cursor.
    """
    if x_values is None or not len(x_values):
        return None
    after = int(np.searchsorted(x_values, x))
    if after <= 0:
        return 0
    if after >= len(x_values):
        return len(x_values) - 1
    before = after - 1
    return before if abs(x_values[before] - x) <= abs(x_values[after] - x) else after


def _coloured(text: str, colour: str, *, italic: bool = False) -> str:
    style = f"color:{colour}" + (";font-style:italic" if italic else "")
    return f'<span style="{style}">{text}</span>'
