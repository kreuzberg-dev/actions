import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "retag-for-republish" / "scripts" / "retag.py"

spec = importlib.util.spec_from_file_location("retag", str(_SCRIPT))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


# ---------------------------------------------------------------------------
# build_delete_url
# ---------------------------------------------------------------------------


def test_build_delete_url():
    result = mod.build_delete_url("org/repo", "v1.2.3")
    assert result == "repos/org/repo/git/refs/tags/v1.2.3"


def test_build_delete_url_nested_repo():
    result = mod.build_delete_url("kreuzberg-dev/actions", "v0.5.0")
    assert result == "repos/kreuzberg-dev/actions/git/refs/tags/v0.5.0"


def test_build_delete_url_starts_with_repos():
    result = mod.build_delete_url("org/repo", "v1.0.0")
    assert result.startswith("repos/")


# ---------------------------------------------------------------------------
# build_create_payload
# ---------------------------------------------------------------------------


def test_build_create_payload():
    sha = "a" * 40
    result = mod.build_create_payload("v1.2.3", sha)
    assert result == {"ref": "refs/tags/v1.2.3", "sha": sha}


def test_build_create_payload_format():
    sha = "deadbeef" * 5
    result = mod.build_create_payload("v0.1.0", sha)
    assert result["ref"] == "refs/tags/v0.1.0"
    assert result["sha"] == sha


def test_build_create_payload_ref_prefix():
    sha = "b" * 40
    result = mod.build_create_payload("v2.0.0", sha)
    assert result["ref"].startswith("refs/tags/")
