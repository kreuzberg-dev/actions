"""The validate-versions action must tie the canonical version to the release being published.

`alef validate versions --json` only compares each language manifest against the canonical
Cargo.toml, so `.ok` is equally true for a correct checkout and for a stale one in which every
manifest agrees on the *previous* version. The action declared a `version` input, wired it into
the step env as `EXPECTED_VERSION`, and never read it — so the five product repos that call this
action as their release gate believed an assertion was happening that no code performed.

The action's own shell is extracted from the committed `action.yml` and executed here against a
stub `alef`, so these assertions cannot drift away from what the action really does.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

ACTION = Path(__file__).resolve().parents[1] / "validate-versions" / "action.yml"
VALIDATE_STEP_ID = "validate"

CANONICAL = "3.12.0"


def _validate_script() -> str:
    steps = yaml.safe_load(ACTION.read_text())["runs"]["steps"]
    step = next(step for step in steps if step.get("id") == VALIDATE_STEP_ID)
    return step["run"]


def _stub_alef(bin_dir: Path) -> None:
    """Install an `alef` on PATH that prints whatever `ALEF_JSON` holds, or nothing at all."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    stub = bin_dir / "alef"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'if [[ -n "${ALEF_JSON:-}" ]]; then\n'
        "  printf '%s\\n' \"${ALEF_JSON}\"\n"
        "fi\n"
        'exit "${ALEF_EXIT_CODE:-0}"\n'
    )
    stub.chmod(0o755)


def _alef_payload(*, canonical: str | None = CANONICAL, manifest_version: str | None = None) -> str:
    """Build the JSON `alef validate versions --json` emits for a consistent workspace."""
    manifest_version = manifest_version if manifest_version is not None else canonical
    checks = [
        {
            "blocked_on_publish": None,
            "expected": canonical,
            "found": manifest_version,
            "manifest": "packages/python/pyproject.toml",
            "ok": manifest_version == canonical,
        }
    ]
    payload: dict[str, object] = {"checks": checks, "ok": all(check["ok"] for check in checks)}
    if canonical is not None:
        payload["canonical"] = canonical
    return json.dumps(payload)


def _execute(
    tmp_path: Path,
    *,
    expected_version: str,
    alef_json: str | None = None,
    alef_exit_code: int = 0,
) -> tuple[subprocess.CompletedProcess[str], dict[str, str]]:
    """Execute the action's own validate step; return the process and its $GITHUB_OUTPUT keys."""
    bin_dir = tmp_path / "bin"
    _stub_alef(bin_dir)
    github_output = tmp_path / "github_output"
    github_output.write_text("")

    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "GITHUB_OUTPUT": str(github_output),
        "EXPECTED_VERSION": expected_version,
        "ALEF_JSON": _alef_payload() if alef_json is None else alef_json,
        "ALEF_EXIT_CODE": str(alef_exit_code),
    }
    result = subprocess.run(
        ["bash", "-c", _validate_script()],
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


def test_the_action_still_reads_the_release_version_from_the_step_env():
    """The wiring the guard depends on: the input must reach the script as EXPECTED_VERSION."""
    steps = yaml.safe_load(ACTION.read_text())["runs"]["steps"]
    step = next(step for step in steps if step.get("id") == VALIDATE_STEP_ID)

    assert step["env"]["EXPECTED_VERSION"] == "${{ inputs.version }}"
    assert "EXPECTED_VERSION" in step["run"], "the input is wired into the env but never consumed"


def test_matching_release_version_passes(tmp_path):
    result, outputs = _execute(tmp_path, expected_version=CANONICAL)

    assert result.returncode == 0, result.stderr
    assert outputs["valid"] == "true"
    assert json.loads(outputs["mismatches"]) == []


def test_leading_v_is_stripped_from_the_release_version(tmp_path):
    result, outputs = _execute(tmp_path, expected_version=f"v{CANONICAL}")

    assert result.returncode == 0, result.stderr
    assert outputs["valid"] == "true"


def test_stale_checkout_fails_even_though_every_manifest_agrees(tmp_path):
    """The defect: `.ok` is true, but the whole repo sits on the previous version."""
    result, outputs = _execute(tmp_path, expected_version="3.13.0")

    assert result.returncode == 1
    assert outputs["valid"] == "false"
    assert json.loads(outputs["mismatches"]) == [
        {"manifest": "Cargo.toml", "expected": "3.13.0", "found": CANONICAL, "ok": False}
    ]
    assert "the canonical version is 3.12.0 but the release being validated is 3.13.0" in result.stderr


def test_dry_run_suffix_is_stripped_rather_than_skipping_the_assertion(tmp_path):
    """A dry run synthesizes `<version>-dryrun-<sha>`; the assertion must still run on it."""
    result, outputs = _execute(tmp_path, expected_version=f"v{CANONICAL}-dryrun-abc1234")

    assert result.returncode == 0, result.stderr
    assert outputs["valid"] == "true"


def test_dry_run_of_a_stale_checkout_still_fails(tmp_path):
    """Stripping the suffix must not become a way to opt out of the guard."""
    result, outputs = _execute(tmp_path, expected_version="3.13.0-dryrun-abc1234")

    assert result.returncode == 1
    assert outputs["valid"] == "false"
    assert "the release being validated is 3.13.0" in result.stderr


def test_prerelease_versions_are_not_mistaken_for_dry_run_tags(tmp_path):
    """Only the literal `-dryrun-` marker is stripped; a real `-rc.1` must still be compared."""
    result, _ = _execute(
        tmp_path,
        expected_version="3.12.0-rc.1",
        alef_json=_alef_payload(canonical="3.12.0-rc.1"),
    )
    assert result.returncode == 0, result.stderr

    stale, _ = _execute(tmp_path, expected_version="3.12.0-rc.1")
    assert stale.returncode == 1, "a -rc.1 release must not silently match the 3.12.0 canonical"


def test_omitting_the_version_preserves_consistency_only_behaviour(tmp_path):
    """Existing callers that pass no version must keep working exactly as before."""
    result, outputs = _execute(tmp_path, expected_version="")

    assert result.returncode == 0, result.stderr
    assert outputs["valid"] == "true"
    assert json.loads(outputs["mismatches"]) == []


def test_manifest_drift_still_fails_when_no_version_is_supplied(tmp_path):
    result, outputs = _execute(
        tmp_path,
        expected_version="",
        alef_json=_alef_payload(manifest_version="3.11.0"),
    )

    assert result.returncode == 1
    assert outputs["valid"] == "false"
    assert json.loads(outputs["mismatches"])[0]["manifest"] == "packages/python/pyproject.toml"


def test_manifest_drift_and_a_stale_release_are_both_reported(tmp_path):
    result, outputs = _execute(
        tmp_path,
        expected_version="3.13.0",
        alef_json=_alef_payload(manifest_version="3.11.0"),
    )

    assert result.returncode == 1
    assert outputs["valid"] == "false"
    reported = {entry["manifest"] for entry in json.loads(outputs["mismatches"])}
    assert reported == {"packages/python/pyproject.toml", "Cargo.toml"}


def test_a_missing_canonical_version_fails_rather_than_passing_unverified(tmp_path):
    """An alef that cannot report a canonical version must not be read as agreement."""
    result, _ = _execute(
        tmp_path,
        expected_version=CANONICAL,
        alef_json=json.dumps({"checks": [], "ok": True}),
    )

    assert result.returncode == 1
    assert "no canonical version" in result.stderr


def test_empty_alef_output_still_fails_closed(tmp_path):
    result, _ = _execute(tmp_path, expected_version=CANONICAL, alef_json="", alef_exit_code=1)

    assert result.returncode == 1
    assert "produced no output" in result.stderr


@pytest.mark.parametrize("supplied", ["", CANONICAL])
def test_the_action_declares_every_output_the_step_writes(tmp_path, supplied):
    _, outputs = _execute(tmp_path, expected_version=supplied)
    declared = set(yaml.safe_load(ACTION.read_text())["outputs"])

    assert set(outputs) <= declared, "a key written to $GITHUB_OUTPUT that no caller can read"
