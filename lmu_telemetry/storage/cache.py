"""Per-session cache of derived data, invalidated by the source file's hash.

What is worth caching was decided by measurement rather than by assumption.

**Channel data is not cached.** Reading five chart channels straight from the
game's file takes 3.8 ms; the same five columns from a parquet copy take 2.9 ms.
The source is already a compressed columnar database, so re-encoding it buys
about a millisecond and costs twice the disk (a 26.7 MB session becomes a
51.9 MB cache). Dropping the channels that never vary saves nothing either -
constant columns already compress to almost zero.

**Session metadata is worth caching.** Opening a session costs 83 ms, of which
53 ms is building the channel registry: that is one DESCRIBE and one COUNT(*)
per channel, roughly 200 SQL round-trips. Browsing a folder of 58 sessions
therefore takes about 4.9 s before anything is drawn. The manifest holds the
result in a few kilobytes and makes that instant.

The layout leaves room for phase 4, where the genuinely expensive artifact
appears: per-lap frames resampled onto a 1 m distance grid, which require
cumulative integration of speed and a scale correction per lap. Those land in
`laps/` inside the same folder and reuse the same invalidation.

    <data_dir>/cache/<session_id>/
        manifest.json      identity, time base, channel registry, lap table
        laps/              phase 4: one parquet per lap, distance domain
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lmu_telemetry.core.models import Lap, LapFlag, SessionInfo
from lmu_telemetry.ingest.channel_registry import ChannelFormat, ChannelInfo
from lmu_telemetry.ingest.time_base import TimeBase, TimeBaseSource
from lmu_telemetry.logging_config import get_logger
from lmu_telemetry.storage import paths

logger = get_logger(__name__)

#: Bumped whenever the manifest's meaning changes. A cache written by an older
#: version is discarded rather than misread - the alternative is a subtly wrong
#: lap table that looks perfectly valid.
CACHE_FORMAT_VERSION = 1

MANIFEST_FILENAME = "manifest.json"
LAP_FRAMES_DIRNAME = "laps"


@dataclass(frozen=True, slots=True)
class CachedSession:
    """A session's derived data, read back without opening the source file."""

    session_id: str
    info: SessionInfo
    time_base: TimeBase
    registry: dict[str, ChannelInfo]
    laps: list[Lap]
    warnings: list[str]
    cached_at: datetime

    @property
    def cache_dir(self) -> Path:
        return paths.session_cache_dir(self.session_id)


# --------------------------------------------------------------------------- #
# Writing
# --------------------------------------------------------------------------- #

def write_manifest(
    session_id: str,
    info: SessionInfo,
    time_base: TimeBase,
    registry: dict[str, ChannelInfo],
    laps: list[Lap],
    warnings: list[str],
) -> Path:
    """Write a session's manifest, replacing any previous one.

    Returns:
        Path to the manifest file.
    """
    directory = paths.session_cache_dir(session_id)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / LAP_FRAMES_DIRNAME).mkdir(exist_ok=True)

    document = {
        "cache_format_version": CACHE_FORMAT_VERSION,
        "session_id": session_id,
        "cached_at": datetime.now(UTC).isoformat(),
        "source": _encode_info(info),
        "time_base": _encode_time_base(time_base),
        "channels": [_encode_channel(c) for c in registry.values()],
        "laps": [_encode_lap(lap) for lap in laps],
        "warnings": list(warnings),
    }

    target = directory / MANIFEST_FILENAME
    # Write to a temporary file and replace, so an interrupted write cannot
    # leave a half-written manifest that parses but describes nothing real.
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(document, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    temporary.replace(target)

    logger.info("Cached manifest for session %s (%d laps)", session_id[:12], len(laps))
    return target


# --------------------------------------------------------------------------- #
# Reading
# --------------------------------------------------------------------------- #

def read_manifest(session_id: str, expected_hash: str | None = None) -> CachedSession | None:
    """Read a cached manifest, or None when it is absent or stale.

    Args:
        session_id: The source file's hash.
        expected_hash: When given, the cache is rejected unless the manifest
            records this exact source hash. Guards against a session id being
            reused for different content.

    Returns:
        The cached session, or None. Never raises for a damaged cache: a cache
        is an optimisation, and failing to read one must always fall back to
        reading the source rather than failing the application.
    """
    manifest = paths.session_cache_dir(session_id) / MANIFEST_FILENAME
    if not manifest.is_file():
        return None

    try:
        document = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Discarding unreadable cache for %s: %s", session_id[:12], exc)
        return None

    if document.get("cache_format_version") != CACHE_FORMAT_VERSION:
        logger.info(
            "Cache for %s was written by format version %s, expected %d; ignoring",
            session_id[:12], document.get("cache_format_version"),
            CACHE_FORMAT_VERSION,
        )
        return None

    try:
        info = _decode_info(document["source"])
        if expected_hash is not None and info.file_hash != expected_hash:
            logger.info("Cache for %s records a different source hash", session_id[:12])
            return None

        return CachedSession(
            session_id=document["session_id"],
            info=info,
            time_base=_decode_time_base(document["time_base"]),
            registry={c["name"]: _decode_channel(c) for c in document["channels"]},
            laps=[_decode_lap(lap) for lap in document["laps"]],
            warnings=list(document.get("warnings", [])),
            cached_at=datetime.fromisoformat(document["cached_at"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("Discarding malformed cache for %s: %s", session_id[:12], exc)
        return None


def is_cached(session_id: str) -> bool:
    """True when a usable manifest exists for this session."""
    return read_manifest(session_id) is not None


def clear(session_id: str) -> bool:
    """Delete one session's cache folder. Returns whether anything was removed."""
    import shutil

    directory = paths.session_cache_dir(session_id)
    if not directory.is_dir():
        return False
    shutil.rmtree(directory)
    logger.info("Cleared cache for session %s", session_id[:12])
    return True


def clear_all() -> int:
    """Delete every cached session. Returns how many were removed."""
    import shutil

    removed = 0
    for directory in paths.cache_dir().iterdir():
        if directory.is_dir():
            shutil.rmtree(directory)
            removed += 1
    logger.info("Cleared %d cached sessions", removed)
    return removed


def cache_size_bytes() -> int:
    """Total size of the cache on disk."""
    return sum(
        f.stat().st_size for f in paths.cache_dir().rglob("*") if f.is_file()
    )


# --------------------------------------------------------------------------- #
# Encoding helpers. Kept explicit rather than reflective so that adding a field
# to a dataclass cannot silently change the cache format without a version bump.
# --------------------------------------------------------------------------- #

def _json_float(value: float) -> float | None:
    """Encode a float for JSON, mapping NaN and infinity to null.

    `json.dumps` writes NaN and Infinity as bare tokens, which Python reads back
    but which are not valid JSON - any other tool reading the manifest would
    choke. Both occur legitimately here: an event channel has no frequency, and
    an unvalidated time base has no measured drift.
    """
    import math

    return value if math.isfinite(value) else None


def _decode_float(value: float | None) -> float:
    """Inverse of `_json_float`: null becomes NaN."""
    return float("nan") if value is None else float(value)


def _encode_info(info: SessionInfo) -> dict[str, Any]:
    return {
        "path": str(info.path),
        "track_name": info.track_name,
        "session_type_code": info.session_type_code,
        "started_at": info.started_at.isoformat(),
        "car_name": info.car_name,
        "car_class": info.car_class,
        "weather": info.weather,
        "file_hash": info.file_hash,
        "file_size_bytes": info.file_size_bytes,
    }


def _decode_info(document: dict[str, Any]) -> SessionInfo:
    return SessionInfo(
        path=Path(document["path"]),
        track_name=document["track_name"],
        session_type_code=document["session_type_code"],
        started_at=datetime.fromisoformat(document["started_at"]),
        car_name=document.get("car_name"),
        car_class=document.get("car_class"),
        weather=document.get("weather"),
        file_hash=document.get("file_hash"),
        file_size_bytes=document.get("file_size_bytes"),
    )


def _encode_time_base(base: TimeBase) -> dict[str, Any]:
    # `reference_times` is deliberately not stored. It is only meaningful for a
    # corrected time base, and holding 141k float64 samples would defeat the
    # point of a manifest measured in kilobytes. A session needing it is read
    # from the source, which is where the correction is derived anyway.
    return {
        "t0": base.t0,
        "span_s": base.span_s,
        "source": base.source.value,
        "max_drift_s": _json_float(base.max_drift_s),
        "warnings": list(base.warnings),
    }


def _decode_time_base(document: dict[str, Any]) -> TimeBase:
    return TimeBase(
        t0=float(document["t0"]),
        span_s=float(document["span_s"]),
        source=TimeBaseSource(document["source"]),
        max_drift_s=_decode_float(document["max_drift_s"]),
        reference_times=None,
        warnings=tuple(document.get("warnings", ())),
    )


def _encode_channel(channel: ChannelInfo) -> dict[str, Any]:
    return {
        "name": channel.name,
        "frequency": _json_float(channel.frequency),
        "unit": channel.unit,
        "fmt": channel.fmt.value,
        "n_samples": channel.n_samples,
        "value_sql_type": channel.value_sql_type,
    }


def _decode_channel(document: dict[str, Any]) -> ChannelInfo:
    return ChannelInfo(
        name=document["name"],
        frequency=_decode_float(document["frequency"]),
        unit=document["unit"],
        fmt=ChannelFormat(document["fmt"]),
        n_samples=int(document["n_samples"]),
        value_sql_type=document["value_sql_type"],
    )


def _encode_lap(lap: Lap) -> dict[str, Any]:
    return {
        "index": lap.index,
        "number": lap.number,
        "t_start": lap.t_start,
        "t_end": lap.t_end,
        "official_time_s": lap.official_time_s,
        "sector_times_s": list(lap.sector_times_s),
        "flags": sorted(flag.value for flag in lap.flags),
        "off_track_fraction": lap.off_track_fraction,
    }


def _decode_lap(document: dict[str, Any]) -> Lap:
    sectors = document.get("sector_times_s") or [None, None, None]
    return Lap(
        index=int(document["index"]),
        number=int(document["number"]),
        t_start=float(document["t_start"]),
        t_end=float(document["t_end"]),
        official_time_s=document.get("official_time_s"),
        sector_times_s=(sectors[0], sectors[1], sectors[2]),
        flags=frozenset(LapFlag(f) for f in document.get("flags", ())),
        off_track_fraction=float(document.get("off_track_fraction", 0.0)),
    )
