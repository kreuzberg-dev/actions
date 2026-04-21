#!/usr/bin/env python3
"""Publish Rust crates to crates.io.

Usage (GitHub Actions via env vars):
    INPUT_CRATES="crate-a crate-b" INPUT_VERSION="1.2.3" python3 publish.py
"""

import os
import re
import subprocess
import sys

ALREADY_PUBLISHED_PATTERN = re.compile(
    r"already uploaded|already exists",
    re.IGNORECASE,
)


def is_already_published(output: str) -> bool:
    """Return True if cargo publish output indicates the crate was already published."""
    return bool(ALREADY_PUBLISHED_PATTERN.search(output))


def build_manifest_args(manifest_path: str) -> list[str]:
    """Return --manifest-path flag list, or empty list if manifest_path is blank."""
    if not manifest_path:
        return []
    return ["--manifest-path", manifest_path]


def parse_crate_list(crates: str) -> list[str]:
    """Split a whitespace-separated crate list into individual names."""
    return crates.split()


def _run(cmd: list[str]) -> tuple[int, str]:
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return result.returncode, result.stdout + result.stderr


def main() -> None:
    crates_input = os.environ.get("INPUT_CRATES", "")
    version = os.environ.get("INPUT_VERSION", "")
    dry_run = os.environ.get("INPUT_DRY_RUN", "false").lower() == "true"
    manifest_path = os.environ.get("INPUT_MANIFEST_PATH", "")

    if not crates_input:
        print("Error: INPUT_CRATES is required", file=sys.stderr)
        sys.exit(1)
    if not version:
        print("Error: INPUT_VERSION is required", file=sys.stderr)
        sys.exit(1)

    crate_list = parse_crate_list(crates_input)
    manifest_args = build_manifest_args(manifest_path)
    total = len(crate_list)

    for index, crate in enumerate(crate_list, start=1):
        print(f"Publishing {crate} ({index}/{total})...")

        if dry_run:
            print(f"  [dry-run] cargo publish -p {crate} --dry-run")
            _run(["cargo", "publish", "-p", crate, *manifest_args, "--dry-run"])
            continue

        exit_code, output = _run(["cargo", "publish", "-p", crate, *manifest_args])

        if exit_code == 0:
            print(f"  Published {crate}@{version}")
        elif is_already_published(output):
            print(f"  {crate}@{version} already published, skipping")
        else:
            print(f"  Error publishing {crate}:", file=sys.stderr)
            print(output, file=sys.stderr)
            sys.exit(1)

    print("All crates published successfully")


if __name__ == "__main__":
    main()
