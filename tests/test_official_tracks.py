"""Tests for the official turn numbering and for measuring corners from it."""

from __future__ import annotations

import numpy as np
import pytest

from lmu_telemetry.domain import official_tracks
from lmu_telemetry.domain.analysis import corners
from lmu_telemetry.domain.official_tracks import LEFT, RIGHT, OfficialTurn


# --------------------------------------------------------------------------- #
# Matching the game's track names
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    ("game_name", "key"),
    [
        ("Fuji Speedway", "fuji"),
        ("fuji speedway", "fuji"),
        ("Autodromo Nazionale Monza", "monza"),
        ("Circuit de Spa-Francorchamps", "spa"),
        ("Circuit de la Sarthe", "le-mans"),
        ("Circuit of the Americas", "cota"),
        ("Autódromo José Carlos Pace", "interlagos"),
        ("Autódromo Internacional do Algarve", "portimao"),
        ("Lusail International Circuit", "qatar"),
        ("Sebring International Raceway", "sebring"),
    ],
)
def test_the_games_track_names_are_recognised(game_name, key):
    assert official_tracks.find_track(game_name).key == key


@pytest.mark.parametrize("name", ["Spanish Grand Prix Circuit", "", None, "Nowhere"])
def test_an_unknown_name_matches_nothing(name):
    """Whole-word matching: "spa" inside "Spanish" is not Spa."""
    assert official_tracks.find_track(name) is None


# --------------------------------------------------------------------------- #
# The data itself
# --------------------------------------------------------------------------- #

def test_every_track_has_a_unique_key_and_a_plausible_length():
    keys = [track.key for track in official_tracks.TRACKS]
    assert len(keys) == len(set(keys))
    for track in official_tracks.TRACKS:
        assert 3_000.0 < track.length_m < 14_000.0


def test_no_track_lists_more_turns_than_it_has():
    for track in official_tracks.TRACKS:
        assert len(track.turns) <= track.turn_count, track.key


def test_turn_numbers_are_unique_within_a_track():
    for track in official_tracks.TRACKS:
        numbers = [turn.number for turn in track.turns]
        assert len(numbers) == len(set(numbers)), track.key


def test_a_turn_is_labelled_with_its_name_when_it_has_one():
    assert OfficialTurn("6", "Hairpin").label == "T6 Hairpin"
    assert OfficialTurn("2").label == "T2"


def test_a_gap_in_the_source_stays_a_gap():
    """Spa's turn 16 is never described by the wiki; it must not be invented,
    and its absence must not stop the other eighteen being placed."""
    spa = official_tracks.find_track("Circuit de Spa-Francorchamps")
    assert "16" not in {turn.number for turn in spa.turns}
    assert spa.is_calibrated


# --------------------------------------------------------------------------- #
# Fuji, the one circuit measured against a lap
# --------------------------------------------------------------------------- #

@pytest.fixture
def fuji():
    return official_tracks.find_track("Fuji Speedway")


def test_fuji_has_sixteen_turns_all_placed(fuji):
    assert fuji.turn_count == 16
    assert len(fuji.turns) == 16
    assert fuji.is_calibrated


def test_fuji_splits_six_left_ten_right_as_the_circuit_states(fuji):
    """The game's own track-info panel says 16 turns, 6 left and 10 right."""
    directions = [turn.direction for turn in fuji.turns]
    assert directions.count(LEFT) == 6
    assert directions.count(RIGHT) == 10


def test_fuji_anchors_run_in_lap_order_inside_the_lap(fuji):
    distances = [distance for distance, _label in fuji.anchors]
    assert distances == sorted(distances)
    assert 0.0 < distances[0] and distances[-1] < fuji.length_m


def test_fuji_anchors_are_far_enough_apart_not_to_share_a_minimum(fuji):
    """Two turns closer than the apex search radius would fight for one minimum."""
    distances = [distance for distance, _label in fuji.anchors]
    assert min(np.diff(distances)) >= 40.0


def test_a_track_nobody_has_measured_is_not_calibrated():
    sebring = official_tracks.find_track("Sebring International Raceway")
    assert sebring.anchors == ()
    assert not sebring.is_calibrated


def test_a_partly_placed_track_is_not_calibrated():
    """Half a numbering would label some corners T6 and leave neighbours C4."""
    track = official_tracks.OfficialTrack(
        key="x", display_name="X", aliases=("x",), length_m=4000.0, turn_count=2,
        turns=(OfficialTurn("1", None, RIGHT, 500.0), OfficialTurn("2")),
    )
    assert len(track.anchors) == 1
    assert not track.is_calibrated


# --------------------------------------------------------------------------- #
# Monza, measured against a race lap
# --------------------------------------------------------------------------- #

@pytest.fixture
def monza():
    return official_tracks.find_track("Autodromo Nazionale Monza")


def test_monza_has_eleven_turns_all_placed(monza):
    assert monza.turn_count == 11
    assert monza.is_calibrated
    assert [turn.number for turn in monza.turns] == [str(n) for n in range(1, 12)]


def test_monza_directions_follow_the_circuits_own_sequence(monza):
    sequence = "".join(turn.direction for turn in monza.turns)
    assert sequence == "RLRLRRRLRLR"


def test_monza_anchors_are_in_lap_order_inside_the_lap(monza):
    distances = [distance for distance, _label in monza.anchors]
    assert distances == sorted(distances)
    assert 0.0 < distances[0] and distances[-1] < monza.length_m


# --------------------------------------------------------------------------- #
# Measuring corners at the anchors
# --------------------------------------------------------------------------- #

def _lap():
    """A 2 km lap with one slow corner and one corner taken flat out."""
    grid = np.arange(0.0, 2000.0, 1.0)
    speed = np.full_like(grid, 70.0)
    speed -= 40.0 * np.exp(-((grid - 500.0) / 60.0) ** 2)
    brake = np.where((grid > 420.0) & (grid < 495.0), 0.8, 0.0)
    throttle = np.where(grid > 505.0, 1.0, 0.0)
    return grid, speed, brake, throttle


def test_a_corner_is_measured_at_every_anchor_including_flat_ones():
    grid, speed, brake, throttle = _lap()
    anchors = [(500.0, "T1 Slow"), (1200.0, "T2")]

    found = corners.corners_at_anchors(speed, grid, brake, throttle, anchors)

    assert [c.label for c in found] == ["T1 Slow", "T2"]
    assert [c.index for c in found] == [0, 1]


def test_the_slow_corner_apex_is_the_speed_minimum_and_the_flat_one_sits_on_its_anchor():
    grid, speed, brake, throttle = _lap()
    found = corners.corners_at_anchors(
        speed, grid, brake, throttle, [(505.0, "T1"), (1200.0, "T2")]
    )

    assert found[0].apex_distance_m == pytest.approx(500.0, abs=3.0)
    assert found[0].minimum_speed_ms == pytest.approx(30.0, abs=0.5)
    # No speed minimum near 1200 m: the turn stays where the circuit puts it.
    assert found[1].apex_distance_m == pytest.approx(1200.0, abs=1.0)


def test_a_flat_out_turn_reports_no_braking_point():
    grid, speed, brake, throttle = _lap()
    found = corners.corners_at_anchors(
        speed, grid, brake, throttle, [(500.0, "T1"), (1200.0, "T2")]
    )

    assert found[0].braking_distance_m is not None
    assert found[1].braking_distance_m is None


def test_two_anchors_in_one_arc_do_not_share_an_apex():
    """A hairpin numbered as two turns, with one speed minimum between them."""
    grid, speed, brake, throttle = _lap()
    found = corners.corners_at_anchors(
        speed, grid, brake, throttle, [(480.0, "T1"), (520.0, "T2")]
    )

    assert found[0].apex_distance_m < found[1].apex_distance_m


def test_anchors_given_out_of_order_come_back_in_lap_order():
    grid, speed, brake, throttle = _lap()
    found = corners.corners_at_anchors(
        speed, grid, brake, throttle, [(1200.0, "late"), (500.0, "early")]
    )

    assert [c.label for c in found] == ["early", "late"]


def test_an_anchor_beyond_the_lap_is_dropped():
    grid, speed, brake, throttle = _lap()
    found = corners.corners_at_anchors(
        speed, grid, brake, throttle, [(500.0, "T1"), (9000.0, "T99")]
    )

    assert [c.label for c in found] == ["T1"]


def test_no_anchors_means_no_corners():
    grid, speed, brake, throttle = _lap()
    assert corners.corners_at_anchors(speed, grid, brake, throttle, []) == []


# --------------------------------------------------------------------------- #
# Every calibrated circuit
# --------------------------------------------------------------------------- #

CALIBRATED = [track for track in official_tracks.TRACKS if track.is_calibrated]


def test_the_circuits_measured_so_far_are_calibrated():
    keys = {track.key for track in CALIBRATED}
    assert keys >= {
        "fuji", "monza", "spa", "le-mans", "cota", "interlagos", "portimao",
        "bahrain", "imola",
    }


@pytest.mark.parametrize("track", CALIBRATED, ids=lambda t: t.key)
def test_anchors_follow_the_turn_order_and_stay_on_the_lap(track):
    """Turn 7 comes after turn 6 on the lap: the numbering is the lap order."""
    distances = [turn.anchor_m for turn in track.turns]
    assert distances == sorted(distances)
    assert len(set(distances)) == len(distances)
    assert 0.0 < distances[0] and distances[-1] < track.length_m


@pytest.mark.parametrize("track", CALIBRATED, ids=lambda t: t.key)
def test_no_two_turns_are_closer_than_a_corner_can_be(track):
    """Closer than this, the apex search could not tell two turns apart."""
    assert min(np.diff([turn.anchor_m for turn in track.turns])) >= 30.0


@pytest.mark.parametrize("track", CALIBRATED, ids=lambda t: t.key)
def test_every_anchor_has_a_label_with_its_number(track):
    for turn, (_distance, label) in zip(track.turns, track.anchors, strict=True):
        assert label.startswith(f"T{turn.number}")


@pytest.mark.parametrize("track", CALIBRATED, ids=lambda t: t.key)
def test_directions_are_left_right_or_unknown(track):
    assert {turn.direction for turn in track.turns} <= {LEFT, RIGHT, None}


# --------------------------------------------------------------------------- #
# Not applying a numbering to a layout it does not describe
# --------------------------------------------------------------------------- #

def test_a_lap_of_the_right_length_fits(fuji):
    assert fuji.fits_lap(4533.0)
    assert fuji.fits_lap(4530.0)


def test_a_lap_of_another_layout_does_not_fit():
    bahrain = official_tracks.find_track("Bahrain International Circuit")
    assert bahrain.fits_lap(5384.0)
    assert not bahrain.fits_lap(3507.0)


def test_the_bahrain_outer_circuit_is_not_the_grand_prix_layout():
    assert official_tracks.find_track("Bahrain Outer Circuit") is None
    assert official_tracks.find_track("Bahrain International Circuit") is not None
