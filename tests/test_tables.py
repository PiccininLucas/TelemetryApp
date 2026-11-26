"""The corner table, the corner card and the consistency panel, read together.

Three things are held here:

- **One costliest corner.** `pipeline.costliest_corner` is the only rule, so
  the table's marked row and the card's flag can never disagree; the marked
  row is told by weight and a mark, not by colour alone, and the rows never
  move.
- **The column groups.** The band above the header follows the sections
  through hiding, resizing and scrolling, and never widens a column.
- **The consistency selectors.** Chips, one choice each; the stint row only
  with more than one stint; the measure kept across stints; units in every
  name; reachable by keyboard and named for screen readers.

Widgets are fed plain values, offscreen.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PySide6 import QtCore, QtGui, QtTest, QtWidgets  # noqa: E402

from lmu_telemetry.application.pipeline import (  # noqa: E402
    CornerRow, CostBasis, StintAnalysis, costliest_corner,
)
from lmu_telemetry.domain.analysis.consistency import (  # noqa: E402
    ConsistencyReport, CornerConsistency,
)
from lmu_telemetry.domain.models import Corner  # noqa: E402
from lmu_telemetry.presentation import theme  # noqa: E402
from lmu_telemetry.presentation.consistency_panel import (  # noqa: E402
    METRICS, ConsistencyPanel,
)
from lmu_telemetry.presentation.corner_detail import CornerDetail  # noqa: E402
from lmu_telemetry.presentation.corner_table import (  # noqa: E402
    _INDEX_OF, _MARK_ROLE, COLUMN_DELTA, COLUMN_GAIN, COLUMN_NAME, COLUMNS,
    COMPARISON_COLUMNS, GROUPS, IDEAL_COLUMNS, CornerTable,
)
from lmu_telemetry.shared import strings  # noqa: E402

NAN = float("nan")


@pytest.fixture(scope="module")
def qt_app():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    theme.apply(app)
    yield app


def _corner(index: int, name: str | None = None) -> Corner:
    apex = 1000.0 * (index + 1)
    return Corner(
        index=index, apex_distance_m=apex, minimum_speed_ms=20.0 + index,
        entry_speed_ms=70.0, braking_distance_m=apex - 150.0,
        throttle_distance_m=apex + 40.0, coasting_time_s=0.1,
        trail_braking_m=60.0, start_distance_m=apex - 200.0,
        end_distance_m=apex + 200.0, name=name or f"T{index + 1}",
    )


def _rows(*, gains=None, deltas=None) -> list[CornerRow]:
    """One row per value given; `None` lists leave that comparison off."""
    n = len(gains if gains is not None else deltas if deltas is not None else [0, 0, 0])
    return [
        CornerRow(
            corner=_corner(index),
            delta_s=None if deltas is None else deltas[index],
            speed_delta_ms=None if deltas is None else 0.5,
            best_lap_index=None if gains is None else 3,
            gain_s=None if gains is None else gains[index],
        )
        for index in range(n)
    ]


# --- the rule ---------------------------------------------------------------------


@pytest.mark.parametrize(("gains", "deltas", "expected"), [
    # With an ideal lap: the most to gain, whatever the comparison says.
    ([0.0, 0.05, 0.10], [0.4, -0.1, 0.0], (2, CostBasis.IDEAL)),
    ([0.30, 0.05, 0.10], None, (0, CostBasis.IDEAL)),
    # Nothing left to gain: no corner, and no falling back to the comparison.
    ([0.0, 0.0, 0.0], [0.4, 0.2, 0.1], None),
    # A gap in the ideal lap's coverage is skipped, not treated as zero.
    ([None, NAN, 0.02], None, (2, CostBasis.IDEAL)),
    # Without one: where the lap loses most to the comparison.
    (None, [-0.2, 0.15, 0.05], (1, CostBasis.COMPARISON)),
    (None, [0.1, None, NAN], (0, CostBasis.COMPARISON)),
    # Faster everywhere: nothing costs anything.
    (None, [-0.2, -0.1, 0.0], None),
    # Ties go to the first corner of the lap.
    ([0.1, 0.1, 0.0], None, (0, CostBasis.IDEAL)),
    # Neither: no mark.
    (None, None, None),
])
def test_the_costliest_corner(gains, deltas, expected):
    result = costliest_corner(_rows(gains=gains, deltas=deltas))
    if expected is None:
        assert result is None
    else:
        assert (result.position, result.basis) == expected
        assert result.seconds > 0.0


def test_no_rows_no_costliest_corner():
    assert costliest_corner([]) is None


# --- the table marks it -------------------------------------------------------------


def _marked_rows(table: CornerTable) -> list[int]:
    column = _INDEX_OF[COLUMN_NAME]
    return [row for row in range(table.table.rowCount())
            if table.table.item(row, column).data(_MARK_ROLE)]


def _weight(item: QtWidgets.QTableWidgetItem) -> QtGui.QFont.Weight:
    return item.font().weight()


def test_the_table_marks_the_whole_row_not_just_a_cell(qt_app):
    table = CornerTable()
    table.show_corners(_rows(gains=[0.0, 0.05, 0.10]), show_ideal=True)

    assert _marked_rows(table) == [2]
    for column in range(len(COLUMNS)):
        marked = table.table.item(2, column)
        plain = table.table.item(0, column)
        # Colour is never the only cue: the weight changes on every cell.
        assert _weight(marked) == QtGui.QFont.Weight.DemiBold, COLUMNS[column]
        assert _weight(plain) != QtGui.QFont.Weight.DemiBold
        # No tint behind the figures: it took the loss colour under AA.
        assert marked.background().style() == QtCore.Qt.BrushStyle.NoBrush


def test_the_marked_row_has_a_bar_at_its_left_edge(qt_app):
    table = CornerTable()
    table.show_corners(_rows(gains=[0.0, 0.05, 0.10]), show_ideal=True)
    table.resize(900, 300)
    table.show()
    QtWidgets.QApplication.processEvents()
    view = table.table
    image = view.viewport().grab().toImage()
    bar = theme.standout_brush().color().name()

    def left_edge(row: int) -> str:
        y = view.rowViewportPosition(row) + view.rowHeight(row) // 2
        return image.pixelColor(1, y).name()

    assert left_edge(2) == bar
    assert left_edge(0) != bar


def test_the_marked_name_is_not_cut_short(qt_app):
    """The mark and the bar are drawn, not written, so the column has to be
    told about them or the name is elided to make room."""
    table = CornerTable()
    table.show_corners(_rows(gains=[0.0, 0.05, 0.10]), show_ideal=True)
    view = table.table
    column = _INDEX_OF[COLUMN_NAME]
    delegate = view.itemDelegateForColumn(column)
    option = QtWidgets.QStyleOptionViewItem()
    option.initFrom(view)
    plain = delegate.sizeHint(option, view.model().index(0, column)).width()
    marked = delegate.sizeHint(option, view.model().index(2, column)).width()
    mark_width = QtGui.QFontMetrics(theme.emphasised(view.font())).horizontalAdvance(
        f"{strings.COSTLIEST_MARK} ")
    assert marked >= plain + theme.STANDOUT_BAR_WIDTH + mark_width - 2
    table.resize(900, 300)
    table.show()
    QtWidgets.QApplication.processEvents()
    assert view.columnWidth(column) >= marked


def test_the_mark_is_drawn_not_written(qt_app):
    """The name is the user's and editable: a mark in its text would end up in
    the editor and, from there, in the catalog."""
    table = CornerTable()
    table.show_corners(_rows(gains=[0.0, 0.05, 0.10]), show_ideal=True)
    column = _INDEX_OF[COLUMN_NAME]
    item = table.table.item(2, column)
    assert item.text() == "T3"

    delegate = table.table.itemDelegateForColumn(column)
    option = QtWidgets.QStyleOptionViewItem()
    delegate.initStyleOption(option, table.table.model().index(2, column))
    assert option.text == f"{strings.COSTLIEST_MARK} T3"
    option = QtWidgets.QStyleOptionViewItem()
    delegate.initStyleOption(option, table.table.model().index(0, column))
    assert option.text == "T1"

    renames = []
    table.corner_renamed.connect(lambda *args: renames.append(args))
    item.setText("Curva do S")
    assert renames == [(2, 3000.0, "Curva do S")]


def test_the_marked_row_says_why(qt_app):
    table = CornerTable()
    table.show_corners(_rows(gains=[0.0, 0.05, 0.10]), show_ideal=True)
    tooltip = table.table.item(2, _INDEX_OF[COLUMN_NAME]).toolTip()
    assert strings.COSTLIEST_MARK in tooltip and "0.100" in tooltip
    assert strings.CORNERS_TOOLTIP_NAME in tooltip     # renaming still explained


def test_without_an_ideal_lap_the_comparison_decides(qt_app):
    """The Δt cell keeps the loss colour, which says "slower"; the row's tint,
    weight and mark say "this one"."""
    table = CornerTable()
    table.show_corners(_rows(deltas=[-0.2, 0.15, 0.05]), show_comparison=True)
    assert _marked_rows(table) == [1]
    delta = table.table.item(1, _INDEX_OF[COLUMN_DELTA])
    assert delta.foreground().color().name() == theme.LOSS


def test_with_nothing_to_measure_against_nothing_is_marked(qt_app):
    table = CornerTable()
    table.show_corners(_rows())
    assert _marked_rows(table) == []
    assert table.costliest is None


def test_marking_never_reorders_the_rows(qt_app):
    """Order around the lap is what the row order means."""
    table = CornerTable()
    table.show_corners(_rows(gains=[0.0, 0.3, 0.1]), show_ideal=True)
    names = [table.table.item(row, _INDEX_OF[COLUMN_NAME]).text()
             for row in range(3)]
    assert names == ["T1", "T2", "T3"]
    assert not table.table.isSortingEnabled()


def test_a_new_lap_moves_the_mark(qt_app):
    table = CornerTable()
    table.show_corners(_rows(gains=[0.0, 0.3, 0.1]), show_ideal=True)
    table.show_corners(_rows(gains=[0.4, 0.0, 0.1]), show_ideal=True)
    assert _marked_rows(table) == [0]
    assert _weight(table.table.item(1, 0)) != QtGui.QFont.Weight.DemiBold


# --- the card agrees ------------------------------------------------------------------


@pytest.mark.parametrize(("gains", "deltas"), [
    ([0.0, 0.05, 0.10], [0.4, -0.1, 0.0]),
    (None, [-0.2, 0.15, 0.05]),
    (None, None),
    ([0.0, 0.0, 0.0], [0.3, 0.0, 0.0]),
])
def test_the_card_flags_the_corner_the_table_marks(qt_app, gains, deltas):
    rows = _rows(gains=gains, deltas=deltas)
    table = CornerTable()
    table.show_corners(rows, show_comparison=deltas is not None,
                       show_ideal=gains is not None)
    card = CornerDetail()
    card.show_rows(rows, comparing=deltas is not None, has_ideal=gains is not None)

    flagged = []
    for row in rows:
        card.select_corner_at(row.corner.apex_distance_m)
        if card.shows_costliest:
            flagged.append(card.shown_label)
            assert not card.costliest_flag.isHidden()
            assert card.costliest_flag.text().startswith(strings.COSTLIEST_MARK)
        else:
            assert card.costliest_flag.isHidden()

    marked = [rows[position].corner.label for position in _marked_rows(table)]
    assert flagged == marked


def test_the_card_warns_on_the_gain_only_where_the_table_does(qt_app):
    """The card used to colour any gain over 0.05 s, marking corners the table
    did not."""
    rows = _rows(gains=[0.06, 0.08, 0.20])
    card = CornerDetail()
    card.show_rows(rows, comparing=False, has_ideal=True)
    tones = []
    for row in rows:
        card.select_corner_at(row.corner.apex_distance_m)
        tones.append(card.values["gain"].property("tone"))
    assert tones == ["", "", theme.Tone.WARNING.value]


def test_the_card_shows_nothing_rather_than_a_unit_alone(qt_app):
    corner = Corner(index=0, apex_distance_m=500.0, minimum_speed_ms=NAN,
                    start_distance_m=400.0, end_distance_m=600.0)
    card = CornerDetail()
    card.show_rows([CornerRow(corner)], comparing=False, has_ideal=False)
    assert card.values["min_speed"].text() == "--"
    assert card.values["throttle"].text() == "--"


# --- the column groups ------------------------------------------------------------------


def test_every_measured_column_is_in_exactly_one_group():
    grouped = [column for group in GROUPS for column in group.columns]
    assert len(grouped) == len(set(grouped))
    assert set(grouped) == set(range(len(COLUMNS))) - {_INDEX_OF[COLUMN_NAME]}
    labels = [group.label for group in GROUPS]
    assert labels == [strings.CORNERS_GROUP_LAP, strings.CORNERS_GROUP_REFERENCE,
                      strings.CORNERS_GROUP_IDEAL]


def test_the_card_files_figures_under_the_same_questions():
    assert (strings.DETAIL_SECTION_LAP, strings.DETAIL_SECTION_REFERENCE,
            strings.DETAIL_SECTION_IDEAL) == tuple(group.label for group in GROUPS)


def _shown(table: CornerTable, **flags) -> CornerTable:
    table.show_corners(_rows(gains=[0.0, 0.1, 0.0], deltas=[0.1, 0.0, -0.1]),
                       ideal_summary="Volta ideal 1:42.507", **flags)
    table.resize(1400, 300)
    table.show()
    QtWidgets.QApplication.processEvents()
    return table


def test_the_band_sits_above_the_column_labels(qt_app):
    table = _shown(CornerTable(), show_comparison=True, show_ideal=True)
    header = table.header
    assert header.band_height() > 0
    assert header.height() >= header.band_height() + 10
    # Painting runs without complaint, band and sections together.
    assert not table.table.grab().isNull()


def test_a_hidden_group_draws_nothing_and_a_shown_one_spans_its_columns(qt_app):
    table = _shown(CornerTable(), show_comparison=False, show_ideal=True)
    header = table.header
    reference, ideal = GROUPS[1], GROUPS[2]
    assert header.group_span(reference) is None

    left, right = header.group_span(ideal)
    columns = sorted(_INDEX_OF[key] for key in IDEAL_COLUMNS)
    assert left == header.sectionViewportPosition(columns[0])
    assert right == (header.sectionViewportPosition(columns[-1])
                     + header.sectionSize(columns[-1]))

    table.show_corners(_rows(deltas=[0.1, 0.0, -0.1]), show_comparison=True)
    QtWidgets.QApplication.processEvents()
    assert header.group_span(reference) is not None
    assert header.group_span(ideal) is None


def test_the_groups_do_not_overlap_and_read_left_to_right(qt_app):
    table = _shown(CornerTable(), show_comparison=True, show_ideal=True)
    spans = [table.header.group_span(group) for group in GROUPS]
    assert all(span is not None for span in spans)
    for (_l1, right), (left, _r2) in zip(spans, spans[1:]):
        assert right <= left


def test_the_band_scrolls_with_the_columns(qt_app):
    table = CornerTable()
    _shown(table, show_comparison=True, show_ideal=True)
    table.resize(320, 300)
    QtWidgets.QApplication.processEvents()
    ideal = GROUPS[2]
    before = table.header.group_span(ideal)
    bar = table.table.horizontalScrollBar()
    assert bar.maximum() > 0
    bar.setValue(bar.maximum())
    QtWidgets.QApplication.processEvents()
    after = table.header.group_span(ideal)
    assert after[0] == before[0] - table.header.offset()
    assert after[1] - after[0] == before[1] - before[0]


def test_the_band_follows_a_resized_column(qt_app):
    table = _shown(CornerTable(), show_comparison=True, show_ideal=True)
    header = table.header
    header.setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Interactive)
    column = _INDEX_OF[COLUMN_DELTA]
    left, right = header.group_span(GROUPS[1])
    header.resizeSection(column, header.sectionSize(column) + 40)
    assert header.group_span(GROUPS[1]) == (left, right + 40)


def test_the_band_never_widens_a_column(qt_app):
    """A group label is elided to its columns; the columns are as wide as
    their own labels and figures, with or without the band."""
    grouped = _shown(CornerTable(), show_comparison=True, show_ideal=True)
    plain = CornerTable()
    plain.header.set_groups([])
    _shown(plain, show_comparison=True, show_ideal=True)
    for column in range(len(COLUMNS) - 1):          # the last one stretches
        assert grouped.header.sectionSize(column) == plain.header.sectionSize(column)
    assert (grouped.minimumSizeHint().width()
            == plain.minimumSizeHint().width())


def test_a_column_tooltip_names_its_group(qt_app):
    table = CornerTable()
    for key in IDEAL_COLUMNS:
        tooltip = table.table.horizontalHeaderItem(_INDEX_OF[key]).toolTip()
        assert tooltip.startswith(strings.CORNERS_GROUP_IDEAL)
    for key in COMPARISON_COLUMNS:
        tooltip = table.table.horizontalHeaderItem(_INDEX_OF[key]).toolTip()
        assert tooltip.startswith(strings.CORNERS_GROUP_REFERENCE)


def test_the_table_does_not_set_the_window_width(qt_app):
    """The summary line above the table wraps; it alone used to make the dock
    487 px wide at least."""
    table = CornerTable()
    table.show_corners(
        _rows(gains=[0.0, 0.1, 0.0]), show_ideal=True,
        ideal_summary=strings.IDEAL_SUMMARY.format(
            time="1:42.507", gain="1.057", best="1:43.564", n_laps=4),
    )
    assert table.minimumSizeHint().width() < 200


def test_the_gain_cell_keeps_its_warning(qt_app):
    """Unchanged from before the row was marked: the figure it was chosen by."""
    table = CornerTable()
    table.show_corners(_rows(gains=[0.0, 0.05, 0.10]), show_ideal=True)
    colours = [table.table.item(row, _INDEX_OF[COLUMN_GAIN]).foreground().color().name()
               for row in range(3)]
    assert colours[2] == theme.WARNING
    assert theme.WARNING not in colours[:2]


# --- the consistency selectors --------------------------------------------------------


def _report(offset: float = 0.0) -> ConsistencyReport:
    corners = [
        CornerConsistency(
            corner_index=0, corner_label="Parabolica", apex_distance_m=5186.0,
            n_laps=5, braking_point_std_m=9.0, minimum_speed_std_ms=1.8,
            throttle_point_std_m=6.0,
            braking_points_m=tuple(500.0 + offset + d for d in (0, -20, 10, -10, 5)),
            minimum_speeds_ms=(38.0, 39.0, 40.0, 38.5, 41.0),
            throttle_points_m=(5250.0,) * 5, estimated_time_lost_s=0.31,
        ),
    ]
    return ConsistencyReport(corners, (2, 3, 4, 8, 9), {}, 0.42, 108.594)


def _stints(n: int) -> list[StintAnalysis]:
    return [StintAnalysis(index, tuple(range(10 * index + 1, 10 * index + 6)),
                          _report(offset=100.0 * index))
            for index in range(n)]


def test_one_stint_no_stint_chips(qt_app):
    panel = ConsistencyPanel()
    panel.show_stints(_stints(1))
    assert panel.stint_selector.isHidden()
    panel.show_stints(_stints(3), current_index=1)
    assert not panel.stint_selector.isHidden()
    assert panel.stint_selector.count() == 3
    assert panel.stint_selector.current_index() == 1


def test_choosing_a_stint_asks_for_it(qt_app):
    panel = ConsistencyPanel()
    panel.show_stints(_stints(2))
    asked = []
    panel.stint_changed.connect(asked.append)
    panel.stint_selector.chips()[1].click()
    assert asked == [1]


def test_the_measure_survives_a_change_of_stint(qt_app):
    """Comparing one measure across stints is the reason to switch."""
    stints = _stints(2)
    panel = ConsistencyPanel()
    panel.show_stints(stints)
    panel.metric_selector.chips()[1].click()          # minimum speed
    assert panel.metric is METRICS[1]

    # What the window does on `stint_changed`, and again when a lap of the
    # other stint is opened.
    panel.show_report(stints[1].report, list(stints[1].lap_indices))
    assert panel.metric is METRICS[1]
    panel.show_stints(stints, current_index=1)
    assert panel.metric is METRICS[1]
    _x, y = panel._series.getData()
    assert y.min() > 100.0                            # km/h, not m


def test_a_stint_too_short_to_measure_keeps_the_way_back(qt_app):
    """It used to hide the stint chips too, leaving no way to the others."""
    stints = _stints(2)
    short = StintAnalysis(1, (21,), ConsistencyReport([], (21,), {}, 0.0, 0.0))
    panel = ConsistencyPanel()
    panel.show_stints([stints[0], short])
    panel.show_report(short.report, [21])
    assert not panel.placeholder.isHidden()
    assert not panel.stint_selector.isHidden()
    panel.clear()
    assert panel.stint_selector.isHidden()


@pytest.mark.parametrize("metric", METRICS, ids=lambda m: m.attribute)
def test_every_measure_names_its_unit(metric):
    assert f"({metric.unit})" in metric.chip
    assert f"({metric.unit})" in metric.label


def test_the_plot_title_carries_the_unit(qt_app):
    panel = ConsistencyPanel()
    panel.show_report(_report(), [2, 3, 4, 8, 9])
    panel.metric_selector.chips()[1].click()
    title = panel.plot.getPlotItem().titleLabel.text
    assert strings.CONSISTENCY_UNIT_KMH in title


def test_the_selectors_are_named_for_screen_readers(qt_app):
    panel = ConsistencyPanel()
    panel.show_stints(_stints(2))
    assert panel.stint_selector.accessibleName() == strings.CONSISTENCY_STINT_NAME
    assert panel.metric_selector.accessibleName() == strings.CONSISTENCY_METRIC_NAME
    assert [chip.accessibleName() for chip in panel.metric_selector.chips()] == \
        [metric.label for metric in METRICS]
    for chip in panel.stint_selector.chips():
        assert chip.accessibleName() and chip.toolTip()


def test_the_chips_work_like_radio_buttons_from_the_keyboard(qt_app):
    """Tab stops on the chosen chip only; the arrows move the choice."""
    panel = ConsistencyPanel()
    panel.show_report(_report(), [2, 3, 4, 8, 9])
    panel.show()
    QtWidgets.QApplication.processEvents()
    chips = panel.metric_selector.chips()
    tab = QtCore.Qt.FocusPolicy.TabFocus
    assert chips[0].focusPolicy() & tab
    assert not chips[1].focusPolicy() & tab

    chips[0].setFocus()
    QtTest.QTest.keyClick(chips[0], QtCore.Qt.Key.Key_Right)
    assert panel.metric is METRICS[1]
    assert chips[1].hasFocus()
    assert chips[1].focusPolicy() & tab and not chips[0].focusPolicy() & tab
    _x, y = panel._series.getData()
    assert y.min() > 100.0                            # redrawn in km/h


def test_the_panel_does_not_set_the_window_width(qt_app):
    """The summary and the stint chips used to sit in one unbreakable row,
    which made this panel 674 px wide at least - more than half the window's
    minimum."""
    few, many = ConsistencyPanel(), ConsistencyPanel()
    few.show_stints(_stints(2))
    many.show_stints(_stints(6))
    least = many.minimumSizeHint().width()
    # More stints wrap onto another line instead of widening the panel.
    assert least == few.minimumSizeHint().width()
    assert least < many.stint_selector.sizeHint().width()
    # And the summary wraps rather than holding its whole line.
    assert many.summary.minimumSizeHint().width() < many.summary.sizeHint().width()


def test_the_figures_go_through_the_shared_formats(qt_app):
    panel = ConsistencyPanel()
    panel.show_report(_report(), [2, 3, 4, 8, 9])
    # σ braking (m), σ minimum speed (1.8 m/s in km/h), σ throttle (m), loss (s)
    texts = [panel.table.item(0, column).text() for column in range(2, 6)]
    assert texts == ["9.0", "6.5", "6.0", "0.310"]
    assert "0.420 s" in panel.summary.text()
