"""Run the full analysis on a real session and print the results.

Phase 4's visible deliverable. Everything the analysis layer computes appears
here, in units a driver can sanity-check: braking points in metres, apex speeds
in km/h, delta-t in seconds. A formula that is subtly wrong shows up as a
braking point 300 m from any corner, not as a failing assertion.

Usage:
    python scripts/analyse_session.py "<file.duckdb>" [--lap N]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

from lmu_telemetry import pipeline  # noqa: E402
from lmu_telemetry.analysis import delta, ideal_lap as ideal_lap_module, trackmap  # noqa: E402
from lmu_telemetry.core.errors import TelemetryError  # noqa: E402
from lmu_telemetry.ingest.session_loader import load_session  # noqa: E402
from lmu_telemetry.logging_config import get_logger, setup_logging  # noqa: E402
from lmu_telemetry.storage import catalog  # noqa: E402

logger = get_logger(__name__)
WIDTH = 92


def emit(text: str = "") -> None:
    print(text)


def force_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def header(title: str) -> None:
    emit()
    emit("=" * WIDTH)
    emit(title)
    emit("=" * WIDTH)


def lap_time(seconds: float) -> str:
    minutes, remainder = divmod(seconds, 60.0)
    return f"{int(minutes)}:{remainder:06.3f}"


def report_distance(analysis: pipeline.LapAnalysis) -> None:
    header("1. RECONSTRUÇÃO DA DISTÂNCIA")
    r = analysis.reconstruction
    emit(f"  Integração de Ground Speed : {r.integrated_length_m:10.2f} m")
    emit(f"  Referência (Lap Dist)      : "
         f"{r.reference_length_m:10.2f} m" if r.reference_length_m
         else "  Referência                 :        n/d")
    emit(f"  Fator de escala            : {r.scale_factor:10.6f}"
         f"   {'aplicado' if r.correction_applied else 'RECUSADO'}")
    emit(f"  Deriva da integração       : {r.drift_m:+10.2f} m")
    emit(f"  Comprimento final          : {r.length_m:10.2f} m")
    emit()
    emit("  A 250 km/h, Lap Dist a 10 Hz dá uma amostra a cada 6,9 m; a "
         "integração a 100 Hz dá 0,7 m.")


def report_corners(analysis: pipeline.LapAnalysis) -> None:
    header("2. CURVAS DA MELHOR VOLTA")
    if not analysis.corners:
        emit("  Nenhuma curva detectada.")
        return

    emit(f"  {'curva':<7}{'ápice':>9}{'v_mín':>9}{'v_entr':>9}{'frenagem':>10}"
         f"{'dist.fren':>11}{'retomada':>10}{'coast':>8}{'trail':>8}")
    emit(f"  {'-' * (WIDTH - 4)}")
    for corner in analysis.corners:
        braking = (f"{corner.braking_distance_m:10.0f}"
                   if corner.braking_distance_m is not None else "       n/d")
        braking_length = (f"{corner.braking_length_m:11.0f}"
                          if corner.braking_length_m is not None else "        n/d")
        entry = (f"{corner.entry_speed_ms * 3.6:9.1f}"
                 if corner.entry_speed_ms is not None else "      n/d")
        throttle = (f"{corner.throttle_distance_m:10.0f}"
                    if corner.throttle_distance_m is not None else "       n/d")
        emit(
            f"  {corner.label:<7}{corner.apex_distance_m:9.0f}"
            f"{corner.minimum_speed_ms * 3.6:9.1f}{entry}{braking}{braking_length}"
            f"{throttle}{corner.coasting_time_s:8.2f}{corner.trail_braking_m:8.0f}"
        )
    emit()
    emit("  Distâncias em metros da linha de chegada, velocidades em km/h, "
         "coasting em segundos.")


def report_delta(session_analysis: pipeline.SessionAnalysis) -> None:
    header("3. DELTA-T ENTRE AS DUAS MELHORES VOLTAS")
    ordered = sorted(session_analysis.laps.values(), key=lambda a: a.time_s)
    if len(ordered) < 2:
        emit("  Menos de duas voltas comparáveis.")
        return

    best, second = ordered[0], ordered[1]
    result = pipeline.delta_between(best, second)

    emit(f"  Referência: volta {best.lap.number} ({lap_time(best.time_s)})")
    emit(f"  Comparada : volta {second.lap.number} ({lap_time(second.time_s)})")
    emit()
    emit(f"  Delta final                : {result.final_delta_s:+8.3f} s")
    emit(f"  Diferença real dos tempos  : {second.time_s - best.time_s:+8.3f} s")
    emit(f"  Maior perda                : {result.worst_loss_s:+8.3f} s "
         f"em {result.worst_loss_distance_m:.0f} m")

    # A lap against itself must be exactly zero; if it is not, the alignment is
    # broken and every other delta on this page is meaningless.
    self_delta = pipeline.delta_between(best, best)
    emit(f"  Delta da volta contra si mesma: {np.abs(self_delta.delta_s).max():.2e} s"
         f"   {'OK' if np.abs(self_delta.delta_s).max() < 1e-6 else 'FALHOU'}")


def report_ideal(session_analysis: pipeline.SessionAnalysis) -> None:
    header("4. VOLTA TEÓRICA IDEAL")
    ideal = session_analysis.ideal
    if ideal is None:
        emit("  Voltas insuficientes.")
        return

    emit(f"  Tempo ideal                : {lap_time(ideal.total_time_s)}")
    if ideal.best_real_time_s is not None:
        emit(f"  Melhor volta real          : {lap_time(ideal.best_real_time_s)}")
        emit(f"  Ganho teórico              : {ideal.gain_over_best_real_s:+8.3f} s")
    emit(f"  Voltas que contribuem      : {ideal.n_contributing_laps} "
         f"de {len(session_analysis.laps)}")
    emit()
    emit(f"  {'seg':<5}{'início':>9}{'fim':>9}{'melhor':>9}{'volta':>7}"
         f"{'dispersão':>11}")
    emit(f"  {'-' * (WIDTH - 4)}")
    for segment in ideal.segments:
        emit(f"  {segment.index:<5}{segment.start_m:9.0f}{segment.end_m:9.0f}"
             f"{segment.best_time_s:9.3f}{segment.best_lap_index:7d}"
             f"{segment.spread_s:11.3f}")

    seams = ideal_lap_module.significant_discontinuities(ideal, threshold_ms=1.0)
    emit()
    emit(f"  Descontinuidades de velocidade nas emendas: {len(seams)}")
    for seam in seams[:6]:
        emit(f"    {seam.distance_m:8.0f} m   "
             f"{seam.speed_before_ms * 3.6:6.1f} -> {seam.speed_after_ms * 3.6:6.1f} km/h "
             f"({seam.jump_ms * 3.6:+.1f})   volta {seam.from_lap_index} -> "
             f"{seam.to_lap_index}")
    emit()
    emit(f"  {ideal_lap_module.IdealLap.CAVEAT}")


def report_consistency(session_analysis: pipeline.SessionAnalysis) -> None:
    header("5. CONSISTÊNCIA POR CURVA")
    report = session_analysis.consistency
    if report is None or not report.corners:
        emit("  Sem dados suficientes.")
        return

    emit(f"  Voltas medidas: {len(report.lap_indices)}   "
         f"mediana {lap_time(report.median_lap_time_s)}   "
         f"desvio dos tempos {report.lap_time_std_s:.3f} s")
    if report.excluded_lap_indices:
        emit(f"  Excluídas: "
             + ", ".join(f"{i} ({why})"
                         for i, why in report.excluded_lap_indices.items()))
    emit()
    emit(f"  {'curva':<7}{'ápice':>8}{'n':>4}{'σ frenagem':>12}{'σ v_mín':>10}"
         f"{'σ retomada':>12}{'perda est.':>12}  tendência")
    emit(f"  {'-' * (WIDTH - 4)}")
    for corner in report.corners:
        emit(
            f"  {corner.corner_label:<7}{corner.apex_distance_m:8.0f}"
            f"{corner.n_laps:4d}{corner.braking_point_std_m:11.1f} m"
            f"{corner.minimum_speed_std_kmh:9.2f} "
            f"{corner.throttle_point_std_m:11.1f} "
            f"{corner.estimated_time_lost_s:11.3f} s"
            f"  {'sim' if corner.has_trend else ''}"
        )
    emit()
    emit(f"  Ganho total estimado: {report.total_estimated_gain_s:.3f} s por volta")
    emit(f"  Piores curvas: "
         + ", ".join(c.corner_label for c in report.worst(3)))


def report_friction(session_analysis: pipeline.SessionAnalysis) -> None:
    header("6. ADERÊNCIA (DIAGRAMA g-g)")
    best = session_analysis.best
    envelope = pipeline.friction_envelope(best) if best else None
    if envelope is None or not envelope.is_valid:
        emit("  Canais de aceleração indisponíveis.")
        return

    emit(f"  Amostras                   : {envelope.n_points}")
    emit(f"  g lateral máximo           : {envelope.max_lateral_g:6.2f} g")
    emit(f"  g de frenagem máximo       : {envelope.max_braking_g:6.2f} g")
    emit(f"  g de aceleração máximo     : {envelope.max_acceleration_g:6.2f} g")
    emit(f"  Área da envoltória         : {envelope.hull_area_g2:6.2f} g²")
    emit(f"  Preenchimento da envoltória: {envelope.fill_fraction:6.1%}")

    from lmu_telemetry.analysis import friction as friction_module
    blend = friction_module.transition_quality(
        envelope.lateral_g, envelope.longitudinal_g
    )
    emit(f"  Transição frenagem/curva   : {blend:6.1%} das amostras com os "
         f"dois eixos carregados")
    emit()
    emit("  Preenchimento parcial no centro indica soltar o freio antes de virar,")
    emit("  em vez de misturar as duas coisas.")


def report_trackmap(session_analysis: pipeline.SessionAnalysis) -> None:
    header("7. MAPA DA PISTA")
    best = session_analysis.best
    if best is None:
        return

    gps, integrated = pipeline.track_paths(best)
    if gps is None:
        emit("  Canais de GPS indisponíveis.")
        return

    width, height = gps.extent_m
    emit(f"  Projeção equirretangular do GPS")
    emit(f"    extensão                 : {width:.0f} x {height:.0f} m")
    emit(f"    comprimento do traçado   : {gps.path_length_m:.0f} m")
    emit(f"    erro de fechamento       : {gps.closure_error_m:.1f} m")

    if integrated is None:
        emit("  Reconstrução por integração indisponível.")
        return

    comparison = trackmap.compare_paths(gps, integrated)
    emit()
    emit(f"  Reconstrução por ω = a_y / V (validação cruzada, sem usar posição)")
    emit(f"    erro médio contra o GPS  : {comparison.mean_error_m:.1f} m")
    emit(f"    erro máximo              : {comparison.max_error_m:.1f} m")
    emit(f"    erro de fechamento       : {comparison.integrated_closure_error_m:.1f} m")
    emit()
    emit("  A relação ω = a_y / V vale em curva quase-permanente com ângulo de")
    emit("  deriva pequeno. Ela falha em transientes, com o carro deslizando e em")
    emit("  baixa velocidade; a integração acumula esses erros ao longo da volta.")


def analyse(path: Path, lap_number: int | None) -> bool:
    with load_session(path, with_hash=False) as session:
        header(f"ANÁLISE: {path.name}")
        emit(f"  {session.info.track_name} / {session.info.car_name or '?'}")
        emit(f"  {len(session.comparable_laps)} voltas comparáveis "
             f"de {len(session.laps)}")

        track_length = None
        try:
            with catalog.connect() as con:
                track_length = catalog.track_length(con, session.info.track_name)
        except Exception:  # noqa: BLE001 - the catalog is optional here
            pass
        if track_length:
            emit(f"  Comprimento da pista no catálogo: {track_length:.0f} m")

        indices = None
        if lap_number is not None:
            indices = [lap.index for lap in session.laps if lap.number == lap_number]

        result = pipeline.analyse_session(session, track_length, lap_indices=indices)
        if not result.laps:
            emit("\n  Nenhuma volta analisável.")
            return False

        best = result.best
        emit(f"  Melhor volta analisada: {best.lap.number} "
             f"({lap_time(best.time_s)})")

        report_distance(best)
        report_corners(best)
        report_delta(result)
        report_ideal(result)
        report_consistency(result)
        report_friction(result)
        report_trackmap(result)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Roda a análise completa sobre uma sessão do LMU."
    )
    parser.add_argument("file", type=Path)
    parser.add_argument("--lap", type=int, default=None,
                        help="Analisa apenas esta volta.")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    force_utf8()
    setup_logging(level=logging.INFO if args.verbose else logging.WARNING)

    try:
        return 0 if analyse(args.file.resolve(), args.lap) else 1
    except TelemetryError as exc:
        emit(f"FALHA: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
