"""Event channels: irregular samples turned into step series.

Event tables (layouts C and D) carry their own `ts` column and are written only
when the value changes. `Gear` has 670 rows for a 24-minute session; `In Pits`
often has one.

Their `ts` shares the session clock with `GPS Time` exactly - both start at the
same instant in every file inspected - so no offset is applied anywhere.

Events are never interpolated. Halfway between gear 3 and gear 4 there is no
gear 3.5, and halfway between "on track" and "in pits" there is no half-pit.
They are forward-filled: a value holds until the next event replaces it, which
is exactly what the recording means.
"""

from __future__ import annotations

from dataclasses import dataclass

import duckdb
import numpy as np

from lmu_telemetry.core.errors import ChannelNotFoundError
from lmu_telemetry.ingest import duckdb_reader
from lmu_telemetry.ingest.channel_registry import TS_COLUMN, ChannelInfo
from lmu_telemetry.ingest.time_base import step_interpolate
from lmu_telemetry.logging_config import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class EventSeries:
    """An event channel's samples.

    Attributes:
        name: Channel name.
        times: Event timestamps, float64, ascending. On the session clock.
        values: Shape `(n,)` for layout C, `(n, 4)` for layout D.
    """

    name: str
    times: np.ndarray
    values: np.ndarray

    def __len__(self) -> int:
        return len(self.times)

    @property
    def is_empty(self) -> bool:
        return len(self.times) == 0

    @property
    def is_constant(self) -> bool:
        """True when the channel never changed during the recording.

        Worth knowing rather than an oddity: `In Pits` is constant in every race
        session where the driver did not pit, which means stint detection has
        nothing to detect and must fall back to treating the session as one
        stint instead of returning nothing.
        """
        if self.is_empty:
            return True
        return bool(np.all(self.values == self.values[0]))

    def value_at(self, t: float | np.ndarray) -> np.ndarray:
        """Value in force at time `t`, forward-filled.

        Times before the first event yield NaN: the recording says nothing
        about them.
        """
        query = np.atleast_1d(np.asarray(t, dtype=np.float64))
        if self.values.ndim == 2:
            columns = [
                step_interpolate(self.values[:, i], self.times, query)
                for i in range(self.values.shape[1])
            ]
            return np.column_stack(columns)
        return step_interpolate(self.values, self.times, query)

    def transitions(self, to_value: float) -> np.ndarray:
        """Times at which the value changes *to* `to_value`.

        The building block for pit detection: `In Pits` going 0 -> 1 is an
        entry, 1 -> 0 is an exit. Only genuine changes count, so a repeated
        sample of the same value is not a transition.
        """
        if self.is_empty or self.values.ndim != 1:
            return np.empty(0, dtype=np.float64)

        is_target = self.values == to_value
        # A transition is a target sample whose predecessor was not the target.
        # The first sample counts only if it is already the target and there is
        # no earlier state to compare against.
        changed = np.empty(len(self.values), dtype=bool)
        changed[0] = bool(is_target[0])
        changed[1:] = is_target[1:] & ~is_target[:-1]
        return self.times[changed]


def read_event_series(
    con: duckdb.DuckDBPyConnection,
    registry: dict[str, ChannelInfo],
    name: str,
) -> EventSeries:
    """Read an event channel.

    Raises:
        ChannelNotFoundError: The channel is absent, or is not an event channel.
    """
    info = registry.get(name)
    if info is None or not info.is_event:
        raise ChannelNotFoundError(name)

    columns = (TS_COLUMN, *info.fmt.value_columns)
    # float64 throughout: `ts` accumulates across the session, and the value
    # columns are small integers that float64 represents exactly.
    data = duckdb_reader.read_columns(con, info.name, columns, dtype=np.float64)

    if data.ndim == 1:  # a single row collapses to 1-D
        data = data.reshape(1, -1)

    times = data[:, 0]
    values = data[:, 1] if len(columns) == 2 else data[:, 1:]

    # The reader deliberately does not sort - for continuous channels row order
    # is time order and imposing an order would corrupt it. Event tables do
    # have a time column, and nothing guarantees the file wrote them sorted.
    order = np.argsort(times, kind="stable")
    if not np.array_equal(order, np.arange(len(times))):
        logger.debug("Event channel %r was not stored in time order", name)
        times, values = times[order], values[order]

    return EventSeries(name=name, times=times, values=values)


def try_read_event_series(
    con: duckdb.DuckDBPyConnection,
    registry: dict[str, ChannelInfo],
    name: str,
) -> EventSeries | None:
    """Read an event channel, or return None when it is not recorded.

    For features that can degrade gracefully: the caller disables one thing and
    carries on rather than failing the whole session load.
    """
    try:
        return read_event_series(con, registry, name)
    except ChannelNotFoundError:
        logger.info("Event channel %r not recorded in this session", name)
        return None
