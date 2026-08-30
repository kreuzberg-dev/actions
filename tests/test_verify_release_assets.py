"""Tests for the verify-release-assets action's release-lookup helpers."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from types import ModuleType

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "verify-release-assets" / "scripts" / "verify_assets.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("verify_assets", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _completed(stdout: str = "", stderr: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=["gh"], returncode=returncode, stdout=stdout, stderr=stderr)


def test_parse_release_list_reads_a_single_array() -> None:
    module = _load_module()
    assert module._parse_release_list('[{"tag_name": "v1"}]') == [{"tag_name": "v1"}]


def test_parse_release_list_concatenates_paginated_arrays() -> None:
    """`gh api --paginate` emits one JSON array per page, newline-separated."""
    module = _load_module()
    payload = '[{"tag_name": "v1"}]\n[{"tag_name": "v2"}]\n'
    assert module._parse_release_list(payload) == [{"tag_name": "v1"}, {"tag_name": "v2"}]


def test_parse_release_list_raises_on_garbage() -> None:
    module = _load_module()
    with pytest.raises(json.JSONDecodeError):
        module._parse_release_list("[not json")


def test_assets_for_tag_returns_matching_release_assets() -> None:
    module = _load_module()
    releases = [
        {"tag_name": "v1", "assets": [{"name": "a.zip"}]},
        {"tag_name": "v2", "assets": [{"name": "b.zip"}]},
    ]
    assert module._assets_for_tag(releases, "v2") == [{"name": "b.zip"}]


def test_assets_for_tag_returns_none_when_absent() -> None:
    module = _load_module()
    assert module._assets_for_tag([{"tag_name": "v1", "assets": []}], "v9") is None


def test_assets_for_tag_distinguishes_missing_release_from_assetless_one() -> None:
    """A found-but-empty release must return [], not None — None means 'keep retrying'."""
    module = _load_module()
    assert module._assets_for_tag([{"tag_name": "v1"}], "v1") == []


def test_assets_for_tag_skips_non_dict_entries() -> None:
    module = _load_module()
    releases: list[Any] = ["junk", None, {"tag_name": "v1", "assets": [{"name": "a.zip"}]}]
    assert module._assets_for_tag(releases, "v1") == [{"name": "a.zip"}]


def test_lookup_via_api_reports_gh_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "_run_gh", lambda _argv: _completed(stderr="boom", returncode=1))
    assets, err = module._lookup_via_api("o/r", "v1")
    assert assets is None
    assert err == "boom"


def test_lookup_via_api_returns_assets_on_match(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    payload = json.dumps([{"tag_name": "v1", "assets": [{"name": "a.zip", "size": 10}]}])
    monkeypatch.setattr(module, "_run_gh", lambda _argv: _completed(stdout=payload))
    assets, err = module._lookup_via_api("o/r", "v1")
    assert assets == [{"name": "a.zip", "size": 10}]
    assert err == ""


def test_lookup_via_view_reports_non_json(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "_run_gh", lambda _argv: _completed(stdout="<html>"))
    assets, err = module._lookup_via_view("o/r", "v1")
    assert assets is None
    assert "non-JSON" in err


def test_fetch_release_assets_falls_back_to_view(monkeypatch: pytest.MonkeyPatch) -> None:
    """The API listing can succeed yet not contain the tag; the view lookup then resolves it."""
    module = _load_module()
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")

    def _fake_run(argv: list[str]) -> subprocess.CompletedProcess[str]:
        if argv[1] == "api":
            return _completed(stdout=json.dumps([{"tag_name": "other", "assets": []}]))
        return _completed(stdout=json.dumps({"assets": [{"name": "found.zip"}]}))

    monkeypatch.setattr(module, "_run_gh", _fake_run)
    assert module.fetch_release_assets("v1") == [{"name": "found.zip"}]


def test_fetch_release_assets_retries_then_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setattr(module, "MAX_LOOKUP_ATTEMPTS", 3)
    monkeypatch.setattr(module, "LOOKUP_SLEEP_SECONDS", 0)
    calls: list[list[str]] = []

    def _fake_run(argv: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return _completed(stderr="not found", returncode=1)

    monkeypatch.setattr(module, "_run_gh", _fake_run)
    with pytest.raises(SystemExit) as excinfo:
        module.fetch_release_assets("v1")
    assert excinfo.value.code == 1
    # Both lookup paths are tried on every attempt.
    assert len(calls) == 6


def test_fetch_release_assets_requires_repo_env(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    monkeypatch.delenv("GH_REPO", raising=False)
    with pytest.raises(SystemExit) as excinfo:
        module.fetch_release_assets("v1")
    assert excinfo.value.code == 1


def test_parse_expected_drops_blanks_and_comments() -> None:
    module = _load_module()
    raw = "a.tar.gz\n\n# a comment\n  b.zip  \n"
    assert module.parse_expected(raw) == ["a.tar.gz", "b.zip"]
