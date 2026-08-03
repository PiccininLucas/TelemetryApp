"""The main window: browser on the left, stacked traces in the centre.

Phase 6 turns the single speed plot into the comparison instrument: several
channels stacked on one shared X axis, a second lap overlaid, and the delta-t
between them.

The comparison is where the physics constrains the interface. Two laps can only
be compared in the *distance* domain, because two laps at the same elapsed time
are at different places on the circuit. So while a comparison is drawn the time
axis is disabled, and a reference lap from another circuit is refused outright
rather than plotted against a distance grid that means nothing.

The right panel - track map, g-g diagram, corner table, consistency - arrives
with the phases that compute what goes in it, and the splitter is already laid
out to take it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from lmu_telemetry import pipeline
from lmu_telemetry.analysis import ideal_lap
from lmu_telemetry.core.errors import SessionNameError, TelemetryError
from lmu_telemetry.core.models import Lap, LapFlag, parse_session_filename
from lmu_telemetry.export import charts, report, tables
from lmu_telemetry.ingest.session_loader import Session, load_session
from lmu_telemetry.logging_config import get_logger
from lmu_telemetry.storage import catalog, importer
from lmu_telemetry.ui import strings
from lmu_telemetry.ui.chart_panel import (
    ROW_SPECS, AxisMode, ChartStack, LapTrace,
)
from lmu_telemetry.ui.consistency_panel import ConsistencyPanel
from lmu_telemetry.ui.corner_table import CornerTable
from lmu_telemetry.ui.formatting import format_gap, format_lap_time
from lmu_telemetry.ui.gg_panel import FrictionPanel
from lmu_telemetry.ui.session_browser import LapSelection, SessionBrowser
from lmu_telemetry.ui.track_map import MapColour, TrackMap

logger = get_logger(__name__)


class ComparisonMode(str, Enum):
    """What the selected lap is drawn against."""

    #: One lap on its own.
    NONE = "none"
    #: The fastest comparable lap of the same session. The default: it answers
    #: "where did this lap lose time against my own best" without any setup.
    SESSION_BEST = "session_best"
    #: A lap the user pinned, possibly from another session, so a whole
    #: afternoon can be measured against one benchmark.
    PINNED = "pinned"
    #: The theoretical ideal lap, stitched from the best segment of every lap
    #: of the session. A target, not a record - see `IdealLap.CAVEAT`.
    IDEAL = "ideal"


@dataclass(slots=True)
class CurrentView:
    """Everything currently on screen, kept so it can be exported.

    Rebuilding it at export time would mean re-deriving the comparison and the
    ideal lap, and any divergence between the two derivations would produce a
    file that does not match what the user was looking at when they asked for
    it. Recording what was drawn is the only way to guarantee they agree.
    """

    selection: LapSelection
    primary: pipeline.LapAnalysis
    primary_label: str
    benchmark: pipeline.LapAnalysis | None = None
    benchmark_label: str = ""
    #: The same lap without the gap, for prose that supplies the gap itself.
    benchmark_summary: str = ""
    delta: object | None = None
    ideal: object | None = None
    corner_rows: list = field(default_factory=list)
    consistency: object | None = None


class OpenSession:
    """One open session file and its analysed laps.

    Opening a session costs about 80 ms and each lap's analysis a few tens of
    milliseconds, so caching the analysed laps makes moving between laps of one
    session instant.
    """

    def __init__(
        self, session_id: str, session: Session, track_length_m: float | None
    ) -> None:
        self.session_id = session_id
        self.session = session
        self.track_length_m = track_length_m
        self._laps: dict[int, pipeline.LapAnalysis | None] = {}
        self._session_analysis: pipeline.SessionAnalysis | None = None
        #: `(distance_m, name)` for every corner the user has named at this
        #: track, applied to each lap as it is analysed.
        self.corner_references: list[tuple[float, str]] = []

    def analysis_for(self, lap_index: int) -> pipeline.LapAnalysis | None:
        if lap_index not in self._laps:
            lap = self._lap(lap_index)
            self._laps[lap_index] = (
                pipeline.analyse_lap(self.session, lap, self.track_length_m)
                if lap is not None else None
            )
        analysis = self._laps[lap_index]
        if analysis is not None:
            pipeline.name_corners(analysis, self.corner_references)
        return analysis

    def rename_corner(self, distance_m: float, name: str) -> None:
        """Apply a new name immediately, without re-analysing the session."""
        self.corner_references = [
            (d, n) for d, n in self.corner_references if d != distance_m
        ] + [(distance_m, name)]
        for analysis in self._laps.values():
            if analysis is not None:
                pipeline.name_corners(analysis, self.corner_references)
        # The ideal lap and the consistency report snapshot the labels, so they
        # have to be rebuilt rather than patched.
        self._session_analysis = None

    def _lap(self, lap_index: int) -> Lap | None:
        return next((lap for lap in self.session.laps if lap.index == lap_index), None)

    def session_analysis(self) -> pipeline.SessionAnalysis:
        """Every comparable lap analysed, and the ideal lap built from them.

        Cached: it costs a few tens of milliseconds per lap, so a thirteen-lap
        race is about half a second. Paid once, on the first request, rather
        than on opening a session that the user may only want one lap of.
        """
        if self._session_analysis is None:
            self._session_analysis = pipeline.analyse_session(
                self.session, self.track_length_m,
                corner_references=self.corner_references,
            )
        return self._session_analysis

    def best_comparable_lap(self, exclude_index: int | None = None) -> Lap | None:
        """The session's fastest comparable lap, ignoring one index.

        Read from the lap list rather than from the analyses, so choosing the
        benchmark does not require analysing every lap of the session first.
        """
        candidates = [
            lap for lap in self.session.comparable_laps
            if lap.index != exclude_index and lap.time_s > 0
        ]
        return min(candidates, key=lambda lap: lap.time_s, default=None)

    def close(self) -> None:
        self.session.close()


class SessionPool:
    """The open session files, at most `capacity` of them.

    Two is enough: the interface never draws more than two laps at once, and a
    comparison against a pinned lap from another afternoon needs both files
    open. Beyond that, holding files open only leaks handles.
    """

    def __init__(self, capacity: int = 2) -> None:
        self._capacity = capacity
        self._open: dict[str, OpenSession] = {}
        #: Session ids, least recently used first.
        self._order: list[str] = []

    def get(self, selection: LapSelection) -> OpenSession:
        """Open the selection's session, reusing it when it is already open.

        Raises:
            TelemetryError: When the file cannot be read.
        """
        session_id = selection.session_id
        if session_id in self._open:
            self._touch(session_id)
            return self._open[session_id]

        with catalog.connect() as con:
            track_length = catalog.track_length(con, selection.track_name)
            references = [
                (reference.reference_distance_m, reference.name)
                for reference in catalog.corner_references(con, selection.track_name)
                if reference.reference_distance_m is not None and reference.name
            ]
        session = load_session(selection.source_path, with_hash=False)

        self._open[session_id] = OpenSession(session_id, session, track_length)
        self._open[session_id].corner_references = references
        self._touch(session_id)
        self._evict()
        return self._open[session_id]

    def _touch(self, session_id: str) -> None:
        if session_id in self._order:
            self._order.remove(session_id)
        self._order.append(session_id)

    def _evict(self) -> None:
        while len(self._order) > self._capacity:
            oldest = self._order.pop(0)
            self._open.pop(oldest).close()

    def all(self) -> list[OpenSession]:
        return list(self._open.values())

    def close_all(self) -> None:
        for opened in self._open.values():
            opened.close()
        self._open.clear()
        self._order.clear()

    def __len__(self) -> int:
        return len(self._open)


class MainWindow(QtWidgets.QMainWindow):
    """The application window."""

    def __init__(self) -> None:
        super().__init__()
        self._sessions = SessionPool()
        self._selection: LapSelection | None = None
        self._current: CurrentView | None = None
        self._pinned: LapSelection | None = None
        self._mode = ComparisonMode.SESSION_BEST
        self.setWindowTitle(strings.WINDOW_TITLE)
        self.resize(1360, 880)
        self._build()
        self._build_menus()
        self.reload_catalog(select_first=True)

    # -- construction ------------------------------------------------------

    def _build(self) -> None:
        central = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # The warning banner, above everything. Hidden unless the session being
        # shown had its clock corrected, or a comparison had to be refused.
        self.warning_banner = QtWidgets.QLabel()
        self.warning_banner.setProperty("role", "warning")
        self.warning_banner.setWordWrap(True)
        self.warning_banner.hide()
        layout.addWidget(self.warning_banner)

        self.splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)

        self.browser = SessionBrowser()
        self.browser.lap_selected.connect(self.show_lap)
        self.splitter.addWidget(self.browser)

        # The centre column: the traces, and under them the corner-by-corner
        # debrief they support. The table sits below rather than beside because
        # its rows are read against the same distance axis as the traces.
        self.centre = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        self.chart = ChartStack()
        self.corner_table = CornerTable()
        self.consistency = ConsistencyPanel()

        # Tabs rather than another split: both are per-corner tables of the
        # same lap, and stacking a third pane would leave every one of them too
        # short to read.
        self.tabs = QtWidgets.QTabWidget()
        self.tabs.addTab(self.corner_table, strings.CORNERS_TAB)
        self.tabs.addTab(self.consistency, strings.CONSISTENCY_TAB)

        self.centre.addWidget(self.chart)
        self.centre.addWidget(self.tabs)
        self.centre.setStretchFactor(0, 3)
        self.centre.setStretchFactor(1, 1)
        self.centre.setSizes([600, 300])
        self.splitter.addWidget(self.centre)

        self.corner_table.corner_selected.connect(self._on_cursor_moved)
        self.corner_table.corner_zoomed.connect(self.chart.zoom_to)
        self.corner_table.corner_renamed.connect(self.rename_corner)
        self.consistency.corner_selected.connect(self._on_cursor_moved)
        self.consistency.stint_changed.connect(self._on_stint_changed)

        # The right column: where the lap happened, and how hard the tyres were
        # worked doing it. Both follow the traces' cursor, and the map drives it
        # back - picking a corner on the map is how a driver thinks about a lap.
        self.side = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        self.track_map = TrackMap()
        self.friction = FrictionPanel()
        self.side.addWidget(self.track_map)
        self.side.addWidget(self.friction)
        self.side.setSizes([460, 420])
        self.splitter.addWidget(self.side)

        self.chart.cursor_moved.connect(self._on_cursor_moved)
        self.track_map.distance_picked.connect(self._on_cursor_moved)

        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 0)
        self.splitter.setSizes([380, 800, 420])
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
        self._build_export_actions(file_menu)

        file_menu.addSeparator()
        quit_action = QtGui.QAction(strings.ACTION_QUIT, self)
        quit_action.setShortcut(QtGui.QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        view_menu = self.menuBar().addMenu(strings.MENU_VIEW)
        self._build_axis_actions(view_menu)
        view_menu.addSeparator()
        self._build_channel_actions(view_menu)
        self._build_panel_actions(view_menu)
        view_menu.addSeparator()
        self._build_comparison_actions(view_menu)

    def _build_export_actions(self, menu: QtWidgets.QMenu) -> None:
        export_menu = menu.addMenu(strings.MENU_EXPORT)
        for label, handler in (
            (strings.ACTION_EXPORT_PNG, self.export_png),
            (strings.ACTION_EXPORT_CSV, self.export_csv),
            (strings.ACTION_EXPORT_CORNERS_CSV, self.export_corners_csv),
            (strings.ACTION_EXPORT_PDF, self.export_pdf),
        ):
            action = QtGui.QAction(label, self)
            action.triggered.connect(handler)
            export_menu.addAction(action)

    def _build_axis_actions(self, menu: QtWidgets.QMenu) -> None:
        axis_group = QtGui.QActionGroup(self)

        self.action_distance = QtGui.QAction(strings.ACTION_AXIS_DISTANCE, self)
        self.action_distance.setCheckable(True)
        self.action_distance.setChecked(True)
        self.action_distance.triggered.connect(
            lambda: self.chart.set_axis_mode(AxisMode.DISTANCE)
        )
        axis_group.addAction(self.action_distance)
        menu.addAction(self.action_distance)

        self.action_time = QtGui.QAction(strings.ACTION_AXIS_TIME, self)
        self.action_time.setCheckable(True)
        self.action_time.setToolTip(strings.ACTION_AXIS_TIME_BLOCKED)
        self.action_time.triggered.connect(
            lambda: self.chart.set_axis_mode(AxisMode.TIME)
        )
        axis_group.addAction(self.action_time)
        menu.addAction(self.action_time)

    def _build_channel_actions(self, menu: QtWidgets.QMenu) -> None:
        channels = menu.addMenu(strings.MENU_CHANNELS)
        self.channel_actions: dict[str, QtGui.QAction] = {}

        for spec in ROW_SPECS:
            action = QtGui.QAction(spec.axis_label, self)
            action.setCheckable(True)
            action.setChecked(self.chart.is_row_enabled(spec.key))
            action.toggled.connect(
                lambda checked, key=spec.key: self.chart.set_row_enabled(key, checked)
            )
            channels.addAction(action)
            self.channel_actions[spec.key] = action

    def _build_panel_actions(self, menu: QtWidgets.QMenu) -> None:
        panels = menu.addMenu(strings.MENU_PANELS)

        for label, widget in (
            (strings.ACTION_PANEL_MAP, self.track_map),
            (strings.ACTION_PANEL_GG, self.friction),
        ):
            action = QtGui.QAction(label, self)
            action.setCheckable(True)
            action.setChecked(True)
            action.toggled.connect(widget.setVisible)
            panels.addAction(action)

        panels.addSeparator()
        colour_group = QtGui.QActionGroup(self)
        self.map_colour_actions: dict[MapColour, QtGui.QAction] = {}
        for mode, label in (
            (MapColour.PEDALS, strings.MAP_COLOUR_PEDALS),
            (MapColour.DELTA, strings.MAP_COLOUR_DELTA),
        ):
            action = QtGui.QAction(label, self)
            action.setCheckable(True)
            action.setChecked(mode is MapColour.PEDALS)
            action.triggered.connect(
                lambda _checked, m=mode: self.track_map.set_colour_mode(m)
            )
            colour_group.addAction(action)
            panels.addAction(action)
            self.map_colour_actions[mode] = action

        panels.addSeparator()
        self.action_integrated = QtGui.QAction(strings.MAP_SHOW_INTEGRATED, self)
        self.action_integrated.setCheckable(True)
        self.action_integrated.setToolTip(strings.MAP_INTEGRATED_UNAVAILABLE)
        self.action_integrated.toggled.connect(self.track_map.set_integrated_visible)
        panels.addAction(self.action_integrated)

    def _build_comparison_actions(self, menu: QtWidgets.QMenu) -> None:
        compare = menu.addMenu(strings.MENU_COMPARE)
        group = QtGui.QActionGroup(self)

        self.comparison_actions: dict[ComparisonMode, QtGui.QAction] = {}
        for mode, label in (
            (ComparisonMode.NONE, strings.ACTION_COMPARE_NONE),
            (ComparisonMode.SESSION_BEST, strings.ACTION_COMPARE_BEST),
            (ComparisonMode.PINNED, strings.ACTION_COMPARE_PINNED),
            (ComparisonMode.IDEAL, strings.ACTION_COMPARE_IDEAL),
        ):
            action = QtGui.QAction(label, self)
            action.setCheckable(True)
            action.setChecked(mode is self._mode)
            action.triggered.connect(
                lambda _checked, m=mode: self.set_comparison_mode(m)
            )
            group.addAction(action)
            compare.addAction(action)
            self.comparison_actions[mode] = action

        compare.addSeparator()
        pin = QtGui.QAction(strings.ACTION_PIN_REFERENCE, self)
        pin.setShortcut(QtGui.QKeySequence("Ctrl+R"))
        pin.triggered.connect(self.pin_current_lap)
        compare.addAction(pin)

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

    # -- comparison --------------------------------------------------------

    def set_comparison_mode(self, mode: ComparisonMode) -> None:
        """Change what the selected lap is drawn against, and redraw."""
        self._mode = mode
        if mode is ComparisonMode.PINNED and self._pinned is None:
            self.statusBar().showMessage(strings.STATUS_NO_REFERENCE_PINNED)
        if self._selection is not None:
            self.show_lap(self._selection)

    def pin_current_lap(self) -> None:
        """Pin the lap on screen as the benchmark every other lap is measured
        against, and switch to that mode."""
        if self._selection is None:
            return
        self._pinned = self._selection
        self.statusBar().showMessage(
            strings.STATUS_REFERENCE_PINNED.format(number=self._selection.lap_number)
        )
        self.comparison_actions[ComparisonMode.PINNED].setChecked(True)
        self.set_comparison_mode(ComparisonMode.PINNED)

    def _benchmark_selection(self, selection: LapSelection) -> LapSelection | None:
        """Which lap the selected one is compared against, or None."""
        if self._mode is ComparisonMode.NONE:
            return None

        if self._mode is ComparisonMode.PINNED:
            pinned = self._pinned
            if pinned is None:
                return None
            if (pinned.session_id == selection.session_id
                    and pinned.lap_index == selection.lap_index):
                return None
            return pinned

        # SESSION_BEST: read from the already-open session's lap list.
        opened = self._sessions.get(selection)
        best = opened.best_comparable_lap(exclude_index=selection.lap_index)
        if best is None:
            return None
        return LapSelection(
            session_id=selection.session_id,
            source_path=selection.source_path,
            lap_index=best.index,
            lap_number=best.number,
            track_name=selection.track_name,
            car_name=selection.car_name,
            time_s=best.time_s,
            is_comparable=True,
            session_started_at=selection.session_started_at,
        )

    # -- showing a lap -----------------------------------------------------

    def show_lap(self, selection: LapSelection) -> None:
        """Load and draw the chosen lap, with its comparison."""
        started = time.perf_counter()
        self._selection = selection
        self.statusBar().showMessage(
            strings.STATUS_LOADING.format(name=Path(selection.source_path).name)
        )
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
        try:
            self._show_lap(selection, started)
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

    def _show_lap(self, selection: LapSelection, started: float) -> None:
        notes: list[str] = []

        try:
            opened = self._sessions.get(selection)
        except TelemetryError as exc:
            self._fail(selection, exc)
            return

        # Before analysing: a session whose clock was corrected must show the
        # banner whether or not this particular lap can be drawn.
        notes.extend(opened.session.warnings)

        primary = opened.analysis_for(selection.lap_index)
        if primary is None:
            self._clear_panels()
            self._set_warnings(notes)
            self.statusBar().showMessage(strings.CHART_NO_DATA)
            return

        # The whole session is analysed either way: it costs about 16 ms per
        # lap, and it is what the corner table's "what is this corner worth"
        # column is computed from. Cached on the open session, so this is paid
        # once per file rather than once per lap viewed.
        ideal = opened.session_analysis().ideal

        benchmark, benchmark_selection, benchmark_trace = None, None, None
        delta = None

        if self._mode is ComparisonMode.IDEAL:
            if ideal is None:
                notes.append(strings.IDEAL_UNAVAILABLE)
            else:
                delta = pipeline.delta_against_ideal(ideal, primary)
                benchmark_trace = LapTrace(
                    label=strings.CHART_LEGEND_IDEAL.format(
                        time=format_lap_time(ideal.total_time_s),
                        gap=format_gap(delta.final_delta_s),
                    ),
                    grid_m=ideal.grid_m,
                    elapsed_s=ideal.elapsed_s,
                    # Only speed is stitched: the ideal lap has no pedal or
                    # steering trace, because no one ever drove it. Showing an
                    # invented one would be the first lie in the application.
                    channels={"Ground Speed": ideal.speed_ms},
                )
        else:
            benchmark, benchmark_selection = self._load_benchmark(selection, notes)
            if benchmark is not None:
                delta = pipeline.delta_between(benchmark, primary)
                benchmark_trace = _trace(
                    strings.CHART_LEGEND_BENCHMARK.format(
                        number=benchmark_selection.lap_number,
                        time=format_lap_time(benchmark.time_s),
                        gap=format_gap(delta.final_delta_s),
                    ),
                    benchmark,
                )

        self.chart.show_laps(
            primary=_trace(
                strings.CHART_LEGEND_PRIMARY.format(
                    number=selection.lap_number,
                    time=format_lap_time(primary.time_s),
                ),
                primary,
            ),
            benchmark=benchmark_trace,
            delta_grid_m=None if delta is None else delta.grid_m,
            delta_s=None if delta is None else delta.delta_s,
        )
        self._show_markers(primary, ideal)
        corner_rows = self._show_corner_table(primary, benchmark, ideal)
        self._show_consistency(opened, selection.lap_index)
        stint = opened.session_analysis().stint_of(selection.lap_index)

        self._current = CurrentView(
            selection=selection,
            primary=primary,
            primary_label=strings.CHART_LEGEND_PRIMARY.format(
                number=selection.lap_number,
                time=format_lap_time(primary.time_s),
            ),
            benchmark=benchmark,
            benchmark_label=(
                "" if benchmark_trace is None else benchmark_trace.label
            ),
            benchmark_summary=_benchmark_summary(
                benchmark, benchmark_selection, ideal, self._mode
            ),
            delta=delta,
            ideal=ideal,
            corner_rows=corner_rows,
            consistency=None if stint is None else stint.report,
        )
        self._show_side_panels(primary, delta)
        self._sync_actions(comparing=benchmark_trace is not None)
        self._set_warnings(notes)

        self.setWindowTitle(strings.WINDOW_TITLE_WITH_SESSION.format(
            track=selection.track_name, car=selection.car_name or "?"
        ))
        self._report(selection, primary, benchmark_selection, delta, started)

    def _show_markers(self, primary: pipeline.LapAnalysis, ideal) -> None:
        """Corner apexes on every lap, and the ideal lap's seams when shown."""
        self.chart.set_corner_markers(
            [corner.apex_distance_m for corner in primary.corners],
            [corner.label for corner in primary.corners],
        )
        seams = []
        if ideal is not None and self._mode is ComparisonMode.IDEAL:
            seams = [
                seam.distance_m
                for seam in ideal_lap.significant_discontinuities(ideal)
            ]
        self.chart.set_seam_markers(seams)

    def _show_corner_table(
        self,
        primary: pipeline.LapAnalysis,
        benchmark: pipeline.LapAnalysis | None,
        ideal,
    ) -> list:
        rows = pipeline.corner_rows(primary, benchmark, ideal)
        self.corner_table.show_corners(
            rows,
            ideal_summary=_ideal_summary(ideal),
            show_comparison=benchmark is not None,
            show_ideal=ideal is not None,
        )
        return rows

    def _show_consistency(self, opened: OpenSession, lap_index: int) -> None:
        """Show the stint the lap on screen belongs to.

        Following the selected lap rather than always opening on the first
        stint: the driver is asking about the run they just did.
        """
        analysis = opened.session_analysis()
        stints = analysis.stints
        if not stints:
            self.consistency.clear()
            return

        stint = analysis.stint_of(lap_index)
        self.consistency.show_stints(
            stints, current_index=0 if stint is None else stint.index
        )

    def _on_stint_changed(self, index: int) -> None:
        """The user picked a different stint from the selector."""
        if self._selection is None:
            return
        try:
            opened = self._sessions.get(self._selection)
        except TelemetryError:
            return
        stints = opened.session_analysis().stints
        if 0 <= index < len(stints):
            stint = stints[index]
            self.consistency.show_report(stint.report, list(stint.lap_indices))

    def rename_corner(
        self, corner_index: int, distance_m: float, name: str
    ) -> None:
        """Store a corner's name and apply it everywhere, at once.

        Written against the track, anchored to the distance, so it survives
        re-importing every session ever recorded there.
        """
        if self._selection is None:
            return
        with catalog.connect() as con:
            catalog.set_corner_name(
                con, catalog.track_id_for(self._selection.track_name),
                corner_index, name, distance_m,
            )
        for opened in self._sessions.all():
            opened.rename_corner(distance_m, name)
        logger.info("Corner at %.0f m named %r", distance_m, name)
        self.show_lap(self._selection)

    def _load_benchmark(
        self, selection: LapSelection, notes: list[str]
    ) -> tuple[pipeline.LapAnalysis | None, LapSelection | None]:
        """The benchmark lap's analysis, refusing comparisons that cannot mean
        anything."""
        benchmark_selection = self._benchmark_selection(selection)
        if benchmark_selection is None:
            return None, None

        # A distance grid only compares two laps if they ran the same track.
        # 4 000 m into Monza and 4 000 m into Le Mans are different corners, and
        # the delta between them would be a number with no referent.
        if benchmark_selection.track_name != selection.track_name:
            notes.append(strings.WARN_COMPARE_DIFFERENT_TRACK.format(
                track_a=selection.track_name, track_b=benchmark_selection.track_name
            ))
            return None, None

        if (benchmark_selection.car_name or "?") != (selection.car_name or "?"):
            # Not refused: comparing two cars around one circuit is a legitimate
            # thing to want. Only flagged, because the delta then measures the
            # car as much as the driving.
            notes.append(strings.WARN_COMPARE_DIFFERENT_CAR.format(
                car_a=selection.car_name or "?",
                car_b=benchmark_selection.car_name or "?",
            ))

        try:
            opened = self._sessions.get(benchmark_selection)
        except TelemetryError as exc:
            logger.warning("Could not open the reference session: %s", exc)
            return None, None

        analysis = opened.analysis_for(benchmark_selection.lap_index)
        return (analysis, benchmark_selection) if analysis is not None else (None, None)

    def _show_side_panels(self, primary: pipeline.LapAnalysis, delta) -> None:
        """Fill the track map and the g-g diagram for the lap on screen."""
        self._show_track_map(primary, delta)
        self._show_friction(primary)

    def _show_track_map(self, primary: pipeline.LapAnalysis, delta) -> None:
        gps, integrated = pipeline.track_paths(primary)
        if gps is None or not len(gps.x_m):
            self.track_map.clear()
            self.action_integrated.setEnabled(False)
            return

        caption = strings.MAP_EXTENT.format(
            width=gps.extent_m[0], height=gps.extent_m[1],
            closure=gps.closure_error_m,
        )

        self.action_integrated.setEnabled(integrated is not None)
        if integrated is not None:
            aligned = pipeline.align_paths(gps, integrated)
            self.track_map.show_integrated(aligned.x_m, aligned.y_m)
            comparison = pipeline.compare_track_paths(gps, integrated)
            caption += "\n" + strings.MAP_INTEGRATED_ERROR.format(
                mean=comparison.mean_error_m, max=comparison.max_error_m
            )

        self.track_map.show_path(
            gps.x_m, gps.y_m, primary.grid_m,
            pedal_states=pipeline.pedal_states(primary),
            loss_classes=(None if delta is None
                          else pipeline.loss_classes_on(primary.grid_m, delta)),
            caption=caption,
        )

        # Opening on the delta colouring whenever there is a comparison: it is
        # the reason the panel exists, and having to find a menu item to see
        # where the time went makes the map decorative.
        available = self.track_map.available_modes()
        preferred = (MapColour.DELTA if MapColour.DELTA in available
                     else MapColour.PEDALS)
        self.track_map.set_colour_mode(preferred)
        for mode, action in self.map_colour_actions.items():
            action.setEnabled(mode in available)
            action.setChecked(mode is self.track_map.colour_mode)

    def _show_friction(self, primary: pipeline.LapAnalysis) -> None:
        envelope = pipeline.friction_envelope(primary)
        if envelope is None or not envelope.is_valid:
            self.friction.clear()
            return
        self.friction.show_envelope(
            envelope,
            primary.lateral_g, primary.longitudinal_g, primary.grid_m,
            pipeline.transition_quality(primary),
        )

    def _on_cursor_moved(self, distance_m: float) -> None:
        """One cursor for the whole window.

        Whichever panel the mouse is over drives the other two, so a point on
        the speed trace, a point on the circuit and a point in the friction
        envelope are always the same instant of the lap.
        """
        self.chart.set_cursor_distance(distance_m)
        self.track_map.set_cursor_distance(distance_m)
        self.friction.set_cursor_distance(distance_m)
        self.corner_table.select_corner_at(distance_m)

    def _report(
        self,
        selection: LapSelection,
        primary: pipeline.LapAnalysis,
        benchmark_selection: LapSelection | None,
        delta,
        started: float,
    ) -> None:
        elapsed_ms = (time.perf_counter() - started) * 1000.0

        if delta is None:
            self.statusBar().showMessage(strings.STATUS_LAP_LOADED.format(
                number=selection.lap_number,
                time=format_lap_time(primary.time_s),
                length=primary.length_m,
                n_corners=len(primary.corners),
                elapsed=elapsed_ms,
            ))
            return

        reference = (
            strings.STATUS_REFERENCE_IDEAL if benchmark_selection is None
            else strings.STATUS_REFERENCE_LAP.format(
                number=benchmark_selection.lap_number
            )
        )
        self.statusBar().showMessage(strings.STATUS_LAP_COMPARED.format(
            number=selection.lap_number,
            time=format_lap_time(primary.time_s),
            gap=format_gap(delta.final_delta_s),
            reference=reference,
            loss=format_gap(delta.worst_loss_s),
            loss_at=delta.worst_loss_distance_m,
            elapsed=elapsed_ms,
        ))

    def _sync_actions(self, *, comparing: bool) -> None:
        """Keep the menu honest about what is currently possible.

        The time axis is disabled while two laps are drawn: at equal elapsed
        times they are at different points of the circuit, so an overlay on that
        axis would invite a comparison that says nothing.
        """
        self.action_time.setEnabled(not comparing)
        if comparing and self.chart.axis_mode is AxisMode.TIME:
            self.chart.set_axis_mode(AxisMode.DISTANCE)
            self.action_distance.setChecked(True)

        available = self.chart.available_rows()
        for key, action in self.channel_actions.items():
            action.setEnabled(key in available)

    def _clear_panels(self) -> None:
        self._current = None
        self.chart.clear()
        self.corner_table.clear()
        self.consistency.clear()
        self.track_map.clear()
        self.friction.clear()

    def _fail(self, selection: LapSelection, exc: Exception) -> None:
        logger.error("Could not open %s: %s", selection.source_path, exc)
        self._clear_panels()
        self.statusBar().showMessage(str(exc))
        self._set_warnings([str(exc)])

    def _set_warnings(self, notes: list[str]) -> None:
        if notes:
            self.warning_banner.setText("  ".join(notes))
            self.warning_banner.show()
        else:
            self.warning_banner.hide()

    # -- export ------------------------------------------------------------

    def export_png(self) -> None:
        """Redraw the traces at print quality and save them."""
        def render(path: Path, _dialect) -> None:
            view = self._current
            charts.export_lap_charts(
                path, view.primary, view.primary_label,
                view.benchmark, view.benchmark_label, view.delta,
                view.primary.corners,
            )

        self._export(
            strings.DIALOG_EXPORT_PNG_TITLE, strings.DIALOG_PNG_FILTER,
            ".png", render,
        )

    def export_csv(self) -> None:
        """Every channel of the lap, one row per metre."""
        def render(path: Path, dialect) -> None:
            view = self._current
            tables.write_lap(path, view.primary, view.delta, dialect)

        self._export(
            strings.DIALOG_EXPORT_CSV_TITLE, strings.DIALOG_CSV_FILTER,
            ".csv", render,
        )

    def export_corners_csv(self) -> None:
        def render(path: Path, dialect) -> None:
            tables.write_corners(path, self._current.corner_rows, dialect)

        self._export(
            strings.DIALOG_EXPORT_CORNERS_TITLE, strings.DIALOG_CSV_FILTER,
            ".csv", render,
        )

    def export_pdf(self) -> None:
        """The whole debrief, with its caveats, in one document."""
        def render(path: Path, _dialect) -> None:
            report.write_report(path, self._report_context())

        self._export(
            strings.DIALOG_EXPORT_PDF_TITLE, strings.DIALOG_PDF_FILTER,
            ".pdf", render,
        )

    def _export(
        self, title: str, file_filter: str, suffix: str, render
    ) -> None:
        """Ask where to save, then render there.

        One place for the parts every export shares: refusing when there is
        nothing on screen, appending the extension the user left off, choosing
        the CSV dialect from the filter they picked, and turning a failure into
        a message instead of a traceback behind the window.
        """
        if self._current is None:
            self.statusBar().showMessage(strings.ERR_EXPORT_NO_LAP)
            return

        path_text, chosen = QtWidgets.QFileDialog.getSaveFileName(
            self, title, self._suggested_name(suffix), file_filter
        )
        if not path_text:
            return

        path = Path(path_text)
        if not path.suffix:
            path = path.with_suffix(suffix)

        dialect = (tables.EXCEL_PT_BR
                   if chosen == strings.DIALOG_CSV_FILTER_EXCEL
                   else tables.STANDARD)

        self.statusBar().showMessage(strings.STATUS_EXPORTING)
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
        try:
            render(path, dialect)
        except Exception as exc:  # noqa: BLE001 - a failed save is survivable
            logger.exception("Export to %s failed", path)
            self.statusBar().showMessage(
                strings.ERR_EXPORT_FAILED.format(detail=exc)
            )
            QtWidgets.QMessageBox.warning(
                self, title, strings.ERR_EXPORT_FAILED.format(detail=exc)
            )
            return
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

        self.statusBar().showMessage(strings.STATUS_EXPORTED.format(path=path))

    def _suggested_name(self, suffix: str) -> str:
        """A file name that says what is in it without being opened."""
        if self._current is None:
            return ""
        selection = self._current.selection
        track = "".join(
            character for character in selection.track_name
            if character.isalnum() or character in " -_"
        ).strip().replace(" ", "-")
        return f"{track}-volta{selection.lap_number}{suffix}"

    def _report_context(self) -> report.ReportContext:
        """Gather everything the PDF needs from what is currently drawn."""
        view = self._current
        selection = view.selection

        gps, _integrated = pipeline.track_paths(view.primary)
        track_path = None if gps is None or not len(gps.x_m) else (
            gps.x_m, gps.y_m
        )

        # The map is coloured the same way it is on screen: by where time moved
        # when there is a comparison, by pedal state when there is not.
        map_classes = map_colours = None
        if track_path is not None:
            if view.delta is not None:
                map_classes = pipeline.loss_classes_on(
                    view.primary.grid_m, view.delta
                )
                map_colours = charts.LOSS_COLOURS
            else:
                map_classes = pipeline.pedal_states(view.primary)
                map_colours = charts.PEDAL_COLOURS

        return report.ReportContext(
            track_name=selection.track_name,
            car_name=selection.car_name or "?",
            session_label=strings.session_type_label(
                _session_code(selection) or "?"
            ),
            session_date=selection.session_started_at,
            lap_number=selection.lap_number,
            primary=view.primary,
            primary_label=view.primary_label,
            benchmark=view.benchmark,
            benchmark_label=view.benchmark_label,
            benchmark_summary=view.benchmark_summary,
            delta=view.delta,
            corner_rows=view.corner_rows,
            ideal=view.ideal,
            consistency=view.consistency,
            envelope=pipeline.friction_envelope(view.primary),
            transition_quality=pipeline.transition_quality(view.primary),
            track_path=track_path,
            map_classes=map_classes,
            map_colours=map_colours,
        )

    # -- lifecycle ---------------------------------------------------------

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        self._sessions.close_all()
        super().closeEvent(event)


def _benchmark_summary(
    benchmark, benchmark_selection, ideal, mode: ComparisonMode
) -> str:
    """Name the reference plainly, for prose that states the gap separately."""
    if mode is ComparisonMode.IDEAL and ideal is not None:
        return f"{strings.STATUS_REFERENCE_IDEAL} · " \
               f"{format_lap_time(ideal.total_time_s)}"
    if benchmark is None or benchmark_selection is None:
        return ""
    return (
        f"{strings.STATUS_REFERENCE_LAP.format(number=benchmark_selection.lap_number)}"
        f" · {format_lap_time(benchmark.time_s)}"
    )


def _session_code(selection: LapSelection) -> str | None:
    """The session type letter, read back out of the source file's name.

    `LapSelection` does not carry it - the browser never needed it - and the
    file name is the authoritative source anyway, since that is where the
    catalog itself got it from.
    """
    try:
        _track, code, _when = parse_session_filename(Path(selection.source_path))
    except SessionNameError:
        return None
    return code


def _ideal_summary(ideal) -> str:
    """The one-line verdict beside the corner table's heading.

    States how many laps contribute, because that is what says how optimistic
    the target is: one contributing lap means the ideal lap *is* a real lap and
    is therefore achievable; five means five different things went right on five
    different occasions.
    """
    if ideal is None:
        return strings.IDEAL_UNAVAILABLE
    gain = ideal.gain_over_best_real_s
    if gain is None or ideal.best_real_time_s is None:
        return ""
    return strings.IDEAL_SUMMARY.format(
        time=format_lap_time(ideal.total_time_s),
        gain=f"{gain:.3f}",
        best=format_lap_time(ideal.best_real_time_s),
        n_laps=ideal.n_contributing_laps,
    )


def _trace(label: str, analysis: pipeline.LapAnalysis) -> LapTrace:
    """Turn an analysed lap into what the chart draws.

    The chart layer takes numpy arrays and a label, nothing else - that is what
    lets it be tested without a session file.
    """
    return LapTrace(
        label=label,
        grid_m=analysis.grid_m,
        elapsed_s=analysis.elapsed_s,
        channels=analysis.channels,
    )
