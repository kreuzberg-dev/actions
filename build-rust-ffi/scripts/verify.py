#!/usr/bin/env python3
"""Verify the built Rust FFI library artifact and display diagnostic information."""

import os
import subprocess
import sys
from pathlib import Path

_MIN_POSITIONAL_ARGS_FOR_TARGET = 2


def _resolve_paths() -> tuple[Path | None, Path | None]:
    """Resolve library path and target dir from environment or positional args."""
    env = os.environ
    library_path_str = env.get("LIBRARY_PATH", "")
    target_dir_str = env.get("TARGET_DIR", "")

    args = sys.argv[1:]
    if not library_path_str and len(args) >= 1:
        library_path_str = args[0]
    if not target_dir_str and len(args) >= _MIN_POSITIONAL_ARGS_FOR_TARGET:
        target_dir_str = args[1]

    library_path = Path(library_path_str) if library_path_str else None
    target_dir = Path(target_dir_str) if target_dir_str else None
    return library_path, target_dir


def _print_file_type(library_path: Path) -> None:
    """Run the `file` command on the library and print the result."""
    result = subprocess.run(
        ["file", str(library_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        print()
        print("File type:")
        print(result.stdout.rstrip())


def _print_exported_symbols(library_path: Path) -> None:
    """Run `nm -D` on the library and print the first 10 exported text symbols."""
    runner_os = os.environ.get("RUNNER_OS", "")
    if runner_os == "Windows":
        return

    result = subprocess.run(
        ["nm", "-D", str(library_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return

    exported = [
        line
        for line in result.stdout.splitlines()
        if len(line.split()) >= _MIN_POSITIONAL_ARGS_FOR_TARGET and line.split()[1] == "T"
    ]
    print()
    print("Exported symbols (first 10):")
    for symbol_line in exported[:10]:
        print(symbol_line)


def _list_target_dir(target_dir: Path | None) -> None:
    """Print the contents of target_dir, or a fallback message if absent."""
    print("Target directory contents:")
    if target_dir is not None and target_dir.is_dir():
        entries = sorted(target_dir.iterdir())
        for entry in entries:
            size_kb = entry.stat().st_size / 1024
            print(f"  {size_kb:8.1f}K  {entry.name}")
    else:
        print("Target directory does not exist")


def main() -> None:
    """Verify library existence, print file type, and show exported symbols."""
    library_path, target_dir = _resolve_paths()

    print("=== Verifying Build Artifacts ===")

    if library_path is not None and library_path.is_file():
        print(f"Library artifact verified: {library_path}")
        _print_file_type(library_path)
        _print_exported_symbols(library_path)
    else:
        print("Library artifact not found at expected path")
        _list_target_dir(target_dir)

    print()
    print("Artifact verification complete")


if __name__ == "__main__":
    main()
