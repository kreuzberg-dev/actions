"""The publish-r-package action must tie the tarball it uploads to the release version.

`R CMD build` names its tarball from the DESCRIPTION `Version:` field and never reads the
action's `version` input, and the build step used to take the first entry of `ls *.tar.gz`. A
stale checkout therefore built and uploaded a tarball for some other version under the release
tag, and the job reported success having shipped nothing for the release.

Both shell steps are extracted from the committed `action.yml` and executed here against a stub
`R`, so these assertions cannot drift away from what the action really does.
"""

import os
import subprocess
from pathlib import Path

import pytest
import yaml

ACTION = Path(__file__).resolve().parents[1] / "publish-r-package" / "action.yml"
VERIFY_STEP_NAME = "Verify DESCRIPTION carries the release version"
BUILD_STEP_ID = "build"


def _step_script(*, name: str | None = None, step_id: str | None = None) -> str:
    steps = yaml.safe_load(ACTION.read_text())["runs"]["steps"]
    step = next(s for s in steps if (s.get("name") == name if name else s.get("id") == step_id))
    return step["run"]


def _stub_r(bin_dir: Path) -> None:
    """Install an `R` on PATH that names its tarball from DESCRIPTION, exactly as `R CMD build` does."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    stub = bin_dir / "R"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'package=$(sed -n "s/^Package:[[:space:]]*\\([^[:space:]]*\\).*/\\1/p" DESCRIPTION | head -n 1)\n'
        'version=$(sed -n "s/^Version:[[:space:]]*\\([^[:space:]]*\\).*/\\1/p" DESCRIPTION | head -n 1)\n'
        "printf 'stub tarball\\n' >\"${package}_${version}.tar.gz\"\n"
    )
    stub.chmod(0o755)


def _package_dir(tmp_path: Path, *, description_version: str | None = "1.2.3") -> Path:
    package_dir = tmp_path / "packages" / "r"
    package_dir.mkdir(parents=True)
    description = "Package: xbergr\n"
    if description_version is not None:
        description += f"Version: {description_version}\n"
    (package_dir / "DESCRIPTION").write_text(description)
    return package_dir


def _execute(script: str, tmp_path: Path, *, version: str) -> tuple[subprocess.CompletedProcess[str], dict[str, str]]:
    """Execute one of the action's steps; return the process and its $GITHUB_OUTPUT keys."""
    bin_dir = tmp_path / "bin"
    _stub_r(bin_dir)
    github_output = tmp_path / "github_output"
    github_output.write_text("")

    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "GITHUB_OUTPUT": str(github_output),
        "GITHUB_WORKSPACE": str(tmp_path),
        "INPUT_PACKAGE_DIR": "packages/r",
        "INPUT_VERSION": version,
    }
    result = subprocess.run(
        ["bash", "-c", script],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    outputs: dict[str, str] = {}
    for line in github_output.read_text().splitlines():
        if not line:
            continue
        key, _, value = line.partition("=")
        outputs[key] = value
    return result, outputs


@pytest.mark.parametrize("version", ["1.2.3", "v1.2.3"])
def test_verify_accepts_a_description_carrying_the_release_version(tmp_path, version):
    _package_dir(tmp_path, description_version="1.2.3")

    result, _ = _execute(_step_script(name=VERIFY_STEP_NAME), tmp_path, version=version)

    assert result.returncode == 0, result.stderr
    assert "Verified DESCRIPTION carries the release version 1.2.3" in result.stdout


def test_verify_rejects_a_stale_description(tmp_path):
    _package_dir(tmp_path, description_version="1.2.2")

    result, _ = _execute(_step_script(name=VERIFY_STEP_NAME), tmp_path, version="1.2.3")

    assert result.returncode == 1
    assert "DESCRIPTION declares version 1.2.2 but the release being published is 1.2.3" in result.stdout


def test_verify_rejects_a_description_without_a_version(tmp_path):
    _package_dir(tmp_path, description_version=None)

    result, _ = _execute(_step_script(name=VERIFY_STEP_NAME), tmp_path, version="1.2.3")

    assert result.returncode == 1
    assert "no Version field could be read" in result.stdout


def test_build_selects_the_tarball_carrying_the_release_version(tmp_path):
    package_dir = _package_dir(tmp_path, description_version="1.2.3")
    # Sorts ahead of the real tarball, so `ls -1 *.tar.gz | head -n 1` would have picked it.
    (package_dir / "xbergr_1.0.0.tar.gz").write_text("leftover from an earlier build\n")

    result, outputs = _execute(_step_script(step_id=BUILD_STEP_ID), tmp_path, version="1.2.3")

    assert result.returncode == 0, result.stderr
    assert outputs["archive-path"] == str(package_dir / "xbergr_1.2.3.tar.gz")


def test_build_fails_when_no_tarball_carries_the_release_version(tmp_path):
    _package_dir(tmp_path, description_version="1.2.2")

    result, outputs = _execute(_step_script(step_id=BUILD_STEP_ID), tmp_path, version="1.2.3")

    assert result.returncode == 1
    assert "did not produce a .tar.gz for version 1.2.3" in result.stdout
    assert outputs == {}


@pytest.mark.parametrize("version", ["1.2.3-dryrun-abc1234", "v1.2.3-dryrun-abc1234"])
def test_a_dry_run_tag_suffix_is_stripped_rather_than_skipping_the_assertion(tmp_path, version):
    """A dry run passes `<version>-dryrun-<sha>`; DESCRIPTION will never carry that."""
    _package_dir(tmp_path, description_version="1.2.3")

    result, _ = _execute(_step_script(name=VERIFY_STEP_NAME), tmp_path, version=version)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Verified DESCRIPTION carries the release version 1.2.3" in result.stdout


def test_a_dry_run_of_a_stale_checkout_still_fails(tmp_path):
    """Stripping the suffix must not become a way to opt out of the guard."""
    _package_dir(tmp_path, description_version="1.2.2")

    result, _ = _execute(_step_script(name=VERIFY_STEP_NAME), tmp_path, version="1.2.3-dryrun-abc1234")

    assert result.returncode == 1
    assert "the release being published is 1.2.3" in result.stdout


def test_the_build_step_selects_the_tarball_for_the_stripped_version(tmp_path):
    """Both steps must strip identically, or the build looks for a tarball that cannot exist."""
    package_dir = _package_dir(tmp_path, description_version="1.2.3")

    result, outputs = _execute(_step_script(step_id=BUILD_STEP_ID), tmp_path, version="v1.2.3-dryrun-abc1234")

    assert result.returncode == 0, result.stdout + result.stderr
    assert outputs["archive-path"] == str(package_dir / "xbergr_1.2.3.tar.gz")


def test_a_real_prerelease_is_not_mistaken_for_a_dry_run_tag(tmp_path):
    _package_dir(tmp_path, description_version="1.2.3")

    result, _ = _execute(_step_script(name=VERIFY_STEP_NAME), tmp_path, version="1.2.3-rc.1")

    assert result.returncode == 1, "a -rc.1 release must not silently match a 1.2.3 DESCRIPTION"
