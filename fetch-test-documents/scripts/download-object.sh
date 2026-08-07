#!/usr/bin/env bash
# Downloads one content-addressed object into the cache store, verifying its sha256. Invoked once
# per unique object, in parallel, by fetch.sh via xargs -P.
#
# Args: $1 = sha256, $2 = bucket name, $3 = cache dir (objects live at <cache-dir>/objects/<sha256>)
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${script_dir}/lib.sh"

sha="$1"
bucket="$2"
cache_dir="$(to_posix_path "$3")"

objects_dir="${cache_dir}/objects"
mkdir -p "$objects_dir"
dest="${objects_dir}/${sha}"

if [[ -f "$dest" ]] && [[ "$(sha256_of "$dest")" == "$sha" ]]; then
	echo "cached: ${sha}"
	exit 0
fi

url="https://storage.googleapis.com/${bucket}/objects/${sha}"
tmp="$(mktemp "${objects_dir}/.download.XXXXXX")"
trap 'rm -f "$tmp"' EXIT

echo "downloading: ${url}"
curl --proto '=https' \
	--tlsv1.2 \
	--fail \
	--silent \
	--show-error \
	--location \
	--connect-timeout 10 \
	--max-time 300 \
	--retry 3 \
	--retry-delay 2 \
	"$url" \
	--output "$tmp"

actual="$(sha256_of "$tmp")"
if [[ "$actual" != "$sha" ]]; then
	echo "::error::checksum mismatch downloading ${url}: expected ${sha}, got ${actual}" >&2
	exit 1
fi

mv "$tmp" "$dest"
trap - EXIT
echo "fetched: ${sha}"
