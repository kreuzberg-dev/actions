#!/usr/bin/env python3
"""Upload artifact files to a GitHub release.

Usage (GitHub Actions via env vars):
    INPUT_TAG=v1.2.3 INPUT_ARTIFACTS="dist/*.whl,dist/*.tar.gz" python3 upload_artifacts.py
"""

import os
import subprocess
import sys
from pathlib import Path


def expand_artifact_patterns(patterns: str) -> list[Path]:
    """Expand comma- or newline-separated glob patterns into a list of existing files."""
    # Normalize comma separators to newlines, then split
    normalized = patterns.replace(",", "\n")
    files: list[Path] = []
    for raw in normalized.splitlines():
        pattern = raw.strip()
        if not pattern:
            continue
        # Use Path() as the base so globs resolve relative to the current directory
        files.extend(path for path in sorted(Path().glob(pattern)) if path.is_file())
    return files


def main() -> None:
    tag = os.environ.get("INPUT_TAG", "")
    artifacts_str = os.environ.get("INPUT_ARTIFACTS", "")

    if not tag:
        print("Error: INPUT_TAG is required", file=sys.stderr)
        sys.exit(1)

    if not artifacts_str:
        print("Error: INPUT_ARTIFACTS is required", file=sys.stderr)
        sys.exit(1)

    files = expand_artifact_patterns(artifacts_str)

    if not files:
        print("No artifact files matched, skipping upload")
        sys.exit(0)

    print(f"Uploading {len(files)} artifact(s) to release {tag}...")

    for file in files:
        print(f"  Uploading {file.name}...")
        subprocess.run(["gh", "release", "upload", tag, str(file), "--clobber"], check=True)

    print("All artifacts uploaded")


if __name__ == "__main__":
    main()
