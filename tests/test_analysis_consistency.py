"""Tests for per-corner consistency over a stint."""

from __future__ import annotations

import numpy as np
import pytest

from lmu_telemetry.analysis import consistency
from lmu_telemetry.core.models import Corner


def make_corner(index: int, apex: float, *, braking=None, speed=30.0,
                throttle=None, start=None, end=None) -> Corner:
    return Corner(
        index=index,
        apex_distance_m=apex,
        minimum_speed_ms=speed,
        braking_distance_m=braking,
        throttle_distance_m=throttle,
        start_distance_m=start if start is not None else apex - 50.0,
        end_distance_m=end if end is not None else apex + 50.0,
    )


# --------------------------------------------------------------------------- #
# Lap selection
# --------------------------------------------------------------------------- #

def test_a_lap_spoiled_by_traffic_is_dropped():
    """It says nothing about repeatability, and keeping it would attribute
    someone else's overtake to the driver's inconsistency."""
    times = {0: 100.0, 1: 100.5, 2: 101.0, 3: 100.2, 4: 130.0}

    kept, excluded = consistency.select_laps(times, max_lap_time_excess=0.05)

    assert 4 not in kept
    assert 4 in excluded
    assert sorted(kept) == [0, 1, 2, 3]


def test_selection_uses_the_median_not_the_mean():
    """One very slow lap drags a mean upward and would then justify keeping
    itself."""
    times = {0: 100.0, 1: 100.0, 2: 100.0, 3: 100.0, 4: 300.0}

    kept, excluded = consistency.select_laps(times, max_lap_time_excess=0.05)

    assert 4 in excluded
    assert len(kept) == 4


def test_too_few_laps_yields_nothing():
    """Dispersion over two laps is not a measurement."""
    kept, excluded = consistency.select_laps({0: 100.0, 1: 100.5}, min_laps=3)
    assert kept == []
    assert excluded


def test_selection_of_an_empty_stint():
    assert consistency.select_laps({}) == ([], {})


# --------------------------------------------------------------------------- #
# Dispersion
# --------------------------------------------------------------------------- #

def build_stint(braking_points, speeds, throttle_points=None):
    """One corner, measured across several laps."""
    reference = [make_corner(0, 500.0)]
    per_lap = {}
    for lap, (braking, speed) in enumerate(zip(braking_points, speeds, strict=True)):
        throttle = throttle_points[lap] if throttle_points else 520.0
        per_lap[lap] = [
            make_corner(0, 500.0, braking=braking, speed=speed, throttle=throttle)
        ]
    times = {lap: 100.0 for lap in per_lap}
    return per_lap, times, reference


def test_a_perfectly_repeatable_driver_shows_zero_dispersion():
    per_lap, times, reference = build_stint(
        braking_points=[400.0] * 5, speeds=[30.0] * 5
    )
    report = consistency.analyse(per_lap, times, reference)

    assert report.corners[0].braking_point_std_m == 0.0
    assert report.corners[0].minimum_speed_std_ms == 0.0
    assert report.corners[0].estimated_time_lost_s == pytest.approx(0.0)


def test_dispersion_is_the_sample_standard_deviation():
    """These laps are a sample of how the driver drives, not the population of
    every lap they will ever do, so ddof=1."""
    braking = [390.0, 400.0, 410.0]
    per_lap, times, reference = build_stint(braking, [30.0] * 3)

    report = consistency.analyse(per_lap, times, reference, min_laps=3)

    assert report.corners[0].braking_point_std_m == pytest.approx(
        float(np.std(braking, ddof=1))
    )


def test_apex_speed_spread_is_reported_in_kmh_too():
    per_lap, times, reference = build_stint(
        [400.0] * 4, speeds=[28.0, 30.0, 32.0, 30.0]
    )
    report = consistency.analyse(per_lap, times, reference)

    corner = report.corners[0]
    assert corner.minimum_speed_std_kmh == pytest.approx(
        corner.minimum_speed_std_ms * 3.6
    )


def test_corners_are_ranked_by_estimated_time_lost():
    """The deliverable: a driver cannot work on twelve corners at once."""
    reference = [make_corner(0, 200.0), make_corner(1, 600.0)]
    per_lap = {}
    for lap, (bad_speed, good_speed) in enumerate(
        [(20.0, 30.0), (30.0, 30.0), (25.0, 30.1), (30.0, 29.9)]
    ):
        per_lap[lap] = [
            make_corner(0, 200.0, braking=150.0, speed=bad_speed, throttle=220.0),
            make_corner(1, 600.0, braking=550.0, speed=good_speed, throttle=620.0),
        ]
    times = {lap: 100.0 for lap in per_lap}

    report = consistency.analyse(per_lap, times, reference)

    assert report.corners[0].corner_index == 0
    assert report.corners[0].estimated_time_lost_s > \
        report.corners[1].estimated_time_lost_s
    assert report.worst(1)[0].corner_index == 0


def test_individual_values_are_kept_for_plotting():
    """A drift across the stint and random scatter have the same standard
    deviation and very different causes, so the chart needs the points."""
    per_lap, times, reference = build_stint(
        [390.0, 395.0, 400.0, 405.0], speeds=[30.0] * 4
    )
    report = consistency.analyse(per_lap, times, reference)

    assert report.corners[0].braking_points_m == (390.0, 395.0, 400.0, 405.0)
    assert len(report.corners[0].minimum_speeds_ms) == 4


def test_a_steady_drift_is_flagged_as_a_trend():
    """Usually tyre or fuel state changing through the stint, not erratic
    driving - a different problem with a different fix."""
    per_lap, times, reference = build_stint(
        [380.0, 390.0, 400.0, 410.0, 420.0], speeds=[30.0] * 5
    )
    report = consistency.analyse(per_lap, times, reference)

    assert report.corners[0].has_trend is True


def test_random_scatter_is_not_a_trend():
    per_lap, times, reference = build_stint(
        [400.0, 380.0, 415.0, 385.0, 410.0, 395.0], speeds=[30.0] * 6
    )
    report = consistency.analyse(per_lap, times, reference)

    assert report.corners[0].has_trend is False


def test_corners_missing_on_some_laps_are_tolerated():
    """A corner the detector missed on one lap must not corrupt the others."""
    reference = [make_corner(0, 500.0)]
    per_lap = {
        0: [make_corner(0, 500.0, braking=400.0, speed=30.0)],
        1: [],  # detection failed here
        2: [make_corner(0, 502.0, braking=402.0, speed=30.5)],
        3: [make_corner(0, 498.0, braking=398.0, speed=29.5)],
    }
    times = {lap: 100.0 for lap in per_lap}

    report = consistency.analyse(per_lap, times, reference)

    assert report.corners[0].n_laps == 3


def test_analysis_without_a_reference_returns_an_empty_report():
    report = consistency.analyse({0: []}, {0: 100.0}, [])
    assert report.corners == []


# --------------------------------------------------------------------------- #
# Time-loss estimate
# --------------------------------------------------------------------------- #

def test_measured_time_lost_is_the_shortfall_against_the_driver_s_own_best():
    """The definition of "time available if every corner were driven to its own
    best": mean minus minimum, measured, with no model in between."""
    assert consistency.time_lost_from_segment_times([10.0, 10.5, 11.0]) == \
        pytest.approx(np.mean([10.0, 10.5, 11.0]) - 10.0)


def test_measured_time_lost_is_zero_for_a_repeatable_corner():
    assert consistency.time_lost_from_segment_times([10.0, 10.0, 10.0]) == \
        pytest.approx(0.0)


def test_measured_time_lost_needs_at_least_two_laps():
    assert consistency.time_lost_from_segment_times([10.0]) == 0.0
    assert consistency.time_lost_from_segment_times([]) == 0.0


def test_measured_time_lost_ignores_impossible_times():
    assert consistency.time_lost_from_segment_times([0.0, -5.0, np.nan]) == 0.0


def test_measured_times_are_preferred_over_the_speed_model():
    """The speed model overstated one Monza corner at 26 s of loss on a 107 s
    lap, because a corner's window spans the whole stretch to its neighbour.
    Measuring has no such failure mode.
    """
    per_lap, times, reference = build_stint(
        [400.0] * 4, speeds=[30.0, 20.0, 30.0, 25.0]
    )
    segment_times = {0: {0: 10.0}, 1: {0: 10.4}, 2: {0: 10.0}, 3: {0: 10.2}}

    report = consistency.analyse(
        per_lap, times, reference, segment_times_s=segment_times
    )

    assert report.corners[0].estimated_time_lost_s == pytest.approx(0.15)


def test_speed_model_is_used_when_no_segment_times_are_given():
    """dt = L * (1/V - 1/V_best), over the corner itself rather than the whole
    stretch between corners."""
    losses = consistency.estimate_time_lost_from_speed(
        [30.0, 25.0], corner_length_m=100.0
    )
    expected = np.mean([0.0, 100.0 * (1 / 25.0 - 1 / 30.0)])
    assert losses == pytest.approx(expected)


def test_speed_model_ignores_a_single_lap_and_impossible_speeds():
    assert consistency.estimate_time_lost_from_speed([30.0], 100.0) == 0.0
    assert consistency.estimate_time_lost_from_speed([0.0, -5.0, np.nan], 100.0) == 0.0


def test_speed_model_is_bounded_by_the_corner_not_the_lap():
    """Guards the regression directly: an enormous window must not turn a
    modest speed spread into tens of seconds of claimed loss."""
    reference = [
        Corner(index=0, apex_distance_m=500.0, minimum_speed_ms=16.0,
               start_distance_m=0.0, end_distance_m=1400.0)
    ]
    per_lap = {
        lap: [Corner(index=0, apex_distance_m=500.0, minimum_speed_ms=speed,
                     braking_distance_m=400.0, start_distance_m=0.0,
                     end_distance_m=1400.0)]
        for lap, speed in enumerate([16.0, 21.0, 18.0, 20.0])
    }
    times = {lap: 107.0 for lap in per_lap}

    report = consistency.analyse(per_lap, times, reference)

    assert report.corners[0].estimated_time_lost_s < 5.0


def test_braking_scatter_alone_does_not_count_as_time_lost():
    """A braking point that moves without changing apex speed means the driver
    adjusted successfully. Adding both terms would double-count one mistake."""
    per_lap, times, reference = build_stint(
        braking_points=[380.0, 400.0, 420.0, 390.0],
        speeds=[30.0, 30.0, 30.0, 30.0],
    )
    report = consistency.analyse(per_lap, times, reference)

    assert report.corners[0].braking_point_std_m > 10.0
    assert report.corners[0].estimated_time_lost_s == pytest.approx(0.0)


# --------------------------------------------------------------------------- #
# Stints
# --------------------------------------------------------------------------- #

def test_stints_split_at_pit_visits():
    laps = [0, 1, 2, 3, 4, 5, 6]
    in_pits = {3: True}

    assert consistency.detect_stints(laps, in_pits) == [(0, 1, 2), (4, 5, 6)]


def test_a_session_without_a_pit_stop_is_one_stint():
    """The common case in a race finished without stopping. Returning zero
    stints would silently disable the consistency panel for most sessions."""
    laps = [0, 1, 2, 3, 4]
    assert consistency.detect_stints(laps, {}) == [(0, 1, 2, 3, 4)]


def test_multiple_pit_stops_give_multiple_stints():
    laps = list(range(10))
    in_pits = {3: True, 7: True}

    stints = consistency.detect_stints(laps, in_pits)

    assert stints == [(0, 1, 2), (4, 5, 6), (8, 9)]


def test_no_laps_gives_no_stints():
    assert consistency.detect_stints([], {}) == []


# --------------------------------------------------------------------------- #
# Lap selection
# --------------------------------------------------------------------------- #

def test_the_tighter_of_the_two_ceilings_wins():
    """5% of a 108 s Monza lap is 5.4 s. Against a real race that admitted a lap
    taken through the first chicane at 28 km/h, which is an incident and not
    driving, and it tripled the corner's reported dispersion."""
    times = {i: 108.0 for i in range(6)}
    times[5] = 111.6                                    # +3.6 s, within 5%

    kept, excluded = consistency.select_laps(
        times, max_lap_time_excess=0.05, max_lap_time_excess_s=2.0
    )

    assert 5 not in kept
    assert excluded[5].reason is consistency.Exclusion.TOO_SLOW
    assert excluded[5].excess_s == pytest.approx(3.6)


def test_the_relative_ceiling_still_binds_on_a_short_lap():
    """On a 40 s lap two seconds is 5%, so neither rule is redundant."""
    times = {i: 40.0 for i in range(6)}
    times[5] = 41.5                                     # +1.5 s, but +3.75%

    kept, _excluded = consistency.select_laps(
        times, max_lap_time_excess=0.05, max_lap_time_excess_s=2.0
    )
    assert 5 in kept

    kept, _excluded = consistency.select_laps(
        times, max_lap_time_excess=0.01, max_lap_time_excess_s=2.0
    )
    assert 5 not in kept


def test_exclusions_carry_a_code_not_a_sentence():
    """This layer states facts in numbers; the interface is the only place that
    decides how to word them."""
    kept, excluded = consistency.select_laps({0: 100.0, 1: 100.5}, min_laps=3)

    assert kept == []
    assert all(
        entry.reason is consistency.Exclusion.TOO_FEW_LAPS
        for entry in excluded.values()
    )


# --------------------------------------------------------------------------- #
# Drift versus scatter
# --------------------------------------------------------------------------- #

def test_one_outlier_is_not_a_drift():
    """Regression: the linear correlation called the Parabolica a drift from
    5007, 4996, 5005, 5005, 4955 m - four flat laps and one late outlier, where
    the outlier's magnitude carried the whole statistic."""
    assert consistency._has_trend((5007.0, 4996.0, 5005.0, 5005.0, 4955.0)) is False


def test_a_steady_march_is_a_drift():
    assert consistency._has_trend((480.0, 486.0, 491.0, 497.0, 503.0)) is True
    # Noise on top of the march does not hide it: the order still holds.
    assert consistency._has_trend((480.0, 488.0, 486.0, 497.0, 501.0, 510.0)) is True


def test_pure_scatter_is_not_a_drift():
    assert consistency._has_trend((500.0, 480.0, 510.0, 490.0, 505.0, 485.0)) is False


def test_a_missing_lap_keeps_the_others_in_their_own_places():
    """The correlation is against when each lap happened, not against a lap's
    position in the surviving list."""
    assert consistency._has_trend(
        (480.0, float("nan"), 491.0, 497.0, 503.0, 509.0)
    ) is True


# --------------------------------------------------------------------------- #
# Per-lap alignment
# --------------------------------------------------------------------------- #

def test_per_lap_arrays_line_up_with_the_lap_indices():
    """"Which lap was that" is the question a dispersion chart exists to answer,
    so a lap with no measurement leaves a gap rather than compacting the array."""
    reference = [make_corner(0, 400.0)]
    # Three laps; the middle one has no braking point at this corner.
    corners_per_lap = {
        0: [make_corner(0, 400.0, braking=380.0)],
        1: [make_corner(0, 401.0, braking=None)],
        2: [make_corner(0, 399.0, braking=390.0)],
    }
    lap_times = {0: 100.0, 1: 100.2, 2: 100.1}

    report = consistency.analyse(corners_per_lap, lap_times, reference, min_laps=3)

    corner = report.corners[0]
    assert len(report.lap_indices) == 3
    assert len(corner.braking_points_m) == 3
    assert corner.braking_points_m[0] == pytest.approx(380.0)
    assert np.isnan(corner.braking_points_m[1])
    assert corner.braking_points_m[2] == pytest.approx(390.0)
    # The standard deviation ignores the gap rather than treating it as zero.
    assert corner.braking_point_std_m == pytest.approx(
        np.std([380.0, 390.0], ddof=1)
    )
