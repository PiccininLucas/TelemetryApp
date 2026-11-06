"""Load `config/defaults.toml`, with an optional user file merged over it.

Every threshold used by ingestion and analysis lives in that file rather than
inline in the code. Thresholds are engineering choices that have to be
defensible and tunable per car and track, and a magic number buried in a
function is the fastest way to make an analysis impossible to audit.

**Overriding.** A user file - `config.toml` in the application's data directory,
or whichever file `LMU_TELEMETRY_CONFIG` names - is merged over the defaults, so
it holds only what the user changed. Every key in it must exist in the defaults:
a mistyped name that quietly fell back to the default is a setting the user
believes is applied and is not.
"""

from __future__ import annotations

import os
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any, Final

from lmu_telemetry.shared.errors import ConfigError
from lmu_telemetry.shared.logging_config import get_logger

logger = get_logger(__name__)

#: Shipped defaults, resolved relative to the package rather than the working
#: directory so the CLI behaves the same from anywhere.
DEFAULT_CONFIG_PATH: Final[Path] = (
    Path(__file__).resolve().parents[2] / "config" / "defaults.toml"
)

#: Names a user file other than the one in the data directory.
ENV_CONFIG_PATH: Final = "LMU_TELEMETRY_CONFIG"

#: Same variable `infrastructure.storage.paths` reads. Repeated here because
#: `shared` may not import `infrastructure`, and the user file has to be found
#: without creating anything.
_ENV_DATA_DIR: Final = "LMU_TELEMETRY_DATA_DIR"
_DEFAULT_DATA_DIR_NAME: Final = ".lmu-telemetry"
USER_CONFIG_FILENAME: Final = "config.toml"

#: Sentinel distinguishing "no default given" from "the default is None".
_MISSING: Final = object()


class Config:
    """Read-only view over the configuration tree.

    Access is by dotted path (`config.get("laps.max_time_mismatch_s")`) so no
    caller has to navigate nested dictionaries, and a missing key raises loudly
    instead of returning None that turns into a NaN three layers down.
    """

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def get(self, path: str, default: Any = _MISSING) -> Any:
        """Return the value at a dotted path.

        Raises:
            KeyError: The path is absent and no default was supplied.
        """
        node: Any = self._data
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                if default is _MISSING:
                    raise KeyError(f"Missing configuration key: {path!r}")
                return default
            node = node[part]
        return node

    def section(self, name: str) -> dict[str, Any]:
        """Return a whole section as a plain dictionary."""
        value = self.get(name, {})
        return dict(value) if isinstance(value, dict) else {}

    def as_dict(self) -> dict[str, Any]:
        return dict(self._data)


def user_config_path() -> Path:
    """Where the user's overrides live. The file need not exist."""
    named = os.environ.get(ENV_CONFIG_PATH)
    if named:
        return Path(named)
    data_dir = os.environ.get(_ENV_DATA_DIR)
    root = Path(data_dir) if data_dir else Path.home() / _DEFAULT_DATA_DIR_NAME
    return root / USER_CONFIG_FILENAME


def merge(defaults: dict[str, Any], overrides: dict[str, Any], _where: str = "") -> dict[str, Any]:
    """Overlay `overrides` on `defaults`, section by section.

    Raises:
        ConfigError: An override names a key the defaults do not have, or puts a
            value where the defaults have a section (or the reverse).
    """
    merged = dict(defaults)
    for key, value in overrides.items():
        dotted = f"{_where}{key}"
        if key not in defaults:
            raise ConfigError(f"Unknown configuration key: {dotted!r}")
        if isinstance(defaults[key], dict) != isinstance(value, dict):
            raise ConfigError(
                f"Configuration key {dotted!r} must be "
                f"{'a section' if isinstance(defaults[key], dict) else 'a value'}"
            )
        merged[key] = (
            merge(defaults[key], value, f"{dotted}.")
            if isinstance(value, dict) else value
        )
    return merged


def _read(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: not valid TOML ({exc})") from exc
    except OSError as exc:
        raise ConfigError(f"{path}: cannot be read ({exc})") from exc


@lru_cache(maxsize=None)
def _load(path: str, user_path: str | None, user_stamp: tuple[int, int] | None) -> Config:
    """The cached load. `user_stamp` is part of the key so that editing the user
    file takes effect without restarting."""
    data = _read(Path(path))
    if user_path is not None:
        data = merge(data, _read(Path(user_path)))
        logger.info("Configuration overridden from %s", user_path)
    logger.debug("Configuration loaded from %s", path)
    return Config(data)


def load_config(path: Path | str | None = None) -> Config:
    """Load and cache the configuration.

    Args:
        path: A complete configuration file to use instead of the defaults. No
            user file is merged over an explicit path - the caller named exactly
            what they want.

    Raises:
        ConfigError: The user file is invalid, or sets an unknown key.
    """
    if path is not None:
        return _load(str(Path(path)), None, None)

    user = user_config_path()
    if not user.is_file():
        return _load(str(DEFAULT_CONFIG_PATH), None, None)

    stat = user.stat()
    return _load(str(DEFAULT_CONFIG_PATH), str(user), (stat.st_mtime_ns, stat.st_size))
