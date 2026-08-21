"""The check-registries reusable workflow must aggregate matrix legs without collisions.

A matrix job has one output namespace shared by every leg: a job-level `outputs:` block
declared on a job with `strategy: matrix:` collapses to whichever leg happens to finish last,
silently discarding every other leg's value. The `check` job used to declare
`outputs: result: ${{ steps.check.outputs.all-exist }}` directly on the matrixed job, so with
N registries only one survived, non-deterministically depending on completion order.

The fix has each leg write its own result to a uniquely-named artifact, and a separate
`aggregate` job fans them back in with `jq -s add` over the downloaded files — a union over
disjoint keys, which cannot depend on leg completion order.

The workflow's own shell is extracted from the committed YAML and executed here, so these
assertions cannot drift away from what the workflow really does.
"""

import json
import os
import subprocess
from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "reusable-check-registries.yml"


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def _step(job_name: str, step_id: str) -> dict:
    steps = _workflow()["jobs"][job_name]["steps"]
    matches = [step for step in steps if step.get("id") == step_id]
    assert matches, (
        f"no step with id {step_id!r} in job {job_name!r} -- the per-leg aggregation "
        "mechanism is missing, so matrix legs can only collide onto a single shared output"
    )
    return matches[0]


def _write_result_script() -> str:
    return _step("check", "write-result")["run"]


def _aggregate_script() -> str:
    return _step("aggregate", "aggregate")["run"]


def _parse_github_output(path: Path) -> dict[str, str]:
    outputs: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if not line:
            continue
        key, _, value = line.partition("=")
        outputs[key] = value
    return outputs


def _run_leg(tmp_path: Path, name: str, exists: bool) -> Path:
    """Execute the check job's own write-result step for one matrix leg, in its own isolated
    workspace as it would run on its own runner, and return the json file it produced."""
    leg_dir = tmp_path / f"leg-{name}"
    leg_dir.mkdir()
    env = {
        "PATH": os.environ["PATH"],
        "CHECK_NAME": name,
        "CHECK_RESULT": "true" if exists else "false",
    }
    result = subprocess.run(
        ["bash", "-c", _write_result_script()],
        cwd=leg_dir,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"write-result failed for {name!r}: {result.stderr}"
    produced = leg_dir / "results" / f"{name}.json"
    assert produced.exists(), f"write-result did not produce results/{name}.json"
    return produced


def _run_aggregate(tmp_path: Path, run_id: str, artifact_files_in_arrival_order: list[Path]) -> dict[str, str]:
    """Execute the aggregate job's own script against a results/ directory populated in the
    given arrival order, exactly as `actions/download-artifact` with merge-multiple would leave
    it after each leg's artifact lands, and return the parsed `results` output."""
    agg_dir = tmp_path / f"aggregate-{run_id}"
    results_dir = agg_dir / "results"
    results_dir.mkdir(parents=True)
    for source in artifact_files_in_arrival_order:
        (results_dir / source.name).write_text(source.read_text())

    github_output = agg_dir / "github_output"
    github_output.write_text("")
    env = {"PATH": os.environ["PATH"], "GITHUB_OUTPUT": str(github_output)}
    result = subprocess.run(
        ["bash", "-c", _aggregate_script()],
        cwd=agg_dir,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"aggregate failed: {result.stderr}"
    outputs = _parse_github_output(github_output)
    return json.loads(outputs["results"])


LEGS = [
    ("cratesio", True),
    ("pypi", False),
    ("npm", True),
    ("npm-wasm", True),
    ("maven-kotlin-android", False),
]


def test_every_leg_survives_regardless_of_arrival_order(tmp_path):
    files = [_run_leg(tmp_path, name, exists) for name, exists in LEGS]
    # Callers compare against the JSON strings "true"/"false", not Python/JSON booleans -- see
    # test_write_result_emits_string_values_not_booleans for why that distinction matters.
    expected = {name: ("true" if exists else "false") for name, exists in LEGS}

    forward = _run_aggregate(tmp_path, "forward", files)
    reverse = _run_aggregate(tmp_path, "reverse", list(reversed(files)))
    shuffled = _run_aggregate(tmp_path, "shuffled", [files[3], files[0], files[4], files[1], files[2]])

    assert forward == expected
    assert reverse == expected
    assert shuffled == expected


def test_write_result_emits_string_values_not_booleans(tmp_path):
    """Callers compare `fromJson(...outputs.results).<name> != 'true'` -- a STRING comparison,
    the contract ~30 existing gate conditions across tslp and lllm already encode. `jq --argjson`
    parses its argument as JSON, so a `CHECK_RESULT` of the string "true" becomes the JSON
    boolean `true`, silently changing the aggregated value's type. GitHub Actions expression
    semantics compare mismatched-type operands by casting both to numbers: `true` casts to `1`,
    but the string `'true'` casts to `NaN`, so `true != 'true'` evaluates to TRUE regardless of
    the real registry state -- the exact fail-open failure the matrix collision caused, now
    triggered by value type instead of a collapsed key."""
    exists_file = _run_leg(tmp_path, "cratesio", True)
    missing_file = _run_leg(tmp_path, "pypi", False)

    exists_raw = exists_file.read_text()
    missing_raw = missing_file.read_text()
    assert '"true"' in exists_raw, (
        f"expected a quoted JSON string \"true\" so callers' `!= 'true'` string comparison holds, got: {exists_raw!r}"
    )
    assert '"false"' in missing_raw, f'expected a quoted JSON string "false", got: {missing_raw!r}'

    exists_payload = json.loads(exists_raw)
    missing_payload = json.loads(missing_raw)
    assert exists_payload == {"cratesio": "true"}
    assert missing_payload == {"pypi": "false"}
    assert isinstance(exists_payload["cratesio"], str), (
        f"expected str, got {type(exists_payload['cratesio']).__name__}: "
        f"{exists_payload['cratesio']!r} -- a JSON boolean here breaks every caller's string gate"
    )
    assert isinstance(missing_payload["pypi"], str), (
        f"expected str, got {type(missing_payload['pypi']).__name__}: {missing_payload['pypi']!r}"
    )


def test_aggregation_survives_whichever_leg_finishes_last():
    """Regression for the collision itself: under the old job-level `outputs:` on a matrixed
    job, only whichever leg finished last was visible at all, and it varied by name depending
    on scheduling. Assert the *last-arriving* file never eclipses the earlier ones."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        files = [_run_leg(tmp_path, name, exists) for name, exists in LEGS]
        for finisher in files:
            arrival_order = [f for f in files if f != finisher] + [finisher]
            result = _run_aggregate(tmp_path, f"late-{finisher.stem}", arrival_order)
            expected = {name: ("true" if exists else "false") for name, exists in LEGS}
            assert result == expected, f"leg {finisher.stem!r} finishing last corrupted the aggregate: {result}"


def test_write_result_fails_loudly_on_an_empty_verdict(tmp_path):
    """If the check step succeeds but sets no `all-exist` output, the leg must fail visibly
    rather than silently writing an empty-string verdict into the aggregate -- a silent "" would
    also fail open, the same class of bug as the boolean-vs-string mismatch above, just
    triggered by a missing value instead of a wrong-typed one."""
    leg_dir = tmp_path / "leg-empty"
    leg_dir.mkdir()
    env = {"PATH": os.environ["PATH"], "CHECK_NAME": "cratesio", "CHECK_RESULT": ""}
    result = subprocess.run(
        ["bash", "-c", _write_result_script()],
        cwd=leg_dir,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0, "an empty CHECK_RESULT must fail the step, not silently succeed"
    assert not (leg_dir / "results").exists() or not list((leg_dir / "results").glob("*.json")), (
        "no verdict file should be written when the check result is missing"
    )


def test_check_job_does_not_declare_a_shared_matrix_output():
    """The defect itself: a job-level `outputs:` block on a job with `strategy: matrix:` is a
    single namespace shared by every leg, so it cannot carry per-leg results."""
    check_job = _workflow()["jobs"]["check"]
    assert "outputs" not in check_job, (
        "the check job declares job-level outputs while using a matrix strategy -- every leg "
        "silently overwrites the others, non-deterministically, depending on completion order"
    )


def test_workflow_output_still_wires_to_the_aggregate_job():
    # PyYAML's default (1.1) resolver coerces the bare `on:` key to the boolean True.
    workflow_outputs = _workflow()[True]["workflow_call"]["outputs"]
    assert workflow_outputs["results"]["value"] == "${{ jobs.aggregate.outputs.results }}"
