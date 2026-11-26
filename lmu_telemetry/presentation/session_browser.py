"""The session browser: find a session, open it.

Modelled on how web telemetry tools such as Garage 61 present a history of
laps: **filters on top, a list underneath**, and the laps of the chosen session
in a table of their own. The browser used to be a four-level tree - track, car,
session, lap - whose last level repeated, without sectors, what the lap list
beside it already shows. Now it answers one question, *which session*, and the
lap list answers *which lap of it*.

- **Groups are track · car.** Laps are only comparable within one track and one
  car, so that is the unit that puts comparable things together. Groups are
  ordered by their most recent session, and sessions inside a group newest
  first: the combination driven last is at the top, not the one whose name
  sorts first.
- **Search and filters.** Free text matched against track, car, class, session
  type, date and weather, ignoring case and accents; and one filter each for
  track, car (narrowed to the chosen track) and session type.
- **Marks.** Each session's best comparable lap time in the "best" tone - the
  colour the lap list uses for the same fact; the session holding the pinned
  reference lap tagged "ref"; a session with no comparable lap dimmed.
- **Keyboard.** Ctrl+F (wired by the window) reaches the search; Down or Enter
  in the search moves into the list, Esc clears it; arrows in the list step
  from session to session, skipping the group headings.

Reads the catalog only - never a telemetry file. The catalog holds every lap of
every imported session already, so the list fills in milliseconds no matter how
many sessions there are, and a session file is opened only once it is chosen.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime

from PySide6 import QtCore, QtGui, QtWidgets

from lmu_telemetry.application.ports import CatalogGateway
from lmu_telemetry.domain.records import LapRow, SessionRow
from lmu_telemetry.presentation import theme
from lmu_telemetry.shared import strings
from lmu_telemetry.shared.formatting import format_lap_time
from lmu_telemetry.shared.logging_config import get_logger

logger = get_logger(__name__)

#: Qt item roles for the payload each row carries.
ROLE_KIND = QtCore.Qt.ItemDataRole.UserRole
ROLE_PAYLOAD = QtCore.Qt.ItemDataRole.UserRole + 1

KIND_GROUP = "group"
KIND_SESSION = "session"

COLUMN_SESSION, COLUMN_BEST, COLUMN_LAPS = 0, 1, 2


@dataclass(frozen=True, slots=True)
class LapSelection:
    """Everything the rest of the application needs to load a chosen lap."""

    session_id: str
    source_path: str
    lap_index: int
    lap_number: int
    track_name: str
    car_name: str | None
    time_s: float | None
    is_comparable: bool = False
    session_started_at: datetime | None = None
    #: Single-letter session type (P, Q, R...), as the catalog stores it.
    session_type_code: str | None = None


@dataclass(frozen=True, slots=True)
class BrowserFilter:
    """What the list is narrowed to. Empty fields filter nothing."""

    text: str = ""
    track: str | None = None
    car: str | None = None
    session_type: str | None = None

    @property
    def is_empty(self) -> bool:
        return not (self.text.strip() or self.track or self.car or self.session_type)


def fold(text: str) -> str:
    """Lower case without accents, so "sessao" finds "Sessão" and "Fuji" "fuji"."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def session_matches(session: SessionRow, rule: BrowserFilter) -> bool:
    """Whether a session passes the filter.

    Every word of the search must appear somewhere in the session's
    description, in any order: "fuji corrida" finds the races at Fuji.
    """
    if rule.track and session.track_name != rule.track:
        return False
    if rule.car and (session.car_name or "?") != rule.car:
        return False
    if rule.session_type and (session.session_type or "?") != rule.session_type:
        return False
    words = fold(rule.text).split()
    if not words:
        return True
    haystack = fold(" ".join(part for part in (
        session.track_name, session.car_name, session.car_class,
        strings.session_type_label(session.session_type or "?"),
        _format_date(session.started_at), session.weather,
    ) if part))
    return all(word in haystack for word in words)


def best_comparable(laps: list[LapRow]) -> LapRow | None:
    """A session's fastest lap that can be compared, or None."""
    comparable = [lap for lap in laps if lap.is_comparable and lap.time_s]
    return min(comparable, key=lambda lap: lap.time_s, default=None)


class _SessionList(QtWidgets.QTreeWidget):
    """The list itself: arrow keys step over the group headings.

    A heading is not selectable, so landing the cursor on one would leave
    nothing selected and nothing opened - the keyboard user would have to press
    the arrow twice for every group.
    """

    def moveCursor(self, action, modifiers):  # noqa: N802 - Qt override
        index = super().moveCursor(action, modifiers)
        step = {
            QtWidgets.QAbstractItemView.CursorAction.MoveDown: 1,
            QtWidgets.QAbstractItemView.CursorAction.MoveUp: -1,
            QtWidgets.QAbstractItemView.CursorAction.MoveNext: 1,
            QtWidgets.QAbstractItemView.CursorAction.MovePrevious: -1,
            QtWidgets.QAbstractItemView.CursorAction.MoveHome: 1,
            QtWidgets.QAbstractItemView.CursorAction.MoveEnd: -1,
        }.get(action)
        if step is None:
            return index
        current = index
        while current.isValid() and not (current.flags()
                                         & QtCore.Qt.ItemFlag.ItemIsSelectable):
            current = self.indexBelow(current) if step > 0 else self.indexAbove(current)
        return current if current.isValid() else self.currentIndex()


class SessionBrowser(QtWidgets.QWidget):
    """Search, filters and a grouped list of every session in the catalog."""

    lap_selected = QtCore.Signal(LapSelection)
    #: The empty state's buttons: the window owns the file dialogs.
    import_requested = QtCore.Signal()
    import_folder_requested = QtCore.Signal()

    def __init__(
        self, catalog: CatalogGateway, parent: QtWidgets.QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._catalog = catalog
        self._sessions: list[SessionRow] = []
        self._laps: dict[str, list[LapRow]] = {}
        #: The lap on screen, so re-selecting its session keeps that lap rather
        #: than jumping back to the session's best.
        self._current: LapSelection | None = None
        self._reference: LapSelection | None = None
        self._filling = False
        self._build()

    # -- construction ------------------------------------------------------

    def _build(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 4)
        layout.setSpacing(6)

        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText(strings.BROWSER_SEARCH_PLACEHOLDER)
        self.search.setAccessibleName(strings.BROWSER_SEARCH_NAME)
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filter)
        self.search.installEventFilter(self)
        layout.addWidget(self.search)

        filters = QtWidgets.QHBoxLayout()
        filters.setSpacing(6)
        self.track_filter = self._combo(strings.BROWSER_FILTER_TRACK_NAME)
        self.car_filter = self._combo(strings.BROWSER_FILTER_CAR_NAME)
        self.type_filter = self._combo(strings.BROWSER_FILTER_TYPE_NAME)
        self.track_filter.currentIndexChanged.connect(self._on_track_filter)
        for combo in (self.car_filter, self.type_filter):
            combo.currentIndexChanged.connect(self._apply_filter)
        for combo in (self.track_filter, self.car_filter, self.type_filter):
            filters.addWidget(combo, stretch=1)
        layout.addLayout(filters)

        self.tree = _SessionList()
        self.tree.setAccessibleName(strings.BROWSER_LIST_NAME)
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels([
            strings.BROWSER_COLUMN_SESSION, strings.BROWSER_COLUMN_BEST,
            strings.BROWSER_COLUMN_LAPS,
        ])
        self.tree.setRootIsDecorated(False)
        self.tree.setItemsExpandable(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setIndentation(10)
        # The session column absorbs the slack and elides; best time and lap
        # count size to their content, so the figures never leave the panel.
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(COLUMN_SESSION, QtWidgets.QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(COLUMN_BEST, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COLUMN_LAPS, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.tree.setTextElideMode(QtCore.Qt.TextElideMode.ElideRight)
        self.tree.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tree.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.tree, stretch=1)

        self.count = QtWidgets.QLabel()
        self.count.setProperty("role", "caption")
        layout.addWidget(self.count)

        self.placeholder = self._build_placeholder()
        layout.addWidget(self.placeholder, stretch=1)
        self.placeholder.hide()

        self.setTabOrder(self.search, self.track_filter)
        self.setTabOrder(self.track_filter, self.car_filter)
        self.setTabOrder(self.car_filter, self.type_filter)
        self.setTabOrder(self.type_filter, self.tree)

    def _combo(self, accessible_name: str) -> QtWidgets.QComboBox:
        combo = QtWidgets.QComboBox()
        combo.setAccessibleName(accessible_name)
        combo.setToolTip(accessible_name)
        # The panel may be narrow: the three filters share its width and elide
        # rather than set the window's minimum width. The full choice is in the
        # pop-up, which is as wide as it needs.
        combo.setSizeAdjustPolicy(
            QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        combo.setMinimumContentsLength(3)
        combo.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored,
                            QtWidgets.QSizePolicy.Policy.Fixed)
        combo.setMinimumWidth(56)
        combo.view().setMinimumWidth(220)
        return combo

    def _build_placeholder(self) -> QtWidgets.QWidget:
        """The empty state: what is missing, and the button that fixes it."""
        box = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(box)
        layout.setContentsMargins(12, 24, 12, 24)
        layout.setSpacing(8)
        layout.addStretch(1)

        self.placeholder_title = QtWidgets.QLabel()
        self.placeholder_title.setProperty("role", "heading")
        self.placeholder_title.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.placeholder_hint = QtWidgets.QLabel()
        self.placeholder_hint.setProperty("role", "placeholder")
        self.placeholder_hint.setWordWrap(True)
        self.placeholder_hint.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.placeholder_title)
        layout.addWidget(self.placeholder_hint)

        # Stacked, not side by side: the panel is often narrower than two
        # buttons, and a row of them would set the window's minimum width.
        buttons = QtWidgets.QVBoxLayout()
        buttons.setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter)
        self.import_button = QtWidgets.QPushButton(strings.BROWSER_IMPORT_FILES)
        self.import_button.clicked.connect(self.import_requested)
        self.import_folder_button = QtWidgets.QPushButton(strings.BROWSER_IMPORT_FOLDER)
        self.import_folder_button.clicked.connect(self.import_folder_requested)
        self.clear_button = QtWidgets.QPushButton(strings.BROWSER_CLEAR_FILTERS)
        self.clear_button.clicked.connect(self.clear_filters)
        for button in (self.import_button, self.import_folder_button, self.clear_button):
            buttons.addWidget(button, alignment=QtCore.Qt.AlignmentFlag.AlignHCenter)
        layout.addLayout(buttons)
        layout.addStretch(2)
        return box

    # -- population --------------------------------------------------------

    def reload(self) -> int:
        """Re-read the catalog and rebuild the list.

        Returns:
            How many sessions the catalog holds (not how many the filters let
            through).
        """
        try:
            sessions, laps_by_session = self._catalog.list_sessions()
        except Exception as exc:  # noqa: BLE001 - an unreadable catalog is survivable
            logger.error("Could not read the catalog: %s", exc)
            sessions, laps_by_session = [], {}

        self._sessions = list(sessions)
        self._laps = {key: list(value) for key, value in laps_by_session.items()}
        self._fill_filters()
        self._rebuild()
        logger.info("Browser loaded %d sessions", len(self._sessions))
        return len(self._sessions)

    def _fill_filters(self) -> None:
        """Offer only values the catalog holds, keeping the user's choices."""
        tracks = sorted({s.track_name for s in self._sessions})
        types = sorted({s.session_type or "?" for s in self._sessions})
        with self._quiet():
            _fill(self.track_filter, strings.BROWSER_FILTER_ALL_TRACKS,
                  [(track, track) for track in tracks])
            _fill(self.type_filter, strings.BROWSER_FILTER_ALL_TYPES,
                  [(strings.session_type_label(code), code) for code in types])
            self._fill_cars()

    def _fill_cars(self) -> None:
        """Cars driven at the chosen track - or anywhere, with no track chosen.
        A car never driven at the chosen track would only ever empty the list."""
        track = self.track_filter.currentData()
        cars = sorted({s.car_name or "?" for s in self._sessions
                       if track is None or s.track_name == track})
        _fill(self.car_filter, strings.BROWSER_FILTER_ALL_CARS,
              [(car, car) for car in cars])

    def current_filter(self) -> BrowserFilter:
        return BrowserFilter(
            text=self.search.text(),
            track=self.track_filter.currentData(),
            car=self.car_filter.currentData(),
            session_type=self.type_filter.currentData(),
        )

    def _rebuild(self) -> None:
        """Lay the list out again under the current filter, keeping the
        selection when its session is still listed."""
        rule = self.current_filter()
        shown = [s for s in self._sessions if session_matches(s, rule)]
        selected = self._selected_session_id()

        with self._quiet():
            self.tree.clear()
            for (track, car), group in _groups(shown):
                heading = QtWidgets.QTreeWidgetItem(self.tree, [
                    strings.BROWSER_GROUP_LABEL.format(track=track, car=car), "",
                    strings.BROWSER_GROUP_COUNT.format(n=len(group)),
                ])
                heading.setData(0, ROLE_KIND, KIND_GROUP)
                heading.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled)
                heading.setFirstColumnSpanned(True)
                heading.setFont(0, theme.emphasised(heading.font(0)))
                heading.setToolTip(0, f"{track} · {car}")
                for session in group:
                    item = self._add_session(heading, session)
                    if session.session_id == selected:
                        item.setSelected(True)
                        self.tree.setCurrentItem(item)
            self.tree.expandAll()

        self._show_state(total=len(self._sessions), shown=len(shown), rule=rule)

    def _add_session(
        self, parent: QtWidgets.QTreeWidgetItem, session: SessionRow
    ) -> QtWidgets.QTreeWidgetItem:
        laps = self._laps.get(session.session_id, [])
        best = best_comparable(laps)
        type_label = strings.session_type_label(session.session_type or "?")
        label = strings.BROWSER_SESSION_LABEL.format(
            date=_format_date(session.started_at), type=type_label,
        )
        is_reference = (self._reference is not None
                        and self._reference.session_id == session.session_id)
        if is_reference:
            label = f"{label}  {strings.BROWSER_MARK_REFERENCE}"

        item = QtWidgets.QTreeWidgetItem(parent, [
            label,
            format_lap_time(best.time_s) if best is not None else "--",
            str(len(laps)),
        ])
        item.setData(0, ROLE_KIND, KIND_SESSION)
        item.setData(0, ROLE_PAYLOAD, session.session_id)
        for column in (COLUMN_BEST, COLUMN_LAPS):
            item.setTextAlignment(column, QtCore.Qt.AlignmentFlag.AlignRight
                                  | QtCore.Qt.AlignmentFlag.AlignVCenter)

        tooltip = strings.BROWSER_TOOLTIP_SESSION.format(
            track=session.track_name, car=session.car_name or "?",
            date=_format_date(session.started_at), type=type_label, n=len(laps),
            comparable=sum(1 for lap in laps if lap.is_comparable),
        )
        if is_reference:
            tooltip += "\n" + strings.BROWSER_TOOLTIP_REFERENCE.format(
                number=self._reference.lap_number)
        item.setToolTip(COLUMN_SESSION, tooltip)
        item.setToolTip(COLUMN_LAPS, tooltip)

        if best is None:
            # Listed, not hidden: it still holds telemetry worth looking at, it
            # just has no time to compare.
            dim = QtGui.QColor(theme.tone_colour(theme.Tone.DIM))
            for column in range(3):
                item.setForeground(column, dim)
            item.setToolTip(COLUMN_BEST, strings.BROWSER_TOOLTIP_NO_COMPARABLE)
        else:
            item.setForeground(COLUMN_BEST, QtGui.QColor(theme.tone_colour(theme.Tone.BEST)))
            item.setToolTip(COLUMN_BEST, strings.BROWSER_TOOLTIP_BEST)
        return item

    def _show_state(self, *, total: int, shown: int, rule: BrowserFilter) -> None:
        """The list, or the empty state that says why there is none."""
        has_rows = shown > 0
        self.tree.setVisible(has_rows)
        self.placeholder.setVisible(not has_rows)
        filtering = not rule.is_empty
        for widget in (self.search, self.track_filter, self.car_filter, self.type_filter):
            widget.setVisible(total > 0)
        self.count.setVisible(total > 0)
        self.count.setText(
            strings.BROWSER_COUNT_FILTERED.format(shown=shown, total=total) if filtering
            else strings.BROWSER_COUNT_ALL.format(total=total)
        )
        if has_rows:
            return
        empty_catalog = total == 0
        self.placeholder_title.setText(
            strings.BROWSER_EMPTY_TITLE if empty_catalog else strings.BROWSER_NO_MATCH_TITLE)
        self.placeholder_hint.setText(
            strings.BROWSER_EMPTY_HINT if empty_catalog else strings.BROWSER_NO_MATCH_HINT)
        self.import_button.setVisible(empty_catalog)
        self.import_folder_button.setVisible(empty_catalog)
        self.clear_button.setVisible(not empty_catalog)

    # -- filtering ---------------------------------------------------------

    def _on_track_filter(self) -> None:
        if self._filling:
            return
        with self._quiet():
            car = self.car_filter.currentData()
            self._fill_cars()
            _choose(self.car_filter, car)
        self._apply_filter()

    def _apply_filter(self) -> None:
        if not self._filling:
            self._rebuild()

    def set_filter(self, rule: BrowserFilter) -> None:
        """Apply a filter as if the user had typed and chosen it."""
        with self._quiet():
            self.search.setText(rule.text)
            _choose(self.track_filter, rule.track)
            self._fill_cars()
            _choose(self.car_filter, rule.car)
            _choose(self.type_filter, rule.session_type)
        self._rebuild()

    def clear_filters(self) -> None:
        self.set_filter(BrowserFilter())

    def focus_search(self) -> None:
        self.search.setFocus(QtCore.Qt.FocusReason.ShortcutFocusReason)
        self.search.selectAll()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt override
        """Down or Enter in the search goes to the list; Esc clears the search."""
        if watched is self.search and event.type() == QtCore.QEvent.Type.KeyPress:
            key = event.key()
            if key in (QtCore.Qt.Key.Key_Down, QtCore.Qt.Key.Key_Return,
                       QtCore.Qt.Key.Key_Enter):
                self._focus_list()
                return True
            if key == QtCore.Qt.Key.Key_Escape and self.search.text():
                self.search.clear()
                return True
        return super().eventFilter(watched, event)

    def _focus_list(self) -> None:
        """Into the list, onto the selected session - or, with none selected,
        onto the first one listed, which opens it: a keyboard user who searched
        "fuji corrida" and pressed Enter wants that race."""
        if self.tree.isHidden():
            return
        self.tree.setFocus(QtCore.Qt.FocusReason.OtherFocusReason)
        if self.tree.selectedItems():
            return
        sessions = self._session_items()
        if sessions:
            self.tree.setCurrentItem(sessions[0])

    # -- marks -------------------------------------------------------------

    def mark_reference(self, selection: LapSelection | None) -> None:
        """Tag the session holding the pinned reference lap, or none."""
        if selection == self._reference:
            return
        self._reference = selection
        self._rebuild()

    # -- selection ---------------------------------------------------------

    def _on_selection_changed(self) -> None:
        if self._filling:
            return
        session_id = self._selected_session_id()
        if session_id is None:
            return
        if self._current is not None and self._current.session_id == session_id:
            # Coming back to the session on screen keeps the lap on screen.
            self.lap_selected.emit(self._current)
            return
        selection = self._default_lap_of(session_id)
        if selection is not None:
            self._current = selection
            self.lap_selected.emit(selection)

    def current_lap(self) -> LapSelection | None:
        """The lap on screen when its session is the one selected, else None."""
        session_id = self._selected_session_id()
        if session_id is None:
            return None
        if self._current is not None and self._current.session_id == session_id:
            return self._current
        return self._default_lap_of(session_id)

    def select_lap(self, session_id: str, lap_index: int) -> bool:
        """Open one lap of one session, as if it had been chosen here.

        The lap list picks laps through here rather than opening them itself,
        so the browser and the list can never disagree about which lap is on
        screen: there is one way in, and it emits `lap_selected`.

        Returns:
            False when the catalog does not list that lap; nothing changes.
        """
        selection = self._selection_for(session_id, lap_index)
        if selection is None:
            return False
        self._current = selection
        item = self._item_for(session_id)
        if item is None:
            # Hidden by the filters: a lap the user asked for by other means
            # must still be findable in the list it belongs to.
            self.clear_filters()
            item = self._item_for(session_id)
        if item is not None and not item.isSelected():
            with self._quiet():
                self.tree.setCurrentItem(item)
            self.tree.scrollToItem(item)
        self.lap_selected.emit(selection)
        return True

    def select_default_lap(self) -> bool:
        """Open on the fastest comparable lap of the most recent session.

        Almost certainly the lap the user just drove, which is what they came to
        look at. Only comparable laps qualify - a session's tail is a partial
        lap of a few seconds, and the globally shortest lap time would select
        one of those every time - and the most recent session wins over a
        faster older one.
        """
        candidates = [s for s in self._sessions
                      if best_comparable(self._laps.get(s.session_id, [])) is not None]
        if not candidates:
            return False
        newest = max(candidates, key=lambda s: s.started_at or datetime.min)
        best = best_comparable(self._laps[newest.session_id])
        return self.select_lap(newest.session_id, best.lap_index)

    # -- helpers -----------------------------------------------------------

    def _default_lap_of(self, session_id: str) -> LapSelection | None:
        """What choosing a session opens: its best comparable lap, or - in a
        session without one - its first lap, so there is still telemetry to
        look at."""
        laps = self._laps.get(session_id, [])
        lap = best_comparable(laps) or (laps[0] if laps else None)
        return None if lap is None else self._selection_for(session_id, lap.lap_index)

    def _selection_for(self, session_id: str, lap_index: int) -> LapSelection | None:
        session = next((s for s in self._sessions if s.session_id == session_id), None)
        lap = next((each for each in self._laps.get(session_id, [])
                    if each.lap_index == lap_index), None)
        if session is None or lap is None:
            return None
        return LapSelection(
            session_id=session_id,
            source_path=str(session.source_path),
            lap_index=lap.lap_index,
            lap_number=lap.lap_number,
            track_name=session.track_name,
            car_name=session.car_name,
            time_s=lap.time_s,
            is_comparable=lap.is_comparable,
            session_started_at=session.started_at,
            session_type_code=session.session_type,
        )

    def _session_items(self) -> list[QtWidgets.QTreeWidgetItem]:
        items = []
        iterator = QtWidgets.QTreeWidgetItemIterator(self.tree)
        while iterator.value():
            item = iterator.value()
            if item.data(0, ROLE_KIND) == KIND_SESSION:
                items.append(item)
            iterator += 1
        return items

    def _item_for(self, session_id: str) -> QtWidgets.QTreeWidgetItem | None:
        return next((item for item in self._session_items()
                     if item.data(0, ROLE_PAYLOAD) == session_id), None)

    def _selected_session_id(self) -> str | None:
        items = self.tree.selectedItems()
        if not items or items[0].data(0, ROLE_KIND) != KIND_SESSION:
            return None
        return items[0].data(0, ROLE_PAYLOAD)

    @contextmanager
    def _quiet(self) -> Iterator[None]:
        """Changes made by the browser itself: no lap opened, no refilter."""
        previous, self._filling = self._filling, True
        try:
            yield
        finally:
            self._filling = previous


def _groups(sessions: list[SessionRow]) -> list[tuple[tuple[str, str], list[SessionRow]]]:
    """Sessions by (track, car), newest group first, newest session first."""
    grouped: dict[tuple[str, str], list[SessionRow]] = {}
    for session in sessions:
        grouped.setdefault((session.track_name, session.car_name or "?"), []).append(session)

    def newest(session: SessionRow) -> datetime:
        moment = session.started_at or datetime.min
        # Catalog dates may or may not carry a zone; compare them as given but
        # never let one kind raise against the other.
        return moment.replace(tzinfo=None)

    for group in grouped.values():
        group.sort(key=newest, reverse=True)
    return sorted(grouped.items(), key=lambda item: newest(item[1][0]), reverse=True)


def _fill(combo: QtWidgets.QComboBox, everything: str, options: list[tuple[str, str]]) -> None:
    """Refill a filter combo, keeping its choice when that is still offered."""
    chosen = combo.currentData()
    combo.clear()
    combo.addItem(everything, None)
    for label, value in options:
        combo.addItem(label, value)
    _choose(combo, chosen)


def _choose(combo: QtWidgets.QComboBox, value: str | None) -> None:
    index = combo.findData(value) if value is not None else 0
    combo.setCurrentIndex(max(index, 0))


def _format_date(moment: datetime | None) -> str:
    return moment.strftime("%Y-%m-%d %H:%M") if moment else "?"
