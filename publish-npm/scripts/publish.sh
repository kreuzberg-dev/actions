#!/usr/bin/env bash
set -euo pipefail

packages_dir="${INPUT_PACKAGES_DIR:?INPUT_PACKAGES_DIR is required}"
npm_tag="${INPUT_NPM_TAG:-latest}"
access="${INPUT_ACCESS:-public}"
provenance="${INPUT_PROVENANCE:-true}"
dry_run="${INPUT_DRY_RUN:-false}"

if [[ ! -d "$packages_dir" ]]; then
  echo "Error: packages directory not found: $packages_dir" >&2
  exit 1
fi

publish_flags=(--access "$access" --tag "$npm_tag" --ignore-scripts)
if [[ "$provenance" == "true" ]]; then
  publish_flags+=(--provenance)
fi
if [[ "$dry_run" == "true" ]]; then
  publish_flags+=(--dry-run)
fi

failed=0
published=0

shopt -s nullglob
tgz_files=("$packages_dir"/*.tgz)
shopt -u nullglob

if [[ ${#tgz_files[@]} -eq 0 ]]; then
  echo "Error: no .tgz files found in $packages_dir" >&2
  exit 1
fi

echo "Publishing ${#tgz_files[@]} package(s) with tag '${npm_tag}'..."

for tgz in "${tgz_files[@]}"; do
  name=$(basename "$tgz")
  echo "Publishing ${name}..."

  set +e
  output=$(npm publish "$tgz" "${publish_flags[@]}" 2>&1)
  exit_code=$?
  set -e

  if [[ $exit_code -eq 0 ]]; then
    echo "  Published ${name}"
    published=$((published + 1))
  elif echo "$output" | grep -qi "previously published\|cannot publish over\|already exists"; then
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
