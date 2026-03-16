#!/usr/bin/env bash
set -euo pipefail

tag="${INPUT_TAG:?INPUT_TAG is required}"
artifacts="${INPUT_ARTIFACTS:?INPUT_ARTIFACTS is required}"

# Normalize comma-separated patterns to newline-separated
artifacts="${artifacts//,/$'\n'}"

# Collect files from newline-separated patterns
files=()
while IFS= read -r pattern; do
  pattern=$(echo "$pattern" | xargs)
  if [[ -z "$pattern" ]]; then
    continue
  fi

  shopt -s nullglob
  # shellcheck disable=SC2086,SC2206
  expanded=($pattern)
  shopt -u nullglob

  for f in "${expanded[@]}"; do
    if [[ -f "$f" ]]; then
      files+=("$f")
    fi
  done
done <<<"$artifacts"

if [[ ${#files[@]} -eq 0 ]]; then
  echo "No artifact files matched, skipping upload"
  exit 0
fi

echo "Uploading ${#files[@]} artifact(s) to release ${tag}..."

for file in "${files[@]}"; do
  name=$(basename "$file")
  echo "  Uploading ${name}..."
  gh release upload "$tag" "$file" --clobber
done

echo "All artifacts uploaded"
