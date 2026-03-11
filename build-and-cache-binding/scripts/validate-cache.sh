#!/usr/bin/env bash
# Validate cached artifacts to ensure they're not corrupted
#
# Usage:
#   validate-cache.sh <artifact-type> <path...>

set -euo pipefail

get_file_size() {
  local file="$1"
  if stat -f%z "$file" 2>/dev/null; then
    return 0
  fi
  if stat -c%s "$file" 2>/dev/null; then
    return 0
  fi
  if command -v wc &>/dev/null; then
    wc -c <"$file" 2>/dev/null
    return 0
  fi
  echo "0"
  return 0
}

check_wasm_magic() {
  local file="$1"
  if command -v xxd &>/dev/null && xxd -l 4 -p "$file" 2>/dev/null | grep -q "0061736d"; then
    return 0
  fi
  if command -v od &>/dev/null && od -A n -t x1 -N 4 "$file" 2>/dev/null | grep -q "00 61 73 6d"; then
    return 0
  fi
  if command -v file &>/dev/null && file "$file" 2>/dev/null | grep -q "WebAssembly"; then
    return 0
  fi
  return 1
}

if [[ $# -lt 2 ]]; then
  echo "Error: Usage: $0 <artifact-type> <path...>" >&2
  exit 1
fi

ARTIFACT_TYPE="$1"
shift

echo "Validating $ARTIFACT_TYPE artifacts..."

VALID_COUNT=0
INVALID_COUNT=0
MISSING_COUNT=0

for path in "$@"; do
  if [[ -d "$path" ]]; then
    case "$ARTIFACT_TYPE" in
    wasm)
      wasm_files=$(find "$path" -type f -name "*.wasm" 2>/dev/null || true)
      if [[ -z "$wasm_files" ]]; then
        echo "Warning: No WASM files found in directory: $path" >&2
        ((++MISSING_COUNT))
      else
        while IFS= read -r artifact; do
          [[ -z "$artifact" ]] && continue
          FILE_SIZE=$(get_file_size "$artifact")
          if [[ "$FILE_SIZE" -eq 0 ]]; then
            echo "Warning: Empty file: $artifact" >&2
            ((++INVALID_COUNT))
          elif check_wasm_magic "$artifact"; then
            ((++VALID_COUNT))
          else
            echo "Warning: Invalid WASM format: $artifact" >&2
            ((++INVALID_COUNT))
          fi
        done < <(echo "$wasm_files")
      fi
      ;;
    ffi)
      ffi_files=$(find "$path" -type f \( -name "*.so" -o -name "*.dylib" -o -name "*.dll" -o -name "*.a" -o -name "*.lib" \) 2>/dev/null || true)
      if [[ -z "$ffi_files" ]]; then
        echo "Warning: No FFI library files found in directory: $path" >&2
        ((++MISSING_COUNT))
      else
        while IFS= read -r artifact; do
          [[ -z "$artifact" ]] && continue
          FILE_SIZE=$(get_file_size "$artifact")
          if [[ "$FILE_SIZE" -eq 0 ]]; then
            ((++INVALID_COUNT))
          elif file "$artifact" 2>/dev/null | grep -qE "(shared object|shared library|Mach-O|DLL|current ar archive)"; then
            ((++VALID_COUNT))
          else
            ((++INVALID_COUNT))
          fi
        done < <(echo "$ffi_files")
      fi
      ;;
    *)
      echo "Directory exists: $path"
      ((++VALID_COUNT))
      ;;
    esac
    continue
  fi

  for artifact in $path; do
    if [[ ! -e "$artifact" ]]; then
      ((++MISSING_COUNT))
      continue
    fi
    FILE_SIZE=$(get_file_size "$artifact")
    if [[ "$FILE_SIZE" -eq 0 ]]; then
      ((++INVALID_COUNT))
      continue
    fi
    ((++VALID_COUNT))
  done
done

echo "=== Validation Summary ==="
echo "Valid: $VALID_COUNT, Invalid: $INVALID_COUNT, Missing: $MISSING_COUNT"

if [[ $INVALID_COUNT -gt 0 ]]; then
  echo "Error: Validation failed: $INVALID_COUNT invalid artifacts found" >&2
  exit 1
fi

if [[ $VALID_COUNT -eq 0 ]]; then
  echo "Error: Validation failed: no valid artifacts found" >&2
  exit 1
fi

exit 0
