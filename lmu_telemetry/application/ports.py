"""What the inner layers ask of the outside world.

Two kinds of port live here, both satisfied structurally by classes in
`infrastructure` - nothing there inherits from this module, so the dependency
still points inward:

- `SessionData`, what the pipeline needs from a loaded session. The pipeline
  does not care that today the data comes out of a DuckDB file, which is also
  what would let a live data source feed it later.
- The gateways the interface works through (`CatalogGateway`, `SessionLoader`,
  `SessionImporter`, `Exporter`, gathered in `Gateways`). The interface is handed
  them by `composition.py`, so it never imports storage, ingestion or export.
"""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

import numpy as np

from lmu_telemetry.domain.models import Lap
from lmu_telemetry.domain.records import CornerReference, LapRow, SessionRow

if TYPE_CHECKING:
    from lmu_telemetry.application import pipeline
    from lmu_telemetry.application.reporting import ReportContext


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


class OpenedSession(SessionData, Protocol):
    """A session the interface holds open: it also owns its handle and carries
    the notes the loader raised."""

    @property
    def warnings(self) -> list[str]: ...

    def close(self) -> None: ...


class CatalogGateway(Protocol):
    """The history of imported sessions, and the corner names kept per track."""

    def name_match_tolerance_m(self) -> float:
        """How far apart two names for the same corner may be placed."""
        ...

    def list_sessions(self) -> tuple[list[SessionRow], dict[str, list[LapRow]]]:
        """Every session, and each one's laps by session id.

        Raises:
            Exception: The catalog cannot be read; the caller decides how to
                degrade.
        """
        ...

    def track_length(self, track_name: str) -> float | None: ...

    def corner_references(self, track_name: str) -> list[CornerReference]: ...

    def set_corner_name(
        self, track_name: str, corner_index: int, name: str, distance_m: float
    ) -> None: ...


class SessionLoader(Protocol):
    """Opens a session file for analysis."""

    def load(self, path: Path) -> OpenedSession:
        """Raises TelemetryError when the file cannot be read."""
        ...


class ImportSession(Protocol):
    """One batch of imports sharing a connection."""

    def import_file(self, path: Path) -> object: ...


class SessionImporter(Protocol):
    """Reads session files into the cache and the catalog."""

    def open(self) -> AbstractContextManager[ImportSession]: ...


class Exporter(Protocol):
    """Writes what is on screen to files."""

    def lap_charts(
        self,
        path: Path,
        primary: pipeline.LapAnalysis,
        primary_label: str,
        benchmark: pipeline.LapAnalysis | None,
        benchmark_label: str,
        delta: object,
        corners: list,
    ) -> Path: ...

    def lap_table(
        self, path: Path, primary: pipeline.LapAnalysis, delta: object, *, excel: bool
    ) -> Path: ...

    def corner_table(self, path: Path, rows: list, *, excel: bool) -> Path: ...

    def report(self, path: Path, context: ReportContext) -> Path: ...


@dataclass(frozen=True, slots=True)
class Gateways:
    """Everything the interface needs from the outside, in one hand-off."""

    catalog: CatalogGateway
    sessions: SessionLoader
    importer: SessionImporter
    exporter: Exporter
