"""The check-registry composite action must actually hand its extra-package results to callers.

A composite action propagates only the outputs its `outputs:` block declares, so the per-line
keys `extra-packages` writes to `$GITHUB_OUTPUT` never reached any caller: crawlberg's v1.2.1
publish run shows the consuming step evaluating `"" == "true"` three times.

The action's own shell is extracted from the committed `action.yml` and executed here against a
stub `alef`, so these assertions cannot drift away from what the action really does.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ACTION = Path(__file__).resolve().parents[1] / "check-registry" / "action.yml"
CHECK_STEP_ID = "check"


def _action() -> dict:
    return yaml.safe_load(ACTION.read_text())


def _check_script() -> str:
    steps = _action()["runs"]["steps"]
    step = next(step for step in steps if step.get("id") == CHECK_STEP_ID)
    return step["run"]


def _stub_alef(bin_dir: Path, existing: list[str]) -> None:
    """Install an `alef` on PATH that reports `existing` packages as published."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    stub = bin_dir / "alef"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "package=\n"
        "while [[ $# -gt 0 ]]; do\n"
        '  if [[ "$1" == "--package" ]]; then package="$2"; shift; fi\n'
        "  shift\n"
        "done\n"
        "for known in ${EXISTING_PACKAGES:-}; do\n"
        '  if [[ "${known}" == "${package}" ]]; then\n'
        '    printf \'{"exists": true, "package": "%s"}\\n\' "${package}"\n'
        "    exit 0\n"
        "  fi\n"
        "done\n"
        'printf \'{"exists": false, "package": "%s"}\\n\' "${package}"\n'
    )
    stub.chmod(0o755)


def _run_check(tmp_path: Path, *, package: str, extra_packages: str, existing: list[str]) -> dict[str, str]:
    """Execute the action's own check step and return the keys it wrote to $GITHUB_OUTPUT."""
    bin_dir = tmp_path / "bin"
    _stub_alef(bin_dir, existing)
    github_output = tmp_path / "github_output"
    github_output.write_text("")

    env = {
        "PATH": f"{bin_dir}:{shutil.os.environ['PATH']}",
        "GITHUB_OUTPUT": str(github_output),
        "EXISTING_PACKAGES": " ".join(existing),
        "REGISTRY": "cratesio",
        "PACKAGE": package,
        "VERSION": "1.2.3",
        "EXTRA_PACKAGES": extra_packages,
        "TAP_REPO": "",
        "REPO_INPUT": "",
        "SOURCE": "",
        "ASSET_PREFIX": "",
        "REQUIRED_ASSETS": "",
        "GITHUB_TOKEN": "stub-token",
    }
    result = subprocess.run(
        ["bash", "-c", _check_script()],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"check step failed: {result.stderr}"

    outputs: dict[str, str] = {}
    for line in github_output.read_text().splitlines():
        if not line:
            continue
        key, _, value = line.partition("=")
        outputs[key] = value
    return outputs


def test_extra_package_results_reach_the_caller(tmp_path):
    outputs = _run_check(
        tmp_path,
        package="widget",
        extra_packages="cli_exists=widget-cli\ntesseract_exists=widget-tesseract\n",
        existing=["widget", "widget-cli", "widget-tesseract"],
    )

    assert json.loads(outputs["results"]) == {
        "exists": True,
        "cli_exists": True,
        "tesseract_exists": True,
    }
    assert outputs["all-exist"] == "true"
    assert outputs["exists"] == "true"


def test_all_exist_is_false_when_one_extra_package_is_missing(tmp_path):
    outputs = _run_check(
        tmp_path,
        package="widget",
        extra_packages="cli_exists=widget-cli\ntesseract_exists=widget-tesseract\n",
        existing=["widget", "widget-cli"],
    )

    assert json.loads(outputs["results"]) == {
        "exists": True,
        "cli_exists": True,
        "tesseract_exists": False,
    }
    assert outputs["all-exist"] == "false"
    assert outputs["exists"] == "true", "the primary package is published; only an extra is not"


def test_all_exist_matches_exists_without_extra_packages(tmp_path):
    for existing, expected in ((["widget"], "true"), ([], "false")):
        outputs = _run_check(tmp_path, package="widget", extra_packages="", existing=existing)
        assert outputs["all-exist"] == expected
        assert outputs["exists"] == expected
        assert json.loads(outputs["results"]) == {"exists": expected == "true"}


def test_every_emitted_output_key_is_declared_by_the_action(tmp_path):
    """The defect itself: a key written to $GITHUB_OUTPUT but not declared reaches nobody."""
    outputs = _run_check(
        tmp_path,
        package="widget",
        extra_packages="cli_exists=widget-cli\n",
        existing=["widget", "widget-cli"],
    )
    declared = set(_action()["outputs"])

    undeclared = set(outputs) - declared
    assert not undeclared, (
        f"{sorted(undeclared)} are written to $GITHUB_OUTPUT but not declared as action outputs, "
        "so callers read an empty string"
    )


@pytest.mark.parametrize("name", ["exists", "all-exist", "results"])
def test_declared_outputs_are_wired_to_the_check_step(name):
    value = _action()["outputs"][name]["value"]
    assert value == f"${{{{ steps.{CHECK_STEP_ID}.outputs.{name} }}}}"
