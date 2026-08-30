from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[1]


def test_task_test_collects_every_configured_testpath():
    taskfile = (_ROOT / "Taskfile.yml").read_text()
    test_unit = taskfile.split("  test:unit:", 1)[1].split("\n  test:act:", 1)[0]

    assert "uv run pytest -v" in test_unit
    assert "pytest tests/" not in test_unit

    release_skill = (_ROOT / ".ai-rulez" / "skills" / "release-workflow" / "SKILL.md").read_text()
    assert "runs `uv run pytest -v` across configured testpaths" in release_skill
    assert "pytest tests/" not in release_skill


def test_unit_workflow_runs_when_reusable_validate_changes():
    workflow = yaml.safe_load((_ROOT / ".github" / "workflows" / "test-unit.yml").read_text())
    triggers = workflow[True]

    workflow_path = ".github/workflows/reusable-validate.yml"
    for event in ("push", "pull_request"):
        paths = triggers[event]["paths"]
        assert workflow_path in paths
        assert "Taskfile.yml" in paths
