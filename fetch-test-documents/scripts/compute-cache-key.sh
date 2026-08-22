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

# ~keep The include hash leads and the manifest hash trails so that "everything built for this
# same selection" is a stable key prefix. That prefix is what restore-keys falls back to: when
# corpus.lock.json changes, the previous run's object store is still restored and fetch.sh only
# downloads the objects that actually changed, instead of re-pulling the whole selection. Objects
# are content-addressed and immutable, and every one is re-verified against its sha256 before use,
# so reusing a stale store is always safe. Reversing this order silently reverts to a full
# re-download on every manifest bump.
prefix="fetch-test-documents-v1-${include_hash}-"

{
	echo "key=${prefix}${manifest_hash}"
	echo "restore-prefix=${prefix}"
} >>"$GITHUB_OUTPUT"
