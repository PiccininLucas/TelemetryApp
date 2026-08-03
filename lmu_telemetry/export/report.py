"""The PDF debrief: one document that says what the lap was and what to fix.

Everything the interface shows, laid out to be read once and acted on - which
is a different job from an interactive tool. Order follows how a debrief
actually goes: what the lap was, what it looked like, corner by corner, and how
repeatable it was.

**The caveats travel with the numbers.** A PDF outlives the session it came
from and gets forwarded to people who were not there when it was generated. The
ideal lap's "this target is not guaranteed to be achievable", the fact that
distance is reconstructed rather than recorded, and the fact that the
acceleration channels arrive mislabelled are all reproduced in the document
itself rather than assumed to be remembered.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from lmu_telemetry.export import charts
from lmu_telemetry.logging_config import get_logger
from lmu_telemetry.ui import strings
from lmu_telemetry.ui.formatting import format_gap, format_lap_time

logger = get_logger(__name__)

HEADING = colors.HexColor("#1f5fa8")
RULE = colors.HexColor("#c8ccd2")
MUTED = colors.HexColor("#5f656d")
HIGHLIGHT = colors.HexColor("#b8791a")


@dataclass(frozen=True, slots=True)
class ReportContext:
    """Everything a report needs, gathered by the caller.

    Assembled by whoever has access to the session - the interface or a script -
    so this module stays a renderer and never opens a file of its own.

    Attributes:
        track_name: Circuit.
        car_name: Car.
        session_label: "Corrida", "Treino livre" and so on.
        session_date: When it was recorded.
        lap_number: The lap being reported.
        primary: Its `pipeline.LapAnalysis`.
        primary_label: How to name it in the legend.
        benchmark: The comparison lap's analysis, if any.
        benchmark_label: How to name it in the chart legend, where the gap is
            useful because nothing else on the image states it.
        benchmark_summary: How to name it in the prose line, which supplies the
            gap itself. Separate from the legend label so the sentence does not
            come out as "Referência: referência: volta 4 … · diferença …".
        delta: The delta between them.
        corner_rows: `pipeline.CornerRow` objects.
        ideal: The session's `IdealLap`, if built.
        consistency: The stint's `ConsistencyReport`, if measurable.
        envelope: The lap's `FrictionEnvelope`, if available.
        transition_quality: Fraction of working time with both axes loaded.
        track_path: `(x_m, y_m)` of the circuit, if GPS was recorded.
        map_classes: Per-metre integer classes colouring the map - pedal state
            when there is no comparison, gain and loss when there is.
        map_colours: The palette those classes index, from `export.charts`.
    """

    track_name: str
    car_name: str
    session_label: str
    session_date: datetime | None
    lap_number: int
    primary: object
    primary_label: str
    benchmark: object | None = None
    benchmark_label: str = ""
    benchmark_summary: str = ""
    delta: object | None = None
    corner_rows: list | None = None
    ideal: object | None = None
    consistency: object | None = None
    envelope: object | None = None
    transition_quality: float = 0.0
    track_path: tuple | None = None
    map_classes: object | None = None
    map_colours: dict | None = None


def write_report(path: Path | str, context: ReportContext) -> Path:
    """Render the debrief.

    Args:
        path: Destination `.pdf`.
        context: Everything to put in it.

    Returns:
        The path written.
    """
    path = Path(path)
    styles = _styles()

    document = SimpleDocTemplate(
        str(path), pagesize=A4,
        leftMargin=16 * mm, rightMargin=16 * mm,
        topMargin=14 * mm, bottomMargin=14 * mm,
        title=strings.PDF_TITLE, author=strings.APP_NAME,
    )

    # The chart images live in a temporary directory that outlives the build:
    # reportlab reads them lazily, so deleting them before `build` returns
    # produces a document with holes where the charts should be.
    with tempfile.TemporaryDirectory() as scratch:
        story = _story(context, styles, Path(scratch))
        document.build(story, onFirstPage=_footer, onLaterPages=_footer)

    logger.info("Report written to %s", path)
    return path


def _story(context: ReportContext, styles: dict, scratch: Path) -> list:
    story: list = []

    story.append(Paragraph(strings.PDF_TITLE, styles["title"]))
    story.append(Paragraph(strings.PDF_SUBTITLE.format(
        track=context.track_name, car=context.car_name,
        session=context.session_label,
        date=(context.session_date.strftime("%Y-%m-%d %H:%M")
              if context.session_date else "?"),
    ), styles["subtitle"]))
    story.append(Spacer(1, 6 * mm))

    story.extend(_summary(context, styles))
    story.extend(_charts(context, styles, scratch))
    story.append(PageBreak())
    story.extend(_corners(context, styles))
    story.extend(_consistency(context, styles))
    story.extend(_notes(context, styles))

    return story


def _summary(context: ReportContext, styles: dict) -> list:
    primary = context.primary
    story = [Paragraph(strings.PDF_SECTION_LAP, styles["heading"])]

    story.append(Paragraph(strings.PDF_LAP_LINE.format(
        number=context.lap_number,
        time=format_lap_time(primary.time_s),
        length=primary.length_m,
        n_corners=len(primary.corners),
    ), styles["body"]))

    if context.delta is not None:
        story.append(Paragraph(strings.PDF_COMPARISON_LINE.format(
            reference=context.benchmark_summary or context.benchmark_label or "—",
            gap=format_gap(context.delta.final_delta_s),
        ), styles["body"]))

    ideal = context.ideal
    if ideal is not None and ideal.gain_over_best_real_s is not None:
        story.append(Paragraph(strings.PDF_IDEAL_LINE.format(
            time=format_lap_time(ideal.total_time_s),
            gain=f"{ideal.gain_over_best_real_s:.3f}",
            n_laps=ideal.n_contributing_laps,
        ), styles["body"]))

    if context.envelope is not None and context.envelope.is_valid:
        story.append(Paragraph(strings.PDF_GG_LINE.format(
            lateral=context.envelope.max_lateral_g,
            braking=context.envelope.max_braking_g,
            acceleration=context.envelope.max_acceleration_g,
            fill=context.envelope.fill_fraction,
            transitions=context.transition_quality,
        ), styles["body"]))

    story.append(Spacer(1, 4 * mm))
    return story


def _charts(context: ReportContext, styles: dict, scratch: Path) -> list:
    story = [Paragraph(strings.PDF_SECTION_CHARTS, styles["heading"])]

    traces = charts.export_lap_charts(
        scratch / "traces.png",
        context.primary, context.primary_label,
        context.benchmark, context.benchmark_label,
        context.delta, context.primary.corners,
    )
    story.append(Image(str(traces), width=168 * mm, height=107 * mm))
    story.append(Spacer(1, 3 * mm))

    side: list = []
    if context.track_path is not None:
        x_m, y_m = context.track_path
        map_path = charts.export_track_map(
            scratch / "map.png", x_m, y_m,
            classes=context.map_classes, colours=context.map_colours,
        )
        side.append(Image(str(map_path), width=80 * mm, height=80 * mm))

    if context.envelope is not None and context.envelope.is_valid:
        gg_path = charts.export_friction(scratch / "gg.png", context.envelope)
        side.append(Image(str(gg_path), width=80 * mm, height=80 * mm))

    if side:
        row = Table([side + [""] * (2 - len(side))], colWidths=[84 * mm] * 2)
        row.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ]))
        story.append(row)

    return story


def _corners(context: ReportContext, styles: dict) -> list:
    rows = context.corner_rows or []
    if not rows:
        return []

    story = [Paragraph(strings.PDF_SECTION_CORNERS, styles["heading"])]

    comparing = any(row.delta_s is not None for row in rows)
    with_ideal = any(row.gain_s is not None for row in rows)

    header = [
        strings.CORNERS_COLUMN_NAME, strings.CORNERS_COLUMN_APEX,
        strings.CORNERS_COLUMN_MIN_SPEED, strings.CORNERS_COLUMN_BRAKING,
        strings.CORNERS_COLUMN_COASTING,
    ]
    if comparing:
        header.append(strings.PDF_COLUMN_DELTA)
    if with_ideal:
        header.append(strings.CORNERS_COLUMN_GAIN)

    body = []
    for row in rows:
        corner = row.corner
        line = [
            corner.label,
            f"{corner.apex_distance_m:.0f}",
            f"{corner.minimum_speed_ms * 3.6:.1f}",
            "—" if corner.braking_length_m is None
            else f"{corner.braking_length_m:.0f}",
            f"{corner.coasting_time_s:.2f}",
        ]
        if comparing:
            line.append("—" if row.delta_s is None else f"{row.delta_s:+.3f}")
        if with_ideal:
            line.append("—" if row.gain_s is None else f"{row.gain_s:.3f}")
        body.append(line)

    # The corner worth the most gets marked, the same as on screen: with the
    # ideal lap present, that one cell is the practice list's first entry.
    highlight = None
    if with_ideal:
        gains = [(row.gain_s or 0.0) for row in rows]
        if max(gains) > 0:
            highlight = gains.index(max(gains))

    story.append(_table([header] + body, highlight_row=highlight))
    story.append(Spacer(1, 5 * mm))
    return story


def _consistency(context: ReportContext, styles: dict) -> list:
    story = [Paragraph(strings.PDF_SECTION_CONSISTENCY, styles["heading"])]
    report = context.consistency

    if report is None or not report.is_measurable:
        story.append(Paragraph(strings.PDF_NO_CONSISTENCY, styles["muted"]))
        story.append(Spacer(1, 4 * mm))
        return story

    story.append(Paragraph(strings.PDF_CONSISTENCY_SUMMARY.format(
        n_laps=len(report.lap_indices),
        median=format_lap_time(report.median_lap_time_s),
        std=report.lap_time_std_s,
        gain=report.total_estimated_gain_s,
    ), styles["body"]))

    header = [
        strings.CONSISTENCY_COLUMN_CORNER, strings.CONSISTENCY_COLUMN_LAPS,
        strings.PDF_COLUMN_BRAKING_STD,
        strings.PDF_COLUMN_SPEED_STD,
        strings.CONSISTENCY_COLUMN_TIME_LOST,
        strings.CONSISTENCY_COLUMN_PATTERN,
    ]
    body = [
        [
            corner.corner_label,
            str(corner.n_laps),
            f"{corner.braking_point_std_m:.1f}",
            f"{corner.minimum_speed_std_kmh:.1f}",
            f"{corner.estimated_time_lost_s:.3f}",
            (strings.CONSISTENCY_PATTERN_DRIFT if corner.has_trend
             else strings.CONSISTENCY_PATTERN_SCATTER),
        ]
        for corner in report.corners
    ]

    story.append(_table([header] + body, highlight_row=0))
    story.append(Spacer(1, 5 * mm))
    return story


def _notes(context: ReportContext, styles: dict) -> list:
    story = [Paragraph(strings.PDF_SECTION_NOTES, styles["heading"])]
    notes = [strings.PDF_NOTE_DISTANCE, strings.PDF_NOTE_ACCELERATION]
    if context.ideal is not None:
        notes.insert(0, strings.PDF_NOTE_IDEAL)
    story.extend(Paragraph("• " + note, styles["muted"]) for note in notes)
    return story


def _table(data: list[list[str]], highlight_row: int | None = None) -> Table:
    """One styled table, with the first row as its header.

    `highlight_row` is an index into the *body*, so callers do not have to
    remember that row zero is the header.
    """
    table = Table(data, repeatRows=1, hAlign="LEFT")
    style = [
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 8),
        ("TEXTCOLOR", (0, 0), (-1, 0), HEADING),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, RULE),
        ("LINEBELOW", (0, 1), (-1, -2), 0.25, RULE),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    if highlight_row is not None:
        row = highlight_row + 1
        style.append(("TEXTCOLOR", (0, row), (-1, row), HIGHLIGHT))
        style.append(("FONT", (0, row), (-1, row), "Helvetica-Bold", 8))
    table.setStyle(TableStyle(style))
    return table


def _styles() -> dict:
    sample = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "title", parent=sample["Title"], fontSize=17, leading=20,
            textColor=HEADING, alignment=TA_LEFT, spaceAfter=1,
        ),
        "subtitle": ParagraphStyle(
            "subtitle", parent=sample["Normal"], fontSize=9.5, leading=12,
            textColor=MUTED,
        ),
        "heading": ParagraphStyle(
            "heading", parent=sample["Heading2"], fontSize=11, leading=14,
            textColor=HEADING, spaceBefore=4, spaceAfter=3,
        ),
        "body": ParagraphStyle(
            "body", parent=sample["Normal"], fontSize=9, leading=12.5,
        ),
        "muted": ParagraphStyle(
            "muted", parent=sample["Normal"], fontSize=8, leading=11,
            textColor=MUTED, spaceAfter=2,
        ),
    }


def _footer(canvas, document) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(MUTED)
    canvas.drawString(
        16 * mm, 8 * mm,
        strings.PDF_FOOTER.format(
            generated=datetime.now().strftime("%Y-%m-%d %H:%M")
        ),
    )
    canvas.drawRightString(A4[0] - 16 * mm, 8 * mm, str(document.page))
    canvas.restoreState()
