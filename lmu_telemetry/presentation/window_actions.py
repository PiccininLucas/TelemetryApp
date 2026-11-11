"""The window's commands: every action, the menus that list them and the
toolbar that repeats the everyday ones.

The actions only *say* what was asked - "import", "compare against the ideal
lap", "show the gear row" - through their `triggered` signal or one of the typed
signals below. The window decides what that does. So the menus can be rearranged
here without touching a handler, and a handler changed without touching a menu.

The same `QAction` sits in a menu and on the toolbar, so its state (checked,
enabled) is shared rather than kept in step.
"""

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from lmu_telemetry.presentation.chart_panel import ROW_SPECS, AxisMode
from lmu_telemetry.presentation.session_state import ComparisonMode
from lmu_telemetry.presentation.track_map import MapColour
from lmu_telemetry.shared import strings

#: Comparison modes in menu and toolbar order.
COMPARISON_MODES = (
    ComparisonMode.NONE, ComparisonMode.SESSION_BEST,
    ComparisonMode.PINNED, ComparisonMode.IDEAL,
)


class WindowActions(QtCore.QObject):
    """Builds the actions, the menus on `menu_bar` and the main toolbar."""

    comparison_chosen = QtCore.Signal(object)   # ComparisonMode
    axis_chosen = QtCore.Signal(object)         # AxisMode
    channel_toggled = QtCore.Signal(str, bool)  # row key, visible
    map_colour_chosen = QtCore.Signal(object)   # MapColour

    def __init__(
        self,
        parent: QtWidgets.QMainWindow,
        docks: list[QtWidgets.QDockWidget],
        enabled_rows: set[str],
    ) -> None:
        super().__init__(parent)
        self._parent = parent

        # -- File
        self.import_files = self._action(
            strings.ACTION_IMPORT, QtGui.QKeySequence.StandardKey.Open)
        self.import_folder = self._action(strings.ACTION_IMPORT_FOLDER)
        #: Disabled together while an import runs.
        self.import_actions = [self.import_files, self.import_folder]
        self.refresh = self._action(
            strings.ACTION_REFRESH, QtGui.QKeySequence.StandardKey.Refresh)
        self.export = {
            "png": self._action(strings.ACTION_EXPORT_PNG),
            "csv": self._action(strings.ACTION_EXPORT_CSV),
            "corners": self._action(strings.ACTION_EXPORT_CORNERS_CSV),
            "pdf": self._action(strings.ACTION_EXPORT_PDF),
        }
        self.quit = self._action(strings.ACTION_QUIT, QtGui.QKeySequence.StandardKey.Quit)

        # -- View: finding a session
        self.find_session = self._action(
            strings.ACTION_FIND_SESSION, QtGui.QKeySequence.StandardKey.Find)

        # -- View: axis
        axis_group = QtGui.QActionGroup(self)
        self.axis_distance = self._checkable(strings.ACTION_AXIS_DISTANCE, axis_group,
                                             checked=True)
        self.axis_time = self._checkable(strings.ACTION_AXIS_TIME, axis_group)
        self.axis_time.setToolTip(strings.ACTION_AXIS_TIME_BLOCKED)
        self.axis_distance.triggered.connect(
            lambda: self.axis_chosen.emit(AxisMode.DISTANCE))
        self.axis_time.triggered.connect(lambda: self.axis_chosen.emit(AxisMode.TIME))

        # -- View: channels
        self.channels: dict[str, QtGui.QAction] = {}
        for spec in ROW_SPECS:
            action = self._checkable(spec.axis_label, checked=spec.key in enabled_rows)
            action.toggled.connect(
                lambda checked, key=spec.key: self.channel_toggled.emit(key, checked))
            self.channels[spec.key] = action

        # -- View: panels. A dock's own view action stays in step with the dock
        # however it was closed or reopened - from the menu or its title bar.
        self.panel_toggles = [dock.toggleViewAction() for dock in docks]
        self.reset_layout = self._action(strings.ACTION_RESET_LAYOUT)

        colour_group = QtGui.QActionGroup(self)
        self.map_colours: dict[MapColour, QtGui.QAction] = {}
        for mode, label in ((MapColour.PEDALS, strings.MAP_COLOUR_PEDALS),
                            (MapColour.DELTA, strings.MAP_COLOUR_DELTA)):
            action = self._checkable(label, colour_group, checked=mode is MapColour.PEDALS)
            action.triggered.connect(
                lambda _checked, m=mode: self.map_colour_chosen.emit(m))
            self.map_colours[mode] = action

        self.integrated = self._checkable(strings.MAP_SHOW_INTEGRATED)
        self.integrated.setToolTip(strings.MAP_INTEGRATED_UNAVAILABLE)

        # -- View: comparison
        group = QtGui.QActionGroup(self)
        self.comparison: dict[ComparisonMode, QtGui.QAction] = {}
        for mode, label in zip(COMPARISON_MODES, (
            strings.ACTION_COMPARE_NONE, strings.ACTION_COMPARE_BEST,
            strings.ACTION_COMPARE_PINNED, strings.ACTION_COMPARE_IDEAL,
        ), strict=True):
            action = self._checkable(label, group)
            action.triggered.connect(
                lambda _checked, m=mode: self.comparison_chosen.emit(m))
            self.comparison[mode] = action
        self.pin = self._action(strings.ACTION_PIN_REFERENCE, QtGui.QKeySequence("Ctrl+R"))

        self._short_labels()

    # -- building ----------------------------------------------------------

    def _action(self, text: str, shortcut=None) -> QtGui.QAction:
        action = QtGui.QAction(text, self._parent)
        if shortcut is not None:
            action.setShortcut(shortcut)
        return action

    def _checkable(
        self, text: str, group: QtGui.QActionGroup | None = None, *, checked: bool = False
    ) -> QtGui.QAction:
        action = self._action(text)
        action.setCheckable(True)
        action.setChecked(checked)
        if group is not None:
            group.addAction(action)
        return action

    def _short_labels(self) -> None:
        """A toolbar button shows the action's `iconText`, so a short wording is
        given here while the menu keeps the full one. The tooltip stays the full
        text, so the short label is never the only explanation."""
        short = {
            self.comparison[ComparisonMode.SESSION_BEST]: strings.TOOLBAR_COMPARE_BEST,
            self.comparison[ComparisonMode.PINNED]: strings.TOOLBAR_COMPARE_PINNED,
            self.comparison[ComparisonMode.IDEAL]: strings.TOOLBAR_COMPARE_IDEAL,
            self.pin: strings.TOOLBAR_PIN,
            self.axis_distance: strings.TOOLBAR_AXIS_DISTANCE,
            self.axis_time: strings.TOOLBAR_AXIS_TIME,
            self.export["png"]: strings.TOOLBAR_EXPORT_PNG,
            self.export["pdf"]: strings.TOOLBAR_EXPORT_PDF,
        }
        for action, label in short.items():
            if not action.toolTip() or action.toolTip() == action.text().replace("&", ""):
                action.setToolTip(action.text().replace("&", ""))
            action.setIconText(label)

    def build_menus(self, menu_bar: QtWidgets.QMenuBar) -> QtWidgets.QMenu:
        """Fill the menu bar.

        Returns:
            The Panels menu, so the toolbars - built after it - can add their
            own show/hide entries.
        """
        file_menu = menu_bar.addMenu(strings.MENU_FILE)
        file_menu.addActions([self.import_files, self.import_folder, self.refresh])
        file_menu.addSeparator()
        export_menu = file_menu.addMenu(strings.MENU_EXPORT)
        export_menu.addActions(list(self.export.values()))
        file_menu.addSeparator()
        file_menu.addAction(self.quit)

        view_menu = menu_bar.addMenu(strings.MENU_VIEW)
        view_menu.addAction(self.find_session)
        view_menu.addSeparator()
        view_menu.addActions([self.axis_distance, self.axis_time])
        view_menu.addSeparator()
        view_menu.addMenu(strings.MENU_CHANNELS).addActions(list(self.channels.values()))

        panels = view_menu.addMenu(strings.MENU_PANELS)
        panels.addActions(self.panel_toggles)
        panels.addSeparator()
        panels.addAction(self.reset_layout)
        panels.addSeparator()
        panels.addActions(list(self.map_colours.values()))
        panels.addSeparator()
        panels.addAction(self.integrated)

        view_menu.addSeparator()
        compare = view_menu.addMenu(strings.MENU_COMPARE)
        compare.addActions(list(self.comparison.values()))
        compare.addSeparator()
        compare.addAction(self.pin)
        self._panels_menu = panels
        return panels

    def build_toolbar(self) -> QtWidgets.QToolBar:
        """The actions used on every lap, one click away.

        Text only: the actions have no icons, and a row of unlabelled glyphs
        would be harder to read than the menu it duplicates.
        """
        bar = QtWidgets.QToolBar(strings.TOOLBAR_MAIN, self._parent)
        bar.setObjectName("toolbar_main")
        bar.setMovable(False)
        bar.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextOnly)
        bar.addActions([self.import_files, self.refresh])
        bar.addSeparator()
        bar.addActions([self.comparison[mode] for mode in COMPARISON_MODES])
        bar.addAction(self.pin)
        bar.addSeparator()
        bar.addActions([self.axis_distance, self.axis_time])
        bar.addSeparator()
        bar.addActions([self.export["png"], self.export["pdf"]])
        return bar

    def add_toolbar_toggle(self, bar: QtWidgets.QToolBar) -> None:
        """List a toolbar in the Panels menu, hideable like any dock."""
        action = bar.toggleViewAction()
        self.panel_toggles.append(action)
        self._panels_menu.addAction(action)

    # -- keeping the actions honest ------------------------------------------

    def set_import_enabled(self, enabled: bool) -> None:
        for action in self.import_actions:
            action.setEnabled(enabled)

    def show_comparison(self, mode: ComparisonMode) -> None:
        self.comparison[mode].setChecked(True)

    def show_axis(self, mode: AxisMode) -> None:
        (self.axis_distance if mode is AxisMode.DISTANCE else self.axis_time).setChecked(True)

    def allow_time_axis(self, allowed: bool) -> None:
        """The time axis is offered only while a single lap is drawn."""
        self.axis_time.setEnabled(allowed)

    def offer_channels(self, available: set[str]) -> None:
        """Only rows the lap actually has a channel for can be switched on."""
        for key, action in self.channels.items():
            action.setEnabled(key in available)

    def offer_map_colours(self, available: set[MapColour], current: MapColour) -> None:
        for mode, action in self.map_colours.items():
            action.setEnabled(mode in available)
            action.setChecked(mode is current)
