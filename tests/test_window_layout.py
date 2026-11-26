"""The window's docks, toolbar and remembered layout.

Offscreen like the rest of the UI tests, so these check structure and state -
which panels exist, which are hidden, what is saved and restored - not how the
window looks.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6 import QtCore, QtWidgets  # noqa: E402

from lmu_telemetry.composition import build_gateways  # noqa: E402
from lmu_telemetry.presentation import theme  # noqa: E402
from lmu_telemetry.presentation.main_window import (  # noqa: E402
    LAYOUT_STATE_VERSION, MainWindow,
)
from lmu_telemetry.presentation.session_state import ComparisonMode  # noqa: E402
from lmu_telemetry.shared import strings  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    theme.apply(app)
    yield app


@pytest.fixture
def settings(tmp_path):
    """A settings file of the test's own, so layouts never leak between tests."""
    return QtCore.QSettings(str(tmp_path / "layout.ini"), QtCore.QSettings.Format.IniFormat)


@pytest.fixture
def window(qt_app, tmp_path, monkeypatch, settings):
    from lmu_telemetry.infrastructure.storage import paths

    monkeypatch.setenv(paths.ENV_DATA_DIR, str(tmp_path / "data"))
    made = MainWindow(build_gateways(), settings)
    made.show()  # a never-shown window has no visible docks to toggle
    yield made
    made.close()


def _hidden(dock: QtWidgets.QDockWidget) -> bool:
    return dock.isHidden()


# --- structure ---------------------------------------------------------------


def test_the_traces_are_the_centre_and_every_other_panel_is_a_dock(window):
    assert window.chart.parent() is window.centralWidget()
    assert {d.widget() for d in window.docks} == {
        window.browser, window.tabs, window.track_map, window.friction,
    }


def test_docks_have_stable_object_names(window):
    """`saveState` keys the layout on them; a rename orphans every saved layout."""
    assert [d.objectName() for d in window.docks] == [
        "dock_sessions", "dock_corners", "dock_map", "dock_gg",
    ]


def test_docks_are_titled_by_what_they_hold(window):
    assert window.dock_sessions.windowTitle() == strings.BROWSER_TITLE
    assert window.dock_map.windowTitle() == strings.MAP_TITLE
    assert window.dock_gg.windowTitle() == strings.GG_TITLE
    assert window.dock_corners.windowTitle() == strings.DOCK_CORNERS


def test_every_dock_is_shown_floatable_and_closable_by_default(window):
    for dock in window.docks:
        assert not _hidden(dock)
        assert not dock.isFloating()
        features = dock.features()
        assert features & QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetFloatable
        assert features & QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetClosable


def test_panels_in_the_signal_wiring_still_reach_each_other(window):
    """The cursor is shared: moving it on the map must reach the chart."""
    window.track_map.distance_picked.emit(500.0)  # must not raise


# --- panels menu -------------------------------------------------------------


def test_panels_menu_toggles_each_dock(window):
    for dock in window.docks:
        dock.toggleViewAction().trigger()
        assert _hidden(dock)
        dock.toggleViewAction().trigger()
        assert not _hidden(dock)


def test_closing_a_dock_from_its_title_bar_updates_the_menu(window):
    window.dock_map.close()
    assert not window.dock_map.toggleViewAction().isChecked()


def test_reset_layout_brings_back_hidden_docks_and_the_toolbar(window):
    for dock in window.docks:
        dock.hide()
    window.toolbar.hide()

    window.reset_layout()

    assert all(not _hidden(d) for d in window.docks)
    assert not window.toolbar.isHidden()
    assert window.statusBar().currentMessage() == strings.STATUS_LAYOUT_RESET


def test_reset_layout_docks_a_floating_panel_again(window):
    window.dock_gg.setFloating(True)
    window.reset_layout()
    assert not window.dock_gg.isFloating()


# --- toolbar -----------------------------------------------------------------


def test_the_toolbar_reuses_the_menu_actions(window):
    """One QAction in both places, so checked and enabled state cannot drift."""
    in_bar = set(window.toolbar.actions())
    assert window.action_import in in_bar
    assert window.action_refresh in in_bar
    assert window.action_pin in in_bar
    assert window.action_distance in in_bar
    assert set(window.comparison_actions.values()) <= in_bar


def test_toolbar_buttons_use_short_labels_and_keep_the_full_tooltip(window):
    """Long menu wording pushed the last buttons into the overflow menu."""
    best = window.comparison_actions[ComparisonMode.SESSION_BEST]
    assert best.iconText() == strings.TOOLBAR_COMPARE_BEST
    assert len(best.iconText()) < len(best.text())
    assert best.toolTip() == best.text().replace("&", "")
    assert window.export_actions["pdf"].iconText() == strings.TOOLBAR_EXPORT_PDF


def test_the_time_axis_keeps_its_own_tooltip(window):
    """It explains why the axis is blocked during a comparison."""
    assert window.action_time.toolTip() == strings.ACTION_AXIS_TIME_BLOCKED


def test_choosing_a_comparison_in_the_toolbar_changes_the_mode(window):
    window.comparison_actions[ComparisonMode.NONE].trigger()
    assert window._mode is ComparisonMode.NONE


def test_import_actions_in_the_toolbar_are_disabled_while_importing(window):
    window._import_actions_enabled(False)
    assert not window.action_import.isEnabled()
    window._import_actions_enabled(True)
    assert window.action_import.isEnabled()


def test_the_toolbar_can_be_hidden_from_the_panels_menu(window):
    window.toolbar.toggleViewAction().trigger()
    assert window.toolbar.isHidden()


# --- remembered layout -------------------------------------------------------


def test_the_layout_is_saved_when_the_window_closes(qt_app, tmp_path, monkeypatch, settings):
    from lmu_telemetry.infrastructure.storage import paths

    monkeypatch.setenv(paths.ENV_DATA_DIR, str(tmp_path / "data"))
    first = MainWindow(build_gateways(), settings)
    first.close()

    assert not settings.value("window/state", QtCore.QByteArray()).isEmpty()
    assert not settings.value("window/geometry", QtCore.QByteArray()).isEmpty()


def test_a_hidden_panel_stays_hidden_next_time(qt_app, tmp_path, monkeypatch, settings):
    from lmu_telemetry.infrastructure.storage import paths

    monkeypatch.setenv(paths.ENV_DATA_DIR, str(tmp_path / "data"))
    first = MainWindow(build_gateways(), settings)
    first.dock_map.hide()
    first.close()

    second = MainWindow(build_gateways(), settings)
    try:
        assert _hidden(second.dock_map)
        assert not _hidden(second.dock_gg)
    finally:
        second.close()


def test_a_floating_panel_stays_floating_next_time(qt_app, tmp_path, monkeypatch, settings):
    from lmu_telemetry.infrastructure.storage import paths

    monkeypatch.setenv(paths.ENV_DATA_DIR, str(tmp_path / "data"))
    first = MainWindow(build_gateways(), settings)
    first.dock_gg.setFloating(True)
    first.close()

    second = MainWindow(build_gateways(), settings)
    try:
        assert second.dock_gg.isFloating()
    finally:
        second.close()


def test_a_first_run_uses_the_default_layout(window):
    assert all(not _hidden(d) for d in window.docks)


def test_an_unusable_saved_layout_falls_back_to_the_default(
    qt_app, tmp_path, monkeypatch, settings
):
    """A layout from another build, or a damaged file, must not leave the window
    half-restored or empty."""
    from lmu_telemetry.infrastructure.storage import paths

    monkeypatch.setenv(paths.ENV_DATA_DIR, str(tmp_path / "data"))
    settings.setValue("window/state", QtCore.QByteArray(b"not a saved layout"))
    settings.sync()

    window = MainWindow(build_gateways(), settings)
    try:
        assert all(not _hidden(d) for d in window.docks)
    finally:
        window.close()


def test_a_layout_saved_under_another_version_is_ignored(
    qt_app, tmp_path, monkeypatch, settings
):
    from lmu_telemetry.infrastructure.storage import paths

    monkeypatch.setenv(paths.ENV_DATA_DIR, str(tmp_path / "data"))
    first = MainWindow(build_gateways(), settings)
    first.dock_map.hide()
    stale = first.saveState(LAYOUT_STATE_VERSION + 1)
    first.close()
    settings.setValue("window/state", stale)
    settings.sync()

    second = MainWindow(build_gateways(), settings)
    try:
        assert not _hidden(second.dock_map)  # default, not the stale layout
    finally:
        second.close()
