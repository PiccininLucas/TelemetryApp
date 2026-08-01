"""Shared pytest fixtures.

Two kinds of test live in this suite. Most build their own synthetic DuckDB file
and run anywhere, including CI. A few need a real session file recorded by the
game; those are skipped when none is available, so a clone of this repository
without the game still gets a green run.
"""

from __future__ import annotations

import os
from pathlib import Path

import duckdb
import pytest

#: Folders searched for a real session file, in order. Override with the
#: LMU_TELEMETRY_DIR environment variable.
DEFAULT_TELEMETRY_DIRS = (
    Path(r"D:\SteamLibrary\steamapps\common\Le Mans Ultimate\UserData\Telemetry"),
    Path(r"C:\Program Files (x86)\Steam\steamapps\common\Le Mans Ultimate")
    / "UserData" / "Telemetry",
)


def find_real_session() -> Path | None:
    """Return any real session file found on this machine, or None."""
    candidates = list(DEFAULT_TELEMETRY_DIRS)
    if env_dir := os.environ.get("LMU_TELEMETRY_DIR"):
        candidates.insert(0, Path(env_dir))

    for directory in candidates:
        if directory.is_dir():
            files = sorted(directory.glob("*.duckdb"))
            if files:
                return files[0]
    return None


@pytest.fixture(scope="session")
def synthetic_lap():
    """One lap of the synthetic rectangular circuit, with known properties."""
    from tests.synthetic import make_lap

    return make_lap()


@pytest.fixture(scope="session")
def slower_synthetic_lap():
    """The same lap driven 3% slower everywhere.

    Identical in shape, so any delta against the reference is purely the speed
    difference and can be predicted in closed form.
    """
    from tests.synthetic import make_lap

    return make_lap(speed_scale=0.97)


@pytest.fixture(scope="session")
def real_session_path() -> Path:
    """Path to a real session file, skipping the test when none exists."""
    path = find_real_session()
    if path is None:
        pytest.skip("No real Le Mans Ultimate session file available on this machine")
    return path


@pytest.fixture(scope="session")
def real_session_con(real_session_path: Path):
    """Read-only connection to a real session file."""
    con = duckdb.connect(str(real_session_path), read_only=True)
    yield con
    con.close()


@pytest.fixture
def synthetic_session(tmp_path: Path) -> Path:
    """Build a minimal session file exercising all four channel layouts.

    Mirrors the real schema closely enough to test the reader and the registry:
    catalog tables with the same column names, one channel per layout, table
    names containing spaces, and a discrete-typed channel in a continuous
    layout (which the real files do contain).
    """
    path = tmp_path / "Test Track_R_2026-01-02T03_04_05Z.duckdb"
    con = duckdb.connect(str(path))

    con.execute(
        "CREATE TABLE channelsList "
        "(channelName VARCHAR, frequency INTEGER, unit VARCHAR)"
    )
    con.execute(
        "INSERT INTO channelsList VALUES "
        "('Ground Speed', 10, 'km/h'), "
        "('GPS Time', 10, 's'), "
        "('TyresPressure', 10, 'kPa'), "
        "('SurfaceTypes', 10, '')"
    )
    con.execute("CREATE TABLE eventsList (eventName VARCHAR, unit VARCHAR)")
    con.execute("INSERT INTO eventsList VALUES ('Gear', ''), ('TyresCompound', '')")
    con.execute("CREATE TABLE metadata (key VARCHAR, value VARCHAR)")
    con.execute(
        "INSERT INTO metadata VALUES "
        "('TrackName', 'Test Track'), "
        "('CarName', 'Test Car'), "
        "('CarClass', 'GT3'), "
        "('SessionType', 'Race')"
    )

    # Layout A - continuous, single valued. Note the space in the table name.
    con.execute('CREATE TABLE "Ground Speed" (value FLOAT)')
    con.execute(
        'INSERT INTO "Ground Speed" SELECT 100.0 + i FROM range(10) t(i)'
    )
    # Layout A carrying the reference clock, 10 Hz starting at zero.
    con.execute('CREATE TABLE "GPS Time" (value DOUBLE)')
    con.execute('INSERT INTO "GPS Time" SELECT i * 0.1 FROM range(10) t(i)')

    # Layout B - continuous, per wheel.
    con.execute(
        "CREATE TABLE TyresPressure "
        "(value1 FLOAT, value2 FLOAT, value3 FLOAT, value4 FLOAT)"
    )
    con.execute(
        "INSERT INTO TyresPressure "
        "SELECT 170.0 + i, 171.0 + i, 172.0 + i, 173.0 + i FROM range(10) t(i)"
    )

    # Layout B with a discrete type: continuous layout, step resampling.
    con.execute(
        "CREATE TABLE SurfaceTypes "
        "(value1 UTINYINT, value2 UTINYINT, value3 UTINYINT, value4 UTINYINT)"
    )
    con.execute("INSERT INTO SurfaceTypes SELECT 0, 0, 0, 0 FROM range(10)")

    # Layout C - event, single valued.
    con.execute("CREATE TABLE Gear (ts DOUBLE, value TINYINT)")
    con.execute("INSERT INTO Gear VALUES (0.0, 1), (0.3, 2), (0.7, 3)")

    # Layout D - event, per wheel.
    con.execute(
        "CREATE TABLE TyresCompound "
        "(ts DOUBLE, value1 UINTEGER, value2 UINTEGER, "
        "value3 UINTEGER, value4 UINTEGER)"
    )
    con.execute("INSERT INTO TyresCompound VALUES (0.0, 1, 1, 1, 1)")

    con.close()
    return path
