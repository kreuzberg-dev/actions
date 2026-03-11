#!/usr/bin/env bash
set -euo pipefail

library_path="${LIBRARY_PATH:-${1:-}}"
target_dir="${TARGET_DIR:-${2:-}}"

echo "=== Verifying Build Artifacts ==="

if [ -n "$library_path" ] && [ -f "$library_path" ]; then
  echo "Library artifact verified: $library_path"

  if command -v file &>/dev/null; then
    echo ""
    echo "File type:"
    file "$library_path"
  fi

  if [[ "${RUNNER_OS:-}" != "Windows" ]] && command -v nm &>/dev/null; then
    echo ""
    echo "Exported symbols (first 10):"
    nm -D "$library_path" 2>/dev/null | grep -E "^[0-9a-f]+ T " | head -10 || true
  fi
else
  echo "Library artifact not found at expected path"
  echo "Target directory contents:"
  ls -lh "${target_dir}/" 2>/dev/null || echo "Target directory does not exist"
fi

echo ""
echo "Artifact verification complete"
