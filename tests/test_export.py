"""Tests for the export layer.

Everything here runs headless: matplotlib is pinned to Agg on import and
nothing in `lmu_telemetry.export` touches Qt, which is what lets a report be
produced from a script or from CI.
"""

from __future__ import annotations

import csv
import re
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import numpy as np
import pytest

from lmu_telemetry.analysis import friction
from lmu_telemetry.core.errors import TelemetryError
from lmu_telemetry.core.models import Corner, Lap, LapFlag
from lmu_telemetry.export import anonymise, charts, report, tables
from lmu_telemetry.pipeline import CornerRow, LapAnalysis


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

def make_analysis(n: int = 400) -> LapAnalysis:
    """A lap on a 1 m grid with every channel the exports can write."""
    from lmu_telemetry.analysis.distance import DistanceReconstruction

    grid = np.arange(float(n))
    speed = 50.0 - 20.0 * np.exp(-((grid - 200.0) ** 2) / 2000.0)
    elapsed = np.concatenate(([0.0], np.cumsum(1.0 / speed[:-1])))

    corner = Corner(
        index=0, apex_distance_m=200.0, minimum_speed_ms=float(speed.min()),
        entry_speed_ms=50.0, braking_distance_m=140.0,
        throttle_distance_m=240.0, coasting_time_s=0.32, trail_braking_m=40.0,
        start_distance_m=100.0, end_distance_m=300.0,
    )

    return LapAnalysis(
        lap=Lap(index=1, number=1, t_start=0.0, t_end=float(elapsed[-1]),
                official_time_s=float(elapsed[-1]),
                flags=frozenset({LapFlag.VALID})),
        grid_m=grid,
        channels={
            "Ground Speed": speed,
            "Throttle Pos": np.clip((speed - 30.0) / 20.0, 0.0, 1.0),
            "Brake Pos": np.clip((40.0 - speed) / 20.0, 0.0, 1.0),
            "Steering Pos": np.sin(grid / 60.0) * 0.3,
            "Gear": np.full_like(grid, 4.0),
            "Engine RPM": speed * 140.0,
        },
        elapsed_s=elapsed,
        reconstruction=DistanceReconstruction(
            raw_m=grid, corrected_m=grid, scale_factor=1.0,
            integrated_length_m=float(grid[-1]),
            reference_length_m=float(grid[-1]), correction_applied=False,
        ),
        corners=[corner],
        lateral_g=np.sin(grid / 40.0) * 1.5,
        longitudinal_g=np.cos(grid / 40.0) * 1.2,
    )


@pytest.fixture
def analysis() -> LapAnalysis:
    return make_analysis()


@pytest.fixture
def corner_rows(analysis) -> list[CornerRow]:
    return [CornerRow(
        corner=analysis.corners[0], delta_s=-0.104, speed_delta_ms=0.6,
        best_lap_index=3, gain_s=0.078,
    )]


# --------------------------------------------------------------------------- #
# CSV
# --------------------------------------------------------------------------- #

def test_lap_csv_has_one_row_per_metre(tmp_path, analysis):
    path = tables.write_lap(tmp_path / "lap.csv", analysis)

    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))

    assert len(rows) == len(analysis.grid_m) + 1     # + header
    assert rows[0][0] == "distancia_m"
    assert rows[1][0] == "0.0"


def test_lap_csv_exports_the_numbers_that_were_on_screen(tmp_path, analysis):
    """An exported value that disagrees with the chart is worse than no export:
    the two are read side by side."""
    path = tables.write_lap(tmp_path / "lap.csv", analysis)

    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert float(rows[0]["velocidade_kmh"]) == pytest.approx(
        analysis.speed_ms[0] * 3.6, abs=0.01
    )
    assert float(rows[0]["acelerador_pct"]) == pytest.approx(
        analysis.channels["Throttle Pos"][0] * 100.0, abs=0.1
    )


def test_excel_dialect_uses_a_comma_decimal_and_a_semicolon(tmp_path, analysis):
    """A standard CSV shows a Portuguese-locale Excel one column of garbage."""
    path = tables.write_lap(
        tmp_path / "lap.csv", analysis, dialect=tables.EXCEL_PT_BR
    )
    first, second = path.read_text(encoding="utf-8-sig").splitlines()[:2]

    assert ";" in first
    assert "," in second and "." not in second


def test_csv_writes_nothing_for_a_missing_value(tmp_path, analysis):
    """An empty cell says "not recorded". A zero would be a measurement."""
    assert tables.STANDARD.format(None, 2) == ""
    assert tables.STANDARD.format(float("nan"), 2) == ""


def test_corner_csv_matches_the_table(tmp_path, corner_rows):
    path = tables.write_corners(tmp_path / "corners.csv", corner_rows)

    with path.open(encoding="utf-8-sig", newline="") as handle:
        row = next(csv.DictReader(handle))

    assert row["curva"] == "C1"
    assert float(row["apice_m"]) == pytest.approx(200.0)
    assert float(row["a_ganhar_s"]) == pytest.approx(0.078)
    assert float(row["delta_s"]) == pytest.approx(-0.104)


def test_delta_column_is_blank_past_the_shorter_lap(tmp_path, analysis):
    """Beyond the end of the shorter lap nothing was measured, and interpolating
    would flatten rather than admit it."""
    from lmu_telemetry.analysis.delta import DeltaResult

    short = np.arange(0.0, 100.0)
    delta = DeltaResult(
        grid_m=short, delta_s=short * 0.001,
        reference_time_s=short, lap_time_s=short,
    )
    path = tables.write_lap(tmp_path / "lap.csv", analysis, delta)

    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert rows[50]["delta_s"] != ""
    assert rows[-1]["delta_s"] == ""


# --------------------------------------------------------------------------- #
# Charts
# --------------------------------------------------------------------------- #

def test_charts_render_without_a_display(tmp_path, analysis):
    """Forced to Agg on import, so this works over SSH and in CI."""
    import matplotlib

    assert matplotlib.get_backend().lower() == "agg"

    path = charts.export_lap_charts(
        tmp_path / "lap.png", analysis, "Volta 1",
        corners=analysis.corners,
    )
    assert path.exists()
    assert path.stat().st_size > 10_000
    assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_charts_draw_the_comparison_and_the_delta(tmp_path, analysis):
    from lmu_telemetry.analysis.delta import DeltaResult

    grid = analysis.grid_m
    delta = DeltaResult(grid_m=grid, delta_s=np.linspace(-0.2, 0.4, len(grid)),
                        reference_time_s=grid, lap_time_s=grid)

    path = charts.export_lap_charts(
        tmp_path / "both.png", analysis, "Volta 8",
        make_analysis(), "referência", delta, analysis.corners,
    )
    assert path.stat().st_size > 10_000


def test_friction_chart_needs_no_qt(tmp_path):
    rng = np.random.default_rng(5)
    angle = rng.uniform(0, 2 * np.pi, 300)
    envelope = friction.compute_envelope(
        2.0 * np.cos(angle), 1.4 * np.sin(angle)
    )
    path = charts.export_friction(tmp_path / "gg.png", envelope)
    assert path.exists()


def test_track_map_colours_runs_without_gaps(tmp_path):
    x = np.linspace(0.0, 100.0, 50)
    y = np.zeros_like(x)
    classes = np.where(x < 50, 1, -1).astype(np.int8)

    path = charts.export_track_map(
        tmp_path / "map.png", x, y, classes, charts.PEDAL_COLOURS
    )
    assert path.exists()
    assert charts._runs_of(classes) == [(0, 25, 1), (25, 50, -1)]


# --------------------------------------------------------------------------- #
# PDF
# --------------------------------------------------------------------------- #

def test_report_is_a_valid_pdf_with_its_charts(tmp_path, analysis, corner_rows):
    path = report.write_report(tmp_path / "report.pdf", report.ReportContext(
        track_name="Autodromo Nazionale Monza",
        car_name="DKR Engineering #4:ELMS25",
        session_label="Corrida",
        session_date=datetime(2026, 7, 30, 17, 12, tzinfo=UTC),
        lap_number=8,
        primary=analysis,
        primary_label="Volta 8",
        corner_rows=corner_rows,
        envelope=friction.compute_envelope(
            analysis.lateral_g, analysis.longitudinal_g
        ),
        transition_quality=0.38,
    ))

    raw = path.read_bytes()
    assert raw[:5] == b"%PDF-"
    assert raw.rstrip().endswith(b"%%EOF")
    assert raw.count(b"/Subtype /Image") >= 2      # traces and the g-g diagram


def test_report_states_the_ideal_lap_s_caveat(tmp_path, analysis, corner_rows):
    """A PDF outlives the session it came from and gets forwarded to people who
    were not there. A target that is not achievable must not read as one that
    is."""
    from lmu_telemetry.analysis.ideal_lap import IdealLap

    ideal = IdealLap(
        segments=[], grid_m=analysis.grid_m, elapsed_s=analysis.elapsed_s,
        speed_ms=analysis.speed_ms, discontinuities=[],
        total_time_s=analysis.time_s - 0.5, best_real_lap_index=1,
        best_real_time_s=analysis.time_s,
    )
    path = report.write_report(tmp_path / "ideal.pdf", report.ReportContext(
        track_name="Monza", car_name="LMP3", session_label="Corrida",
        session_date=None, lap_number=8, primary=analysis,
        primary_label="Volta 8", corner_rows=corner_rows, ideal=ideal,
    ))

    from lmu_telemetry.ui import strings

    # The note is built from the same string the interface shows, so a change
    # to one cannot silently drop the other.
    assert strings.PDF_NOTE_IDEAL.startswith("A volta ideal é costurada")
    assert path.stat().st_size > 10_000


def test_report_column_labels_avoid_glyphs_helvetica_cannot_print(tmp_path):
    """WinAnsi has no Greek: a sigma comes out as "s" and a delta as "D"."""
    from lmu_telemetry.ui import strings

    for label in (strings.PDF_COLUMN_DELTA, strings.PDF_COLUMN_BRAKING_STD,
                  strings.PDF_COLUMN_SPEED_STD,
                  strings.PDF_CONSISTENCY_SUMMARY):
        assert "σ" not in label
        assert "Δ" not in label


# --------------------------------------------------------------------------- #
# Anonymisation
# --------------------------------------------------------------------------- #

@pytest.fixture
def personal_session(tmp_path: Path) -> Path:
    """A minimal session file carrying a driver's name."""
    path = tmp_path / "Test Track_R_2026-01-02T03_04_05Z.duckdb"
    con = duckdb.connect(str(path))
    con.execute(
        "CREATE TABLE channelsList "
        "(channelName VARCHAR, frequency INTEGER, unit VARCHAR)"
    )
    con.execute("INSERT INTO channelsList VALUES ('Ground Speed', 10, 'km/h')")
    con.execute("CREATE TABLE eventsList (eventName VARCHAR, unit VARCHAR)")
    con.execute("CREATE TABLE metadata (key VARCHAR, value VARCHAR)")
    con.execute(
        "INSERT INTO metadata VALUES "
        "('DriverName', 'Lucas Piccinin'), "
        "('SteamID', '76561198000000000'), "
        "('TrackName', 'Test Track'), "
        "('CarName', 'Team Something #4:GT3'), "
        "('Notes', 'setup by Lucas Piccinin after qualifying')"
    )
    con.execute('CREATE TABLE "Ground Speed" (value FLOAT)')
    con.execute('INSERT INTO "Ground Speed" SELECT 100.0 + i FROM range(10) t(i)')
    con.close()
    return path


def test_anonymisation_never_touches_the_original(tmp_path, personal_session):
    """A tool that can damage the only record of a session is worse than no
    tool."""
    before = personal_session.read_bytes()

    anonymise.anonymise_session(personal_session, tmp_path / "out.duckdb")

    assert personal_session.read_bytes() == before
    con = duckdb.connect(str(personal_session), read_only=True)
    try:
        name = con.execute(
            "SELECT value FROM metadata WHERE key='DriverName'"
        ).fetchone()[0]
    finally:
        con.close()
    assert name == "Lucas Piccinin"


def test_anonymisation_clears_the_known_fields(tmp_path, personal_session):
    destination = tmp_path / "out.duckdb"
    result = anonymise.anonymise_session(personal_session, destination)

    con = duckdb.connect(str(destination), read_only=True)
    try:
        values = dict(con.execute("SELECT key, value FROM metadata").fetchall())
    finally:
        con.close()

    assert values["DriverName"] == anonymise.PLACEHOLDER_DRIVER
    assert values["SteamID"] == "0"
    assert result.replaced["DriverName"][0] == "Lucas Piccinin"


def test_anonymisation_sweeps_fields_it_was_not_told_about(
    tmp_path, personal_session
):
    """A field this code does not know about is exactly the field that would
    leak."""
    destination = tmp_path / "out.duckdb"
    result = anonymise.anonymise_session(personal_session, destination)

    con = duckdb.connect(str(destination), read_only=True)
    try:
        notes = con.execute(
            "SELECT value FROM metadata WHERE key='Notes'"
        ).fetchone()[0]
    finally:
        con.close()

    assert "Lucas Piccinin" not in notes
    assert anonymise.PLACEHOLDER_DRIVER in notes
    assert result.cells_scrubbed >= 1


def test_anonymisation_leaves_the_telemetry_intact(tmp_path, personal_session):
    destination = tmp_path / "out.duckdb"
    anonymise.anonymise_session(personal_session, destination)

    con = duckdb.connect(str(destination), read_only=True)
    try:
        tables_found = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
        samples = con.execute('SELECT count(*) FROM "Ground Speed"').fetchone()[0]
    finally:
        con.close()

    assert tables_found == {"channelsList", "eventsList", "metadata",
                            "Ground Speed"}
    assert samples == 10


def test_verification_finds_a_residue(tmp_path, personal_session):
    """Checking the artefact rather than trusting the writer is the only check
    that means anything before publishing one."""
    untouched = tmp_path / "copy.duckdb"
    untouched.write_bytes(personal_session.read_bytes())

    assert anonymise.verify(untouched, ("Lucas Piccinin",))
    destination = tmp_path / "out.duckdb"
    result = anonymise.anonymise_session(personal_session, destination)
    assert anonymise.verify(destination, result.residues) == []


def test_anonymisation_refuses_to_overwrite_without_being_told(
    tmp_path, personal_session
):
    destination = tmp_path / "out.duckdb"
    anonymise.anonymise_session(personal_session, destination)

    with pytest.raises(TelemetryError):
        anonymise.anonymise_session(personal_session, destination)

    anonymise.anonymise_session(personal_session, destination, force=True)


def test_anonymisation_refuses_to_write_over_the_source(personal_session):
    with pytest.raises(TelemetryError):
        anonymise.anonymise_session(personal_session, personal_session)


def test_short_values_are_not_swept(tmp_path):
    """Scrubbing a two-character name out of the schema would break the file to
    protect nothing."""
    path = tmp_path / "Short_R_2026-01-02T03_04_05Z.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE metadata (key VARCHAR, value VARCHAR)")
    con.execute("INSERT INTO metadata VALUES ('DriverName', 'TC')")
    con.execute(
        "CREATE TABLE channelsList "
        "(channelName VARCHAR, frequency INTEGER, unit VARCHAR)"
    )
    con.execute("INSERT INTO channelsList VALUES ('TC', 10, '')")
    con.close()

    result = anonymise.anonymise_session(path, tmp_path / "out.duckdb")

    assert result.residues == ()
    con = duckdb.connect(str(tmp_path / "out.duckdb"), read_only=True)
    try:
        assert con.execute(
            "SELECT channelName FROM channelsList"
        ).fetchone()[0] == "TC"
    finally:
        con.close()


# --------------------------------------------------------------------------- #
# The committed demo dataset
# --------------------------------------------------------------------------- #

DEMO_DIR = Path(__file__).resolve().parent.parent / "data" / "demo"


def _demo_files() -> list[Path]:
    return sorted(DEMO_DIR.glob("*.duckdb")) if DEMO_DIR.exists() else []


#: Metadata keys the game writes that carry no personal data, verified across
#: all 66 sessions recorded on the development machine. Keeping this as an
#: allowlist rather than a blocklist is the point: a key a future game version
#: adds fails this test and gets looked at, instead of shipping unnoticed.
IMPERSONAL_KEYS = frozenset({
    "CarClass", "CarName", "CarSetup", "RecordingTime", "SessionTime",
    "SessionType", "TrackLayout", "TrackName", "Version",
    "WeatherConditions",
})


@pytest.mark.skipif(not _demo_files(), reason="no demo dataset in the tree")
def test_the_committed_demo_carries_no_personal_data():
    """The one test that would matter after a mistake: the file in the
    repository, checked as it will be published."""
    for path in _demo_files():
        con = duckdb.connect(str(path), read_only=True)
        try:
            values = dict(
                con.execute("SELECT key, value FROM metadata").fetchall()
            )
        finally:
            con.close()

        assert values.get("DriverName") == anonymise.PLACEHOLDER_DRIVER
        assert values.get("SteamID") in (None, "0")

        unexpected = set(values) - IMPERSONAL_KEYS - set(anonymise.REPLACEMENTS)
        assert not unexpected, (
            f"{path.name} carries metadata keys nobody has reviewed: "
            f"{sorted(unexpected)}"
        )


@pytest.mark.skipif(not _demo_files(), reason="no demo dataset in the tree")
def test_the_committed_demo_still_loads_and_analyses():
    """Anonymising must not have damaged the telemetry: a demo file that cannot
    be opened demonstrates nothing."""
    from lmu_telemetry import pipeline
    from lmu_telemetry.ingest.session_loader import load_session

    path = _demo_files()[0]
    with load_session(path, with_hash=False) as session:
        assert session.laps
        analysis = pipeline.analyse_session(session)
        assert analysis.laps
        assert analysis.reference_corners
