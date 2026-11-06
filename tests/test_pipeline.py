"""Tests for the seam between ingestion and analysis.

Run against the demo session that ships in the tree, so they need no game.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lmu_telemetry.application import pipeline
from lmu_telemetry.infrastructure.ingest.session_loader import Session, load_session

DEMO_FILES = sorted(
    (Path(__file__).resolve().parent.parent / "data" / "demo").glob("*.duckdb")
)

pytestmark = pytest.mark.skipif(not DEMO_FILES, reason="no demo dataset in the tree")


@pytest.fixture(scope="module")
def session():
    with load_session(DEMO_FILES[0], with_hash=False) as loaded:
        yield loaded


def test_analysing_a_session_reads_each_channel_once(session, monkeypatch):
    """Every lap needs the same channels, so reading them per lap multiplied the
    cost of a session by its number of laps."""
    fresh = load_session(DEMO_FILES[0], with_hash=False)
    reads: list[str] = []
    original = Session.channel

    def counting(self, name, *, convert=True):
        reads.append(name)
        return original(self, name, convert=convert)

    monkeypatch.setattr(Session, "channel", counting)
    try:
        analysis = pipeline.analyse_session(fresh)
    finally:
        fresh.close()

    assert len(analysis.laps) >= 3
    assert len(reads) == len(set(reads))


def test_precomputed_laps_are_reused_not_analysed_again(session, monkeypatch):
    first = pipeline.analyse_session(session)
    calls: list[int] = []
    original = pipeline.analyse_lap

    def counting(session_, lap, *args, **kwargs):
        calls.append(lap.index)
        return original(session_, lap, *args, **kwargs)

    monkeypatch.setattr(pipeline, "analyse_lap", counting)
    second = pipeline.analyse_session(session, precomputed=first.laps)

    assert calls == []
    assert second.best_lap_index == first.best_lap_index
    assert second.laps.keys() == first.laps.keys()


def test_only_the_missing_laps_are_analysed(session, monkeypatch):
    first = pipeline.analyse_session(session)
    kept = dict(list(first.laps.items())[:1])
    calls: list[int] = []
    original = pipeline.analyse_lap

    def counting(session_, lap, *args, **kwargs):
        calls.append(lap.index)
        return original(session_, lap, *args, **kwargs)

    monkeypatch.setattr(pipeline, "analyse_lap", counting)
    pipeline.analyse_session(session, precomputed=kept)

    assert set(calls) == set(first.laps) - set(kept)
