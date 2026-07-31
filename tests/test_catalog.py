"""Tests for the historical catalog."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from lmu_telemetry.core.models import Lap, LapFlag, SessionInfo
from lmu_telemetry.storage import catalog, paths


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv(paths.ENV_DATA_DIR, str(tmp_path / "data"))


@pytest.fixture
def con():
    with catalog.connect() as connection:
        yield connection


def make_info(track="Autodromo Nazionale Monza", car="DKR Engineering #4:ELMS25",
              session_id="a" * 64, when=None, **overrides) -> SessionInfo:
    defaults = dict(
        path=Path(f"D:/Telemetry/{track}_R.duckdb"),
        track_name=track,
        session_type_code="R",
        started_at=when or datetime(2026, 7, 30, 17, 12, 31, tzinfo=UTC),
        car_name=car,
        car_class="LMP3",
        weather="Clear",
        file_hash=session_id,
        file_size_bytes=1000,
    )
    return SessionInfo(**{**defaults, **overrides})


def lap(index: int, time_s: float | None, comparable: bool = True) -> Lap:
    flags = frozenset({LapFlag.VALID}) if comparable else frozenset({LapFlag.PARTIAL})
    return Lap(
        index=index, number=index, t_start=index * 110.0,
        t_end=(index + 1) * 110.0,
        official_time_s=time_s,
        sector_times_s=(35.0, 36.0, 37.0) if time_s else (None, None, None),
        flags=flags,
    )


# --------------------------------------------------------------------------- #
# Identifiers
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Autodromo Nazionale Monza", "autodromo-nazionale-monza"),
        ("autodromo nazionale monza", "autodromo-nazionale-monza"),
        ("Circuit de Spa-Francorchamps", "circuit-de-spa-francorchamps"),
        ("Paul Ricard - ELMS", "paul-ricard-elms"),
        ("  Fuji Speedway  ", "fuji-speedway"),
        ("!!!", "unknown"),
    ],
)
def test_track_id_is_stable_across_spellings(name, expected):
    """Two spellings of one track must not become two tracks in the history."""
    assert catalog.track_id_for(name) == expected


# --------------------------------------------------------------------------- #
# Import
# --------------------------------------------------------------------------- #

def test_import_records_session_and_laps(con):
    catalog.import_session(
        con, "a" * 64, make_info(), [lap(0, 110.4), lap(1, 108.5)], 5793.0
    )

    sessions = catalog.list_sessions(con)
    assert len(sessions) == 1
    assert sessions[0].track_name == "Autodromo Nazionale Monza"
    assert sessions[0].n_laps == 2
    assert catalog.track_length(con, "Autodromo Nazionale Monza") == pytest.approx(5793.0)


def test_import_is_idempotent(con):
    """Re-importing the same file must not duplicate anything: the session id is
    the file's hash, so the rows are replaced in place."""
    laps = [lap(0, 110.4), lap(1, 108.5)]
    catalog.import_session(con, "a" * 64, make_info(), laps, 5793.0)
    catalog.import_session(con, "a" * 64, make_info(), laps, 5793.0)

    stats = catalog.statistics(con)
    assert stats["sessions"] == 1
    assert stats["laps"] == 2


def test_reimport_replaces_stale_laps(con):
    """A re-import after a classification change can yield a different lap count.
    Leftover rows would silently pollute every best-lap query."""
    catalog.import_session(
        con, "a" * 64, make_info(), [lap(0, 110.4), lap(1, 90.0)], 5793.0
    )
    catalog.import_session(con, "a" * 64, make_info(), [lap(0, 110.4)], 5793.0)

    assert catalog.statistics(con)["laps"] == 1
    assert catalog.best_lap(
        con, "Autodromo Nazionale Monza", "DKR Engineering #4:ELMS25"
    )["time_s"] == pytest.approx(110.4)


def test_track_length_is_kept_when_a_later_import_has_none(con):
    """A session with no complete lap must not erase a length measured earlier."""
    catalog.import_session(con, "a" * 64, make_info(), [lap(0, 110.4)], 5793.0)
    catalog.import_session(con, "b" * 64, make_info(session_id="b" * 64), [], None)

    assert catalog.track_length(con, "Autodromo Nazionale Monza") == pytest.approx(5793.0)


def test_started_at_survives_as_utc(con):
    """DuckDB's TIMESTAMPTZ needs pytz to reach Python, so timestamps are stored
    naive and the zone is re-attached on read."""
    when = datetime(2026, 7, 30, 17, 12, 31, tzinfo=UTC)
    catalog.import_session(con, "a" * 64, make_info(when=when), [lap(0, 110.4)])

    restored = catalog.list_sessions(con)[0].started_at
    assert restored == when
    assert restored.tzinfo is not None
    assert restored.utcoffset().total_seconds() == 0


def test_forget_session(con):
    catalog.import_session(con, "a" * 64, make_info(), [lap(0, 110.4)])
    assert catalog.forget_session(con, "a" * 64) is True
    assert catalog.statistics(con)["sessions"] == 0
    assert catalog.statistics(con)["laps"] == 0
    assert catalog.forget_session(con, "a" * 64) is False


# --------------------------------------------------------------------------- #
# Best laps
# --------------------------------------------------------------------------- #

def test_best_lap_picks_the_fastest_comparable_lap(con):
    catalog.import_session(
        con, "a" * 64, make_info(),
        [lap(0, 110.4), lap(1, 107.0), lap(2, 108.5)],
    )
    best = catalog.best_lap(
        con, "Autodromo Nazionale Monza", "DKR Engineering #4:ELMS25"
    )
    assert best["time_s"] == pytest.approx(107.0)
    assert best["lap_number"] == 1


def test_best_lap_ignores_laps_that_are_not_comparable(con):
    """A partial or pit-limited lap has a meaningless time."""
    catalog.import_session(
        con, "a" * 64, make_info(),
        [lap(0, 90.0, comparable=False), lap(1, 108.5)],
    )
    best = catalog.best_lap(
        con, "Autodromo Nazionale Monza", "DKR Engineering #4:ELMS25"
    )
    assert best["time_s"] == pytest.approx(108.5)


def test_best_lap_spans_sessions(con):
    """The reason the catalog exists: a personal best is not a session's best."""
    catalog.import_session(con, "a" * 64, make_info(), [lap(0, 110.0)])
    catalog.import_session(
        con, "b" * 64, make_info(session_id="b" * 64), [lap(0, 106.2)]
    )

    best = catalog.best_lap(
        con, "Autodromo Nazionale Monza", "DKR Engineering #4:ELMS25"
    )
    assert best["time_s"] == pytest.approx(106.2)
    assert best["session_id"] == "b" * 64


def test_best_laps_are_separated_by_car(con):
    """Laps are only comparable within one car."""
    catalog.import_session(con, "a" * 64, make_info(car="LMP3 car"), [lap(0, 107.0)])
    catalog.import_session(
        con, "b" * 64, make_info(car="GT3 car", session_id="b" * 64), [lap(0, 118.0)]
    )

    assert catalog.best_lap(con, "Autodromo Nazionale Monza", "LMP3 car")["time_s"] \
        == pytest.approx(107.0)
    assert catalog.best_lap(con, "Autodromo Nazionale Monza", "GT3 car")["time_s"] \
        == pytest.approx(118.0)
    assert len(catalog.list_best_laps(con)) == 2


def test_best_lap_is_a_view_and_never_goes_stale(con):
    """Stored as a table it would survive a deletion it should not have."""
    catalog.import_session(con, "a" * 64, make_info(), [lap(0, 100.0)])
    catalog.import_session(
        con, "b" * 64, make_info(session_id="b" * 64), [lap(0, 120.0)]
    )
    assert catalog.best_lap(
        con, "Autodromo Nazionale Monza", "DKR Engineering #4:ELMS25"
    )["time_s"] == pytest.approx(100.0)

    catalog.forget_session(con, "a" * 64)
    assert catalog.best_lap(
        con, "Autodromo Nazionale Monza", "DKR Engineering #4:ELMS25"
    )["time_s"] == pytest.approx(120.0)


def test_best_lap_of_an_unknown_track_is_none(con):
    assert catalog.best_lap(con, "Nowhere", "Nothing") is None


def test_invalidated_lap_is_never_the_best(con):
    """The game reports an invalidated lap as time zero."""
    catalog.import_session(
        con, "a" * 64, make_info(),
        [Lap(index=0, number=0, t_start=0.0, t_end=106.9, official_time_s=0.0,
             flags=frozenset({LapFlag.INVALIDATED})),
         lap(1, 110.0)],
    )
    assert catalog.best_lap(
        con, "Autodromo Nazionale Monza", "DKR Engineering #4:ELMS25"
    )["time_s"] == pytest.approx(110.0)


# --------------------------------------------------------------------------- #
# Corners
# --------------------------------------------------------------------------- #

def test_corner_names_survive_reimporting_every_session(con):
    """Corner names are the user's own work and are keyed on the track, never on
    a session, so re-importing must never lose them."""
    track_id = catalog.upsert_track(con, "Autodromo Nazionale Monza", 5793.0)
    catalog.set_corner_name(con, track_id, 1, "Variante del Rettifilo", 600.0)
    catalog.set_corner_name(con, track_id, 4, "Lesmo 1", 2400.0)

    catalog.import_session(con, "a" * 64, make_info(), [lap(0, 110.0)], 5793.0)

    names = catalog.corner_names(con, "Autodromo Nazionale Monza")
    assert names == {1: "Variante del Rettifilo", 4: "Lesmo 1"}


def test_renaming_a_corner_keeps_its_reference_distance(con):
    track_id = catalog.upsert_track(con, "Fuji Speedway")
    catalog.set_corner_name(con, track_id, 1, "Turn 1", 900.0)
    catalog.set_corner_name(con, track_id, 1, "Primeira")

    row = con.execute(
        "SELECT name, reference_distance_m FROM corners WHERE corner_index = 1"
    ).fetchone()
    assert row[0] == "Primeira"
    assert row[1] == pytest.approx(900.0)


# --------------------------------------------------------------------------- #
# Persistence
# --------------------------------------------------------------------------- #

def test_catalog_persists_across_connections():
    with catalog.connect() as first:
        catalog.import_session(first, "a" * 64, make_info(), [lap(0, 110.4)], 5793.0)

    with catalog.connect() as second:
        assert catalog.statistics(second)["sessions"] == 1
        assert catalog.is_imported(second, "a" * 64)


def test_initialise_is_safe_to_run_twice():
    with catalog.connect() as con:
        catalog.initialise(con)
        assert con.execute("SELECT count(*) FROM schema_info").fetchone()[0] == 1


def test_list_sessions_filters_by_track(con):
    catalog.import_session(con, "a" * 64, make_info(track="Fuji Speedway"), [])
    catalog.import_session(
        con, "b" * 64,
        make_info(track="Autodromo Nazionale Monza", session_id="b" * 64), [],
    )

    fuji = catalog.list_sessions(con, track_id=catalog.track_id_for("Fuji Speedway"))
    assert len(fuji) == 1
    assert fuji[0].track_name == "Fuji Speedway"
    assert len(catalog.list_sessions(con)) == 2
