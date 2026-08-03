"""Export a lap without opening the interface.

    python scripts/export_session.py "session.duckdb" --lap 8 --out out/

Writes the charts, the CSVs and the PDF debrief for one lap, comparing it
against the session's own best lap. Runs headless: nothing here imports Qt, so
it works over SSH and in CI.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lmu_telemetry import pipeline  # noqa: E402
from lmu_telemetry.core.errors import SessionNameError, TelemetryError  # noqa: E402
from lmu_telemetry.core.models import parse_session_filename  # noqa: E402
from lmu_telemetry.export import charts, report, tables  # noqa: E402
from lmu_telemetry.ingest.session_loader import load_session  # noqa: E402
from lmu_telemetry.logging_config import setup_logging  # noqa: E402
from lmu_telemetry.storage import catalog  # noqa: E402
from lmu_telemetry.ui import strings  # noqa: E402
from lmu_telemetry.ui.formatting import format_gap, format_lap_time  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session", type=Path)
    parser.add_argument("--lap", type=int, default=None,
                        help="Lap index (default: the session's best)")
    parser.add_argument("--out", type=Path, default=Path("out"))
    parser.add_argument("--excel", action="store_true",
                        help="Write CSVs for a Portuguese-locale Excel")
    arguments = parser.parse_args(argv)

    setup_logging()
    arguments.out.mkdir(parents=True, exist_ok=True)
    dialect = tables.EXCEL_PT_BR if arguments.excel else tables.STANDARD

    try:
        session = load_session(arguments.session, with_hash=False)
    except TelemetryError as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 1

    try:
        return _export(session, arguments, dialect)
    finally:
        session.close()


def _export(session, arguments, dialect) -> int:
    track_length = None
    try:
        with catalog.connect() as con:
            track_length = catalog.track_length(con, session.info.track_name)
    except Exception:  # noqa: BLE001 - the catalog is optional here
        pass

    analysis = pipeline.analyse_session(session, track_length)
    if not analysis.laps:
        print(strings.CHART_NO_DATA, file=sys.stderr)
        return 1

    lap_index = arguments.lap
    if lap_index is None:
        lap_index = analysis.best_lap_index
    if lap_index not in analysis.laps:
        print(f"ERRO: volta {lap_index} não analisável. "
              f"Disponíveis: {sorted(analysis.laps)}", file=sys.stderr)
        return 1

    primary = analysis.laps[lap_index]
    benchmark = _benchmark(analysis, lap_index)
    delta = None if benchmark is None else pipeline.delta_between(benchmark, primary)

    stem = arguments.out / f"volta{primary.lap.number}"
    primary_label = strings.CHART_LEGEND_PRIMARY.format(
        number=primary.lap.number, time=format_lap_time(primary.time_s)
    )
    benchmark_label = "" if benchmark is None else (
        strings.CHART_LEGEND_BENCHMARK.format(
            number=benchmark.lap.number,
            time=format_lap_time(benchmark.time_s),
            gap=format_gap(delta.final_delta_s),
        )
    )

    written = [
        charts.export_lap_charts(
            stem.with_suffix(".png"), primary, primary_label,
            benchmark, benchmark_label, delta, primary.corners,
        ),
        tables.write_lap(stem.with_suffix(".csv"), primary, delta, dialect),
        tables.write_corners(
            Path(f"{stem}-curvas.csv"),
            pipeline.corner_rows(primary, benchmark, analysis.ideal),
            dialect,
        ),
    ]

    stint = analysis.stint_of(lap_index)
    if stint is not None and stint.report is not None and stint.report.is_measurable:
        written.append(tables.write_consistency(
            Path(f"{stem}-consistencia.csv"), stint.report, dialect
        ))

    written.append(report.write_report(
        stem.with_suffix(".pdf"),
        _context(session, analysis, primary, primary_label,
                 benchmark, benchmark_label, delta, stint),
    ))

    for path in written:
        print(strings.STATUS_EXPORTED.format(path=path))
    return 0


def _benchmark(analysis, lap_index: int):
    """The session's best other lap, which is what a debrief compares against."""
    others = [i for i in analysis.laps if i != lap_index]
    if not others:
        return None
    return analysis.laps[min(others, key=lambda i: analysis.laps[i].time_s)]


def _context(session, analysis, primary, primary_label,
             benchmark, benchmark_label, delta, stint) -> report.ReportContext:
    gps, _integrated = pipeline.track_paths(primary)
    track_path = None if gps is None or not len(gps.x_m) else (gps.x_m, gps.y_m)

    map_classes = map_colours = None
    if track_path is not None:
        if delta is not None:
            map_classes = pipeline.loss_classes_on(primary.grid_m, delta)
            map_colours = charts.LOSS_COLOURS
        else:
            map_classes = pipeline.pedal_states(primary)
            map_colours = charts.PEDAL_COLOURS

    try:
        _track, code, _when = parse_session_filename(session.info.path)
    except SessionNameError:
        code = session.info.session_type_code

    return report.ReportContext(
        track_name=session.info.track_name,
        car_name=session.info.car_name or "?",
        session_label=strings.session_type_label(code or "?"),
        session_date=session.info.started_at,
        lap_number=primary.lap.number,
        primary=primary,
        primary_label=primary_label,
        benchmark=benchmark,
        benchmark_label=benchmark_label,
        benchmark_summary="" if benchmark is None else (
            strings.STATUS_REFERENCE_LAP.format(number=benchmark.lap.number)
            + " · " + format_lap_time(benchmark.time_s)
        ),
        delta=delta,
        corner_rows=pipeline.corner_rows(primary, benchmark, analysis.ideal),
        ideal=analysis.ideal,
        consistency=None if stint is None else stint.report,
        envelope=pipeline.friction_envelope(primary),
        transition_quality=pipeline.transition_quality(primary),
        track_path=track_path,
        map_classes=map_classes,
        map_colours=map_colours,
    )


if __name__ == "__main__":
    raise SystemExit(main())
