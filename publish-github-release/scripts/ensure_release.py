#!/usr/bin/env python3
"""Ensure a GitHub release exists for a given tag, creating or publishing as needed.

Usage (GitHub Actions via env vars):
    INPUT_TAG=v1.2.3 INPUT_DRY_RUN=false python3 ensure_release.py
"""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

# A freshly pushed tag is not immediately visible to the releases API, so creation
# waits up to a minute for it rather than failing the release outright. ~keep
MAX_TAG_WAIT_ATTEMPTS = 12
TAG_WAIT_INTERVAL_SECONDS = 5


def get_github_api_headers(token: str) -> dict[str, str]:
    """Return headers for GitHub REST API v2022-11-28."""
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "xberg-io-actions-publish-github-release",
    }


def github_request(method: str, url: str, token: str, data: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
    """Make a GitHub REST API request and return (status_code, response_json).

    Raises SystemExit on non-2xx responses (except 404 for GETs).
    """
    headers = get_github_api_headers(token)

    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=body, headers=headers, method=method)  # noqa: S310

    try:
        with urllib.request.urlopen(req) as response:  # noqa: S310
            response_data = json.loads(response.read().decode("utf-8"))
            return response.status, response_data
    except urllib.error.HTTPError as e:
        if method == "GET" and e.code == 404:
            return 404, {}
        error_body = e.read().decode("utf-8")
        print(
            f"Error: HTTP {e.code} {e.reason} from {url}",
            file=sys.stderr,
        )
        print(error_body, file=sys.stderr)
        sys.exit(1)


def get_release_by_tag(owner: str, repo: str, tag: str, token: str) -> dict[str, Any] | None:
    """Get release info for a tag. Returns dict if found, None if 404.

    Retries on 404 with exponential backoff (20 attempts, 10s interval) to absorb
    GitHub API read-replica propagation delays after tag push.
    """
    url = f"https://api.github.com/repos/{owner}/{repo}/releases/tags/{tag}"
    max_attempts = 20
    sleep_seconds = 10

    for attempt in range(1, max_attempts + 1):
        status, data = github_request("GET", url, token)
        if status == 200:
            return data

        if status == 404 and attempt < max_attempts:
            print(
                f"Release lookup attempt {attempt}/{max_attempts} did not find {tag}; "
                f"tag may not be propagated yet, retrying in {sleep_seconds}s...",
                file=sys.stderr,
            )
            time.sleep(sleep_seconds)
        elif status != 200:
            return None

    return None


def tag_exists_on_git(owner: str, repo: str, tag: str, token: str) -> bool:
    """Verify tag exists via git refs endpoint.

    After get_release_by_tag exhausts retries, check if the tag itself is present
    on disk via the canonical git-tag endpoint. This catches cases where the tag
    exists but release metadata is missing.
    """
    url = f"https://api.github.com/repos/{owner}/{repo}/git/refs/tags/{tag}"
    status, _data = github_request("GET", url, token)
    return status == 200


def create_release(
    owner: str,
    repo: str,
    tag: str,
    title: str,
    *,
    generate_notes: bool,
    draft: bool,
    prerelease: bool,
    notes: str = "",
    target: str = "",
    token: str = "",
) -> dict[str, Any]:
    """Create a release via POST /repos/{owner}/{repo}/releases."""
    url = f"https://api.github.com/repos/{owner}/{repo}/releases"

    body_dict = {
        "tag_name": tag,
        "name": title,
        "draft": draft,
        "prerelease": prerelease,
    }

    if notes:
        body_dict["body"] = notes
    elif generate_notes:
        body_dict["generate_release_notes"] = True

    if target:
        body_dict["target_commitish"] = target

    _status, data = github_request("POST", url, token, body_dict)
    return data


def update_release(
    owner: str, repo: str, release_id: int, *, draft: bool | None = None, tag_name: str | None = None, token: str = ""
) -> dict[str, Any]:
    """Update a release via PATCH /repos/{owner}/{repo}/releases/{id}.

    Supports updating draft status and/or tag_name.
    """
    url = f"https://api.github.com/repos/{owner}/{repo}/releases/{release_id}"

    body_dict: dict[str, Any] = {}
    if draft is not None:
        body_dict["draft"] = draft
    if tag_name is not None:
        body_dict["tag_name"] = tag_name

    _status, data = github_request("PATCH", url, token, body_dict)
    return data


def list_releases(owner: str, repo: str, token: str, per_page: int = 30) -> list[dict[str, Any]]:
    """List all releases for a repo via GET /repos/{owner}/{repo}/releases."""
    url = f"https://api.github.com/repos/{owner}/{repo}/releases?per_page={per_page}"
    _status, data = github_request("GET", url, token)
    return data if isinstance(data, list) else []


def _repair_tag_name(
    owner: str, repo: str, release: dict[str, Any], tag: str, token: str, *, success_message: str = ""
) -> None:
    """PATCH a release whose tag_name drifted from `tag`. Exits 1 if the repair does not stick.

    The API can return a release with a placeholder `untagged-*` tag_name, and a release whose
    tag_name is wrong is invisible to every later lookup by tag, so a failed repair must stop
    the pipeline rather than let downstream jobs chase a release they will never find. ~keep
    """
    release_id = int(release.get("id", 0))
    repaired = update_release(owner, repo, release_id, tag_name=tag, token=token)
    if repaired.get("tag_name") != tag:
        print(
            f"Error: PATCH to fix tag_name failed; release still has tag_name={repaired.get('tag_name')}",
            file=sys.stderr,
        )
        sys.exit(1)
    print(success_message or f"Repaired tag_name to {tag}")


def _print_dry_run(tag: str, title: str, *, generate_notes: bool, draft: bool, prerelease: bool, target: str) -> None:
    print(f"[dry-run] Would create/ensure release for tag: {tag}")
    print(f"  Title: {title}")
    print(f"  Generate notes: {generate_notes}")
    print(f"  Draft: {draft}")
    print(f"  Pre-release: {prerelease}")
    if target:
        print(f"  Target: {target}")


def _reconcile_existing(owner: str, repo: str, existing: dict[str, Any], tag: str, token: str, *, draft: bool) -> None:
    print(f"Release {tag} already exists")
    if existing.get("tag_name", "") != tag:
        print(
            f"Warning: release has tag_name={existing.get('tag_name', '')}, expected {tag}; repairing...",
            file=sys.stderr,
        )
        _repair_tag_name(owner, repo, existing, tag, token)

    if existing.get("draft", False) and not draft:
        print(f"Publishing draft release {tag}...")
        update_release(owner, repo, int(existing.get("id", 0)), draft=False, token=token)


def _wait_for_tag(owner: str, repo: str, tag: str, token: str) -> None:
    """Block until the tag is visible on the remote, or exit 1."""
    for attempt in range(1, MAX_TAG_WAIT_ATTEMPTS + 1):
        if tag_exists_on_git(owner, repo, tag, token):
            return
        if attempt < MAX_TAG_WAIT_ATTEMPTS:
            print(
                f"Tag {tag} not visible yet ({attempt}/{MAX_TAG_WAIT_ATTEMPTS}); "
                f"retrying in {TAG_WAIT_INTERVAL_SECONDS}s...",
                file=sys.stderr,
            )
            time.sleep(TAG_WAIT_INTERVAL_SECONDS)

    print(
        f"Error: Tag {tag} not found on remote after {MAX_TAG_WAIT_ATTEMPTS * TAG_WAIT_INTERVAL_SECONDS}s. "
        f"Push the tag before publishing.",
        file=sys.stderr,
    )
    sys.exit(1)


def _find_broken_draft(releases: list[dict[str, Any]], tag: str) -> dict[str, Any] | None:
    """Find a draft named `tag` that GitHub left with a placeholder `untagged-*` tag_name."""
    for release in releases:
        if release.get("name") == tag and release.get("tag_name", "").startswith("untagged-"):
            return release
    return None


def main() -> None:
    tag = os.environ.get("INPUT_TAG", "")
    title = os.environ.get("INPUT_TITLE", "") or tag
    generate_notes = os.environ.get("INPUT_GENERATE_NOTES", "true").lower() == "true"
    draft = os.environ.get("INPUT_DRAFT", "false").lower() == "true"
    prerelease = os.environ.get("INPUT_PRERELEASE", "false").lower() == "true"
    notes = os.environ.get("INPUT_NOTES", "")
    target = os.environ.get("INPUT_TARGET", "").strip()
    dry_run = os.environ.get("INPUT_DRY_RUN", "false").lower() == "true"
    token = os.environ.get("GH_TOKEN", "")
    repository = os.environ.get("GITHUB_REPOSITORY", "")

    if not tag:
        print("Error: INPUT_TAG is required", file=sys.stderr)
        sys.exit(1)

    if not title:
        title = tag

    if not token:
        print("Error: GH_TOKEN is required", file=sys.stderr)
        sys.exit(1)

    if not repository:
        print("Error: GITHUB_REPOSITORY is required", file=sys.stderr)
        sys.exit(1)

    owner, repo = repository.split("/", 1)

    if dry_run:
        _print_dry_run(tag, title, generate_notes=generate_notes, draft=draft, prerelease=prerelease, target=target)
        sys.exit(0)

    existing = get_release_by_tag(owner, repo, tag, token)

    if existing:
        _reconcile_existing(owner, repo, existing, tag, token, draft=draft)
    else:
        _wait_for_tag(owner, repo, tag, token)

        broken_draft = _find_broken_draft(list_releases(owner, repo, token), tag)
        if broken_draft:
            print(f"Found pre-existing broken draft for {tag}; repairing tag_name...")
            _repair_tag_name(
                owner, repo, broken_draft, tag, token, success_message=f"Repaired broken draft, tag_name now {tag}"
            )
        else:
            print(f"Creating release {tag}...")
            created = create_release(
                owner,
                repo,
                tag,
                title,
                generate_notes=generate_notes,
                draft=draft,
                prerelease=prerelease,
                notes=notes,
                target=target,
                token=token,
            )
            if created.get("tag_name") != tag:
                print(
                    f"Warning: created release has tag_name={created.get('tag_name')}, expected {tag}; repairing...",
                    file=sys.stderr,
                )
                _repair_tag_name(owner, repo, created, tag, token)

    print(f"Release {tag} ready")


if __name__ == "__main__":
    main()
