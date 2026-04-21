#!/usr/bin/env python3
"""Generate RustlerPrecompiled checksum files for Elixir NIF binaries.

Usage (GitHub Actions via env vars):
    INPUT_GITHUB_REPO=org/repo \
    INPUT_TAG=v1.2.3 \
    INPUT_VERSION=1.2.3 \
    INPUT_LIB_NAME=mylib \
    INPUT_NIF_VERSIONS=2.16,2.17 \
    INPUT_TARGETS=x86_64-unknown-linux-gnu,aarch64-unknown-linux-gnu \
    INPUT_OUTPUT_PATH=checksum-mylib.exs \
    python3 generate.py
"""

import hashlib
import os
import sys
import urllib.request
from pathlib import Path


def build_nif_artifact_name(lib_name: str, version: str, nif_version: str, target: str) -> str:
    """Return the NIF artifact filename for a given target triple.

    Uses platform-specific shared library extensions:
    - linux targets  → .so.tar.gz
    - darwin targets → .dylib.tar.gz
    - windows targets → .dll.tar.gz
    """
    if "linux" in target:
        ext = "so.tar.gz"
    elif "darwin" in target or "apple" in target:
        ext = "dylib.tar.gz"
    else:
        ext = "dll.tar.gz"

    return f"lib{lib_name}-v{version}-nif-{nif_version}-{target}.{ext}"


def build_download_url(github_repo: str, tag: str, filename: str) -> str:
    """Return the GitHub release asset download URL."""
    return f"https://github.com/{github_repo}/releases/download/{tag}/{filename}"


def compute_sha256_hex(data: bytes) -> str:
    """Return the SHA256 hex digest of data."""
    return hashlib.sha256(data).hexdigest()


def format_checksum_file(checksums: dict[str, str]) -> str:
    """Format checksums as an Elixir map literal for RustlerPrecompiled.

    Each entry is formatted as:
        "filename" => "sha256:hexdigest",

    Entries are sorted by key for deterministic output.
    """
    lines = ["%{"]
    for filename in sorted(checksums):
        digest = checksums[filename]
        lines.append(f'  "{filename}" => "sha256:{digest}",')
    lines.append("}")
    return "\n".join(lines) + "\n"


def main() -> None:
    github_repo = os.environ.get("INPUT_GITHUB_REPO", "")
    tag = os.environ.get("INPUT_TAG", "")
    version = os.environ.get("INPUT_VERSION", "")
    lib_name = os.environ.get("INPUT_LIB_NAME", "")
    nif_versions_raw = os.environ.get("INPUT_NIF_VERSIONS", "2.16,2.17")
    targets_raw = os.environ.get("INPUT_TARGETS", "")
    output_path = Path(os.environ.get("INPUT_OUTPUT_PATH", ""))

    for name, value in [
        ("INPUT_GITHUB_REPO", github_repo),
        ("INPUT_TAG", tag),
        ("INPUT_VERSION", version),
        ("INPUT_LIB_NAME", lib_name),
        ("INPUT_TARGETS", targets_raw),
        ("INPUT_OUTPUT_PATH", str(output_path)),
    ]:
        if not value:
            print(f"Error: {name} is required", file=sys.stderr)
            sys.exit(1)

    nif_versions = [v.strip() for v in nif_versions_raw.split(",") if v.strip()]
    targets = [t.strip() for t in targets_raw.split(",") if t.strip()]

    checksums: dict[str, str] = {}

    for nif_version in nif_versions:
        for target in targets:
            filename = build_nif_artifact_name(lib_name, version, nif_version, target)
            url = build_download_url(github_repo, tag, filename)

            print(f"Downloading {filename}...")
            try:
                with urllib.request.urlopen(url) as response:  # noqa: S310
                    data = response.read()
            except Exception as exc:
                print(f"Error downloading {url}: {exc}", file=sys.stderr)
                sys.exit(1)

            digest = compute_sha256_hex(data)
            checksums[filename] = digest
            print(f"  sha256: {digest}")

    content = format_checksum_file(checksums)
    output_path.write_text(content, encoding="utf-8")
    print(f"Wrote checksum file: {output_path}")

    github_output = os.environ.get("GITHUB_OUTPUT", "")
    if github_output:
        with Path(github_output).open("a") as fh:
            fh.write(f"checksum-file={output_path}\n")


if __name__ == "__main__":
    main()
