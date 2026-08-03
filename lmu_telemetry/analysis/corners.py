"""Find the corners of a lap, and measure how each one was driven.

A corner, for this purpose, is a sustained local minimum in speed. That
definition is deliberately about what the driver *did* rather than about the
circuit's geometry: a fast kink taken flat is not a corner to analyse, and two
geometric bends taken as one long arc are one corner to a driver.

The method:

1. Smooth the speed trace with a Savitzky-Golay filter. Unlike a moving average,
   it fits a low-order polynomial over each window, so it removes noise without
   flattening or displacing a minimum - which matters here, because the position
   of the minimum *is* the measurement.
2. Keep local minima below a fraction of the lap's maximum speed. Above that,
   the dip is a kink rather than a corner.
3. Merge minima closer together than a separation threshold, keeping the slower
   one: a double apex is one corner.
4. For each corner, measure the braking point, entry and minimum speed, the
   throttle resumption point, coasting and trail braking.

Every threshold comes from configuration; none is written into the code.

This module takes numpy arrays and returns numbers. It imports nothing from the
rest of the application beyond the `Corner` value object.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from scipy.signal import find_peaks, savgol_filter

from lmu_telemetry.core.models import Corner


@dataclass(frozen=True, slots=True)
class CornerDetectionSettings:
    """Thresholds for corner detection, all supplied by the caller.

    Defaults mirror `config/defaults.toml` so the module is usable on its own in
    a test, but production callers pass the configured values.
    """

    smoothing_window_fraction: float = 0.01
    savgol_polynomial_order: int = 3
    speed_threshold_fraction: float = 0.85
    min_separation_m: float = 50.0
    brake_threshold: float = 0.03
    brake_min_duration_s: float = 0.1
    throttle_threshold: float = 0.2
    throttle_min_duration_s: float = 0.1
    coast_brake_max: float = 0.03
    coast_throttle_max: float = 0.05
    #: A slow stretch is split into separate corners at any internal speed peak
    #: rising by at least this fraction of the lap's maximum speed. Without it,
    #: corners linked by a short burst - Lesmo 1 and 2, the three apexes of
    #: Ascari - never rise back above the corner threshold and are reported as
    #: one, which under-segments a fast circuit badly.
    split_prominence_fraction: float = 0.08


def smooth_speed(
    speed_ms: np.ndarray,
    step_m: float,
    settings: CornerDetectionSettings,
) -> np.ndarray:
    """Smooth a distance-domain speed trace.

    Savitzky-Golay rather than a moving average: a moving average shifts and
    flattens extrema, and the position of the speed minimum is exactly what is
    being measured. A polynomial fit preserves it.

    The window is a fraction of the lap length, so the same settings work at
    Monza and at Le Mans without retuning.
    """
    speed_ms = np.asarray(speed_ms, dtype=np.float64)
    if speed_ms.size < 5:
        return speed_ms.copy()

    lap_length_m = speed_ms.size * step_m
    window = int(round(lap_length_m * settings.smoothing_window_fraction / step_m))
    # savgol needs an odd window strictly greater than the polynomial order.
    window = max(window | 1, settings.savgol_polynomial_order + 2)
    if window % 2 == 0:
        window += 1
    if window >= speed_ms.size:
        window = (speed_ms.size - 1) | 1
    if window <= settings.savgol_polynomial_order:
        return speed_ms.copy()

    return savgol_filter(
        speed_ms, window_length=window, polyorder=settings.savgol_polynomial_order
    )


def _contiguous_regions(mask: np.ndarray) -> list[tuple[int, int]]:
    """Start and end (exclusive) of each run of True in a boolean mask."""
    padded = np.concatenate([[False], mask, [False]])
    edges = np.flatnonzero(np.diff(padded.astype(np.int8)))
    return list(zip(edges[::2].tolist(), edges[1::2].tolist(), strict=True))


def _merge_across_start_line(
    regions: list[tuple[int, int]], n_samples: int
) -> list[tuple[int, int]]:
    """Join a region touching the lap's end with one touching its start.

    A lap is a loop. A corner sitting on the start/finish line appears as two
    fragments, one at each end of the array, and treating them as two corners
    would both invent a corner and put neither apex in the right place.

    The merged region is expressed with an end index past `n_samples`; callers
    take indices modulo the length.
    """
    if len(regions) < 2:
        return regions

    first_start, first_end = regions[0]
    last_start, last_end = regions[-1]
    if first_start != 0 or last_end != n_samples:
        return regions

    return [*regions[1:-1], (last_start, first_end + n_samples)]


def _merge_close_apexes(
    apexes: list[int], speed: np.ndarray, min_separation: int
) -> list[int]:
    """Collapse apexes closer together than the separation threshold.

    "Two minima closer than 50 m are one corner" is a statement about the
    minima, so it is applied to them rather than to the regions they came from.
    Applying it to regions would undo the splitting done just before, because
    splitting a region leaves its two halves touching.

    The slower of a merged pair is kept: it is the one that defines the corner.
    """
    if not apexes:
        return []

    merged = [apexes[0]]
    for apex in apexes[1:]:
        if apex - merged[-1] < min_separation:
            if speed[apex] < speed[merged[-1]]:
                merged[-1] = apex
        else:
            merged.append(apex)
    return merged


def _split_at_internal_peaks(
    speed: np.ndarray,
    start: int,
    end: int,
    n_samples: int,
    prominence: float,
) -> list[tuple[int, int]]:
    """Divide one slow stretch wherever the car meaningfully speeds up again.

    Two corners joined by a short burst of throttle - Lesmo 1 into Lesmo 2, the
    apexes of Ascari - never let the speed climb back above the corner
    threshold, so they arrive here as a single stretch. Splitting at internal
    peaks with real prominence recovers them, while a small wobble in the middle
    of one long corner is left alone.
    """
    indices = np.arange(start, end) % n_samples
    values = speed[indices]
    if values.size < 3:
        return [(start, end)]

    peaks, _properties = find_peaks(values, prominence=prominence)
    if peaks.size == 0:
        return [(start, end)]

    cuts = [start, *(start + int(p) for p in peaks), end]
    return [
        (cuts[i], cuts[i + 1])
        for i in range(len(cuts) - 1)
        if cuts[i + 1] > cuts[i]
    ]


def _apex_of(
    speed: np.ndarray, start: int, end: int, n_samples: int
) -> int:
    """Index of the apex within one slow region.

    Not simply `argmin`. A constant-radius corner taken at the limit holds a
    genuinely flat minimum speed for its whole arc, and `argmin` would return
    the first sample of that plateau - the corner's entry - rather than its
    middle. So the apex is the centre of the longest run of samples within a
    small tolerance of the region's minimum, which reduces to `argmin` when the
    minimum really is a single point.
    """
    indices = np.arange(start, end) % n_samples
    values = speed[indices]

    minimum = float(values.min())
    spread = float(values.max() - minimum)
    tolerance = max(spread * 0.02, 1e-9)

    at_minimum = values <= minimum + tolerance
    runs = _contiguous_regions(at_minimum)
    if not runs:
        return int(indices[int(np.argmin(values))])

    run_start, run_end = max(runs, key=lambda r: r[1] - r[0])
    return int(indices[(run_start + run_end - 1) // 2])


def find_speed_minima(
    smoothed_speed_ms: np.ndarray,
    step_m: float,
    settings: CornerDetectionSettings,
) -> np.ndarray:
    """Indices of the speed minima that count as corners.

    Rather than picking peaks out of the negated signal, this finds the
    contiguous stretches where the car is slow - below a fraction of the lap's
    maximum speed - and takes the apex of each.

    The reason is a failure the synthetic circuit exposed. A corner held at the
    cornering limit produces a perfectly flat speed plateau, and smoothing rings
    slightly at its shoulders, so `find_peaks` reported two minima at the edges
    of every corner and none in the middle. Working from "where is the car
    slow", which is what a corner physically is, has no such failure mode: it
    merges a double apex naturally, is indifferent to the plateau, and closes
    around the lap.
    """
    speed = np.asarray(smoothed_speed_ms, dtype=np.float64)
    n_samples = speed.size
    if n_samples < 3:
        return np.empty(0, dtype=int)

    maximum = float(np.nanmax(speed))
    if not np.isfinite(maximum) or maximum <= 0.0:
        return np.empty(0, dtype=int)

    ceiling = maximum * settings.speed_threshold_fraction
    below = speed <= ceiling
    if not below.any() or below.all():
        # All fast: no corners. All slow: no corner stands out either, which is
        # what an in-lap behind a safety car looks like.
        return np.empty(0, dtype=int)

    separation = max(int(round(settings.min_separation_m / step_m)), 1)

    regions = _contiguous_regions(below)
    regions = _merge_across_start_line(regions, n_samples)

    prominence = maximum * settings.split_prominence_fraction
    regions = [
        piece
        for start, end in regions
        for piece in _split_at_internal_peaks(
            speed, start, end, n_samples, prominence
        )
    ]

    apexes = sorted({
        _apex_of(speed, start, end, n_samples)
        for start, end in sorted(regions)
    })
    return np.array(_merge_close_apexes(apexes, speed, separation), dtype=int)


def _first_sustained(
    mask: np.ndarray,
    minimum_samples: int,
    *,
    search_from: int,
    search_to: int,
    reverse: bool = False,
) -> int | None:
    """First index in a window where `mask` stays true for long enough.

    "Sustained" is what separates a real pedal application from a twitch. A
    single sample over the brake threshold is noise; a tenth of a second of it
    is the driver braking.

    Args:
        mask: Boolean condition per sample.
        minimum_samples: How many consecutive samples must hold.
        search_from: Window start, inclusive.
        search_to: Window end, exclusive.
        reverse: Search backwards, returning the latest qualifying start. Used
            for the braking point, which is the *first* moment of the braking
            phase closest before the apex.
    """
    start = max(0, search_from)
    end = min(len(mask), search_to)
    if end - start < minimum_samples or minimum_samples <= 0:
        return None

    window = mask[start:end]
    # A run of `minimum_samples` trues has a rolling sum equal to that count.
    kernel = np.ones(minimum_samples, dtype=int)
    runs = np.convolve(window.astype(int), kernel, mode="valid")
    qualifying = np.flatnonzero(runs == minimum_samples)
    if qualifying.size == 0:
        return None

    chosen = qualifying[-1] if reverse else qualifying[0]
    return start + int(chosen)


def measure_corner(
    index: int,
    apex_sample: int,
    window_start: int,
    window_end: int,
    speed_ms: np.ndarray,
    brake: np.ndarray,
    throttle: np.ndarray,
    grid_m: np.ndarray,
    step_m: float,
    settings: CornerDetectionSettings,
) -> Corner:
    """Measure how one corner was driven.

    Args:
        index: The corner's position around the lap.
        apex_sample: Grid index of the speed minimum.
        window_start: Grid index where this corner's window begins.
        window_end: Grid index where it ends, exclusive.
        speed_ms: Speed on the distance grid, in m/s.
        brake: Brake position, 0-1.
        throttle: Throttle position, 0-1.
        grid_m: The distance grid.
        step_m: Grid spacing.
        settings: Thresholds.
    """
    apex_speed = float(speed_ms[apex_sample])

    # Duration thresholds are in seconds, but the grid is in metres. Convert
    # using the speed at the apex, which is the slowest point and therefore the
    # most conservative: it demands the most metres for a given time.
    def samples_for(duration_s: float) -> int:
        speed = max(apex_speed, 1.0)
        return max(int(round(duration_s * speed / step_m)), 1)

    braking_mask = np.asarray(brake) > settings.brake_threshold
    throttle_mask = np.asarray(throttle) > settings.throttle_threshold

    # Braking point: the last sustained braking run that starts before the apex.
    # Searching backwards from the apex finds the braking phase belonging to
    # this corner rather than one from the previous corner.
    brake_sample = _first_sustained(
        braking_mask,
        samples_for(settings.brake_min_duration_s),
        search_from=window_start,
        search_to=apex_sample + 1,
        reverse=False,
    )

    # Throttle resumption: the first sustained application after the apex.
    throttle_sample = _first_sustained(
        throttle_mask,
        samples_for(settings.throttle_min_duration_s),
        search_from=apex_sample,
        search_to=window_end,
    )

    # Coasting: neither pedal meaningfully applied, converted from metres to
    # seconds using the local speed.
    coasting = (
        (np.asarray(brake)[window_start:window_end] < settings.coast_brake_max)
        & (np.asarray(throttle)[window_start:window_end] < settings.coast_throttle_max)
    )
    local_speed = np.clip(speed_ms[window_start:window_end], 1.0, None)
    coasting_time = float(np.sum(step_m / local_speed * coasting))

    # Trail braking: braking that continues past the point where the car has
    # started turning, measured here as braking still applied while speed is
    # falling on the approach to the apex.
    approach = slice(brake_sample if brake_sample is not None else window_start,
                     apex_sample + 1)
    still_braking = np.asarray(brake)[approach] > settings.brake_threshold
    trail_braking_m = float(np.sum(still_braking) * step_m) if still_braking.size else 0.0

    return Corner(
        index=index,
        apex_distance_m=float(grid_m[apex_sample]),
        minimum_speed_ms=apex_speed,
        entry_speed_ms=(
            float(speed_ms[brake_sample]) if brake_sample is not None else None
        ),
        braking_distance_m=(
            float(grid_m[brake_sample]) if brake_sample is not None else None
        ),
        throttle_distance_m=(
            float(grid_m[throttle_sample]) if throttle_sample is not None else None
        ),
        coasting_time_s=coasting_time,
        trail_braking_m=trail_braking_m,
        start_distance_m=float(grid_m[window_start]),
        end_distance_m=float(grid_m[min(window_end, len(grid_m) - 1)]),
    )


def detect_corners(
    speed_ms: np.ndarray,
    grid_m: np.ndarray,
    brake: np.ndarray,
    throttle: np.ndarray,
    settings: CornerDetectionSettings | None = None,
) -> list[Corner]:
    """Detect and measure every corner of a lap.

    All inputs must already be on the same distance grid.

    Args:
        speed_ms: Speed in m/s.
        grid_m: Distance grid, uniformly spaced.
        brake: Brake position, 0-1.
        throttle: Throttle position, 0-1.
        settings: Thresholds. Defaults mirror the shipped configuration.

    Returns:
        Corners in order of distance around the lap.
    """
    settings = settings or CornerDetectionSettings()
    speed_ms = np.asarray(speed_ms, dtype=np.float64)
    grid_m = np.asarray(grid_m, dtype=np.float64)

    if speed_ms.size < 5 or grid_m.size != speed_ms.size:
        return []

    step_m = float(grid_m[1] - grid_m[0]) if grid_m.size > 1 else 1.0
    smoothed = smooth_speed(speed_ms, step_m, settings)
    apexes = find_speed_minima(smoothed, step_m, settings)
    if apexes.size == 0:
        return []

    windows = corner_windows(apexes, len(grid_m))

    return [
        measure_corner(
            index=i,
            apex_sample=int(apex),
            window_start=start,
            window_end=end,
            speed_ms=speed_ms,
            brake=brake,
            throttle=throttle,
            grid_m=grid_m,
            step_m=step_m,
            settings=settings,
        )
        for i, (apex, (start, end)) in enumerate(zip(apexes, windows, strict=True))
    ]


def corner_windows(
    apex_samples: np.ndarray, n_samples: int
) -> list[tuple[int, int]]:
    """Split the lap so each corner owns the stretch around its apex.

    Boundaries sit midway between consecutive apexes, so a corner's window holds
    its own braking zone and exit and does not reach into its neighbour's.
    """
    apexes = np.asarray(apex_samples, dtype=int)
    if apexes.size == 0:
        return []

    midpoints = ((apexes[:-1] + apexes[1:]) // 2).tolist()
    starts = [0, *midpoints]
    ends = [*midpoints, n_samples]
    return list(zip(starts, ends, strict=True))


def match_corners(
    corners: list[Corner],
    reference: list[Corner],
    tolerance_m: float = 50.0,
) -> dict[int, int]:
    """Match this lap's corners to a reference set by apex distance.

    Corner identity across laps and sessions is by distance from the line, which
    is what lets a corner keep the name the user gave it. The tolerance absorbs
    the metre or two an apex moves between laps.

    Returns:
        Index in `corners` -> index in `reference`, omitting anything unmatched.
    """
    if not corners or not reference:
        return {}

    reference_distances = np.array([c.apex_distance_m for c in reference])
    matches: dict[int, int] = {}

    for i, corner in enumerate(corners):
        distances = np.abs(reference_distances - corner.apex_distance_m)
        nearest = int(np.argmin(distances))
        if distances[nearest] <= tolerance_m:
            matches[i] = nearest

    return matches


def apply_names(corners: list[Corner], names: dict[int, str]) -> list[Corner]:
    """Return the corners with the user's names attached, matched by index."""
    from dataclasses import replace

    return [
        replace(corner, name=names.get(corner.index, corner.name))
        for corner in corners
    ]


def apply_names_by_distance(
    corners: list[Corner],
    references: Sequence[tuple[float, str]],
    tolerance_m: float = 50.0,
) -> list[Corner]:
    """Attach names to corners by where they are, not by their position in the list.

    Corner *indices* shift the moment the detector finds one more or one fewer
    corner - a wet lap, a lap with a spin, a lap where two corners joined by a
    throttle burst failed to separate. A name pinned to an index would then move
    to the wrong corner and quietly stay wrong. Pinned to a distance from the
    line it stays put, because that is what a corner actually is.

    Each name is given to at most one corner: the nearest within tolerance. Two
    names competing for the same corner would otherwise both appear to apply.

    Args:
        corners: The corners detected on this lap.
        references: `(distance_m, name)` pairs from the catalog.
        tolerance_m: How far an apex may move between laps and still be the
            same corner.

    Returns:
        The corners, with names attached where one matched.
    """
    from dataclasses import replace

    if not corners or not references:
        return corners

    apexes = np.array([corner.apex_distance_m for corner in corners])
    names: dict[int, str] = {}
    taken: set[int] = set()

    for distance, name in references:
        gaps = np.abs(apexes - distance)
        # Corners already claimed are removed from consideration rather than
        # overwritten, so the second name falls to its own next-nearest corner.
        for index in np.argsort(gaps):
            if int(index) in taken:
                continue
            if gaps[index] <= tolerance_m:
                names[int(index)] = name
                taken.add(int(index))
            break

    return [
        replace(corner, name=names.get(position, corner.name))
        for position, corner in enumerate(corners)
    ]
