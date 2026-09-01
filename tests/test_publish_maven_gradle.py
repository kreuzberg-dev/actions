"""The Gradle stale-artifact guard must work on the projects it was added for.

Every Kotlin Android package in this org publishes through `com.vanniktech.maven.publish` and
declares its version only inside that plugin's `coordinates(...)` block. `project.version` is
never assigned there, so `gradle properties -q` prints `version: unspecified` and the guard
failed closed on a perfectly correct project — it could not run at all on exactly the packages
whose "already published, skipping" branch it exists to make safe. The generated POM carries
the version Maven Central will index, so it is the source of truth this falls back to.

The action's own shell is extracted from the committed `action.yml` and executed here against a
stub `gradle` reproducing both shapes, so these assertions cannot drift away from the action.
The same script was also run against a real Gradle 9.7.1 + vanniktech 0.37.0 project.
"""

import os
import subprocess
import textwrap
from pathlib import Path

import yaml

ACTION = Path(__file__).resolve().parents[1] / "publish-maven-gradle" / "action.yml"
VERIFY_STEP_ID = "verify-version"

PROJECT_VERSION = "3.12.0"

POM_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <modelVersion>4.0.0</modelVersion>
  <groupId>io.xberg</groupId>
  <artifactId>html-to-markdown-android</artifactId>
  <version>{version}</version>
  <dependencies>
    <dependency>
      <groupId>org.jetbrains.kotlin</groupId>
      <artifactId>kotlin-stdlib</artifactId>
      <version>2.3.0</version>
    </dependency>
  </dependencies>
</project>
"""


def _verify_script() -> str:
    steps = yaml.safe_load(ACTION.read_text())["runs"]["steps"]
    step = next(step for step in steps if step.get("id") == VERIFY_STEP_ID)
    return step["run"]


def _stub_gradle(bin_dir: Path) -> None:
    """Install a `gradle` on PATH reproducing the two shapes the guard has to tell apart.

    `PROPERTIES_VERSION` is what `gradle properties -q` reports — `unspecified` for a project
    whose version lives only in `coordinates(...)`. `POM_VERSION`, when set, is written into a
    generated POM by the aggregator task the guard registers through its init script.
    """
    bin_dir.mkdir(parents=True, exist_ok=True)
    stub = bin_dir / "gradle"
    stub.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            set -euo pipefail
            for arg in "$@"; do
              if [[ "${arg}" == "properties" ]]; then
                printf 'version: %s\\n' "${PROPERTIES_VERSION:-unspecified}"
                exit 0
              fi
              if [[ "${arg}" == "alefGeneratePomFiles" ]]; then
                if [[ -n "${POM_VERSION:-}" ]]; then
                  mkdir -p build/publications/release
                  printf '%s' "${POM_CONTENT}" >build/publications/release/pom-default.xml
                fi
                exit 0
              fi
            done
            exit 1
            """
        )
    )
    stub.chmod(0o755)


def _execute(
    tmp_path: Path,
    *,
    expected_version: str,
    properties_version: str = "unspecified",
    pom_version: str | None = PROJECT_VERSION,
    gradle_properties: str | None = None,
    stale_pom_version: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Execute the action's own verify step against a stub Gradle in a throwaway project."""
    project = tmp_path / "packages" / "kotlin-android"
    project.mkdir(parents=True)
    if gradle_properties is not None:
        (project / "gradle.properties").write_text(gradle_properties)
    if stale_pom_version is not None:
        stale = project / "build" / "publications" / "release"
        stale.mkdir(parents=True)
        (stale / "pom-default.xml").write_text(POM_TEMPLATE.format(version=stale_pom_version))

    bin_dir = tmp_path / "bin"
    _stub_gradle(bin_dir)

    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "WORKING_DIR": str(project),
        "NO_DAEMON": "true",
        "INPUT_EXPECTED_VERSION": expected_version,
        "PROPERTIES_VERSION": properties_version,
        "POM_VERSION": pom_version or "",
        "POM_CONTENT": POM_TEMPLATE.format(version=pom_version) if pom_version else "",
    }
    return subprocess.run(
        ["bash", "-eo", "pipefail", "-c", _verify_script()],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_action_still_reads_the_release_version_from_the_step_env():
    steps = yaml.safe_load(ACTION.read_text())["runs"]["steps"]
    step = next(step for step in steps if step.get("id") == VERIFY_STEP_ID)

    assert step["env"]["INPUT_EXPECTED_VERSION"] == "${{ inputs.expected-version }}"
    assert "INPUT_EXPECTED_VERSION" in step["run"]


def test_a_version_declared_only_in_the_vanniktech_coordinates_block_is_verified(tmp_path):
    """The defect: `gradle properties -q` says `unspecified`, but the POM says 3.12.0."""
    result = _execute(tmp_path, expected_version=PROJECT_VERSION)

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"Verified the Gradle project carries the release version {PROJECT_VERSION}" in result.stdout


def test_a_stale_coordinates_version_fails_before_publishing(tmp_path):
    result = _execute(tmp_path, expected_version="3.13.0")

    assert result.returncode == 1
    assert "would publish version 3.12.0 but the release being published is 3.13.0" in result.stdout


def test_a_project_no_source_can_report_a_version_for_still_fails(tmp_path):
    """No gradle.properties, `unspecified` from Gradle, and no POM: nothing may be assumed."""
    result = _execute(tmp_path, expected_version=PROJECT_VERSION, pom_version=None)

    assert result.returncode == 1
    assert "could not be determined" in result.stdout


def test_a_stale_pom_from_an_earlier_build_cannot_satisfy_the_guard(tmp_path):
    """A leftover POM matching the release is the exact failure this step exists to catch."""
    result = _execute(
        tmp_path,
        expected_version="3.13.0",
        pom_version=None,
        stale_pom_version="3.13.0",
    )

    assert result.returncode == 1
    assert "could not be determined" in result.stdout


def test_gradle_properties_still_short_circuits_the_pom_probe(tmp_path):
    """The cheap source keeps working; the POM fallback is only for projects without one."""
    result = _execute(
        tmp_path,
        expected_version=PROJECT_VERSION,
        gradle_properties=f"version={PROJECT_VERSION}\n",
        pom_version="9.9.9",
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_a_gradle_properties_without_a_version_falls_through_instead_of_dying(tmp_path):
    """`set -e` plus `pipefail` turned a `version=`-less gradle.properties into a silent abort."""
    result = _execute(
        tmp_path,
        expected_version=PROJECT_VERSION,
        gradle_properties="org.gradle.jvmargs=-Xmx4g\n",
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_a_resolved_project_version_is_preferred_over_the_pom(tmp_path):
    result = _execute(
        tmp_path,
        expected_version=PROJECT_VERSION,
        properties_version=PROJECT_VERSION,
        pom_version="9.9.9",
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_the_dry_run_suffix_is_stripped_rather_than_skipping_the_assertion(tmp_path):
    result = _execute(tmp_path, expected_version=f"v{PROJECT_VERSION}-dryrun-abc1234")

    assert result.returncode == 0, result.stdout + result.stderr


def test_a_dry_run_of_a_stale_project_still_fails(tmp_path):
    result = _execute(tmp_path, expected_version="3.13.0-dryrun-abc1234")

    assert result.returncode == 1
    assert "the release being published is 3.13.0" in result.stdout


def test_a_real_prerelease_is_not_mistaken_for_a_dry_run_tag(tmp_path):
    matching = _execute(
        tmp_path / "matching",
        expected_version="3.12.0-rc.1",
        pom_version="3.12.0-rc.1",
    )
    assert matching.returncode == 0, matching.stdout + matching.stderr

    stale = _execute(tmp_path / "stale", expected_version="3.12.0-rc.1")
    assert stale.returncode == 1, "a -rc.1 release must not silently match the 3.12.0 POM"


def test_omitting_the_expected_version_warns_and_preserves_the_old_behaviour(tmp_path):
    result = _execute(tmp_path, expected_version="")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "::warning::" in result.stdout
