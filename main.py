"""Entry point.

    .venv\\Scripts\\python.exe main.py

The dependencies live in the project's virtual environment, not in the system
Python, so the interpreter matters. See `check_environment` below.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))


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

from PySide6 import QtWidgets  # noqa: E402

from lmu_telemetry.logging_config import setup_logging  # noqa: E402
from lmu_telemetry.storage import paths  # noqa: E402
from lmu_telemetry.ui import strings, theme  # noqa: E402
from lmu_telemetry.ui.main_window import MainWindow  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    # The log file lives with the application's other data, so a session that
    # misbehaves can be reported together with the warnings it produced.
    setup_logging(level=logging.INFO, log_file=paths.data_dir() / "lmu-telemetry.log")

    app = QtWidgets.QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(strings.APP_NAME)
    app.setApplicationDisplayName(strings.APP_NAME)

    # Before any widget is built: pyqtgraph reads its globals at construction.
    theme.apply(app)

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
