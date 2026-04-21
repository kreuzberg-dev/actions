#!/usr/bin/env python3
"""Publish RubyGems packages from a directory.

Usage (GitHub Actions via env vars):
    INPUT_GEMS_DIR=dist/gems/ python3 publish.py
"""

import os
import re
import subprocess
import sys
from pathlib import Path

ALREADY_PUBLISHED_PATTERN = re.compile(
    r"repushing.*not allowed|already been pushed",
    re.IGNORECASE,
)


def is_already_published(output: str) -> bool:
    """Return True if the gem push output indicates the gem was already published."""
    return bool(ALREADY_PUBLISHED_PATTERN.search(output))


def validate_gem_structure(path: Path) -> bool:
    """Return True if path is a non-empty, readable gem with valid structure."""
    if not path.is_file() or not os.access(path, os.R_OK) or path.stat().st_size == 0:
        return False
    result = subprocess.run(["gem", "spec", str(path)], capture_output=True, check=False)
    return result.returncode == 0


def find_gem_files(directory: Path) -> list[Path]:
    """Return all *.gem files in directory (non-recursive)."""
    return sorted(directory.glob("*.gem"))


def _run(cmd: list[str]) -> tuple[int, str]:
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return result.returncode, result.stdout + result.stderr


def main() -> None:
    gems_dir = os.environ.get("INPUT_GEMS_DIR", "")
    dry_run = os.environ.get("INPUT_DRY_RUN", "false").lower() == "true"

    if not gems_dir:
        print("Error: INPUT_GEMS_DIR is required", file=sys.stderr)
        sys.exit(1)

    gems_path = Path(gems_dir)
    if not gems_path.is_dir():
        print(f"Error: gems directory not found: {gems_dir}", file=sys.stderr)
        sys.exit(1)

    gem_files = find_gem_files(gems_path)
    if not gem_files:
        print(f"Error: no .gem files found in {gems_dir}", file=sys.stderr)
        sys.exit(1)

    failed = 0
    published = 0

    print(f"Publishing {len(gem_files)} gem(s)...")

    for gem_file in gem_files:
        name = gem_file.name

        if not gem_file.is_file() or not os.access(gem_file, os.R_OK) or gem_file.stat().st_size == 0:
            print(f"  Error: {name} is missing, unreadable, or empty", file=sys.stderr)
            failed += 1
            continue

        if not validate_gem_structure(gem_file):
            print(f"  Error: {name} has invalid gem structure", file=sys.stderr)
            failed += 1
            continue

        print(f"Publishing {name}...")

        if dry_run:
            print(f"  [dry-run] gem push {name}")
            published += 1
            continue

        exit_code, output = _run(["gem", "push", str(gem_file)])

        if exit_code == 0:
            print(f"  Published {name}")
            published += 1
        elif is_already_published(output):
            print(f"  {name} already published, skipping")
            published += 1
        else:
            print(f"  Error publishing {name}:", file=sys.stderr)
            print(output, file=sys.stderr)
            failed += 1

    print(f"Published: {published}, Failed: {failed}")

    if failed > 0:
        sys.exit(1)

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY", "")
    if summary_path:
        with Path(summary_path).open("a") as fh:
            fh.write("### RubyGems Publish\n")
            fh.write(f"- Published: {published}\n")
            fh.write(f"- Failed: {failed}\n")


if __name__ == "__main__":
    main()
