"""Entry point.

    python main.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

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
