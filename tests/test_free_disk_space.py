from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "free-disk-space-linux" / "scripts" / "free-disk-space.sh"


def test_cleanup_preserves_pre_pulled_action_images():
    content = _SCRIPT.read_text()

    assert "docker system prune" not in content
    assert "docker image prune" not in content
    assert "docker container prune" in content
    assert "docker builder prune" in content
