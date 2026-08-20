"""Tests for build-php-extension.

The action captures the build script's stdout verbatim into the `extension-path`
output, so the script's stdout contract is load-bearing: one line, the path, and
nothing else. A progress line leaking onto stdout made the runner reject the whole
`$GITHUB_OUTPUT` write with "Unable to process file command 'output' successfully".
"""

import os
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "build-php-extension" / "scripts" / "build-out-of-workspace.sh"
_ACTION = _ROOT / "build-php-extension" / "action.yml"

_CRATE_NAME = "demo-ext"
_LIB_NAME = "demo_ext"

_STUB_CARGO = """#!/bin/bash
# A stub cargo that is noisy on both streams and materialises the artifact the
# script copies out, so the test exercises stdout discipline without a real build.
echo "stub cargo stdout noise: $*"
echo "stub cargo stderr noise: $*" >&2
mkdir -p target/release
touch "target/release/lib{lib}.so" "target/release/lib{lib}.dylib"
"""

_ROOT_MANIFEST = """[workspace]
resolver = "2"
members = ["crates/demo-ext"]
"""

_CRATE_MANIFEST = """[package]
name = "demo-ext"
version = "0.1.0"
edition = "2021"
license = "MIT"

[lib]
name = "demo_ext"
crate-type = ["cdylib"]

[dependencies]
sibling = { version = "1", path = "../sibling" }

[lints]
workspace = true
"""


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A minimal workspace whose binding crate inherits `workspace = true`."""
    crate_dir = tmp_path / "crates" / _CRATE_NAME
    (crate_dir / "src").mkdir(parents=True)
    (tmp_path / "Cargo.toml").write_text(_ROOT_MANIFEST)
    (tmp_path / "Cargo.lock").write_text('version = 4\n\n[[package]]\nname = "demo-ext"\nversion = "0.1.0"\n')
    (crate_dir / "Cargo.toml").write_text(_CRATE_MANIFEST)
    (crate_dir / "src" / "lib.rs").write_text("")
    return tmp_path


@pytest.fixture
def stub_cargo_path(tmp_path: Path) -> str:
    """PATH with a stub `cargo` that writes to stdout as well as stderr."""
    bin_dir = tmp_path / "stub-bin"
    bin_dir.mkdir()
    cargo = bin_dir / "cargo"
    cargo.write_text(_STUB_CARGO.format(lib=_LIB_NAME))
    cargo.chmod(0o755)
    return f"{bin_dir}{os.pathsep}{os.environ['PATH']}"


def _run(workspace: Path, path_env: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(_SCRIPT), _CRATE_NAME, _LIB_NAME, str(workspace)],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PATH": path_env},
    )


def test_stdout_is_only_the_extension_path(workspace: Path, stub_cargo_path: str):
    result = _run(workspace, stub_cargo_path)

    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert len(lines) == 1, f"stdout must carry only the result path, got: {lines}"
    assert lines[0] in {
        f"{workspace}/target/release/lib{_LIB_NAME}.so",
        f"{workspace}/target/release/lib{_LIB_NAME}.dylib",
    }


def test_workspace_strip_progress_goes_to_stderr(workspace: Path, stub_cargo_path: str):
    result = _run(workspace, stub_cargo_path)

    assert "Stripped workspace inheritance from binding crate Cargo.toml" in result.stderr
    assert "Stripped workspace inheritance" not in result.stdout


def test_missing_crate_dir_reports_on_stderr(tmp_path: Path, stub_cargo_path: str):
    result = _run(tmp_path, stub_cargo_path)

    assert result.returncode == 1
    assert result.stdout == ""
    assert "crate directory not found" in result.stderr


def test_action_keeps_only_the_last_stdout_line():
    content = _ACTION.read_text()
    assert "| tail -n 1" in content


def test_action_writes_output_with_heredoc_delimiter():
    content = _ACTION.read_text()
    assert "extension-path<<GHA_EXTENSION_PATH_EOF" in content
    assert 'echo "extension-path=$extension_path"' not in content
