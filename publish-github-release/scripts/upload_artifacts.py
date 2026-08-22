#!/usr/bin/env python3
"""Upload artifact files to a GitHub release.

Usage (GitHub Actions via env vars):
    INPUT_TAG=v1.2.3 INPUT_ARTIFACTS="dist/*.whl,dist/*.tar.gz" python3 upload_artifacts.py

    INPUT_FAIL_IF_EMPTY: "false" to warn instead of failing when the patterns match nothing
    (default true).
"""

import json
import mimetypes
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

UPLOAD_MAX_ATTEMPTS = 5
UPLOAD_BACKOFF_BASE_SECONDS = 2.0


def env_bool(key: str, default: bool = False) -> bool:
    """Read a GitHub Actions boolean-ish input, falling back to `default` when unset."""
    raw = os.environ.get(key, "").strip().lower()
    if not raw:
        return default
    return raw in {"true", "1", "yes", "y", "on"}


def get_github_api_headers(token: str) -> dict[str, str]:
    """Return headers for GitHub REST API v2022-11-28."""
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "xberg-io-actions-publish-github-release",
    }


def expand_artifact_patterns(patterns: str) -> list[Path]:
    """Expand comma- or newline-separated glob patterns into a list of existing files."""
    normalized = patterns.replace(",", "\n")
    files: list[Path] = []
    for raw in normalized.splitlines():
        pattern = raw.strip()
        if not pattern:
            continue
        files.extend(path for path in sorted(Path().glob(pattern)) if path.is_file())
    return files


def get_release_by_tag(owner: str, repo: str, tag: str, token: str) -> dict[str, Any]:
    """Get release info for a tag. Exits on error."""
    url = f"https://api.github.com/repos/{owner}/{repo}/releases/tags/{tag}"
    headers = get_github_api_headers(token)

    req = urllib.request.Request(url, headers=headers, method="GET")

    try:
        with urllib.request.urlopen(req) as response:  # noqa: S310
            data: dict[str, Any] = json.loads(response.read().decode("utf-8"))
            return data
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        print(
            f"Error: HTTP {e.code} {e.reason} from {url}",
            file=sys.stderr,
        )
        print(error_body, file=sys.stderr)
        sys.exit(1)


def delete_asset(owner: str, repo: str, asset_id: int, token: str) -> None:
    """Delete an asset via DELETE /repos/{owner}/{repo}/releases/assets/{id}."""
    url = f"https://api.github.com/repos/{owner}/{repo}/releases/assets/{asset_id}"
    headers = get_github_api_headers(token)

    req = urllib.request.Request(url, headers=headers, method="DELETE")

    try:
        with urllib.request.urlopen(req):  # noqa: S310
            pass
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        print(
            f"Error: HTTP {e.code} {e.reason} deleting asset {asset_id}",
            file=sys.stderr,
        )
        print(error_body, file=sys.stderr)
        sys.exit(1)


def upload_asset(upload_url: str, filename: str, file_path: Path, token: str) -> None:
    """Upload a file to a release.

    upload_url is the GitHub release's upload_url with {?name,label} template,
    e.g. "https://uploads.github.com/repos/owner/repo/releases/123/assets{?name,label}".
    Strip the template, append ?name=<filename>, and POST the file.
    """
    if "{" in upload_url:
        upload_url = upload_url[: upload_url.index("{")]

    query_string = urllib.parse.urlencode({"name": filename})
    url = f"{upload_url}?{query_string}"

    mime_type, _ = mimetypes.guess_type(str(file_path))
    if mime_type is None:
        mime_type = "application/octet-stream"

    with file_path.open("rb") as f:
        file_data = f.read()

    headers = get_github_api_headers(token)
    headers["Content-Type"] = mime_type

    last_error: Exception | None = None
    for attempt in range(1, UPLOAD_MAX_ATTEMPTS + 1):
        req = urllib.request.Request(url, data=file_data, headers=headers, method="POST")  # noqa: S310
        try:
            with urllib.request.urlopen(req):  # noqa: S310
                return
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8")
            if 500 <= e.code < 600 and attempt < UPLOAD_MAX_ATTEMPTS:
                backoff = UPLOAD_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
                print(
                    f"  Transient HTTP {e.code} {e.reason} on attempt {attempt}/{UPLOAD_MAX_ATTEMPTS}; "
                    f"retrying in {backoff:.1f}s",
                    file=sys.stderr,
                )
                time.sleep(backoff)
                last_error = e
                continue
            print(
                f"Error: HTTP {e.code} {e.reason} uploading {filename}",
                file=sys.stderr,
            )
            print(error_body, file=sys.stderr)
            sys.exit(1)
        except (urllib.error.URLError, ssl.SSLError, ConnectionError, TimeoutError) as e:
            last_error = e
            if attempt < UPLOAD_MAX_ATTEMPTS:
                backoff = UPLOAD_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
                print(
                    f"  Transient network error on attempt {attempt}/{UPLOAD_MAX_ATTEMPTS}: {e}; "
                    f"retrying in {backoff:.1f}s",
                    file=sys.stderr,
                )
                time.sleep(backoff)
                continue
            break

    print(
        f"Error: failed to upload {filename} after {UPLOAD_MAX_ATTEMPTS} attempts: {last_error}",
        file=sys.stderr,
    )
    sys.exit(1)


def main() -> None:
    tag = os.environ.get("INPUT_TAG", "")
    artifacts_str = os.environ.get("INPUT_ARTIFACTS", "")
    token = os.environ.get("GH_TOKEN", "")
    repository = os.environ.get("GITHUB_REPOSITORY", "")

    if not tag:
        print("Error: INPUT_TAG is required", file=sys.stderr)
        sys.exit(1)

    if not artifacts_str:
        print("Error: INPUT_ARTIFACTS is required", file=sys.stderr)
        sys.exit(1)

    if not token:
        print("Error: GH_TOKEN is required", file=sys.stderr)
        sys.exit(1)

    if not repository:
        print("Error: GITHUB_REPOSITORY is required", file=sys.stderr)
        sys.exit(1)

    owner, repo = repository.split("/", 1)

    files = expand_artifact_patterns(artifacts_str)

    if not files:
        message = f"no files matched artifact pattern(s) {artifacts_str!r}"
        if env_bool("INPUT_FAIL_IF_EMPTY", default=True):
            print(
                f"Error: {message}; refusing an upload that would report success with zero "
                "release assets. Set fail-if-empty: 'false' if an empty match is expected.",
                file=sys.stderr,
            )
            sys.exit(1)
        print(f"::warning::{message}; skipping upload")
        return

    print(f"Uploading {len(files)} artifact(s) to release {tag}...")

    release = get_release_by_tag(owner, repo, tag, token)
    upload_url = release.get("upload_url", "")
    existing_assets = {asset["name"]: asset["id"] for asset in release.get("assets", [])}

    for file in files:
        filename = file.name
        print(f"  Uploading {filename}...")

        if filename in existing_assets:
            asset_id = existing_assets[filename]
            print(f"    Removing existing {filename}...")
            delete_asset(owner, repo, asset_id, token)

        upload_asset(upload_url, filename, file, token)

    print("All artifacts uploaded")


if __name__ == "__main__":
    main()
