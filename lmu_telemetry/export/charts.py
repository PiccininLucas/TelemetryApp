"""Print-quality charts, drawn again in matplotlib.

`pyqtgraph` draws the screen because a long session is hundreds of thousands of
points and panning has to stay fluid. It is the wrong tool for a file someone
will read on paper or paste into a message: no vector output, no control over
typography, and a screenshot of a dark interface is unreadable printed.

So the export redraws rather than screenshots. That does mean the two renderers
have to agree, and the agreement is not free - the unit conversions live in one
place (`export.tables.CHANNEL_COLUMNS` and the chart panel's row specs) so an
exported number always equals the number that was on screen.

The palette is light, not the interface's dark theme. Thin bright traces on
black are right on a monitor in a dim room and wrong on paper, where they either
soak the page in toner or vanish.

Backend is forced to Agg on import: this module runs from the interface, from a
script, and from tests, and must never try to open a window in any of them.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

from lmu_telemetry.ui import strings  # noqa: E402

#: Print palette. Deliberately not the screen theme - see the module docstring.
COLOUR_PRIMARY = "#1f5fa8"
COLOUR_BENCHMARK = "#c8781a"
COLOUR_BRAKE = "#c0392b"
COLOUR_THROTTLE = "#1e8449"
COLOUR_GRID = "#d5d8dc"
COLOUR_TEXT = "#2c3037"

#: Relative heights of the stacked rows.
ROW_HEIGHTS = (3.0, 1.6, 1.6)

#: Track-map palettes, in print colours. Defined here rather than imported from
#: the interface: this layer has to run from a script with no Qt installed, and
#: reaching into `ui.track_map` for two dictionaries would drag PySide6 and
#: pyqtgraph into every headless export.
PEDAL_COLOURS: dict[int, str] = {
    -1: COLOUR_BRAKE,
    0: "#8a9099",
    +1: COLOUR_THROTTLE,
}
LOSS_COLOURS: dict[int, str] = {
    -2: "#b0272d",
    -1: "#d4756f",
    0: "#b9bec6",
    +1: "#5aab84",
    +2: "#18804f",
}


def export_lap_charts(
    path: Path | str,
    primary,
    primary_label: str,
    benchmark=None,
    benchmark_label: str = "",
    delta=None,
    corners: list | None = None,
    dpi: int = 200,
) -> Path:
    """Draw speed, pedals and delta-t stacked on a shared distance axis.

    Args:
        path: Destination `.png`.
        primary: A `pipeline.LapAnalysis`.
        primary_label: Legend text for it.
        benchmark: An optional second `LapAnalysis`.
        benchmark_label: Legend text for that.
        delta: An optional `analysis.delta.DeltaResult`.
        corners: Corners to mark and label.
        dpi: Output resolution.

    Returns:
        The path written.
    """
    path = Path(path)
    rows = 3 if delta is not None else 2

    figure, axes = plt.subplots(
        rows, 1, figsize=(11.0, 7.0), sharex=True, dpi=dpi,
        gridspec_kw={"height_ratios": ROW_HEIGHTS[:rows], "hspace": 0.08},
    )
    axes = np.atleast_1d(axes)

    _speed_axis(axes[0], primary, primary_label, benchmark, benchmark_label)
    _pedal_axis(axes[1], primary, benchmark)
    if delta is not None:
        _delta_axis(axes[2], delta)

    axes[-1].set_xlabel(strings.CHART_AXIS_DISTANCE)
    for axis in axes:
        _style(axis)
        if corners:
            _mark_corners(axis, corners, label=axis is axes[0])

    figure.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(figure)
    return path


def _speed_axis(axis, primary, primary_label, benchmark, benchmark_label) -> None:
    axis.plot(primary.grid_m, primary.speed_ms * 3.6,
              color=COLOUR_PRIMARY, linewidth=1.1, label=primary_label)
    if benchmark is not None:
        axis.plot(benchmark.grid_m, benchmark.speed_ms * 3.6,
                  color=COLOUR_BENCHMARK, linewidth=1.0,
                  label=benchmark_label or None)
    axis.set_ylabel(strings.CHART_ROW_SPEED)
    axis.legend(loc="lower right", fontsize=8, framealpha=0.9)


def _pedal_axis(axis, primary, benchmark) -> None:
    for channel, colour in (("Throttle Pos", COLOUR_THROTTLE),
                            ("Brake Pos", COLOUR_BRAKE)):
        values = primary.channels.get(channel)
        if values is not None:
            axis.plot(primary.grid_m, np.asarray(values) * 100.0,
                      color=colour, linewidth=0.9)
        if benchmark is None:
            continue
        other = benchmark.channels.get(channel)
        if other is not None:
            # Same rule as on screen: this row already spends colour telling
            # throttle from brake, so the second lap is dashed instead.
            axis.plot(benchmark.grid_m, np.asarray(other) * 100.0,
                      color=colour, linewidth=0.8, linestyle="--", alpha=0.75)
    axis.set_ylabel(strings.CHART_ROW_PEDALS)
    axis.set_ylim(-3.0, 103.0)


def _delta_axis(axis, delta) -> None:
    values = np.asarray(delta.delta_s, dtype=np.float64)
    grid = np.asarray(delta.grid_m, dtype=np.float64)

    # Split at zero: the sign is the difference between losing and gaining
    # time, and one fill colour would make them look identical.
    axis.fill_between(grid, 0.0, np.where(values > 0, values, 0.0),
                      color=COLOUR_BRAKE, alpha=0.28, linewidth=0)
    axis.fill_between(grid, 0.0, np.where(values < 0, values, 0.0),
                      color=COLOUR_THROTTLE, alpha=0.28, linewidth=0)
    axis.plot(grid, values, color=COLOUR_TEXT, linewidth=1.0)
    axis.axhline(0.0, color=COLOUR_GRID, linewidth=0.8)
    axis.set_ylabel(strings.CHART_ROW_DELTA)


def export_track_map(
    path: Path | str,
    x_m: np.ndarray,
    y_m: np.ndarray,
    classes: np.ndarray | None = None,
    colours: dict[int, str] | None = None,
    dpi: int = 200,
) -> Path:
    """Draw the circuit, coloured by class, with the aspect ratio locked.

    A circuit stretched to fill a page is not a circuit.
    """
    path = Path(path)
    figure = Figure(figsize=(5.4, 5.4), dpi=dpi)
    axis = figure.add_subplot(111)

    if classes is None or colours is None or len(classes) != len(x_m):
        axis.plot(x_m, y_m, color=COLOUR_TEXT, linewidth=1.6)
    else:
        for start, end, value in _runs_of(np.asarray(classes)):
            stop = min(end + 1, len(x_m))
            axis.plot(x_m[start:stop], y_m[start:stop],
                      color=colours.get(int(value), COLOUR_TEXT), linewidth=1.8)

    axis.plot([x_m[0]], [y_m[0]], marker="o", markersize=5, color=COLOUR_TEXT)
    axis.set_aspect("equal", adjustable="datalim")
    axis.axis("off")

    figure.savefig(path, bbox_inches="tight", facecolor="white")
    return path


def export_friction(
    path: Path | str,
    envelope,
    dpi: int = 200,
) -> Path:
    """Draw the g-g scatter with its convex hull, on equal axes.

    One g of braking has to be as tall as one g of cornering, or a circular
    envelope reads as an elliptical one.
    """
    path = Path(path)
    figure = Figure(figsize=(5.4, 5.4), dpi=dpi)
    axis = figure.add_subplot(111)

    axis.scatter(envelope.lateral_g, envelope.longitudinal_g,
                 s=1.5, color=COLOUR_PRIMARY, alpha=0.25, linewidths=0)
    if len(envelope.hull_lateral_g):
        axis.plot(envelope.hull_lateral_g, envelope.hull_longitudinal_g,
                  color=COLOUR_BENCHMARK, linewidth=1.3)

    axis.axhline(0.0, color=COLOUR_GRID, linewidth=0.8)
    axis.axvline(0.0, color=COLOUR_GRID, linewidth=0.8)
    axis.set_xlabel(strings.GG_AXIS_LATERAL)
    axis.set_ylabel(strings.GG_AXIS_LONGITUDINAL)
    axis.set_aspect("equal", adjustable="datalim")
    _style(axis)

    figure.savefig(path, bbox_inches="tight", facecolor="white")
    return path


def _style(axis) -> None:
    axis.grid(True, color=COLOUR_GRID, linewidth=0.6)
    axis.set_axisbelow(True)
    axis.tick_params(colors=COLOUR_TEXT, labelsize=8)
    axis.yaxis.label.set_color(COLOUR_TEXT)
    axis.xaxis.label.set_color(COLOUR_TEXT)
    axis.yaxis.label.set_fontsize(9)
    axis.xaxis.label.set_fontsize(9)
    for spine in axis.spines.values():
        spine.set_color(COLOUR_GRID)


def _mark_corners(axis, corners: list, *, label: bool) -> None:
    for corner in corners:
        axis.axvline(corner.apex_distance_m, color=COLOUR_GRID,
                     linewidth=0.7, linestyle=":", zorder=0)
    if not label:
        return
    top = axis.get_ylim()[1]
    for corner in corners:
        axis.annotate(
            corner.label, xy=(corner.apex_distance_m, top),
            xytext=(2, -10), textcoords="offset points",
            fontsize=7, color=COLOUR_TEXT, alpha=0.7, rotation=0,
        )


def _runs_of(classes: np.ndarray) -> list[tuple[int, int, int]]:
    """Split a class array into maximal runs of one value."""
    if not len(classes):
        return []
    boundaries = np.flatnonzero(np.diff(classes)) + 1
    starts = np.concatenate(([0], boundaries))
    ends = np.concatenate((boundaries, [len(classes)]))
    return [
        (int(start), int(end), int(classes[start]))
        for start, end in zip(starts, ends, strict=True)
    ]
