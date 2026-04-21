#!/usr/bin/env python3
"""Publish NuGet packages from a directory.

Usage (GitHub Actions via env vars):
    INPUT_PACKAGES_DIR=./dist INPUT_DRY_RUN=false python3 publish.py
"""

import os
import subprocess
import sys
from pathlib import Path


def find_nupkg_files(directory: Path) -> list[Path]:
    """Return all .nupkg files found directly in directory (non-recursive)."""
    return sorted(directory.glob("*.nupkg"))


def is_publish_error(exit_code: int, output: str) -> bool:  # noqa: ARG001
    """Return True if the exit code indicates a real publish failure."""
    return exit_code != 0


def _run(cmd: list[str]) -> tuple[int, str]:
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return result.returncode, result.stdout + result.stderr


def main() -> None:
    packages_dir_str = os.environ.get("INPUT_PACKAGES_DIR", "")
    source_url = os.environ.get("INPUT_SOURCE", "https://api.nuget.org/v3/index.json")
    dry_run = os.environ.get("INPUT_DRY_RUN", "false").lower() == "true"

    if not packages_dir_str:
        print("Error: INPUT_PACKAGES_DIR is required", file=sys.stderr)
        sys.exit(1)

    packages_dir = Path(packages_dir_str)

    if not packages_dir.is_dir():
        print(f"Error: packages directory not found: {packages_dir}", file=sys.stderr)
        sys.exit(1)

    nupkg_files = find_nupkg_files(packages_dir)

    if not nupkg_files:
        print(f"Error: no .nupkg files found in {packages_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Publishing {len(nupkg_files)} NuGet package(s)...")

    failed = 0
    published = 0

    for nupkg in nupkg_files:
        name = nupkg.name
        print(f"Publishing {name}...")

        if dry_run:
            print(f"  [dry-run] dotnet nuget push {name}")
            published += 1
            continue

        nuget_api_key = os.environ.get("NUGET_API_KEY", "")
        exit_code, output = _run(
            [
                "dotnet",
                "nuget",
                "push",
                str(nupkg),
                "--api-key",
                nuget_api_key,
                "--source",
                source_url,
                "--skip-duplicate",
            ]
        )

        if is_publish_error(exit_code, output):
            print(f"  Error publishing {name}:", file=sys.stderr)
            print(output, file=sys.stderr)
            failed += 1
        else:
            print(f"  Published {name}")
            published += 1

    print(f"Published: {published}, Failed: {failed}")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
