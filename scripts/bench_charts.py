"""Time the trace stack on a Le Mans-sized lap.

    .venv\\Scripts\\python.exe scripts\\bench_charts.py

Draws a 13 600 m lap against a second one, with the delta and all six rows on,
and reports the median of several runs for:

- **load**: `show_laps` plus one full paint - what opening a lap costs;
- **paint**: one repaint of the stack as it stands - what a resize or a pan costs;
- **cursor**: moving the cursor once and letting Qt repaint what moved - what
  every mouse move costs, and the one that has to stay well under a frame
  (16 ms);
- **pan**: moving the visible window along the lap - every layer is redrawn.

Synthetic data, so the numbers are comparable between machines' runs of the
same build rather than meaningful in themselves; run it before and after a
change to the charts and compare.
"""

from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
from PySide6 import QtWidgets  # noqa: E402

from lmu_telemetry.presentation import theme  # noqa: E402
from lmu_telemetry.presentation.chart_panel import (  # noqa: E402
    ROW_SPECS, ChartStack, LapTrace,
)

LENGTH_M = 13_600
RUNS = 7


def _lap(label: str, seed: int, pace: float) -> LapTrace:
    rng = np.random.default_rng(seed)
    grid = np.arange(float(LENGTH_M))
    speed = 60.0 + 25.0 * np.sin(grid / 700.0) + rng.normal(0.0, 0.3, grid.size)
    speed = np.clip(speed * pace, 15.0, None)
    elapsed = np.concatenate(([0.0], np.cumsum(1.0 / speed[1:])))
    throttle = np.clip(np.sin(grid / 300.0) * 2.0, 0.0, 1.0)
    return LapTrace(
        label=label, grid_m=grid, elapsed_s=elapsed,
        channels={
            "Ground Speed": speed,
            "Throttle Pos": throttle,
            "Brake Pos": 1.0 - throttle,
            "Steering Pos": np.sin(grid / 120.0) * 0.4,
            "Gear": np.clip(np.round(speed / 12.0), 1, 7),
            "Engine RPM": 4000.0 + speed * 40.0,
        },
    )


def _median_ms(action, runs: int = RUNS) -> float:
    samples = []
    for _ in range(runs):
        started = time.perf_counter()
        action()
        samples.append((time.perf_counter() - started) * 1000.0)
    return statistics.median(samples)


def main() -> None:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    theme.apply(app)
    chart = ChartStack()
    for spec in ROW_SPECS:
        chart.set_row_enabled(spec.key, True)
    chart.resize(1100, 900)
    chart.show()
    app.processEvents()

    primary, benchmark = _lap("Volta 2", 1, 1.0), _lap("Volta 1", 2, 1.01)
    delta = primary.elapsed_s - benchmark.elapsed_s

    def load() -> None:
        chart.show_laps(primary, benchmark, primary.grid_m, delta)
        chart.grab()

    positions = iter(np.linspace(100.0, LENGTH_M - 100.0, RUNS * 4))

    def cursor() -> None:
        # What a mouse move costs on screen: the cursor lines and the readout
        # move, and Qt repaints only what they dirtied.
        chart.set_cursor_distance(float(next(positions)))
        app.processEvents()

    offsets = iter(np.linspace(0.0, 4000.0, RUNS * 4))

    def pan() -> None:
        # Dragging along the lap: the view moves, so every layer is redrawn.
        start = float(next(offsets))
        chart._anchor.plot.setXRange(start, start + 3000.0, padding=0.0)
        app.processEvents()

    load()  # warm up: first paint builds caches
    results = {
        "load": _median_ms(load),
        "paint": _median_ms(chart.grab),
        "cursor": _median_ms(cursor),
        "pan": _median_ms(pan),
    }
    print(f"{LENGTH_M} m lap, {len(chart.visible_rows())} rows, 2 laps + delta, "
          f"median of {RUNS}:")
    for name, value in results.items():
        print(f"  {name:<7}{value:8.1f} ms")


if __name__ == "__main__":
    main()
