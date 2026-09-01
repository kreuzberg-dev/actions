"""The shell publish actions must keep their stale-artifact guard armed on dry runs.

`prepare-release-metadata` synthesizes a dry run's tag as `<version>-dryrun-<sha>`, and every
caller feeds that straight through as the release version. The guards compared it verbatim
against the package manifest, so a dry run of a *correct* checkout failed — which is the one
run where a real mismatch should be allowed to surface, while nothing has been published.

Each guard's shell is extracted from its committed `action.yml` and executed here, so these
assertions cannot drift away from what the actions really do.
"""

import os
import subprocess
from pathlib import Path

import pytest
import yaml

ACTIONS_ROOT = Path(__file__).resolve().parents[1]

PACKAGE_VERSION = "1.2.3"

# action directory, guard step name, manifest file, manifest body declaring {version}
GUARDS = [
    (
        "publish-gleam",
        "Verify gleam.toml carries the release version",
        "gleam.toml",
        'name = "demo"\nversion = "{version}"\n',
    ),
    (
        "publish-hex",
        "Verify mix.exs carries the release version",
        "mix.exs",
        'defmodule Demo.MixProject do\n  def project, do: [app: :demo, version: "{version}"]\nend\n',
    ),
    (
        "publish-pub",
        "Verify pubspec.yaml carries the release version",
        "pubspec.yaml",
        "name: demo\nversion: {version}\n",
    ),
]

GUARD_IDS = [action for action, _, _, _ in GUARDS]


def _guard_script(action: str, step_name: str) -> str:
    steps = yaml.safe_load((ACTIONS_ROOT / action / "action.yml").read_text())["runs"]["steps"]
    return next(step for step in steps if step.get("name") == step_name)["run"]


def _execute(
    guard: tuple[str, str, str, str],
    tmp_path: Path,
    *,
    expected_version: str,
    manifest_version: str = PACKAGE_VERSION,
) -> subprocess.CompletedProcess[str]:
    action, step_name, manifest, body = guard
    package_dir = tmp_path / "packages" / "demo"
    package_dir.mkdir(parents=True)
    (package_dir / manifest).write_text(body.format(version=manifest_version))

    env = {
        "PATH": os.environ["PATH"],
        "PACKAGE_DIR": str(package_dir),
        "INPUT_EXPECTED_VERSION": expected_version,
    }
    return subprocess.run(
        ["bash", "-eo", "pipefail", "-c", _guard_script(action, step_name)],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("guard", GUARDS, ids=GUARD_IDS)
@pytest.mark.parametrize("expected_version", [PACKAGE_VERSION, f"v{PACKAGE_VERSION}"])
def test_a_matching_manifest_is_accepted(guard, tmp_path, expected_version):
    result = _execute(guard, tmp_path, expected_version=expected_version)

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"carries the release version {PACKAGE_VERSION}" in result.stdout


@pytest.mark.parametrize("guard", GUARDS, ids=GUARD_IDS)
def test_a_dry_run_tag_suffix_is_stripped_rather_than_skipping_the_assertion(guard, tmp_path):
    result = _execute(guard, tmp_path, expected_version=f"v{PACKAGE_VERSION}-dryrun-abc1234")

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"carries the release version {PACKAGE_VERSION}" in result.stdout


@pytest.mark.parametrize("guard", GUARDS, ids=GUARD_IDS)
def test_a_dry_run_of_a_stale_package_still_fails(guard, tmp_path):
    """Stripping the suffix must not become a way to opt out of the guard."""
    result = _execute(
        guard,
        tmp_path,
        expected_version=f"{PACKAGE_VERSION}-dryrun-abc1234",
        manifest_version="1.2.2",
    )

    assert result.returncode == 1
    assert f"the release being published is {PACKAGE_VERSION}" in result.stdout


@pytest.mark.parametrize("guard", GUARDS, ids=GUARD_IDS)
def test_a_real_prerelease_is_not_mistaken_for_a_dry_run_tag(guard, tmp_path):
    matching = _execute(
        guard,
        tmp_path / "matching",
        expected_version=f"{PACKAGE_VERSION}-rc.1",
        manifest_version=f"{PACKAGE_VERSION}-rc.1",
    )
    assert matching.returncode == 0, matching.stdout + matching.stderr

    stale = _execute(guard, tmp_path / "stale", expected_version=f"{PACKAGE_VERSION}-rc.1")
    assert stale.returncode == 1, "a -rc.1 release must not silently match a 1.2.3 manifest"


@pytest.mark.parametrize("guard", GUARDS, ids=GUARD_IDS)
def test_omitting_the_expected_version_warns_and_preserves_the_old_behaviour(guard, tmp_path):
    result = _execute(guard, tmp_path, expected_version="")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "::warning::" in result.stdout
