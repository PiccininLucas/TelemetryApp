"""The base every plot in the window is built on.

pyqtgraph out of the box has a look of its own - bright axis lines, its default
font at its default size, tick marks pointing everywhere - and each panel used
to configure it by hand, a little differently. This module is the one place a
plot is made, so the traces, the track map, the g-g diagram and the consistency
chart read as one instrument, styled from the theme like every other widget.

It also owns one rendering decision: **static layers are cached.** Moving the
cursor dirties a thin vertical strip, but repainting that strip made pyqtgraph
stroke every curve in the row again - thousands of points, clipped to a few
pixels. On a Le Mans lap with six rows that was ~80 ms per mouse move, five
frames. `freeze` gives curves and axes a device-coordinate cache, so repainting
the strip is a copy of pixels already drawn; the cache is redrawn only when the
view itself changes (pan, zoom, new data). See `scripts/bench_charts.py`.
"""

from __future__ import annotations

import pyqtgraph as pg
from PySide6 import QtGui, QtWidgets

from lmu_telemetry.presentation import theme

def tick_font() -> QtGui.QFont:
    """Tick labels: the caption step, with tabular figures so a column of
    numbers lines up and a changing number does not shift its neighbours."""
    return theme.figures(theme.font(theme.TYPE.caption))


def label_style() -> dict[str, str]:
    """Axis titles, in the form pyqtgraph's `setLabel` takes."""
    return {"color": theme.TEXT_MUTED, "font-size": f"{theme.TYPE.caption}px"}


def make_plot(
    *,
    left: str | None = None,
    bottom: str | None = None,
    grid: bool = True,
    axes: bool = True,
) -> pg.PlotWidget:
    """A plot styled from the theme.

    Args:
        left: Left-axis title, with its unit.
        bottom: Bottom-axis title, with its unit.
        grid: Faint grid lines at the major ticks.
        axes: False for a plot that is a picture, not a graph - the track map.
    """
    plot = pg.PlotWidget()
    plot.setBackground(theme.PLOT_BACKGROUND)
    plot.setMenuEnabled(False)
    if not axes:
        plot.hideAxis("left")
        plot.hideAxis("bottom")
        return plot

    for side in ("left", "bottom"):
        style_axis(plot.getAxis(side))
    if grid:
        plot.showGrid(x=True, y=True, alpha=theme.GRID_ALPHA)
    if left is not None:
        plot.setLabel("left", left, **label_style())
    if bottom is not None:
        plot.setLabel("bottom", bottom, **label_style())
    return plot


def style_axis(axis: pg.AxisItem) -> None:
    """A quiet axis: the line in the border colour, numbers muted, no tick
    marks sticking out - the grid already says where the ticks are.

    Every quantity here is read at its natural magnitude - 7000 rpm, 268 km/h,
    a delta of -0.51 s - so pyqtgraph's automatic SI prefix ("7 (x1000)") is off.
    """
    axis.setPen(pg.mkPen(theme.BORDER, width=1))
    axis.setTextPen(pg.mkPen(theme.TEXT_MUTED))
    # The grid is drawn by the ticks: they keep the muted colour, and the grid
    # alpha makes them faint.
    axis.setTickPen(pg.mkPen(theme.TEXT_MUTED))
    axis.setTickFont(tick_font())
    axis.setStyle(tickLength=0, tickTextOffset=6)
    axis.enableAutoSIPrefix(False)


def set_label(plot: pg.PlotWidget, side: str, text: str) -> None:
    """Retitle an axis, keeping the theme's style."""
    plot.setLabel(side, text, **label_style())


#: Bytes per pixel of a cached layer, and how many window-sized layers to make
#: room for: the stack's rows, each with its curves and axes, add up to about
#: six screens' worth when every row is on.
_BYTES_PER_PIXEL = 4
_LAYERS = 6
_CACHE_FLOOR_KB = 64 * 1024
_CACHE_CEILING_KB = 256 * 1024


def reserve_cache() -> int:
    """Make room for the cached layers; returns the limit set, in KB.

    Qt keeps every item cache in one global `QPixmapCache`, 10 MB by default.
    Six rows of cached curves need several times that, so each row's repaint
    evicted the row before it and every cache missed: the cursor cost 120 ms
    with caching on - more than without it. The limit is a ceiling, not an
    allocation: memory is used only as layers are actually drawn.
    """
    screen = QtGui.QGuiApplication.primaryScreen()
    pixels = 1920 * 1080
    if screen is not None:
        size = screen.size() * screen.devicePixelRatio()
        pixels = max(int(size.width() * size.height()), 1)
    wanted = pixels * _BYTES_PER_PIXEL * _LAYERS // 1024
    limit = max(_CACHE_FLOOR_KB, min(_CACHE_CEILING_KB, wanted))
    if QtGui.QPixmapCache.cacheLimit() < limit:
        QtGui.QPixmapCache.setCacheLimit(limit)
    return QtGui.QPixmapCache.cacheLimit()


def freeze(*items: QtWidgets.QGraphicsItem) -> None:
    """Cache items that do not move with the cursor. See the module docstring."""
    reserve_cache()
    for item in items:
        target = getattr(item, "curve", item)  # a PlotDataItem draws via its curve
        target.setCacheMode(QtWidgets.QGraphicsItem.CacheMode.DeviceCoordinateCache)
        scatter = getattr(item, "scatter", None)
        if scatter is not None:
            scatter.setCacheMode(QtWidgets.QGraphicsItem.CacheMode.DeviceCoordinateCache)


def freeze_axes(plot: pg.PlotWidget) -> None:
    for side in ("left", "bottom"):
        freeze(plot.getAxis(side))
