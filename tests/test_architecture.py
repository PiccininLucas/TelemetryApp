"""Enforce the layering rule that makes the analysis testable.

`lmu_telemetry.analysis` must depend on nothing but numpy, scipy and the
standard library. Two things rely on it: every formula can be tested against
synthetic data with the game absent, and a live data source could feed the same
functions later without touching a single equation.

The check follows the **transitive** import closure, not just each module's own
imports. A direct-imports-only check passes happily while `analysis` reaches
`ingest` through `core`, which is exactly the kind of drift that goes unnoticed.

One exception is allowed and is itself tested: `ui.strings`. The specification
requires all user-visible text to live in one module, `core` raises errors
carrying user-visible messages, and `analysis` reaches `core`. That is only
harmless because `ui.strings` is pure data importing nothing at all, which
`test_strings_module_is_a_leaf` verifies.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_ROOT = PROJECT_ROOT / "lmu_telemetry"
PACKAGE = "lmu_telemetry"

#: Third-party modules `analysis` may never import.
FORBIDDEN_EXTERNAL = (
    "duckdb", "pandas", "PySide6", "shiboken6", "pyqtgraph",
    "matplotlib", "reportlab", "pyarrow",
)

#: Internal packages `analysis` may never reach, directly or transitively.
FORBIDDEN_INTERNAL = (
    f"{PACKAGE}.ingest",
    f"{PACKAGE}.ui",
    f"{PACKAGE}.storage",
    f"{PACKAGE}.export",
)

#: Documented exception: a pure-data leaf, proven leaf-like by its own test.
ALLOWED_INTERNAL_EXCEPTIONS = frozenset({f"{PACKAGE}.ui.strings", f"{PACKAGE}.ui"})


def module_name_for(path: Path) -> str:
    """`lmu_telemetry/analysis/delta.py` -> `lmu_telemetry.analysis.delta`."""
    relative = path.relative_to(PROJECT_ROOT).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def imports_of(path: Path) -> set[str]:
    """Every module name imported by one source file, resolved absolutely."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative import
                continue
            if node.module:
                names.add(node.module)
                # `from x.y import z` may be importing the module `x.y.z`.
                names.update(f"{node.module}.{a.name}" for a in node.names)

    return names


def path_for(module: str) -> Path | None:
    """Locate a project module's source file."""
    relative = Path(*module.split("."))
    for candidate in (
        PROJECT_ROOT / relative.with_suffix(".py"),
        PROJECT_ROOT / relative / "__init__.py",
    ):
        if candidate.is_file():
            return candidate
    return None


def transitive_imports(start: Path) -> dict[str, list[str]]:
    """Every module reachable from `start`, mapped to how it was reached.

    Returns:
        Module name -> the import chain that led to it, so a failure can name
        the actual path rather than only the endpoint.
    """
    reached: dict[str, list[str]] = {}
    queue: list[tuple[Path, list[str]]] = [(start, [module_name_for(start)])]

    while queue:
        current, chain = queue.pop()
        for imported in sorted(imports_of(current)):
            if imported in reached:
                continue
            reached[imported] = chain + [imported]

            if imported.startswith(PACKAGE):
                source = path_for(imported)
                if source is not None:
                    queue.append((source, chain + [imported]))

    return reached


def analysis_modules() -> list[Path]:
    return sorted((PACKAGE_ROOT / "analysis").rglob("*.py"))


def test_analysis_package_exists():
    assert (PACKAGE_ROOT / "analysis").is_dir()


@pytest.mark.parametrize("path", analysis_modules(), ids=lambda p: p.name)
def test_analysis_layer_stays_pure(path: Path):
    """No module reachable from `analysis` may touch a forbidden dependency."""
    for module, chain in transitive_imports(path).items():
        if module in ALLOWED_INTERNAL_EXCEPTIONS:
            continue

        root = module.split(".")[0]
        assert root not in FORBIDDEN_EXTERNAL, (
            f"{path.name} reaches {module!r} via {' -> '.join(chain)}. "
            f"The analysis layer takes numpy arrays and returns numbers; move "
            f"the {root} dependency to the caller."
        )

        for forbidden in FORBIDDEN_INTERNAL:
            assert not (module == forbidden or module.startswith(forbidden + ".")), (
                f"{path.name} reaches {module!r} via {' -> '.join(chain)}. "
                f"The analysis layer must not depend on {forbidden}."
            )


def test_strings_module_is_a_leaf():
    """The one allowed exception must stay harmless.

    `ui.strings` is reachable from `analysis` through `core`. That is acceptable
    only while it imports nothing from this project - the moment it imports Qt,
    the exception stops being free and this test says so.
    """
    strings = PACKAGE_ROOT / "ui" / "strings.py"
    internal = [m for m in imports_of(strings) if m.startswith(PACKAGE)]
    assert internal == [], (
        f"ui/strings.py must import nothing from {PACKAGE}, but imports {internal}. "
        f"It is allowed as an exception to the layering rule precisely because "
        f"it is pure data."
    )


def test_analysis_does_not_render_text():
    """Analysis returns numbers. Formatting belongs to whoever displays them."""
    for path in analysis_modules():
        for module in imports_of(path):
            assert "strings" not in module, (
                f"{path.name} imports {module!r}; analysis must not format text."
            )


def test_core_does_not_depend_on_ingest_or_storage():
    """`core` is the bottom of the stack and must stay there."""
    for path in sorted((PACKAGE_ROOT / "core").rglob("*.py")):
        for module in imports_of(path):
            for forbidden in (f"{PACKAGE}.ingest", f"{PACKAGE}.storage",
                              f"{PACKAGE}.analysis", f"{PACKAGE}.export"):
                assert not module.startswith(forbidden), (
                    f"core/{path.name} imports {module!r}"
                )


def test_ingest_does_not_depend_on_storage_or_ui():
    """Reading files must not know where the app keeps things, nor how it draws
    them - that is what would let a live source replace the file reader."""
    for path in sorted((PACKAGE_ROOT / "ingest").rglob("*.py")):
        for module in imports_of(path):
            for forbidden in (f"{PACKAGE}.storage", f"{PACKAGE}.export"):
                assert not module.startswith(forbidden), (
                    f"ingest/{path.name} imports {module!r}"
                )
            assert not module.startswith("PySide6"), (
                f"ingest/{path.name} imports Qt"
            )


def test_expected_schema_is_only_used_by_the_inspection_script():
    """`scripts/expected_schema.py` is a hypothesis to check, not a source of
    truth. Production code derives every layout from the file's own DESCRIBE."""
    for path in PACKAGE_ROOT.rglob("*.py"):
        modules = imports_of(path)
        assert not any("expected_schema" in m for m in modules), (
            f"{path.relative_to(PROJECT_ROOT)} imports the documented schema. "
            f"Channel layouts must come from the file itself."
        )
