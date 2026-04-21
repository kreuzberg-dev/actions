#!/usr/bin/env python3
"""Publish npm packages from a directory or a .tgz file.

Usage (GitHub Actions via env vars):
    INPUT_PACKAGE_DIR=dist/ python3 publish.py
    INPUT_PACKAGES_DIR=dist/packages/ python3 publish.py
"""

import os
import re
import subprocess
import sys
from pathlib import Path

ALREADY_PUBLISHED_PATTERN = re.compile(
    r"previously published|cannot publish over|already exists",
    re.IGNORECASE,
)


def validate_inputs(packages_dir: str, package_dir: str) -> str:
    """Validate mutually exclusive inputs; return mode 'tgz' or 'dir'.

    Raises SystemExit on invalid combinations.
    """
    if packages_dir and package_dir:
        print("Error: packages-dir and package-dir are mutually exclusive", file=sys.stderr)
        sys.exit(1)
    if not packages_dir and not package_dir:
        print("Error: either packages-dir or package-dir must be provided", file=sys.stderr)
        sys.exit(1)
    return "tgz" if packages_dir else "dir"


def build_publish_flags(access: str, npm_tag: str, provenance: bool, dry_run: bool) -> list[str]:
    """Build the list of flags to pass to `npm publish`."""
    flags: list[str] = ["--access", access, "--tag", npm_tag, "--ignore-scripts"]
    if provenance:
        flags.append("--provenance")
    if dry_run:
        flags.append("--dry-run")
    return flags


def is_already_published(output: str) -> bool:
    """Return True if the npm output indicates the package was already published."""
    return bool(ALREADY_PUBLISHED_PATTERN.search(output))


def find_tgz_files(directory: Path) -> list[Path]:
    """Return all *.tgz files in directory (non-recursive)."""
    return sorted(directory.glob("*.tgz"))


def _run(cmd: list[str], cwd: Path | None = None) -> tuple[int, str]:
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, check=False)
    return result.returncode, result.stdout + result.stderr


def main() -> None:
    packages_dir = os.environ.get("INPUT_PACKAGES_DIR", "")
    package_dir = os.environ.get("INPUT_PACKAGE_DIR", "")
    npm_tag = os.environ.get("INPUT_NPM_TAG", "latest")
    access = os.environ.get("INPUT_ACCESS", "public")
    provenance = os.environ.get("INPUT_PROVENANCE", "true").lower() == "true"
    dry_run = os.environ.get("INPUT_DRY_RUN", "false").lower() == "true"

    mode = validate_inputs(packages_dir, package_dir)
    flags = build_publish_flags(access, npm_tag, provenance, dry_run)

    if mode == "dir":
        pkg_path = Path(package_dir)
        if not pkg_path.is_dir():
            print(f"Error: package directory not found: {package_dir}", file=sys.stderr)
            sys.exit(1)

        print(f"Publishing from directory: {package_dir}")
        exit_code, output = _run(["npm", "publish", ".", *flags], cwd=pkg_path)

        if exit_code == 0:
            print("Published successfully")
        elif is_already_published(output):
            print("Package already published, skipping")
        else:
            print("Error publishing:", file=sys.stderr)
            print(output, file=sys.stderr)
            sys.exit(1)
        return

    pkgs_path = Path(packages_dir)
    if not pkgs_path.is_dir():
        print(f"Error: packages directory not found: {packages_dir}", file=sys.stderr)
        sys.exit(1)

    tgz_files = find_tgz_files(pkgs_path)
    if not tgz_files:
        print(f"Error: no .tgz files found in {packages_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Publishing {len(tgz_files)} package(s) with tag '{npm_tag}'...")

    failed = 0
    published = 0

    for tgz in tgz_files:
        name = tgz.name
        print(f"Publishing {name}...")
        exit_code, output = _run(["npm", "publish", str(tgz), *flags])

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


if __name__ == "__main__":
    main()
