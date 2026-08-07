#!/usr/bin/env bash
# ~keep INCLUDE_PATTERNS arrives via env, not a positional arg, so it stays out of run:
# interpolation in action.yml (untrusted-shaped workflow input).
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${script_dir}/lib.sh"

manifest_path="$1"

manifest_hash="$(sha256_of "$manifest_path")"

normalized_patterns_file="$(mktemp)"
trap 'rm -f "$normalized_patterns_file"' EXIT

printf '%s\n' "${INCLUDE_PATTERNS:-**}" |
	sed 's/[[:space:]]*$//; s/^[[:space:]]*//' |
	grep -v '^$' |
	sort >"$normalized_patterns_file"

# An empty/all-blank input still needs a stable key, so fall back to the "**" default explicitly.
if [[ ! -s "$normalized_patterns_file" ]]; then
	printf '**\n' >"$normalized_patterns_file"
fi

include_hash="$(sha256_of "$normalized_patterns_file")"

echo "key=fetch-test-documents-v1-${manifest_hash}-${include_hash}" >>"$GITHUB_OUTPUT"
