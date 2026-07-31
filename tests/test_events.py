"""Tests for event channels and their step semantics."""

from __future__ import annotations

import numpy as np
import pytest

from lmu_telemetry.core.errors import ChannelNotFoundError
from lmu_telemetry.ingest import channel_registry, duckdb_reader, events
from lmu_telemetry.ingest.events import EventSeries


def make_series(times, values, name="Test"):
    return EventSeries(
        name=name,
        times=np.asarray(times, dtype=np.float64),
        values=np.asarray(values, dtype=np.float64),
    )


# --------------------------------------------------------------------------- #
# Step semantics
# --------------------------------------------------------------------------- #

def test_value_at_holds_until_the_next_event():
    """An event's value stands until something replaces it - that is what the
    recording means, and why interpolation would be wrong."""
    gears = make_series([0.0, 1.0, 2.0], [3, 4, 5])

    assert gears.value_at(0.0)[0] == 3
    assert gears.value_at(0.999)[0] == 3
    assert gears.value_at(1.0)[0] == 4
    assert gears.value_at(100.0)[0] == 5


def test_value_at_never_invents_an_intermediate_value():
    gears = make_series([0.0, 1.0], [3, 4])
    sampled = gears.value_at(np.linspace(0.0, 1.0, 50))
    assert set(np.unique(sampled)) <= {3.0, 4.0}


def test_value_at_before_the_first_event_is_nan():
    series = make_series([10.0, 11.0], [1, 2])
    assert np.isnan(series.value_at(9.0)[0])


def test_per_wheel_event_keeps_four_columns():
    compounds = make_series([0.0, 5.0], [[1, 1, 1, 1], [2, 2, 3, 3]])
    result = compounds.value_at(np.array([1.0, 6.0]))

    assert result.shape == (2, 4)
    assert result[0].tolist() == [1, 1, 1, 1]
    assert result[1].tolist() == [2, 2, 3, 3]


# --------------------------------------------------------------------------- #
# Constant channels
# --------------------------------------------------------------------------- #

def test_is_constant_detects_a_channel_that_never_changed():
    """`In Pits` is constant in every race the driver finished without pitting.

    Stint detection has to fall back to one stint instead of returning nothing,
    so it needs to be able to tell this case apart from a real sequence.
    """
    assert make_series([0.0], [0]).is_constant is True
    assert make_series([0.0, 5.0], [0, 0]).is_constant is True
    assert make_series([0.0, 5.0], [0, 1]).is_constant is False


def test_empty_series_is_constant_and_empty():
    empty = make_series([], [])
    assert empty.is_empty is True
    assert empty.is_constant is True
    assert len(empty) == 0


# --------------------------------------------------------------------------- #
# Transitions
# --------------------------------------------------------------------------- #

def test_transitions_finds_only_genuine_changes():
    """0 -> 1 is a pit entry, 1 -> 0 an exit. A repeat of the same value is
    neither."""
    pits = make_series([0.0, 10.0, 20.0, 30.0, 40.0], [0, 1, 1, 0, 1])

    assert pits.transitions(1.0).tolist() == [10.0, 40.0]
    assert pits.transitions(0.0).tolist() == [0.0, 30.0]


def test_transitions_counts_an_initial_matching_value():
    """A session that begins in the pit lane starts already at 1."""
    assert make_series([5.0, 9.0], [1, 0]).transitions(1.0).tolist() == [5.0]


def test_transitions_on_a_constant_channel():
    constant = make_series([0.0, 1.0], [0, 0])
    assert constant.transitions(1.0).size == 0
    assert constant.transitions(0.0).tolist() == [0.0]


# --------------------------------------------------------------------------- #
# Reading from a file
# --------------------------------------------------------------------------- #

def test_read_event_series(synthetic_session):
    con = duckdb_reader.open_session(synthetic_session)
    try:
        registry = channel_registry.build_registry(con)
        gears = events.read_event_series(con, registry, "Gear")

        assert gears.times.tolist() == pytest.approx([0.0, 0.3, 0.7])
        assert gears.values.tolist() == [1, 2, 3]
        assert gears.times.dtype == np.float64
    finally:
        con.close()


def test_read_per_wheel_event_series(synthetic_session):
    con = duckdb_reader.open_session(synthetic_session)
    try:
        registry = channel_registry.build_registry(con)
        compounds = events.read_event_series(con, registry, "TyresCompound")

        assert compounds.values.shape == (1, 4)
        assert compounds.times.tolist() == [0.0]
    finally:
        con.close()


def test_reading_a_continuous_channel_as_an_event_is_rejected(synthetic_session):
    con = duckdb_reader.open_session(synthetic_session)
    try:
        registry = channel_registry.build_registry(con)
        with pytest.raises(ChannelNotFoundError):
            events.read_event_series(con, registry, "Ground Speed")
    finally:
        con.close()


def test_try_read_returns_none_for_a_missing_channel(synthetic_session):
    con = duckdb_reader.open_session(synthetic_session)
    try:
        registry = channel_registry.build_registry(con)
        assert events.try_read_event_series(con, registry, "Not A Channel") is None
    finally:
        con.close()


def test_events_are_sorted_by_time(tmp_path):
    """Unlike continuous channels, event tables have a time column, and nothing
    guarantees the file wrote them in order."""
    import duckdb

    path = tmp_path / "Unsorted_R_2026-01-01T00_00_00Z.duckdb"
    con = duckdb.connect(str(path))
    con.execute(
        "CREATE TABLE channelsList "
        "(channelName VARCHAR, frequency INTEGER, unit VARCHAR)"
    )
    con.execute("CREATE TABLE eventsList (eventName VARCHAR, unit VARCHAR)")
    con.execute("INSERT INTO eventsList VALUES ('Gear', '')")
    con.execute("CREATE TABLE metadata (key VARCHAR, value VARCHAR)")
    con.execute("CREATE TABLE Gear (ts DOUBLE, value TINYINT)")
    con.execute("INSERT INTO Gear VALUES (5.0, 3), (1.0, 1), (3.0, 2)")
    con.close()

    con = duckdb_reader.open_session(path)
    try:
        registry = channel_registry.build_registry(con)
        gears = events.read_event_series(con, registry, "Gear")

        assert gears.times.tolist() == [1.0, 3.0, 5.0]
        assert gears.values.tolist() == [1, 2, 3]
    finally:
        con.close()


# --------------------------------------------------------------------------- #
# Against a real file
# --------------------------------------------------------------------------- #

def test_real_event_timestamps_share_the_gps_clock(real_session_con):
    """Event `ts` and `GPS Time` have the same origin, so no offset is applied
    anywhere in the pipeline. If that ever stopped being true, every lap
    boundary would land in the wrong place."""
    from lmu_telemetry.ingest import time_base

    registry = channel_registry.build_registry(real_session_con)
    base = time_base.build_time_base(real_session_con, registry)

    checked = 0
    for name in ("Lap", "Gear", "In Pits", "Current Sector"):
        series = events.try_read_event_series(real_session_con, registry, name)
        if series is None or series.is_empty:
            continue
        checked += 1
        assert series.times[0] >= base.t0 - 1e-3, f"{name} starts before the clock"
        assert series.times[-1] <= base.t_end + 1e-3, f"{name} ends after the clock"

    assert checked, "expected at least one event channel in a real session"
