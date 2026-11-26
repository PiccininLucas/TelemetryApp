"""Entry point.

    .venv\\Scripts\\python.exe main.py
    .venv\\Scripts\\python.exe main.py --smoke-test [screenshot.png]

The dependencies live in the project's virtual environment, not in the system
Python, so the interpreter matters. See `check_environment` below.

The same file is the entry point of the packaged `LMU Telemetry.exe`
(`packaging/lmu_telemetry.spec`). There, files that ship with the program -
the icon - are found under PyInstaller's unpack folder rather than next to
this file; `RESOURCE_ROOT` is whichever applies.

`--smoke-test` builds the window, opens the default lap as a user would, then
quits with 0 - optionally saving a screenshot. It is how a build is checked to
actually start: imports resolved, Qt plugins found, config bundled.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

#: Where bundled files live: PyInstaller's unpack folder in the .exe, the
#: project folder otherwise.
RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", PROJECT_ROOT))
ICON_PATH = RESOURCE_ROOT / "assets" / "app.ico"
SMOKE_TEST_FLAG = "--smoke-test"


def check_environment() -> None:
    """Fail with an explanation rather than a bare ModuleNotFoundError.

    Running `python main.py` picks up whichever Python is first on PATH, which
    on Windows is usually the system one - and the dependencies were installed
    into the project's `.venv`. The traceback that produces says only "No module
    named 'PySide6'", which does not point at the actual mistake.
    """
    try:
        import PySide6  # noqa: F401
        return
    except ImportError:
        pass

    venv_python = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    if not venv_python.exists():
        venv_python = PROJECT_ROOT / ".venv" / "bin" / "python"

    lines = [
        "",
        "As dependências não estão disponíveis neste interpretador Python.",
        f"  Interpretador em uso: {sys.executable}",
        "",
    ]
    if venv_python.exists():
        lines += [
            "O projeto tem um ambiente virtual. Rode o aplicativo com ele:",
            "",
            f"    {venv_python} main.py",
            "",
            "Ou ative o ambiente antes (PowerShell):",
            "",
            "    .venv\\Scripts\\Activate.ps1",
            "    python main.py",
        ]
    else:
        lines += [
            "O ambiente virtual ainda não existe. Crie e instale as dependências:",
            "",
            "    uv venv",
            "    uv pip install -r requirements.txt",
            "",
            "(ou: python -m venv .venv  e  .venv\\Scripts\\pip install -r requirements.txt)",
        ]

    # The Windows console defaults to a legacy code page, which mangles every
    # accented character in the message meant to help.
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    print("\n".join(lines), file=sys.stderr)
    raise SystemExit(1)


check_environment()

from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

from lmu_telemetry.composition import build_gateways  # noqa: E402
from lmu_telemetry.shared.config import load_config  # noqa: E402
from lmu_telemetry.shared.errors import ConfigError  # noqa: E402
from lmu_telemetry.shared.logging_config import setup_logging  # noqa: E402
from lmu_telemetry.infrastructure.storage import paths  # noqa: E402
from lmu_telemetry.shared import strings  # noqa: E402
from lmu_telemetry.presentation import theme  # noqa: E402
from lmu_telemetry.presentation.main_window import MainWindow  # noqa: E402


def _smoke_test(argv: list[str]) -> tuple[bool, Path | None]:
    """Whether `--smoke-test` was given, and the screenshot path after it."""
    if SMOKE_TEST_FLAG not in argv:
        return False, None
    position = argv.index(SMOKE_TEST_FLAG)
    following = argv[position + 1] if position + 1 < len(argv) else ""
    return True, (Path(following) if following and not following.startswith("-") else None)


def main(argv: list[str] | None = None) -> int:
    # The log file lives with the application's other data, so a session that
    # misbehaves can be reported together with the warnings it produced.
    setup_logging(level=logging.INFO, log_file=paths.data_dir() / "lmu-telemetry.log")

    argv = list(argv if argv is not None else sys.argv)
    smoke_test, screenshot = _smoke_test(argv)
    app = QtWidgets.QApplication(argv)
    # QSettings keys the saved window layout on both names.
    app.setOrganizationName("LMU Telemetry")
    app.setApplicationName(strings.APP_NAME)
    app.setApplicationDisplayName(strings.APP_NAME)
    if ICON_PATH.is_file():
        app.setWindowIcon(QtGui.QIcon(str(ICON_PATH)))

    # The user's configuration file is read lazily, deep inside the first lap to
    # be analysed. A mistake in it should be reported here, as what it is, and
    # not as a traceback from somewhere that looks unrelated.
    try:
        load_config()
    except ConfigError as exc:
        logging.getLogger(__name__).error("Invalid configuration: %s", exc)
        QtWidgets.QMessageBox.critical(
            None, strings.APP_NAME, strings.ERR_CONFIG_INVALID.format(detail=exc)
        )
        return 2

    # Before any widget is built: pyqtgraph reads its globals at construction.
    theme.apply(app)

    window = MainWindow(build_gateways())
    window.show()
    if smoke_test:
        # The window opened the default lap while it was built; give the event
        # loop a moment to paint it, then leave.
        def finish() -> None:
            if screenshot is not None:
                window.grab().save(str(screenshot))
            logging.getLogger(__name__).info("Smoke test passed")
            window.close()
            app.quit()

        QtCore.QTimer.singleShot(1500, finish)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
