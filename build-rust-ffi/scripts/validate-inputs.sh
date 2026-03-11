#!/usr/bin/env bash
set -euo pipefail

crate_name="${CRATE_NAME:?CRATE_NAME required}"
manifest_path="${MANIFEST_PATH:-}"

echo "=== Validating FFI build inputs ==="
echo "Crate: ${crate_name}"

if [ -n "$manifest_path" ]; then
  if [ ! -f "$manifest_path" ]; then
    echo "Error: manifest-path '${manifest_path}' does not exist" >&2
    exit 1
  fi
  echo "Manifest: ${manifest_path}"
elif [ -f "crates/${crate_name}/Cargo.toml" ]; then
  echo "Found crate at crates/${crate_name}/"
else
  echo "Error: Crate '${crate_name}' not found at crates/${crate_name}/Cargo.toml" >&2
  echo "Hint: Use manifest-path input for non-standard crate locations" >&2
  exit 1
fi

echo "Validation passed"
