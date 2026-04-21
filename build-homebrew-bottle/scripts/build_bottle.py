#!/usr/bin/env python3
"""Create a Homebrew bottle tarball from a CLI binary.

Usage (GitHub Actions via env vars):
    INPUT_BINARY_PATH=./target/release/mytool \
    INPUT_FORMULA_NAME=mytool \
    INPUT_VERSION=1.2.3 \
    INPUT_BOTTLE_TAG=arm64_sequoia \
    python3 build_bottle.py
"""

import hashlib
import os
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path


def build_bottle_dir_structure(binary_path: Path, formula_name: str, version: str, dest: Path) -> Path:
    """Create the Homebrew-style bottle directory structure and copy the binary.

    The layout is: dest/formula_name/version/bin/formula_name

    Returns:
        dest — the root of the bottle directory.

    Raises:
        SystemExit: If binary_path does not exist.
    """
    if not binary_path.exists():
        print(f"Error: binary not found: {binary_path}", file=sys.stderr)
        sys.exit(1)

    bin_dir = dest / formula_name / version / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)

    dest_binary = bin_dir / formula_name
    shutil.copy2(str(binary_path), str(dest_binary))
    dest_binary.chmod(binary_path.stat().st_mode)

    return dest


def create_bottle_tarball(bottle_root: Path, formula_name: str, version: str, bottle_tag: str) -> Path:
    """Create a .tar.gz bottle tarball from the bottle directory structure.

    The tarball is placed next to bottle_root with the naming convention:
    formula_name-version.bottle_tag.bottle.tar.gz

    Returns:
        Path to the created tarball.
    """
    filename = f"{formula_name}-{version}.{bottle_tag}.bottle.tar.gz"
    tarball_path = bottle_root.parent / filename

    with tarfile.open(str(tarball_path), "w:gz") as tar:
        tar.add(str(bottle_root), arcname=".")

    return tarball_path


def compute_bottle_sha256(path: Path) -> str:
    """Compute and return the SHA256 hex digest of a file."""
    sha256 = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def main() -> None:
    binary_path = Path(os.environ.get("INPUT_BINARY_PATH", ""))
    formula_name = os.environ.get("INPUT_FORMULA_NAME", "")
    version = os.environ.get("INPUT_VERSION", "")
    bottle_tag = os.environ.get("INPUT_BOTTLE_TAG", "")

    if not binary_path.parts:
        print("Error: INPUT_BINARY_PATH is required", file=sys.stderr)
        sys.exit(1)
    if not formula_name:
        print("Error: INPUT_FORMULA_NAME is required", file=sys.stderr)
        sys.exit(1)
    if not version:
        print("Error: INPUT_VERSION is required", file=sys.stderr)
        sys.exit(1)
    if not bottle_tag:
        print("Error: INPUT_BOTTLE_TAG is required", file=sys.stderr)
        sys.exit(1)

    workspace = Path(os.environ.get("GITHUB_WORKSPACE", "."))

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        bottle_root = build_bottle_dir_structure(binary_path, formula_name, version, tmp_path / "bottle")
        tarball_path = create_bottle_tarball(bottle_root, formula_name, version, bottle_tag)
        sha256 = compute_bottle_sha256(tarball_path)

        dest = workspace / tarball_path.name
        shutil.copy2(str(tarball_path), str(dest))

    print(f"Bottle: {dest.name}")
    print(f"SHA256: {sha256}")

    github_output = os.environ.get("GITHUB_OUTPUT", "")
    if github_output:
        with Path(github_output).open("a") as fh:
            fh.write(f"filename={dest.name}\n")
            fh.write(f"sha256={sha256}\n")
            fh.write(f"path={dest}\n")


if __name__ == "__main__":
    main()
