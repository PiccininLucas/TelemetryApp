"""Enforce the Clean Architecture layering.

    presentation ─┐
                  ├─> application ─> domain ─> shared
    infrastructure┘

Dependencies point inward only:

- `shared`: cross-cutting kernel (user-visible strings, errors, configuration,
  logging, formatting). Imports nothing from the rest of the project.
- `domain`: models, units, resampling and every formula in `domain.analysis`.
  Numpy, scipy and the standard library only.
- `application`: the pipeline that joins the two, and the ports (`SessionData`)
  it reads data through. Knows no file format, no database, no GUI.
- `infrastructure`: DuckDB ingestion, the catalog and cache, export. Implements
  what the layers above need.
- `presentation`: the PySide6 interface.

Two things rely on this: every formula can be tested against synthetic data with
the game absent, and a live data source could feed the same pipeline later
without touching a single equation.

The domain check follows the **transitive** import closure, not just each
module's own imports. A direct-imports-only check passes happily while the
domain reaches infrastructure through a third module, which is exactly the kind
of drift that goes unnoticed.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_ROOT = PROJECT_ROOT / "lmu_telemetry"
PACKAGE = "lmu_telemetry"

#: Each layer and the layers it may import (itself always allowed).
ALLOWED_LAYERS: dict[str, frozenset[str]] = {
    "shared": frozenset({"shared"}),
    "domain": frozenset({"domain", "shared"}),
    "application": frozenset({"application", "domain", "shared"}),
    "infrastructure": frozenset({"infrastructure", "application", "domain", "shared"}),
    "presentation": frozenset({"presentation", "application", "domain", "shared"}),
}

#: Third-party modules the inner layers may never import.
FORBIDDEN_EXTERNAL_INNER = (
    "duckdb", "pandas", "PySide6", "shiboken6", "pyqtgraph",
    "matplotlib", "reportlab", "pyarrow",
)

#: KNOWN DEBT, not a design. These presentation modules still reach
#: infrastructure directly: `MainWindow` opens the catalog, loads sessions and
#: writes exports itself, and `SessionBrowser` queries the catalog. The way out
#: is to give them gateways (ports in `application`, injected from `main.py`).
#: The list may only shrink: `test_presentation_debt_is_not_stale` fails when an
#: entry no longer applies, and any new reach fails `test_layer_dependencies`.
PRESENTATION_INFRASTRUCTURE_DEBT: dict[str, frozenset[str]] = {
    f"{PACKAGE}.presentation.main_window": frozenset({
        f"{PACKAGE}.infrastructure.export",
        f"{PACKAGE}.infrastructure.ingest.session_loader",
        f"{PACKAGE}.infrastructure.storage",
    }),
    f"{PACKAGE}.presentation.session_browser": frozenset({
        f"{PACKAGE}.infrastructure.storage",
    }),
}


def module_name_for(path: Path) -> str:
    """`lmu_telemetry/domain/analysis/delta.py` -> `lmu_telemetry.domain.analysis.delta`."""
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
    """Every module reachable from `start`, mapped to how it was reached."""
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


def layer_of(module: str) -> str | None:
    """`lmu_telemetry.domain.models` -> `domain`; None for anything else."""
    parts = module.split(".")
    if len(parts) >= 2 and parts[0] == PACKAGE and parts[1] in ALLOWED_LAYERS:
        return parts[1]
    return None


def modules_in(layer: str) -> list[Path]:
    return sorted(
        p for p in (PACKAGE_ROOT / layer).rglob("*.py") if "__pycache__" not in p.parts
    )


def _is_debt(importer: str, imported: str) -> bool:
    return any(
        imported == allowed or imported.startswith(allowed + ".")
        for allowed in PRESENTATION_INFRASTRUCTURE_DEBT.get(importer, ())
    )


# --- structure ---------------------------------------------------------------


@pytest.mark.parametrize("layer", sorted(ALLOWED_LAYERS))
def test_layer_package_exists(layer: str):
    assert (PACKAGE_ROOT / layer / "__init__.py").is_file()


def test_every_module_belongs_to_a_layer():
    """A stray module at the package root would sit outside the rule."""
    strays = [
        p.name for p in PACKAGE_ROOT.glob("*.py") if p.name != "__init__.py"
    ] + [
        d.name for d in PACKAGE_ROOT.iterdir()
        if d.is_dir() and d.name != "__pycache__" and d.name not in ALLOWED_LAYERS
    ]
    assert strays == [], f"outside every layer: {strays}"


# --- dependency rule ---------------------------------------------------------


@pytest.mark.parametrize("layer", sorted(ALLOWED_LAYERS))
def test_layer_dependencies(layer: str):
    """Each module imports only its own layer and the ones inside it."""
    allowed = ALLOWED_LAYERS[layer]
    offenders: list[str] = []

    for path in modules_in(layer):
        importer = module_name_for(path)
        for imported in sorted(imports_of(path)):
            target = layer_of(imported)
            if target is None or target in allowed:
                continue
            if layer == "presentation" and _is_debt(importer, imported):
                continue
            offenders.append(f"{importer} imports {imported}")

    assert offenders == [], (
        f"`{layer}` may only depend on {sorted(allowed)}:\n  " + "\n  ".join(offenders)
    )


def test_presentation_debt_is_not_stale():
    """Remove an entry once the module stops reaching infrastructure."""
    stale: list[str] = []
    for importer, allowed in PRESENTATION_INFRASTRUCTURE_DEBT.items():
        path = path_for(importer)
        imports = imports_of(path) if path else set()
        for entry in sorted(allowed):
            if not any(i == entry or i.startswith(entry + ".") for i in imports):
                stale.append(f"{importer}: {entry}")
    assert stale == [], "debt entries no longer needed:\n  " + "\n  ".join(stale)


@pytest.mark.parametrize(
    "path", modules_in("domain") + modules_in("application"),
    ids=lambda p: str(p.relative_to(PACKAGE_ROOT)),
)
def test_inner_layers_stay_pure(path: Path):
    """No module reachable from the domain or application may touch a
    forbidden library or an outer layer - however indirectly."""
    layer = layer_of(module_name_for(path))
    allowed = ALLOWED_LAYERS[layer]

    for module, chain in transitive_imports(path).items():
        root = module.split(".")[0]
        assert root not in FORBIDDEN_EXTERNAL_INNER, (
            f"{path.name} reaches {module!r} via {' -> '.join(chain)}. "
            f"Inner layers take numpy arrays and return numbers; move the "
            f"{root} dependency to infrastructure."
        )
        target = layer_of(module)
        assert target is None or target in allowed, (
            f"{path.name} reaches {module!r} via {' -> '.join(chain)}, "
            f"which is in `{target}`; `{layer}` may not depend on it."
        )


# --- specific guarantees -----------------------------------------------------


def test_strings_module_is_a_leaf():
    """`shared.strings` is reachable from every layer, so it must stay harmless:
    pure data that imports nothing from this project."""
    strings = PACKAGE_ROOT / "shared" / "strings.py"
    internal = [m for m in imports_of(strings) if m.startswith(PACKAGE)]
    assert internal == [], (
        f"shared/strings.py must import nothing from {PACKAGE}, but imports "
        f"{internal}. It is shared by every layer precisely because it is pure data."
    )


def test_analysis_does_not_render_text():
    """Analysis returns numbers. Formatting belongs to whoever displays them."""
    for path in sorted((PACKAGE_ROOT / "domain" / "analysis").rglob("*.py")):
        for module in imports_of(path):
            assert "strings" not in module, (
                f"{path.name} imports {module!r}; analysis must not format text."
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
