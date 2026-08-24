"""Tests for build-php-extension.

The action captures the build script's stdout verbatim into the `extension-path`
output, so the script's stdout contract is load-bearing: one line, the path, and
nothing else. A progress line leaking onto stdout made the runner reject the whole
`$GITHUB_OUTPUT` write with "Unable to process file command 'output' successfully".
"""

import os
import pathlib
import subprocess
from pathlib import Path

import pytest
import tomlkit

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "build-php-extension" / "scripts" / "build-out-of-workspace.sh"
_ACTION = _ROOT / "build-php-extension" / "action.yml"

_CRATE_NAME = "demo-ext"
_LIB_NAME = "demo_ext"

_STUB_CARGO = """#!/bin/bash
# A stub cargo that is noisy on both streams and materialises the artifact the
# script copies out, so the test exercises stdout discipline without a real build.
# It also copies the rewritten manifest out of the build dir: the script builds under
# `mktemp -d` and deletes it on EXIT, so a test that looks for the manifest under the
# workspace afterwards finds nothing and asserts against an empty string.
echo "stub cargo stdout noise: $*"
echo "stub cargo stderr noise: $*" >&2
if [ -n "${{MANIFEST_CAPTURE:-}}" ]; then
	cp Cargo.toml "$MANIFEST_CAPTURE"
fi
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


def _run(workspace: Path, path_env: str, capture: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PATH": path_env}
    if capture is not None:
        env["MANIFEST_CAPTURE"] = str(capture)
    return subprocess.run(
        ["bash", str(_SCRIPT), _CRATE_NAME, _LIB_NAME, str(workspace)],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _rewritten_manifest(workspace: Path, path_env: str) -> str:
    """The crate manifest as the isolated build actually saw it."""
    capture = workspace / "captured-Cargo.toml"
    result = _run(workspace, path_env, capture)
    assert result.returncode == 0, result.stderr
    assert capture.exists(), f"stub cargo never ran, so no manifest was captured:\n{result.stderr}"
    return capture.read_text()


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


@pytest.fixture
def workspace_with_inherited_package(workspace: Path) -> Path:
    """Same workspace, but the root declares `[workspace.package]`.

    The plain `workspace` fixture has a bare `[workspace]` table, so the
    `grep -q "^\\[workspace\\.package\\]"` guard is false and the metadata-extraction
    branch never executes. That is precisely why a GNU-only `head -n -1` in that branch
    passed every local test while failing every macos-arm64 CI job.
    """
    workspace.joinpath("Cargo.toml").write_text(
        '[workspace]\nresolver = "2"\nmembers = ["crates/demo-ext"]\n\n'
        '[workspace.package]\nversion = "3.11.2"\nedition = "2024"\nlicense = "MIT"\n\n'
        '[workspace.dependencies]\nserde = "1"\n'
    )
    return workspace


def test_inherited_workspace_metadata_branch_runs_on_this_platform(
    workspace_with_inherited_package: Path, stub_cargo_path: str
):
    """Regression: the branch must work with BSD tools, not just GNU coreutils.

    On macOS this asserted `head: illegal line count -- -1`; under `set -euo pipefail`
    that killed the script and took down every macos-arm64 PHP build.
    """
    result = _run(workspace_with_inherited_package, stub_cargo_path)

    assert "illegal line count" not in result.stderr, result.stderr
    assert "Broken pipe" not in result.stderr, result.stderr
    assert result.returncode == 0, result.stderr
    assert len(result.stdout.splitlines()) == 1, result.stdout


def test_inherited_workspace_metadata_is_substituted_into_the_crate_manifest(
    workspace_with_inherited_package: Path, stub_cargo_path: str
):
    """The point of that branch: inherited keys become literals the isolated build can read."""
    rewritten = _rewritten_manifest(workspace_with_inherited_package, stub_cargo_path)

    assert "workspace = true" not in rewritten, f"inherited keys must be resolved to literals; got:\n{rewritten}"


# ~keep A manifest copied out of its workspace cannot inherit: cargo answers "error
# inheriting `version` from workspace root manifest's `workspace.package.version` ...
# failed to find a workspace root". Deleting the lines is not enough either -- `version`,
# `edition` and `license` are required for the package to parse -- so every spelling has
# to resolve to the workspace's literal value.
_INHERITING_CRATE_MANIFEST = """# A comment mentioning workspace = true must survive verbatim.
[package]
name = "demo-ext"
version.workspace = true
edition = { workspace = true }
license.workspace = true
readme.workspace = true
keywords.workspace = true
homepage.workspace = true

[lib]
name = "demo_ext"
crate-type = ["cdylib"]

[dependencies]
sibling = { version = "1", path = "../sibling" }
serde.workspace = true

[lints]
workspace = true
"""

_INHERITING_ROOT_MANIFEST = """[workspace]
resolver = "2"
members = ["crates/demo-ext"]

[workspace.package]
version = "3.11.3"
edition = "2024"
license = "MIT"
readme = "README.md"
keywords = ["demo", "fixture"]

[workspace.dependencies]
serde = { version = "1", features = ["derive"] }

[workspace.lints.rust]
unused_imports = "warn"
"""


@pytest.fixture
def workspace_with_every_inheritance_spelling(workspace: Path) -> Path:
    """A crate inheriting via the dotted, inline-table and bare forms at once."""
    workspace.joinpath("Cargo.toml").write_text(_INHERITING_ROOT_MANIFEST)
    workspace.joinpath("crates", _CRATE_NAME, "Cargo.toml").write_text(_INHERITING_CRATE_MANIFEST)
    return workspace


def test_dotted_and_inline_inheritance_resolve_to_the_workspace_values(
    workspace_with_every_inheritance_spelling: Path, stub_cargo_path: str
):
    """Regression: the dotted form is what cargo and alef emit, and it was never stripped.

    `-replace '^\\s*workspace = true\\s*$', ''` on the Windows branch matched only the bare
    form, so `version.workspace = true` survived into the isolated build and every Windows
    PHP leg died on "failed to find a workspace root".
    """
    rewritten = _rewritten_manifest(workspace_with_every_inheritance_spelling, stub_cargo_path)
    package = tomlkit.parse(rewritten)["package"]

    assert package["version"] == "3.11.3"
    assert package["edition"] == "2024"
    assert package["license"] == "MIT"
    assert package["keywords"] == ["demo", "fixture"]


def test_inherited_dependencies_resolve_from_workspace_dependencies(
    workspace_with_every_inheritance_spelling: Path, stub_cargo_path: str
):
    """`serde.workspace = true` inherits from [workspace.dependencies], not [workspace.package]."""
    rewritten = _rewritten_manifest(workspace_with_every_inheritance_spelling, stub_cargo_path)
    serde = tomlkit.parse(rewritten)["dependencies"]["serde"]

    assert serde["version"] == "1"
    assert serde["features"] == ["derive"]


def test_path_valued_inherited_keys_are_dropped_rather_than_resolved(
    workspace_with_every_inheritance_spelling: Path, stub_cargo_path: str
):
    """`readme` names a file left behind at the workspace root, so resolving it dangles."""
    rewritten = _rewritten_manifest(workspace_with_every_inheritance_spelling, stub_cargo_path)
    package = tomlkit.parse(rewritten)["package"]

    assert "readme" not in package
    # `homepage` is inherited but absent from [workspace.package]: nothing to resolve to.
    assert "homepage" not in package


def test_bare_inheritance_leaves_a_table_cargo_can_still_parse(
    workspace_with_every_inheritance_spelling: Path, stub_cargo_path: str
):
    """`[lints]` + bare `workspace = true` has no key to resolve, so the line goes."""
    rewritten = _rewritten_manifest(workspace_with_every_inheritance_spelling, stub_cargo_path)
    document = tomlkit.parse(rewritten)

    assert "lints" in document
    assert dict(document["lints"]) == {}


def test_a_comment_mentioning_inheritance_is_not_treated_as_inheritance(
    workspace_with_every_inheritance_spelling: Path, stub_cargo_path: str
):
    """Alef-generated manifests carry prose naming `workspace = true`; it is not a key."""
    rewritten = _rewritten_manifest(workspace_with_every_inheritance_spelling, stub_cargo_path)

    assert "# A comment mentioning workspace = true must survive verbatim." in rewritten
    tomlkit.parse(rewritten)


def test_an_unresolvable_inheritance_form_fails_loudly(workspace: Path, stub_cargo_path: str):
    """A merged inline table cannot be resolved; say so instead of emitting broken TOML."""
    workspace.joinpath("Cargo.toml").write_text(_INHERITING_ROOT_MANIFEST)
    workspace.joinpath("crates", _CRATE_NAME, "Cargo.toml").write_text(
        '[package]\nname = "demo-ext"\nversion.workspace = true\n\n'
        '[dependencies]\nserde = { workspace = true, features = ["derive"] }\n'
    )

    result = _run(workspace, stub_cargo_path)

    assert result.returncode != 0
    assert "unsupported workspace inheritance form" in result.stderr
    assert 'serde = { workspace = true, features = ["derive"] }' in result.stderr


def test_no_script_uses_the_gnu_only_negative_head_count():
    """Guard the whole repo, not just this action -- build-python-sdist had the same line."""
    offenders = [
        f"{script}:{lineno}"
        for script in pathlib.Path(_SCRIPT).parents[2].rglob("*.sh")
        if ".git" not in script.parts
        for lineno, line in enumerate(script.read_text().splitlines(), 1)
        # Skip comments -- the fix's own rationale names the construct it replaced.
        if "head -n -" in line and not line.lstrip().startswith("#")
    ]
    assert not offenders, f"`head -n -N` is a GNU extension and fails on BSD/macOS: {offenders}"


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


# ~keep The isolated build copies the binding crate and nothing else, so a sibling
# `path = "../<core>"` that survives the rewrite resolves against the build directory:
# `failed to read <build-dir>/<core>/Cargo.toml`. Keeping `version` lets cargo fall back
# to the registry, which is the whole point of the strip.
_PATH_DEP_CRATE_MANIFEST = """[package]
name = "demo-ext"
version = "0.1.0"
edition = "2021"
license = "MIT"

[lib]
name = "demo_ext"
path = "src/lib.rs"
crate-type = ["cdylib"]

[dependencies]
core-lib = { version = "3.11.4", path = "../core-lib", features = ["serde"] }

[dev-dependencies]
test-helper = { path = "../test-helper", version = "0.2" }

[target.'cfg(unix)'.dependencies]
unix-only = { version = "1", path = "../unix-only" }
"""


@pytest.fixture
def workspace_with_internal_path_deps(workspace: Path) -> Path:
    """A binding crate depending on siblings the isolated copy does not carry."""
    workspace.joinpath("crates", _CRATE_NAME, "Cargo.toml").write_text(_PATH_DEP_CRATE_MANIFEST)
    return workspace


def test_internal_path_deps_are_stripped_from_the_isolated_manifest(
    workspace_with_internal_path_deps: Path, stub_cargo_path: str
):
    """Regression: the sibling crate is not copied, so the path must not survive."""
    rewritten = _rewritten_manifest(workspace_with_internal_path_deps, stub_cargo_path)
    document = tomlkit.parse(rewritten)

    for table, name in (("dependencies", "core-lib"), ("dev-dependencies", "test-helper")):
        dependency = document[table][name]
        assert "path" not in dependency, f"{table}.{name} kept a path the isolated build cannot resolve"
        assert "version" in dependency, f"{table}.{name} lost the version it must now resolve by"

    unix_only = document["target"]["cfg(unix)"]["dependencies"]["unix-only"]
    assert "path" not in unix_only
    assert unix_only["version"] == "1"


def test_stripping_paths_leaves_the_other_dependency_keys_intact(
    workspace_with_internal_path_deps: Path, stub_cargo_path: str
):
    """Dropping the key must not orphan the commas around it and break the manifest."""
    core_lib = tomlkit.parse(_rewritten_manifest(workspace_with_internal_path_deps, stub_cargo_path))["dependencies"][
        "core-lib"
    ]

    assert core_lib["version"] == "3.11.4"
    assert core_lib["features"] == ["serde"]


def test_non_dependency_paths_survive_the_strip(workspace_with_internal_path_deps: Path, stub_cargo_path: str):
    """`[lib] path` names a file inside the copy; stripping it would break the build."""
    rewritten = _rewritten_manifest(workspace_with_internal_path_deps, stub_cargo_path)

    assert tomlkit.parse(rewritten)["lib"]["path"] == "src/lib.rs"


def test_the_windows_branch_strips_internal_path_deps_as_well():
    """Regression: the strip landed on the bash branch only, so `PHP (windows)` alone died.

    The Windows leg runs inline pwsh rather than `build-out-of-workspace.sh`, so every
    manifest rewrite has to be wired into it separately or the two branches drift.
    """
    script = _ROOT / "build-php-extension" / "scripts" / "strip-internal-paths.ps1"
    assert script.is_file(), "the Windows branch has no path-stripping script to call"
    assert "strip-internal-paths.ps1" in _ACTION.read_text(), (
        "action.yml never invokes the Windows path-stripping script"
    )
