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
    """Install an `alef` on PATH that reports `existing` packages as published.

    `FAILING_PACKAGES` makes the stub exit non-zero (as alef does when the registry answers
    HTTP 403), and `BROKEN_OUTPUT_PACKAGES` makes it succeed while printing non-JSON.
    """
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
        "for bad in ${FAILING_PACKAGES:-}; do\n"
        '  if [[ "${bad}" == "${package}" ]]; then\n'
        '    echo "ERROR GitHub API GET .../releases/tags: HTTP request failed: http status: 403" >&2\n'
        '    exit "${FAIL_EXIT_CODE:-1}"\n'
        "  fi\n"
        "done\n"
        "for flaky in ${FLAKY_PACKAGES:-}; do\n"
        '  if [[ "${flaky}" == "${package}" ]]; then\n'
        '    if [[ ! -f "${FLAKY_STATE}" ]]; then\n'
        '      : >"${FLAKY_STATE}"\n'
        "      printf 'partial garbage from a failed attempt\\n'\n"
        "      exit 1\n"
        "    fi\n"
        "  fi\n"
        "done\n"
        "for broken in ${BROKEN_OUTPUT_PACKAGES:-}; do\n"
        '  if [[ "${broken}" == "${package}" ]]; then\n'
        "    printf 'not json at all\\n'\n"
        "    exit 0\n"
        "  fi\n"
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


def _stub_sleep(bin_dir: Path) -> None:
    """Neutralise the action's retry backoff so the failure paths run in test time."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    stub = bin_dir / "sleep"
    stub.write_text("#!/usr/bin/env bash\nexit 0\n")
    stub.chmod(0o755)


def _execute(
    tmp_path: Path,
    *,
    package: str,
    extra_packages: str,
    existing: list[str],
    failing: list[str] | None = None,
    fail_exit_code: int = 1,
    broken_output: list[str] | None = None,
    flaky: list[str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], dict[str, str]]:
    """Execute the action's own check step; return the process and its $GITHUB_OUTPUT keys."""
    bin_dir = tmp_path / "bin"
    _stub_alef(bin_dir, existing)
    _stub_sleep(bin_dir)
    github_output = tmp_path / "github_output"
    github_output.write_text("")

    env = {
        "PATH": f"{bin_dir}:{shutil.os.environ['PATH']}",
        "GITHUB_OUTPUT": str(github_output),
        "EXISTING_PACKAGES": " ".join(existing),
        "FAILING_PACKAGES": " ".join(failing or []),
        "FAIL_EXIT_CODE": str(fail_exit_code),
        "BROKEN_OUTPUT_PACKAGES": " ".join(broken_output or []),
        "FLAKY_PACKAGES": " ".join(flaky or []),
        "FLAKY_STATE": str(tmp_path / "flaky-state"),
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

    outputs: dict[str, str] = {}
    for line in github_output.read_text().splitlines():
        if not line:
            continue
        key, _, value = line.partition("=")
        outputs[key] = value
    return result, outputs


def _run_check(tmp_path: Path, *, package: str, extra_packages: str, existing: list[str]) -> dict[str, str]:
    """Execute the check step, requiring it to succeed, and return its outputs."""
    result, outputs = _execute(tmp_path, package=package, extra_packages=extra_packages, existing=existing)
    assert result.returncode == 0, f"check step failed: {result.stderr}"
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


def test_retry_loop_reports_the_real_exit_code_not_zero(tmp_path):
    """`if cmd; then return 0; fi` leaves `$?` at 0, so every failure was logged as 'exit code 0'."""
    result, _ = _execute(
        tmp_path,
        package="widget",
        extra_packages="",
        existing=[],
        failing=["widget"],
        fail_exit_code=7,
    )

    assert "failed with exit code 7" in result.stderr, result.stderr
    assert "failed with exit code 0" not in result.stderr, "the retry loop is misreading $? again"
    assert "Max retries (5) exhausted" in result.stderr


def test_failed_check_is_reported_as_not_published_instead_of_crashing_jq(tmp_path):
    """A check that never completes must not reach `jq --argjson` with an empty string."""
    result, outputs = _execute(
        tmp_path,
        package="widget",
        extra_packages="",
        existing=[],
        failing=["widget"],
    )

    assert result.returncode == 0, f"the step crashed instead of failing open: {result.stderr}"
    assert "invalid JSON text passed to --argjson" not in result.stderr
    assert outputs["exists"] == "false"
    assert outputs["all-exist"] == "false"
    assert json.loads(outputs["results"]) == {"exists": False}
    assert "::warning::" in result.stdout, "a check that failed open must say so"


def test_unparseable_alef_output_is_treated_as_not_published(tmp_path):
    result, outputs = _execute(
        tmp_path,
        package="widget",
        extra_packages="",
        existing=[],
        broken_output=["widget"],
    )

    assert result.returncode == 0, f"non-JSON output crashed the step: {result.stderr}"
    assert outputs["exists"] == "false"
    assert json.loads(outputs["results"]) == {"exists": False}
    assert "unparseable output" in result.stdout


def test_a_failed_extra_package_check_clears_all_exist_without_crashing(tmp_path):
    result, outputs = _execute(
        tmp_path,
        package="widget",
        extra_packages="cli_exists=widget-cli\n",
        existing=["widget"],
        failing=["widget-cli"],
    )

    assert result.returncode == 0, f"the step crashed instead of failing open: {result.stderr}"
    assert outputs["exists"] == "true"
    assert outputs["all-exist"] == "false"
    assert json.loads(outputs["results"]) == {"exists": True, "cli_exists": False}


def test_a_retry_recovers_and_the_failed_attempt_output_is_discarded(tmp_path):
    """The first attempt fails after printing noise; the result must be the retry's clean JSON."""
    result, outputs = _execute(
        tmp_path,
        package="widget",
        extra_packages="",
        existing=["widget"],
        flaky=["widget"],
    )

    assert result.returncode == 0, f"the retry did not recover: {result.stderr}"
    assert "Attempt 1 failed with exit code 1" in result.stderr
    assert outputs["exists"] == "true"
    assert json.loads(outputs["results"]) == {"exists": True}


@pytest.mark.parametrize("name", ["exists", "all-exist", "results"])
def test_declared_outputs_are_wired_to_the_check_step(name):
    value = _action()["outputs"][name]["value"]
    assert value == f"${{{{ steps.{CHECK_STEP_ID}.outputs.{name} }}}}"
