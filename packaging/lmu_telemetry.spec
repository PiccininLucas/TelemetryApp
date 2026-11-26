# PyInstaller build of LMU Telemetry: one folder, no console.
#
#     .\scripts\build_exe.ps1            (or)
#     .venv\Scripts\python.exe -m PyInstaller packaging\lmu_telemetry.spec --noconfirm --clean
#
# Output: dist\LMU Telemetry\LMU Telemetry.exe, with its libraries beside it in
# _internal\. One folder rather than one file: a single-file build unpacks
# everything to a temporary folder on every launch, seconds of waiting each
# time, while a folder opens directly.
#
# What has to travel with the code:
# - config/defaults.toml, found by `shared/config.py` relative to the package,
#   i.e. at _internal/config/defaults.toml;
# - assets/app.ico, the window icon (found through sys._MEIPASS in main.py).
# User data never goes in here: the catalog, cache, log and user config live in
# %USERPROFILE%\.lmu-telemetry, so replacing the program keeps every session.

from pathlib import Path

ROOT = Path(SPECPATH).parent
NAME = "LMU Telemetry"

# Never imported by the application, but pulled in by optional imports in its
# dependencies; leaving them out keeps the folder smaller and the build honest.
EXCLUDES = [
    "tkinter", "_tkinter",                      # matplotlib's Tk backend
    "PyQt5", "PyQt6", "PySide2",                # pyqtgraph probes for these
    "IPython", "jupyter", "notebook", "ipykernel",
    "pytest", "_pytest", "tests",
    "pyqtgraph.opengl", "OpenGL",               # 3-D, unused
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore",
    "PySide6.QtMultimedia", "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtPdf",
]

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    datas=[
        (str(ROOT / "config" / "defaults.toml"), "config"),
        (str(ROOT / "assets" / "app.ico"), "assets"),
    ],
    hiddenimports=[],
    excludes=EXCLUDES,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=NAME,
    icon=str(ROOT / "assets" / "app.ico"),
    console=False,
    upx=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name=NAME,
    upx=False,
)
