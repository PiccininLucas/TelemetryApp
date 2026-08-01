"""Domain models shared by every layer.

`Corner` and `Stint` arrive with the phases that produce them.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
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
        car_name: From `metadata.CarName`, which every file inspected carries.
            None only when the metadata is incomplete.
        car_class: From `metadata.CarClass` - "GT3", "LMP3" and so on. Laps are
            only comparable within a class, so this is part of the identity.
        weather: From `metadata.WeatherConditions`.
        file_hash: SHA-256 of the source file, used to invalidate the parquet
            cache when the source changes.
        file_size_bytes: Size of the source file.
    """

    path: Path
    track_name: str
    session_type_code: str
    started_at: datetime
    car_name: str | None = None
    car_class: str | None = None
    weather: str | None = None
    file_hash: str | None = None
    file_size_bytes: int | None = None

    @property
    def session_type_label(self) -> str:
        """Portuguese label for the session type, for display."""
        return strings.session_type_label(self.session_type_code)

    @property
    def comparison_key(self) -> tuple[str, str]:
        """What makes two sessions' laps comparable: same track, same car.

        The historical catalog's best-lap table is keyed on this.
        """
        return (self.track_name, self.car_name or "?")


class LapFlag(str, Enum):
    """What is known about a lap. A lap can carry several of these at once."""

    #: A complete, timed lap the game did not invalidate.
    VALID = "valid"

    #: The recording does not cover the whole lap. Always true of the first lap
    #: of a session and of the last, because recording starts and stops mid-lap.
    #: This is the normal case, not an exception.
    PARTIAL = "partial"

    #: The game reported a lap time of exactly zero, which is how it marks a lap
    #: it invalidated. This is the game's own verdict on track limits and is
    #: treated as authoritative - the telemetry has no channel that reproduces
    #: the ruling.
    INVALIDATED = "invalidated"

    #: The car left the pits during this lap.
    OUT_LAP = "out_lap"

    #: The car entered the pits during this lap.
    IN_LAP = "in_lap"

    #: The car was in the pit lane for part of the lap.
    IN_PITS = "in_pits"

    #: Wheels spent time on grass, dirt or gravel. Informational only: measured
    #: against real sessions this does *not* predict the game's invalidation,
    #: because track-limit rulings are about kerbs and white lines rather than
    #: about leaving the road. A lap at Monza with a near-stationary excursion
    #: onto grass stayed valid.
    OFF_TRACK = "off_track"


@dataclass(frozen=True, slots=True)
class Lap:
    """One lap of a session.

    Attributes:
        index: Position in the session's lap list, from zero.
        number: Lap number as the game counts it.
        t_start: Session-clock time of the crossing that opened this lap.
        t_end: Session-clock time of the crossing that closed it.
        official_time_s: Lap time as reported by the game, or None when it
            reported none. Zero means the game invalidated the lap.
        sector_times_s: The three sector durations, any of which may be None.
        flags: Everything known about the lap.
        off_track_fraction: Share of the lap's wheel-samples on grass, dirt or
            gravel.
    """

    index: int
    number: int
    t_start: float
    t_end: float
    official_time_s: float | None = None
    sector_times_s: tuple[float | None, float | None, float | None] = (None, None, None)
    flags: frozenset[LapFlag] = field(default_factory=frozenset)
    off_track_fraction: float = 0.0

    @property
    def measured_time_s(self) -> float:
        """Duration actually covered by the recording, from the two crossings.

        For a complete lap this agrees with `official_time_s` to within about
        0.02 s. It is the only time available for a lap the game invalidated,
        since those are reported as zero.
        """
        return self.t_end - self.t_start

    @property
    def time_s(self) -> float:
        """The lap time to display: the official one when the game gave a real
        one, the measured span otherwise."""
        if self.official_time_s:  # rejects both None and 0.0
            return self.official_time_s
        return self.measured_time_s

    @property
    def is_partial(self) -> bool:
        return LapFlag.PARTIAL in self.flags

    @property
    def is_invalidated(self) -> bool:
        return LapFlag.INVALIDATED in self.flags

    @property
    def is_valid(self) -> bool:
        return LapFlag.VALID in self.flags

    @property
    def is_comparable(self) -> bool:
        """True when this lap may be used for lap-to-lap comparison.

        Excludes partial laps, laps the game invalidated, and in/out laps: a lap
        that starts or ends in the pit lane has a pit-limited section that makes
        its time meaningless against a flying lap.
        """
        excluded = {
            LapFlag.PARTIAL, LapFlag.INVALIDATED,
            LapFlag.OUT_LAP, LapFlag.IN_LAP, LapFlag.IN_PITS,
        }
        return self.is_valid and not (self.flags & excluded)

    def flag_labels(self) -> list[str]:
        """Portuguese labels for this lap's flags, for display."""
        return [strings.LAP_FLAG_LABEL[flag.value] for flag in sorted(self.flags)]


@dataclass(frozen=True, slots=True)
class Corner:
    """One corner of a lap, measured in the distance domain.

    Every distance is metres from the start/finish line, so a corner found on
    one lap can be matched to the same corner on another by distance.

    Attributes:
        index: Position around the lap, from zero.
        apex_distance_m: Where the speed minimum falls.
        minimum_speed_ms: Speed at the apex.
        entry_speed_ms: Speed at the braking point.
        braking_distance_m: Where sustained braking begins, or None when the
            corner is taken without braking.
        throttle_distance_m: Where sustained throttle resumes after the apex.
        coasting_time_s: Time with neither pedal applied inside the corner
            window - the cost of an unresolved decision between brake and
            throttle.
        trail_braking_m: Distance over which braking continues past the turn-in
            point while speed is still falling.
        start_distance_m: Window start, used to bound per-corner statistics.
        end_distance_m: Window end.
        name: The user's name for it, filled from the catalog.
    """

    index: int
    apex_distance_m: float
    minimum_speed_ms: float
    entry_speed_ms: float | None = None
    braking_distance_m: float | None = None
    throttle_distance_m: float | None = None
    coasting_time_s: float = 0.0
    trail_braking_m: float = 0.0
    start_distance_m: float = 0.0
    end_distance_m: float = 0.0
    name: str | None = None

    @property
    def label(self) -> str:
        """The name to show: the user's if given, otherwise a number."""
        return self.name or f"C{self.index + 1}"

    @property
    def braking_length_m(self) -> float | None:
        """Distance from the braking point to the apex."""
        if self.braking_distance_m is None:
            return None
        return self.apex_distance_m - self.braking_distance_m


@dataclass(frozen=True, slots=True)
class Stint:
    """A run of consecutive laps between two visits to the pits.

    Attributes:
        index: Position in the session, from zero.
        lap_indices: Indices into the session's lap list, in order.
        started_at_s: Session-clock time the stint began.
        ended_at_s: Session-clock time it ended.
    """

    index: int
    lap_indices: tuple[int, ...]
    started_at_s: float
    ended_at_s: float

    def __len__(self) -> int:
        return len(self.lap_indices)


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
