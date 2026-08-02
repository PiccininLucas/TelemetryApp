"""The main window: browser on the left, charts in the centre.

Phase 5 fills two of the three regions the specification describes. The right
panel - track map, g-g diagram, corner table, consistency - arrives with the
phases that compute what goes in it, and the splitter is already laid out to
take it.
"""

from __future__ import annotations

import time
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from lmu_telemetry import pipeline
from lmu_telemetry.core.errors import TelemetryError
from lmu_telemetry.ingest.session_loader import Session, load_session
from lmu_telemetry.logging_config import get_logger
from lmu_telemetry.storage import catalog, importer
from lmu_telemetry.ui import strings, theme
from lmu_telemetry.ui.chart_panel import AxisMode, SpeedChart
from lmu_telemetry.ui.session_browser import (
    LapSelection, SessionBrowser, format_lap_time,
)

logger = get_logger(__name__)


class OpenSession:
    """Holds the one session that is currently open, and its analysed laps.

    Only one session file is kept open at a time. Opening a session costs about
    80 ms and each lap's analysis a few tens of milliseconds, so caching the
    analysed laps makes moving between laps of one session instant, while
    holding a single connection keeps the file handles bounded no matter how
    long the application runs.
    """

    def __init__(self, session_id: str, session: Session, track_length_m: float | None):
        self.session_id = session_id
        self.session = session
        self.track_length_m = track_length_m
        self._laps: dict[int, pipeline.LapAnalysis | None] = {}

    def analysis_for(self, lap_index: int) -> pipeline.LapAnalysis | None:
        if lap_index not in self._laps:
            lap = next(
                (lap for lap in self.session.laps if lap.index == lap_index), None
            )
            self._laps[lap_index] = (
                pipeline.analyse_lap(self.session, lap, self.track_length_m)
                if lap is not None else None
            )
        return self._laps[lap_index]

    def close(self) -> None:
        self.session.close()


class MainWindow(QtWidgets.QMainWindow):
    """The application window."""

    def __init__(self) -> None:
        super().__init__()
        self._open: OpenSession | None = None
        self.setWindowTitle(strings.WINDOW_TITLE)
        self.resize(1280, 800)
        self._build()
        self._build_menus()
        self.reload_catalog(select_first=True)

    # -- construction ------------------------------------------------------

    def _build(self) -> None:
        central = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # The time-base warning banner, above everything. Hidden unless the
        # session being shown had its clock corrected - the specification asks
        # for it to be visible at the top, not buried in a log.
        self.warning_banner = QtWidgets.QLabel()
        self.warning_banner.setProperty("role", "warning")
        self.warning_banner.setWordWrap(True)
        self.warning_banner.hide()
        layout.addWidget(self.warning_banner)

        self.splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)

        self.browser = SessionBrowser()
        self.browser.lap_selected.connect(self.show_lap)
        self.splitter.addWidget(self.browser)

        self.chart = SpeedChart()
        self.splitter.addWidget(self.chart)

        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([440, 840])
        layout.addWidget(self.splitter, stretch=1)

        self.setCentralWidget(central)
        self.setStatusBar(QtWidgets.QStatusBar())
        self.statusBar().showMessage(strings.STATUS_READY)

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu(strings.MENU_FILE)

        import_action = QtGui.QAction(strings.ACTION_IMPORT, self)
        import_action.setShortcut(QtGui.QKeySequence.StandardKey.Open)
        import_action.triggered.connect(self.import_session)
        file_menu.addAction(import_action)

        import_folder = QtGui.QAction(strings.ACTION_IMPORT_FOLDER, self)
        import_folder.triggered.connect(self.import_folder)
        file_menu.addAction(import_folder)

        refresh = QtGui.QAction(strings.ACTION_REFRESH, self)
        refresh.setShortcut(QtGui.QKeySequence.StandardKey.Refresh)
        refresh.triggered.connect(lambda: self.reload_catalog())
        file_menu.addAction(refresh)

        file_menu.addSeparator()
        quit_action = QtGui.QAction(strings.ACTION_QUIT, self)
        quit_action.setShortcut(QtGui.QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        view_menu = self.menuBar().addMenu(strings.MENU_VIEW)
        axis_group = QtGui.QActionGroup(self)

        self.action_distance = QtGui.QAction(strings.ACTION_AXIS_DISTANCE, self)
        self.action_distance.setCheckable(True)
        self.action_distance.setChecked(True)
        self.action_distance.triggered.connect(
            lambda: self.chart.set_axis_mode(AxisMode.DISTANCE)
        )
        axis_group.addAction(self.action_distance)
        view_menu.addAction(self.action_distance)

        self.action_time = QtGui.QAction(strings.ACTION_AXIS_TIME, self)
        self.action_time.setCheckable(True)
        self.action_time.triggered.connect(
            lambda: self.chart.set_axis_mode(AxisMode.TIME)
        )
        axis_group.addAction(self.action_time)
        view_menu.addAction(self.action_time)

    # -- catalog -----------------------------------------------------------

    def reload_catalog(self, *, select_first: bool = False) -> None:
        n_sessions = self.browser.reload()
        if select_first and n_sessions:
            self.browser.select_default_lap()
        elif not n_sessions:
            self.statusBar().showMessage(strings.BROWSER_EMPTY)

    def import_session(self) -> None:
        paths, _filter = QtWidgets.QFileDialog.getOpenFileNames(
            self, strings.DIALOG_IMPORT_TITLE, "", strings.DIALOG_FILE_FILTER
        )
        if paths:
            self._import([Path(p) for p in paths])

    def import_folder(self) -> None:
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self, strings.DIALOG_IMPORT_FOLDER_TITLE
        )
        if folder:
            self._import(sorted(Path(folder).glob("*.duckdb")))

    def _import(self, paths: list[Path]) -> None:
        if not paths:
            return
        self.statusBar().showMessage(strings.STATUS_IMPORTING)
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)

        imported, failures = 0, []
        try:
            with catalog.connect() as con:
                for path in paths:
                    try:
                        importer.import_session_file(path, con=con)
                        imported += 1
                    except TelemetryError as exc:
                        logger.error("Import failed for %s: %s", path.name, exc)
                        failures.append(f"{path.name}: {exc}")
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

        self.reload_catalog(select_first=imported > 0)
        self.statusBar().showMessage(strings.STATUS_IMPORTED.format(n=imported))

        if failures:
            QtWidgets.QMessageBox.warning(
                self, strings.DIALOG_IMPORT_FAILED_TITLE, "\n".join(failures[:10])
            )

    # -- showing a lap -----------------------------------------------------

    def show_lap(self, selection: LapSelection) -> None:
        """Load and draw the chosen lap."""
        started = time.perf_counter()
        self.statusBar().showMessage(
            strings.STATUS_LOADING.format(name=Path(selection.source_path).name)
        )
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
        try:
            opened = self._ensure_open(selection)
            if opened is None:
                return

            # Before analysing: a session whose clock was corrected must show
            # the banner whether or not this particular lap can be drawn.
            self._update_warnings(opened.session)

            analysis = opened.analysis_for(selection.lap_index)
            if analysis is None:
                self.chart.clear()
                self.statusBar().showMessage(strings.CHART_NO_DATA)
                return

            self.chart.show_lap(
                analysis.grid_m, analysis.elapsed_s, analysis.speed_ms,
                title=f"{selection.track_name} · "
                      f"{strings.BROWSER_LAP_LABEL.format(number=selection.lap_number)} · "
                      f"{format_lap_time(analysis.time_s)}",
            )
            self.setWindowTitle(strings.WINDOW_TITLE_WITH_SESSION.format(
                track=selection.track_name, car=selection.car_name or "?"
            ))

            self.statusBar().showMessage(strings.STATUS_LAP_LOADED.format(
                number=selection.lap_number,
                time=format_lap_time(analysis.time_s),
                length=analysis.length_m,
                n_corners=len(analysis.corners),
                elapsed=(time.perf_counter() - started) * 1000.0,
            ))
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

    def _ensure_open(self, selection: LapSelection) -> OpenSession | None:
        """Open the selection's session, reusing it when it is already open."""
        if self._open is not None and self._open.session_id == selection.session_id:
            return self._open

        if self._open is not None:
            self._open.close()
            self._open = None

        try:
            track_length = None
            with catalog.connect() as con:
                track_length = catalog.track_length(con, selection.track_name)
            session = load_session(selection.source_path, with_hash=False)
        except TelemetryError as exc:
            logger.error("Could not open %s: %s", selection.source_path, exc)
            self.chart.clear()
            self.statusBar().showMessage(str(exc))
            self.warning_banner.setText(str(exc))
            self.warning_banner.show()
            return None

        self._open = OpenSession(selection.session_id, session, track_length)
        return self._open

    def _update_warnings(self, session: Session) -> None:
        """Show the session's warnings, the time-base correction above all."""
        if session.warnings:
            self.warning_banner.setText("  ".join(session.warnings))
            self.warning_banner.show()
        else:
            self.warning_banner.hide()

    # -- lifecycle ---------------------------------------------------------

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        if self._open is not None:
            self._open.close()
            self._open = None
        super().closeEvent(event)
