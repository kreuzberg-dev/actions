#!/usr/bin/env python3
"""Ensure a GitHub release exists for a given tag, creating or publishing as needed.

Usage (GitHub Actions via env vars):
    INPUT_TAG=v1.2.3 INPUT_DRY_RUN=false python3 ensure_release.py
"""

import json
import os
import subprocess
import sys


def build_create_flags(title: str, generate_notes: bool, draft: bool, prerelease: bool) -> list[str]:
    """Return the list of flags for `gh release create`."""
    flags: list[str] = ["--title", title]
    if generate_notes:
        flags.append("--generate-notes")
    if draft:
        flags.append("--draft")
    if prerelease:
        flags.append("--prerelease")
    return flags


def main() -> None:
    tag = os.environ.get("INPUT_TAG", "")
    title = os.environ.get("INPUT_TITLE", "") or tag
    generate_notes = os.environ.get("INPUT_GENERATE_NOTES", "true").lower() == "true"
    draft = os.environ.get("INPUT_DRAFT", "false").lower() == "true"
    prerelease = os.environ.get("INPUT_PRERELEASE", "false").lower() == "true"
    dry_run = os.environ.get("INPUT_DRY_RUN", "false").lower() == "true"

    if not tag:
        print("Error: INPUT_TAG is required", file=sys.stderr)
        sys.exit(1)

    if not title:
        title = tag

    if dry_run:
        print(f"[dry-run] Would create/ensure release for tag: {tag}")
        print(f"  Title: {title}")
        print(f"  Generate notes: {generate_notes}")
        print(f"  Draft: {draft}")
        print(f"  Pre-release: {prerelease}")
        sys.exit(0)

    # Check if release already exists
    view_result = subprocess.run(
        ["gh", "release", "view", tag, "--json", "isDraft,tagName"],
        capture_output=True,
        text=True,
        check=False,
    )

    if view_result.returncode == 0:
        print(f"Release {tag} already exists")
        try:
            existing = json.loads(view_result.stdout)
        except json.JSONDecodeError:
            existing = {}

        is_draft = bool(existing.get("isDraft", False))
        if is_draft and not draft:
            print(f"Publishing draft release {tag}...")
            subprocess.run(["gh", "release", "edit", tag, "--draft=false"], check=True)
    else:
        print(f"Creating release {tag}...")
        create_flags = build_create_flags(title, generate_notes, draft, prerelease)
        subprocess.run(["gh", "release", "create", tag, *create_flags], check=True)

    print(f"Release {tag} ready")


if __name__ == "__main__":
    main()
