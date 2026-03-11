#!/usr/bin/env bash
# Compute deterministic hash for cache key generation
#
# Usage:
#   compute-hash.sh <glob-pattern> [glob-pattern...]
#   compute-hash.sh --files <file1> <file2> ...
#   compute-hash.sh --dirs <dir1> <dir2> ...

set -euo pipefail

if command -v sha256sum &>/dev/null; then
  HASH_CMD="sha256sum"
elif command -v shasum &>/dev/null; then
  HASH_CMD="shasum -a 256"
else
  echo "Error: Neither sha256sum nor shasum found in PATH" >&2
  exit 1
fi

MODE="glob"
if [[ "${1:-}" == "--files" ]]; then
  MODE="files"
  shift
elif [[ "${1:-}" == "--dirs" ]]; then
  MODE="dirs"
  shift
fi

if [[ $# -eq 0 ]]; then
  echo "Error: No input provided. Usage: $0 <pattern...> or $0 --files <file...> or $0 --dirs <dir...>" >&2
  exit 1
fi

TEMP_HASHES=$(mktemp)
trap 'rm -f "$TEMP_HASHES"' EXIT

case "$MODE" in
files)
  for file in "$@"; do
    if [[ -f "$file" ]]; then
      $HASH_CMD "$file" >>"$TEMP_HASHES" 2>/dev/null || echo "Warning: Failed to hash: $file" >&2
    else
      echo "Warning: File not found: $file" >&2
    fi
  done
  ;;

dirs)
  for dir in "$@"; do
    if [[ -d "$dir" ]]; then
      find "$dir" -type f \
        ! -path "*/.*" \
        ! -path "*/target/*" \
        ! -path "*/node_modules/*" \
        ! -path "*/.venv/*" \
        ! -path "*/dist/*" \
        ! -path "*/build/*" \
        -exec "$HASH_CMD" {} \; >>"$TEMP_HASHES" 2>/dev/null || true
    else
      echo "Warning: Directory not found: $dir" >&2
    fi
  done
  ;;

glob)
  for pattern in "$@"; do
    if [[ "$pattern" == *"**"* ]]; then
      base_dir=$(echo "$pattern" | cut -d'*' -f1 | sed 's|/$||')
      suffix="${pattern#*\*\*/}"
      if [[ "$suffix" == /* ]]; then
        name_pattern="${suffix#/}"
      else
        name_pattern="$suffix"
      fi

      if [[ -d "$base_dir" ]]; then
        find "$base_dir" -type f \
          ! -path "*/.*" \
          ! -path "*/target/*" \
          ! -path "*/node_modules/*" \
          ! -path "*/.venv/*" \
          -name "$name_pattern" \
          -exec "$HASH_CMD" {} \; 2>/dev/null >>"$TEMP_HASHES" || true
      else
        echo "Warning: Directory not found: $base_dir" >&2
      fi
    else
      for file in $pattern; do
        if [[ -f "$file" ]]; then
          $HASH_CMD "$file" >>"$TEMP_HASHES" 2>/dev/null || echo "Warning: Failed to hash: $file" >&2
        fi
      done
    fi
  done
  ;;
esac

if [[ ! -s "$TEMP_HASHES" ]]; then
  echo "Error: No files found matching the provided patterns" >&2
  exit 1
fi

FINAL_HASH=$(sort "$TEMP_HASHES" | $HASH_CMD | cut -d' ' -f1)
SHORT_HASH="${FINAL_HASH:0:12}"
echo "$SHORT_HASH"

FILE_COUNT=$(wc -l <"$TEMP_HASHES")
echo "Hashed $FILE_COUNT files -> $SHORT_HASH" >&2
