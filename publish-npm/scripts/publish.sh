#!/usr/bin/env bash
set -euo pipefail

packages_dir="${INPUT_PACKAGES_DIR:-}"
package_dir="${INPUT_PACKAGE_DIR:-}"
npm_tag="${INPUT_NPM_TAG:-latest}"
access="${INPUT_ACCESS:-public}"
provenance="${INPUT_PROVENANCE:-true}"
dry_run="${INPUT_DRY_RUN:-false}"

# Validate inputs: exactly one of packages-dir or package-dir must be set
if [[ -n "$packages_dir" && -n "$package_dir" ]]; then
  echo "Error: packages-dir and package-dir are mutually exclusive" >&2
  exit 1
fi

if [[ -z "$packages_dir" && -z "$package_dir" ]]; then
  echo "Error: either packages-dir or package-dir must be provided" >&2
  exit 1
fi

publish_flags=(--access "$access" --tag "$npm_tag" --ignore-scripts)
if [[ "$provenance" == "true" ]]; then
  publish_flags+=(--provenance)
fi
if [[ "$dry_run" == "true" ]]; then
  publish_flags+=(--dry-run)
fi

# --- Mode 1: Publish from a package directory directly ---

if [[ -n "$package_dir" ]]; then
  if [[ ! -d "$package_dir" ]]; then
    echo "Error: package directory not found: $package_dir" >&2
    exit 1
  fi

  echo "Publishing from directory: $package_dir"

  # Change to package directory before publishing.
  # This ensures npm's provenance attestation derives git info from the correct repository.
  # Without this, npm's git commands run from the repo root, which may give incorrect remote info
  # for monorepo subdirectories (e.g., deriving a wrong git URL for the package).
  pushd "$package_dir" >/dev/null

  set +e
  output=$(npm publish . "${publish_flags[@]}" 2>&1)
  exit_code=$?
  set -e

  popd >/dev/null

  if [[ $exit_code -eq 0 ]]; then
    echo "Published successfully"
  elif echo "$output" | grep -qi "previously published\|cannot publish over\|already exists"; then
    echo "Package already published, skipping"
  else
    echo "Error publishing:" >&2
    echo "$output" >&2
    exit 1
  fi

  exit 0
fi

# --- Mode 2: Publish .tgz files from a directory ---

if [[ ! -d "$packages_dir" ]]; then
  echo "Error: packages directory not found: $packages_dir" >&2
  exit 1
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
