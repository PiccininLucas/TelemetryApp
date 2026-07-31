"""Load `config/defaults.toml`.

Every threshold used by ingestion and analysis lives in that file rather than
inline in the code. Thresholds are engineering choices that have to be
defensible and tunable per car and track, and a magic number buried in a
function is the fastest way to make an analysis impossible to audit.
"""

from __future__ import annotations

import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any, Final

from lmu_telemetry.logging_config import get_logger

logger = get_logger(__name__)

#: Shipped defaults, resolved relative to the package rather than the working
#: directory so the CLI behaves the same from anywhere.
DEFAULT_CONFIG_PATH: Final[Path] = (
    Path(__file__).resolve().parents[2] / "config" / "defaults.toml"
)

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


@lru_cache(maxsize=None)
def load_config(path: Path | str | None = None) -> Config:
    """Load and cache the configuration.

    Args:
        path: Override for the config file. Defaults to `config/defaults.toml`.
    """
    resolved = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    with resolved.open("rb") as handle:
        data = tomllib.load(handle)
    logger.debug("Configuration loaded from %s", resolved)
    return Config(data)
