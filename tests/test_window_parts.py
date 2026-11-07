"""The parts the window was split into: the status line, the notice banner, the
commands, the import runner, the exports and the lap view.

Each is tested on its own, without a window, which is what splitting them out
was for; the last group opens the demo session and checks the window hands
their results to the right places.
"""

from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6 import QtCore, QtWidgets  # noqa: E402

from lmu_telemetry.presentation import lap_view, theme  # noqa: E402
from lmu_telemetry.presentation.chart_panel import AxisMode  # noqa: E402
from lmu_telemetry.presentation.import_worker import ImportRunner  # noqa: E402
from lmu_telemetry.presentation.notice_banner import NoticeBanner, Severity  # noqa: E402
from lmu_telemetry.presentation.session_state import ComparisonMode  # noqa: E402
from lmu_telemetry.presentation.status_line import StatusLine  # noqa: E402
from lmu_telemetry.presentation.window_actions import WindowActions  # noqa: E402
from lmu_telemetry.shared import strings  # noqa: E402

PRESENTATION = Path(theme.__file__).parent


@pytest.fixture(scope="module")
def qt_app():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    theme.apply(app)
    yield app


def _drawn(label: QtWidgets.QLabel) -> str:
    label.ensurePolished()
    return label.palette().color(label.foregroundRole()).name()


# --- status line -----------------------------------------------------------------


def test_the_status_line_opens_ready(qt_app):
    assert StatusLine().currentMessage() == strings.STATUS_READY


def test_a_notice_gives_way_to_the_resting_line(qt_app):
    """An exported file's path must not stay on the bar for the rest of the
    session, long after the lap it was about has changed."""
    status = StatusLine()
    status.rest("Volta 5")
    status.notify("Salvo em x.pdf")
    assert status.currentMessage() == "Salvo em x.pdf"
    status.clearMessage()  # what the notice's timeout does
    assert status.currentMessage() == "Volta 5"


def test_a_new_resting_line_replaces_a_notice_at_once(qt_app):
    status = StatusLine()
    status.notify("Carregando...", sticky=True)
    status.rest("Volta 6")
    assert status.currentMessage() == "Volta 6"
    assert status.resting == "Volta 6"


def test_the_timing_sits_apart_and_survives_a_notice(qt_app):
    status = StatusLine()
    status.set_timing(401.2)
    status.notify("Layout padrão restaurado")
    assert status.timing.text() == strings.STATUS_TIMING.format(elapsed=401.2)
    assert "ms" not in status.currentMessage()
    status.set_timing(None)
    assert status.timing.text() == ""


def test_lap_lines_no_longer_carry_the_timing():
    for template in (strings.STATUS_LAP_LOADED, strings.STATUS_LAP_COMPARED):
        assert "elapsed" not in template


# --- notice banner ---------------------------------------------------------------


def test_the_banner_is_hidden_until_there_is_something_to_say(qt_app):
    banner = NoticeBanner()
    assert banner.isHidden()
    banner.show_notes([])
    assert banner.isHidden()
    banner.show_notes(["", ""])
    assert banner.isHidden()


def test_a_single_note_reads_as_a_sentence(qt_app):
    banner = NoticeBanner()
    banner.show_notes(["Relógio corrigido."])
    assert not banner.isHidden()
    assert banner.body.text() == "Relógio corrigido."
    assert banner.title.text() == strings.NOTICE_WARNING


def test_several_notes_get_a_line_each(qt_app):
    banner = NoticeBanner()
    banner.show_notes(["Relógio corrigido.", "Carros diferentes."])
    lines = banner.body.text().split("\n")
    assert len(lines) == 2
    assert all(line.startswith("• ") for line in lines)
    assert banner.notes == ["Relógio corrigido.", "Carros diferentes."]


def test_warning_and_error_look_different(qt_app):
    banner = NoticeBanner()
    banner.show_notes(["a"], Severity.WARNING)
    assert banner.property("severity") == "warning"
    assert _drawn(banner.title) == theme.WARNING
    banner.show_notes(["b"], Severity.ERROR)
    assert banner.property("severity") == "error"
    assert banner.title.text() == strings.NOTICE_ERROR
    assert _drawn(banner.title) == theme.ERROR


def test_the_banner_can_be_dismissed_until_the_next_notes(qt_app):
    banner = NoticeBanner()
    banner.show_notes(["a"])
    banner.dismiss.click()
    assert banner.isHidden()
    banner.show_notes(["b"])
    assert not banner.isHidden()


def test_the_dismiss_button_is_named_for_screen_readers(qt_app):
    banner = NoticeBanner()
    assert banner.dismiss.accessibleName() == strings.NOTICE_DISMISS
    banner.show_notes(["Relógio corrigido."])
    assert "Relógio corrigido." in banner.accessibleName()


# --- commands --------------------------------------------------------------------


@pytest.fixture
def commands(qt_app):
    window = QtWidgets.QMainWindow()
    docks = [QtWidgets.QDockWidget("A", window), QtWidgets.QDockWidget("B", window)]
    actions = WindowActions(window, docks, enabled_rows={"speed"})
    actions.build_menus(window.menuBar())
    yield actions, window
    window.close()


def test_menu_and_toolbar_share_one_action(commands):
    actions, window = commands
    bar = actions.build_toolbar()
    menu_actions = {
        action for menu in window.menuBar().findChildren(QtWidgets.QMenu)
        for action in menu.actions()
    }
    for action in bar.actions():
        if not action.isSeparator():
            assert action in menu_actions, action.text()


def test_choosing_a_comparison_says_which(commands):
    actions, _window = commands
    chosen = []
    actions.comparison_chosen.connect(chosen.append)
    actions.comparison[ComparisonMode.IDEAL].trigger()
    assert chosen == [ComparisonMode.IDEAL]


def test_choosing_an_axis_says_which(commands):
    actions, _window = commands
    chosen = []
    actions.axis_chosen.connect(chosen.append)
    actions.axis_time.trigger()
    actions.axis_distance.trigger()
    assert chosen == [AxisMode.TIME, AxisMode.DISTANCE]


def test_channel_toggles_say_which_row(commands):
    actions, _window = commands
    toggled = []
    actions.channel_toggled.connect(lambda key, on: toggled.append((key, on)))
    assert actions.channels["speed"].isChecked()
    actions.channels["speed"].trigger()
    assert toggled == [("speed", False)]


def test_only_available_channels_are_offered(commands):
    actions, _window = commands
    actions.offer_channels({"speed"})
    assert actions.channels["speed"].isEnabled()
    assert not any(action.isEnabled()
                   for key, action in actions.channels.items() if key != "speed")


def test_one_comparison_is_checked_at_a_time(commands):
    actions, _window = commands
    actions.show_comparison(ComparisonMode.PINNED)
    actions.show_comparison(ComparisonMode.NONE)
    checked = [mode for mode, action in actions.comparison.items() if action.isChecked()]
    assert checked == [ComparisonMode.NONE]


# --- import runner -----------------------------------------------------------------


class _BlockingImporter:
    """An importer whose files wait for a go-ahead, so a run can be caught in
    the middle."""

    def __init__(self) -> None:
        self.release = threading.Event()
        self.imported: list[Path] = []

    @contextmanager
    def open(self):
        yield self

    def import_file(self, path: Path) -> None:
        self.release.wait(5.0)
        self.imported.append(path)


def _wait(condition, timeout_s: float = 10.0) -> bool:
    import time

    deadline = time.monotonic() + timeout_s
    while not condition() and time.monotonic() < deadline:
        QtCore.QCoreApplication.processEvents()
        time.sleep(0.01)
    QtCore.QCoreApplication.processEvents()
    return condition()


def test_the_runner_refuses_a_second_run_and_reports_the_first(qt_app):
    importer = _BlockingImporter()
    runner = ImportRunner(importer)
    busy, finished = [], []
    runner.busy_changed.connect(busy.append)
    runner.finished.connect(lambda n, failures: finished.append((n, failures)))

    assert runner.start([Path("a.duckdb"), Path("b.duckdb")]) is True
    assert runner.is_running
    assert runner.start([Path("c.duckdb")]) is False

    importer.release.set()
    assert _wait(lambda: not runner.is_running)
    assert busy == [True, False]
    assert finished == [(2, [])]
    assert importer.imported == [Path("a.duckdb"), Path("b.duckdb")]


def test_stopping_lets_the_current_file_finish_and_skips_the_rest(qt_app):
    importer = _BlockingImporter()
    runner = ImportRunner(importer)
    runner.start([Path("a.duckdb"), Path("b.duckdb"), Path("c.duckdb")])
    threading.Timer(0.05, importer.release.set).start()
    runner.stop()
    assert len(importer.imported) < 3


# --- the window only composes ------------------------------------------------------


def test_the_window_does_not_analyse():
    """What a lap looks like is worked out in `lap_view`; the window only hands
    it out. A pipeline import there means analysis crept back in."""
    source = (PRESENTATION / "main_window.py").read_text(encoding="utf-8")
    assert "import pipeline" not in source
    assert "pipeline." not in source


def test_short_labels_keep_the_official_number_only():
    assert lap_view.short_label("T6 Hairpin") == "T6"
    assert lap_view.short_label("T4.1 Esses") == "T4.1"
    assert lap_view.short_label("C4") == "C4"
    assert lap_view.short_label("Minha curva") == "Minha curva"


# --- the demo session --------------------------------------------------------------

DEMO_FILES = sorted(
    (Path(__file__).resolve().parent.parent / "data" / "demo").glob("*.duckdb")
)


@pytest.fixture
def demo_window(qt_app, tmp_path, monkeypatch):
    from lmu_telemetry.composition import build_gateways
    from lmu_telemetry.infrastructure.storage import importer, paths
    from lmu_telemetry.presentation.main_window import MainWindow

    if not DEMO_FILES:
        pytest.skip("no demo dataset in the tree")
    monkeypatch.setenv(paths.ENV_DATA_DIR, str(tmp_path / "data"))
    importer.import_session_file(DEMO_FILES[0])
    settings = QtCore.QSettings(
        str(tmp_path / "layout.ini"), QtCore.QSettings.Format.IniFormat
    )
    window = MainWindow(build_gateways(), settings)
    window.show()
    yield window
    window.close()


def test_the_view_compares_against_the_session_best_by_default(demo_window):
    window = demo_window
    view = lap_view.compose(window._sessions, window._selection,
                            ComparisonMode.SESSION_BEST, None)
    figures = view.figures
    assert figures is not None
    assert figures.comparing and figures.has_benchmark_lap
    assert figures.reference_index is not None
    assert figures.track_map is not None and figures.track_map.loss_classes is not None
    assert len(figures.corner_marks) == 16
    assert figures.seams == ()


def test_the_view_on_its_own_has_no_reference(demo_window):
    window = demo_window
    view = lap_view.compose(window._sessions, window._selection, ComparisonMode.NONE, None)
    figures = view.figures
    assert not figures.comparing
    assert figures.current.delta is None
    assert figures.track_map.loss_classes is None
    assert figures.status.startswith(f"Volta {window._selection.lap_number}")


def test_a_reference_from_another_track_is_refused_with_a_note(demo_window):
    from dataclasses import replace

    window = demo_window
    elsewhere = replace(window._selection, lap_index=1, track_name="Monza")
    view = lap_view.compose(window._sessions, window._selection,
                            ComparisonMode.PINNED, elsewhere)
    assert view.figures.current.benchmark is None
    assert any("pistas diferentes" in note for note in view.notes)


def test_pinning_the_lap_on_screen_compares_it_with_nothing(demo_window):
    window = demo_window
    view = lap_view.compose(window._sessions, window._selection,
                            ComparisonMode.PINNED, window._selection)
    assert not view.figures.comparing


def test_the_window_rests_on_the_lap_and_times_it_apart(demo_window):
    window = demo_window
    assert window.statusBar().currentMessage() == window.status.resting
    assert window.status.resting.startswith(f"Volta {window._selection.lap_number}")
    assert window.status.timing.text().endswith("ms")


def test_the_pdf_context_follows_what_is_drawn(demo_window):
    from lmu_telemetry.presentation.exporting import report_context

    window = demo_window
    context = report_context(window._current)
    assert context.track_name == window._selection.track_name
    # A comparison is on screen, so the map is coloured by loss, as on screen.
    assert context.map_scheme == "loss"
    assert context.corner_rows == window._current.corner_rows
