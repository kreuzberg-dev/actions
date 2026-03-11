#!/usr/bin/env bash
set -euo pipefail

packages_dir="${INPUT_PACKAGES_DIR:?INPUT_PACKAGES_DIR is required}"
source_url="${INPUT_SOURCE:-https://api.nuget.org/v3/index.json}"
dry_run="${INPUT_DRY_RUN:-false}"

if [[ ! -d "$packages_dir" ]]; then
  echo "Error: packages directory not found: $packages_dir" >&2
  exit 1
fi

shopt -s nullglob
nupkg_files=("$packages_dir"/*.nupkg)
shopt -u nullglob

if [[ ${#nupkg_files[@]} -eq 0 ]]; then
  echo "Error: no .nupkg files found in $packages_dir" >&2
  exit 1
fi

echo "Publishing ${#nupkg_files[@]} NuGet package(s)..."

failed=0
published=0

for nupkg in "${nupkg_files[@]}"; do
  name=$(basename "$nupkg")
  echo "Publishing ${name}..."

  if [[ "$dry_run" == "true" ]]; then
    echo "  [dry-run] dotnet nuget push ${name}"
    published=$((published + 1))
    continue
  fi

  set +e
  output=$(dotnet nuget push "$nupkg" \
    --api-key "$NUGET_API_KEY" \
    --source "$source_url" \
    --skip-duplicate 2>&1)
  exit_code=$?
  set -e

  if [[ $exit_code -eq 0 ]]; then
    echo "  Published ${name}"
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
