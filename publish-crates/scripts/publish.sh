#!/usr/bin/env bash
set -euo pipefail

crates="${INPUT_CRATES:?INPUT_CRATES is required}"
version="${INPUT_VERSION:?INPUT_VERSION is required}"
dry_run="${INPUT_DRY_RUN:-false}"
manifest_path="${INPUT_MANIFEST_PATH:-}"

manifest_args=()
if [[ -n "$manifest_path" ]]; then
  manifest_args=(--manifest-path "$manifest_path")
fi

read -ra crate_list <<<"$crates"
total=${#crate_list[@]}

for i in "${!crate_list[@]}"; do
  crate="${crate_list[$i]}"
  echo "Publishing ${crate} ($((i + 1))/${total})..."

  if [[ "$dry_run" == "true" ]]; then
    echo "  [dry-run] cargo publish -p ${crate} --dry-run"
    cargo publish -p "$crate" "${manifest_args[@]}" --dry-run 2>&1 || true
    continue
  fi

  set +e
  output=$(cargo publish -p "$crate" "${manifest_args[@]}" 2>&1)
  exit_code=$?
  set -e

  if [[ $exit_code -eq 0 ]]; then
    echo "  Published ${crate}@${version}"
  elif echo "$output" | grep -qi "already uploaded\|already exists"; then
    echo "  ${crate}@${version} already published, skipping"
  else
    echo "  Error publishing ${crate}:" >&2
    echo "$output" >&2
    exit 1
  fi
done

echo "All crates published successfully"
