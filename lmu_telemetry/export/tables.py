"""CSV export: the numbers behind every chart, in a form other tools can read.

A telemetry tool that cannot hand its data to something else is a dead end. The
exports here are what let a lap be taken into a spreadsheet, a notebook, or a
setup discussion with someone who does not have this application.

**Two dialects, because a CSV is opened by two very different things.** The
standard one - comma delimiter, dot decimal - is what pandas, R and every other
analysis tool expect. The other - semicolon delimiter, comma decimal - is what a
Brazilian or Italian Excel opens correctly on a double click. Writing only the
first means the user's own spreadsheet shows one column of garbage; writing only
the second means no tool can read it. The choice is the caller's.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from lmu_telemetry.ui import strings


@dataclass(frozen=True, slots=True)
class CsvDialect:
    """How numbers and columns are separated.

    Attributes:
        delimiter: Column separator.
        decimal: Decimal mark.
    """

    delimiter: str = ","
    decimal: str = "."

    def format(self, value: float | None, decimals: int) -> str:
        if value is None or not np.isfinite(value):
            return ""
        text = f"{value:.{decimals}f}"
        return text if self.decimal == "." else text.replace(".", self.decimal)


#: What every analysis tool expects.
STANDARD = CsvDialect(",", ".")
#: What a Portuguese-locale Excel opens on a double click.
EXCEL_PT_BR = CsvDialect(";", ",")

#: Channel name -> (column header, display scale, decimals). The scale is the
#: same conversion the charts apply, kept in one place so an exported number
#: always equals the number that was on screen.
CHANNEL_COLUMNS: tuple[tuple[str, str, float, int], ...] = (
    ("Ground Speed", strings.CSV_SPEED, 3.6, 2),
    ("Throttle Pos", strings.CSV_THROTTLE, 100.0, 1),
    ("Brake Pos", strings.CSV_BRAKE, 100.0, 1),
    ("Steering Pos", strings.CSV_STEERING, 100.0, 2),
    ("Gear", strings.CSV_GEAR, 1.0, 0),
    ("Engine RPM", strings.CSV_RPM, 1.0, 0),
)


def write_lap(
    path: Path | str,
    analysis,
    delta=None,
    dialect: CsvDialect = STANDARD,
) -> Path:
    """Write one lap's channels, one row per metre of the distance grid.

    Args:
        path: Destination file.
        analysis: A `pipeline.LapAnalysis`.
        delta: An optional `analysis.delta.DeltaResult`, resampled onto the
            lap's own grid so every row of the file describes the same metre.
        dialect: Delimiter and decimal mark.

    Returns:
        The path written.
    """
    path = Path(path)
    grid = analysis.grid_m

    headers = [strings.CSV_DISTANCE, strings.CSV_ELAPSED]
    columns: list[tuple[np.ndarray, int]] = [
        (grid, 1), (analysis.elapsed_s, 4),
    ]

    for channel, header, scale, decimals in CHANNEL_COLUMNS:
        values = analysis.channels.get(channel)
        if values is None:
            continue
        headers.append(header)
        columns.append((np.asarray(values) * scale, decimals))

    for values, header in (
        (analysis.lateral_g, strings.CSV_LATERAL_G),
        (analysis.longitudinal_g, strings.CSV_LONGITUDINAL_G),
    ):
        if values is not None:
            headers.append(header)
            columns.append((np.asarray(values), 4))

    if delta is not None and len(delta.grid_m):
        headers.append(strings.CSV_DELTA)
        # Held onto the lap's own grid: past the end of the shorter lap there
        # is no measurement, and np.interp would flatten rather than admit it.
        columns.append((
            np.interp(grid, delta.grid_m, delta.delta_s,
                      left=np.nan, right=np.nan),
            4,
        ))

    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle, delimiter=dialect.delimiter)
        writer.writerow(headers)
        for row in range(len(grid)):
            writer.writerow([
                dialect.format(float(values[row]), decimals)
                for values, decimals in columns
            ])

    return path


def write_corners(
    path: Path | str,
    rows: list,
    dialect: CsvDialect = STANDARD,
) -> Path:
    """Write the corner table as it appears on screen.

    Args:
        path: Destination file.
        rows: `pipeline.CornerRow` objects.
        dialect: Delimiter and decimal mark.
    """
    path = Path(path)

    headers = [
        strings.CSV_CORNER, strings.CSV_CORNER_APEX,
        strings.CSV_CORNER_MIN_SPEED, strings.CSV_CORNER_ENTRY_SPEED,
        strings.CSV_CORNER_BRAKING, strings.CSV_CORNER_TRAIL,
        strings.CSV_CORNER_COASTING, strings.CSV_CORNER_SPEED_DELTA,
        strings.CSV_CORNER_DELTA, strings.CSV_CORNER_BEST_LAP,
        strings.CSV_CORNER_GAIN,
    ]

    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle, delimiter=dialect.delimiter)
        writer.writerow(headers)
        for row in rows:
            corner = row.corner
            writer.writerow([
                corner.label,
                dialect.format(corner.apex_distance_m, 1),
                dialect.format(corner.minimum_speed_ms * 3.6, 2),
                dialect.format(_kmh(corner.entry_speed_ms), 2),
                dialect.format(corner.braking_length_m, 1),
                dialect.format(corner.trail_braking_m, 1),
                dialect.format(corner.coasting_time_s, 3),
                dialect.format(_kmh(row.speed_delta_ms), 2),
                dialect.format(row.delta_s, 3),
                "" if row.best_lap_index is None else str(row.best_lap_index),
                dialect.format(row.gain_s, 3),
            ])

    return path


def write_consistency(
    path: Path | str,
    report,
    dialect: CsvDialect = STANDARD,
) -> Path:
    """Write the per-corner consistency ranking.

    Args:
        path: Destination file.
        report: An `analysis.consistency.ConsistencyReport`.
        dialect: Delimiter and decimal mark.
    """
    path = Path(path)

    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle, delimiter=dialect.delimiter)
        writer.writerow([
            strings.CSV_CONSISTENCY_CORNER, strings.CSV_CONSISTENCY_LAPS,
            strings.CSV_CONSISTENCY_BRAKING_STD,
            strings.CSV_CONSISTENCY_SPEED_STD,
            strings.CSV_CONSISTENCY_THROTTLE_STD,
            strings.CSV_CONSISTENCY_TIME_LOST,
            strings.CSV_CONSISTENCY_PATTERN,
        ])
        for corner in report.corners:
            writer.writerow([
                corner.corner_label,
                str(corner.n_laps),
                dialect.format(corner.braking_point_std_m, 2),
                dialect.format(corner.minimum_speed_std_kmh, 2),
                dialect.format(corner.throttle_point_std_m, 2),
                dialect.format(corner.estimated_time_lost_s, 3),
                (strings.CONSISTENCY_PATTERN_DRIFT if corner.has_trend
                 else strings.CONSISTENCY_PATTERN_SCATTER),
            ])

    return path


def _kmh(speed_ms: float | None) -> float | None:
    return None if speed_ms is None else speed_ms * 3.6
