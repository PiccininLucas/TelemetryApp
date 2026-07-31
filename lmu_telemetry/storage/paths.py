"""Where the application keeps its data.

Everything the app writes lives under one directory, so uninstalling is deleting
one folder and nothing is ever written next to the game's own files.
"""

from __future__ import annotations

import os
from pathlib import Path

#: Root of the application's data, overridable for tests and for users who keep
#: their home directory on a small drive.
ENV_DATA_DIR = "LMU_TELEMETRY_DATA_DIR"

DEFAULT_DATA_DIR_NAME = ".lmu-telemetry"
CATALOG_FILENAME = "catalog.duckdb"
CACHE_DIR_NAME = "cache"


def data_dir() -> Path:
    """Return the application data directory, creating it if needed."""
    override = os.environ.get(ENV_DATA_DIR)
    root = Path(override) if override else Path.home() / DEFAULT_DATA_DIR_NAME
    root.mkdir(parents=True, exist_ok=True)
    return root


def catalog_path() -> Path:
    """Path to the historical catalog database."""
    return data_dir() / CATALOG_FILENAME


def cache_dir() -> Path:
    """Root of the per-session cache."""
    directory = data_dir() / CACHE_DIR_NAME
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def session_cache_dir(session_id: str) -> Path:
    """Cache folder for one session.

    Keyed on the source file's hash rather than its name: the same session
    recorded to two paths is one session, and a file edited in place gets a new
    folder instead of silently reusing stale derived data.
    """
    return cache_dir() / session_id
