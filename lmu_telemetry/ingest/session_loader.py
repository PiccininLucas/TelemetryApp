"""Load a session file into a `Session`: the single entry point to ingestion.

Everything above this module - analysis, UI, export - works with `Session` and
never touches DuckDB.

`Session` lives here rather than in `core/models.py` because it aggregates a
`TimeBase` and the channel registry, both of which are ingestion artifacts.
`core` must not depend on `ingest`, and the layering rule wins over tidiness:
`core/models.py` keeps the pure value objects (`SessionInfo`, `Lap`), and the
aggregate that binds them to a data source lives with the data source.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType

import duckdb
import numpy as np

from lmu_telemetry.core import units
from lmu_telemetry.core.config import Config, load_config
from lmu_telemetry.core.errors import ChannelNotFoundError, SessionNameError
from lmu_telemetry.core.models import Lap, SessionInfo, compute_file_hash, parse_session_filename
from lmu_telemetry.ingest import (
    channel_registry, corrections, duckdb_reader, lap_splitter, time_base,
)
from lmu_telemetry.ingest.channel_registry import ChannelInfo
from lmu_telemetry.ingest.time_base import TimeBase
from lmu_telemetry.logging_config import get_logger
from lmu_telemetry.ui import strings

logger = get_logger(__name__)

#: metadata keys the game writes. Confirmed present in every file inspected.
META_TRACK = "TrackName"
META_TRACK_LAYOUT = "TrackLayout"
META_CAR = "CarName"
META_CAR_CLASS = "CarClass"
META_SESSION_TYPE = "SessionType"
META_WEATHER = "WeatherConditions"


@dataclass(slots=True)
class Session:
    """One loaded session: identity, clock, channels and laps.

    Holds an open read-only connection, so it is a context manager:

        with load_session(path) as session:
            ...
    """

    info: SessionInfo
    time_base: TimeBase
    registry: dict[str, ChannelInfo]
    laps: list[Lap]
    metadata: dict[str, str]
    connection: duckdb.DuckDBPyConnection
    warnings: list[str] = field(default_factory=list)

    def __enter__(self) -> Session:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self.connection.close()

    # -- channels ----------------------------------------------------------

    def has(self, *names: str) -> bool:
        """True when every named channel is recorded in this session."""
        return all(name in self.registry for name in names)

    def missing(self, *names: str) -> list[str]:
        """Which of the named channels are absent."""
        return channel_registry.require(self.registry, list(names))

    def channel(self, name: str, *, convert: bool = True) -> np.ndarray:
        """Read a channel, converted to canonical units by default.

        Args:
            name: Channel name.
            convert: Convert using the unit the file declares. Set False to get
                the raw stored values, which the schema report needs.

        Raises:
            ChannelNotFoundError: The channel is not recorded here.
        """
        info = self.registry.get(name)
        if info is None:
            raise ChannelNotFoundError(name)

        values = channel_registry.read_channel(self.connection, self.registry, name)
        if not convert:
            return values

        converted, _canonical = units.convert(values, info.unit, channel=name)
        return converted

    def channel_times(self, name: str) -> np.ndarray:
        """Sample times of a continuous channel, on the session clock."""
        info = self.registry.get(name)
        if info is None:
            raise ChannelNotFoundError(name)
        return time_base.sample_times(info.n_samples, self.time_base)

    def acceleration(self, quantity: str) -> np.ndarray:
        """Read an acceleration component in g, correctly labelled.

        The file swaps its lateral and longitudinal channels and negates both;
        see `ingest/corrections.py` for the evidence. Use this rather than
        `channel("G Force Lat")`, which returns the raw - and mislabelled -
        values.

        Args:
            quantity: "longitudinal", "lateral" or "vertical".

        Returns:
            Acceleration in g. Longitudinal is positive under acceleration,
            lateral is positive in a right-hand corner.
        """
        raw_name = corrections.source_channel(quantity)
        return corrections.corrected_acceleration(
            self.channel(raw_name, convert=True), quantity
        )

    def acceleration_times(self, quantity: str) -> np.ndarray:
        """Sample times of an acceleration component."""
        return self.channel_times(corrections.source_channel(quantity))

    def try_channel(self, name: str) -> np.ndarray | None:
        """Read a channel, or return None when it is absent.

        For features that disable themselves rather than failing the session.
        """
        try:
            return self.channel(name)
        except ChannelNotFoundError:
            logger.info("Channel %r not available in this session", name)
            return None

    # -- laps --------------------------------------------------------------

    @property
    def comparable_laps(self) -> list[Lap]:
        """Laps usable for lap-to-lap comparison."""
        return [lap for lap in self.laps if lap.is_comparable]

    @property
    def best_lap(self) -> Lap | None:
        """Fastest comparable lap, or None when there is none."""
        candidates = self.comparable_laps
        return min(candidates, key=lambda lap: lap.time_s) if candidates else None

    def lap_at(self, t: float) -> Lap | None:
        """The lap containing session-clock time `t`."""
        for lap in self.laps:
            if lap.t_start <= t < lap.t_end:
                return lap
        return None


def load_session(
    path: Path | str,
    config: Config | None = None,
    *,
    with_hash: bool = True,
) -> Session:
    """Open a session file and build everything phase 2 provides.

    Order matters: the registry needs the catalog, the time base needs the
    registry, and lap splitting needs the time base to place `SurfaceTypes`
    samples in time.

    Args:
        path: Path to a `.duckdb` session file.
        config: Configuration override, mainly for tests.
        with_hash: Compute the file's SHA-256. Skipped when only browsing a
            folder, where hashing every file would be wasteful.

    Raises:
        SessionFileError: The file cannot be opened.
        SchemaError: A catalog table is missing.
        TimeBaseError: No channel can establish a timeline.
    """
    config = config or load_config()
    path = Path(path).resolve()

    con = duckdb_reader.open_session(path)
    try:
        metadata = duckdb_reader.read_metadata(con)
        registry = channel_registry.build_registry(con)
        base = time_base.build_time_base(con, registry, config)
        laps, lap_warnings = lap_splitter.split_laps(con, registry, base, config)

        info = _build_session_info(path, metadata, with_hash=with_hash)
        warnings = [*base.warnings, *lap_warnings]

        logger.info(
            "Loaded %s: %s / %s, %d channels, %d laps",
            path.name, info.track_name, info.car_name or "?",
            len(registry), len(laps),
        )
        return Session(
            info=info,
            time_base=base,
            registry=registry,
            laps=laps,
            metadata=metadata,
            connection=con,
            warnings=warnings,
        )
    except Exception:
        # A half-built session must not leak the connection.
        con.close()
        raise


def _build_session_info(
    path: Path,
    metadata: dict[str, str],
    *,
    with_hash: bool,
) -> SessionInfo:
    """Identify track, car and start time.

    `metadata` is consulted first because it is authoritative and, unlike the
    file name, names the car. The file name is the fallback and the source of
    the start timestamp, which `metadata` records only as a local wall clock
    without a zone.
    """
    try:
        name_track, name_session, started_at = parse_session_filename(path)
    except SessionNameError as exc:
        logger.warning("%s", exc)
        name_track, name_session, started_at = None, "?", None

    track = metadata.get(META_TRACK) or name_track or "?"
    layout = metadata.get(META_TRACK_LAYOUT)
    if layout and layout != track:
        # Some tracks record a layout distinct from the venue (a short circuit,
        # a chicane variant). They are genuinely different tracks for lap
        # comparison, so the layout wins.
        track = layout

    if started_at is None:
        # Without a parsable file name there is no timezone-qualified start.
        # Falling back to the epoch keeps the type honest and sorts the session
        # to the beginning, where it is obviously wrong rather than subtly so.
        from datetime import UTC, datetime
        started_at = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        logger.warning("Using file mtime as session start for %s", path.name)

    return SessionInfo(
        path=path,
        track_name=track,
        session_type_code=_session_code(metadata, name_session),
        started_at=started_at,
        car_name=metadata.get(META_CAR),
        car_class=metadata.get(META_CAR_CLASS),
        weather=metadata.get(META_WEATHER),
        file_hash=compute_file_hash(path) if with_hash else None,
        file_size_bytes=path.stat().st_size,
    )


def _session_code(metadata: dict[str, str], name_session: str) -> str:
    """Prefer the file name's single-letter code, which the catalog keys on.

    `metadata` spells the session type out ("Race"), so it is only used when the
    file name could not be parsed.
    """
    if name_session and name_session != "?":
        return name_session
    spelled = (metadata.get(META_SESSION_TYPE) or "").strip()
    return spelled[:1].upper() if spelled else "?"


def describe_time_base(base: TimeBase) -> str:
    """One-line Portuguese description of the time base, for display."""
    if base.source is time_base.TimeBaseSource.GPS_CORRECTED:
        return strings.LAPS_TIME_BASE_CORRECTED.format(drift=base.max_drift_s)
    if base.source is time_base.TimeBaseSource.UNVALIDATED:
        return strings.LAPS_TIME_BASE_UNVALIDATED
    return strings.LAPS_TIME_BASE_UNIFORM.format(drift=base.max_drift_s)
