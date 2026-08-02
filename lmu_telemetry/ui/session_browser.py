"""The session browser: track, car, session, lap.

Reads the catalog only - never a telemetry file. The catalog holds every lap of
every imported session already, so the tree fills in milliseconds no matter how
many sessions there are, and a session file is opened only once a lap is
actually selected.

The grouping is track, then car, then session. Laps are only comparable within
one track and one car, so that is the order that puts comparable things next to
each other.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from PySide6 import QtCore, QtGui, QtWidgets

from lmu_telemetry.logging_config import get_logger
from lmu_telemetry.storage import catalog
from lmu_telemetry.ui import strings, theme

logger = get_logger(__name__)

#: Qt item roles for the payload each node carries.
ROLE_KIND = QtCore.Qt.ItemDataRole.UserRole
ROLE_PAYLOAD = QtCore.Qt.ItemDataRole.UserRole + 1

KIND_TRACK = "track"
KIND_CAR = "car"
KIND_SESSION = "session"
KIND_LAP = "lap"


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


def format_lap_time(seconds: float | None) -> str:
    """m:ss.mmm, the way a timing screen shows it."""
    if seconds is None or seconds <= 0:
        return "--"
    minutes, remainder = divmod(seconds, 60.0)
    return f"{int(minutes)}:{remainder:06.3f}"


class SessionBrowser(QtWidgets.QWidget):
    """Tree of everything in the catalog, emitting a signal when a lap is picked."""

    lap_selected = QtCore.Signal(LapSelection)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._build()

    def _build(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        heading = QtWidgets.QLabel(strings.BROWSER_TITLE)
        heading.setProperty("role", "heading")
        layout.addWidget(heading)

        self.tree = QtWidgets.QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels([
            strings.BROWSER_COLUMN_NAME,
            strings.BROWSER_COLUMN_TIME,
            strings.BROWSER_COLUMN_NOTE,
        ])
        self.tree.setRootIsDecorated(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(False)

        # The name column absorbs the slack and elides; the time and status
        # columns size to their content. Letting the name column set its own
        # width instead pushes the status column off the edge, which is where
        # the information the driver actually needs lives.
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.Fixed)
        header.setMinimumSectionSize(60)
        self.tree.setColumnWidth(1, 76)
        self.tree.setColumnWidth(2, 96)
        self.tree.setTextElideMode(QtCore.Qt.TextElideMode.ElideRight)
        self.tree.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.tree.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.tree, stretch=1)

        self.placeholder = QtWidgets.QLabel(strings.BROWSER_EMPTY)
        self.placeholder.setProperty("role", "placeholder")
        self.placeholder.setWordWrap(True)
        self.placeholder.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.placeholder)
        self.placeholder.hide()

    # -- population --------------------------------------------------------

    def reload(self) -> int:
        """Rebuild the tree from the catalog.

        Returns:
            How many sessions were found.
        """
        self.tree.clear()

        try:
            with catalog.connect() as con:
                sessions = catalog.list_sessions(con)
                laps_by_session = {
                    session.session_id: catalog.list_laps(con, session.session_id)
                    for session in sessions
                }
        except Exception as exc:  # noqa: BLE001 - an unreadable catalog is survivable
            logger.error("Could not read the catalog: %s", exc)
            sessions, laps_by_session = [], {}

        self.placeholder.setVisible(not sessions)
        self.tree.setVisible(bool(sessions))

        for track_name, track_sessions in _group_by_track(sessions).items():
            track_item = self._add_track(track_name, track_sessions)
            for car_name, car_sessions in _group_by_car(track_sessions).items():
                car_item = self._add_car(track_item, car_name, car_sessions)
                for session in car_sessions:
                    self._add_session(
                        car_item, session, laps_by_session.get(session.session_id, [])
                    )

        self.tree.expandToDepth(0)
        logger.info("Browser loaded %d sessions", len(sessions))
        return len(sessions)

    def _add_track(self, name: str, sessions: list) -> QtWidgets.QTreeWidgetItem:
        item = QtWidgets.QTreeWidgetItem(self.tree, [name, "", ""])
        item.setData(0, ROLE_KIND, KIND_TRACK)
        item.setText(2, strings.BROWSER_N_SESSIONS.format(n=len(sessions)))
        font = item.font(0)
        font.setBold(True)
        item.setFont(0, font)
        return item

    def _add_car(
        self, parent: QtWidgets.QTreeWidgetItem, name: str, sessions: list
    ) -> QtWidgets.QTreeWidgetItem:
        item = QtWidgets.QTreeWidgetItem(parent, [name, "", ""])
        item.setData(0, ROLE_KIND, KIND_CAR)
        item.setText(2, strings.BROWSER_N_SESSIONS.format(n=len(sessions)))
        return item

    def _add_session(
        self,
        parent: QtWidgets.QTreeWidgetItem,
        session: catalog.SessionRow,
        laps: list[catalog.LapRow],
    ) -> QtWidgets.QTreeWidgetItem:
        label = strings.BROWSER_SESSION_LABEL.format(
            date=_format_date(session.started_at),
            type=strings.session_type_label(session.session_type or "?"),
        )
        item = QtWidgets.QTreeWidgetItem(parent, [label, "", ""])
        item.setData(0, ROLE_KIND, KIND_SESSION)
        item.setText(2, strings.BROWSER_N_LAPS.format(n=len(laps)))

        # The session's own best comparable lap, so the fastest of each session
        # can be picked out without expanding it.
        comparable = [lap for lap in laps if lap.is_comparable and lap.time_s]
        best_time = min((lap.time_s for lap in comparable), default=None)
        if best_time is not None:
            item.setText(1, format_lap_time(best_time))

        for lap in laps:
            self._add_lap(item, session, lap, is_best=lap.time_s == best_time)
        return item

    def _add_lap(
        self,
        parent: QtWidgets.QTreeWidgetItem,
        session: catalog.SessionRow,
        lap: catalog.LapRow,
        *,
        is_best: bool,
    ) -> None:
        item = QtWidgets.QTreeWidgetItem(parent, [
            strings.BROWSER_LAP_LABEL.format(number=lap.lap_number),
            format_lap_time(lap.time_s),
            strings.primary_lap_flag(lap.flags),
        ])
        # The full flag list on hover: a lap can be an in-lap that also went off
        # track and was only partly recorded, and all of that is worth knowing
        # without giving the column enough width to say it outright.
        if lap.flag_labels:
            tooltip = ", ".join(lap.flag_labels)
            for column in range(3):
                item.setToolTip(column, tooltip)
        item.setData(0, ROLE_KIND, KIND_LAP)
        item.setData(0, ROLE_PAYLOAD, LapSelection(
            session_id=lap.session_id,
            source_path=str(session.source_path),
            lap_index=lap.lap_index,
            lap_number=lap.lap_number,
            track_name=session.track_name,
            car_name=session.car_name,
            time_s=lap.time_s,
            is_comparable=lap.is_comparable,
            session_started_at=session.started_at,
        ))

        # A lap that cannot be compared is dimmed rather than hidden: it still
        # holds telemetry worth looking at, it just has no meaningful time.
        if not lap.is_comparable:
            for column in range(3):
                item.setForeground(column, QtGui.QColor(theme.TEXT_DISABLED))
        elif is_best:
            for column in range(2):
                item.setForeground(column, QtGui.QColor(theme.ACCENT))

    # -- selection ---------------------------------------------------------

    def _on_selection_changed(self) -> None:
        selection = self.current_lap()
        if selection is not None:
            self.lap_selected.emit(selection)

    def current_lap(self) -> LapSelection | None:
        """The selected lap, or None when the selection is not a lap."""
        items = self.tree.selectedItems()
        if not items:
            return None
        item = items[0]
        if item.data(0, ROLE_KIND) != KIND_LAP:
            return None
        return item.data(0, ROLE_PAYLOAD)

    def select_default_lap(self) -> bool:
        """Open on the fastest comparable lap of the most recent session.

        Almost certainly the lap the user just drove, which is what they came to
        look at.

        Two filters matter here. Only comparable laps qualify: a session's tail
        is a partial lap of a few seconds, and picking the globally shortest lap
        time would select one of those every time. And the most recent session
        wins, because the tree is ordered by track name, so "the first lap in
        the tree" would be alphabetical rather than useful.
        """
        candidates: list[tuple[datetime, float, QtWidgets.QTreeWidgetItem]] = []

        iterator = QtWidgets.QTreeWidgetItemIterator(self.tree)
        while iterator.value():
            item = iterator.value()
            if item.data(0, ROLE_KIND) == KIND_LAP:
                payload: LapSelection = item.data(0, ROLE_PAYLOAD)
                if payload.is_comparable and payload.time_s:
                    candidates.append((
                        payload.session_started_at or datetime.min,
                        payload.time_s,
                        item,
                    ))
            iterator += 1

        if not candidates:
            return False

        newest = max(moment for moment, _time, _item in candidates)
        _moment, _time, chosen = min(
            (c for c in candidates if c[0] == newest), key=lambda c: c[1]
        )

        self.tree.setCurrentItem(chosen)
        self.tree.scrollToItem(chosen)
        return True


def _group_by_track(sessions: list[catalog.SessionRow]) -> dict[str, list]:
    grouped: dict[str, list] = {}
    for session in sessions:
        grouped.setdefault(session.track_name, []).append(session)
    return dict(sorted(grouped.items()))


def _group_by_car(sessions: list[catalog.SessionRow]) -> dict[str, list]:
    grouped: dict[str, list] = {}
    for session in sessions:
        grouped.setdefault(session.car_name or "?", []).append(session)
    return dict(sorted(grouped.items()))


def _format_date(moment: datetime | None) -> str:
    return moment.strftime("%Y-%m-%d %H:%M") if moment else "?"
