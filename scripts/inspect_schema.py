"""Verify the real schema of a Le Mans Ultimate session file.

Run this before trusting anything else in the project. The documented schema
(specification section 1) was obtained by inspecting the file's bytes, not by
querying it, and the entire ingestion layer rests on one assumption from that
inspection: continuous channels have no time column, so `t[i] = i / frequency`.
If that is wrong, every lap comparison built on top of it is wrong too, and
nothing would raise an error.

The report answers six questions:

    1. What tables and columns actually exist?
    2. What do the catalog tables say?
    3. Which of the four layouts does each table have?
    4. Where does that differ from the specification?
    5. Is the catalog self-consistent with the data tables?
    6. Do the implicit durations agree, and do they match the GPS clock?

Usage:
    python scripts/inspect_schema.py "<file.duckdb>" [more files...] [--json out.json]

Report text goes to stdout (that is the product of this script), while
diagnostics go through `logging` to stderr, so the report can be redirected to a
file without warnings contaminating it.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

# Allow running as `python scripts/inspect_schema.py` from the project root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import duckdb  # noqa: E402
import numpy as np  # noqa: E402

from lmu_telemetry.core import models, units  # noqa: E402
from lmu_telemetry.core.errors import TelemetryError  # noqa: E402
from lmu_telemetry.ingest import channel_registry, duckdb_reader  # noqa: E402
from lmu_telemetry.ingest.channel_registry import ChannelFormat  # noqa: E402
from lmu_telemetry.logging_config import get_logger, setup_logging  # noqa: E402
from lmu_telemetry.ui import strings  # noqa: E402
from scripts import expected_schema  # noqa: E402

logger = get_logger(__name__)

LINE_WIDTH = 88

#: Two continuous channels are considered to agree on duration when they differ
#: by less than this. One sample of the slowest plausible channel (~1 Hz) is the
#: natural floor; anything larger is a real inconsistency, not rounding.
DURATION_TOLERANCE_S = 1.0


# --------------------------------------------------------------------------- #
# Output helpers. These write the report itself, which is why they use stdout
# directly rather than `logging` - the report is data, not a diagnostic.
# --------------------------------------------------------------------------- #

def emit(text: str = "") -> None:
    print(text)


def _force_utf8_stdout() -> None:
    """Make the report readable when redirected to a file on Windows.

    Without this the report is written in the console code page (cp1252 here),
    which mangles every accented character in the Portuguese output the moment
    stdout is not a terminal.
    """
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def header(title: str, char: str = "=") -> None:
    emit()
    emit(char * LINE_WIDTH)
    emit(title)
    emit(char * LINE_WIDTH)


def subheader(title: str) -> None:
    emit()
    emit(title)
    emit("-" * len(title))


def bullet_list(items: list[str], indent: str = "  ") -> None:
    for item in sorted(items):
        emit(f"{indent}- {item}")


# --------------------------------------------------------------------------- #
# Report sections
# --------------------------------------------------------------------------- #

def report_tables(
    con: duckdb.DuckDBPyConnection,
    tables: list[str],
) -> dict[str, list[tuple[str, str]]]:
    """Section 1: every table with its columns, types and row count."""
    header(strings.INSPECT_SECTION_TABLES)

    schemas: dict[str, list[tuple[str, str]]] = {}
    for table in tables:
        columns = duckdb_reader.describe_table(con, table)
        schemas[table] = columns
        n_rows = duckdb_reader.row_count(con, table)
        column_text = ", ".join(f"{name} {ctype}" for name, ctype in columns)
        emit(f"  {table:<28} {n_rows:>9,} linhas   ({column_text})")

    return schemas


def report_catalog(con: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    """Section 2: the catalog tables in full. They are small enough to dump."""
    header(strings.INSPECT_SECTION_CATALOG)
    catalog = duckdb_reader.read_catalog(con)

    for name, frame in catalog.items():
        subheader(f"{name}  ({len(frame)} linhas)")
        # to_string keeps every row; the catalogs run to ~100 rows at most.
        emit(frame.to_string(index=False, max_colwidth=40))

    return catalog


def report_formats(
    schemas: dict[str, list[tuple[str, str]]],
) -> dict[str, ChannelFormat]:
    """Section 3: classify every non-catalog table by its real column set."""
    header(strings.INSPECT_SECTION_FORMATS)

    formats: dict[str, ChannelFormat] = {}
    for table, columns in schemas.items():
        if table in duckdb_reader.CATALOG_TABLES:
            continue
        formats[table] = channel_registry.detect_format(name for name, _ in columns)

    counts = Counter(formats.values())
    for fmt in ChannelFormat:
        label = strings.FORMAT_LABEL[fmt.value]
        emit(f"  {label:<42} {counts.get(fmt, 0):>3} tabelas")

    by_format: dict[ChannelFormat, list[str]] = defaultdict(list)
    for table, fmt in formats.items():
        by_format[fmt].append(table)

    for fmt in ChannelFormat:
        if by_format[fmt]:
            subheader(strings.FORMAT_LABEL[fmt.value])
            bullet_list(by_format[fmt])

    return formats


def report_divergence(formats: dict[str, ChannelFormat]) -> dict[str, Any]:
    """Section 4: how the real file differs from the documented schema.

    Divergence is reported, never worked around silently. Three kinds matter:
    a documented channel that is absent (some feature has to be dropped), an
    undocumented channel that exists (a capability nobody planned for), and a
    channel whose layout differs (would be read with the wrong columns).
    """
    header(strings.INSPECT_SECTION_DIVERGENCE)

    actual = {name: fmt.value for name, fmt in formats.items()}
    expected = expected_schema.EXPECTED_BY_CHANNEL

    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    wrong_format = sorted(
        (name, expected[name], actual[name])
        for name in set(expected) & set(actual)
        if expected[name] != actual[name]
    )
    unknown = sorted(name for name, fmt in actual.items() if fmt == "UNKNOWN")
    surprises = sorted(set(actual) & expected_schema.DOCUMENTED_ABSENT)

    if not (missing or extra or wrong_format or unknown):
        emit(f"  {strings.INSPECT_NO_DIVERGENCE}")

    if missing:
        subheader(strings.INSPECT_MISSING_TABLES.format(count=len(missing)))
        bullet_list([f"{name}  (esperado formato {expected[name]})" for name in missing])

    if extra:
        subheader(strings.INSPECT_EXTRA_TABLES.format(count=len(extra)))
        bullet_list([f"{name}  (formato real {actual[name]})" for name in extra])

    if wrong_format:
        subheader(strings.INSPECT_WRONG_FORMAT.format(count=len(wrong_format)))
        bullet_list([f"{n}: esperado {e}, real {a}" for n, e, a in wrong_format])

    if unknown:
        subheader(strings.INSPECT_UNKNOWN_FORMAT.format(count=len(unknown)))
        bullet_list(unknown)

    if surprises:
        subheader("Canais documentados como AUSENTES que na verdade existem")
        bullet_list(surprises)

    return {
        "missing": missing,
        "extra": extra,
        "wrong_format": [
            {"channel": n, "expected": e, "actual": a} for n, e, a in wrong_format
        ],
        "unknown_format": unknown,
        "unexpectedly_present": surprises,
    }


def report_coherence(
    catalog: dict[str, Any],
    formats: dict[str, ChannelFormat],
) -> dict[str, Any]:
    """Section 5: is the catalog consistent with the data tables?"""
    header(strings.INSPECT_SECTION_COHERENCE)

    channels = catalog["channelsList"]
    events = catalog["eventsList"]

    catalog_names: set[str] = set()
    if "channelName" in channels.columns:
        catalog_names |= {str(v) for v in channels["channelName"]}
    if "eventName" in events.columns:
        catalog_names |= {str(v) for v in events["eventName"]}

    table_names = set(formats)
    without_table = sorted(catalog_names - table_names)
    without_catalog = sorted(table_names - catalog_names)

    emit(f"  Canais no catálogo: {len(catalog_names)}   "
         f"Tabelas de dados: {len(table_names)}")

    if without_table:
        subheader(f"No catálogo mas SEM tabela de dados ({len(without_table)})")
        bullet_list(without_table)
    else:
        emit(f"  {strings.INSPECT_ALL_CHANNELS_HAVE_TABLE}")

    if without_catalog:
        subheader(f"Com tabela mas AUSENTES do catálogo ({len(without_catalog)})")
        bullet_list(without_catalog)
    else:
        emit(f"  {strings.INSPECT_ALL_TABLES_IN_CATALOG}")

    # Distinct units and frequencies. The units drive core/units.py, so knowing
    # exactly which spellings appear is what stops that module from guessing.
    # Both catalogs are scanned: eventsList declares units the channel catalog
    # never uses (e.g. "On/Off"), and an unrecognised one there would warn just
    # as loudly at ingestion time.
    unit_values: set[str] = set()
    for frame in (channels, events):
        if "unit" in frame.columns:
            unit_values |= {str(v) for v in frame["unit"]}
    raw_units = sorted(unit_values)
    subheader(f"{strings.INSPECT_DISTINCT_UNITS} ({len(raw_units)})")
    for unit in raw_units:
        spec = units.lookup(unit)
        status = (
            f"-> {spec.canonical}" + ("" if spec.is_identity else
                                      f"  (x{spec.factor:g}, +{spec.offset:g})")
            if spec is not None
            else "-> NÃO RECONHECIDA (passará sem conversão)"
        )
        emit(f"  {unit!r:<18} {status}")

    frequencies = (
        sorted({float(v) for v in channels["frequency"]})
        if "frequency" in channels.columns
        else []
    )
    subheader(f"{strings.INSPECT_DISTINCT_FREQUENCIES} ({len(frequencies)})")
    emit("  " + ", ".join(f"{f:g} Hz" for f in frequencies))

    invalid = [f for f in frequencies if not (np.isfinite(f) and f > 0)]
    if invalid:
        emit(f"  ATENÇÃO: frequências inválidas encontradas: {invalid}")

    return {
        "catalog_without_table": without_table,
        "table_without_catalog": without_catalog,
        "units": raw_units,
        "unrecognised_units": [u for u in raw_units if units.lookup(u) is None],
        "frequencies": frequencies,
    }


def report_time_base(
    con: duckdb.DuckDBPyConnection,
    registry: dict[str, channel_registry.ChannelInfo],
) -> dict[str, Any]:
    """Section 6: does `t[i] = i / frequency` hold?

    Two independent checks.

    First, internal consistency: every continuous channel implies a recording
    length of `n_samples / frequency`. They all describe the same recording, so
    they must agree. If a 100 Hz channel implies 600 s while a 10 Hz channel
    implies 540 s, then row count and time are not related the way we assume.

    Second, against a real clock: `GPS Time` is a continuous channel carrying an
    actual timestamp. Its span must match the duration implied by its own row
    count and frequency. This is the same comparison `ingest/time_base.py` will
    do sample by sample in phase 2 - here it is only a coarse go/no-go.
    """
    header(strings.INSPECT_SECTION_TIMEBASE)

    continuous = channel_registry.continuous_channels(registry)
    durations = {
        info.name: info.implicit_duration_s
        for info in continuous
        if info.has_usable_frequency
    }

    no_frequency = [
        info.name for info in continuous if not info.has_usable_frequency
    ]
    if no_frequency:
        subheader(f"Canais contínuos SEM frequência utilizável ({len(no_frequency)})")
        bullet_list(no_frequency)

    result: dict[str, Any] = {
        "duration_min_s": None,
        "duration_max_s": None,
        "duration_spread_s": None,
        "consistent": None,
        "channels_without_frequency": no_frequency,
    }

    if durations:
        values = np.array(list(durations.values()))
        d_min, d_max = float(values.min()), float(values.max())
        spread = d_max - d_min
        consistent = spread <= DURATION_TOLERANCE_S

        emit(f"  Duração implícita (n_amostras / frequência):")
        emit(f"    mínima  {d_min:9.3f} s   ({min(durations, key=durations.get)})")
        emit(f"    máxima  {d_max:9.3f} s   ({max(durations, key=durations.get)})")
        emit(f"    espalhamento {spread:.3f} s "
             f"(tolerância {DURATION_TOLERANCE_S:.1f} s)")
        emit()
        emit("  " + (strings.INSPECT_DURATION_CONSISTENT if consistent
                     else strings.INSPECT_DURATION_INCONSISTENT))

        if not consistent:
            subheader("Durações por canal (as 10 mais discrepantes)")
            median = float(np.median(values))
            worst = sorted(durations.items(), key=lambda kv: -abs(kv[1] - median))[:10]
            for name, duration in worst:
                emit(f"  {name:<28} {duration:9.3f} s   "
                     f"(desvio {duration - median:+.3f} s)")

        result.update(
            duration_min_s=d_min,
            duration_max_s=d_max,
            duration_spread_s=spread,
            consistent=consistent,
        )

    # --- cross-check against the GPS clock ---------------------------------
    subheader("Confronto com o relógio GPS")
    gps = registry.get("GPS Time")
    if gps is None:
        emit(f"  {strings.INSPECT_GPS_TIME_MISSING}")
        result["gps_time"] = None
        return result

    values = duckdb_reader.read_columns(
        con, gps.name, (channel_registry.VALUE_COLUMN,), dtype=np.float64
    )
    finite = values[np.isfinite(values)]
    if finite.size < 2:
        emit("  GPS Time presente mas sem amostras utilizáveis.")
        result["gps_time"] = None
        return result

    observed_span = float(finite[-1] - finite[0])
    # Compare span against span. `implicit_duration_s` (n/f) counts one sample
    # period more than the first-to-last interval, and comparing it to a clock
    # span manufactures a phantom drift of exactly one sample period.
    implicit_span = gps.implicit_span_s

    emit(f"  {strings.INSPECT_GPS_TIME_RANGE}: "
         f"{finite[0]:.3f} .. {finite[-1]:.3f}  (span {observed_span:.3f} s)")
    emit(f"  Amostras: {gps.n_samples:,}   frequência declarada: {gps.frequency:g} Hz")
    emit(f"  Span implícito ((n-1)/f): {implicit_span:.3f} s")

    # A monotonic clock with a constant step is what makes GPS Time usable as a
    # reference at all. A varying step would mean the game stalled, which is the
    # exact failure the whole check exists to catch.
    diffs = np.diff(finite)
    n_backwards = int((diffs < 0).sum())
    emit(f"  Monotônico: "
         f"{'sim' if n_backwards == 0 else f'NÃO ({n_backwards} saltos para trás)'}")

    step_constant = None
    if diffs.size:
        step_median = float(np.median(diffs))
        step_min, step_max = float(diffs.min()), float(diffs.max())
        step_constant = (step_max - step_min) < 1e-6
        emit(f"  Passo entre amostras: mediana {step_median:.6f} s, "
             f"mín {step_min:.6f}, máx {step_max:.6f}")
        emit(f"  Passo constante: {'sim' if step_constant else 'NÃO'}")
        if not step_constant:
            n_gaps = int((diffs > 1.5 * step_median).sum())
            emit(f"  ATENÇÃO: {n_gaps} intervalo(s) acima de 1,5x o passo mediano. "
                 "Houve pausa ou travamento durante a gravação; a correção da "
                 "base de tempo da fase 2 é obrigatória nesta sessão.")

    drift = None
    if np.isfinite(implicit_span) and implicit_span > 0:
        drift = observed_span - implicit_span
        emit(f"  Deriva (span observado - span implícito): {drift:+.4f} s")
        if abs(drift) > DURATION_TOLERANCE_S:
            emit("  ATENÇÃO: a base de tempo por índice diverge do relógio GPS.")
        result["gps_drift_s"] = drift

    result["gps_time"] = {
        "span_s": observed_span,
        "implicit_span_s": implicit_span,
        "n_samples": gps.n_samples,
        "frequency": gps.frequency,
        "monotonic": n_backwards == 0,
        "step_constant": step_constant,
        "drift_s": drift,
    }

    report_frequencies(registry, observed_span)
    result["frequency_check"] = _frequency_table(registry, observed_span)
    return result


#: A declared frequency is considered exact when it is within this relative
#: distance of the empirical rate. 0.1% over a 1400 s session is ~1.4 s of
#: accumulated position error, which is already visible when locating a braking
#: point, so the bar is deliberately tight.
FREQUENCY_TOLERANCE_REL = 0.001


def _frequency_table(
    registry: dict[str, channel_registry.ChannelInfo],
    reference_span_s: float,
) -> list[dict[str, Any]]:
    """Declared vs empirical sample rate for every continuous channel."""
    rows = []
    for info in channel_registry.continuous_channels(registry):
        if info.n_samples < 2:
            continue
        effective = info.effective_frequency(reference_span_s)
        declared = info.frequency
        relative = (
            abs(effective - declared) / effective if effective > 0 else float("nan")
        )
        rows.append({
            "channel": info.name,
            "declared_hz": declared,
            "effective_hz": effective,
            "relative_error": relative,
            "n_samples": info.n_samples,
        })
    return rows


def report_frequencies(
    registry: dict[str, channel_registry.ChannelInfo],
    reference_span_s: float,
) -> None:
    """Section 7: is the catalog's declared frequency usable as-is?

    `channelsList.frequency` is an INTEGER column. A channel whose real rate is
    not a whole number is therefore stored truncated, and rebuilding its time
    base from the declared value drifts it linearly across the session with no
    error raised anywhere. The empirical rate `(n-1) / reference_span` is exact
    by construction, so the two are compared here and the ingestion layer is
    expected to prefer the empirical one.
    """
    header(strings.INSPECT_SECTION_FREQUENCY)

    rows = _frequency_table(registry, reference_span_s)
    truncated = [r for r in rows if r["relative_error"] > FREQUENCY_TOLERANCE_REL]

    emit(f"  Referência: span do GPS Time = {reference_span_s:.3f} s")
    emit(f"  Canais contínuos avaliados: {len(rows)}")

    if not truncated:
        emit(f"  {strings.INSPECT_FREQ_ALL_EXACT}")
    else:
        subheader(strings.INSPECT_FREQ_TRUNCATED.format(count=len(truncated)))
        emit(f"  {'canal':<26}{'declarada':>11}{'empírica':>12}"
             f"{'erro rel.':>11}{'desloc. no fim':>16}")
        for row in sorted(truncated, key=lambda r: -r["relative_error"]):
            # How far out of place the last sample lands if the declared rate is
            # believed: the whole point of the check, in seconds the user can
            # judge.
            offset = (row["n_samples"] - 1) * (
                1.0 / row["declared_hz"] - 1.0 / row["effective_hz"]
            )
            emit(f"  {row['channel']:<26}{row['declared_hz']:>9.0f} Hz"
                 f"{row['effective_hz']:>10.4f} Hz"
                 f"{row['relative_error'] * 100:>10.3f}%"
                 f"{offset:>14.2f} s")

    # Discrete channels: which ones must be forward-filled rather than
    # interpolated when everything is put on the common 100 Hz grid.
    discrete = sorted(
        info.name for info in registry.values()
        if info.is_discrete and not info.is_event
    )
    if discrete:
        subheader(strings.INSPECT_DISCRETE_CHANNELS.format(count=len(discrete)))
        for name in discrete:
            emit(f"  {name:<26} {registry[name].value_sql_type}")


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #

def inspect_file(path: Path) -> dict[str, Any]:
    """Run the full inspection on one file and return a machine-readable summary."""
    header(f"{strings.INSPECT_TITLE}: {path.name}", char="#")

    size_mb = duckdb_reader.file_size_bytes(path) / (1024 * 1024)
    emit(f"  {strings.INSPECT_FILE}: {path}")
    emit(f"  {strings.INSPECT_SIZE}: {size_mb:.1f} MB")

    # The file name is the only identification always present; verify the parser
    # against every real name rather than only against the documented example.
    try:
        track, session_code, started_at = models.parse_session_filename(path)
        emit(f"  Pista: {track}")
        emit(f"  Sessão: {session_code} ({strings.session_type_label(session_code)})")
        emit(f"  Início (UTC): {started_at.isoformat()}")
        name_parsed = True
    except TelemetryError as exc:
        emit(f"  Nome do arquivo NÃO reconhecido: {exc}")
        track, session_code, started_at, name_parsed = None, None, None, False

    con = duckdb_reader.open_session(path)
    try:
        tables = duckdb_reader.list_tables(con)
        emit(f"  {strings.INSPECT_TABLE_COUNT}: {len(tables)}")

        schemas = report_tables(con, tables)
        catalog = report_catalog(con)
        formats = report_formats(schemas)
        divergence = report_divergence(formats)
        coherence = report_coherence(catalog, formats)

        registry = channel_registry.build_registry(con)
        time_base = report_time_base(con, registry)
    finally:
        con.close()

    return {
        "file": str(path),
        "size_mb": round(size_mb, 1),
        "filename_parsed": name_parsed,
        "track": track,
        "session_type": session_code,
        "started_at": started_at.isoformat() if started_at else None,
        "n_tables": len(tables),
        "formats": {name: fmt.value for name, fmt in formats.items()},
        "format_counts": dict(Counter(fmt.value for fmt in formats.values())),
        "divergence": divergence,
        "coherence": coherence,
        "time_base": time_base,
    }


def compare_files(summaries: list[dict[str, Any]]) -> None:
    """Report where two or more session files disagree on schema.

    Run over different session types (Practice / Qualifying / Race) and cars:
    if the schema varies between them, the registry has to be rebuilt per file
    rather than assumed once, and any feature depending on a variable channel
    needs the graceful-degradation path.
    """
    if len(summaries) < 2:
        return

    header("COMPARAÇÃO ENTRE ARQUIVOS", char="#")

    for summary in summaries:
        emit(f"  {Path(summary['file']).name}")
        emit(f"      pista {summary['track']!r}, sessão {summary['session_type']!r}, "
             f"{summary['n_tables']} tabelas, formatos {summary['format_counts']}")

    reference = summaries[0]
    ref_formats = reference["formats"]
    for other in summaries[1:]:
        subheader(f"{Path(reference['file']).name}  vs  {Path(other['file']).name}")
        other_formats = other["formats"]

        only_ref = sorted(set(ref_formats) - set(other_formats))
        only_other = sorted(set(other_formats) - set(ref_formats))
        differing = sorted(
            (n, ref_formats[n], other_formats[n])
            for n in set(ref_formats) & set(other_formats)
            if ref_formats[n] != other_formats[n]
        )

        if not (only_ref or only_other or differing):
            emit("  Schemas idênticos.")
            continue

        if only_ref:
            emit(f"  Só no primeiro ({len(only_ref)}):")
            bullet_list(only_ref, indent="    ")
        if only_other:
            emit(f"  Só no segundo ({len(only_other)}):")
            bullet_list(only_other, indent="    ")
        if differing:
            emit(f"  Formato diferente ({len(differing)}):")
            bullet_list([f"{n}: {a} vs {b}" for n, a, b in differing], indent="    ")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inspeciona o schema real de arquivos de telemetria do LMU."
    )
    parser.add_argument("files", nargs="+", type=Path, help="Arquivos .duckdb")
    parser.add_argument(
        "--json", type=Path, default=None,
        help="Grava um resumo em JSON no caminho indicado.",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="Silencia os avisos de logging no stderr.",
    )
    args = parser.parse_args(argv)

    _force_utf8_stdout()
    setup_logging(level=logging.ERROR if args.quiet else logging.WARNING)

    summaries: list[dict[str, Any]] = []
    for path in args.files:
        try:
            summaries.append(inspect_file(path.resolve()))
        except TelemetryError as exc:
            # One unreadable file must not abort inspection of the others.
            emit(f"\nFALHA em {path}: {exc}")
            logger.error("Inspection failed for %s: %s", path, exc)

    compare_files(summaries)

    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(summaries, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        emit(f"\nResumo em JSON gravado em {args.json}")

    return 0 if summaries else 1


if __name__ == "__main__":
    raise SystemExit(main())
