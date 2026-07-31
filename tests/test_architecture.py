"""Enforce the layering rule that makes the analysis testable.

`lmu_telemetry.analysis` must depend on nothing but numpy and the standard
library. Two things rely on it: every formula can be tested against synthetic
data with the game absent, and a live data source could feed the same functions
later without touching a single equation.

The rule is easy to state and easy to break by accident - one convenient
`from lmu_telemetry.ingest import ...` while debugging is all it takes - so it
is checked mechanically rather than by review. The check parses imports with
`ast` instead of matching text, so a name inside a comment or a docstring
cannot trip it.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ANALYSIS_DIR = PROJECT_ROOT / "lmu_telemetry" / "analysis"

#: Modules `analysis` may never import, directly or indirectly.
FORBIDDEN_PREFIXES = (
    "duckdb",
    "pandas",
    "PySide6",
    "pyqtgraph",
    "matplotlib",
    "reportlab",
    "lmu_telemetry.ingest",
    "lmu_telemetry.ui",
    "lmu_telemetry.storage",
    "lmu_telemetry.export",
)


def imported_modules(source: str) -> list[str]:
    """Return every module name imported by a Python source file."""
    tree = ast.parse(source)
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.append(node.module)
    return names


def analysis_modules() -> list[Path]:
    return sorted(ANALYSIS_DIR.rglob("*.py"))


def test_analysis_package_exists():
    assert ANALYSIS_DIR.is_dir()


@pytest.mark.parametrize(
    "path", analysis_modules(), ids=lambda p: p.name
)
def test_analysis_layer_stays_pure(path: Path):
    source = path.read_text(encoding="utf-8")
    for module in imported_modules(source):
        for forbidden in FORBIDDEN_PREFIXES:
            assert not (module == forbidden or module.startswith(forbidden + ".")), (
                f"{path.relative_to(PROJECT_ROOT)} imports {module!r}. "
                f"The analysis layer must take numpy arrays and return numbers; "
                f"move the {forbidden} dependency to the caller."
            )


def test_ui_strings_are_not_imported_by_analysis():
    """Analysis returns numbers, never rendered text. Formatting belongs to the
    layer that displays it."""
    for path in analysis_modules():
        assert "strings" not in imported_modules(path.read_text(encoding="utf-8"))


def test_expected_schema_is_only_used_by_the_inspection_script():
    """`scripts/expected_schema.py` is a hypothesis to check, not a source of
    truth. Production code derives every layout from the file's own DESCRIBE."""
    package = PROJECT_ROOT / "lmu_telemetry"
    for path in package.rglob("*.py"):
        modules = imported_modules(path.read_text(encoding="utf-8"))
        assert not any("expected_schema" in m for m in modules), (
            f"{path.relative_to(PROJECT_ROOT)} imports the documented schema. "
            f"Channel layouts must come from the file itself."
        )
