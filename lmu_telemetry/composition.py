"""Composition root: the one place that wires the layers together.

Nothing else may import this module - the interface receives its gateways as
arguments, which is what keeps `presentation` independent of `infrastructure`.
Entry points (`main.py`, the scripts, the tests) call `build_gateways` and hand
the result in.
"""

from __future__ import annotations

from lmu_telemetry.infrastructure.adapters import build_gateways

__all__ = ["build_gateways"]
