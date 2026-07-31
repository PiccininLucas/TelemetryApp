"""Single place where logging is configured.

The project uses `logging`, never `print`. A telemetry pipeline fails in ways
that only show up on one specific session file, so the warnings it emits (drift
corrected, channel missing, unit unrecognised) have to survive into a log file
the user can send along with the file that broke.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

_LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)-38s %(message)s"
_DATE_FORMAT = "%H:%M:%S"

_configured = False


def setup_logging(
    level: int = logging.INFO,
    log_file: Path | None = None,
) -> None:
    """Configure the root logger once per process.

    Args:
        level: Threshold for the console handler.
        log_file: Optional file that additionally receives DEBUG and above.
            The file handler is deliberately more verbose than the console:
            the console is for the user, the file is for diagnosing a bad
            session file after the fact.
    """
    global _configured
    if _configured:
        return

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    console = logging.StreamHandler(sys.stderr)
    console.setLevel(level)
    console.setFormatter(logging.Formatter(_LOG_FORMAT, _DATE_FORMAT))
    root.addHandler(console)

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(_LOG_FORMAT, _DATE_FORMAT))
        root.addHandler(file_handler)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Return the module logger. Thin wrapper, kept so modules import one name."""
    return logging.getLogger(name)
