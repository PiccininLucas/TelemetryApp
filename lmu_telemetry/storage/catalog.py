"""The historical catalog: everything the app knows across all sessions.

A DuckDB database of its own, at `~/.lmu-telemetry/catalog.duckdb`. It answers
the questions a single session cannot: what is my best lap ever at this track in
this car, what are this track's corners called, which sessions have I imported.

Design notes:

**Natural keys, not sequences.** A session's id is its source file's SHA-256 and
a lap's is `<session_id>:<index>`. Re-importing the same file therefore updates
its rows in place instead of creating duplicates, which makes import idempotent
without needing to check first.

**`best_laps` is a view, not a table.** The specification lists it among the
tables, but a stored best lap goes stale the moment a session is re-imported or
deleted, and a wrong "best ever" is worse than none. Computing it on demand
costs nothing at this scale and cannot disagree with the laps it summarises.

Import is manual: the user picks a file. The schema is ready for a folder watcher
to call the same `import_session` later, but no watcher is built.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator

import duckdb

from lmu_telemetry.core.models import Lap, SessionInfo
from lmu_telemetry.logging_config import get_logger
from lmu_telemetry.storage import paths

logger = get_logger(__name__)

#: Bumped when the schema changes in a way that needs migration.
SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_info (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS tracks (
    track_id     VARCHAR PRIMARY KEY,
    name         VARCHAR NOT NULL,
    length_m     DOUBLE
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id    VARCHAR PRIMARY KEY,
    source_path   VARCHAR NOT NULL,
    source_hash   VARCHAR NOT NULL,
    track_id      VARCHAR NOT NULL,
    car_name      VARCHAR,
    car_class     VARCHAR,
    session_type  VARCHAR,
    started_at    TIMESTAMP,
    weather       VARCHAR,
    n_laps        INTEGER,
    imported_at   TIMESTAMP WITH TIME ZONE
);

CREATE TABLE IF NOT EXISTS laps (
    lap_id             VARCHAR PRIMARY KEY,
    session_id         VARCHAR NOT NULL,
    lap_index          INTEGER NOT NULL,
    lap_number         INTEGER,
    t_start            DOUBLE,
    t_end              DOUBLE,
    official_time_s    DOUBLE,
    measured_time_s    DOUBLE,
    time_s             DOUBLE,
    sector1_s          DOUBLE,
    sector2_s          DOUBLE,
    sector3_s          DOUBLE,
    flags              VARCHAR,
    is_comparable      BOOLEAN,
    off_track_fraction DOUBLE
);

-- Corner names are the user's own, so they must survive re-importing every
-- session at a track. Keyed on the track, never on a session.
CREATE TABLE IF NOT EXISTS corners (
    track_id             VARCHAR NOT NULL,
    corner_index         INTEGER NOT NULL,
    name                 VARCHAR,
    reference_distance_m DOUBLE,
    PRIMARY KEY (track_id, corner_index)
);
"""

_BEST_LAPS_VIEW = """
CREATE OR REPLACE VIEW best_laps AS
SELECT
    s.track_id,
    t.name        AS track_name,
    s.car_name,
    s.car_class,
    l.lap_id,
    l.session_id,
    l.lap_number,
    l.time_s,
    l.sector1_s,
    l.sector2_s,
    l.sector3_s,
    s.started_at
FROM laps l
JOIN sessions s ON s.session_id = l.session_id
JOIN tracks   t ON t.track_id   = s.track_id
WHERE l.is_comparable AND l.time_s > 0
QUALIFY row_number() OVER (
    PARTITION BY s.track_id, s.car_name ORDER BY l.time_s
) = 1;
"""


def _to_naive_utc(moment: datetime) -> datetime:
    """Store timestamps as naive UTC.

    DuckDB's TIMESTAMP WITH TIME ZONE requires `pytz` to hand a value back to
    Python, which is a dependency bought for nothing here: every timestamp in
    this application is UTC by construction - the game writes UTC and the file
    name marks it with a trailing Z. Storing naive UTC keeps the column a real
    timestamp, so date functions and ordering still work, without the import.
    """
    if moment.tzinfo is None:
        return moment
    return moment.astimezone(UTC).replace(tzinfo=None)


def _from_naive_utc(moment: datetime | None) -> datetime | None:
    """Re-attach the timezone that `_to_naive_utc` stripped."""
    if moment is None:
        return None
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment


def track_id_for(track_name: str) -> str:
    """Stable identifier for a track name.

    Lowercased with runs of non-alphanumerics collapsed to a single dash, so
    "Autodromo Enzo e Dino Ferrari" and a future "autodromo enzo e dino ferrari"
    are one track rather than two.
    """
    import re

    slug = re.sub(r"[^a-z0-9]+", "-", track_name.strip().lower())
    return slug.strip("-") or "unknown"


def lap_id_for(session_id: str, lap_index: int) -> str:
    return f"{session_id}:{lap_index}"


@dataclass(frozen=True, slots=True)
class SessionRow:
    """One row of the sessions table, as read back."""

    session_id: str
    source_path: Path
    track_id: str
    track_name: str
    car_name: str | None
    car_class: str | None
    session_type: str | None
    started_at: datetime
    weather: str | None
    n_laps: int


@contextmanager
def connect(path: Path | str | None = None) -> Iterator[duckdb.DuckDBPyConnection]:
    """Open the catalog, creating and migrating it as needed."""
    target = Path(path) if path is not None else paths.catalog_path()
    target.parent.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(target))
    try:
        initialise(con)
        yield con
    finally:
        con.close()


def initialise(con: duckdb.DuckDBPyConnection) -> None:
    """Create the schema if absent, and record its version."""
    for statement in _SCHEMA.strip().split(";"):
        if statement.strip():
            con.execute(statement)
    con.execute(_BEST_LAPS_VIEW)

    existing = con.execute("SELECT version FROM schema_info").fetchone()
    if existing is None:
        con.execute("INSERT INTO schema_info VALUES (?)", [SCHEMA_VERSION])
    elif existing[0] != SCHEMA_VERSION:
        logger.warning(
            "Catalog schema version %s does not match %d expected by this build",
            existing[0], SCHEMA_VERSION,
        )


# --------------------------------------------------------------------------- #
# Writing
# --------------------------------------------------------------------------- #

def upsert_track(
    con: duckdb.DuckDBPyConnection,
    track_name: str,
    length_m: float | None = None,
) -> str:
    """Insert or update a track, and return its id.

    An existing length is kept when the caller has none to offer, so importing a
    session with no complete lap never erases a length measured earlier.
    """
    track_id = track_id_for(track_name)
    con.execute(
        """
        INSERT INTO tracks (track_id, name, length_m) VALUES (?, ?, ?)
        ON CONFLICT (track_id) DO UPDATE SET
            name = excluded.name,
            length_m = coalesce(excluded.length_m, tracks.length_m)
        """,
        [track_id, track_name, length_m],
    )
    return track_id


def import_session(
    con: duckdb.DuckDBPyConnection,
    session_id: str,
    info: SessionInfo,
    laps: list[Lap],
    track_length_m: float | None = None,
) -> str:
    """Record a session and its laps, replacing any earlier import of the file.

    Idempotent: importing the same file twice leaves the catalog unchanged apart
    from `imported_at`.

    Returns:
        The track id the session was filed under.
    """
    track_id = upsert_track(con, info.track_name, track_length_m)

    con.execute(
        """
        INSERT INTO sessions (
            session_id, source_path, source_hash, track_id, car_name, car_class,
            session_type, started_at, weather, n_laps, imported_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (session_id) DO UPDATE SET
            source_path = excluded.source_path,
            track_id    = excluded.track_id,
            car_name    = excluded.car_name,
            car_class   = excluded.car_class,
            weather     = excluded.weather,
            n_laps      = excluded.n_laps,
            imported_at = excluded.imported_at
        """,
        [
            session_id, str(info.path), info.file_hash or session_id, track_id,
            info.car_name, info.car_class, info.session_type_code,
            _to_naive_utc(info.started_at), info.weather, len(laps),
            _to_naive_utc(datetime.now(UTC)),
        ],
    )

    # Replace the whole lap set rather than upserting row by row: a re-import
    # after a classification change could produce a different number of laps,
    # and stale rows would silently pollute every best-lap query.
    con.execute("DELETE FROM laps WHERE session_id = ?", [session_id])
    if laps:
        con.executemany(
            """
            INSERT INTO laps (
                lap_id, session_id, lap_index, lap_number, t_start, t_end,
                official_time_s, measured_time_s, time_s,
                sector1_s, sector2_s, sector3_s,
                flags, is_comparable, off_track_fraction
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                [
                    lap_id_for(session_id, lap.index), session_id,
                    lap.index, lap.number, lap.t_start, lap.t_end,
                    lap.official_time_s, lap.measured_time_s, lap.time_s,
                    lap.sector_times_s[0], lap.sector_times_s[1],
                    lap.sector_times_s[2],
                    ",".join(sorted(f.value for f in lap.flags)),
                    lap.is_comparable, lap.off_track_fraction,
                ]
                for lap in laps
            ],
        )

    logger.info(
        "Catalogued session %s: %s / %s, %d laps",
        session_id[:12], info.track_name, info.car_name or "?", len(laps),
    )
    return track_id


def forget_session(con: duckdb.DuckDBPyConnection, session_id: str) -> bool:
    """Remove a session and its laps. Returns whether anything was removed."""
    found = con.execute(
        "SELECT 1 FROM sessions WHERE session_id = ?", [session_id]
    ).fetchone()
    if found is None:
        return False
    con.execute("DELETE FROM laps WHERE session_id = ?", [session_id])
    con.execute("DELETE FROM sessions WHERE session_id = ?", [session_id])
    return True


def set_corner_name(
    con: duckdb.DuckDBPyConnection,
    track_id: str,
    corner_index: int,
    name: str,
    reference_distance_m: float | None = None,
) -> None:
    """Name a corner. Phase 8 populates these; the table exists now so that a
    name given once survives every later re-import of every session."""
    con.execute(
        """
        INSERT INTO corners (track_id, corner_index, name, reference_distance_m)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (track_id, corner_index) DO UPDATE SET
            name = excluded.name,
            reference_distance_m =
                coalesce(excluded.reference_distance_m, corners.reference_distance_m)
        """,
        [track_id, corner_index, name, reference_distance_m],
    )


# --------------------------------------------------------------------------- #
# Reading
# --------------------------------------------------------------------------- #

def is_imported(con: duckdb.DuckDBPyConnection, session_id: str) -> bool:
    return con.execute(
        "SELECT 1 FROM sessions WHERE session_id = ?", [session_id]
    ).fetchone() is not None


def list_sessions(
    con: duckdb.DuckDBPyConnection,
    track_id: str | None = None,
) -> list[SessionRow]:
    """Every imported session, newest first."""
    query = """
        SELECT s.session_id, s.source_path, s.track_id, t.name, s.car_name,
               s.car_class, s.session_type, s.started_at, s.weather, s.n_laps
        FROM sessions s
        JOIN tracks t ON t.track_id = s.track_id
    """
    parameters: list[object] = []
    if track_id is not None:
        query += " WHERE s.track_id = ?"
        parameters.append(track_id)
    query += " ORDER BY s.started_at DESC"

    return [
        SessionRow(
            session_id=row[0], source_path=Path(row[1]), track_id=row[2],
            track_name=row[3], car_name=row[4], car_class=row[5],
            session_type=row[6], started_at=_from_naive_utc(row[7]),
            weather=row[8], n_laps=row[9],
        )
        for row in con.execute(query, parameters).fetchall()
    ]


def best_lap(
    con: duckdb.DuckDBPyConnection,
    track_name: str,
    car_name: str | None,
) -> dict[str, object] | None:
    """The fastest comparable lap ever recorded at a track in a car."""
    row = con.execute(
        """
        SELECT lap_id, session_id, lap_number, time_s,
               sector1_s, sector2_s, sector3_s, started_at
        FROM best_laps
        WHERE track_id = ? AND car_name IS NOT DISTINCT FROM ?
        """,
        [track_id_for(track_name), car_name],
    ).fetchone()
    if row is None:
        return None
    return {
        "lap_id": row[0], "session_id": row[1], "lap_number": row[2],
        "time_s": row[3], "sector1_s": row[4], "sector2_s": row[5],
        "sector3_s": row[6], "started_at": _from_naive_utc(row[7]),
    }


def list_best_laps(con: duckdb.DuckDBPyConnection) -> list[dict[str, object]]:
    """Best lap per (track, car), fastest first within each track."""
    rows = con.execute(
        """
        SELECT track_name, car_name, car_class, lap_number, time_s,
               sector1_s, sector2_s, sector3_s, started_at
        FROM best_laps
        ORDER BY track_name, time_s
        """
    ).fetchall()
    return [
        {
            "track_name": r[0], "car_name": r[1], "car_class": r[2],
            "lap_number": r[3], "time_s": r[4], "sector1_s": r[5],
            "sector2_s": r[6], "sector3_s": r[7],
            "started_at": _from_naive_utc(r[8]),
        }
        for r in rows
    ]


def track_length(con: duckdb.DuckDBPyConnection, track_name: str) -> float | None:
    row = con.execute(
        "SELECT length_m FROM tracks WHERE track_id = ?", [track_id_for(track_name)]
    ).fetchone()
    return row[0] if row else None


def corner_names(
    con: duckdb.DuckDBPyConnection, track_name: str
) -> dict[int, str]:
    rows = con.execute(
        "SELECT corner_index, name FROM corners WHERE track_id = ? ORDER BY 1",
        [track_id_for(track_name)],
    ).fetchall()
    return {row[0]: row[1] for row in rows}


def statistics(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    """Row counts, for the CLI summary."""
    def count(table: str) -> int:
        return int(con.execute(f"SELECT count(*) FROM {table}").fetchone()[0])

    return {
        "tracks": count("tracks"),
        "sessions": count("sessions"),
        "laps": count("laps"),
        "comparable_laps": int(
            con.execute("SELECT count(*) FROM laps WHERE is_comparable").fetchone()[0]
        ),
        "corners": count("corners"),
    }
