import shlex
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "free-disk-space-linux" / "scripts" / "free-disk-space.sh"


def test_cleanup_preserves_pre_pulled_action_images():
    content = _SCRIPT.read_text()
    image_prunes = [
        shlex.split(line.strip().removesuffix(" || true"))
        for line in content.splitlines()
        if line.strip().startswith("docker image prune")
    ]

    assert "docker system prune" not in content
    assert image_prunes == [["docker", "image", "prune", "-f"]]
    assert "docker container prune" in content
    assert "docker network prune" in content
    assert "docker volume prune" in content
    assert "docker builder prune" in content


def test_workflow_requires_cleanup_to_reclaim_material_space():
    workflow = (_SCRIPT.parents[2] / ".github" / "workflows" / "test-free-disk-space.yml").read_text()

    assert "MIN_RECLAIMED_BYTES" in workflow
    assert "MIN_RECLAIMED_BYTES=$((512 * 1024 * 1024))" in workflow
    assert "AVAILABLE_BEFORE_BYTES" in workflow
    assert "AVAILABLE_AFTER_BYTES" in workflow
    assert "RECLAIMED_BYTES=$((AVAILABLE_AFTER_BYTES - AVAILABLE_BEFORE_BYTES))" in workflow
    assert "if (( RECLAIMED_BYTES < MIN_RECLAIMED_BYTES )); then" in workflow
    assert "exit 1" in workflow
