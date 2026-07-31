"""Import sessions into the catalog, and show what the catalog knows.

Phase 3's visible deliverable. Import is manual, as the specification requires
for the MVP: files are named on the command line, nothing runs by itself.

Usage:
    python scripts/import_session.py "<file.duckdb>" [more files...]
    python scripts/import_session.py --folder "<UserData/Telemetry>"
    python scripts/import_session.py --show
    python scripts/import_session.py --clear-cache
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lmu_telemetry.core.errors import TelemetryError  # noqa: E402
from lmu_telemetry.logging_config import get_logger, setup_logging  # noqa: E402
from lmu_telemetry.storage import cache, catalog, importer, paths  # noqa: E402
from lmu_telemetry.ui import strings  # noqa: E402

logger = get_logger(__name__)
LINE_WIDTH = 92


def emit(text: str = "") -> None:
    print(text)


def force_utf8_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def format_lap_time(seconds: float | None) -> str:
    if seconds is None or seconds <= 0:
        return "   --    "
    minutes, remainder = divmod(seconds, 60.0)
    return f"{int(minutes)}:{remainder:06.3f}"


def header(title: str) -> None:
    emit()
    emit("=" * LINE_WIDTH)
    emit(title)
    emit("=" * LINE_WIDTH)


# --------------------------------------------------------------------------- #
# Importing
# --------------------------------------------------------------------------- #

def run_import(paths_to_import: list[Path], *, force: bool) -> int:
    header(strings.IMPORT_TITLE)

    results, failures = [], []
    # One catalog connection for the whole run: opening it per file dominated
    # the cost of re-importing a folder where everything is already cached.
    with catalog.connect() as con:
        for path in paths_to_import:
            try:
                result = importer.import_session_file(path, force=force, con=con)
                results.append(result)
                length = (
                    f"  pista {result.track_length_m:.0f} m"
                    if result.track_length_m else ""
                )
                emit(f"  {result.action:<12} {path.name}")
                emit(f"               {result.track_name} / {result.car_name or '?'}"
                     f"  ·  {result.n_laps} voltas{length}")
                for warning in result.warnings:
                    emit(f"               ! {warning}")
            except TelemetryError as exc:
                failures.append((path, str(exc)))
                emit(f"  {strings.IMPORT_FAILED.format(name=path.name, detail=exc)}")

    n_cached = sum(1 for r in results if r.was_cached)
    emit()
    emit("  " + strings.IMPORT_DONE.format(
        n_imported=len(results) - n_cached,
        n_cached=n_cached,
        n_failed=len(failures),
    ))
    return 0 if results or not paths_to_import else 1


# --------------------------------------------------------------------------- #
# Showing the catalog
# --------------------------------------------------------------------------- #

def show_catalog() -> int:
    header(strings.CATALOG_TITLE)
    emit(f"  {strings.CATALOG_LOCATION}: {paths.catalog_path()}")
    emit(f"  {strings.CATALOG_CACHE}: {paths.cache_dir()}  "
         f"({cache.cache_size_bytes() / 1024:.0f} KB)")

    with catalog.connect() as con:
        stats = catalog.statistics(con)
        emit()
        emit("  " + strings.CATALOG_STATS.format(**stats))

        if stats["sessions"] == 0:
            emit()
            emit(f"  {strings.CATALOG_EMPTY}")
            return 0

        emit()
        emit(f"  {strings.CATALOG_SECTION_TRACKS}")
        emit(f"  {'-' * (LINE_WIDTH - 4)}")
        for row in con.execute(
            """
            SELECT t.name, t.length_m, count(DISTINCT s.session_id)
            FROM tracks t LEFT JOIN sessions s ON s.track_id = t.track_id
            GROUP BY 1, 2 ORDER BY 1
            """
        ).fetchall():
            length = (f"{row[1]:>9.0f} m" if row[1]
                      else f"{strings.CATALOG_TRACK_LENGTH_UNKNOWN:>11}")
            emit(f"  {row[0]:<40}{length}   {row[2]} sessões")

        emit()
        emit(f"  {strings.CATALOG_SECTION_BEST}")
        emit(f"  {'-' * (LINE_WIDTH - 4)}")
        emit(f"  {'pista':<34}{'carro':<30}{'volta':>10}  "
             f"{'S1':>9}{'S2':>9}{'S3':>9}")
        for best in catalog.list_best_laps(con):
            car = (best["car_name"] or "?")[:28]
            emit(
                f"  {best['track_name'][:32]:<34}{car:<30}"
                f"{format_lap_time(best['time_s']):>10}  "
                f"{_sector(best['sector1_s'])}{_sector(best['sector2_s'])}"
                f"{_sector(best['sector3_s'])}"
            )

        emit()
        emit(f"  {strings.CATALOG_SECTION_SESSIONS}")
        emit(f"  {'-' * (LINE_WIDTH - 4)}")
        for session in catalog.list_sessions(con):
            emit(
                f"  {session.started_at:%Y-%m-%d %H:%M}  "
                f"{(session.session_type or '?'):<3}"
                f"{session.track_name[:30]:<32}"
                f"{(session.car_name or '?')[:26]:<28}"
                f"{session.n_laps:>3} voltas"
            )
    return 0


def _sector(seconds: float | None) -> str:
    # Nine wide: a Le Mans sector runs past 110 s, and at seven the columns ran
    # into each other.
    return "       --" if seconds is None else f"{seconds:9.3f}"


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Importa sessões do LMU para o catálogo histórico."
    )
    parser.add_argument("files", nargs="*", type=Path, help="Arquivos .duckdb")
    parser.add_argument("--folder", type=Path, default=None,
                        help="Importa todos os .duckdb de uma pasta.")
    parser.add_argument("--force", action="store_true",
                        help="Relê o arquivo mesmo havendo cache válido.")
    parser.add_argument("--show", action="store_true",
                        help="Mostra o conteúdo do catálogo.")
    parser.add_argument("--clear-cache", action="store_true",
                        help="Apaga todo o cache (o catálogo é preservado).")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    force_utf8_stdout()
    setup_logging(level=logging.INFO if args.verbose else logging.WARNING)

    if args.clear_cache:
        removed = cache.clear_all()
        emit(f"  Cache apagado: {removed} sessões.")
        return 0

    targets = list(args.files)
    if args.folder is not None:
        found = sorted(args.folder.glob("*.duckdb"))
        if not found:
            emit(f"  {strings.IMPORT_NOTHING_FOUND.format(folder=args.folder)}")
            return 1
        targets.extend(found)

    status = 0
    if targets:
        status = run_import(targets, force=args.force)
    if args.show or not targets:
        status = show_catalog() or status

    return status


if __name__ == "__main__":
    raise SystemExit(main())
