"""The panels added with the fuller layout: session header, lap list, corner
card, and the corner numbers on the map.

Widget tests feed each panel plain values; the last group opens the demo
session in a real window and checks the panels agree with each other.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PySide6 import QtCore, QtWidgets  # noqa: E402

from lmu_telemetry.application.pipeline import CornerRow  # noqa: E402
from lmu_telemetry.domain.models import Corner, Lap, LapFlag  # noqa: E402
from lmu_telemetry.presentation import theme  # noqa: E402
from lmu_telemetry.presentation.corner_detail import CornerDetail  # noqa: E402
from lmu_telemetry.presentation.lap_list import (  # noqa: E402
    COLUMN_GAP, COLUMN_LAP, COLUMN_S1, COLUMN_S2, COLUMN_TIME, LapList,
    best_lap, best_sectors,
)
from lmu_telemetry.presentation.session_header import (  # noqa: E402
    SectorFigure, SessionHeader, SessionSummary,
)
from lmu_telemetry.presentation.track_map import TrackMap  # noqa: E402
from lmu_telemetry.shared import strings  # noqa: E402
from lmu_telemetry.shared.formatting import format_sector_time  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    theme.apply(app)
    yield app


def _colour(label: QtWidgets.QLabel) -> str:
    return label.styleSheet()


# --- formatting ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(28.111, "28.111"), (75.2, "1:15.200"), (None, "--"), (0.0, "--")],
)
def test_sector_times_read_as_seconds_until_a_minute(seconds, expected):
    assert format_sector_time(seconds) == expected


# --- session header -----------------------------------------------------------


def _summary(**overrides) -> SessionSummary:
    values = dict(
        track="Fuji Speedway",
        details=("Team WRT #46", "GT3", "Corrida", "Nublado"),
        lap_number=5,
        lap_time_s=103.581,
        reference="volta 3 · 1:43.881",
        delta_s=-0.300,
        sectors=(SectorFigure(37.385, 37.385), SectorFigure(28.111, 28.111),
                 SectorFigure(38.085, 37.839)),
        best_lap_number=5,
        best_lap_time_s=103.581,
        ideal_time_s=102.484,
    )
    values.update(overrides)
    return SessionSummary(**values)


def test_the_header_starts_empty_with_a_hint(qt_app):
    header = SessionHeader()
    assert not header.placeholder.isHidden()
    assert header.track.isHidden()


def test_the_header_shows_the_lap_against_its_reference(qt_app):
    header = SessionHeader()
    header.show_summary(_summary())

    assert header.placeholder.isHidden()
    assert header.track.text() == "Fuji Speedway"
    assert "GT3" in header.details.text()
    assert header.lap.caption.text() == strings.HEADER_LAP.format(number=5)
    assert header.lap.value.text() == "1:43.581"
    assert header.reference.value.text() == "volta 3 · 1:43.881"
    assert header.delta.value.text() == "-0.300"


def test_a_faster_lap_is_green_and_a_slower_one_red(qt_app):
    header = SessionHeader()
    header.show_summary(_summary(delta_s=-0.3))
    assert theme.COLOUR_THROTTLE in _colour(header.delta.value)
    header.show_summary(_summary(delta_s=+0.3))
    assert theme.COLOUR_BRAKE in _colour(header.delta.value)


def test_a_session_best_sector_is_marked_and_the_others_show_their_gap(qt_app):
    header = SessionHeader()
    header.show_summary(_summary())

    s1, _s2, s3 = header.sectors
    assert theme.TRACE_IDEAL in _colour(s1.value)
    assert s1.value.text() == "37.385"
    assert s3.value.text() == "38.085  +0.246"
    assert theme.TRACE_IDEAL not in _colour(s3.value)


def test_no_comparison_is_said_rather_than_left_blank(qt_app):
    header = SessionHeader()
    header.show_summary(_summary(reference=None, delta_s=None))
    assert header.reference.value.text() == strings.HEADER_REFERENCE_NONE
    assert header.delta.value.text() == "--"


def test_the_ideal_lap_is_shown_with_what_it_is_worth(qt_app):
    header = SessionHeader()
    header.show_summary(_summary())
    assert header.ideal.value.text() == "1:42.484 (-1.097 s)"


def test_missing_sectors_are_padded_not_dropped(qt_app):
    header = SessionHeader()
    header.show_summary(_summary(sectors=()))
    assert [stat.value.text() for stat in header.sectors] == ["--", "--", "--"]


def test_clearing_the_header_brings_the_hint_back(qt_app):
    header = SessionHeader()
    header.show_summary(_summary())
    header.clear()
    assert not header.placeholder.isHidden()
    assert header.lap.isHidden()


def test_the_header_never_sets_the_window_s_minimum_width(qt_app):
    header = SessionHeader()
    header.show_summary(_summary())
    assert header.minimumSizeHint().width() < 300


# --- lap list -------------------------------------------------------------------


def _lap(index, time_s, sectors=(None, None, None), flags=(LapFlag.VALID,)):
    return Lap(
        index=index, number=index, t_start=0.0, t_end=time_s,
        official_time_s=time_s, sector_times_s=sectors, flags=frozenset(flags),
    )


def _laps():
    return [
        _lap(0, 150.0, (60.0, 40.0, 50.0), (LapFlag.PARTIAL,)),
        _lap(1, 105.0, (38.0, 29.0, 38.0)),
        _lap(2, 104.0, (37.5, 28.6, 37.9)),
        _lap(3, 104.5, (37.4, 29.2, 37.9)),
        # Fastest first sector of all, but invalidated: it must not count.
        _lap(4, 103.0, (36.0, 29.0, 38.0), (LapFlag.VALID, LapFlag.INVALIDATED)),
    ]


def test_the_best_lap_is_the_fastest_comparable_one():
    assert best_lap(_laps()).index == 2


def test_best_sectors_ignore_laps_that_cannot_be_compared():
    assert best_sectors(_laps()) == (37.4, 28.6, 37.9)


def test_every_lap_gets_a_row_in_the_order_driven(qt_app):
    laps = LapList()
    laps.show_laps(_laps(), current_index=1)
    table = laps.table
    assert table.rowCount() == 5
    assert [table.item(r, COLUMN_LAP).text() for r in range(5)] == ["0", "1", "2", "3", "4"]


def test_the_best_lap_is_marked_and_others_show_their_gap(qt_app):
    laps = LapList()
    laps.show_laps(_laps())
    table = laps.table
    assert table.item(2, COLUMN_GAP).text() == strings.LAPS_MARK_BEST
    assert table.item(2, COLUMN_TIME).font().bold()
    assert table.item(1, COLUMN_GAP).text() == "+1.000"
    # A lap that cannot be compared has no gap to the best.
    assert table.item(0, COLUMN_GAP).text() == "--"


def test_best_sectors_are_coloured(qt_app):
    laps = LapList()
    laps.show_laps(_laps())
    table = laps.table
    best_colour = theme.TRACE_IDEAL.lower()
    assert table.item(3, COLUMN_S1).foreground().color().name() == best_colour
    assert table.item(2, COLUMN_S2).foreground().color().name() == best_colour
    assert table.item(1, COLUMN_S1).foreground().color().name() != best_colour


def test_the_reference_lap_is_marked(qt_app):
    laps = LapList()
    laps.show_laps(_laps(), current_index=1, reference_index=2)
    assert strings.LAPS_MARK_REFERENCE in laps.table.item(2, COLUMN_LAP).text()


def test_showing_a_lap_selects_it_without_emitting(qt_app):
    laps = LapList()
    emitted = []
    laps.lap_chosen.connect(emitted.append)
    laps.show_laps(_laps(), current_index=3)
    assert laps.table.selectionModel().selectedRows()[0].row() == 3
    assert emitted == []


def test_picking_a_row_emits_its_lap_index(qt_app):
    laps = LapList()
    laps.show_laps(_laps(), current_index=1)
    emitted = []
    laps.lap_chosen.connect(emitted.append)
    laps.table.selectRow(3)
    assert emitted == [3]


def test_the_lap_list_summarises_the_session(qt_app):
    laps = LapList()
    laps.show_laps(_laps())
    assert laps.summary.text() == strings.LAPS_SUMMARY.format(
        n=5, comparable=3, best="1:44.000"
    )


def test_an_empty_lap_list_shows_a_hint(qt_app):
    laps = LapList()
    laps.show_laps(_laps())
    laps.clear()
    assert laps.table.isHidden()
    assert not laps.placeholder.isHidden()


# --- corner card ---------------------------------------------------------------


def _rows():
    braked = Corner(
        index=0, apex_distance_m=760.0, minimum_speed_ms=62.6 / 3.6,
        entry_speed_ms=255.7 / 3.6, braking_distance_m=567.0,
        throttle_distance_m=762.0, coasting_time_s=0.86, trail_braking_m=187.0,
        start_distance_m=0.0, end_distance_m=835.0, name="T1 First Corner",
    )
    flat = Corner(
        index=1, apex_distance_m=910.0, minimum_speed_ms=154.3 / 3.6,
        start_distance_m=835.0, end_distance_m=1130.0, name="T2",
    )
    return [
        CornerRow(braked, delta_s=0.120, speed_delta_ms=-1.0, best_lap_index=3, gain_s=0.2),
        CornerRow(flat, delta_s=-0.010, speed_delta_ms=0.5, best_lap_index=5, gain_s=0.0),
    ]


def test_the_card_opens_on_the_first_corner(qt_app):
    card = CornerDetail()
    card.show_rows(_rows(), comparing=True, has_ideal=True)
    assert card.shown_label == "T1 First Corner"
    assert card.title.text() == "T1 First Corner"
    assert card.values["min_speed"].text() == "62.6 km/h"
    assert card.values["braking"].text() == "193 m"


def test_the_card_follows_the_cursor_to_the_nearest_apex(qt_app):
    card = CornerDetail()
    card.show_rows(_rows(), comparing=True, has_ideal=True)
    card.select_corner_at(890.0)
    assert card.shown_label == "T2"


def test_a_flat_out_corner_says_so(qt_app):
    card = CornerDetail()
    card.show_rows(_rows(), comparing=True, has_ideal=True)
    card.select_corner_at(910.0)
    assert card.values["braking"].text() == strings.DETAIL_FLAT


def test_the_comparison_is_coloured_by_who_was_better(qt_app):
    card = CornerDetail()
    card.show_rows(_rows(), comparing=True, has_ideal=True)
    assert card.values["time_delta"].text() == "+0.120 s"
    assert theme.COLOUR_BRAKE in card.values["time_delta"].styleSheet()
    card.select_corner_at(910.0)
    assert theme.COLOUR_THROTTLE in card.values["time_delta"].styleSheet()


def test_without_a_comparison_the_card_says_so(qt_app):
    card = CornerDetail()
    card.show_rows(_rows(), comparing=False, has_ideal=False)
    assert not card.not_comparing.isHidden()
    assert card.reference_form.isHidden()
    assert card.ideal_form.isHidden()


def test_a_lap_without_corners_clears_the_card(qt_app):
    card = CornerDetail()
    card.show_rows(_rows(), comparing=True, has_ideal=True)
    card.show_rows([], comparing=True, has_ideal=True)
    assert card.shown_label is None
    assert not card.placeholder.isHidden()


# --- corner numbers on the map --------------------------------------------------


def _square():
    side = np.linspace(0.0, 100.0, 101)
    x = np.concatenate([side, np.full(100, 100.0), side[::-1][1:], np.zeros(100)])
    y = np.concatenate([np.zeros(101), side[1:], np.full(100, 100.0), side[::-1][1:]])
    grid = np.arange(len(x), dtype=float)
    return x, y, grid


def test_corner_numbers_are_drawn_on_the_map(qt_app):
    track = TrackMap()
    x, y, grid = _square()
    track.show_path(x, y, grid)
    track.set_corner_labels([100.0, 200.0], ["T1", "T2"])
    assert track.corner_labels == ["T1", "T2"]


def test_corner_numbers_survive_a_change_of_colouring(qt_app):
    track = TrackMap()
    x, y, grid = _square()
    states = np.zeros(len(x), dtype=np.int8)
    track.show_path(x, y, grid, pedal_states=states, loss_classes=states)
    track.set_corner_labels([100.0], ["T1"])
    from lmu_telemetry.presentation.track_map import MapColour

    track.set_colour_mode(MapColour.DELTA)
    assert track.corner_labels == ["T1"]


def test_clearing_the_map_removes_the_corner_numbers(qt_app):
    track = TrackMap()
    x, y, grid = _square()
    track.show_path(x, y, grid)
    track.set_corner_labels([100.0], ["T1"])
    track.clear()
    assert track.corner_labels == []


# --- the demo session in a real window ------------------------------------------

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


def test_opening_the_demo_fills_every_new_panel(demo_window):
    window = demo_window
    assert window.header.track.text() == "Fuji Speedway"
    assert window.lap_list.table.rowCount() == len(
        window._sessions.get(window._selection).session.laps
    )
    assert window.corner_detail.shown_label == "T1 First Corner"


def test_the_map_and_traces_use_the_short_corner_numbers(demo_window):
    labels = demo_window.track_map.corner_labels
    assert labels[0] == "T1" and labels[-1] == "T16"
    assert len(labels) == 16


def test_moving_the_cursor_walks_the_corner_card(demo_window):
    window = demo_window
    corners = window._current.primary.corners
    for corner in (corners[5], corners[-1], corners[0]):
        window._on_cursor_moved(corner.apex_distance_m)
        assert window.corner_detail.shown_label == corner.label


def test_picking_a_lap_in_the_list_opens_it_and_the_tree_follows(demo_window):
    window = demo_window
    laps = window._sessions.get(window._selection).session.laps
    other = next(
        lap for lap in laps
        if lap.is_comparable and lap.index != window._selection.lap_index
    )
    window.lap_list.lap_chosen.emit(other.index)
    assert window._selection.lap_index == other.index
    assert window.browser.current_lap().lap_index == other.index
    assert window.header.lap.caption.text() == strings.HEADER_LAP.format(
        number=other.number
    )


def test_a_lap_that_cannot_be_drawn_keeps_the_lap_list(demo_window):
    """The list is the way out of a partial lap with nothing to draw."""
    window = demo_window
    laps = window._sessions.get(window._selection).session.laps
    tail = next(lap for lap in reversed(laps) if lap.is_partial)
    opened = window._sessions.get(window._selection)
    original = opened.analysis_for
    opened.analysis_for = lambda index: None if index == tail.index else original(index)
    try:
        window.lap_list.lap_chosen.emit(tail.index)
    finally:
        opened.analysis_for = original
    assert window.lap_list.table.rowCount() == len(laps)
    assert not window.lap_list.table.isHidden()
    assert not window.header.placeholder.isHidden()
