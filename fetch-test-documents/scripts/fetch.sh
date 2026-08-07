#!/usr/bin/env bash
# Selects manifest entries matching the include patterns, dedupes them by sha256, downloads each
# unique object in parallel, verifies every download's sha256, and writes it to every path that
# references it. Safe to run twice: already-cached, hash-verified objects are neither
# re-downloaded nor re-flagged as fetched.
#
# Args: $1 = path to corpus.lock.json, $2 = target directory (the test_documents checkout)
# Env:  INCLUDE_PATTERNS, BUCKET, CONCURRENCY, CACHE_DIR, GITHUB_OUTPUT
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${script_dir}/lib.sh"

manifest_path="$1"
target_path="$2"

bucket="${BUCKET:?BUCKET is required}"
concurrency="${CONCURRENCY:-8}"
cache_dir="${CACHE_DIR:?CACHE_DIR is required}"

if ! [[ "$concurrency" =~ ^[0-9]+$ ]] || [[ "$concurrency" -lt 1 ]]; then
	echo "::error::concurrency must be a positive integer, got '${concurrency}'" >&2
	exit 1
fi

mkdir -p "${cache_dir}/objects"

work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT

patterns_file="${work_dir}/patterns"
printf '%s\n' "${INCLUDE_PATTERNS:-**}" |
	sed 's/[[:space:]]*$//; s/^[[:space:]]*//' |
	grep -v '^$' >"$patterns_file"
if [[ ! -s "$patterns_file" ]]; then
	printf '**\n' >"$patterns_file"
fi

all_entries="${work_dir}/all-entries.tsv"
jq -r '.objects | to_entries[] | "\(.key)\t\(.value.sha256)\t\(.value.size)"' "$manifest_path" >"$all_entries"

# Matched entries = manifest paths matched against every include pattern. `[[ path == pattern ]]`
# is plain string globbing (no filesystem traversal), so "**" and "*" both match across "/"
# already — no globstar shell option needed. ~keep
matched_entries="${work_dir}/matched-entries.tsv"
: >"$matched_entries"
while IFS=$'\t' read -r path sha size; do
	while IFS= read -r pattern; do
		# shellcheck disable=SC2053 # intentional glob match against $pattern, not literal compare
		if [[ "$path" == $pattern ]]; then
			printf '%s\t%s\t%s\n' "$path" "$sha" "$size" >>"$matched_entries"
			break
		fi
	done <"$patterns_file"
done <"$all_entries"

unique_shas="${work_dir}/unique-shas"
cut -f2 "$matched_entries" | sort -u >"$unique_shas"

to_download="${work_dir}/to-download"
: >"$to_download"
while IFS= read -r sha; do
	[[ -z "$sha" ]] && continue
	dest="${cache_dir}/objects/${sha}"
	if [[ -f "$dest" ]] && [[ "$(sha256_of "$dest")" == "$sha" ]]; then
		continue
	fi
	echo "$sha" >>"$to_download"
done <"$unique_shas"

if [[ -s "$to_download" ]]; then
	echo "Downloading $(wc -l <"$to_download" | tr -d ' ') object(s) with concurrency ${concurrency}..."
	xargs -P "$concurrency" -I{} "${script_dir}/download-object.sh" {} "$bucket" "$cache_dir" <"$to_download"
else
	echo "All selected objects already cached and verified; nothing to download."
fi

# Materialise every matched path from the (now fully populated) object store, re-verifying each
# object's hash on the way out so a corrupted cache entry fails loudly instead of silently.
while IFS=$'\t' read -r path sha size; do
	src="${cache_dir}/objects/${sha}"
	actual="$(sha256_of "$src")"
	if [[ "$actual" != "$sha" ]]; then
		echo "::error::checksum mismatch for cached object required by '${path}': expected ${sha}, got ${actual}" >&2
		exit 1
	fi
	dest="${target_path}/${path}"
	mkdir -p "$(dirname "$dest")"
	cp "$src" "$dest"
done <"$matched_entries"

matched_count="$(wc -l <"$matched_entries" | tr -d ' ')"
unique_count="$(wc -l <"$unique_shas" | tr -d ' ')"
objects_fetched="$(wc -l <"$to_download" | tr -d ' ')"

bytes_fetched=0
while IFS= read -r sha; do
	[[ -z "$sha" ]] && continue
	size="$(awk -F'\t' -v s="$sha" '$2==s{print $3; exit}' "$matched_entries")"
	bytes_fetched=$((bytes_fetched + size))
done <"$to_download"

echo "Matched ${matched_count} path(s) across ${unique_count} unique object(s); downloaded ${objects_fetched} object(s), ${bytes_fetched} byte(s)."

{
	echo "objects-fetched=${objects_fetched}"
	echo "bytes-fetched=${bytes_fetched}"
} >>"$GITHUB_OUTPUT"
