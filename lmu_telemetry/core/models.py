"""Domain models shared by every layer.

Phase 1 only needs `SessionInfo`. `Lap`, `Corner` and `Stint` arrive with the
phases that produce them.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from lmu_telemetry.core.errors import SessionNameError
from lmu_telemetry.ui import strings

#: Pattern of a session file name written by the game, e.g.
#:
#:     Circuit de la Sarthe_R_2026-07-30T20_44_16Z.duckdb
#:
#: Note the track name contains **spaces**, and may contain underscores of its
#: own, so splitting on "_" from the left is wrong. The date part is rigid
#: enough to anchor the match from the right instead: the greedy `.+` for the
#: track can only end where a valid session code and timestamp follow.
#: The time uses "_" as separator because ":" is illegal in Windows file names.
_SESSION_NAME_RE = re.compile(
    r"^(?P<track>.+)"
    r"_(?P<session>[A-Za-z0-9]{1,4})"
    r"_(?P<date>\d{4}-\d{2}-\d{2})"
    r"T(?P<hour>\d{2})_(?P<minute>\d{2})_(?P<second>\d{2})Z$"
)


@dataclass(frozen=True, slots=True)
class SessionInfo:
    """Identity of one recorded session.

    Attributes:
        path: Absolute path to the source `.duckdb` file.
        track_name: Track as named by the game, taken from the file name or
            from `metadata` when available.
        session_type_code: Raw single-letter code from the file name (P/Q/R/...).
        started_at: Session start, timezone-aware UTC. The game writes UTC and
            marks it with a trailing "Z"; keeping it UTC avoids two sessions
            recorded around a DST change sorting incorrectly.
        car_name: None when neither `metadata` nor the file name reveals it.
            The importer asks the user and stores the answer in the catalog.
        file_hash: SHA-256 of the source file, used to invalidate the parquet
            cache when the source changes.
        file_size_bytes: Size of the source file.
    """

    path: Path
    track_name: str
    session_type_code: str
    started_at: datetime
    car_name: str | None = None
    file_hash: str | None = None
    file_size_bytes: int | None = None

    @property
    def session_type_label(self) -> str:
        """Portuguese label for the session type, for display."""
        return strings.session_type_label(self.session_type_code)


def parse_session_filename(path: Path | str) -> tuple[str, str, datetime]:
    """Extract track, session type and UTC start time from a session file name.

    The file name is the only identification guaranteed to be present; the
    `metadata` table is consulted first by the importer, but it does not always
    carry the track.

    Args:
        path: File path or bare file name, with or without the `.duckdb` suffix.

    Returns:
        `(track_name, session_type_code, started_at_utc)`.

    Raises:
        SessionNameError: The name does not follow the game's convention.

    >>> parse_session_filename("Circuit de la Sarthe_R_2026-07-30T20_44_16Z.duckdb")[:2]
    ('Circuit de la Sarthe', 'R')
    """
    stem = Path(path).stem
    match = _SESSION_NAME_RE.match(stem)
    if match is None:
        raise SessionNameError(strings.ERR_BAD_SESSION_NAME.format(name=stem))

    started_at = datetime(
        year=int(match["date"][0:4]),
        month=int(match["date"][5:7]),
        day=int(match["date"][8:10]),
        hour=int(match["hour"]),
        minute=int(match["minute"]),
        second=int(match["second"]),
        tzinfo=UTC,
    )
    return match["track"], match["session"].upper(), started_at


def compute_file_hash(path: Path | str, chunk_size: int = 1 << 20) -> str:
    """Return the SHA-256 of a file, read in chunks.

    Session files reach tens of megabytes, so the file is streamed rather than
    loaded. The hash is what tells the parquet cache that a source file changed
    and its derived data must be rebuilt.
    """
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def session_info_from_path(path: Path | str, *, with_hash: bool = True) -> SessionInfo:
    """Build a `SessionInfo` from the file name alone.

    Car name is left as None here: the file name never contains it. The importer
    fills it from `metadata`, or asks the user.

    Args:
        path: Path to the session file.
        with_hash: Set False to skip hashing when only the identity is needed,
            for example when listing a folder of sessions in the UI.
    """
    path = Path(path).resolve()
    track, session_code, started_at = parse_session_filename(path)
    return SessionInfo(
        path=path,
        track_name=track,
        session_type_code=session_code,
        started_at=started_at,
        car_name=None,
        file_hash=compute_file_hash(path) if with_hash else None,
        file_size_bytes=path.stat().st_size if path.is_file() else None,
    )
