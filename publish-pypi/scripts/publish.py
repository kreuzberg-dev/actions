#!/usr/bin/env python3
"""Find and validate dist files for PyPI publishing.

Usage (GitHub Actions via env vars):
    INPUT_PACKAGES_DIR=dist INPUT_DRY_RUN=false python3 publish.py
"""

import os
import sys
from pathlib import Path


def find_dist_files(directory: Path) -> list[Path]:
    """Return all .whl and .tar.gz files found directly in directory."""
    files: list[Path] = []
    files.extend(sorted(directory.glob("*.whl")))
    files.extend(sorted(directory.glob("*.tar.gz")))
    return files


def validate_dist_dir(directory: Path) -> list[Path]:
    """Validate the dist directory and return its dist files.

    Raises:
        SystemExit: If the directory does not exist or contains no dist files.
    """
    if not directory.exists():
        print(f"Error: packages directory does not exist: {directory}", file=sys.stderr)
        sys.exit(1)

    files = find_dist_files(directory)
    if not files:
        print(f"Error: no .whl or .tar.gz files found in {directory}", file=sys.stderr)
        sys.exit(1)

    return files


def main() -> None:
    packages_dir = Path(os.environ.get("INPUT_PACKAGES_DIR", "dist"))
    dry_run = os.environ.get("INPUT_DRY_RUN", "false").lower() == "true"

    files = validate_dist_dir(packages_dir)

    print(f"Found {len(files)} dist file(s) in {packages_dir}:")
    for f in files:
        print(f"  {f.name}")

    if dry_run:
        print("[dry-run] Skipping publish")
        return

    print("Ready for publish")


if __name__ == "__main__":
    main()
