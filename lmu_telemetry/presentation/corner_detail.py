"""One corner, read on its own.

The corner table is for scanning: a row per corner, a column per measurement.
This card is for the corner being looked at - picked in the table, on the map
or on the traces - with each figure labelled in words and grouped by the
question it answers: how was it driven, how does that compare with the
reference, and what is it worth against the ideal lap.

It follows the window's single cursor, so moving along the lap walks the card
through the corners, and it chooses the corner the same way the table does -
the nearest apex - so the two always agree on which corner is meant. They agree
on which corner costs the most for the same reason: both ask
`pipeline.costliest_corner`, and both mark it with the same words.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from PySide6 import QtCore, QtWidgets

from lmu_telemetry.application.pipeline import (
    CornerRow, CostBasis, CostliestCorner, costliest_corner,
)
from lmu_telemetry.presentation import theme
from lmu_telemetry.presentation.corner_table import coasting_tone, costliest_cost
from lmu_telemetry.shared import strings
from lmu_telemetry.shared.formatting import (
    MISSING, format_distance, format_gap, format_seconds, format_speed,
)


class CornerDetail(QtWidgets.QWidget):
    """The card. `show_rows` gives it the lap's corners; the cursor picks one."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: list[CornerRow] = []
        self._costliest: CostliestCorner | None = None
        self._comparing = False
        self._has_ideal = False
        self._shown: int | None = None
        self._build()
        self.clear()

    def _build(self) -> None:
        # The card scrolls rather than setting its own height: sixteen labelled
        # figures are taller than the bottom row should be, and a card that
        # insisted on its full height would push the traces up to make room.
        frame = QtWidgets.QVBoxLayout(self)
        frame.setContentsMargins(0, 0, 0, 0)
        frame.setSpacing(0)
        content = QtWidgets.QWidget()
        content.setObjectName("detail_content")
        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setObjectName("detail_scroll")
        self.scroll.setWidget(content)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        frame.addWidget(self.scroll)

        outer = QtWidgets.QVBoxLayout(content)
        outer.setContentsMargins(10, 6, 10, 8)
        outer.setSpacing(2)

        self.title = QtWidgets.QLabel()
        self.title.setProperty("role", "title")
        self.subtitle = QtWidgets.QLabel()
        self.subtitle.setProperty("role", "caption")
        outer.addWidget(self.title)
        outer.addWidget(self.subtitle)

        # Shown only on the corner the table marks: the mark and the words say
        # it, the warning tone and the weight only repeat it.
        self.costliest_flag = QtWidgets.QLabel()
        self.costliest_flag.setProperty("role", "caption")
        self.costliest_flag.setWordWrap(True)
        self.costliest_flag.setFont(theme.emphasised(self.costliest_flag.font()))
        theme.set_tone(self.costliest_flag, theme.Tone.WARNING)
        outer.addWidget(self.costliest_flag)

        self.body = QtWidgets.QWidget()
        body = QtWidgets.QVBoxLayout(self.body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        outer.addWidget(self.body)

        self.values: dict[str, QtWidgets.QLabel] = {}

        body.addWidget(_section(strings.DETAIL_SECTION_LAP))
        body.addLayout(self._form([
            ("min_speed", strings.DETAIL_MIN_SPEED),
            ("entry_speed", strings.DETAIL_ENTRY_SPEED),
            ("braking", strings.DETAIL_BRAKING),
            ("braking_point", strings.DETAIL_BRAKING_POINT),
            ("throttle", strings.DETAIL_THROTTLE),
            ("trail", strings.DETAIL_TRAIL),
            ("coasting", strings.DETAIL_COASTING),
        ]))

        body.addWidget(_section(strings.DETAIL_SECTION_REFERENCE))
        self.not_comparing = QtWidgets.QLabel(strings.DETAIL_NOT_COMPARING)
        self.not_comparing.setProperty("role", "placeholder")
        body.addWidget(self.not_comparing)
        self.reference_form = QtWidgets.QWidget()
        self.reference_form.setLayout(self._form([
            ("speed_delta", strings.DETAIL_SPEED_DELTA),
            ("time_delta", strings.DETAIL_TIME_DELTA),
        ]))
        body.addWidget(self.reference_form)

        self.ideal_section = _section(strings.DETAIL_SECTION_IDEAL)
        body.addWidget(self.ideal_section)
        self.ideal_form = QtWidgets.QWidget()
        self.ideal_form.setLayout(self._form([
            ("gain", strings.DETAIL_GAIN),
            ("best_lap", strings.DETAIL_BEST_LAP),
        ]))
        body.addWidget(self.ideal_form)
        outer.addStretch(1)

        self.placeholder = QtWidgets.QLabel(strings.DETAIL_EMPTY)
        self.placeholder.setProperty("role", "placeholder")
        self.placeholder.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.placeholder.setWordWrap(True)
        outer.addWidget(self.placeholder, stretch=1)

    def _form(self, fields: list[tuple[str, str]]) -> QtWidgets.QFormLayout:
        form = QtWidgets.QFormLayout()
        form.setContentsMargins(0, 4, 0, 2)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(3)
        form.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        for key, caption in fields:
            label = QtWidgets.QLabel(caption)
            label.setProperty("role", "caption")
            value = QtWidgets.QLabel("--")
            value.setAlignment(
                QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter
            )
            self.values[key] = value
            form.addRow(label, value)
        return form

    # -- data --------------------------------------------------------------

    def show_rows(
        self,
        rows: Sequence[CornerRow],
        *,
        comparing: bool,
        has_ideal: bool,
    ) -> None:
        """Take the corners of the lap on screen. Shows the first until the
        cursor picks another, so the card is never blank beside a full table."""
        self._rows = list(rows)
        self._costliest = costliest_corner(self._rows)
        self._comparing = comparing
        self._has_ideal = has_ideal
        self._shown = None
        if not self._rows:
            self.clear()
            return
        self._show(0)

    def select_corner_at(self, distance_m: float) -> None:
        """Show the corner whose apex is nearest a distance."""
        if not self._rows:
            return
        apexes = np.array([row.corner.apex_distance_m for row in self._rows])
        nearest = int(np.argmin(np.abs(apexes - distance_m)))
        if nearest != self._shown:
            self._show(nearest)

    @property
    def shown_label(self) -> str | None:
        """Which corner the card is showing, for tests and accessibility."""
        if self._shown is None:
            return None
        return self._rows[self._shown].corner.label

    @property
    def shows_costliest(self) -> bool:
        """Whether the corner on the card is the one the table marks."""
        return (self._shown is not None and self._costliest is not None
                and self._costliest.position == self._shown)

    def _show(self, position: int) -> None:
        self._shown = position
        row = self._rows[position]
        corner = row.corner

        self.title.setText(corner.label)
        self.subtitle.setText(strings.DETAIL_APEX.format(
            distance=format_distance(corner.apex_distance_m),
            start=format_distance(corner.start_distance_m),
            end=format_distance(corner.end_distance_m),
        ))
        costliest = self._costliest if self.shows_costliest else None
        self.costliest_flag.setVisible(costliest is not None)
        if costliest is not None:
            self.costliest_flag.setText(strings.DETAIL_COSTLIEST.format(
                mark=strings.COSTLIEST_MARK, cost=costliest_cost(costliest),
            ))

        self._set("min_speed", _with_unit(strings.DETAIL_KMH,
                                          format_speed(corner.minimum_speed_ms)))
        self._set("entry_speed", _with_unit(strings.DETAIL_KMH,
                                            format_speed(corner.entry_speed_ms)))
        if corner.braking_distance_m is None:
            self._set("braking", strings.DETAIL_FLAT)
            self._set("braking_point", MISSING)
        else:
            self._set("braking", _with_unit(
                strings.DETAIL_M, format_distance(corner.braking_length_m)))
            self._set("braking_point", _with_unit(
                strings.DETAIL_AT_M, format_distance(corner.braking_distance_m)))
        self._set("throttle", _with_unit(
            strings.DETAIL_AT_M, format_distance(corner.throttle_distance_m)))
        self._set("trail", _with_unit(
            strings.DETAIL_M, format_distance(corner.trail_braking_m)))
        self._set(
            "coasting",
            _with_unit(strings.DETAIL_S, format_seconds(corner.coasting_time_s, 2)),
            # The same threshold the table uses to flag a hesitation.
            tone=coasting_tone(corner.coasting_time_s),
        )

        self.not_comparing.setVisible(not self._comparing)
        self.reference_form.setVisible(self._comparing)
        if self._comparing:
            self._set(
                "speed_delta",
                _with_unit(strings.DETAIL_KMH,
                           format_speed(row.speed_delta_ms, signed=True)),
                tone=theme.verdict(row.speed_delta_ms, higher_is_better=True),
            )
            self._set(
                "time_delta",
                _with_unit(strings.DETAIL_S, format_gap(row.delta_s)),
                tone=theme.verdict(row.delta_s, higher_is_better=False),
            )

        self.ideal_section.setVisible(self._has_ideal)
        self.ideal_form.setVisible(self._has_ideal)
        if self._has_ideal:
            # Warning only where the table puts it: on the costliest corner.
            # Any gain over a threshold used to qualify, which marked corners
            # the table did not.
            self._set("gain", _with_unit(strings.DETAIL_S, format_seconds(row.gain_s)),
                      tone=theme.Tone.WARNING
                      if costliest is not None and costliest.basis is CostBasis.IDEAL
                      else None)
            self._set("best_lap", MISSING if row.best_lap_index is None
                      else strings.DETAIL_LAP.format(value=row.best_lap_index))

        self.placeholder.hide()
        for widget in (self.title, self.subtitle, self.body):
            widget.show()

    def _set(self, key: str, text: str, *, tone: theme.Tone | None = None) -> None:
        label = self.values[key]
        label.setText(text)
        theme.set_tone(label, tone)

    def clear(self) -> None:
        self._rows = []
        self._costliest = None
        self._shown = None
        for widget in (self.title, self.subtitle, self.costliest_flag, self.body):
            widget.hide()
        self.placeholder.show()


def _section(text: str) -> QtWidgets.QLabel:
    label = QtWidgets.QLabel(text)
    label.setProperty("role", "section")
    return label


def _with_unit(template: str, figure: str) -> str:
    """A figure in its unit's template, or "--" alone: "-- km/h" reads as a
    value that exists and is unknown, when there is no value at all."""
    return MISSING if figure == MISSING else template.format(value=figure)
