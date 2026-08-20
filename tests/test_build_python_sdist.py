"""Wiring tests for the build-python-sdist action. The actual rewrite is alef's
(tested there) and maturin's; here we assert the action installs the rewrite +
runs maturin in both package-dir and manifest-path modes.

The split-layout isolation is exercised for real against stub `cargo`/`maturin`
binaries: it has to produce a self-consistent tree, and a missing readme there
fails maturin's metadata parse outright."""

import os
import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def _read() -> str:
    path = _ROOT / "build-python-sdist" / "action.yml"
    assert path.is_file(), f"missing {path}"
    return path.read_text()


def test_runs_rewrite_then_maturin():
    content = _read()
    assert "uses: xberg-io/actions/rewrite-native-deps@v1" in content
    assert "lang: python" in content
    assert "scripts/build-out-of-workspace.sh" in content


def test_rewrite_is_opt_outable_and_default_on():
    content = _read()
    assert "rewrite-native-deps:" in content
    assert "if: inputs.rewrite-native-deps == 'true'" in content
    assert 'default: "true"' in content


def test_supports_both_package_dir_and_manifest_path_modes():
    content = _read()
    assert 'input_path="${INPUT_MANIFEST_PATH:-${INPUT_PACKAGE_DIR}}"' in content


def test_output_dir_resolved_under_workspace():
    content = _read()
    assert 'out="${GITHUB_WORKSPACE}/${INPUT_OUTPUT_DIR}"' in content


_SCRIPT = _ROOT / "build-python-sdist" / "scripts" / "build-out-of-workspace.sh"

_ROOT_MANIFEST = """[workspace]
resolver = "2"
members = ["crates/demo-py"]

[workspace.package]
version = "1.2.3"
edition = "2021"
license = "MIT"
readme = "README.md"

[workspace.dependencies]
demo-rs = { version = "1.2.3", path = "crates/demo" }
"""

_PYPROJECT = """[build-system]
build-backend = "maturin"
requires = ["maturin>=1,<2"]

[project]
name = "demo"
version = "1.2.3"

[tool.maturin]
manifest-path = "../../crates/demo-py/Cargo.toml"
"""

_CRATE_MANIFEST = """[package]
name = "demo-py"
version.workspace = true
edition = "2021"
license.workspace = true
{readme}

[lib]
name = "demo"
crate-type = ["cdylib"]

[dependencies]
demo-rs = {{ version = "1.2.3", path = "../demo" }}
"""

_STUB_CARGO = """#!/bin/bash
touch Cargo.lock
"""

# ~keep The isolated tree is deleted when the script exits, so the stub records its
# contents while maturin would be running. The fixture puts the package two levels
# below the isolated root, matching the split layout the script builds.
_STUB_MATURIN = """#!/bin/bash
iso_root=$(cd ../.. && pwd)
find "$iso_root" -type f | sed "s|^$iso_root/||" | sort >"$STUB_MATURIN_REPORT"
"""


def _split_layout(tmp_path: Path, readme_key: str) -> Path:
    workspace = tmp_path / "ws"
    (workspace / "packages" / "python").mkdir(parents=True)
    (workspace / "crates" / "demo-py" / "src").mkdir(parents=True)
    (workspace / "Cargo.toml").write_text(_ROOT_MANIFEST)
    (workspace / "README.md").write_text("# Demo\n\nThe real long description.\n")
    (workspace / "packages" / "python" / "pyproject.toml").write_text(_PYPROJECT)
    (workspace / "crates" / "demo-py" / "Cargo.toml").write_text(_CRATE_MANIFEST.format(readme=readme_key))
    (workspace / "crates" / "demo-py" / "src" / "lib.rs").write_text("")
    return workspace


def _run_isolation(workspace: Path, tmp_path: Path) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    bin_dir = tmp_path / "stub-bin"
    bin_dir.mkdir()
    for name, body in (("cargo", _STUB_CARGO), ("maturin", _STUB_MATURIN)):
        stub = bin_dir / name
        stub.write_text(body)
        stub.chmod(0o755)

    report = tmp_path / "iso-tree.txt"
    out_dir = tmp_path / "dist"
    out_dir.mkdir()
    result = subprocess.run(
        ["bash", str(_SCRIPT), "packages/python", str(out_dir), str(workspace)],
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "STUB_MATURIN_REPORT": str(report),
        },
    )
    listed = report.read_text().splitlines() if report.is_file() else []
    return result, listed


def test_split_layout_materializes_inherited_readme(tmp_path: Path):
    workspace = _split_layout(tmp_path, "readme.workspace = true")

    result, listed = _run_isolation(workspace, tmp_path)

    assert result.returncode == 0, result.stderr
    assert "README.md" in listed, f"workspace readme missing from the isolated tree: {listed}"


def test_split_layout_materializes_crate_relative_readme(tmp_path: Path):
    workspace = _split_layout(tmp_path, 'readme = "../../README.md"')

    result, listed = _run_isolation(workspace, tmp_path)

    assert result.returncode == 0, result.stderr
    assert "README.md" in listed, f"crate-relative readme missing from the isolated tree: {listed}"


def test_split_layout_without_readme_key_copies_nothing(tmp_path: Path):
    workspace = _split_layout(tmp_path, "")

    result, listed = _run_isolation(workspace, tmp_path)

    assert result.returncode == 0, result.stderr
    assert "README.md" not in listed
