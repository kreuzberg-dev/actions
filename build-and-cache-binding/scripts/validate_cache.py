#!/usr/bin/env python3
# Validate cached artifacts to ensure they're not corrupted
#
# Usage:
#   validate_cache.py <artifact-type> <path...>
#
import shutil
import subprocess
import sys
from pathlib import Path

WASM_MAGIC = b"\x00asm"
FFI_EXTENSIONS = frozenset({".so", ".dylib", ".dll", ".a", ".lib"})
FFI_FILE_PATTERNS = ("shared object", "shared library", "Mach-O", "DLL", "current ar archive")


def check_wasm_magic(path: Path) -> bool:
    with path.open("rb") as fh:
        return fh.read(4) == WASM_MAGIC


def check_ffi_file_command(path: Path) -> bool:
    if shutil.which("file") is None:
        return True
    result = subprocess.run(["file", str(path)], capture_output=True, text=True, check=False)
    output = result.stdout
    return any(pattern in output for pattern in FFI_FILE_PATTERNS)


def validate_wasm_dir(directory: Path) -> tuple[int, int, int]:
    valid = invalid = missing = 0
    wasm_files = list(directory.rglob("*.wasm"))
    if not wasm_files:
        print(f"Warning: No WASM files found in directory: {directory}", file=sys.stderr)
        missing += 1
        return valid, invalid, missing
    for artifact in wasm_files:
        if artifact.stat().st_size == 0:
            print(f"Warning: Empty file: {artifact}", file=sys.stderr)
            invalid += 1
        elif check_wasm_magic(artifact):
            valid += 1
        else:
            print(f"Warning: Invalid WASM format: {artifact}", file=sys.stderr)
            invalid += 1
    return valid, invalid, missing


def validate_ffi_dir(directory: Path) -> tuple[int, int, int]:
    valid = invalid = missing = 0
    ffi_files = [f for f in directory.rglob("*") if f.is_file() and f.suffix in FFI_EXTENSIONS]
    if not ffi_files:
        print(f"Warning: No FFI library files found in directory: {directory}", file=sys.stderr)
        missing += 1
        return valid, invalid, missing
    for artifact in ffi_files:
        if artifact.stat().st_size == 0:
            invalid += 1
        elif check_ffi_file_command(artifact):
            valid += 1
        else:
            invalid += 1
    return valid, invalid, missing


def validate_path(artifact_type: str, raw_path: str) -> tuple[int, int, int]:
    path = Path(raw_path)

    if path.is_dir():
        if artifact_type == "wasm":
            return validate_wasm_dir(path)
        if artifact_type == "ffi":
            return validate_ffi_dir(path)
        print(f"Directory exists: {path}")
        return 1, 0, 0

    if not path.exists():
        return 0, 0, 1
    if path.stat().st_size == 0:
        return 0, 1, 0
    return 1, 0, 0


def main() -> int:
    if len(sys.argv) < 3:
        print(f"Error: Usage: {sys.argv[0]} <artifact-type> <path...>", file=sys.stderr)
        return 1

    artifact_type = sys.argv[1]
    paths = sys.argv[2:]

    print(f"Validating {artifact_type} artifacts...")

    total_valid = total_invalid = total_missing = 0

    for raw_path in paths:
        valid, invalid, missing = validate_path(artifact_type, raw_path)
        total_valid += valid
        total_invalid += invalid
        total_missing += missing

    print("=== Validation Summary ===")
    print(f"Valid: {total_valid}, Invalid: {total_invalid}, Missing: {total_missing}")

    if total_invalid > 0:
        print(f"Error: Validation failed: {total_invalid} invalid artifacts found", file=sys.stderr)
        return 1

    if total_valid == 0:
        print("Error: Validation failed: no valid artifacts found", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
