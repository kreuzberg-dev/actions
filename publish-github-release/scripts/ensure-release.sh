#!/usr/bin/env bash
set -euo pipefail

tag="${INPUT_TAG:?INPUT_TAG is required}"
title="${INPUT_TITLE:-$tag}"
generate_notes="${INPUT_GENERATE_NOTES:-true}"
draft="${INPUT_DRAFT:-false}"
prerelease="${INPUT_PRERELEASE:-false}"
dry_run="${INPUT_DRY_RUN:-false}"

if [[ -z "$title" ]]; then
  title="$tag"
fi

if [[ "$dry_run" == "true" ]]; then
  echo "[dry-run] Would create/ensure release for tag: ${tag}"
  echo "  Title: ${title}"
  echo "  Generate notes: ${generate_notes}"
  echo "  Draft: ${draft}"
  echo "  Pre-release: ${prerelease}"
  exit 0
fi

# Check if release already exists
set +e
existing=$(gh release view "$tag" --json isDraft,tagName 2>/dev/null)
exists=$?
set -e

if [[ $exists -eq 0 ]]; then
  echo "Release ${tag} already exists"

  # Publish draft releases
  is_draft=$(echo "$existing" | python3 -c "import sys,json; print(json.load(sys.stdin).get('isDraft', False))" 2>/dev/null || echo "False")

  if [[ "$is_draft" == "True" && "$draft" != "true" ]]; then
    echo "Publishing draft release ${tag}..."
    gh release edit "$tag" --draft=false
  fi
else
  echo "Creating release ${tag}..."

  create_flags=(--title "$title")

  if [[ "$generate_notes" == "true" ]]; then
    create_flags+=(--generate-notes)
  fi

  if [[ "$draft" == "true" ]]; then
    create_flags+=(--draft)
  fi

  if [[ "$prerelease" == "true" ]]; then
    create_flags+=(--prerelease)
  fi

  gh release create "$tag" "${create_flags[@]}"
fi

echo "Release ${tag} ready"
