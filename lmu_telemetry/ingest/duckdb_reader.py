"""Low-level access to a Le Mans Ultimate session file.

This module knows how to talk to DuckDB and nothing else. It has no opinion
about what a channel means; interpreting the catalog is `channel_registry`'s
job. Keeping the split means the SQL quoting rules live in exactly one place.

Two facts about these files drive the whole module:

1. **The files belong to the game.** Every connection is opened read-only so a
   bug here can never damage a recorded session.
2. **Table names contain spaces** (`Brake Pos`, `G Force Lat`). Every identifier
   that reaches SQL has to go through `quote_ident`. This is the single most
   likely source of bugs in this layer, which is why there is exactly one
   function that does it and a test dedicated to it.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from lmu_telemetry.core.errors import SchemaError, SessionFileError
from lmu_telemetry.logging_config import get_logger
from lmu_telemetry.ui import strings

logger = get_logger(__name__)

#: Catalog tables every session file is expected to carry.
CATALOG_TABLES = ("channelsList", "eventsList", "metadata")


def quote_ident(name: str) -> str:
    """Quote a SQL identifier so it survives spaces and special characters.

    DuckDB (like standard SQL) uses double quotes for identifiers, and an
    embedded double quote is escaped by doubling it. Channel tables are named
    after the channel (`Brake Pos`, `G Force Lat`), so an unquoted identifier
    is a syntax error on most of this schema.

    >>> quote_ident("Brake Pos")
    '"Brake Pos"'
    >>> quote_ident('weird"name')
    '"weird""name"'
    """
    return '"' + name.replace('"', '""') + '"'


def open_session(path: Path | str) -> duckdb.DuckDBPyConnection:
    """Open a session file read-only.

    Args:
        path: Path to a `.duckdb` file written by the game.

    Raises:
        SessionFileError: The file is missing, locked, or not a DuckDB database.
    """
    path = Path(path)
    if not path.is_file():
        raise SessionFileError(strings.ERR_FILE_NOT_FOUND.format(path=path))

    try:
        # read_only also prevents DuckDB from creating an empty database when
        # the path is wrong, which would otherwise fail silently much later.
        return duckdb.connect(str(path), read_only=True)
    except duckdb.Error as exc:
        raise SessionFileError(
            strings.ERR_FILE_UNREADABLE.format(path=path, detail=exc)
        ) from exc


def list_tables(con: duckdb.DuckDBPyConnection) -> list[str]:
    """Return every table name in the file, sorted."""
    rows = con.execute("SHOW TABLES").fetchall()
    return sorted(row[0] for row in rows)


def describe_table(con: duckdb.DuckDBPyConnection, table: str) -> list[tuple[str, str]]:
    """Return `[(column_name, column_type), ...]` for one table."""
    rows = con.execute(f"DESCRIBE {quote_ident(table)}").fetchall()
    return [(row[0], row[1]) for row in rows]


def column_names(con: duckdb.DuckDBPyConnection, table: str) -> list[str]:
    """Return just the column names of a table, in declaration order."""
    return [name for name, _type in describe_table(con, table)]


def row_count(con: duckdb.DuckDBPyConnection, table: str) -> int:
    """Return the number of rows in a table."""
    result = con.execute(f"SELECT COUNT(*) FROM {quote_ident(table)}").fetchone()
    return int(result[0]) if result else 0


def read_table(con: duckdb.DuckDBPyConnection, table: str) -> pd.DataFrame:
    """Read a whole table as a DataFrame. Intended for the small catalog tables."""
    return con.execute(f"SELECT * FROM {quote_ident(table)}").fetchdf()


def read_catalog(con: duckdb.DuckDBPyConnection) -> dict[str, pd.DataFrame]:
    """Read `channelsList`, `eventsList` and `metadata`.

    Returns:
        Mapping of table name to DataFrame.

    Raises:
        SchemaError: A catalog table is missing. Without `channelsList` there
            are no sample frequencies, and without frequencies the implicit
            time base `t[i] = i / frequency` cannot be built at all, so there is
            nothing to degrade gracefully into.
    """
    present = set(list_tables(con))
    catalog: dict[str, pd.DataFrame] = {}

    for table in CATALOG_TABLES:
        if table not in present:
            raise SchemaError(
                strings.ERR_MISSING_CATALOG_TABLE.format(table=table)
            )
        catalog[table] = read_table(con, table)

    return catalog


def read_metadata(con: duckdb.DuckDBPyConnection) -> dict[str, str]:
    """Read `metadata` as a plain key -> value dictionary."""
    frame = read_table(con, "metadata")
    if "key" not in frame.columns or "value" not in frame.columns:
        raise SchemaError(strings.ERR_MISSING_CATALOG_TABLE.format(table="metadata"))
    return {str(k): str(v) for k, v in zip(frame["key"], frame["value"], strict=True)}


def read_columns(
    con: duckdb.DuckDBPyConnection,
    table: str,
    columns: Sequence[str],
    dtype: type[np.floating] = np.float32,
) -> np.ndarray:
    """Read one or more numeric columns of a channel table as a numpy array.

    Row order is the file's own order, which for continuous channels *is* the
    time order: sample `i` was recorded at `t = i / frequency`. No ORDER BY is
    applied, deliberately - there is no column to order by, and imposing one
    would silently reorder samples.

    Args:
        con: Open read-only connection.
        table: Channel table name (may contain spaces).
        columns: Column names to read, in the order they should appear.
        dtype: Output dtype. float32 is the default because the game records
            float32 anyway and a long session holds millions of samples, so
            float64 would double memory for no added precision.

    Returns:
        Shape `(n,)` when one column is requested, `(n, len(columns))` otherwise.
        Missing values become NaN.
    """
    projection = ", ".join(quote_ident(c) for c in columns)
    fetched = con.execute(
        f"SELECT {projection} FROM {quote_ident(table)}"
    ).fetchnumpy()

    arrays = []
    for name in columns:
        column = fetched[name]
        # Nullable columns come back as masked arrays; make the gaps explicit
        # NaN so downstream code never mistakes a fill value for a reading.
        if isinstance(column, np.ma.MaskedArray):
            column = column.astype(dtype).filled(np.nan)
        arrays.append(np.asarray(column, dtype=dtype))

    if len(arrays) == 1:
        return arrays[0]
    return np.column_stack(arrays)


def file_size_bytes(path: Path | str) -> int:
    """Return the size of the session file in bytes."""
    return Path(path).stat().st_size
