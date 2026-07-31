"""Print the laps of a session: phase 2's visible deliverable.

Everything the phase builds is exercised here - the time base and its GPS Time
validation, event step series, lap splitting and classification - so a wrong
number shows up as a wrong lap time rather than hiding until the UI exists.

Usage:
    python scripts/list_laps.py "<file.duckdb>" [more files...]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lmu_telemetry.core.errors import TelemetryError  # noqa: E402
from lmu_telemetry.core.models import LapFlag  # noqa: E402
from lmu_telemetry.ingest.session_loader import (  # noqa: E402
    Session, describe_time_base, load_session,
)
from lmu_telemetry.logging_config import get_logger, setup_logging  # noqa: E402
from lmu_telemetry.ui import strings  # noqa: E402

logger = get_logger(__name__)

LINE_WIDTH = 84


def emit(text: str = "") -> None:
    print(text)


def force_utf8_stdout() -> None:
    """Keep the Portuguese output readable when redirected on Windows."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def format_lap_time(seconds: float | None) -> str:
    """Format a lap time as m:ss.mmm, the way a timing screen shows it."""
    if seconds is None or seconds <= 0:
        return "     --   "
    minutes, remainder = divmod(seconds, 60.0)
    return f"{int(minutes)}:{remainder:06.3f}"


def format_sector(seconds: float | None) -> str:
    return "      --" if seconds is None else f"{seconds:8.3f}"


def print_header(session: Session) -> None:
    info = session.info
    emit("=" * LINE_WIDTH)
    emit(f"{strings.LAPS_TITLE}: {info.path.name}")
    emit("=" * LINE_WIDTH)
    emit(f"  {strings.LAPS_TRACK:<22}{info.track_name}")
    emit(f"  {strings.LAPS_CAR:<22}{info.car_name or '?'}"
         f"{f'  ({info.car_class})' if info.car_class else ''}")
    emit(f"  {strings.LAPS_SESSION:<22}{info.session_type_label}")
    emit(f"  {strings.LAPS_DATE:<22}{info.started_at.isoformat()}")
    if info.weather:
        emit(f"  {strings.LAPS_WEATHER:<22}{info.weather}")
    emit(f"  {strings.LAPS_DURATION:<22}{session.time_base.span_s:.1f} s")
    emit(f"  {strings.LAPS_TIME_BASE:<22}{describe_time_base(session.time_base)}")


def print_warnings(session: Session) -> None:
    if not session.warnings:
        return
    emit()
    emit("  AVISOS")
    for warning in session.warnings:
        emit(f"    ! {warning}")


def print_laps(session: Session) -> None:
    emit()
    if not session.laps:
        emit(f"  {strings.LAPS_NO_LAPS}")
        return

    emit(f"  {strings.LAPS_TABLE_HEADER}")
    emit(f"  {'-' * (LINE_WIDTH - 4)}")

    best = session.best_lap
    for lap in session.laps:
        marker = " *" if best is not None and lap.index == best.index else "  "
        situation = ", ".join(lap.flag_labels())
        # Only quantify the excursion when it was large enough to be flagged.
        # Every lap brushes a kerb exit; printing "0.0% fora" on all of them
        # buries the one lap that actually went off.
        if LapFlag.OFF_TRACK in lap.flags:
            situation += f" ({lap.off_track_fraction * 100:.1f}%)"

        emit(
            f"  {lap.number:>3}{marker} "
            f"{format_lap_time(lap.official_time_s):>10} "
            f"{lap.measured_time_s:>9.3f} "
            f"{format_sector(lap.sector_times_s[0])}"
            f"{format_sector(lap.sector_times_s[1])}"
            f"{format_sector(lap.sector_times_s[2])}"
            f"  {situation}"
        )

    emit()
    comparable = session.comparable_laps
    if best is not None:
        emit("  " + strings.LAPS_SUMMARY.format(
            n_total=len(session.laps),
            n_comparable=len(comparable),
            best=format_lap_time(best.time_s).strip(),
        ))
    else:
        emit("  " + strings.LAPS_NO_COMPARABLE.format(n_total=len(session.laps)))


def print_consistency_check(session: Session) -> None:
    """Cross-check the reconstructed lap boundaries against `Lap Dist`.

    `Lap Dist` resets to zero at every start/finish crossing. If the time base
    and the lap boundaries are right, the reset must land on the boundary. This
    is an independent confirmation that index-to-time mapping is correct - it
    uses a different channel, at a different sample rate, than anything that
    produced the boundaries.
    """
    distance = session.try_channel("Lap Dist")
    if distance is None or len(distance) < 2 or not session.laps:
        return

    times = session.channel_times("Lap Dist")
    # A reset is a large negative jump: distance climbs to the lap length and
    # drops to zero.
    drops = [
        float(times[i + 1])
        for i in range(len(distance) - 1)
        if distance[i + 1] < distance[i] - 100.0
    ]
    if not drops:
        return

    emit()
    emit("  VERIFICAÇÃO CRUZADA - reset de 'Lap Dist' vs fronteira de volta")
    boundaries = [lap.t_start for lap in session.laps[1:]]
    worst = 0.0
    for boundary in boundaries:
        nearest = min(drops, key=lambda d: abs(d - boundary))
        worst = max(worst, abs(nearest - boundary))
    # Median, not times[1] - times[0]: in a session with a recording stall the
    # first interval can straddle the gap and overstate the period tenfold.
    sample_period = float(np.median(np.diff(times)))
    emit(f"    maior diferença: {worst:.3f} s "
         f"(intervalo de amostragem do canal: {sample_period:.3f} s)")
    emit("    " + ("OK: dentro de uma amostra." if worst <= 2 * sample_period
                   else "ATENÇÃO: fora de duas amostras, verifique a base de tempo."))


def inspect(path: Path) -> bool:
    try:
        with load_session(path, with_hash=False) as session:
            print_header(session)
            print_warnings(session)
            print_laps(session)
            print_consistency_check(session)
        return True
    except TelemetryError as exc:
        emit(f"\nFALHA em {path.name}: {exc}")
        logger.error("Could not load %s: %s", path, exc)
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Lista as voltas de uma sessão de telemetria do LMU."
    )
    parser.add_argument("files", nargs="+", type=Path, help="Arquivos .duckdb")
    parser.add_argument("--verbose", action="store_true",
                        help="Mostra mensagens de diagnóstico.")
    args = parser.parse_args(argv)

    force_utf8_stdout()
    setup_logging(level=logging.INFO if args.verbose else logging.WARNING)

    succeeded = 0
    for path in args.files:
        if inspect(path.resolve()):
            succeeded += 1
        emit()

    return 0 if succeeded else 1


if __name__ == "__main__":
    raise SystemExit(main())
