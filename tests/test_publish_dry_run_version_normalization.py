"""Every publish action's release-version guard must survive a dry run.

A dry run synthesizes its tag as ``<version>-dryrun-<sha>`` (see
``prepare-release-metadata``), a version no manifest ever declares. An action that compares
that verbatim fails every dry run on a correct checkout -- and a guard that can only fail is
worse than no guard, because it trains people to ignore it.

``v1.11.0`` shipped the guards to five of these actions without the strip, so the first dry
run after ``v1`` moved failed on ``html-to-markdown`` at a step asserting a bundle that was in
fact correct. These tests pin the strip for every action that carries the guard.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

ACTIONS = [
    ("publish-npm", "scripts/publish.py"),
    ("publish-pypi", "scripts/publish.py"),
    ("publish-maven", "scripts/deploy.py"),
    ("publish-nuget", "scripts/publish.py"),
    ("publish-rubygems", "scripts/publish.py"),
    ("publish-crates", "scripts/publish.py"),
]


def _load(action: str, rel: str):
    path = REPO_ROOT / action / rel
    spec = importlib.util.spec_from_file_location(action.replace("-", "_"), path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except SystemExit:  # a module that runs main() under __main__ only
        pass
    return module


@pytest.mark.parametrize(("action", "rel"), ACTIONS, ids=[a for a, _ in ACTIONS])
def test_a_dry_run_tag_suffix_is_stripped_so_the_guard_still_runs(action: str, rel: str) -> None:
    normalize = _load(action, rel).normalize_release_version
    assert normalize("3.12.0-dryrun-5d9b85d") == "3.12.0"
    assert normalize("v3.12.0-dryrun-5d9b85d") == "3.12.0"


@pytest.mark.parametrize(("action", "rel"), ACTIONS, ids=[a for a, _ in ACTIONS])
def test_a_prerelease_is_not_mistaken_for_a_dry_run_tag(action: str, rel: str) -> None:
    """The strip must key on the literal ``-dryrun-`` marker, not on the first hyphen.

    Widening it to ``-`` would silently compare ``1.9.0-rc.2`` as ``1.9.0`` and accept a
    stable artifact for a prerelease tag.
    """
    normalize = _load(action, rel).normalize_release_version
    assert normalize("1.9.0-rc.2") == "1.9.0-rc.2"
    assert normalize("v0.1.0-alpha.2") == "0.1.0-alpha.2"


@pytest.mark.parametrize(("action", "rel"), ACTIONS, ids=[a for a, _ in ACTIONS])
def test_a_plain_release_version_passes_through_unchanged(action: str, rel: str) -> None:
    normalize = _load(action, rel).normalize_release_version
    assert normalize("v3.12.0") == "3.12.0"
    assert normalize("  3.12.0  ") == "3.12.0"
