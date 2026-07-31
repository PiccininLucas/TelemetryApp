"""Tests for the low-level session file reader."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from lmu_telemetry.core.errors import SchemaError, SessionFileError
from lmu_telemetry.ingest import duckdb_reader


# --------------------------------------------------------------------------- #
# Identifier quoting - most channel tables are named with a space in them
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("value", '"value"'),
        ("Brake Pos", '"Brake Pos"'),
        ("G Force Lat", '"G Force Lat"'),
        ("Brake Pos Unfiltered", '"Brake Pos Unfiltered"'),
        ('weird"name', '"weird""name"'),
        ("", '""'),
    ],
)
def test_quote_ident(raw, expected):
    assert duckdb_reader.quote_ident(raw) == expected


def test_quoting_actually_works_against_a_spaced_table(synthetic_session):
    """The real point of quoting: an unquoted `Ground Speed` is a syntax error."""
    con = duckdb_reader.open_session(synthetic_session)
    try:
        assert duckdb_reader.row_count(con, "Ground Speed") == 10
        assert duckdb_reader.column_names(con, "Ground Speed") == ["value"]
    finally:
        con.close()


# --------------------------------------------------------------------------- #
# Opening files
# --------------------------------------------------------------------------- #

def test_open_missing_file_raises(tmp_path: Path):
    with pytest.raises(SessionFileError):
        duckdb_reader.open_session(tmp_path / "does not exist.duckdb")


def test_open_non_duckdb_file_raises(tmp_path: Path):
    bogus = tmp_path / "corrupt.duckdb"
    bogus.write_bytes(b"this is definitely not a database" * 100)
    with pytest.raises(SessionFileError):
        duckdb_reader.open_session(bogus)


def test_connection_is_read_only(synthetic_session):
    """Session files belong to the game and must never be modified by this app."""
    import duckdb

    con = duckdb_reader.open_session(synthetic_session)
    try:
        with pytest.raises(duckdb.Error):
            con.execute('INSERT INTO "Ground Speed" VALUES (999.0)')
    finally:
        con.close()


def test_open_does_not_create_a_database(tmp_path: Path):
    """A wrong path must fail immediately, not create an empty file that only
    fails much later with a confusing "no such table"."""
    ghost = tmp_path / "ghost.duckdb"
    with pytest.raises(SessionFileError):
        duckdb_reader.open_session(ghost)
    assert not ghost.exists()


# --------------------------------------------------------------------------- #
# Catalog
# --------------------------------------------------------------------------- #

def test_read_catalog(synthetic_session):
    con = duckdb_reader.open_session(synthetic_session)
    try:
        catalog = duckdb_reader.read_catalog(con)
        assert set(catalog) == set(duckdb_reader.CATALOG_TABLES)
        assert list(catalog["channelsList"].columns) == [
            "channelName", "frequency", "unit"
        ]
        assert len(catalog["channelsList"]) == 4
    finally:
        con.close()


def test_read_metadata_as_dict(synthetic_session):
    con = duckdb_reader.open_session(synthetic_session)
    try:
        metadata = duckdb_reader.read_metadata(con)
        assert metadata["TrackName"] == "Test Track"
        assert metadata["CarName"] == "Test Car"
    finally:
        con.close()


def test_missing_catalog_table_raises(tmp_path: Path):
    """Without channelsList there are no frequencies, so there is no time base
    to degrade gracefully into."""
    import duckdb

    path = tmp_path / "Nothing_R_2026-01-01T00_00_00Z.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE metadata (key VARCHAR, value VARCHAR)")
    con.close()

    con = duckdb_reader.open_session(path)
    try:
        with pytest.raises(SchemaError):
            duckdb_reader.read_catalog(con)
    finally:
        con.close()


# --------------------------------------------------------------------------- #
# Reading values
# --------------------------------------------------------------------------- #

def test_read_single_column_shape_and_order(synthetic_session):
    con = duckdb_reader.open_session(synthetic_session)
    try:
        values = duckdb_reader.read_columns(con, "Ground Speed", ("value",))
        assert values.shape == (10,)
        assert values.dtype == np.float32
        # File order is time order for continuous channels; no ORDER BY is
        # applied because there is no column to order by.
        assert values.tolist() == pytest.approx([100.0 + i for i in range(10)])
    finally:
        con.close()


def test_read_multiple_columns_stacks_in_requested_order(synthetic_session):
    con = duckdb_reader.open_session(synthetic_session)
    try:
        values = duckdb_reader.read_columns(
            con, "TyresPressure", ("value1", "value2", "value3", "value4")
        )
        assert values.shape == (10, 4)
        assert values[0].tolist() == pytest.approx([170.0, 171.0, 172.0, 173.0])

        reversed_order = duckdb_reader.read_columns(
            con, "TyresPressure", ("value4", "value1")
        )
        assert reversed_order[0].tolist() == pytest.approx([173.0, 170.0])
    finally:
        con.close()


def test_read_columns_honours_dtype(synthetic_session):
    """Timestamps need float64: over an hour of running, float32 quantises them
    to about a millisecond."""
    con = duckdb_reader.open_session(synthetic_session)
    try:
        timestamps = duckdb_reader.read_columns(
            con, "Gear", ("ts",), dtype=np.float64
        )
        assert timestamps.dtype == np.float64
    finally:
        con.close()


def test_nulls_become_nan(tmp_path: Path):
    """A gap must be an explicit NaN, never a fill value mistaken for a reading."""
    import duckdb

    path = tmp_path / "Gaps_R_2026-01-01T00_00_00Z.duckdb"
    con = duckdb.connect(str(path))
    con.execute('CREATE TABLE "Some Channel" (value FLOAT)')
    con.execute('INSERT INTO "Some Channel" VALUES (1.0), (NULL), (3.0)')
    con.close()

    con = duckdb_reader.open_session(path)
    try:
        values = duckdb_reader.read_columns(con, "Some Channel", ("value",))
        assert values[0] == pytest.approx(1.0)
        assert np.isnan(values[1])
        assert values[2] == pytest.approx(3.0)
    finally:
        con.close()


# --------------------------------------------------------------------------- #
# Against a real file, when one is available
# --------------------------------------------------------------------------- #

def test_real_file_has_the_expected_catalog(real_session_con):
    catalog = duckdb_reader.read_catalog(real_session_con)
    assert not catalog["channelsList"].empty
    assert list(catalog["channelsList"].columns) == [
        "channelName", "frequency", "unit"
    ]


def test_real_continuous_channels_have_no_time_column(real_session_con):
    """The assumption the whole ingestion layer rests on.

    If a continuous channel ever gained a `ts` column, `t[i] = i / frequency`
    would stop being the right way to read it, and this test is the tripwire.
    """
    from lmu_telemetry.ingest import channel_registry

    registry = channel_registry.build_registry(real_session_con)
    continuous = channel_registry.continuous_channels(registry)
    assert continuous, "expected at least one continuous channel in a real file"

    for info in continuous:
        columns = duckdb_reader.column_names(real_session_con, info.name)
        assert channel_registry.TS_COLUMN not in columns, (
            f"{info.name} unexpectedly has a time column"
        )


def test_real_file_has_no_unknown_layouts(real_session_con):
    from lmu_telemetry.ingest import channel_registry

    tables = [
        t for t in duckdb_reader.list_tables(real_session_con)
        if t not in duckdb_reader.CATALOG_TABLES
    ]
    unknown = [
        t for t in tables
        if channel_registry.detect_format(
            duckdb_reader.column_names(real_session_con, t)
        ) is channel_registry.ChannelFormat.UNKNOWN
    ]
    assert unknown == []
