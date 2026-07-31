"""Tests for the time base: index to time, validation, correction, resampling."""

from __future__ import annotations

import numpy as np
import pytest

from lmu_telemetry.core.config import Config, load_config
from lmu_telemetry.ingest import channel_registry, duckdb_reader, time_base
from lmu_telemetry.ingest.time_base import TimeBase, TimeBaseSource
from lmu_telemetry.ui import strings


def make_base(t0=0.0, span=10.0, source=TimeBaseSource.UNIFORM, reference=None):
    return TimeBase(t0=t0, span_s=span, source=source, reference_times=reference)


def _config(max_drift_s=0.05, min_gps_samples=100, target_hz=100.0) -> Config:
    """Build a configuration in memory, so a test never depends on the shipped
    thresholds staying at a particular value."""
    return Config({
        "ingest": {
            "target_hz": target_hz,
            "time_base": {
                "max_drift_s": max_drift_s,
                "min_gps_samples": min_gps_samples,
            },
        },
    })


# --------------------------------------------------------------------------- #
# sample_times
# --------------------------------------------------------------------------- #

def test_sample_times_spread_evenly_across_the_span():
    """A channel's samples cover the whole recording, whatever its rate."""
    base = make_base(t0=100.0, span=10.0)
    times = time_base.sample_times(11, base)

    assert times[0] == pytest.approx(100.0)
    assert times[-1] == pytest.approx(110.0)
    assert np.allclose(np.diff(times), 1.0)


def test_sample_times_ignores_the_declared_frequency():
    """The rate comes from sample count over span, never from the catalog.

    Reproduces the real defect: a channel declared at 7 Hz with 9934 samples
    over 1415.52 s is actually sampled at 7.017 Hz. Believing the declared 7 Hz
    would put its last sample 3.5 s past the end of the recording.
    """
    base = make_base(t0=0.0, span=1415.520)
    times = time_base.sample_times(9934, base)

    assert times[-1] == pytest.approx(1415.520)
    declared_end = (9934 - 1) / 7.0
    assert declared_end - 1415.520 > 3.0

    rate = time_base.effective_frequency(9934, base)
    assert rate == pytest.approx(7.0172, abs=1e-3)


@pytest.mark.parametrize("n_samples", [0, 1, 2])
def test_sample_times_degenerate_lengths(n_samples):
    base = make_base(t0=5.0, span=10.0)
    times = time_base.sample_times(n_samples, base)
    assert len(times) == n_samples
    if n_samples:
        assert times[0] == pytest.approx(5.0)


def test_sample_times_are_float64():
    """float32 would quantise a session's timestamps to about a millisecond."""
    assert time_base.sample_times(100, make_base()).dtype == np.float64


def test_corrected_time_base_reads_the_clock():
    """After a stall, times come from the clock, not from a uniform ramp.

    The clock here runs 0..1 s then jumps to 10 s: the game froze for nine
    seconds. Channels stop producing samples during the freeze exactly as the
    clock does, so equal relative positions map to equal real times.
    """
    reference = np.array([0.0, 0.5, 1.0, 10.0, 10.5, 11.0])
    base = make_base(
        t0=0.0, span=11.0,
        source=TimeBaseSource.GPS_CORRECTED,
        reference=reference,
    )
    times = time_base.sample_times(6, base)

    assert np.allclose(times, reference)
    # A uniform ramp would have placed the middle sample at 4.4 s, inside the
    # freeze, where no sample was ever recorded.
    assert times[2] == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# build_time_base against synthetic files
# --------------------------------------------------------------------------- #

def test_build_time_base_accepts_a_clean_clock(synthetic_session):
    con = duckdb_reader.open_session(synthetic_session)
    try:
        registry = channel_registry.build_registry(con)
        # The fixture is deliberately tiny, so lower the sample floor rather
        # than inflating the fixture: the floor exists to stop a stub clock
        # being trusted, not to gate this behaviour.
        base = time_base.build_time_base(con, registry, _config(min_gps_samples=5))

        assert base.source is TimeBaseSource.UNIFORM
        assert base.t0 == pytest.approx(0.0)
        assert base.span_s == pytest.approx(0.9)
        assert base.max_drift_s < 1e-9
        assert base.was_corrected is False
        assert base.warnings == ()
    finally:
        con.close()


def test_build_time_base_corrects_a_stalled_clock(tmp_path):
    """A pause during recording must be detected and corrected, with a warning.

    This is the failure the whole validation exists for: nothing else in the
    file reveals it, the arrays stay the right length, and every value still
    looks plausible.
    """
    import duckdb

    path = tmp_path / "Stall_R_2026-01-01T00_00_00Z.duckdb"
    con = duckdb.connect(str(path))
    con.execute(
        "CREATE TABLE channelsList "
        "(channelName VARCHAR, frequency INTEGER, unit VARCHAR)"
    )
    con.execute("INSERT INTO channelsList VALUES ('GPS Time', 100, 's')")
    con.execute("CREATE TABLE eventsList (eventName VARCHAR, unit VARCHAR)")
    con.execute("CREATE TABLE metadata (key VARCHAR, value VARCHAR)")
    con.execute('CREATE TABLE "GPS Time" (value DOUBLE)')

    # 200 samples at 100 Hz, with a two-second freeze halfway through.
    clean = np.arange(200) * 0.01
    stalled = np.where(np.arange(200) >= 100, clean + 2.0, clean)
    con.executemany(
        'INSERT INTO "GPS Time" VALUES (?)', [(float(v),) for v in stalled]
    )
    con.close()

    con = duckdb_reader.open_session(path)
    try:
        registry = channel_registry.build_registry(con)
        base = time_base.build_time_base(con, registry, _config(min_gps_samples=50))

        assert base.source is TimeBaseSource.GPS_CORRECTED
        assert base.was_corrected is True
        assert base.max_drift_s > 0.5
        assert base.warnings, "a corrected time base must warn the user"
        # Compare against the string module rather than a literal, so rewording
        # the message for the user does not break the test.
        expected = strings.WARN_TIME_BASE_DRIFT.format(drift=base.max_drift_s)
        assert base.warnings[0] == expected
    finally:
        con.close()


def test_time_base_without_gps_is_flagged_unvalidated(tmp_path):
    """No clock means no validation, and the user has to be told."""
    import duckdb

    path = tmp_path / "NoClock_R_2026-01-01T00_00_00Z.duckdb"
    con = duckdb.connect(str(path))
    con.execute(
        "CREATE TABLE channelsList "
        "(channelName VARCHAR, frequency INTEGER, unit VARCHAR)"
    )
    con.execute("INSERT INTO channelsList VALUES ('Ground Speed', 10, 'km/h')")
    con.execute("CREATE TABLE eventsList (eventName VARCHAR, unit VARCHAR)")
    con.execute("CREATE TABLE metadata (key VARCHAR, value VARCHAR)")
    con.execute('CREATE TABLE "Ground Speed" (value FLOAT)')
    con.execute('INSERT INTO "Ground Speed" SELECT 100.0 FROM range(101)')
    con.close()

    con = duckdb_reader.open_session(path)
    try:
        registry = channel_registry.build_registry(con)
        base = time_base.build_time_base(con, registry)

        assert base.source is TimeBaseSource.UNVALIDATED
        assert base.is_validated is False
        assert base.warnings
        assert base.span_s == pytest.approx(10.0)
    finally:
        con.close()


# --------------------------------------------------------------------------- #
# Resampling
# --------------------------------------------------------------------------- #

def test_common_grid_is_uniform_at_the_configured_rate():
    base = make_base(t0=10.0, span=1.0)
    grid = time_base.common_grid(base, load_config())

    assert grid[0] == pytest.approx(10.0)
    assert np.allclose(np.diff(grid), 0.01)
    assert grid[-1] <= base.t_end + 1e-9


def test_continuous_channel_is_interpolated_linearly():
    source_times = np.array([0.0, 1.0, 2.0])
    values = np.array([0.0, 10.0, 20.0])
    grid = np.array([0.0, 0.5, 1.5, 2.0])

    result = time_base.resample_to_grid(values, source_times, grid, discrete=False)
    assert result.tolist() == pytest.approx([0.0, 5.0, 15.0, 20.0])


def test_discrete_channel_is_forward_filled_not_interpolated():
    """Between gear 3 and gear 4 there is no gear 3.5."""
    source_times = np.array([0.0, 1.0, 2.0])
    gears = np.array([3.0, 4.0, 5.0])
    grid = np.array([0.5, 0.99, 1.0, 1.5])

    result = time_base.resample_to_grid(gears, source_times, grid, discrete=True)
    assert result.tolist() == [3.0, 3.0, 4.0, 4.0]
    assert not np.any((result > 3.0) & (result < 4.0))


def test_step_interpolation_before_the_first_sample_is_nan():
    """The recording says nothing about times before it started, and inventing
    history is worse than admitting the gap."""
    result = time_base.step_interpolate(
        np.array([1.0, 2.0]), np.array([10.0, 11.0]), np.array([9.0, 10.0, 11.5])
    )
    assert np.isnan(result[0])
    assert result[1] == 1.0
    assert result[2] == 2.0


def test_per_wheel_channel_resamples_column_by_column():
    source_times = np.array([0.0, 1.0])
    values = np.array([[1.0, 2.0, 3.0, 4.0], [5.0, 6.0, 7.0, 8.0]])
    grid = np.array([0.0, 0.5, 1.0])

    result = time_base.resample_to_grid(values, source_times, grid, discrete=False)
    assert result.shape == (3, 4)
    assert result[1].tolist() == pytest.approx([3.0, 4.0, 5.0, 6.0])


def test_interpolation_clamps_rather_than_extrapolating():
    """Beyond the recorded range, repeating the edge sample beats inventing
    values that were never measured."""
    result = time_base.resample_to_grid(
        np.array([5.0, 6.0]), np.array([1.0, 2.0]),
        np.array([0.0, 3.0]), discrete=False,
    )
    assert result.tolist() == [5.0, 6.0]


# --------------------------------------------------------------------------- #
# Against a real file
# --------------------------------------------------------------------------- #

def test_real_session_time_base_is_clean(real_session_con):
    """Every session inspected has an intact clock; a stall would be news."""
    registry = channel_registry.build_registry(real_session_con)
    base = time_base.build_time_base(real_session_con, registry)

    assert base.is_validated, "GPS Time should be usable in a real session"
    assert base.span_s > 0


def test_real_continuous_channels_share_one_timeline(real_session_con):
    """Channels at 1 Hz and 100 Hz must start and end at the same instants.

    This is the property that makes the whole index-to-time model work: all of
    them describe the same recording.
    """
    registry = channel_registry.build_registry(real_session_con)
    base = time_base.build_time_base(real_session_con, registry)

    for info in channel_registry.continuous_channels(registry):
        if info.n_samples < 2:
            continue
        times = time_base.sample_times(info.n_samples, base)
        assert times[0] == pytest.approx(base.t0)
        assert times[-1] == pytest.approx(base.t_end, abs=1e-6)
