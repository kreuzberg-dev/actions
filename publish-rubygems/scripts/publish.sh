#!/usr/bin/env bash
set -euo pipefail

gems_dir="${INPUT_GEMS_DIR:?INPUT_GEMS_DIR is required}"
dry_run="${INPUT_DRY_RUN:-false}"

if [[ ! -d "$gems_dir" ]]; then
  echo "Error: gems directory not found: $gems_dir" >&2
  exit 1
fi

shopt -s nullglob
gem_files=("$gems_dir"/*.gem)
shopt -u nullglob

if [[ ${#gem_files[@]} -eq 0 ]]; then
  echo "Error: no .gem files found in $gems_dir" >&2
  exit 1
fi

failed=0
published=0

echo "Publishing ${#gem_files[@]} gem(s)..."

for gem_file in "${gem_files[@]}"; do
  name=$(basename "$gem_file")

  # Validate gem file
  if [[ ! -r "$gem_file" ]] || [[ ! -s "$gem_file" ]]; then
    echo "  Error: ${name} is missing, unreadable, or empty" >&2
    failed=$((failed + 1))
    continue
  fi

  # Validate gem structure
  if ! gem spec "$gem_file" >/dev/null 2>&1; then
    echo "  Error: ${name} has invalid gem structure" >&2
    failed=$((failed + 1))
    continue
  fi

  echo "Publishing ${name}..."

  if [[ "$dry_run" == "true" ]]; then
    echo "  [dry-run] gem push ${name}"
    published=$((published + 1))
    continue
  fi

  set +e
  output=$(gem push "$gem_file" 2>&1)
  exit_code=$?
  set -e

  if [[ $exit_code -eq 0 ]]; then
    echo "  Published ${name}"
    published=$((published + 1))
  elif echo "$output" | grep -qi "repushing.*not allowed\|already been pushed"; then
    echo "  ${name} already published, skipping"
    published=$((published + 1))
  else
    echo "  Error publishing ${name}:" >&2
    echo "$output" >&2
    failed=$((failed + 1))
  fi
done

echo "Published: ${published}, Failed: ${failed}"

if [[ $failed -gt 0 ]]; then
  exit 1
fi

# Write summary if available
if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  {
    echo "### RubyGems Publish"
    echo "- Published: ${published}"
    echo "- Failed: ${failed}"
  } >>"$GITHUB_STEP_SUMMARY"
fi
