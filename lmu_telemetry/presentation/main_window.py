"""The main window: a summary strip on top, the stacked traces in the centre,
everything else docked around them.

The comparison is where the physics constrains the interface. Two laps can only
be compared in the *distance* domain, because two laps at the same elapsed time
are at different places on the circuit. So while a comparison is drawn the time
axis is disabled, and a reference lap from another circuit is refused outright
rather than plotted against a distance grid that means nothing.

The default arrangement reads top to bottom the way a lap is analysed:

- **across the top**, the session header - track, car, the lap against its
  reference, the sectors, the session's best and the ideal lap;
- **on the left**, where the lap comes from: the session tree over the list of
  that session's laps with their sectors;
- **in the centre**, the traces;
- **on the right**, where on the circuit: the track map, with its corners
  numbered, over the g-g diagram;
- **along the bottom**, corner by corner: the corner table, the card of the
  corner under the cursor, and the consistency report, side by side.

Every panel is a dock widget and the header a toolbar, so each can be hidden,
moved, tabbed together or floated; the arrangement is remembered between runs
(`QSettings`), and "Restaurar layout padrão" puts it back.

This module only builds and connects. What a lap looks like is worked out in
`lap_view`, the commands live in `window_actions`, saving files in `exporting`
and the import thread in `import_worker`.
"""

from __future__ import annotations

import time
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from lmu_telemetry.application.ports import Gateways
from lmu_telemetry.presentation import lap_view
from lmu_telemetry.presentation.chart_panel import ROW_SPECS, AxisMode, ChartStack
from lmu_telemetry.presentation.consistency_panel import ConsistencyPanel
from lmu_telemetry.presentation.corner_detail import CornerDetail
from lmu_telemetry.presentation.corner_table import CornerTable
from lmu_telemetry.presentation.exporting import LapExporter
from lmu_telemetry.presentation.gg_panel import FrictionPanel
from lmu_telemetry.presentation.import_worker import ImportRunner
from lmu_telemetry.presentation.lap_list import LapList
from lmu_telemetry.presentation.lap_view import MapFigure
from lmu_telemetry.presentation.notice_banner import NoticeBanner, Severity
from lmu_telemetry.presentation.session_browser import LapSelection, SessionBrowser
from lmu_telemetry.presentation.session_header import SessionHeader
from lmu_telemetry.presentation.session_state import (
    ComparisonMode, CurrentView, SessionPool,
)
from lmu_telemetry.presentation.status_line import StatusLine
from lmu_telemetry.presentation.track_map import MapColour, TrackMap
from lmu_telemetry.presentation.window_actions import WindowActions
from lmu_telemetry.shared import strings
from lmu_telemetry.shared.errors import TelemetryError
from lmu_telemetry.shared.logging_config import get_logger

logger = get_logger(__name__)

#: Bumped when a dock is added, removed or renamed, so a layout saved by an
#: older build is dropped instead of half-applied.
LAYOUT_STATE_VERSION = 2
_SETTING_GEOMETRY = "window/geometry"
_SETTING_STATE = "window/state"


class MainWindow(QtWidgets.QMainWindow):
    """The application window."""

    def __init__(
        self, gateways: Gateways, settings: QtCore.QSettings | None = None
    ) -> None:
        super().__init__()
        self._gateways = gateways
        #: Where the layout is remembered. Injectable so tests never touch the
        #: user's real settings.
        self._settings = settings if settings is not None else QtCore.QSettings()
        self._sessions = SessionPool(gateways.sessions, gateways.catalog)
        self._selection: LapSelection | None = None
        self._current: CurrentView | None = None
        self._pinned: LapSelection | None = None
        self._mode = ComparisonMode.SESSION_BEST

        self.importer = ImportRunner(gateways.importer, self)
        self.exporter = LapExporter(self, gateways.exporter, lambda: self._current)

        self.setWindowTitle(strings.WINDOW_TITLE)
        self._initial_size()
        self._build()
        self._build_commands()
        self._connect()
        self._restore_layout()
        self.reload_catalog(select_first=True)

    # -- construction ------------------------------------------------------

    def _build(self) -> None:
        # The centre: the notice banner above the traces, hidden unless the lap
        # on screen comes with something the user must know.
        central = QtWidgets.QWidget()
        central.setObjectName("central")  # the theme styles it as a card
        layout = QtWidgets.QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.notices = NoticeBanner()
        layout.addWidget(self.notices)
        self.chart = ChartStack()
        layout.addWidget(self.chart, stretch=1)
        self.setCentralWidget(central)

        self.header = SessionHeader()
        self.browser = SessionBrowser(self._gateways.catalog)
        self.lap_list = LapList()
        self.corner_table = CornerTable()
        self.corner_detail = CornerDetail()
        self.consistency = ConsistencyPanel()
        self.track_map = TrackMap()
        self.friction = FrictionPanel()

        self.dock_sessions = self._make_dock(
            "dock_sessions", strings.BROWSER_TITLE, self.browser)
        self.dock_laps = self._make_dock("dock_laps", strings.DOCK_LAPS, self.lap_list)
        # Corner table and consistency are two docks rather than two tabs of
        # one: they answer different questions about the same corners - how was
        # this lap, and how repeatable is the driver - and are read together.
        self.dock_corners = self._make_dock(
            "dock_corners", strings.DOCK_CORNERS, self.corner_table)
        self.dock_detail = self._make_dock(
            "dock_detail", strings.DOCK_DETAIL, self.corner_detail)
        self.dock_consistency = self._make_dock(
            "dock_consistency", strings.DOCK_CONSISTENCY, self.consistency)
        self.dock_map = self._make_dock("dock_map", strings.MAP_TITLE, self.track_map)
        self.dock_gg = self._make_dock("dock_gg", strings.GG_TITLE, self.friction)
        self.docks = [
            self.dock_sessions, self.dock_laps, self.dock_corners,
            self.dock_detail, self.dock_consistency, self.dock_map, self.dock_gg,
        ]

        # The side columns stop above the bottom row, which runs the full width:
        # the corner table has eleven columns and needs the room more than the
        # session tree needs the height.
        Corner, Area = QtCore.Qt.Corner, QtCore.Qt.DockWidgetArea
        self.setCorner(Corner.TopLeftCorner, Area.LeftDockWidgetArea)
        self.setCorner(Corner.BottomLeftCorner, Area.BottomDockWidgetArea)
        self.setCorner(Corner.TopRightCorner, Area.RightDockWidgetArea)
        self.setCorner(Corner.BottomRightCorner, Area.BottomDockWidgetArea)
        self.setDockOptions(
            QtWidgets.QMainWindow.DockOption.AnimatedDocks
            | QtWidgets.QMainWindow.DockOption.AllowNestedDocks
            | QtWidgets.QMainWindow.DockOption.AllowTabbedDocks
        )
        self._arrange_docks()

        self.status = StatusLine()
        self.setStatusBar(self.status)

    def _make_dock(
        self, name: str, title: str, widget: QtWidgets.QWidget
    ) -> QtWidgets.QDockWidget:
        """A dock the user can hide, move, tab or float.

        The object name is what `saveState` keys the arrangement on, so it must
        be stable: renaming one orphans every saved layout.
        """
        dock = QtWidgets.QDockWidget(title, self)
        dock.setObjectName(name)
        dock.setWidget(widget)
        return dock

    def _build_commands(self) -> None:
        """Menus, the main toolbar and the session header's row."""
        enabled_rows = {spec.key for spec in ROW_SPECS if self.chart.is_row_enabled(spec.key)}
        commands = self.commands = WindowActions(self, self.docks, enabled_rows)
        commands.show_comparison(self._mode)
        commands.build_menus(self.menuBar())

        self.toolbar = commands.build_toolbar()
        self.addToolBar(QtCore.Qt.ToolBarArea.TopToolBarArea, self.toolbar)
        commands.add_toolbar_toggle(self.toolbar)

        # The session header: a toolbar on its own row rather than a dock, so it
        # spans the whole window above the side columns and cannot be squeezed
        # into a column where its figures would wrap.
        self.addToolBarBreak(QtCore.Qt.ToolBarArea.TopToolBarArea)
        header = self.header_bar = QtWidgets.QToolBar(strings.TOOLBAR_HEADER, self)
        header.setObjectName("toolbar_header")
        header.setMovable(False)
        header.setFloatable(False)
        header.addWidget(self.header)
        self.addToolBar(QtCore.Qt.ToolBarArea.TopToolBarArea, header)
        commands.add_toolbar_toggle(header)

    def _connect(self) -> None:
        """Every signal, in one place: what each panel and command drives."""
        commands = self.commands
        commands.import_files.triggered.connect(self.import_session)
        commands.import_folder.triggered.connect(self.import_folder)
        commands.refresh.triggered.connect(lambda: self.reload_catalog())
        commands.quit.triggered.connect(self.close)
        commands.export["png"].triggered.connect(self.exporter.export_png)
        commands.export["csv"].triggered.connect(self.exporter.export_csv)
        commands.export["corners"].triggered.connect(self.exporter.export_corners_csv)
        commands.export["pdf"].triggered.connect(self.exporter.export_pdf)
        commands.axis_chosen.connect(self.chart.set_axis_mode)
        commands.channel_toggled.connect(self.chart.set_row_enabled)
        commands.reset_layout.triggered.connect(self.reset_layout)
        commands.map_colour_chosen.connect(self.track_map.set_colour_mode)
        commands.integrated.toggled.connect(self.track_map.set_integrated_visible)
        commands.comparison_chosen.connect(self.set_comparison_mode)
        commands.pin.triggered.connect(self.pin_current_lap)
        commands.find_session.triggered.connect(self.find_session)

        self.importer.busy_changed.connect(
            lambda busy: commands.set_import_enabled(not busy))
        self.importer.progress.connect(self._on_import_progress)
        self.importer.finished.connect(self._on_import_finished)
        self.exporter.status.connect(self.status.notify)

        self.browser.lap_selected.connect(self.show_lap)
        self.browser.import_requested.connect(self.import_session)
        self.browser.import_folder_requested.connect(self.import_folder)
        self.lap_list.lap_chosen.connect(self._on_lap_chosen)
        self.corner_table.corner_selected.connect(self._on_cursor_moved)
        self.corner_table.corner_zoomed.connect(self.chart.zoom_to)
        self.corner_table.corner_renamed.connect(self.rename_corner)
        self.consistency.corner_selected.connect(self._on_cursor_moved)
        self.consistency.stint_changed.connect(self._on_stint_changed)
        # The map drives the cursor back: picking a corner on the map is how a
        # driver thinks about a lap.
        self.chart.cursor_moved.connect(self._on_cursor_moved)
        self.track_map.distance_picked.connect(self._on_cursor_moved)

    # -- layout ------------------------------------------------------------

    def _initial_size(self) -> None:
        """Open large enough for seven panels, but never larger than the screen.

        A fixed size that suits a 1440p monitor would open off the edge of a
        laptop's 1366 x 768, with the bottom row out of reach.
        """
        width, height = 1500, 950
        screen = QtGui.QGuiApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            width = min(width, int(available.width() * 0.95))
            height = min(height, int(available.height() * 0.92))
        self.resize(width, height)

    def _arrange_docks(self) -> None:
        """The default layout: sessions over laps on the left, map over g-g on
        the right, and corners, the corner card and consistency side by side
        along the bottom."""
        Area = QtCore.Qt.DockWidgetArea
        horizontal, vertical = QtCore.Qt.Orientation.Horizontal, QtCore.Qt.Orientation.Vertical
        # Dock first, then detach: a floating dock has to be docked before it
        # can be taken out of its area and placed again.
        for dock in self.docks:
            dock.setFloating(False)
            self.removeDockWidget(dock)

        self.addDockWidget(Area.LeftDockWidgetArea, self.dock_sessions)
        self.splitDockWidget(self.dock_sessions, self.dock_laps, vertical)
        self.addDockWidget(Area.RightDockWidgetArea, self.dock_map)
        self.splitDockWidget(self.dock_map, self.dock_gg, vertical)
        self.addDockWidget(Area.BottomDockWidgetArea, self.dock_corners)
        self.splitDockWidget(self.dock_corners, self.dock_detail, horizontal)
        self.splitDockWidget(self.dock_detail, self.dock_consistency, horizontal)
        for dock in self.docks:
            dock.show()

        # The traces are the instrument, so the docks take what they need to
        # be legible and no more: a bottom row about a quarter of the height,
        # side columns wide enough for a lap's sectors and for a map that is
        # not a thumbnail. Fractions of the window, so a laptop screen gets the
        # same proportions as a large monitor rather than the same pixels.
        width, height = max(self.width(), 800), max(self.height(), 600)
        side = int(width * 0.275)
        column = height - int(height * 0.26)
        self.resizeDocks([self.dock_sessions, self.dock_map], [side, side], horizontal)
        self.resizeDocks(
            [self.dock_sessions, self.dock_laps],
            [int(column * 0.42), int(column * 0.58)], vertical,
        )
        self.resizeDocks(
            [self.dock_map, self.dock_gg],
            [int(column * 0.56), int(column * 0.44)], vertical,
        )
        self.resizeDocks([self.dock_corners], [int(height * 0.26)], vertical)
        self.resizeDocks(
            [self.dock_corners, self.dock_detail, self.dock_consistency],
            [int(width * 0.5), int(width * 0.18), int(width * 0.32)], horizontal,
        )

    def reset_layout(self) -> None:
        """Put every panel back where it started."""
        self._arrange_docks()
        self.toolbar.setVisible(True)
        self.header_bar.setVisible(True)
        self.status.notify(strings.STATUS_LAYOUT_RESET)

    def _restore_layout(self) -> None:
        """Apply the arrangement saved by the last run, if there is one.

        Falls back to the default when the saved state no longer fits - a dock
        was added or renamed since - rather than leaving a half-restored window.
        """
        geometry = self._settings.value(_SETTING_GEOMETRY)
        state = self._settings.value(_SETTING_STATE)
        if isinstance(geometry, QtCore.QByteArray) and not geometry.isEmpty():
            self.restoreGeometry(geometry)
        if isinstance(state, QtCore.QByteArray) and not state.isEmpty():
            if not self.restoreState(state, LAYOUT_STATE_VERSION):
                logger.warning("Saved window layout not usable; using the default")
                self._arrange_docks()

    def _save_layout(self) -> None:
        self._settings.setValue(_SETTING_GEOMETRY, self.saveGeometry())
        self._settings.setValue(_SETTING_STATE, self.saveState(LAYOUT_STATE_VERSION))
        self._settings.sync()

    # -- catalog and import ------------------------------------------------

    def reload_catalog(self, *, select_first: bool = False) -> None:
        n_sessions = self.browser.reload()
        if select_first and n_sessions:
            self.browser.select_default_lap()
        elif not n_sessions:
            self.status.rest(strings.BROWSER_EMPTY)

    def import_session(self) -> None:
        paths, _filter = QtWidgets.QFileDialog.getOpenFileNames(
            self, strings.DIALOG_IMPORT_TITLE, "", strings.DIALOG_FILE_FILTER
        )
        if paths:
            self.import_files([Path(p) for p in paths])

    def import_folder(self) -> None:
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self, strings.DIALOG_IMPORT_FOLDER_TITLE
        )
        if folder:
            self.import_files(sorted(Path(folder).glob("*.duckdb")))

    def import_files(self, paths: list[Path]) -> None:
        """Import in the background, keeping the window responsive."""
        if not paths:
            return
        if not self.importer.start(paths):
            self.status.notify(strings.STATUS_IMPORT_BUSY)
            return
        self.status.notify(strings.STATUS_IMPORTING, sticky=True)

    def _on_import_progress(self, done: int, total: int, name: str) -> None:
        self.status.notify(
            strings.STATUS_IMPORT_PROGRESS.format(done=done, total=total, name=name),
            sticky=True,
        )

    def _on_import_finished(self, imported: int, failures: list) -> None:
        self.reload_catalog(select_first=imported > 0)
        self.status.notify(strings.STATUS_IMPORTED.format(n=imported))
        if failures:
            QtWidgets.QMessageBox.warning(
                self, strings.DIALOG_IMPORT_FAILED_TITLE, "\n".join(failures[:10])
            )

    def find_session(self) -> None:
        """Ctrl+F: to the session search, bringing its panel back if hidden."""
        self.dock_sessions.show()
        self.dock_sessions.raise_()
        self.browser.focus_search()

    # -- comparison --------------------------------------------------------

    def set_comparison_mode(self, mode: ComparisonMode) -> None:
        """Change what the selected lap is drawn against, and redraw."""
        self._mode = mode
        self.commands.show_comparison(mode)
        if self._selection is not None:
            self.show_lap(self._selection)
        if mode is ComparisonMode.PINNED and self._pinned is None:
            # After the redraw, so its own line does not cover this one.
            self.status.notify(strings.STATUS_NO_REFERENCE_PINNED)

    def pin_current_lap(self) -> None:
        """Pin the lap on screen as the benchmark every other lap is measured
        against, and switch to that mode."""
        if self._selection is None:
            return
        self._pinned = self._selection
        self.browser.mark_reference(self._pinned)
        self.set_comparison_mode(ComparisonMode.PINNED)
        self.status.notify(
            strings.STATUS_REFERENCE_PINNED.format(number=self._selection.lap_number)
        )

    # -- showing a lap -----------------------------------------------------

    def show_lap(self, selection: LapSelection) -> None:
        """Load and draw the chosen lap, with its comparison."""
        started = time.perf_counter()
        self._selection = selection
        self.status.notify(
            strings.STATUS_LOADING.format(name=Path(selection.source_path).name),
            sticky=True,
        )
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
        try:
            try:
                view = lap_view.compose(
                    self._sessions, selection, self._mode, self._pinned
                )
            except TelemetryError as exc:
                self._fail(selection, exc)
                return
            self._show(view)
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        self.status.set_timing((time.perf_counter() - started) * 1000.0)

    def _show(self, view: lap_view.LapView) -> None:
        """Hand each panel its part of the view."""
        figures = view.figures
        if figures is None:
            self._clear_panels()
            # The lap list stays: it is how the user gets from a lap that cannot
            # be drawn - a few seconds of partial lap - to one that can.
            self.lap_list.show_laps(list(view.laps), current_index=view.selection.lap_index)
            self.notices.show_notes(view.notes)
            self.status.rest(strings.CHART_NO_DATA)
            return

        current = self._current = figures.current
        delta = current.delta
        self.chart.show_laps(
            primary=figures.primary_trace,
            benchmark=figures.benchmark_trace,
            delta_grid_m=None if delta is None else delta.grid_m,
            delta_s=None if delta is None else delta.delta_s,
        )
        distances = [distance for distance, _label in figures.corner_marks]
        labels = [label for _distance, label in figures.corner_marks]
        self.chart.set_corner_markers(distances, labels)
        self.chart.set_seam_markers(list(figures.seams))

        self.corner_table.show_corners(
            current.corner_rows,
            ideal_summary=figures.ideal_summary,
            show_comparison=figures.has_benchmark_lap,
            show_ideal=current.ideal is not None,
        )
        if figures.stints:
            self.consistency.show_stints(list(figures.stints),
                                         current_index=figures.stint_index)
        else:
            self.consistency.clear()

        self._show_track_map(figures.track_map, distances, labels)
        if figures.friction is None:
            self.friction.clear()
        else:
            friction = figures.friction
            self.friction.show_envelope(
                friction.envelope, friction.lateral_g, friction.longitudinal_g,
                friction.grid_m, friction.transition_quality,
            )

        self.lap_list.show_laps(
            list(view.laps), current_index=view.selection.lap_index,
            reference_index=figures.reference_index,
        )
        self.corner_detail.show_rows(
            current.corner_rows, comparing=figures.has_benchmark_lap,
            has_ideal=current.ideal is not None,
        )
        self.header.show_summary(figures.summary)

        self._sync_actions(comparing=figures.comparing)
        self.notices.show_notes(view.notes)
        self.setWindowTitle(strings.WINDOW_TITLE_WITH_SESSION.format(
            track=view.selection.track_name, car=view.selection.car_name or "?"
        ))
        self.status.rest(figures.status)

    def _show_track_map(
        self, figure: MapFigure | None, distances: list[float], labels: list[str]
    ) -> None:
        if figure is None:
            self.track_map.clear()
            self.commands.integrated.setEnabled(False)
            return

        self.commands.integrated.setEnabled(figure.integrated is not None)
        if figure.integrated is not None:
            self.track_map.show_integrated(*figure.integrated)
        self.track_map.show_path(
            figure.x_m, figure.y_m, figure.grid_m,
            pedal_states=figure.pedal_states,
            loss_classes=figure.loss_classes,
            caption=figure.caption,
        )
        self.track_map.set_corner_labels(distances, labels)

        # Opening on the delta colouring whenever there is a comparison: it is
        # the reason the panel exists, and having to find a menu item to see
        # where the time went makes the map decorative.
        available = self.track_map.available_modes()
        self.track_map.set_colour_mode(
            MapColour.DELTA if MapColour.DELTA in available else MapColour.PEDALS
        )
        self.commands.offer_map_colours(available, self.track_map.colour_mode)

    def _sync_actions(self, *, comparing: bool) -> None:
        """Keep the commands honest about what is currently possible.

        The time axis is disabled while two laps are drawn: at equal elapsed
        times they are at different points of the circuit, so an overlay on that
        axis would invite a comparison that says nothing.
        """
        self.commands.allow_time_axis(not comparing)
        if comparing and self.chart.axis_mode is AxisMode.TIME:
            self.chart.set_axis_mode(AxisMode.DISTANCE)
            self.commands.show_axis(AxisMode.DISTANCE)
        self.commands.offer_channels(set(self.chart.available_rows()))

    def _clear_panels(self) -> None:
        self._current = None
        self.header.clear()
        self.lap_list.clear()
        self.corner_detail.clear()
        self.chart.clear()
        self.corner_table.clear()
        self.consistency.clear()
        self.track_map.clear()
        self.friction.clear()

    def _fail(self, selection: LapSelection, exc: Exception) -> None:
        logger.error("Could not open %s: %s", selection.source_path, exc)
        self._clear_panels()
        self.notices.show_notes([str(exc)], Severity.ERROR)
        self.status.rest(strings.STATUS_OPEN_FAILED)

    # -- panels talking to each other ----------------------------------------

    def _on_lap_chosen(self, lap_index: int) -> None:
        """A lap picked in the lap list: opened through the session tree, so
        the tree follows and there is a single way a lap gets shown."""
        if self._selection is None:
            return
        if not self.browser.select_lap(self._selection.session_id, lap_index):
            self.status.notify(strings.STATUS_NO_SELECTION)

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

    def _on_cursor_moved(self, distance_m: float) -> None:
        """One cursor for the whole window.

        Whichever panel the mouse is over drives the others, so a point on the
        speed trace, a point on the circuit and a point in the friction envelope
        are always the same instant of the lap.
        """
        self.chart.set_cursor_distance(distance_m)
        self.track_map.set_cursor_distance(distance_m)
        self.friction.set_cursor_distance(distance_m)
        self.corner_table.select_corner_at(distance_m)
        self.corner_detail.select_corner_at(distance_m)

    def rename_corner(self, corner_index: int, distance_m: float, name: str) -> None:
        """Store a corner's name and apply it everywhere, at once.

        Written against the track, anchored to the distance, so it survives
        re-importing every session ever recorded there.
        """
        if self._selection is None:
            return
        self._gateways.catalog.set_corner_name(
            self._selection.track_name, corner_index, name, distance_m
        )
        for opened in self._sessions.all():
            opened.rename_corner(distance_m, name)
        logger.info("Corner at %.0f m named %r", distance_m, name)
        self.show_lap(self._selection)

    # -- lifecycle ---------------------------------------------------------

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        self.importer.stop()
        self._save_layout()
        self._sessions.close_all()
        super().closeEvent(event)

