"""Tests for the per-session metadata cache."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from lmu_telemetry.core.models import Lap, LapFlag, SessionInfo
from lmu_telemetry.ingest.channel_registry import ChannelFormat, ChannelInfo
from lmu_telemetry.ingest.time_base import TimeBase, TimeBaseSource
from lmu_telemetry.storage import cache, paths


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """Keep every test out of the user's real ~/.lmu-telemetry."""
    monkeypatch.setenv(paths.ENV_DATA_DIR, str(tmp_path / "data"))
    return tmp_path


SESSION_ID = "a" * 64


def make_info(**overrides) -> SessionInfo:
    defaults = dict(
        path=Path("D:/Telemetry/Monza_R_2026-07-30T17_12_31Z.duckdb"),
        track_name="Autodromo Nazionale Monza",
        session_type_code="R",
        started_at=datetime(2026, 7, 30, 17, 12, 31, tzinfo=UTC),
        car_name="DKR Engineering #4:ELMS25",
        car_class="LMP3",
        weather="Partially Cloudy",
        file_hash=SESSION_ID,
        file_size_bytes=27_848_704,
    )
    return SessionInfo(**{**defaults, **overrides})


def make_registry() -> dict[str, ChannelInfo]:
    return {
        "Ground Speed": ChannelInfo(
            name="Ground Speed", frequency=100.0, unit="km/h",
            fmt=ChannelFormat.A, n_samples=145101, value_sql_type="FLOAT",
        ),
        # An event channel has no frequency, so this one round-trips a NaN.
        "Gear": ChannelInfo(
            name="Gear", frequency=float("nan"), unit="",
            fmt=ChannelFormat.C, n_samples=670, value_sql_type="TINYINT",
        ),
        "TyresPressure": ChannelInfo(
            name="TyresPressure", frequency=10.0, unit="kPa",
            fmt=ChannelFormat.B, n_samples=14510, value_sql_type="FLOAT",
        ),
    }


def make_laps() -> list[Lap]:
    return [
        Lap(
            index=0, number=0, t_start=17.47, t_end=246.94,
            official_time_s=121.92, sector_times_s=(47.954, 38.928, 35.038),
            flags=frozenset({LapFlag.PARTIAL}), off_track_fraction=0.0,
        ),
        Lap(
            index=1, number=1, t_start=246.94, t_end=353.84,
            official_time_s=0.0, sector_times_s=(35.391, None, None),
            flags=frozenset({LapFlag.INVALIDATED}), off_track_fraction=0.012,
        ),
        Lap(
            index=2, number=2, t_start=353.84, t_end=464.26,
            official_time_s=110.402, sector_times_s=(39.045, 36.521, 34.836),
            flags=frozenset({LapFlag.VALID}), off_track_fraction=0.0,
        ),
    ]


def write_sample(**overrides):
    arguments = dict(
        session_id=SESSION_ID,
        info=make_info(),
        time_base=TimeBase(
            t0=17.4725, span_s=1451.0, source=TimeBaseSource.UNIFORM,
            max_drift_s=0.0,
        ),
        registry=make_registry(),
        laps=make_laps(),
        warnings=[],
    )
    arguments.update(overrides)
    return cache.write_manifest(**arguments)


# --------------------------------------------------------------------------- #
# Round trip
# --------------------------------------------------------------------------- #

def test_manifest_round_trips():
    write_sample()
    restored = cache.read_manifest(SESSION_ID)

    assert restored is not None
    assert restored.session_id == SESSION_ID
    assert restored.info.track_name == "Autodromo Nazionale Monza"
    assert restored.info.car_class == "LMP3"
    assert restored.info.started_at == datetime(2026, 7, 30, 17, 12, 31, tzinfo=UTC)
    assert restored.time_base.source is TimeBaseSource.UNIFORM
    assert restored.time_base.span_s == pytest.approx(1451.0)
    assert len(restored.registry) == 3
    assert len(restored.laps) == 3


def test_lap_flags_and_sectors_survive():
    write_sample()
    laps = cache.read_manifest(SESSION_ID).laps

    assert laps[0].is_partial
    assert laps[1].is_invalidated
    assert laps[2].is_comparable
    assert laps[2].sector_times_s == pytest.approx((39.045, 36.521, 34.836))
    # None must stay None, not become 0.0 - a missing sector is not a zero one.
    assert laps[1].sector_times_s[1] is None
    assert laps[1].off_track_fraction == pytest.approx(0.012)


def test_channel_registry_survives_including_nan_frequency():
    """Event channels have no frequency, and JSON has no NaN literal."""
    write_sample()
    registry = cache.read_manifest(SESSION_ID).registry

    import math

    assert registry["Ground Speed"].frequency == pytest.approx(100.0)
    assert math.isnan(registry["Gear"].frequency)
    assert registry["Gear"].fmt is ChannelFormat.C
    assert registry["TyresPressure"].fmt is ChannelFormat.B
    assert registry["TyresPressure"].is_per_wheel
    assert registry["Gear"].is_discrete


def test_manifest_is_valid_json():
    """NaN and Infinity are Python extensions, not JSON. Any other tool reading
    the manifest would choke on them."""
    manifest = write_sample(
        time_base=TimeBase(
            t0=0.0, span_s=10.0, source=TimeBaseSource.UNVALIDATED,
            max_drift_s=float("nan"),
        )
    )
    text = manifest.read_text(encoding="utf-8")

    assert "NaN" not in text
    assert "Infinity" not in text
    json.loads(text, parse_constant=_reject_constants)


def _reject_constants(name):
    raise AssertionError(f"manifest contains the non-JSON constant {name!r}")


def test_unvalidated_time_base_round_trips_with_nan_drift():
    import math

    write_sample(
        time_base=TimeBase(
            t0=0.0, span_s=10.0, source=TimeBaseSource.UNVALIDATED,
            max_drift_s=float("nan"), warnings=("sem GPS",),
        )
    )
    restored = cache.read_manifest(SESSION_ID).time_base

    assert restored.source is TimeBaseSource.UNVALIDATED
    assert math.isnan(restored.max_drift_s)
    assert restored.is_validated is False
    assert restored.warnings == ("sem GPS",)


# --------------------------------------------------------------------------- #
# Invalidation
# --------------------------------------------------------------------------- #

def test_missing_cache_returns_none():
    assert cache.read_manifest("b" * 64) is None
    assert cache.is_cached("b" * 64) is False


def test_cache_is_rejected_when_the_source_hash_differs():
    """Guards against a session id being reused for different content."""
    write_sample()
    assert cache.read_manifest(SESSION_ID, expected_hash=SESSION_ID) is not None
    assert cache.read_manifest(SESSION_ID, expected_hash="c" * 64) is None


def test_cache_from_an_older_format_version_is_ignored():
    """A manifest whose meaning changed must be discarded, not misread: a subtly
    wrong lap table looks perfectly valid."""
    manifest = write_sample()
    document = json.loads(manifest.read_text(encoding="utf-8"))
    document["cache_format_version"] = cache.CACHE_FORMAT_VERSION - 1
    manifest.write_text(json.dumps(document), encoding="utf-8")

    assert cache.read_manifest(SESSION_ID) is None


def test_damaged_cache_degrades_instead_of_raising():
    """A cache is an optimisation. Failing to read one must fall back to the
    source, never fail the application."""
    manifest = write_sample()
    manifest.write_text("{ this is not json", encoding="utf-8")

    assert cache.read_manifest(SESSION_ID) is None


def test_manifest_missing_a_required_field_is_discarded():
    manifest = write_sample()
    document = json.loads(manifest.read_text(encoding="utf-8"))
    del document["time_base"]
    manifest.write_text(json.dumps(document), encoding="utf-8")

    assert cache.read_manifest(SESSION_ID) is None


def test_rewriting_replaces_the_previous_manifest():
    write_sample()
    write_sample(laps=make_laps()[:1])

    assert len(cache.read_manifest(SESSION_ID).laps) == 1


def test_no_temporary_file_is_left_behind():
    """The write goes through a temporary file so an interrupted write cannot
    leave a manifest that parses but describes nothing real."""
    manifest = write_sample()
    leftovers = list(manifest.parent.glob("*.tmp"))
    assert leftovers == []


# --------------------------------------------------------------------------- #
# Housekeeping
# --------------------------------------------------------------------------- #

def test_lap_frames_directory_is_created_for_phase_4():
    write_sample()
    directory = paths.session_cache_dir(SESSION_ID) / cache.LAP_FRAMES_DIRNAME
    assert directory.is_dir()


def test_clear_removes_one_session():
    write_sample()
    assert cache.clear(SESSION_ID) is True
    assert cache.read_manifest(SESSION_ID) is None
    assert cache.clear(SESSION_ID) is False


def test_clear_all_removes_every_session():
    write_sample()
    write_sample(session_id="d" * 64)
    assert cache.clear_all() == 2
    assert cache.cache_size_bytes() == 0


def test_cache_stays_small():
    """The whole point of caching metadata rather than channel data.

    A real session's manifest holds 98 channels and a lap table; measured across
    64 real sessions the entire cache came to 1.2 MB, against 1.9 GB for a
    100 Hz copy of the same telemetry.
    """
    write_sample()
    assert cache.cache_size_bytes() < 50_000


def test_data_dir_honours_the_environment_override(tmp_path, monkeypatch):
    target = tmp_path / "elsewhere"
    monkeypatch.setenv(paths.ENV_DATA_DIR, str(target))
    assert paths.data_dir() == target
    assert target.is_dir()
