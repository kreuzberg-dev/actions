import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "prepare-release-metadata" / "scripts" / "prepare.py"

spec = importlib.util.spec_from_file_location("prepare_release_metadata", str(_SCRIPT))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

AVAILABLE = [
    "python",
    "node",
    "ruby",
    "cli",
    "crates",
    "docker",
    "homebrew",
    "java",
    "csharp",
    "go",
    "wasm",
    "php",
    "elixir",
    "r",
    "c_ffi",
]


# ---------------------------------------------------------------------------
# validate_tag
# ---------------------------------------------------------------------------


def test_validate_tag_valid():
    assert mod.validate_tag("v4.3.6") == "4.3.6"


def test_validate_tag_prerelease():
    assert mod.validate_tag("v1.0.0-rc.1") == "1.0.0-rc.1"


def test_validate_tag_missing_v():
    with pytest.raises(SystemExit):
        mod.validate_tag("4.3.6")


def test_validate_tag_empty():
    with pytest.raises(SystemExit):
        mod.validate_tag("")


# ---------------------------------------------------------------------------
# determine_npm_tag
# ---------------------------------------------------------------------------


def test_determine_npm_tag_latest():
    assert mod.determine_npm_tag("4.3.6") == "latest"


def test_determine_npm_tag_rc():
    assert mod.determine_npm_tag("4.3.6-rc.1") == "next"


def test_determine_npm_tag_alpha():
    assert mod.determine_npm_tag("1.0.0-alpha.1") == "next"


def test_determine_npm_tag_beta():
    assert mod.determine_npm_tag("1.0.0-beta.2") == "next"


def test_determine_npm_tag_pre():
    assert mod.determine_npm_tag("1.0.0-pre.1") == "next"


# ---------------------------------------------------------------------------
# resolve_ref
# ---------------------------------------------------------------------------


def test_resolve_ref_empty():
    ref, checkout_ref, target_sha, matrix_ref, is_tag = mod.resolve_ref("", "v4.3.6")
    assert ref == "refs/tags/v4.3.6"
    assert checkout_ref == "refs/tags/v4.3.6"
    assert target_sha == ""
    assert matrix_ref == "v4.3.6"
    assert is_tag is True


def test_resolve_ref_same_as_tag():
    ref, checkout_ref, target_sha, matrix_ref, is_tag = mod.resolve_ref("v4.3.6", "v4.3.6")
    assert ref == "refs/tags/v4.3.6"
    assert checkout_ref == "refs/tags/v4.3.6"
    assert target_sha == ""
    assert matrix_ref == "v4.3.6"
    assert is_tag is True


def test_resolve_ref_sha40():
    sha = "a" * 40
    _ref, checkout_ref, target_sha, matrix_ref, is_tag = mod.resolve_ref(sha, "v4.3.6")
    assert checkout_ref == "refs/heads/main"
    assert target_sha == sha
    assert matrix_ref == "main"
    assert is_tag is False


def test_resolve_ref_explicit_ref():
    _ref, checkout_ref, target_sha, _matrix_ref, is_tag = mod.resolve_ref("refs/heads/fix", "v4.3.6")
    assert checkout_ref == "refs/heads/fix"
    assert target_sha == ""
    assert is_tag is False


def test_resolve_ref_branch_name():
    _ref, checkout_ref, _target_sha, _matrix_ref, is_tag = mod.resolve_ref("fix-branch", "v4.3.6")
    assert checkout_ref == "refs/heads/fix-branch"
    assert is_tag is False


def test_resolve_ref_tag_ref():
    ref, _checkout_ref, _target_sha, _matrix_ref, is_tag = mod.resolve_ref("refs/tags/v1.0", "v4.3.6")
    assert is_tag is True
    assert ref == "refs/tags/v1.0"


# ---------------------------------------------------------------------------
# route_event
# ---------------------------------------------------------------------------


def test_route_event_workflow_dispatch(monkeypatch):
    env = {
        "INPUT_TAG": "v4.3.6",
        "INPUT_DRY_RUN": "true",
        "INPUT_FORCE_REPUBLISH": "false",
        "INPUT_REF": "refs/heads/main",
        "INPUT_TARGETS": "python,node",
    }
    result = mod.route_event("workflow_dispatch", env)
    assert result["tag"] == "v4.3.6"
    assert result["dry_run"] == "true"
    assert result["force_republish"] == "false"
    assert result["ref"] == "refs/heads/main"
    assert result["targets"] == "python,node"


def test_route_event_release():
    env = {"EVENT_RELEASE_TAG": "v2.0.0"}
    result = mod.route_event("release", env)
    assert result["tag"] == "v2.0.0"
    assert result["dry_run"] == "false"
    assert result["force_republish"] == "false"
    assert result["ref"] == "refs/tags/v2.0.0"


def test_route_event_repository_dispatch():
    env = {
        "EVENT_DISPATCH_TAG": "v3.1.0",
        "EVENT_DISPATCH_DRY_RUN": "true",
        "EVENT_DISPATCH_FORCE_REPUBLISH": "true",
        "EVENT_DISPATCH_REF": "refs/heads/release",
        "EVENT_DISPATCH_TARGETS": "python",
    }
    result = mod.route_event("repository_dispatch", env)
    assert result["tag"] == "v3.1.0"
    assert result["dry_run"] == "true"
    assert result["force_republish"] == "true"
    assert result["ref"] == "refs/heads/release"
    assert result["targets"] == "python"


def test_route_event_default_prerelease():
    env = {"GITHUB_REF_NAME": "v1.0.0-rc.1"}
    result = mod.route_event("push", env)
    assert result["tag"] == "v1.0.0-rc.1"
    assert result["dry_run"] == "true"


# ---------------------------------------------------------------------------
# parse_targets
# ---------------------------------------------------------------------------


def test_parse_targets_all():
    result = mod.parse_targets("", AVAILABLE)
    assert all(result[t] for t in AVAILABLE)


def test_parse_targets_star():
    result = mod.parse_targets("*", AVAILABLE)
    assert all(result[t] for t in AVAILABLE)


def test_parse_targets_specific():
    result = mod.parse_targets("python,node", AVAILABLE)
    assert result["python"] is True
    assert result["node"] is True
    assert result["ruby"] is False
    assert result["crates"] is False


def test_parse_targets_aliases():
    result = mod.parse_targets("dotnet,golang", AVAILABLE)
    assert result["csharp"] is True
    assert result["go"] is True
    assert result["python"] is False


def test_parse_targets_none():
    result = mod.parse_targets("none", AVAILABLE)
    assert all(not result[t] for t in AVAILABLE)


def test_parse_targets_unknown():
    with pytest.raises(SystemExit):
        mod.parse_targets("invalid", AVAILABLE)


def test_parse_targets_homebrew_implies_cli():
    result = mod.parse_targets("homebrew", AVAILABLE)
    assert result["homebrew"] is True
    assert result["cli"] is True


def test_parse_targets_case_insensitive():
    result = mod.parse_targets("Python,NODE", AVAILABLE)
    assert result["python"] is True
    assert result["node"] is True
