"""Tests for lap splitting and classification."""

from __future__ import annotations

import numpy as np
import pytest

from lmu_telemetry.core.models import Lap, LapFlag
from lmu_telemetry.ingest import lap_splitter
from lmu_telemetry.ingest.events import EventSeries


def make_lap(**overrides) -> Lap:
    defaults = dict(
        index=0, number=1, t_start=0.0, t_end=100.0,
        official_time_s=100.0, flags=frozenset({LapFlag.VALID}),
    )
    return Lap(**{**defaults, **overrides})


# --------------------------------------------------------------------------- #
# Sector arithmetic - the finding that `Last Sector2` is cumulative
# --------------------------------------------------------------------------- #

def test_sector_marks_are_cumulative_not_per_sector():
    """Verified against real data: in one Le Mans lap, `Current Sector`
    transitions measured sector 1 at 39.68 s and sector 2 at 95.52 s, while
    `Last Sector1` read 39.685 and `Last Sector2` read 135.207 = 39.685 + 95.52.

    Reading `Last Sector2` as a duration would overstate sector 2 by the whole
    of sector 1.
    """
    s1, s2, s3 = lap_splitter._sector_durations(39.685, 135.207, 246.100)

    assert s1 == pytest.approx(39.685)
    assert s2 == pytest.approx(95.522, abs=1e-3)
    assert s3 == pytest.approx(110.893, abs=1e-3)
    assert s1 + s2 + s3 == pytest.approx(246.100, abs=1e-3)


def test_sector_durations_treat_zero_as_not_set():
    """Zero is the game's "no time" marker, not a zero-second sector."""
    assert lap_splitter._sector_durations(0.0, 0.0, 0.0) == (None, None, None)
    assert lap_splitter._sector_durations(39.4, 0.0, 0.0) == (39.4, None, None)


def test_sector_durations_tolerate_missing_marks():
    assert lap_splitter._sector_durations(None, None, 100.0) == (None, None, None)


# --------------------------------------------------------------------------- #
# Classification
# --------------------------------------------------------------------------- #

def classify(**overrides) -> frozenset[LapFlag]:
    defaults = dict(
        official=100.0, measured=100.0, max_mismatch=0.5,
        off_track_fraction=0.0, min_off_track=0.01,
        pit_flags=frozenset(),
    )
    return lap_splitter._classify(**{**defaults, **overrides})


def test_complete_lap_is_valid():
    assert classify(official=100.0, measured=100.02) == frozenset({LapFlag.VALID})


def test_zero_official_time_means_the_game_invalidated_the_lap():
    """Track-limit rulings are the game's alone - no channel reproduces them."""
    assert LapFlag.INVALIDATED in classify(official=0.0, measured=106.9)
    assert LapFlag.VALID not in classify(official=0.0, measured=106.9)


def test_recording_shorter_than_the_lap_is_partial():
    """How the first lap of every session identifies itself: at Le Mans the
    first two crossings were 428.9 s apart for an official 263.7 s lap."""
    flags = classify(official=263.748, measured=428.868)
    assert LapFlag.PARTIAL in flags
    assert LapFlag.VALID not in flags


def test_missing_official_time_is_partial():
    """Seen in qualifying, where the out lap gets no time at all."""
    assert LapFlag.PARTIAL in classify(official=None)


def test_off_track_does_not_invalidate_a_lap():
    """Measured against real sessions these disagree, so they stay independent.

    A Monza lap with a near-stationary excursion onto grass was still rated
    valid by the game; laps with no off-track sample at all were invalidated.
    """
    flags = classify(official=118.171, measured=118.180, off_track_fraction=0.034)
    assert LapFlag.OFF_TRACK in flags
    assert LapFlag.VALID in flags


def test_small_off_track_fraction_is_not_flagged():
    """Every lap brushes a kerb on exit; only a real excursion counts."""
    assert LapFlag.OFF_TRACK not in classify(off_track_fraction=0.001)


def test_pit_flags_are_carried_through():
    flags = classify(pit_flags=frozenset({LapFlag.OUT_LAP, LapFlag.IN_PITS}))
    assert LapFlag.OUT_LAP in flags
    assert LapFlag.IN_PITS in flags


# --------------------------------------------------------------------------- #
# Pit detection
# --------------------------------------------------------------------------- #

def test_pit_exit_marks_the_out_lap():
    pits = EventSeries(
        name="In Pits",
        times=np.array([10.0, 40.0]),
        values=np.array([1.0, 0.0]),
    )
    boundaries = np.array([10.0, 150.0, 260.0])
    flags = lap_splitter._pit_flags_per_lap(pits, boundaries)

    assert LapFlag.OUT_LAP in flags[0]
    assert LapFlag.IN_PITS in flags[0]
    assert flags[1] == frozenset()


def test_pit_entry_marks_the_in_lap():
    pits = EventSeries(
        name="In Pits",
        times=np.array([0.0, 200.0]),
        values=np.array([0.0, 1.0]),
    )
    boundaries = np.array([0.0, 100.0, 250.0])
    flags = lap_splitter._pit_flags_per_lap(pits, boundaries)

    assert flags[0] == frozenset()
    assert LapFlag.IN_LAP in flags[1]


def test_initial_state_is_not_a_pit_event():
    """`In Pits` reporting 0 at the first sample is its initial state, not the
    car leaving the pits."""
    pits = EventSeries(
        name="In Pits", times=np.array([17.47]), values=np.array([0.0])
    )
    boundaries = np.array([17.47, 130.0])
    assert lap_splitter._pit_flags_per_lap(pits, boundaries)[0] == frozenset()


# --------------------------------------------------------------------------- #
# Boundary value lookup
# --------------------------------------------------------------------------- #

def test_value_at_boundary_requires_an_event_on_the_boundary():
    """A forward fill would attribute the previous lap's time to the next one.

    `Lap Time` reports a completed lap only at the crossing itself.
    """
    lap_times = EventSeries(
        name="Lap Time",
        times=np.array([26.512, 455.38]),
        values=np.array([0.0, 263.748]),
    )
    assert lap_splitter._value_at_boundary(lap_times, 455.38) == pytest.approx(263.748)
    assert lap_splitter._value_at_boundary(lap_times, 700.0) is None


def test_value_at_boundary_tolerates_rounding_between_channels():
    """The same instant is stored as 26.5125 in one channel and 26.512 in
    another, so an exact match would fail."""
    series = EventSeries(
        name="Lap Time", times=np.array([26.512]), values=np.array([5.0])
    )
    assert lap_splitter._value_at_boundary(series, 26.5125) == pytest.approx(5.0)


def test_value_at_boundary_handles_a_missing_channel():
    assert lap_splitter._value_at_boundary(None, 10.0) is None


# --------------------------------------------------------------------------- #
# Lap model
# --------------------------------------------------------------------------- #

def test_measured_time_is_available_even_when_the_game_reported_none():
    """An invalidated lap still has usable telemetry and a real duration."""
    lap = make_lap(
        t_start=100.0, t_end=206.9, official_time_s=0.0,
        flags=frozenset({LapFlag.INVALIDATED}),
    )
    assert lap.measured_time_s == pytest.approx(106.9)
    assert lap.time_s == pytest.approx(106.9)


def test_official_time_wins_when_the_game_reported_one():
    lap = make_lap(t_start=0.0, t_end=100.02, official_time_s=100.0)
    assert lap.time_s == pytest.approx(100.0)


@pytest.mark.parametrize(
    ("flags", "comparable"),
    [
        (frozenset({LapFlag.VALID}), True),
        (frozenset({LapFlag.VALID, LapFlag.OFF_TRACK}), True),
        (frozenset({LapFlag.PARTIAL}), False),
        (frozenset({LapFlag.INVALIDATED}), False),
        (frozenset({LapFlag.VALID, LapFlag.OUT_LAP}), False),
        (frozenset({LapFlag.VALID, LapFlag.IN_LAP}), False),
        (frozenset({LapFlag.VALID, LapFlag.IN_PITS}), False),
    ],
)
def test_is_comparable(flags, comparable):
    """A lap that touches the pit lane has a speed-limited section, so its time
    is meaningless against a flying lap - even though the lap itself is valid."""
    assert make_lap(flags=flags).is_comparable is comparable


def test_flag_labels_are_portuguese():
    labels = make_lap(flags=frozenset({LapFlag.VALID, LapFlag.OUT_LAP})).flag_labels()
    assert "válida" in labels
    assert "volta de saída" in labels
