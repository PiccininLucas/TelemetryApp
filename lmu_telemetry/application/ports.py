"""What the application layer needs from a loaded session.

The pipeline analyses a session; it does not care that today the data comes out
of a DuckDB file. It states what it uses here, and `infrastructure.ingest`'s
`Session` satisfies it structurally - nothing there inherits from this module,
so the dependency still points inward.

That is also what would let a live data source feed the same pipeline later.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

import numpy as np

from lmu_telemetry.domain.models import Lap


class ChannelMeta(Protocol):
    """The one thing the pipeline asks of a channel's description."""

    @property
    def is_discrete(self) -> bool: ...


class SessionData(Protocol):
    """A loaded session, as the pipeline reads it."""

    @property
    def laps(self) -> list[Lap]: ...

    @property
    def comparable_laps(self) -> list[Lap]: ...

    @property
    def registry(self) -> Mapping[str, ChannelMeta]: ...

    def has(self, *names: str) -> bool: ...

    def series(self, name: str) -> tuple[np.ndarray, np.ndarray]: ...

    def acceleration_series(self, quantity: str) -> tuple[np.ndarray, np.ndarray]: ...
