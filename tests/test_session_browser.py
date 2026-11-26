"""The session browser: search, filters, marks, empty states and keyboard.

A fake catalog in memory - three sessions at two tracks with two cars - so the
filters have something to narrow and no database is needed.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6 import QtCore, QtWidgets  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from lmu_telemetry.domain.records import LapRow, SessionRow  # noqa: E402
from lmu_telemetry.presentation import theme  # noqa: E402
from lmu_telemetry.presentation.session_browser import (  # noqa: E402
    KIND_SESSION, ROLE_KIND, ROLE_PAYLOAD, BrowserFilter, SessionBrowser, fold,
    session_matches,
)
from lmu_telemetry.shared import strings  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    theme.apply(app)
    yield app


def _session(sid, track, car, kind, when, weather="Seco"):
    return SessionRow(
        session_id=sid, source_path=Path(f"{sid}.duckdb"), track_id=track.lower(),
        track_name=track, car_name=car, car_class="Hypercar", session_type=kind,
        started_at=when, weather=weather, n_laps=3,
    )


def _lap(sid, index, time_s, comparable=True):
    return LapRow(
        lap_id=f"{sid}-{index}", session_id=sid, lap_index=index, lap_number=index,
        time_s=time_s, flags=("valid",) if comparable else ("partial",),
        is_comparable=comparable,
    )


class FakeCatalog:
    def __init__(self, sessions=None, laps=None):
        self.sessions = sessions if sessions is not None else [
            _session("fuji-race", "Fuji Speedway", "Toyota GR010", "R",
                     datetime(2026, 7, 15, 18, 42)),
            _session("fuji-quali", "Fuji Speedway", "Ferrari 499P", "Q",
                     datetime(2026, 7, 14, 10, 0)),
            _session("monza-practice", "Monza", "Toyota GR010", "P",
                     datetime(2026, 7, 20, 9, 30), weather="Chuva"),
            _session("monza-outlap", "Monza", "Toyota GR010", "P",
                     datetime(2026, 7, 10, 9, 0)),
        ]
        self.laps = laps if laps is not None else {
            "fuji-race": [_lap("fuji-race", 0, 5.0, False), _lap("fuji-race", 1, 103.5),
                          _lap("fuji-race", 2, 102.9)],
            "fuji-quali": [_lap("fuji-quali", 1, 101.8)],
            "monza-practice": [_lap("monza-practice", 1, 108.0),
                               _lap("monza-practice", 2, 107.4)],
            # Only an out-lap: listed, dimmed, still openable.
            "monza-outlap": [_lap("monza-outlap", 0, 140.0, False)],
        }

    def list_sessions(self):
        return self.sessions, self.laps


@pytest.fixture
def browser(qt_app):
    widget = SessionBrowser(FakeCatalog())
    widget.resize(420, 600)
    widget.reload()
    widget.show()
    yield widget
    widget.close()


def _listed(browser) -> list[str]:
    ids = []
    iterator = QtWidgets.QTreeWidgetItemIterator(browser.tree)
    while iterator.value():
        item = iterator.value()
        if item.data(0, ROLE_KIND) == KIND_SESSION:
            ids.append(item.data(0, ROLE_PAYLOAD))
        iterator += 1
    return ids


def _item(browser, session_id):
    iterator = QtWidgets.QTreeWidgetItemIterator(browser.tree)
    while iterator.value():
        item = iterator.value()
        if item.data(0, ROLE_PAYLOAD) == session_id:
            return item
        iterator += 1
    return None


# --- matching ------------------------------------------------------------------


def test_folding_ignores_case_and_accents():
    assert fold("Sessão Classificação") == "sessao classificacao"


@pytest.mark.parametrize(("text", "expected"), [
    ("", True),
    ("fuji", True),
    ("FUJI corrida", True),          # every word, any order, any case
    ("corrida fuji", True),
    ("toyota", True),
    ("hypercar", True),              # the class
    ("2026-07-15", True),            # the date
    ("seco", True),                  # the weather
    ("monza", False),
    ("fuji classificacao", False),   # this session is a race
])
def test_search_words_must_all_match(text, expected):
    race = _session("x", "Fuji Speedway", "Toyota GR010", "R", datetime(2026, 7, 15, 18, 42))
    assert session_matches(race, BrowserFilter(text=text)) is expected


def test_filters_match_exactly():
    race = _session("x", "Fuji Speedway", "Toyota GR010", "R", datetime(2026, 7, 15))
    assert session_matches(race, BrowserFilter(track="Fuji Speedway", car="Toyota GR010",
                                               session_type="R"))
    assert not session_matches(race, BrowserFilter(track="Monza"))
    assert not session_matches(race, BrowserFilter(car="Ferrari 499P"))
    assert not session_matches(race, BrowserFilter(session_type="Q"))


# --- grouping and order ----------------------------------------------------------


def test_groups_are_track_and_car_most_recent_first(browser):
    headings = [browser.tree.topLevelItem(i).text(0)
                for i in range(browser.tree.topLevelItemCount())]
    assert headings == [
        "Monza · Toyota GR010",            # 20 Jul
        "Fuji Speedway · Toyota GR010",    # 15 Jul
        "Fuji Speedway · Ferrari 499P",    # 14 Jul
    ]
    assert _listed(browser)[:2] == ["monza-practice", "monza-outlap"]


def test_a_session_without_a_comparable_lap_is_dimmed_not_hidden(browser):
    item = _item(browser, "monza-outlap")
    assert item is not None
    assert item.text(1) == "--"
    assert item.foreground(0).color().name() == theme.TEXT_DISABLED


# --- filtering ---------------------------------------------------------------------


def test_typing_narrows_the_list(browser):
    browser.search.setText("fuji")
    assert set(_listed(browser)) == {"fuji-race", "fuji-quali"}
    assert browser.count.text() == strings.BROWSER_COUNT_FILTERED.format(shown=2, total=4)


def test_the_track_filter_narrows_the_car_choices(browser):
    browser.set_filter(BrowserFilter(track="Monza"))
    cars = [browser.car_filter.itemText(i) for i in range(1, browser.car_filter.count())]
    assert cars == ["Toyota GR010"]
    browser.set_filter(BrowserFilter())
    cars = [browser.car_filter.itemText(i) for i in range(1, browser.car_filter.count())]
    assert cars == ["Ferrari 499P", "Toyota GR010"]


def test_choosing_from_the_combos_filters(browser):
    browser.type_filter.setCurrentIndex(browser.type_filter.findData("Q"))
    assert _listed(browser) == ["fuji-quali"]
    browser.track_filter.setCurrentIndex(browser.track_filter.findData("Monza"))
    assert _listed(browser) == []


def test_session_type_choices_are_named(browser):
    labels = {browser.type_filter.itemText(i) for i in range(browser.type_filter.count())}
    assert strings.SESSION_TYPE_RACE in labels
    assert strings.BROWSER_FILTER_ALL_TYPES in labels


def test_filtering_does_not_open_anything(browser):
    opened = []
    browser.lap_selected.connect(opened.append)
    browser.search.setText("monza")
    browser.set_filter(BrowserFilter(track="Fuji Speedway"))
    assert opened == []


def test_the_selection_survives_a_filter_that_keeps_its_session(browser):
    browser.select_lap("fuji-race", 2)
    browser.search.setText("toyota")
    assert browser.current_lap().session_id == "fuji-race"


# --- empty states --------------------------------------------------------------------


def test_an_empty_catalog_offers_the_import(qt_app):
    browser = SessionBrowser(FakeCatalog(sessions=[], laps={}))
    browser.reload()
    requested = []
    browser.import_requested.connect(lambda: requested.append("files"))
    browser.import_folder_requested.connect(lambda: requested.append("folder"))

    assert browser.tree.isHidden() and not browser.placeholder.isHidden()
    assert browser.placeholder_title.text() == strings.BROWSER_EMPTY_TITLE
    assert browser.search.isHidden()       # nothing to search yet
    assert browser.clear_button.isHidden()
    browser.import_button.click()
    browser.import_folder_button.click()
    assert requested == ["files", "folder"]


def test_no_match_offers_to_clear_the_filters(browser):
    browser.search.setText("nürburgring")
    assert browser.tree.isHidden()
    assert browser.placeholder_title.text() == strings.BROWSER_NO_MATCH_TITLE
    assert not browser.clear_button.isHidden()
    assert browser.import_button.isHidden()

    browser.clear_button.click()
    assert browser.search.text() == ""
    assert len(_listed(browser)) == 4


def test_an_unreadable_catalog_is_an_empty_one(qt_app):
    class Broken:
        def list_sessions(self):
            raise OSError("disk on fire")

    browser = SessionBrowser(Broken())
    assert browser.reload() == 0
    assert browser.placeholder_title.text() == strings.BROWSER_EMPTY_TITLE


# --- choosing ----------------------------------------------------------------------------


def test_choosing_a_session_opens_its_best_lap(browser):
    opened = []
    browser.lap_selected.connect(opened.append)
    browser.tree.setCurrentItem(_item(browser, "fuji-race"))
    assert [(s.session_id, s.lap_index) for s in opened] == [("fuji-race", 2)]


def test_a_session_without_a_comparable_lap_opens_its_first(browser):
    opened = []
    browser.lap_selected.connect(opened.append)
    browser.tree.setCurrentItem(_item(browser, "monza-outlap"))
    assert opened[0].lap_index == 0


def test_coming_back_to_the_open_session_keeps_its_lap(browser):
    """The lap list opened lap 1; clicking the session again must not jump back
    to the session's best."""
    browser.select_lap("fuji-race", 1)
    browser.tree.setCurrentItem(_item(browser, "fuji-quali"))
    opened = []
    browser.lap_selected.connect(opened.append)
    browser.select_lap("fuji-race", 1)
    browser.tree.setCurrentItem(_item(browser, "fuji-race"))
    assert all(s.lap_index == 1 for s in opened)


def test_selecting_a_lap_hidden_by_the_filters_clears_them(browser):
    browser.search.setText("monza")
    assert browser.select_lap("fuji-quali", 1) is True
    assert browser.search.text() == ""
    assert browser.current_lap().session_id == "fuji-quali"


def test_an_unknown_lap_changes_nothing(browser):
    browser.select_lap("fuji-race", 2)
    assert browser.select_lap("fuji-race", 99) is False
    assert browser.select_lap("nowhere", 1) is False
    assert browser.current_lap().lap_index == 2


def test_the_default_is_the_newest_session_with_a_comparable_lap(browser):
    assert browser.select_default_lap() is True
    selection = browser.current_lap()
    assert (selection.session_id, selection.lap_index) == ("monza-practice", 2)


# --- the reference mark ----------------------------------------------------------------


def test_the_pinned_reference_session_is_tagged(browser):
    browser.select_lap("fuji-quali", 1)
    reference = browser.current_lap()
    browser.mark_reference(reference)
    item = _item(browser, "fuji-quali")
    assert item.text(0).endswith(strings.BROWSER_MARK_REFERENCE)
    assert strings.BROWSER_TOOLTIP_REFERENCE.format(number=1) in item.toolTip(0)
    assert not _item(browser, "fuji-race").text(0).endswith(strings.BROWSER_MARK_REFERENCE)

    browser.mark_reference(None)
    assert not _item(browser, "fuji-quali").text(0).endswith(strings.BROWSER_MARK_REFERENCE)


def test_the_reference_mark_survives_a_reload(browser):
    browser.select_lap("fuji-quali", 1)
    browser.mark_reference(browser.current_lap())
    browser.reload()
    assert _item(browser, "fuji-quali").text(0).endswith(strings.BROWSER_MARK_REFERENCE)


# --- keyboard -----------------------------------------------------------------------------


def test_enter_in_the_search_opens_the_first_match(browser):
    opened = []
    browser.lap_selected.connect(opened.append)
    browser.focus_search()
    QTest.keyClicks(browser.search, "fuji corrida")
    QTest.keyClick(browser.search, QtCore.Qt.Key.Key_Return)
    assert [s.session_id for s in opened] == ["fuji-race"]
    # The offscreen window is never active, so ask which child took focus.
    assert browser.focusWidget() is browser.tree


def test_escape_clears_the_search(browser):
    browser.search.setText("fuji")
    QTest.keyClick(browser.search, QtCore.Qt.Key.Key_Escape)
    assert browser.search.text() == ""


def test_arrows_step_over_the_group_headings(browser):
    """Down from the last session of one group lands on the first session of
    the next, never on the heading between them."""
    browser.tree.setFocus()
    browser.tree.setCurrentItem(_item(browser, "monza-outlap"))
    QTest.keyClick(browser.tree, QtCore.Qt.Key.Key_Down)
    assert browser.current_lap().session_id == "fuji-race"
    QTest.keyClick(browser.tree, QtCore.Qt.Key.Key_Up)
    assert browser.current_lap().session_id == "monza-outlap"


def test_up_from_the_first_session_stays_put(browser):
    browser.tree.setFocus()
    browser.tree.setCurrentItem(_item(browser, "monza-practice"))
    QTest.keyClick(browser.tree, QtCore.Qt.Key.Key_Up)
    assert browser.current_lap().session_id == "monza-practice"


def test_every_control_is_named_for_screen_readers(browser):
    for widget in (browser.search, browser.track_filter, browser.car_filter,
                   browser.type_filter, browser.tree):
        assert widget.accessibleName()


def test_tab_runs_search_filters_list(browser):
    chain = [browser.search]
    for _ in range(4):
        chain.append(chain[-1].nextInFocusChain())
        while chain[-1].focusPolicy() == QtCore.Qt.FocusPolicy.NoFocus:
            chain[-1] = chain[-1].nextInFocusChain()
    assert chain[1:] == [browser.track_filter, browser.car_filter,
                         browser.type_filter, browser.tree]
