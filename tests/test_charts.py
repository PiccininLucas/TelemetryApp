"""Etapa 4: the plot foundation, the line key, the readout and the chips.

The older chart behaviour - shared X axis, units, the delta split at zero - is
tested in test_ui.py; these cover what the charts now look like and how they
are read.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

from lmu_telemetry.presentation import plotting, theme  # noqa: E402
from lmu_telemetry.presentation.chart_panel import (  # noqa: E402
    CELL_DELTA, CELL_POSITION, ROW_DELTA, ROW_GEAR, ROW_PEDALS, ROW_SPECS, ROW_SPEED,
    AxisMode, ChartStack, LapTrace, Role, line_style,
)
from lmu_telemetry.presentation.chart_widgets import (  # noqa: E402
    LineKey, LineStyle, ReadoutCell,
)
from lmu_telemetry.shared import strings  # noqa: E402

CACHED = QtWidgets.QGraphicsItem.CacheMode.DeviceCoordinateCache


@pytest.fixture(scope="module")
def qt_app():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    theme.apply(app)
    yield app


def _trace(label="Volta 1", n=200, speed_ms=50.0):
    grid = np.arange(float(n))
    return LapTrace(label=label, grid_m=grid, elapsed_s=grid / speed_ms, channels={
        "Ground Speed": np.full_like(grid, speed_ms),
        "Throttle Pos": np.full_like(grid, 0.8),
        "Brake Pos": np.zeros_like(grid),
        "Steering Pos": np.zeros_like(grid),
        "Gear": np.full_like(grid, 5.0),
        "Engine RPM": np.full_like(grid, 7000.0),
    })


@pytest.fixture
def compared(qt_app):
    chart = ChartStack()
    grid = np.arange(200.0)
    chart.show_laps(_trace("Volta 2", speed_ms=40.0), _trace("Volta 1", speed_ms=50.0),
                    delta_grid_m=grid, delta_s=grid * 0.001)
    chart.resize(900, 600)
    chart.show()
    yield chart
    chart.close()


# --- the foundation ---------------------------------------------------------------


def test_every_axis_is_quiet_and_themed(qt_app):
    plot = plotting.make_plot(left="Velocidade (km/h)", bottom="Distância (m)")
    for side in ("left", "bottom"):
        axis = plot.getAxis(side)
        assert axis.pen().color().name() == theme.BORDER
        assert axis.textPen().color().name() == theme.TEXT_MUTED
        assert axis.style["tickLength"] == 0
        assert axis.autoSIPrefix is False
    assert plot.getAxis("left").labelText == "Velocidade (km/h)"


def test_a_picture_plot_has_no_axes(qt_app):
    plot = plotting.make_plot(axes=False)
    assert not plot.getAxis("left").isVisible()
    assert not plot.getAxis("bottom").isVisible()


def test_tick_labels_use_the_caption_step(qt_app):
    assert plotting.tick_font().pixelSize() == theme.TYPE.caption


def test_curves_and_axes_are_cached_but_the_cursor_is_not(qt_app):
    """Moving the cursor must repaint pixels already drawn, not every curve."""
    chart = ChartStack()
    row = chart._rows[ROW_SPEED]
    assert all(curve.curve.cacheMode() == CACHED for curve in row.curves.values())
    assert row.plot.getAxis("left").cacheMode() == CACHED
    assert row.cursor.cacheMode() != CACHED


def test_caching_does_not_change_a_pixel(qt_app):
    """The cache is a speed-up, not a different picture."""
    chart = ChartStack()
    chart.resize(700, 500)
    chart.show_laps(_trace(n=2000, speed_ms=45.0), _trace("Volta 1", n=2000))
    chart.show()
    QtWidgets.QApplication.processEvents()
    cached = chart.plots.grab().toImage()

    for row in chart._rows.values():
        for item in row.plot.plotItem.listDataItems():
            item.curve.setCacheMode(QtWidgets.QGraphicsItem.CacheMode.NoCache)
        for side in ("left", "bottom"):
            row.plot.getAxis(side).setCacheMode(QtWidgets.QGraphicsItem.CacheMode.NoCache)
    QtWidgets.QApplication.processEvents()
    assert chart.plots.grab().toImage() == cached
    chart.close()


# --- colour is never the only cue -------------------------------------------------


@pytest.mark.parametrize("spec", [s for s in ROW_SPECS if s.series], ids=lambda s: s.key)
def test_the_comparison_is_dashed_in_every_row(qt_app, spec):
    chart = ChartStack()
    row = chart._rows[spec.key]
    for series in spec.series:
        primary = row.curves[(series.channel, Role.PRIMARY)].opts["pen"]
        benchmark = row.curves[(series.channel, Role.BENCHMARK)].opts["pen"]
        assert primary.style() == QtCore.Qt.PenStyle.SolidLine
        assert benchmark.style() == QtCore.Qt.PenStyle.DashLine


def test_the_key_draws_each_lap_as_it_is_drawn(compared):
    assert not compared.primary_key.swatch.line_style.dashed
    assert compared.benchmark_key.swatch.line_style.dashed
    assert compared.primary_key.label.text() == "Volta 2"
    assert compared.benchmark_key.label.text() == "Volta 1"


def test_without_a_comparison_the_key_says_so(qt_app):
    chart = ChartStack()
    chart.show_laps(_trace())
    assert chart.benchmark_key.label.text() == strings.CHART_LEGEND_NO_BENCHMARK
    assert chart.benchmark_key.swatch.line_style.colour == theme.TEXT_DISABLED


def test_the_comparison_figure_is_italic_in_the_readout(compared):
    """The readout has no line to dash, so the same cue is set in type."""
    compared.set_cursor_distance(100.0)
    cell = compared.readout_cells["Ground Speed"]
    assert cell.comparison.font().italic()
    assert not cell.primary.font().italic()


def test_line_styles_follow_the_series_colours():
    pedal = next(s for s in ROW_SPECS if s.key == ROW_PEDALS).series[0]
    assert line_style(pedal, Role.PRIMARY).colour == theme.COLOUR_THROTTLE
    assert line_style(pedal, Role.BENCHMARK).colour == theme.COLOUR_THROTTLE
    assert line_style(None, Role.PRIMARY).colour == theme.TRACE_REFERENCE
    assert line_style(None, Role.BENCHMARK).colour == theme.TRACE_COMPARISON


# --- the readout ------------------------------------------------------------------------


def test_the_readout_waits_for_the_cursor(compared):
    cell = compared.readout_cells["Ground Speed"]
    assert cell.primary.text() == "--"


def test_the_readout_shows_both_laps_under_the_cursor(compared):
    compared.set_cursor_distance(100.0)
    cell = compared.readout_cells["Ground Speed"]
    assert (cell.primary.text(), cell.comparison.text()) == ("144.0", "180.0")
    assert cell.primary.property("series") == "primary"
    assert cell.comparison.property("series") == "comparison"
    assert compared.readout_cells[CELL_POSITION].primary.text() == "100"


def test_the_delta_cell_is_toned_by_who_was_faster(compared):
    compared.set_cursor_distance(150.0)   # delta +0.150: behind
    cell = compared.readout_cells[CELL_DELTA]
    assert cell.primary.text() == "+0.150"
    assert cell.primary.property("tone") == theme.Tone.LOSS.value
    assert cell.comparison.isHidden()


def test_only_visible_rows_have_cells(compared):
    visible = {key for key, cell in compared.readout_cells.items()
               if cell.isVisibleTo(compared.readout)}
    assert "Ground Speed" in visible and "Throttle Pos" in visible
    assert "Gear" not in visible
    compared.set_row_enabled(ROW_GEAR, True)
    assert compared.readout_cells["Gear"].isVisibleTo(compared.readout)


def test_the_position_cell_follows_the_axis(qt_app):
    chart = ChartStack()
    chart.show_laps(_trace(n=201))
    chart.set_axis_mode(AxisMode.TIME)
    assert chart.readout_cells[CELL_POSITION].caption.text() == strings.CHART_READOUT_ELAPSED
    assert chart.readout_at(2.0)[CELL_POSITION] == ("2.00", None)


def test_readout_cells_hold_their_width(qt_app):
    """A figure changing from 99.0 to 268.4 must not shift the cells after it."""
    cell = ReadoutCell("Velocidade · km/h", widest="000.0")
    cell.show()
    cell.ensure_width()
    width = cell.primary.minimumWidth()
    assert width >= cell.primary.fontMetrics().horizontalAdvance("268.4")
    cell.show_values("9.0")
    assert cell.primary.minimumWidth() == width


def test_the_chrome_never_sets_the_window_width(compared):
    assert compared.chrome.minimumSizeHint().width() <= 200


# --- channel chips --------------------------------------------------------------------


def test_chips_are_the_menu_actions(qt_app):
    chart = ChartStack()
    actions = {}
    for spec in ROW_SPECS:
        action = QtGui.QAction(spec.axis_label)
        action.setCheckable(True)
        action.setChecked(chart.is_row_enabled(spec.key))
        actions[spec.key] = action
    chart.set_channel_actions(actions)

    chip = chart.channel_chips[ROW_GEAR]
    assert chip.defaultAction() is actions[ROW_GEAR]
    assert chip.text() == strings.CHART_CHIP_GEAR          # the short name
    assert chip.toolTip() == strings.CHART_ROW_GEAR        # the full one
    actions[ROW_DELTA].setEnabled(False)
    assert not chart.channel_chips[ROW_DELTA].isEnabled()


def test_the_window_shows_one_chip_per_row(qt_app, tmp_path, monkeypatch):
    from lmu_telemetry.composition import build_gateways
    from lmu_telemetry.infrastructure.storage import paths
    from lmu_telemetry.presentation.main_window import MainWindow

    monkeypatch.setenv(paths.ENV_DATA_DIR, str(tmp_path / "data"))
    window = MainWindow(build_gateways(), QtCore.QSettings(
        str(tmp_path / "l.ini"), QtCore.QSettings.Format.IniFormat))
    try:
        assert set(window.chart.channel_chips) == {spec.key for spec in ROW_SPECS}
        chip = window.chart.channel_chips[ROW_GEAR]
        chip.click()
        assert window.chart.is_row_enabled(ROW_GEAR)
        assert window.commands.channels[ROW_GEAR].isChecked()
    finally:
        window.close()


# --- small widgets ----------------------------------------------------------------------


def test_a_line_key_paints_its_style(qt_app):
    key = LineKey(LineStyle(theme.TRACE_COMPARISON, 1.3, dashed=True), "Volta 3")
    key.show()
    image = key.swatch.grab().toImage()
    middle = image.height() // 2
    row = [QtGui.QColor(image.pixel(x, middle)).name() for x in range(image.width())]
    painted = [colour == theme.TRACE_COMPARISON for colour in row[1:-1]]
    # Dashed: some of the line is painted and some is gap.
    assert any(painted) and not all(painted)


# --- the track map ----------------------------------------------------------------------


@pytest.mark.parametrize("name", ["PEDAL_STYLES", "LOSS_STYLES"])
def test_no_map_class_is_told_apart_by_colour_alone(name):
    """Red and green are the pair the commonest colour blindness confuses, and
    both map colourings rest on them: every class needs its own width or dash."""
    from lmu_telemetry.presentation import track_map

    styles = getattr(track_map, name)
    shapes = {(style.width, style.dashed) for style in styles.values()}
    assert len(shapes) == len(styles)


def test_losing_is_solid_and_gaining_is_dashed():
    from lmu_telemetry.presentation.track_map import LOSS_STYLES

    assert not LOSS_STYLES[-2].dashed and not LOSS_STYLES[-1].dashed
    assert LOSS_STYLES[+1].dashed and LOSS_STYLES[+2].dashed
    assert LOSS_STYLES[-2].width > LOSS_STYLES[-1].width > LOSS_STYLES[0].width


def test_the_map_key_follows_the_colouring(qt_app):
    from lmu_telemetry.presentation.track_map import (
        LOSS_STYLES, PEDAL_STYLES, MapColour, TrackMap,
    )

    n = 50
    track = TrackMap()
    track.show_path(np.arange(float(n)), np.zeros(n), np.arange(float(n)),
                    pedal_states=np.zeros(n, dtype=int),
                    loss_classes=np.zeros(n, dtype=int))
    assert [k.swatch.line_style for k in track.legend_keys] == \
        [PEDAL_STYLES[v] for v in (-1, 0, 1)]
    track.set_colour_mode(MapColour.DELTA)
    assert [k.swatch.line_style for k in track.legend_keys] == \
        [LOSS_STYLES[v] for v in (-2, 0, 2)]
    assert track.legend_keys[0].label.text() == strings.MAP_LEGEND_LOSS


def test_the_map_path_is_cached(qt_app):
    from lmu_telemetry.presentation.track_map import TrackMap

    n = 50
    track = TrackMap()
    track.show_path(np.arange(float(n)), np.zeros(n), np.arange(float(n)),
                    pedal_states=np.zeros(n, dtype=int))
    assert all(run.curve.cacheMode() == CACHED for run in track._runs)


# --- what keeps the cursor cheap ---------------------------------------------------------


def test_the_pixmap_cache_has_room_for_every_row(qt_app):
    """At Qt's default 10 MB each row's repaint evicted the row before it and
    the cursor cost 120 ms with caching on."""
    assert plotting.reserve_cache() >= 64 * 1024
    assert QtGui.QPixmapCache.cacheLimit() >= 64 * 1024


def test_rows_fit_their_y_range_once_instead_of_auto_ranging(compared):
    """Auto-range is recomputed on every paint and throws the curve caches
    away; the range is set once per lap instead."""
    for key in compared.visible_rows():
        assert compared._rows[key].plot.getViewBox().autoRangeEnabled()[1] is False


def test_the_fitted_range_spans_both_laps(compared):
    low, high = compared._rows[ROW_SPEED].plot.getViewBox().viewRange()[1]
    assert low <= 144.0 and high >= 180.0      # 40 and 50 m/s in km/h


def test_the_delta_range_always_includes_zero(qt_app):
    chart = ChartStack()
    grid = np.arange(100.0)
    chart.show_laps(_trace("Volta 2", n=100), _trace("Volta 1", n=100),
                    delta_grid_m=grid, delta_s=0.2 + grid * 0.001)
    low, _high = chart._rows[ROW_DELTA].plot.getViewBox().viewRange()[1]
    assert low <= 0.0


def test_line_widths_are_in_pixels():
    """A non-cosmetic pen is as wide as its width in *data* units: 2.4 m on a
    track map, under a pixel."""
    assert LineStyle(theme.TEXT, 2.4).pen().isCosmetic()
