"""Tests for parsing the game's session file names.

The documented example used underscores between the words of the track name
(`Circuit_de_la_Sarthe_R_...`), but real files use spaces
(`Circuit de la Sarthe_R_...`). A naive split on "_" therefore works on the
documentation and fails on every real file, which is exactly the kind of bug
this suite exists to prevent.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from lmu_telemetry.core.errors import SessionNameError
from lmu_telemetry.core.models import parse_session_filename


#: Names taken verbatim from a real Telemetry folder.
REAL_NAMES = [
    (
        "Circuit de la Sarthe_R_2026-07-30T20_44_16Z.duckdb",
        "Circuit de la Sarthe", "R",
        datetime(2026, 7, 30, 20, 44, 16, tzinfo=UTC),
    ),
    (
        "Autodromo Nazionale Monza_P_2026-07-30T16_52_54Z.duckdb",
        "Autodromo Nazionale Monza", "P",
        datetime(2026, 7, 30, 16, 52, 54, tzinfo=UTC),
    ),
    (
        "Autodromo Enzo e Dino Ferrari_R_2026-07-31T12_20_02Z.duckdb",
        "Autodromo Enzo e Dino Ferrari", "R",
        datetime(2026, 7, 31, 12, 20, 2, tzinfo=UTC),
    ),
    (
        "Algarve International Circuit_P_2026-07-17T18_58_25Z.duckdb",
        "Algarve International Circuit", "P",
        datetime(2026, 7, 17, 18, 58, 25, tzinfo=UTC),
    ),
    (
        "Circuit de Spa-Francorchamps_R_2026-07-28T17_04_56Z.duckdb",
        "Circuit de Spa-Francorchamps", "R",
        datetime(2026, 7, 28, 17, 4, 56, tzinfo=UTC),
    ),
    (
        "Sebring International Raceway_P_2026-07-31T12_12_02Z.duckdb",
        "Sebring International Raceway", "P",
        datetime(2026, 7, 31, 12, 12, 2, tzinfo=UTC),
    ),
    (
        "Circuit de la Sarthe_Q_2026-07-30T20_33_51Z.duckdb",
        "Circuit de la Sarthe", "Q",
        datetime(2026, 7, 30, 20, 33, 51, tzinfo=UTC),
    ),
]


@pytest.mark.parametrize(("name", "track", "session", "when"), REAL_NAMES)
def test_parses_real_file_names(name, track, session, when):
    parsed_track, parsed_session, parsed_when = parse_session_filename(name)
    assert parsed_track == track
    assert parsed_session == session
    assert parsed_when == when


def test_handles_underscores_inside_the_track_name():
    """The documented example spelled track names with underscores.

    Anchoring on the timestamp from the right makes both spellings work, so the
    parser survives whichever convention a given build uses.
    """
    track, session, _ = parse_session_filename(
        "Circuit_de_la_Sarthe_R_2026-07-30T20_44_16Z.duckdb"
    )
    assert track == "Circuit_de_la_Sarthe"
    assert session == "R"


def test_accepts_a_full_path_and_a_missing_suffix():
    from pathlib import Path

    full = Path("D:/Telemetry/Circuit de la Sarthe_R_2026-07-30T20_44_16Z.duckdb")
    assert parse_session_filename(full)[0] == "Circuit de la Sarthe"
    assert parse_session_filename(
        "Circuit de la Sarthe_R_2026-07-30T20_44_16Z"
    )[0] == "Circuit de la Sarthe"


def test_timestamp_is_timezone_aware_utc():
    """The game writes UTC and marks it with a trailing Z.

    Keeping it UTC rather than naive stops two sessions recorded either side of
    a daylight-saving change from sorting incorrectly in the catalog.
    """
    _, _, when = parse_session_filename(
        "Monza_R_2026-07-30T20_44_16Z.duckdb"
    )
    assert when.tzinfo is UTC
    assert when.utcoffset().total_seconds() == 0


@pytest.mark.parametrize(
    "name",
    [
        "not a session file.duckdb",
        "Monza_R.duckdb",                              # no timestamp
        "Monza_2026-07-30T20_44_16Z.duckdb",           # no session type
        "Monza_R_2026-07-30 20:44:16Z.duckdb",         # wrong separators
        "Monza_R_2026-07-30T20_44_16.duckdb",          # missing Z
        "",
    ],
)
def test_rejects_malformed_names(name):
    with pytest.raises(SessionNameError):
        parse_session_filename(name)


def test_session_type_codes_get_portuguese_labels():
    from lmu_telemetry.ui import strings

    assert strings.session_type_label("R") == strings.SESSION_TYPE_RACE
    assert strings.session_type_label("p") == strings.SESSION_TYPE_PRACTICE
    assert strings.session_type_label("Q") == strings.SESSION_TYPE_QUALIFYING
    assert "ZZ" in strings.session_type_label("ZZ")
