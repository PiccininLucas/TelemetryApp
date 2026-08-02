"""Tests for the user interface.

Run against Qt's `offscreen` platform, so they need no display and work in CI.
Text renders as empty boxes there because the offscreen platform has no fonts;
that affects nothing these tests assert, and the interface renders normally on
a real desktop.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import numpy as np
import pytest

# Must be set before PySide6 is imported anywhere in the process.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets  # noqa: E402

from lmu_telemetry.core.models import Lap, LapFlag, SessionInfo  # noqa: E402
from lmu_telemetry.storage import catalog, paths  # noqa: E402
from lmu_telemetry.ui import strings, theme  # noqa: E402
from lmu_telemetry.ui.chart_panel import (  # noqa: E402
    ROW_DELTA, ROW_GEAR, ROW_PEDALS, ROW_SPEED, AxisMode, ChartStack, LapTrace, Role,
)
from lmu_telemetry.ui.formatting import (  # noqa: E402
    format_gap, format_lap_time, format_value,
)
from lmu_telemetry.ui.session_browser import SessionBrowser  # noqa: E402


def make_trace(
    label: str = "Volta 1",
    *,
    n: int = 200,
    speed_ms: float = 50.0,
    start_s: float = 0.0,
) -> LapTrace:
    """A flat-out lap on a 1 m grid, with every channel the stack can draw."""
    grid = np.arange(float(n))
    return LapTrace(
        label=label,
        grid_m=grid,
        elapsed_s=start_s + grid / speed_ms,
        channels={
            "Ground Speed": np.full_like(grid, speed_ms),
            "Throttle Pos": np.full_like(grid, 1.0),
            "Brake Pos": np.zeros_like(grid),
            "Steering Pos": np.zeros_like(grid),
            "Gear": np.full_like(grid, 5.0),
            "Engine RPM": np.full_like(grid, 7000.0),
        },
    )


@pytest.fixture(scope="session")
def qt_app():
    """One QApplication for the whole test session; Qt allows only one."""
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    theme.apply(app)
    yield app


@pytest.fixture
def catalog_with_sessions(tmp_path, monkeypatch):
    """A catalog holding two sessions at one track, with mixed lap kinds."""
    monkeypatch.setenv(paths.ENV_DATA_DIR, str(tmp_path / "data"))

    def info(session_id: str, car: str, when: datetime) -> SessionInfo:
        return SessionInfo(
            path=tmp_path / f"{session_id}.duckdb",
            track_name="Autodromo Nazionale Monza",
            session_type_code="R",
            started_at=when,
            car_name=car,
            car_class="LMP3",
            file_hash=session_id,
        )

    laps = [
        # A partial tail lap: very short, and the trap `select_default_lap` must
        # not fall into.
        Lap(index=0, number=0, t_start=0.0, t_end=4.4, official_time_s=None,
            flags=frozenset({LapFlag.PARTIAL})),
        Lap(index=1, number=1, t_start=4.4, t_end=114.8, official_time_s=110.4,
            flags=frozenset({LapFlag.VALID})),
        Lap(index=2, number=2, t_start=114.8, t_end=222.0, official_time_s=107.2,
            flags=frozenset({LapFlag.VALID})),
        Lap(index=3, number=3, t_start=222.0, t_end=330.0, official_time_s=0.0,
            flags=frozenset({LapFlag.INVALIDATED})),
    ]

    with catalog.connect() as con:
        catalog.import_session(
            con, "a" * 64,
            info("a" * 64, "DKR Engineering #4:ELMS25",
                 datetime(2026, 7, 30, 17, 0, tzinfo=UTC)),
            laps, 5793.0,
        )
        # A newer session, whose best lap is slower. The default selection must
        # still choose it, because recency wins over outright pace.
        catalog.import_session(
            con, "b" * 64,
            info("b" * 64, "DKR Engineering #4:ELMS25",
                 datetime(2026, 7, 31, 12, 0, tzinfo=UTC)),
            [
                Lap(index=0, number=0, t_start=0.0, t_end=120.0,
                    official_time_s=120.0, flags=frozenset({LapFlag.VALID})),
                Lap(index=1, number=1, t_start=120.0, t_end=125.0,
                    official_time_s=None, flags=frozenset({LapFlag.PARTIAL})),
            ],
            5793.0,
        )
    return tmp_path


# --------------------------------------------------------------------------- #
# Formatting
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (107.06, "1:47.060"),
        (244.738, "4:04.738"),
        (59.999, "0:59.999"),
        (None, "--"),
        (0.0, "--"),
        (-1.0, "--"),
    ],
)
def test_lap_time_formatting(seconds, expected):
    assert format_lap_time(seconds) == expected


def test_primary_lap_flag_prefers_the_most_decisive():
    """A lap can carry four flags at once; the narrow column shows the one that
    decides whether the lap is usable."""
    assert strings.primary_lap_flag(["valid"]) == "válida"
    assert strings.primary_lap_flag(["valid", "off_track"]) == "fora"
    assert strings.primary_lap_flag(
        ["in_lap", "in_pits", "off_track", "partial"]
    ) == "parcial"
    assert strings.primary_lap_flag(["invalidated", "off_track"]) == "invalidada"
    assert strings.primary_lap_flag([]) == ""


def test_every_flag_has_a_short_form():
    """Guards against a flag added to the model with no label here."""
    assert set(strings.LAP_FLAG_SHORT) == set(strings.LAP_FLAG_LABEL)
    assert set(strings.LAP_FLAG_PRIORITY) == set(strings.LAP_FLAG_LABEL)


# --------------------------------------------------------------------------- #
# Session browser
# --------------------------------------------------------------------------- #

def test_browser_shows_a_placeholder_when_the_catalog_is_empty(
    qt_app, tmp_path, monkeypatch
):
    monkeypatch.setenv(paths.ENV_DATA_DIR, str(tmp_path / "empty"))
    browser = SessionBrowser()

    assert browser.reload() == 0
    assert browser.placeholder.isVisible() or not browser.tree.isVisible()


def test_browser_groups_by_track_then_car_then_session(
    qt_app, catalog_with_sessions
):
    """Laps are only comparable within one track and one car, so that is the
    order that puts comparable things next to each other."""
    browser = SessionBrowser()
    assert browser.reload() == 2

    assert browser.tree.topLevelItemCount() == 1
    track = browser.tree.topLevelItem(0)
    assert track.text(0) == "Autodromo Nazionale Monza"

    car = track.child(0)
    assert car.text(0) == "DKR Engineering #4:ELMS25"
    assert car.childCount() == 2  # two sessions

    session = car.child(0)
    assert session.childCount() in (2, 4)  # laps of whichever session sorts first


def test_browser_shows_each_session_s_best_lap(qt_app, catalog_with_sessions):
    browser = SessionBrowser()
    browser.reload()

    car = browser.tree.topLevelItem(0).child(0)
    session_times = {car.child(i).text(1) for i in range(car.childCount())}

    assert "1:47.200" in session_times  # the older session's best
    assert "2:00.000" in session_times  # the newer session's only valid lap


def test_default_selection_is_not_the_shortest_lap(qt_app, catalog_with_sessions):
    """A session's tail is a partial lap of a few seconds. Picking the globally
    shortest lap time would select one of those every time - which is exactly
    what the first version of this did."""
    browser = SessionBrowser()
    browser.reload()

    assert browser.select_default_lap() is True
    selection = browser.current_lap()

    assert selection is not None
    assert selection.is_comparable
    assert selection.time_s > 60.0


def test_default_selection_prefers_the_most_recent_session(
    qt_app, catalog_with_sessions
):
    """Almost certainly the lap the user just drove, which is what they came to
    look at - even though a previous session was faster."""
    browser = SessionBrowser()
    browser.reload()
    browser.select_default_lap()

    selection = browser.current_lap()
    assert selection.session_id == "b" * 64
    assert selection.time_s == pytest.approx(120.0)


def test_selecting_a_non_lap_node_yields_nothing(qt_app, catalog_with_sessions):
    """Clicking a track or a car must not try to load telemetry."""
    browser = SessionBrowser()
    browser.reload()

    browser.tree.setCurrentItem(browser.tree.topLevelItem(0))
    assert browser.current_lap() is None


def test_default_selection_on_an_empty_catalog(qt_app, tmp_path, monkeypatch):
    monkeypatch.setenv(paths.ENV_DATA_DIR, str(tmp_path / "empty2"))
    browser = SessionBrowser()
    browser.reload()

    assert browser.select_default_lap() is False
    assert browser.current_lap() is None


def test_browser_survives_an_unreadable_catalog(qt_app, tmp_path, monkeypatch):
    """A broken catalog must leave an empty tree, not a stack trace."""
    data_dir = tmp_path / "broken"
    data_dir.mkdir(parents=True)
    (data_dir / "catalog.duckdb").write_bytes(b"not a database at all" * 50)
    monkeypatch.setenv(paths.ENV_DATA_DIR, str(data_dir))

    browser = SessionBrowser()
    assert browser.reload() == 0


# --------------------------------------------------------------------------- #
# Formatting helpers
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(1.1610001, "+1.161"), (-0.2836, "-0.284"), (0.0, "+0.000"),
     (float("nan"), "--"), (None, "--")],
)
def test_gap_is_always_signed(seconds, expected):
    """An unsigned "0.284" next to a lap time is ambiguous in exactly the case
    that matters most."""
    assert format_gap(seconds) == expected


def test_format_value_survives_gaps_in_the_data():
    assert format_value(218.44, 1) == "218.4"
    assert format_value(float("nan"), 1) == "--"
    assert format_value(None, 0) == "--"


# --------------------------------------------------------------------------- #
# Chart stack
# --------------------------------------------------------------------------- #

def test_chart_starts_empty(qt_app):
    chart = ChartStack()
    assert chart.axis_mode is AxisMode.DISTANCE
    assert chart.visible_rows() == []  # nothing loaded, so nothing to show


def test_chart_converts_speed_to_kmh(qt_app):
    """The application works in SI internally and shows km/h, which is what a
    driver reads."""
    chart = ChartStack()
    chart.show_laps(make_trace(speed_ms=50.0))

    _x, y = chart._rows[ROW_SPEED].curves[("Ground Speed", Role.PRIMARY)].getData()
    assert y[0] == pytest.approx(180.0)


def test_chart_converts_pedals_to_percent(qt_app):
    """Pedals are held as a 0-1 fraction internally; a driver reads percent."""
    chart = ChartStack()
    chart.show_laps(make_trace())

    _x, y = chart._rows[ROW_PEDALS].curves[("Throttle Pos", Role.PRIMARY)].getData()
    assert y[0] == pytest.approx(100.0)


def test_pedal_row_has_a_fixed_range(qt_app):
    """Autoscaling would turn a lap that never used more than 40% brake into one
    that looks like it locked the wheels at every corner."""
    chart = ChartStack()
    chart.show_laps(make_trace())

    low, high = chart._rows[ROW_PEDALS].plot.getViewBox().viewRange()[1]
    assert low == pytest.approx(-3.0)
    assert high == pytest.approx(103.0)


def test_chart_axis_toggle_swaps_the_x_data(qt_app):
    chart = ChartStack()
    chart.show_laps(make_trace(n=201, speed_ms=50.0))
    curve = chart._rows[ROW_SPEED].curves[("Ground Speed", Role.PRIMARY)]

    x, _y = curve.getData()
    assert x[-1] == pytest.approx(200.0)

    chart.set_axis_mode(AxisMode.TIME)
    x, _y = curve.getData()
    assert x[-1] == pytest.approx(4.0)
    assert chart.axis_mode is AxisMode.TIME


def test_only_the_bottom_row_labels_the_x_axis(qt_app):
    """Repeating the same numbers under every plot costs the height the traces
    need and tells the reader nothing new - the axes are linked."""
    chart = ChartStack()
    chart.show_laps(make_trace())

    visible = chart.visible_rows()
    assert len(visible) >= 2
    labels = [chart._rows[k].plot.getAxis("bottom").labelText for k in visible]
    assert labels[-1] == strings.CHART_AXIS_DISTANCE
    assert all(label == "" for label in labels[:-1])


def test_rows_share_one_x_range(qt_app):
    """A braking point is a relationship between rows, so panning one has to
    move all of them."""
    chart = ChartStack()
    chart.show_laps(make_trace())
    chart.set_row_enabled(ROW_GEAR, True)

    chart._rows[ROW_SPEED].plot.setXRange(40.0, 60.0, padding=0.0)
    other = chart._rows[ROW_GEAR].plot.getViewBox().viewRange()[0]
    assert other[0] == pytest.approx(40.0)
    assert other[1] == pytest.approx(60.0)


def test_row_is_hidden_when_the_session_never_recorded_it(qt_app):
    """An empty steering plot reads as "the driver never steered"."""
    trace = make_trace()
    without_steering = LapTrace(
        label=trace.label, grid_m=trace.grid_m, elapsed_s=trace.elapsed_s,
        channels={k: v for k, v in trace.channels.items() if k != "Steering Pos"},
    )
    chart = ChartStack()
    chart.show_laps(without_steering)

    assert "steering" not in chart.available_rows()
    chart.set_row_enabled("steering", True)
    assert "steering" not in chart.visible_rows()


def test_delta_row_appears_only_with_a_comparison(qt_app):
    chart = ChartStack()
    chart.show_laps(make_trace())
    assert ROW_DELTA not in chart.visible_rows()

    grid = np.arange(200.0)
    chart.show_laps(
        make_trace("Volta 2"), make_trace("Volta 1"),
        delta_grid_m=grid, delta_s=grid * 0.001,
    )
    assert ROW_DELTA in chart.visible_rows()


def test_delta_is_split_at_zero(qt_app):
    """The sign is the difference between losing and gaining time; a single
    brush would make a lap that gains 0.4 s look exactly like one that loses
    it."""
    chart = ChartStack()
    grid = np.arange(5.0)
    delta = np.array([0.0, 0.2, 0.4, -0.1, -0.3])
    chart.show_laps(
        make_trace("Volta 2", n=5), make_trace("Volta 1", n=5),
        delta_grid_m=grid, delta_s=delta,
    )

    row = chart._rows[ROW_DELTA]
    _x, loss = row.delta_loss.getData()
    _x, gain = row.delta_gain.getData()
    assert list(loss) == [0.0, 0.2, 0.4, 0.0, 0.0]
    assert list(gain) == [0.0, 0.0, 0.0, -0.1, -0.3]


def test_delta_is_not_drawn_on_the_time_axis(qt_app):
    """Two laps at the same elapsed time are at different places on the
    circuit, so a delta plotted against time compares nothing."""
    chart = ChartStack()
    grid = np.arange(200.0)
    chart.show_laps(
        make_trace("Volta 2"), make_trace("Volta 1"),
        delta_grid_m=grid, delta_s=grid * 0.001,
    )
    chart.set_axis_mode(AxisMode.TIME)

    _x, y = chart._rows[ROW_DELTA].delta_curve.getData()
    assert y is None or len(y) == 0


def test_benchmark_is_drawn_alongside_the_primary_lap(qt_app):
    chart = ChartStack()
    chart.show_laps(make_trace("Volta 2", speed_ms=40.0),
                    make_trace("Volta 1", speed_ms=50.0))

    row = chart._rows[ROW_SPEED]
    _x, primary = row.curves[("Ground Speed", Role.PRIMARY)].getData()
    _x, benchmark = row.curves[("Ground Speed", Role.BENCHMARK)].getData()
    assert primary[0] == pytest.approx(144.0)
    assert benchmark[0] == pytest.approx(180.0)


def test_pedal_row_tells_laps_apart_by_line_style_not_colour(qt_app):
    """Throttle and brake must stay green and red - that reading is instant and
    universal - so on that row the second lap is dashed instead."""
    from PySide6 import QtCore as _QtCore

    chart = ChartStack()
    row = chart._rows[ROW_PEDALS]
    primary = row.curves[("Throttle Pos", Role.PRIMARY)].opts["pen"]
    benchmark = row.curves[("Throttle Pos", Role.BENCHMARK)].opts["pen"]

    assert primary.color().name() == benchmark.color().name()
    assert benchmark.style() == _QtCore.Qt.PenStyle.DashLine


def test_chart_clear_removes_every_trace(qt_app):
    chart = ChartStack()
    chart.show_laps(make_trace())
    chart.clear()

    x, _y = chart._rows[ROW_SPEED].curves[("Ground Speed", Role.PRIMARY)].getData()
    assert x is None or len(x) == 0


def test_cursor_readout_reports_both_laps(qt_app):
    chart = ChartStack()
    chart.show_laps(make_trace("Volta 2", speed_ms=40.0),
                    make_trace("Volta 1", speed_ms=50.0))

    text = chart._readout_text(100.0)
    assert "100 m" in text
    assert "144.0" in text and "180.0" in text


def test_chart_draws_a_full_le_mans_lap(qt_app, synthetic_lap):
    """13 600 points is what a Le Mans lap on a 1 m grid actually is."""
    chart = ChartStack()
    chart.show_laps(LapTrace(
        label="Volta 1",
        grid_m=synthetic_lap.distance_m,
        elapsed_s=synthetic_lap.times_s,
        channels={"Ground Speed": synthetic_lap.speed_ms},
    ))

    x, y = chart._rows[ROW_SPEED].curves[("Ground Speed", Role.PRIMARY)].getData()
    assert len(x) == len(synthetic_lap.distance_m)
    assert y.max() == pytest.approx(synthetic_lap.speed_ms.max() * 3.6)


# --------------------------------------------------------------------------- #
# Theme
# --------------------------------------------------------------------------- #

def test_theme_sets_pyqtgraph_globals(qt_app):
    """pyqtgraph keeps its own background and foreground, separate from Qt's
    palette, so both have to be set or the plots stay white."""
    import pyqtgraph as pg

    theme.configure_pyqtgraph()
    assert pg.getConfigOption("background") == theme.BACKGROUND
    assert pg.getConfigOption("foreground") == theme.TEXT_MUTED


def test_entry_point_is_importable_and_wired():
    """`main.py` is not exercised by any other test, so a typo or a bad import
    there would only surface when the user launched the application."""
    import importlib

    entry = importlib.import_module("main")
    assert callable(entry.main)


def test_main_window_builds_and_closes_cleanly(qt_app, catalog_with_sessions):
    """Building the window opens a session file; closing it must release the
    connection, or a long-running application leaks a handle per session
    viewed."""
    from lmu_telemetry.ui.main_window import MainWindow

    window = MainWindow()
    try:
        assert window.windowTitle()
        assert window.splitter.count() == 3  # browser, traces, side panels
        # No telemetry file exists behind this catalog, so no session opens.
        assert len(window._sessions) == 0
    finally:
        window.close()


def test_session_pool_holds_two_files_and_evicts_the_third(qt_app):
    """A comparison against a pinned lap from another afternoon needs two files
    open. Beyond that, holding them open only leaks handles."""
    from lmu_telemetry.ui.main_window import OpenSession, SessionPool

    class FakeSession:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    pool = SessionPool(capacity=2)
    opened = {}
    for name in ("a", "b", "c"):
        session = FakeSession()
        opened[name] = session
        pool._open[name] = OpenSession(name, session, None)
        pool._touch(name)
        pool._evict()

    assert len(pool) == 2
    assert opened["a"].closed          # least recently used
    assert not opened["c"].closed


def test_comparison_mode_survives_having_nothing_to_compare(qt_app,
                                                            catalog_with_sessions):
    """Switching to a pinned comparison with nothing pinned must say so, not
    crash."""
    from lmu_telemetry.ui.main_window import ComparisonMode, MainWindow

    window = MainWindow()
    try:
        # Nothing selected, so the mode change is not followed by a redraw that
        # would overwrite the message with its own.
        window._selection = None
        window.set_comparison_mode(ComparisonMode.PINNED)

        assert window._mode is ComparisonMode.PINNED
        assert window.statusBar().currentMessage() == (
            strings.STATUS_NO_REFERENCE_PINNED
        )
    finally:
        window.close()


def test_time_axis_is_disabled_while_two_laps_are_drawn(qt_app,
                                                        catalog_with_sessions):
    """At equal elapsed times two laps are at different points of the circuit,
    so an overlay on that axis would invite a comparison that says nothing."""
    from lmu_telemetry.ui.main_window import MainWindow

    window = MainWindow()
    try:
        window._sync_actions(comparing=True)
        assert not window.action_time.isEnabled()
        assert window.chart.axis_mode is AxisMode.DISTANCE

        window._sync_actions(comparing=False)
        assert window.action_time.isEnabled()
    finally:
        window.close()


def test_reference_and_comparison_traces_are_distinguishable():
    """Not a red/green pair: the most common form of colour blindness would make
    the reference and comparison laps indistinguishable."""
    assert theme.TRACE_REFERENCE != theme.TRACE_COMPARISON
    reference = int(theme.TRACE_REFERENCE[1:], 16)
    comparison = int(theme.TRACE_COMPARISON[1:], 16)
    assert abs(reference - comparison) > 0x100000


# --------------------------------------------------------------------------- #
# Track map
# --------------------------------------------------------------------------- #

def make_square_path(n: int = 400):
    """A closed rectangular path, so the map has something with a real shape."""
    side = n // 4
    x = np.concatenate([
        np.linspace(0, 300, side), np.full(side, 300.0),
        np.linspace(300, 0, side), np.zeros(side),
    ])
    y = np.concatenate([
        np.zeros(side), np.linspace(0, 200, side),
        np.full(side, 200.0), np.linspace(200, 0, side),
    ])
    return x, y, np.arange(float(len(x)))


def test_runs_of_splits_a_class_array_into_maximal_runs():
    from lmu_telemetry.ui.track_map import _runs_of

    assert _runs_of(np.array([1, 1, 0, 0, 0, -1])) == [
        (0, 2, 1), (2, 5, 0), (5, 6, -1),
    ]
    assert _runs_of(np.array([])) == []
    assert _runs_of(np.array([3, 3, 3])) == [(0, 3, 3)]


def test_map_draws_one_polyline_per_colour_run(qt_app):
    """A 13 600-point lap as coloured points would be 13 600 items; as runs of
    constant colour it is a few hundred."""
    from lmu_telemetry.ui.track_map import TrackMap

    x, y, grid = make_square_path()
    states = np.ones(len(x), dtype=np.int8)
    states[100:150] = -1     # braking
    states[150:160] = 0      # coasting

    track_map = TrackMap()
    track_map.show_path(x, y, grid, pedal_states=states)

    assert len(track_map._runs) == 4  # throttle, brake, coast, throttle


def test_map_runs_overlap_by_one_point(qt_app):
    """Without the overlap the path shows a gap at every colour change, which
    on a pedal map is every braking point."""
    from lmu_telemetry.ui.track_map import TrackMap

    x, y, grid = make_square_path()
    states = np.ones(len(x), dtype=np.int8)
    states[100:] = -1

    track_map = TrackMap()
    track_map.show_path(x, y, grid, pedal_states=states)

    first_x, _ = track_map._runs[0].getData()
    second_x, _ = track_map._runs[1].getData()
    assert first_x[-1] == pytest.approx(second_x[0])


def test_map_falls_back_when_the_delta_colouring_has_no_data(qt_app):
    """The mode may have been left on delta by a lap that had a comparison."""
    from lmu_telemetry.ui.track_map import MapColour, TrackMap

    x, y, grid = make_square_path()
    states = np.ones(len(x), dtype=np.int8)

    track_map = TrackMap()
    track_map.show_path(x, y, grid, pedal_states=states,
                        loss_classes=np.zeros(len(x), dtype=np.int8))
    track_map.set_colour_mode(MapColour.DELTA)
    assert track_map.colour_mode is MapColour.DELTA

    track_map.show_path(x, y, grid, pedal_states=states)
    assert track_map.colour_mode is MapColour.PEDALS


def test_map_keeps_the_circuit_s_aspect_ratio(qt_app):
    """A circuit stretched to fill the panel is not a circuit."""
    from lmu_telemetry.ui.track_map import TrackMap

    track_map = TrackMap()
    assert track_map.plot.getViewBox().state["aspectLocked"] == 1


def test_map_cursor_lands_on_the_path_at_a_given_distance(qt_app):
    from lmu_telemetry.ui.track_map import TrackMap

    x, y, grid = make_square_path()
    track_map = TrackMap()
    track_map.show_path(x, y, grid, pedal_states=np.ones(len(x), dtype=np.int8))

    track_map.set_cursor_distance(float(grid[150]))

    cursor_x, cursor_y = track_map._cursor.getData()
    assert cursor_x[0] == pytest.approx(x[150])
    assert cursor_y[0] == pytest.approx(y[150])


# --------------------------------------------------------------------------- #
# g-g diagram
# --------------------------------------------------------------------------- #

def test_gg_panel_draws_the_hull_it_reports(qt_app):
    """Outlining the hull is what makes the numbers under the plot auditable by
    eye rather than something the panel asserts."""
    from lmu_telemetry.analysis import friction
    from lmu_telemetry.ui.gg_panel import FrictionPanel

    rng = np.random.default_rng(3)
    angle = rng.uniform(0, 2 * np.pi, 500)
    radius = np.sqrt(rng.uniform(0, 1, 500))
    lateral = 2.0 * radius * np.cos(angle)
    longitudinal = 1.5 * radius * np.sin(angle)
    envelope = friction.compute_envelope(lateral, longitudinal)

    panel = FrictionPanel()
    panel.show_envelope(envelope, lateral, longitudinal,
                        np.arange(float(len(lateral))), 0.42)

    hull_x, _hull_y = panel._hull.getData()
    assert len(hull_x) == len(envelope.hull_lateral_g)
    assert f"{envelope.max_lateral_g:.2f}" in panel.summary.text()
    assert "42%" in panel.detail.text()


def test_gg_panel_keeps_equal_axes(qt_app):
    """One g of braking must be as tall as one g of cornering, or a circular
    envelope reads as an elliptical one."""
    from lmu_telemetry.ui.gg_panel import FrictionPanel

    panel = FrictionPanel()
    assert panel.plot.getViewBox().state["aspectLocked"] == 1


def test_gg_cursor_lands_on_the_lap_s_own_samples(qt_app):
    """The envelope drops low-speed samples, so it no longer lines up with the
    distance grid; the cursor has to index the unfiltered arrays."""
    from lmu_telemetry.analysis import friction
    from lmu_telemetry.ui.gg_panel import FrictionPanel

    grid = np.arange(0.0, 100.0)
    lateral = np.sin(grid / 10.0)
    longitudinal = np.cos(grid / 10.0)
    speed = np.where(grid < 20, 2.0, 60.0)   # the first 20 m are excluded
    envelope = friction.compute_envelope(lateral, longitudinal, speed)

    panel = FrictionPanel()
    panel.show_envelope(envelope, lateral, longitudinal, grid, 0.5)
    panel.set_cursor_distance(50.0)

    x, y = panel._cursor.getData()
    assert x[0] == pytest.approx(lateral[50])
    assert y[0] == pytest.approx(longitudinal[50])
    assert envelope.n_points == 80


# --------------------------------------------------------------------------- #
# Cursor synchronisation
# --------------------------------------------------------------------------- #

def test_chart_cursor_reports_distance_in_both_axis_modes(qt_app):
    """Distance is the coordinate the map and the g-g diagram are indexed by,
    so the stack converts once rather than making every listener know which
    mode it is in."""
    chart = ChartStack()
    chart.show_laps(make_trace(n=201, speed_ms=50.0))

    chart.set_cursor_distance(120.0)
    x_distance = chart._rows[ROW_SPEED].cursor.value()

    chart.set_axis_mode(AxisMode.TIME)
    chart.set_cursor_distance(120.0)
    x_time = chart._rows[ROW_SPEED].cursor.value()

    assert x_distance == pytest.approx(120.0)
    assert x_time == pytest.approx(120.0 / 50.0)


def test_setting_the_cursor_does_not_re_emit(qt_app):
    """The map drives the chart and the chart drives the map; one of them has
    to stay silent or the signal bounces between them forever."""
    chart = ChartStack()
    chart.show_laps(make_trace())

    emitted = []
    chart.cursor_moved.connect(emitted.append)
    chart.set_cursor_distance(50.0)

    assert emitted == []
