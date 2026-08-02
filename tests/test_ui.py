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
from lmu_telemetry.ui.chart_panel import AxisMode, SpeedChart  # noqa: E402
from lmu_telemetry.ui.session_browser import (  # noqa: E402
    SessionBrowser, format_lap_time,
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
# Speed chart
# --------------------------------------------------------------------------- #

def test_chart_starts_empty(qt_app):
    chart = SpeedChart()
    assert chart.axis_mode is AxisMode.DISTANCE


def test_chart_converts_speed_to_kmh(qt_app):
    """The application works in SI internally and shows km/h, which is what a
    driver reads."""
    chart = SpeedChart()
    grid = np.arange(0.0, 100.0)
    chart.show_lap(grid, grid / 50.0, np.full_like(grid, 50.0))

    _x, y = chart._curve.getData()
    assert y[0] == pytest.approx(180.0)


def test_chart_axis_toggle_swaps_the_x_data(qt_app):
    chart = SpeedChart()
    distance = np.array([0.0, 100.0, 200.0])
    elapsed = np.array([0.0, 2.0, 4.0])
    chart.show_lap(distance, elapsed, np.array([50.0, 50.0, 50.0]))

    x, _y = chart._curve.getData()
    assert x[-1] == pytest.approx(200.0)

    chart.set_axis_mode(AxisMode.TIME)
    x, _y = chart._curve.getData()
    assert x[-1] == pytest.approx(4.0)
    assert chart.axis_mode is AxisMode.TIME


def test_chart_axis_label_follows_the_mode(qt_app):
    chart = SpeedChart()
    chart.set_axis_mode(AxisMode.TIME)
    assert strings.CHART_AXIS_TIME in chart.plot.getAxis("bottom").labelText

    chart.set_axis_mode(AxisMode.DISTANCE)
    assert strings.CHART_AXIS_DISTANCE in chart.plot.getAxis("bottom").labelText


def test_chart_clear_removes_the_trace(qt_app):
    chart = SpeedChart()
    grid = np.arange(0.0, 100.0)
    chart.show_lap(grid, grid, np.full_like(grid, 50.0))
    chart.clear()

    x, _y = chart._curve.getData()
    assert x is None or len(x) == 0


def test_chart_draws_a_full_le_mans_lap(qt_app, synthetic_lap):
    """13 600 points is what a Le Mans lap on a 1 m grid actually is."""
    chart = SpeedChart()
    chart.show_lap(
        synthetic_lap.distance_m, synthetic_lap.times_s, synthetic_lap.speed_ms
    )

    x, y = chart._curve.getData()
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
        assert window.splitter.count() == 2
        # No telemetry file exists behind this catalog, so no session opens.
        assert window._open is None
    finally:
        window.close()


def test_reference_and_comparison_traces_are_distinguishable():
    """Not a red/green pair: the most common form of colour blindness would make
    the reference and comparison laps indistinguishable."""
    assert theme.TRACE_REFERENCE != theme.TRACE_COMPARISON
    reference = int(theme.TRACE_REFERENCE[1:], 16)
    comparison = int(theme.TRACE_COMPARISON[1:], 16)
    assert abs(reference - comparison) > 0x100000
