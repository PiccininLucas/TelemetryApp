"""Importing a session: read it once, cache the metadata, record it in the catalog.

This is the seam between reading files and remembering things. `ingest` knows
how to read a session; `catalog` and `cache` know how to keep it; this module is
the only place that knows about both.

Import is manual, as the specification requires for the MVP: the user picks a
file. `import_folder` exists for convenience, not as a watcher - nothing here
runs by itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import duckdb
import numpy as np

from lmu_telemetry.core.errors import TelemetryError
from lmu_telemetry.core.models import Lap, compute_file_hash
from lmu_telemetry.ingest.session_loader import Session, load_session
from lmu_telemetry.logging_config import get_logger
from lmu_telemetry.storage import cache, catalog
from lmu_telemetry.storage.cache import CachedSession

logger = get_logger(__name__)

LAP_DISTANCE_CHANNEL = "Lap Dist"


@dataclass(frozen=True, slots=True)
class ImportResult:
    """What an import did."""

    session_id: str
    path: Path
    n_laps: int
    track_name: str
    car_name: str | None
    track_length_m: float | None
    was_cached: bool
    warnings: list[str]

    @property
    def action(self) -> str:
        return "reused cache" if self.was_cached else "imported"


def session_id_for(path: Path | str) -> str:
    """The session's identity: the SHA-256 of its source file.

    Content-addressed rather than path-addressed, so moving or copying a file
    does not create a second session, and editing one in place does not quietly
    reuse the earlier session's derived data.
    """
    return compute_file_hash(path)


def compute_track_length(session: Session) -> float | None:
    """Measure the track's length from `Lap Dist`, in metres.

    `Lap Dist` climbs to the lap length and resets to zero at each start/finish
    crossing, so the maximum reached within a complete lap is the track length
    less one sample of travel.

    The median across complete laps is used rather than the overall maximum: a
    single lap where the car rejoined past the line, or an off-track excursion
    that ran long, would otherwise set the length permanently wrong.

    Returns:
        Length in metres, or None when no complete lap was recorded.
    """
    if not session.has(LAP_DISTANCE_CHANNEL):
        logger.info("No 'Lap Dist' channel; track length unknown")
        return None

    laps = [lap for lap in session.laps if lap.is_comparable]
    if not laps:
        return None

    distance = session.channel(LAP_DISTANCE_CHANNEL)
    times = session.channel_times(LAP_DISTANCE_CHANNEL)

    per_lap = []
    for lap in laps:
        window = (times >= lap.t_start) & (times < lap.t_end)
        if window.any():
            per_lap.append(float(np.nanmax(distance[window])))

    if not per_lap:
        return None
    return float(np.median(per_lap))


def import_session_file(
    path: Path | str,
    *,
    force: bool = False,
    catalog_path: Path | None = None,
    con: duckdb.DuckDBPyConnection | None = None,
) -> ImportResult:
    """Import one session file into the cache and the catalog.

    Reuses the cached manifest when the source file is unchanged, which is what
    makes re-running an import over a folder cheap.

    Args:
        path: The `.duckdb` session file.
        force: Re-read the source even when a valid cache exists.
        catalog_path: Override the catalog location, for tests.
        con: An already-open catalog connection. Importing a folder passes one
            in so the catalog is opened once rather than once per file.

    Raises:
        TelemetryError: The file could not be read.
    """
    path = Path(path).resolve()
    session_id = session_id_for(path)

    cached = None if force else cache.read_manifest(session_id, expected_hash=session_id)

    if cached is not None:
        _record(session_id, cached.info, cached.laps, None, catalog_path, con)
        return ImportResult(
            session_id=session_id,
            path=path,
            n_laps=len(cached.laps),
            track_name=cached.info.track_name,
            car_name=cached.info.car_name,
            # The cache does not store the track length; the catalog already
            # holds the value measured when this session was first read.
            track_length_m=None,
            was_cached=True,
            warnings=cached.warnings,
        )

    with load_session(path, with_hash=True) as session:
        track_length_m = compute_track_length(session)
        cache.write_manifest(
            session_id=session_id,
            info=session.info,
            time_base=session.time_base,
            registry=session.registry,
            laps=session.laps,
            warnings=session.warnings,
        )
        _record(
            session_id, session.info, session.laps, track_length_m,
            catalog_path, con,
        )

        return ImportResult(
            session_id=session_id,
            path=path,
            n_laps=len(session.laps),
            track_name=session.info.track_name,
            car_name=session.info.car_name,
            track_length_m=track_length_m,
            was_cached=False,
            warnings=session.warnings,
        )


def _record(
    session_id: str,
    info,
    laps: list[Lap],
    track_length_m: float | None,
    catalog_path: Path | None,
    con: duckdb.DuckDBPyConnection | None,
) -> None:
    if con is not None:
        catalog.import_session(con, session_id, info, laps, track_length_m)
        return
    with catalog.connect(catalog_path) as owned:
        catalog.import_session(owned, session_id, info, laps, track_length_m)


def import_folder(
    folder: Path | str,
    *,
    force: bool = False,
    catalog_path: Path | None = None,
) -> tuple[list[ImportResult], list[tuple[Path, str]]]:
    """Import every session file in a folder.

    The catalog is opened once for the whole run: opening it per file dominated
    the cost of a re-import, where every session is already cached and there is
    nothing else to do.

    Returns:
        `(results, failures)`, where each failure is `(path, message)`. One
        unreadable file never aborts the rest - a corrupt session in a folder of
        sixty is not a reason to import none of them.
    """
    folder = Path(folder)
    results: list[ImportResult] = []
    failures: list[tuple[Path, str]] = []

    with catalog.connect(catalog_path) as con:
        for path in sorted(folder.glob("*.duckdb")):
            try:
                results.append(import_session_file(path, force=force, con=con))
            except TelemetryError as exc:
                logger.error("Could not import %s: %s", path.name, exc)
                failures.append((path, str(exc)))

    return results, failures


def load_cached(path: Path | str) -> CachedSession | None:
    """Read a session's metadata from the cache without opening the source.

    What makes a session browser instant: the manifest costs a few milliseconds
    where `load_session` costs 83 ms per file.
    """
    return cache.read_manifest(session_id_for(path))
