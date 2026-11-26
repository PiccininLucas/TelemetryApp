"""Draw the application icon: `assets/app.ico`.

    .venv\\Scripts\\python.exe scripts\\make_icon.py

A dark tile in the window's own panel colour with a speed trace across it in
the accent - what the application is, at 16 px as at 256 px. Drawn with Qt so
the colours come from the theme, saved as a multi-size .ico with Pillow (a
matplotlib dependency, so already installed).
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image  # noqa: E402
from PySide6 import QtCore, QtGui  # noqa: E402

from lmu_telemetry.presentation import theme  # noqa: E402

OUTPUT = Path(__file__).resolve().parent.parent / "assets" / "app.ico"
SIZES = (16, 24, 32, 48, 64, 128, 256)

#: The trace, in a 0..1 square: a straight, a heavy brake into a slow corner,
#: and the climb back out - a lap's speed trace in four strokes.
TRACE = ((0.14, 0.34), (0.42, 0.24), (0.52, 0.70), (0.62, 0.62), (0.86, 0.30))


def draw(size: int) -> QtGui.QImage:
    image = QtGui.QImage(size, size, QtGui.QImage.Format.Format_ARGB32)
    image.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(image)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)

    radius = size * 0.2
    painter.setPen(QtCore.Qt.PenStyle.NoPen)
    painter.setBrush(QtGui.QColor(theme.SURFACE))
    painter.drawRoundedRect(QtCore.QRectF(0, 0, size, size), radius, radius)

    pen = QtGui.QPen(QtGui.QColor(theme.ACCENT))
    pen.setWidthF(max(size * 0.09, 1.6))
    pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(QtCore.Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
    painter.drawPolyline(QtGui.QPolygonF([QtCore.QPointF(x * size, y * size) for x, y in TRACE]))
    painter.end()
    return image


def to_pillow(image: QtGui.QImage) -> Image.Image:
    buffer = QtCore.QBuffer()
    buffer.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return Image.open(io.BytesIO(bytes(buffer.data()))).convert("RGBA")


def main() -> None:
    app = QtGui.QGuiApplication.instance() or QtGui.QGuiApplication([])  # noqa: F841
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    largest = to_pillow(draw(SIZES[-1]))
    # Each size drawn on its own, not scaled down: the stroke keeps a readable
    # width at 16 px instead of thinning to a smudge.
    frames = [to_pillow(draw(size)) for size in SIZES]
    largest.save(OUTPUT, format="ICO", sizes=[(s, s) for s in SIZES],
                 append_images=frames[:-1])
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    main()
