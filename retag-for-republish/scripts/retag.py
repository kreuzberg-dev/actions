#!/usr/bin/env python3
"""Delete and recreate a Git tag on HEAD using the GitHub API.

Usage (GitHub Actions via env vars):
    INPUT_TAG=v1.2.3 python3 retag.py
"""

import json
import os
import subprocess
import sys
from pathlib import Path


def build_delete_url(repo: str, tag: str) -> str:
    """Return the GitHub API path to delete a tag ref."""
    return f"repos/{repo}/git/refs/tags/{tag}"


def build_create_payload(tag: str, sha: str) -> dict[str, str]:
    """Return the JSON payload for creating a tag ref."""
    return {"ref": f"refs/tags/{tag}", "sha": sha}


def main() -> None:
    tag = os.environ.get("INPUT_TAG", "")
    if not tag:
        print("Error: INPUT_TAG is required", file=sys.stderr)
        sys.exit(1)

    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not repo:
        print("Error: GITHUB_REPOSITORY is required", file=sys.stderr)
        sys.exit(1)

    sha_result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    sha = sha_result.stdout.strip()

    # Delete existing tag — ignore failure (tag may not exist yet)
    delete_url = build_delete_url(repo, tag)
    subprocess.run(
        ["gh", "api", "--method", "DELETE", delete_url],
        capture_output=True,
        check=False,
    )

    # Recreate tag on HEAD
    payload = build_create_payload(tag, sha)
    subprocess.run(
        ["gh", "api", "--method", "POST", f"repos/{repo}/git/refs", "--input", "-"],
        input=json.dumps(payload),
        text=True,
        check=True,
    )

    # Update local tag
    subprocess.run(["git", "tag", "-d", tag], capture_output=True, check=False)
    subprocess.run(["git", "tag", tag], check=True)

    print(f"Tag {tag} moved to {sha}")

    github_output = os.environ.get("GITHUB_OUTPUT", "")
    if github_output:
        with Path(github_output).open("a") as fh:
            fh.write(f"sha={sha}\n")


if __name__ == "__main__":
    main()
