"""Build the channel registry: what each channel is, and how to read it.

There is no single telemetry table in these files - there is one table per
channel, in one of four column layouts:

    A  (value,)                     continuous, single valued  - Engine RPM
    B  (value1..value4)             continuous, per wheel      - TyresPressure
    C  (ts, value)                  event, single valued       - Gear
    D  (ts, value1..value4)         event, per wheel           - TyresCompound

The critical property of layouts A and B: **there is no time column**. Time is
implicit in the row index,

    t[i] = i / frequency

with `frequency` coming from the `channelsList` catalog. That makes ingestion
index arithmetic instead of a temporal join, but it also means a stall during
recording desynchronises index from time with no error anywhere - which is why
`time_base` cross-checks against the `GPS Time` channel (phase 2).

Layout is always derived from the file's own `DESCRIBE` output, never from a
hardcoded list of channel names. If a game update adds, removes or reshapes a
channel, the registry adapts on its own; only the divergence report in
`scripts/inspect_schema.py` compares against an expected list, and that report
exists precisely to tell a human that something moved.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import Enum

import duckdb
import numpy as np
import pandas as pd

from lmu_telemetry.core.errors import ChannelNotFoundError
from lmu_telemetry.ingest import duckdb_reader
from lmu_telemetry.logging_config import get_logger
from lmu_telemetry.ui import strings

logger = get_logger(__name__)

#: Column name carrying the sample timestamp in event layouts.
TS_COLUMN = "ts"

#: Column name of a single-valued measurement.
VALUE_COLUMN = "value"

#: Column names of a per-wheel measurement, in file order.
WHEEL_VALUE_COLUMNS = ("value1", "value2", "value3", "value4")

#: DuckDB column types whose values are discrete, i.e. must never be linearly
#: interpolated when resampled.
#:
#: This is *not* the same question as "is it an event". Schema inspection of a
#: real file found `TC` (BOOLEAN) and `OverheatingState` (BOOLEAN) in layout A
#: and `SurfaceTypes` (UTINYINT) in layout B - continuous layouts carrying
#: discrete values. Interpolating them would invent surface type 1.5 halfway
#: between asphalt and kerb, and a traction-control state of 0.5. Discreteness
#: therefore has to be read from the column type, not inferred from the layout.
DISCRETE_SQL_TYPES = frozenset({
    "BOOLEAN",
    "TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT",
    "UTINYINT", "USMALLINT", "UINTEGER", "UBIGINT", "UHUGEINT",
    "VARCHAR",
})

#: Wheel order assumed for layouts B and D.
#:
#: Nothing in the file states which index is which wheel. This is the rFactor 2
#: convention, which Le Mans Ultimate inherits. It is an *assumption*, and
#: `tests/test_wheel_convention.py` (phase 2) checks it empirically: through a
#: long sustained corner the outside wheels must run hotter and more loaded.
WHEEL_ORDER = ("FL", "FR", "RL", "RR")


class ChannelFormat(str, Enum):
    """The four column layouts a channel table can have."""

    A = "A"  # (value,)                continuous, single valued
    B = "B"  # (value1..value4)        continuous, per wheel
    C = "C"  # (ts, value)             event, single valued
    D = "D"  # (ts, value1..value4)    event, per wheel
    UNKNOWN = "UNKNOWN"

    @property
    def is_event(self) -> bool:
        """True when the layout carries its own timestamps.

        Events are sampled irregularly, only when the value changes. They are
        never linearly interpolated - resampling them uses forward fill, because
        interpolating between gear 3 and gear 4 would invent a gear 3.5.
        """
        return self in (ChannelFormat.C, ChannelFormat.D)

    @property
    def is_per_wheel(self) -> bool:
        """True when the layout carries four values, one per wheel."""
        return self in (ChannelFormat.B, ChannelFormat.D)

    @property
    def value_columns(self) -> tuple[str, ...]:
        """The value-carrying columns of this layout, in file order."""
        if self.is_per_wheel:
            return WHEEL_VALUE_COLUMNS
        if self is ChannelFormat.UNKNOWN:
            return ()
        return (VALUE_COLUMN,)


def detect_format(columns: Iterable[str]) -> ChannelFormat:
    """Classify a channel table from its column names alone.

    Pure function: takes column names, returns a layout. No database needed,
    which is what makes the classification rule directly testable.

    Classification is by exact column set, not by "contains a value column".
    A table that *nearly* matches a layout is reported as UNKNOWN rather than
    forced into the closest match - a silent misclassification here would
    corrupt every downstream time alignment.

    >>> detect_format(["value"])
    <ChannelFormat.A: 'A'>
    >>> detect_format(["ts", "value1", "value2", "value3", "value4"])
    <ChannelFormat.D: 'D'>
    >>> detect_format(["ts", "value", "extra"])
    <ChannelFormat.UNKNOWN: 'UNKNOWN'>
    """
    column_set = set(columns)
    wheels = set(WHEEL_VALUE_COLUMNS)

    if column_set == {VALUE_COLUMN}:
        return ChannelFormat.A
    if column_set == wheels:
        return ChannelFormat.B
    if column_set == {TS_COLUMN, VALUE_COLUMN}:
        return ChannelFormat.C
    if column_set == {TS_COLUMN} | wheels:
        return ChannelFormat.D
    return ChannelFormat.UNKNOWN


@dataclass(frozen=True, slots=True)
class ChannelInfo:
    """Everything needed to read and interpret one channel.

    Attributes:
        name: Channel name, identical to its table name.
        frequency: Sample rate in Hz from `channelsList`. NaN when the channel
            is an event (events are irregular by nature) or when the catalog
            does not list it.
        unit: Unit string exactly as the file declares it. Conversion to the
            application's canonical units is driven by this value, so it is kept
            verbatim rather than normalised here.
        fmt: Column layout (A/B/C/D).
        n_samples: Row count, used to derive the channel's implicit duration.
        value_sql_type: DuckDB type of the value column(s), which is what tells
            a discrete channel from a continuous one.
    """

    name: str
    frequency: float
    unit: str
    fmt: ChannelFormat
    n_samples: int
    value_sql_type: str = "FLOAT"

    @property
    def is_event(self) -> bool:
        return self.fmt.is_event

    @property
    def is_per_wheel(self) -> bool:
        return self.fmt.is_per_wheel

    @property
    def is_discrete(self) -> bool:
        """True when values must be forward-filled instead of interpolated.

        Events are always discrete in time (they are only written when
        something changes). Continuous channels are discrete when their column
        type is integral or boolean - see `DISCRETE_SQL_TYPES`.
        """
        return self.is_event or self.value_sql_type.upper() in DISCRETE_SQL_TYPES

    @property
    def has_usable_frequency(self) -> bool:
        """True when `t[i] = i / frequency` can actually be evaluated.

        Guards the division: a channel declaring 0, a negative rate or no rate
        at all would otherwise produce infinities that propagate through every
        alignment downstream.
        """
        return bool(np.isfinite(self.frequency)) and self.frequency > 0.0

    @property
    def implicit_duration_s(self) -> float:
        """Recording length implied by row count and declared frequency.

        `n_samples / frequency`: the total time the samples cover, one sample
        period per sample.
        """
        if not self.has_usable_frequency:
            return float("nan")
        return self.n_samples / self.frequency

    @property
    def implicit_span_s(self) -> float:
        """Time from the first sample to the last: `(n_samples - 1) / frequency`.

        This, not `implicit_duration_s`, is what compares against a clock's
        `last - first`. Mixing the two produces a phantom drift of exactly one
        sample period, which is easy to mistake for a real timing fault.
        """
        if not self.has_usable_frequency or self.n_samples < 2:
            return float("nan")
        return (self.n_samples - 1) / self.frequency

    def effective_frequency(self, reference_span_s: float) -> float:
        """Sample rate derived from the data instead of taken from the catalog.

        `channelsList.frequency` is an INTEGER column, so any channel whose true
        rate is not a whole number is stored truncated. Schema inspection of a
        real session found exactly that: two channels declared at 7 Hz are in
        fact sampled at 7.017 Hz. Believing the declared value puts those
        channels 3.6 s out of position by the end of a 24-minute recording,
        with nothing raising an error.

        Given the span of a reference clock (`GPS Time`) covering the same
        recording, the true rate follows from the sample count:

            f = (n_samples - 1) / reference_span

        Args:
            reference_span_s: Last minus first sample time of the reference
                clock, in seconds.

        Returns:
            The empirical rate, or the declared one when no usable reference is
            available.
        """
        if reference_span_s <= 0 or self.n_samples < 2:
            return self.frequency
        return (self.n_samples - 1) / reference_span_s


def _catalog_lookup(frame: pd.DataFrame, name_column: str) -> dict[str, dict[str, object]]:
    """Index a catalog table by channel name, tolerating missing columns."""
    if frame.empty or name_column not in frame.columns:
        return {}
    return {
        str(row[name_column]): dict(row)
        for _, row in frame.iterrows()
    }


def _to_float(value: object) -> float:
    """Coerce a catalog value to float, returning NaN instead of raising.

    `frequency` arrives from a column whose type we do not control; it has been
    seen as integer, float and string across schema variants. A bad value must
    degrade to NaN (caught later by `has_usable_frequency`) rather than abort
    the whole registry build.
    """
    if value is None:
        return float("nan")
    try:
        result = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return result if np.isfinite(result) else float("nan")


def build_registry(con: duckdb.DuckDBPyConnection) -> dict[str, ChannelInfo]:
    """Build the channel registry for an open session file.

    Walks every table in the file, skips the catalog tables, classifies the rest
    by their real columns, and enriches them with frequency and unit from
    `channelsList` / `eventsList`.

    Mismatches between the data tables and the catalog are logged, never fatal:
    a channel listed in the catalog with no table, or a table with no catalog
    entry, both happen and both are survivable.

    Returns:
        Mapping of channel name to `ChannelInfo`, excluding unrecognised tables.
    """
    catalog = duckdb_reader.read_catalog(con)
    channels_meta = _catalog_lookup(catalog["channelsList"], "channelName")
    events_meta = _catalog_lookup(catalog["eventsList"], "eventName")

    registry: dict[str, ChannelInfo] = {}
    data_tables = [
        t for t in duckdb_reader.list_tables(con)
        if t not in duckdb_reader.CATALOG_TABLES
    ]

    for table in data_tables:
        described = duckdb_reader.describe_table(con, table)
        columns = [name for name, _type in described]
        fmt = detect_format(columns)

        if fmt is ChannelFormat.UNKNOWN:
            logger.warning(
                strings.WARN_UNKNOWN_CHANNEL_FORMAT.format(
                    table=table, columns=", ".join(columns)
                )
            )
            continue

        # All value columns of a per-wheel channel share one type, so the first
        # is representative.
        types = dict(described)
        value_sql_type = str(types.get(fmt.value_columns[0], "FLOAT"))

        meta = channels_meta.get(table) or events_meta.get(table)
        if meta is None:
            logger.warning(strings.WARN_TABLE_WITHOUT_CATALOG.format(table=table))
            meta = {}

        registry[table] = ChannelInfo(
            name=table,
            # Events carry their own timestamps, so a declared frequency would
            # be meaningless for them even if the catalog provided one.
            frequency=float("nan") if fmt.is_event else _to_float(meta.get("frequency")),
            unit=str(meta.get("unit") or ""),
            fmt=fmt,
            n_samples=duckdb_reader.row_count(con, table),
            value_sql_type=value_sql_type,
        )

    for channel_name in set(channels_meta) | set(events_meta):
        if channel_name not in registry:
            logger.warning(
                strings.WARN_CHANNEL_WITHOUT_TABLE.format(channel=channel_name)
            )

    logger.info("Registry built: %d channels", len(registry))
    return registry


def read_channel(
    con: duckdb.DuckDBPyConnection,
    registry: dict[str, ChannelInfo],
    name: str,
) -> np.ndarray:
    """Read a channel's values, shaped according to its layout.

    Returns:
        Shape `(n,)` for layouts A and C, `(n, 4)` for B and D with columns in
        `WHEEL_ORDER`.

    Raises:
        ChannelNotFoundError: The channel is not recorded in this session. The
            caller is expected to catch this and disable the dependent feature.
    """
    info = registry.get(name)
    if info is None:
        raise ChannelNotFoundError(name)
    return duckdb_reader.read_columns(con, info.name, info.fmt.value_columns)


def read_event_timestamps(
    con: duckdb.DuckDBPyConnection,
    registry: dict[str, ChannelInfo],
    name: str,
) -> np.ndarray:
    """Read the `ts` column of an event channel (layouts C and D).

    Raises:
        ChannelNotFoundError: The channel is absent, or is not an event channel.
    """
    info = registry.get(name)
    if info is None or not info.is_event:
        raise ChannelNotFoundError(name)
    # float64 here, unlike channel values: timestamps accumulate over a whole
    # session and float32 would quantise them to ~1 ms after an hour of running.
    return duckdb_reader.read_columns(con, info.name, (TS_COLUMN,), dtype=np.float64)


def channels_by_format(
    registry: dict[str, ChannelInfo],
) -> dict[ChannelFormat, list[str]]:
    """Group channel names by layout. Used by reports and by the resampler."""
    grouped: dict[ChannelFormat, list[str]] = {fmt: [] for fmt in ChannelFormat}
    for info in registry.values():
        grouped[info.fmt].append(info.name)
    for names in grouped.values():
        names.sort()
    return grouped


def continuous_channels(registry: dict[str, ChannelInfo]) -> list[ChannelInfo]:
    """Return the continuous channels (layouts A and B), sorted by name."""
    return sorted(
        (info for info in registry.values() if not info.is_event),
        key=lambda info: info.name,
    )


def require(registry: dict[str, ChannelInfo], names: Sequence[str]) -> list[str]:
    """Return which of `names` are missing from the registry.

    Lets a feature check its prerequisites up front and disable itself with one
    clear message, instead of failing halfway through a computation.
    """
    return [name for name in names if name not in registry]
