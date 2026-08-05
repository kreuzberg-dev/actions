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
        print(f"[dry-run] Would create/ensure release for tag: {tag}")
        print(f"  Title: {title}")
        print(f"  Generate notes: {generate_notes}")
        print(f"  Draft: {draft}")
        print(f"  Pre-release: {prerelease}")
        if target:
            print(f"  Target: {target}")
        sys.exit(0)

    existing = get_release_by_tag(owner, repo, tag, token)

    if existing:
        print(f"Release {tag} already exists")
        is_draft = existing.get("draft", False)

        actual_tag_name = existing.get("tag_name", "")
        if actual_tag_name != tag:
            print(
                f"Warning: release has tag_name={actual_tag_name}, expected {tag}; repairing...",
                file=sys.stderr,
            )
            release_id = int(existing.get("id", 0))
            repaired = update_release(owner, repo, release_id, tag_name=tag, token=token)
            if repaired.get("tag_name") != tag:
                print(
                    f"Error: PATCH to fix tag_name failed; release still has tag_name={repaired.get('tag_name')}",
                    file=sys.stderr,
                )
                sys.exit(1)
            print(f"Repaired tag_name to {tag}")

        if is_draft and not draft:
            print(f"Publishing draft release {tag}...")
            release_id = int(existing.get("id", 0))
            update_release(owner, repo, release_id, draft=False, token=token)
    else:
        max_tag_wait_attempts = 12
        tag_wait_interval = 5
        tag_confirmed = False

        for attempt in range(1, max_tag_wait_attempts + 1):
            if tag_exists_on_git(owner, repo, tag, token):
                tag_confirmed = True
                break
            if attempt < max_tag_wait_attempts:
                print(
                    f"Tag {tag} not visible yet ({attempt}/{max_tag_wait_attempts}); "
                    f"retrying in {tag_wait_interval}s...",
                    file=sys.stderr,
                )
                time.sleep(tag_wait_interval)

        if not tag_confirmed:
            print(
                f"Error: Tag {tag} not found on remote after {max_tag_wait_attempts * tag_wait_interval}s. "
                f"Push the tag before publishing.",
                file=sys.stderr,
            )
            sys.exit(1)

        all_releases = list_releases(owner, repo, token)
        broken_draft = None
        for rel in all_releases:
            if rel.get("name") == tag and rel.get("tag_name", "").startswith("untagged-"):
                broken_draft = rel
                break

        if broken_draft:
            print(f"Found pre-existing broken draft for {tag}; repairing tag_name...")
            release_id = int(broken_draft.get("id", 0))
            repaired = update_release(owner, repo, release_id, tag_name=tag, token=token)
            if repaired.get("tag_name") != tag:
                print(
                    f"Error: PATCH to fix broken draft tag_name failed; still has tag_name={repaired.get('tag_name')}",
                    file=sys.stderr,
                )
                sys.exit(1)
            print(f"Repaired broken draft, tag_name now {tag}")
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
                release_id = int(created.get("id", 0))
                repaired = update_release(owner, repo, release_id, tag_name=tag, token=token)
                if repaired.get("tag_name") != tag:
                    print(
                        f"Error: PATCH to fix tag_name failed; release still has tag_name={repaired.get('tag_name')}",
                        file=sys.stderr,
                    )
                    sys.exit(1)
                print(f"Repaired tag_name to {tag}")

    print(f"Release {tag} ready")


if __name__ == "__main__":
    main()
