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

from lmu_telemetry.shared.errors import TelemetryError
from lmu_telemetry.domain.models import Lap, compute_file_hash
from lmu_telemetry.infrastructure.ingest.session_loader import Session, load_session
from lmu_telemetry.shared.logging_config import get_logger
from lmu_telemetry.infrastructure.storage import cache, catalog
from lmu_telemetry.infrastructure.storage.cache import CachedSession

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


def _lap_length_at_crossing(
    distance: np.ndarray, times: np.ndarray, lap: Lap
) -> float | None:
    """What `Lap Dist` would read at the instant the lap closed.

    `Lap Dist` is sampled at 10 Hz and resets at the line, so its last sample in
    a lap falls short of the length by however far the car travelled between
    that sample and the crossing: up to a tenth of a second, about 7 m at
    250 km/h, and different on every lap. The crossing time is known exactly
    (it is the lap's `t_end`), so the last two samples give the local rate and
    carry the distance across the gap. On the demo session the raw last samples
    spread over 5.5 m between laps and the extrapolated values over 0.8 m.

    Returns:
        The length, or None when the lap has fewer than two samples or the gap
        is not a plausible fraction of a sample (a recording that ended early).
    """
    window = np.flatnonzero((times >= lap.t_start) & (times < lap.t_end))
    if window.size < 2:
        return None

    last, previous = window[-1], window[-2]
    step = float(times[last] - times[previous])
    gap = float(lap.t_end - times[last])
    if step <= 0.0 or not 0.0 <= gap <= 2.0 * step:
        return float(np.nanmax(distance[window]))

    rate = float(distance[last] - distance[previous]) / step
    if not np.isfinite(rate) or rate < 0.0:
        return float(np.nanmax(distance[window]))
    return float(distance[last]) + rate * gap


def compute_track_length(session: Session) -> float | None:
    """Measure the track's length from `Lap Dist`, in metres.

    `Lap Dist` climbs to the lap length and resets to zero at each start/finish
    crossing. Its last sample in a lap is short of the length by the distance
    travelled between that sample and the line, which is added back; see
    `_lap_length_at_crossing`.

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
        length = _lap_length_at_crossing(distance, times, lap)
        if length is not None:
            per_lap.append(length)

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

    if cached is not None and _lacks_track_length(cached, catalog_path, con):
        # The cache survived but the catalog did not (deleted, or a new one):
        # the track length is not in the manifest, so the only place left to
        # get it is the source file.
        logger.info("Catalog has no length for %s; re-reading the session",
                    cached.info.track_name)
        cached = None

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


def _lacks_track_length(
    cached: CachedSession,
    catalog_path: Path | None,
    con: duckdb.DuckDBPyConnection | None,
) -> bool:
    """True when a cache hit would leave the catalog without a track length.

    Only worth re-reading when there is a length to find: a session with no
    comparable lap never had one.
    """
    if not any(lap.is_comparable for lap in cached.laps):
        return False
    if con is not None:
        return catalog.track_length(con, cached.info.track_name) is None
    with catalog.connect(catalog_path) as owned:
        return catalog.track_length(owned, cached.info.track_name) is None


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
