"""Tests for importing sessions into the cache and the catalog.

Run against the demo session that ships in the tree, so they need no game.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lmu_telemetry.infrastructure.storage import catalog, importer, paths

DEMO_DIR = Path(__file__).resolve().parent.parent / "data" / "demo"
DEMO_FILES = sorted(DEMO_DIR.glob("*.duckdb"))

pytestmark = pytest.mark.skipif(not DEMO_FILES, reason="no demo dataset in the tree")


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv(paths.ENV_DATA_DIR, str(tmp_path / "data"))


def test_reimporting_reuses_the_cache():
    importer.import_session_file(DEMO_FILES[0])
    again = importer.import_session_file(DEMO_FILES[0])

    assert again.was_cached


def test_track_length_is_recovered_when_the_catalog_is_rebuilt_under_a_cache():
    """The manifest does not store the track length, the catalog does. Losing
    the catalog while the cache survives used to lose the length for good,
    because a cache hit never reads the source."""
    first = importer.import_session_file(DEMO_FILES[0])
    assert first.track_length_m

    paths.catalog_path().unlink()

    second = importer.import_session_file(DEMO_FILES[0])
    assert not second.was_cached  # it had to go back to the file
    with catalog.connect() as con:
        assert catalog.track_length(con, first.track_name) == pytest.approx(
            first.track_length_m
        )


# --------------------------------------------------------------------------- #
# Track length
# --------------------------------------------------------------------------- #

def _lap(t_end: float):
    from lmu_telemetry.domain.models import Lap

    return Lap(index=0, number=1, t_start=0.0, t_end=t_end)


def test_track_length_accounts_for_the_travel_after_the_last_sample():
    """10 Hz samples of a car at 70 m/s: the last one is short of the line by up
    to 7 m, by a different amount every lap."""
    import numpy as np

    times = np.arange(0.0, 100.0, 0.1)
    distance = times * 70.0  # 7000 m at t = 100 s
    # The line is crossed at t = 100.03, so the last sample (99.9) is 9.1 m short
    # of it: the lap is 7002.1 m long.
    length = importer._lap_length_at_crossing(distance, times, _lap(100.03))

    assert length == pytest.approx(100.03 * 70.0, abs=0.01)


def test_track_length_falls_back_to_the_last_sample_when_the_gap_is_implausible():
    """A recording that stopped early must not be extrapolated across seconds."""
    import numpy as np

    times = np.arange(0.0, 50.0, 0.1)
    distance = times * 70.0

    length = importer._lap_length_at_crossing(distance, times, _lap(80.0))

    assert length == pytest.approx(distance[-1])


def test_track_length_needs_two_samples():
    import numpy as np

    assert importer._lap_length_at_crossing(
        np.array([5.0]), np.array([0.05]), _lap(0.1)
    ) is None
