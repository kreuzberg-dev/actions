#!/usr/bin/env python3
"""Compute deterministic hash for cache key generation.

Usage:
  compute_hash.py <glob-pattern> [glob-pattern...]
  compute_hash.py --files <file1> <file2> ...
  compute_hash.py --dirs <dir1> <dir2> ...
"""

import argparse
import hashlib
import sys
from pathlib import Path

EXCLUDED_DIRS: frozenset[str] = frozenset({"target", "node_modules", ".venv", "dist", "build"})


def hash_file(path: Path) -> str | None:
    """Return the sha256 hex digest of a file, or None on read error."""
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as err:
        print(f"Warning: Failed to hash: {path}: {err}", file=sys.stderr)
        return None
    else:
        return f"{digest}  {path}"


def is_excluded(path: Path) -> bool:
    """Return True if any component of path is a hidden dir or excluded dir."""
    for part in path.parts:
        if part.startswith(".") and part not in (".", ".."):
            return True
        if part in EXCLUDED_DIRS:
            return True
    return False


def collect_files_mode(paths: list[str]) -> list[str]:
    """Collect hashes for an explicit list of files."""
    hashes: list[str] = []
    for raw in paths:
        path = Path(raw)
        if path.is_file():
            entry = hash_file(path)
            if entry is not None:
                hashes.append(entry)
        else:
            print(f"Warning: File not found: {raw}", file=sys.stderr)
    return hashes


def collect_dirs_mode(dirs: list[str]) -> list[str]:
    """Collect hashes for all non-excluded files under each directory."""
    hashes: list[str] = []
    for raw in dirs:
        directory = Path(raw)
        if not directory.is_dir():
            print(f"Warning: Directory not found: {raw}", file=sys.stderr)
            continue
        for candidate in sorted(directory.rglob("*")):
            if not candidate.is_file():
                continue
            # Check relative path components for exclusions (hidden dirs + excluded dirs)
            try:
                rel = candidate.relative_to(directory)
            except ValueError:
                continue
            if is_excluded(rel):
                continue
            entry = hash_file(candidate)
            if entry is not None:
                hashes.append(entry)
    return hashes


def _collect_simple_glob(pattern: str) -> list[str]:
    """Expand a simple (non-recursive) glob pattern relative to cwd."""
    hashes: list[str] = []
    for candidate in sorted(Path.cwd().glob(pattern)):
        if candidate.is_file():
            entry = hash_file(candidate)
            if entry is not None:
                hashes.append(entry)
    return hashes


def _collect_recursive_glob(pattern: str) -> list[str]:
    """Expand a recursive ``**`` glob pattern with exclusions."""
    hashes: list[str] = []
    double_star_idx = pattern.index("**")
    raw_base = pattern[:double_star_idx].rstrip("/")
    base_dir = Path(raw_base) if raw_base else Path.cwd()
    after_stars = pattern[double_star_idx + 2 :]  # skip "**"
    suffix = after_stars.lstrip("/") or "*"

    if not base_dir.is_dir():
        print(f"Warning: Directory not found: {base_dir}", file=sys.stderr)
        return hashes

    for candidate in sorted(base_dir.rglob(suffix)):
        if not candidate.is_file():
            continue
        try:
            rel = candidate.relative_to(base_dir)
        except ValueError:
            continue
        if is_excluded(rel):
            continue
        entry = hash_file(candidate)
        if entry is not None:
            hashes.append(entry)
    return hashes


def collect_glob_mode(patterns: list[str]) -> list[str]:
    """Collect hashes for files matched by glob patterns."""
    hashes: list[str] = []
    for pattern in patterns:
        if "**" in pattern:
            hashes.extend(_collect_recursive_glob(pattern))
        else:
            hashes.extend(_collect_simple_glob(pattern))
    return hashes


def compute_final_hash(entries: list[str]) -> str:
    """Sort hash entries and hash them together, returning the full hex digest."""
    combined = "\n".join(sorted(entries)) + "\n"
    return hashlib.sha256(combined.encode()).hexdigest()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compute deterministic hash for cache key generation.",
        add_help=True,
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--files",
        action="store_true",
        default=False,
        help="Treat positional arguments as explicit file paths.",
    )
    mode_group.add_argument(
        "--dirs",
        action="store_true",
        default=False,
        help="Treat positional arguments as directories to traverse.",
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        metavar="INPUT",
        help="Glob patterns, file paths, or directory paths depending on mode.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if not args.inputs:
        print(
            "Error: No input provided. Usage: compute_hash.py <pattern...> "
            "or compute_hash.py --files <file...> or compute_hash.py --dirs <dir...>",
            file=sys.stderr,
        )
        return 1

    if args.files:
        hashes = collect_files_mode(args.inputs)
    elif args.dirs:
        hashes = collect_dirs_mode(args.inputs)
    else:
        hashes = collect_glob_mode(args.inputs)

    if not hashes:
        print("Error: No files found matching the provided patterns", file=sys.stderr)
        return 1

    final_hash = compute_final_hash(hashes)
    short_hash = final_hash[:12]

    print(short_hash)
    print(f"Hashed {len(hashes)} files -> {short_hash}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
