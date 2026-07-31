"""Tests for channel layout classification and the registry."""

from __future__ import annotations

import math

import pytest

from lmu_telemetry.core.errors import ChannelNotFoundError
from lmu_telemetry.ingest import channel_registry, duckdb_reader
from lmu_telemetry.ingest.channel_registry import ChannelFormat, ChannelInfo


# --------------------------------------------------------------------------- #
# detect_format - pure, so no database is involved
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    ("columns", "expected"),
    [
        (["value"], ChannelFormat.A),
        (["value1", "value2", "value3", "value4"], ChannelFormat.B),
        (["ts", "value"], ChannelFormat.C),
        (["ts", "value1", "value2", "value3", "value4"], ChannelFormat.D),
        # Column order must not matter: DESCRIBE returns declaration order,
        # which is not guaranteed to be stable across game versions.
        (["value4", "value1", "value3", "value2"], ChannelFormat.B),
        (["value", "ts"], ChannelFormat.C),
    ],
)
def test_detect_format_recognises_known_layouts(columns, expected):
    assert channel_registry.detect_format(columns) is expected


@pytest.mark.parametrize(
    "columns",
    [
        [],
        ["ts"],
        ["value1", "value2"],                    # partial wheel set
        ["value1", "value2", "value3"],          # three wheels
        ["value", "value1"],                     # mixed
        ["ts", "value", "extra"],                # extra column
        ["timestamp", "value"],                  # different time column name
    ],
)
def test_detect_format_rejects_near_misses(columns):
    """A near miss must be UNKNOWN, never snapped to the closest layout.

    Forcing a nearly-matching table into a layout would read the wrong columns
    and silently corrupt every time alignment built on it. Refusing to classify
    is the safe failure.
    """
    assert channel_registry.detect_format(columns) is ChannelFormat.UNKNOWN


def test_format_properties():
    assert ChannelFormat.A.is_event is False
    assert ChannelFormat.C.is_event is True
    assert ChannelFormat.D.is_event is True
    assert ChannelFormat.B.is_per_wheel is True
    assert ChannelFormat.C.is_per_wheel is False
    assert ChannelFormat.A.value_columns == ("value",)
    assert ChannelFormat.D.value_columns == channel_registry.WHEEL_VALUE_COLUMNS
    assert ChannelFormat.UNKNOWN.value_columns == ()


# --------------------------------------------------------------------------- #
# ChannelInfo
# --------------------------------------------------------------------------- #

def make_info(**overrides) -> ChannelInfo:
    defaults = dict(
        name="Test",
        frequency=100.0,
        unit="",
        fmt=ChannelFormat.A,
        n_samples=1000,
        value_sql_type="FLOAT",
    )
    return ChannelInfo(**{**defaults, **overrides})


@pytest.mark.parametrize("frequency", [0.0, -1.0, float("nan"), float("inf")])
def test_unusable_frequency_is_rejected(frequency):
    """Guards `t[i] = i / frequency` against producing infinities."""
    info = make_info(frequency=frequency)
    assert info.has_usable_frequency is False
    assert math.isnan(info.implicit_duration_s)


def test_implicit_duration_and_span_differ_by_one_sample():
    """Duration counts n periods, span counts n-1 gaps.

    Comparing a duration against a clock's `last - first` invents a drift of
    exactly one sample period, which is easy to misread as a timing fault.
    """
    info = make_info(frequency=100.0, n_samples=1000)
    assert info.implicit_duration_s == pytest.approx(10.0)
    assert info.implicit_span_s == pytest.approx(9.99)


def test_effective_frequency_recovers_a_truncated_rate():
    """The catalog stores frequency as INTEGER, so 7.017 Hz is written as 7.

    Reproduces the real case found by schema inspection: a channel with 9934
    samples over a 1415.52 s recording is sampled at 7.017 Hz, not 7 Hz.
    """
    info = make_info(frequency=7.0, n_samples=9934)
    effective = info.effective_frequency(1415.520)

    assert effective == pytest.approx(7.0172, abs=1e-4)
    # Believing the declared rate misplaces the last sample by seconds.
    declared_span = (info.n_samples - 1) / info.frequency
    assert declared_span - 1415.520 > 3.0


def test_effective_frequency_falls_back_without_reference():
    info = make_info(frequency=50.0, n_samples=500)
    assert info.effective_frequency(0.0) == 50.0
    assert make_info(n_samples=1).effective_frequency(10.0) == 100.0


@pytest.mark.parametrize(
    ("sql_type", "fmt", "expected"),
    [
        ("FLOAT", ChannelFormat.A, False),
        ("DOUBLE", ChannelFormat.A, False),
        # Continuous layouts really do carry discrete values in these files:
        # TC and OverheatingState are BOOLEAN, SurfaceTypes is UTINYINT.
        ("BOOLEAN", ChannelFormat.A, True),
        ("UTINYINT", ChannelFormat.B, True),
        ("TINYINT", ChannelFormat.A, True),
        # Events are discrete in time regardless of their value type.
        ("FLOAT", ChannelFormat.C, True),
    ],
)
def test_is_discrete(sql_type, fmt, expected):
    assert make_info(value_sql_type=sql_type, fmt=fmt).is_discrete is expected


# --------------------------------------------------------------------------- #
# build_registry against a synthetic file
# --------------------------------------------------------------------------- #

def test_build_registry_classifies_every_layout(synthetic_session):
    con = duckdb_reader.open_session(synthetic_session)
    try:
        registry = channel_registry.build_registry(con)

        assert set(registry) == {
            "Ground Speed", "GPS Time", "TyresPressure",
            "SurfaceTypes", "Gear", "TyresCompound",
        }
        assert registry["Ground Speed"].fmt is ChannelFormat.A
        assert registry["TyresPressure"].fmt is ChannelFormat.B
        assert registry["Gear"].fmt is ChannelFormat.C
        assert registry["TyresCompound"].fmt is ChannelFormat.D

        # Units and frequencies come from the catalog, verbatim.
        assert registry["Ground Speed"].unit == "km/h"
        assert registry["Ground Speed"].frequency == 10.0

        # Events get NaN frequency: they are irregular by construction.
        assert math.isnan(registry["Gear"].frequency)

        # Discreteness is read from the column type, not from the layout.
        assert registry["SurfaceTypes"].is_discrete is True
        assert registry["Ground Speed"].is_discrete is False
    finally:
        con.close()


def test_read_channel_shapes(synthetic_session):
    con = duckdb_reader.open_session(synthetic_session)
    try:
        registry = channel_registry.build_registry(con)

        speed = channel_registry.read_channel(con, registry, "Ground Speed")
        assert speed.shape == (10,)
        assert speed[0] == pytest.approx(100.0)

        pressures = channel_registry.read_channel(con, registry, "TyresPressure")
        assert pressures.shape == (10, 4)
        # Columns must stay in file order, which is the assumed wheel order.
        assert pressures[0].tolist() == pytest.approx([170.0, 171.0, 172.0, 173.0])

        timestamps = channel_registry.read_event_timestamps(con, registry, "Gear")
        assert timestamps.tolist() == pytest.approx([0.0, 0.3, 0.7])
    finally:
        con.close()


def test_missing_channel_raises_typed_error(synthetic_session):
    """Callers must be able to disable one feature, not crash the app."""
    con = duckdb_reader.open_session(synthetic_session)
    try:
        registry = channel_registry.build_registry(con)
        with pytest.raises(ChannelNotFoundError) as excinfo:
            channel_registry.read_channel(con, registry, "Yaw Rate")
        assert excinfo.value.channel_name == "Yaw Rate"
    finally:
        con.close()


def test_require_reports_missing_prerequisites(synthetic_session):
    con = duckdb_reader.open_session(synthetic_session)
    try:
        registry = channel_registry.build_registry(con)
        missing = channel_registry.require(
            registry, ["Ground Speed", "Yaw Rate", "Steered Angle"]
        )
        assert missing == ["Yaw Rate", "Steered Angle"]
    finally:
        con.close()
