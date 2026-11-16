"""The packaged build: what the .exe needs and how it is checked.

Building the .exe takes a couple of minutes and lives in
`scripts/build_exe.ps1`, which smoke-tests its own output. These are the fast
guarantees the build rests on.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "packaging" / "lmu_telemetry.spec"


def _spec_datas() -> list[tuple[str, str]]:
    """The (source, destination) pairs of the spec's `datas`, read without
    running PyInstaller."""
    tree = ast.parse(SPEC.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "datas":
            pairs = []
            for element in node.value.elts:
                source, destination = element.elts
                # In source order: ast.walk is breadth-first, which would put
                # the last part of ROOT / "config" / "defaults.toml" first.
                constants = sorted(
                    (p for p in ast.walk(source)
                     if isinstance(p, ast.Constant) and isinstance(p.value, str)),
                    key=lambda p: p.col_offset,
                )
                parts = [p.value for p in constants]
                pairs.append(("/".join(parts), destination.value))
            return pairs
    raise AssertionError("the spec has no datas")


def test_every_bundled_file_exists():
    for source, _destination in _spec_datas():
        assert (ROOT / source).is_file(), source


def test_the_defaults_land_where_the_config_loader_looks():
    """`shared/config.py` finds defaults.toml two levels above the package -
    in the .exe, `_internal/config/defaults.toml`."""
    from lmu_telemetry.shared import config

    assert ("config/defaults.toml", "config") in _spec_datas()
    relative = config.DEFAULT_CONFIG_PATH.relative_to(ROOT)
    assert relative.as_posix() == "config/defaults.toml"


def test_the_icon_is_bundled_where_main_looks():
    import main

    assert ("assets/app.ico", "assets") in _spec_datas()
    assert main.ICON_PATH.relative_to(main.RESOURCE_ROOT).as_posix() == "assets/app.ico"
    assert main.ICON_PATH.is_file()


def test_the_icon_has_every_size_windows_asks_for():
    from PIL import Image

    with Image.open(ROOT / "assets" / "app.ico") as icon:
        sizes = icon.info["sizes"]
    assert {(16, 16), (32, 32), (48, 48), (256, 256)} <= set(sizes)


def test_the_build_requirements_include_the_runtime_ones():
    text = (ROOT / "requirements-build.txt").read_text(encoding="utf-8")
    assert "-r requirements.txt" in text
    assert "pyinstaller==" in text


@pytest.mark.parametrize(("argv", "expected"), [
    (["main.py"], (False, None)),
    (["main.py", "--smoke-test"], (True, None)),
    (["main.py", "--smoke-test", "shot.png"], (True, Path("shot.png"))),
    (["main.py", "--smoke-test", "-platform", "offscreen"], (True, None)),
])
def test_smoke_test_arguments(argv, expected):
    import main

    assert main._smoke_test(argv) == expected


def test_the_smoke_test_opens_the_demo_and_exits_cleanly(tmp_path):
    """What build_exe.ps1 runs against the .exe, run here against the source:
    the window opens the demo lap and the process exits 0."""
    demo = sorted((ROOT / "data" / "demo").glob("*.duckdb"))
    if not demo:
        pytest.skip("no demo dataset in the tree")
    env = {**os.environ, "LMU_TELEMETRY_DATA_DIR": str(tmp_path),
           "QT_QPA_PLATFORM": "offscreen"}
    subprocess.run(
        [sys.executable, "-c",
         "from pathlib import Path; from lmu_telemetry.infrastructure.storage import "
         f"importer; importer.import_session_file(Path(r'{demo[0]}'))"],
        cwd=ROOT, env=env, check=True, capture_output=True,
    )
    shot = tmp_path / "shot.png"
    result = subprocess.run(
        [sys.executable, str(ROOT / "main.py"), "--smoke-test", str(shot)],
        cwd=ROOT, env=env, capture_output=True, timeout=120,
    )
    log = (tmp_path / "lmu-telemetry.log").read_text(encoding="utf-8")
    assert result.returncode == 0, log
    assert "Smoke test passed" in log
    assert "Loaded " in log            # the demo lap was opened, not just the window
    assert shot.is_file() and shot.stat().st_size > 0
