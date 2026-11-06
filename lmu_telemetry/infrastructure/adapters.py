"""Implementations of the gateways in `application.ports`.

Thin by design: each method forwards to the storage, ingestion or export module
that already does the work, so the interface can depend on the port instead of
on any of them. Nothing here inherits from the ports - they are satisfied
structurally, which keeps the dependency pointing inward.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import duckdb

from lmu_telemetry.application.ports import Gateways
from lmu_telemetry.application.reporting import ReportContext
from lmu_telemetry.domain.records import CornerReference, LapRow, SessionRow
from lmu_telemetry.infrastructure.export import charts, report, tables
from lmu_telemetry.infrastructure.ingest.session_loader import Session, load_session
from lmu_telemetry.infrastructure.storage import catalog, importer


class DuckDbCatalog:
    """The catalog, opened afresh for each operation.

    A connection per call mirrors how the interface used the catalog before:
    short reads and one write, never a connection held across user actions.
    """

    def name_match_tolerance_m(self) -> float:
        return catalog.name_match_tolerance_m()

    def list_sessions(self) -> tuple[list[SessionRow], dict[str, list[LapRow]]]:
        with catalog.connect() as con:
            sessions = catalog.list_sessions(con)
            laps = {s.session_id: catalog.list_laps(con, s.session_id) for s in sessions}
        return sessions, laps

    def track_length(self, track_name: str) -> float | None:
        with catalog.connect() as con:
            return catalog.track_length(con, track_name)

    def corner_references(self, track_name: str) -> list[CornerReference]:
        with catalog.connect() as con:
            return catalog.corner_references(con, track_name)

    def set_corner_name(
        self, track_name: str, corner_index: int, name: str, distance_m: float
    ) -> None:
        with catalog.connect() as con:
            catalog.set_corner_name(
                con, catalog.track_id_for(track_name), corner_index, name, distance_m
            )


class FileSessionLoader:
    """Opens a session file read-only, without hashing it."""

    def load(self, path: Path) -> Session:
        return load_session(path, with_hash=False)


class _ImportSession:
    def __init__(self, con: duckdb.DuckDBPyConnection) -> None:
        self._con = con

    def import_file(self, path: Path) -> object:
        return importer.import_session_file(path, con=self._con)


class DuckDbSessionImporter:
    """Imports into the catalog, one connection for a whole batch.

    The connection is opened inside `open()`, on whichever thread calls it: a
    DuckDB connection cannot be shared between threads, and the import runs on
    a worker.
    """

    @contextmanager
    def open(self) -> Iterator[_ImportSession]:
        with catalog.connect() as con:
            yield _ImportSession(con)


class FileExporter:
    """Writes PNG, CSV and PDF."""

    def lap_charts(self, path, primary, primary_label, benchmark, benchmark_label,
                   delta, corners) -> Path:
        return charts.export_lap_charts(
            path, primary, primary_label, benchmark, benchmark_label, delta, corners
        )

    def lap_table(self, path, primary, delta, *, excel: bool) -> Path:
        return tables.write_lap(path, primary, delta, _dialect(excel))

    def corner_table(self, path, rows, *, excel: bool) -> Path:
        return tables.write_corners(path, rows, _dialect(excel))

    def report(self, path, context: ReportContext) -> Path:
        return report.write_report(path, context)


def _dialect(excel: bool) -> tables.CsvDialect:
    return tables.EXCEL_PT_BR if excel else tables.STANDARD


def build_gateways() -> Gateways:
    """The production wiring."""
    return Gateways(
        catalog=DuckDbCatalog(),
        sessions=FileSessionLoader(),
        importer=DuckDbSessionImporter(),
        exporter=FileExporter(),
    )
