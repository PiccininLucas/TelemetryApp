"""Stacked traces sharing one X axis, with a delta-t row.

This is the instrument a lap is actually read on: speed, pedals, steering, gear
and engine speed stacked vertically, all sharing one X axis, plus the delta-t
against a reference lap at the bottom.

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
zero so the eye follows the slope rather than the level - and it is the only
filled row, the one emphasis on the screen.

Above the rows: the key (each lap's line, drawn as it is drawn below - the
comparison is dashed everywhere, so colour is never the only cue), the channel
chips that switch rows on and off, and a readout of every visible channel under
the cursor, in cells that hold still while the numbers change.

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
from PySide6 import QtCore, QtGui, QtWidgets

from lmu_telemetry.presentation import plotting, theme
from lmu_telemetry.presentation.chart_widgets import LineKey, LineStyle, ReadoutCell
from lmu_telemetry.shared import strings
from lmu_telemetry.shared.formatting import format_value


class AxisMode(str, Enum):
    """What the X axis measures."""

    #: Distance around the lap. The only mode in which two laps can be
    #: meaningfully compared, and therefore the default.
    DISTANCE = "distance"
    #: Time since the lap started. Useful for reading a single lap's rhythm.
    TIME = "time"


class Role(str, Enum):
    """Which of the two laps a curve belongs to."""

    #: The lap the user selected. Solid, slightly thicker.
    PRIMARY = "primary"
    #: The lap it is being compared against. Dashed, in every row.
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
        label: Caption for the cursor readout, with the unit.
        scale: Multiplier from canonical units to display units. Speed is held
            in m/s and shown in km/h; pedals are held as a 0-1 fraction and
            shown as a percentage. The conversion lives here, at the edge, so
            nothing upstream ever has to remember which unit it is holding.
        decimals: Digits after the point in the readout.
        series: A key of `theme.SERIES_COLOURS` when the row uses colour to tell
            *channels* apart (throttle green, brake red) rather than laps. None
            means the curve takes its lap's colour.
        widest: The widest figure the readout can show, which sizes its cell.
    """

    channel: str
    label: str
    scale: float = 1.0
    decimals: int = 0
    series: str | None = None
    widest: str = "-000.0"


@dataclass(frozen=True, slots=True)
class RowSpec:
    """One stacked plot.

    Attributes:
        key: Stable identifier, used by the commands that toggle rows.
        axis_label: Left-axis title, carrying the unit.
        chip: Short name on the channel chip.
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
    chip: str
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
        ROW_SPEED, strings.CHART_ROW_SPEED, strings.CHART_CHIP_SPEED,
        (Series("Ground Speed", strings.CHART_SERIES_SPEED, 3.6, 1, widest="000.0"),),
        stretch=3,
    ),
    RowSpec(
        ROW_PEDALS, strings.CHART_ROW_PEDALS, strings.CHART_CHIP_PEDALS,
        (
            Series("Throttle Pos", strings.CHART_SERIES_THROTTLE, 100.0, 0,
                   "throttle", widest="000"),
            Series("Brake Pos", strings.CHART_SERIES_BRAKE, 100.0, 0,
                   "brake", widest="000"),
        ),
        # Pedals are bounded at 0 and 100% by construction. Autoscaling would
        # turn a lap that never used more than 40% brake into one that looks
        # like it locked the wheels at every corner.
        y_range=(-3.0, 103.0),
        stretch=2,
    ),
    RowSpec(
        ROW_STEERING, strings.CHART_ROW_STEERING, strings.CHART_CHIP_STEERING,
        (Series("Steering Pos", strings.CHART_SERIES_STEERING, 100.0, 1),),
        zero_line=True, stretch=2,
    ),
    RowSpec(
        ROW_GEAR, strings.CHART_ROW_GEAR, strings.CHART_CHIP_GEAR,
        (Series("Gear", strings.CHART_SERIES_GEAR, 1.0, 0, widest="0"),),
        stretch=1,
    ),
    RowSpec(
        ROW_RPM, strings.CHART_ROW_RPM, strings.CHART_CHIP_RPM,
        (Series("Engine RPM", strings.CHART_SERIES_RPM, 1.0, 0, widest="00000"),),
        stretch=2,
    ),
    # No series: the delta is computed from two laps, not read from a channel.
    RowSpec(ROW_DELTA, strings.CHART_ROW_DELTA, strings.CHART_CHIP_DELTA, (),
            zero_line=True, stretch=2),
)

#: Shown on opening. Speed and pedals answer most questions on their own, and a
#: stack of six rows on a laptop screen gives every one of them too little
#: height to read. The rest are one chip away.
DEFAULT_ROWS: tuple[str, ...] = (ROW_SPEED, ROW_PEDALS, ROW_DELTA)

#: Readout cell keys that are not channels.
CELL_POSITION = "position"
CELL_DELTA = "delta"


@dataclass(frozen=True, slots=True)
class LapTrace:
    """One lap, ready to draw.

    Attributes:
        label: The full name - lap, time, gap - for the key's tooltip and for
            exports.
        grid_m: Distance grid, from the start of the lap.
        elapsed_s: Elapsed time on the same grid.
        channels: Channel name -> values on `grid_m`, in canonical units.
        key: The short name beside its line in the key ("Volta 5"); the
            times are in the session header already. Empty means `label`.
    """

    label: str
    grid_m: np.ndarray
    elapsed_s: np.ndarray
    channels: Mapping[str, np.ndarray]
    key: str = ""

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


def line_style(series: Series | None, role: Role) -> LineStyle:
    """How a curve is drawn.

    Colour tells the laps apart, and so does the line: the comparison is
    dashed in every row, so a reader who cannot tell blue from orange can
    still tell the laps apart. On the pedal row colour already tells
    *channels* apart - throttle green, brake red, a reading that is instant and
    universal - so there the dash is the only thing that tells the laps apart.
    """
    dashed = role is Role.BENCHMARK
    if series is not None and series.series is not None:
        return LineStyle(theme.SERIES_COLOURS[series.series], 1.4, dashed)
    colour = theme.TRACE_REFERENCE if role is Role.PRIMARY else theme.TRACE_COMPARISON
    return LineStyle(colour, 1.6 if role is Role.PRIMARY else 1.3, dashed)


def _pen(series: Series, role: Role) -> QtGui.QPen:
    return line_style(series, role).pen()


# --------------------------------------------------------------------------- #
# One row
# --------------------------------------------------------------------------- #

class _Row:
    """A single plot in the stack, with its curves and its cursor line."""

    def __init__(self, spec: RowSpec) -> None:
        self.spec = spec
        self.plot = plotting.make_plot(left=spec.axis_label)
        # Y stays put and X is what the user explores. Letting Y pan too makes
        # a trace easy to lose off-screen, and there is no reason to want it:
        # every row's Y range is meaningful in itself.
        self.plot.setMouseEnabled(x=True, y=False)
        # Render only what is visible, decimated. A Le Mans lap is 13 600
        # points per curve and the stack holds up to ten curves at once.
        self.plot.setDownsampling(auto=True, mode="peak")
        self.plot.setClipToView(True)
        self.plot.getAxis("left").setWidth(theme.AXIS_WIDTH)

        if spec.y_range is not None:
            self.plot.setYRange(*spec.y_range, padding=0.0)

        if spec.zero_line:
            self.plot.addItem(
                pg.InfiniteLine(pos=0.0, angle=0, movable=False,
                                pen=pg.mkPen(theme.BORDER, width=1)),
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
                pen=None, fillLevel=0.0, brush=pg.mkBrush(*theme.FILL_LOSS))
            self.delta_gain = self.plot.plot(
                pen=None, fillLevel=0.0, brush=pg.mkBrush(*theme.FILL_GAIN))
            self.delta_curve = self.plot.plot(pen=pg.mkPen(theme.TEXT, width=1.4))

        # Everything above stays still while the cursor moves: cached, so a
        # mouse move repaints a strip of pixels rather than every curve.
        plotting.freeze(*self.curves.values())
        plotting.freeze(*(item for item in (self.delta_loss, self.delta_gain,
                                            self.delta_curve) if item is not None))
        plotting.freeze_axes(self.plot)

        self.cursor = pg.InfiniteLine(
            angle=90, movable=False,
            pen=pg.mkPen(theme.TEXT_MUTED, width=1, style=QtCore.Qt.PenStyle.DashLine),
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
        self.channel_chips: dict[str, QtWidgets.QToolButton] = {}
        self._build()

    # -- construction ------------------------------------------------------

    def _build(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        # The key, the chips and the readout sit in a strip that scrolls
        # sideways when the window is narrow, as the session header does:
        # nine readout cells and six chips must not set the window's minimum
        # width.
        self._chrome = QtWidgets.QWidget()
        self._chrome.setObjectName("chart_chrome_content")
        chrome_layout = QtWidgets.QVBoxLayout(self._chrome)
        chrome_layout.setContentsMargins(0, 0, 0, 0)
        chrome_layout.setSpacing(0)
        self.chrome = QtWidgets.QScrollArea()
        self.chrome.setObjectName("chart_chrome")
        self.chrome.setWidget(self._chrome)
        self.chrome.setWidgetResizable(True)
        self.chrome.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.chrome.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.chrome.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.chrome.setMinimumWidth(120)
        self.chrome.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored,
                                  QtWidgets.QSizePolicy.Policy.Fixed)
        layout.addWidget(self.chrome)

        # The key and the channel chips.
        top = QtWidgets.QHBoxLayout()
        top.setContentsMargins(10, 6, 8, 0)
        top.setSpacing(16)
        self.primary_key = LineKey(line_style(None, Role.PRIMARY))
        self.benchmark_key = LineKey(line_style(None, Role.BENCHMARK))
        top.addWidget(self.primary_key)
        top.addWidget(self.benchmark_key)
        top.addStretch(1)
        self.chip_bar = QtWidgets.QHBoxLayout()
        self.chip_bar.setSpacing(4)
        chips = QtWidgets.QWidget()
        chips.setLayout(self.chip_bar)
        chips.setAccessibleName(strings.CHART_CHANNELS_NAME)
        self.chip_bar.setContentsMargins(0, 0, 0, 0)
        top.addWidget(chips)
        chrome_layout.addLayout(top)

        # The readout: one cell per quantity, all present from the start so
        # the row never changes height or order as the cursor comes and goes.
        self.readout = QtWidgets.QWidget()
        self.readout.setAccessibleName(strings.CHART_READOUT_NAME)
        readout_layout = QtWidgets.QHBoxLayout(self.readout)
        readout_layout.setContentsMargins(10, 2, 8, 4)
        readout_layout.setSpacing(18)
        self.readout_cells: dict[str, ReadoutCell] = {
            CELL_POSITION: ReadoutCell(strings.CHART_READOUT_POSITION, widest="00000"),
        }
        for spec in ROW_SPECS:
            for series in spec.series:
                self.readout_cells[series.channel] = ReadoutCell(series.label, series.widest)
        self.readout_cells[CELL_DELTA] = ReadoutCell(strings.CHART_SERIES_DELTA, "+00.000")
        for cell in self.readout_cells.values():
            readout_layout.addWidget(cell)
        readout_layout.addStretch(1)
        chrome_layout.addWidget(self.readout)

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

    def set_channel_actions(self, actions: Mapping[str, QtGui.QAction]) -> None:
        """Show the row toggles as chips above the traces.

        The chips are the window's own actions - the same ones the View menu
        lists - so a chip and its menu entry are one switch, checked and
        enabled together, and a row the lap has no data for is greyed in both.
        """
        for key, action in actions.items():
            spec = next((s for s in ROW_SPECS if s.key == key), None)
            if spec is None or key in self.channel_chips:
                continue
            chip = QtWidgets.QToolButton()
            chip.setDefaultAction(action)
            chip.setProperty("role", "chip")
            chip.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextOnly)
            action.setIconText(spec.chip)
            chip.setToolTip(spec.axis_label)
            chip.setFocusPolicy(QtCore.Qt.FocusPolicy.TabFocus)
            self.chip_bar.addWidget(chip)
            self.channel_chips[key] = chip

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)
        # Widths come from the polished font, which only exists once shown.
        for cell in self.readout_cells.values():
            cell.ensure_width()
        self._fit_chrome()

    def _fit_chrome(self) -> None:
        """As tall as the key, chips and readout, plus a scroll bar's room."""
        bar = self.chrome.horizontalScrollBar().sizeHint().height()
        self.chrome.setFixedHeight(self._chrome.sizeHint().height() + bar)

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
        self._delta_s = None if delta_s is None else np.asarray(delta_s, dtype=np.float64)

        self.placeholder.hide()
        self.plots.show()
        self.readout.show()
        self.chrome.show()
        self._redraw()
        self._relayout()
        self._update_legend()
        self._hide_cursor()

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
        self.primary_key.hide()
        self.benchmark_key.hide()
        self.readout.hide()
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
                _fit_y(row, [
                    np.asarray(values) * series.scale
                    for series in spec.series
                    for trace in (self._primary, self._benchmark)
                    if trace is not None
                    and (values := trace.channels.get(series.channel)) is not None
                ])

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
        # Zero is always in view: the delta is read against it.
        _fit_y(row, [delta, np.zeros(1)])

    def _relayout(self) -> None:
        """Show the enabled rows, and put the X axis under the last of them."""
        visible = self.visible_rows()
        for spec in ROW_SPECS:
            self._rows[spec.key].plot.setVisible(spec.key in visible)

        label = (strings.CHART_AXIS_DISTANCE if self._axis_mode is AxisMode.DISTANCE
                 else strings.CHART_AXIS_TIME)
        for position, key in enumerate(visible):
            row = self._rows[key]
            is_last = position == len(visible) - 1
            # Only the bottom row spells out the X axis. Repeating the same
            # numbers under every plot costs the height the traces need and
            # tells the reader nothing new - the axes are linked.
            row.plot.getAxis("bottom").setStyle(showValues=is_last)
            plotting.set_label(row.plot, "bottom", label if is_last else "")

        self._sync_readout_cells(visible)
        # Which row carries the marker labels depends on which rows are shown,
        # and the markers themselves only exist on the distance axis.
        self._rebuild_markers()

    def _sync_readout_cells(self, visible: list[str]) -> None:
        shown = {CELL_POSITION}
        for spec in ROW_SPECS:
            if spec.key in visible:
                shown.update(series.channel for series in spec.series)
        if ROW_DELTA in visible:
            shown.add(CELL_DELTA)
        for key, cell in self.readout_cells.items():
            cell.setVisible(key in shown)
        self.readout_cells[CELL_POSITION].caption.setText(
            strings.CHART_READOUT_POSITION if self._axis_mode is AxisMode.DISTANCE
            else strings.CHART_READOUT_ELAPSED
        )

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
        visible = self.visible_rows()
        top = visible[0] if visible else None
        label_font = theme.font(theme.TYPE.micro)

        for key, row in self._rows.items():
            row.clear_markers()
            if self._axis_mode is not AxisMode.DISTANCE or self._primary is None:
                continue

            for distance, label in self._corner_markers:
                line = pg.InfiniteLine(
                    pos=float(distance), angle=90, movable=False,
                    pen=pg.mkPen(theme.BORDER, width=1, style=QtCore.Qt.PenStyle.DotLine),
                    label=label if key == top else None,
                    labelOpts={"position": 0.04, "color": theme.TEXT_DISABLED,
                               "movable": False},
                )
                if getattr(line, "label", None) is not None:
                    line.label.setFont(label_font)
                row.plot.addItem(line, ignoreBounds=True)
                row.markers.append(line)

            for distance in self._seam_markers:
                line = pg.InfiniteLine(
                    pos=float(distance), angle=90, movable=False,
                    pen=pg.mkPen(theme.WARNING, width=1, style=QtCore.Qt.PenStyle.DashLine),
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
            self._anchor.plot.setXRange(start_m - margin, end_m + margin, padding=0.0)
            return
        elapsed = self._primary.elapsed_s
        grid = self._primary.grid_m
        low = float(np.interp(start_m - margin, grid, elapsed))
        high = float(np.interp(end_m + margin, grid, elapsed))
        self._anchor.plot.setXRange(low, high, padding=0.0)

    # -- key and cursor ----------------------------------------------------

    def _update_legend(self) -> None:
        if self._primary is None:
            self.primary_key.hide()
            self.benchmark_key.hide()
            return
        self.primary_key.set(line_style(None, Role.PRIMARY),
                             self._primary.key or self._primary.label)
        self.primary_key.setToolTip(self._primary.label)
        self.primary_key.show()
        if self._benchmark is not None:
            self.benchmark_key.set(line_style(None, Role.BENCHMARK),
                                   self._benchmark.key or self._benchmark.label)
            self.benchmark_key.setToolTip(self._benchmark.label)
            self.benchmark_key.label.setProperty("role", "")
        else:
            self.benchmark_key.set(LineStyle(theme.TEXT_DISABLED, 1.3, True),
                                   strings.CHART_LEGEND_NO_BENCHMARK)
            self.benchmark_key.setToolTip("")
            self.benchmark_key.label.setProperty("role", "placeholder")
        self.benchmark_key.label.style().unpolish(self.benchmark_key.label)
        self.benchmark_key.label.style().polish(self.benchmark_key.label)
        self.benchmark_key.show()

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
        self._show_readout(x)

    def _hide_cursor(self) -> None:
        for row in self._rows.values():
            row.cursor.setVisible(False)
        for cell in self.readout_cells.values():
            cell.show_values(None)

    def readout_at(self, x: float) -> dict[str, tuple[str, str | None]]:
        """Every readout figure at an X position: cell key -> (this lap, the
        comparison or None). Only the cells of visible rows."""
        values: dict[str, tuple[str, str | None]] = {}
        if self._primary is None:
            return values
        values[CELL_POSITION] = (
            f"{x:.0f}" if self._axis_mode is AxisMode.DISTANCE else f"{x:.2f}", None
        )
        for key in self.visible_rows():
            if key == ROW_DELTA:
                delta = self._delta_at(x)
                if delta is not None:
                    values[CELL_DELTA] = (f"{delta:+.3f}", None)
                continue
            spec = next(s for s in ROW_SPECS if s.key == key)
            for series in spec.series:
                primary = self._primary.sample(series.channel, x, self._axis_mode)
                if primary is None:
                    continue
                other = (None if self._benchmark is None
                         else self._benchmark.sample(series.channel, x, self._axis_mode))
                values[series.channel] = (
                    format_value(primary * series.scale, series.decimals),
                    None if other is None
                    else format_value(other * series.scale, series.decimals),
                )
        return values

    def _show_readout(self, x: float) -> None:
        values = self.readout_at(x)
        series_of = {s.channel: s for spec in ROW_SPECS for s in spec.series}
        for key, cell in self.readout_cells.items():
            if not cell.isVisibleTo(self.readout):
                continue
            primary, other = values.get(key, (None, None))
            if key == CELL_DELTA:
                delta = self._delta_at(x)
                cell.show_values(primary, tone=theme.verdict(delta, higher_is_better=False))
                continue
            series = series_of.get(key)
            colour_key = None if series is None else series.series
            cell.show_values(
                primary, other,
                primary_series=None if series is None else (colour_key or "primary"),
                comparison_series=colour_key or "comparison",
                # The readout has no line to dash: the comparison's figure is
                # set in italic, the same cue in type.
                comparison_italic=True,
            )

    def _delta_at(self, x: float) -> float | None:
        if self._delta_s is None or self._delta_grid_m is None or not len(self._delta_s):
            return None
        index = _nearest_index(self._delta_grid_m, x)
        return None if index is None else float(self._delta_s[index])


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _fit_y(row: _Row, arrays: list[np.ndarray]) -> None:
    """Set a row's Y range to its data, once, instead of leaving it on
    pyqtgraph's auto-range.

    The result is the same - auto-range also spans all the data, and Y never
    pans - but auto-range is recomputed on every paint and re-applies the
    range, which throws away the cached curves: a mouse move then repainted
    every curve of every autoscaled row (~90 ms on a Le Mans lap, against
    ~2 ms with the range set here). See `plotting.freeze`.
    """
    finite = [a[np.isfinite(a)] for a in arrays if a is not None and len(a)]
    finite = [a for a in finite if a.size]
    if not finite:
        return
    low = float(min(a.min() for a in finite))
    high = float(max(a.max() for a in finite))
    if high - low < 1e-9:
        low, high = low - 1.0, high + 1.0
    row.plot.disableAutoRange(axis="y")
    row.plot.setYRange(low, high, padding=0.05)


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
