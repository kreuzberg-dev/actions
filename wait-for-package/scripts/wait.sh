#!/usr/bin/env bash
set -euo pipefail

registry="${INPUT_REGISTRY:?INPUT_REGISTRY is required}"
package="${INPUT_PACKAGE:?INPUT_PACKAGE is required}"
version="${INPUT_VERSION:?INPUT_VERSION is required}"
max_attempts="${INPUT_MAX_ATTEMPTS:-10}"
maven_group_id="${INPUT_MAVEN_GROUP_ID:-}"

if ! [[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+ ]]; then
  echo "Error: Invalid version format: $version" >&2
  exit 1
fi

# shellcheck disable=SC2329
check_npm() {
  npm view "${package}@${version}" version 2>/dev/null | grep -q "$version"
}

# shellcheck disable=SC2329
check_pypi() {
  curl -sf "https://pypi.org/pypi/${package}/${version}/json" 2>/dev/null |
    PKG="$package" VER="$version" python3 -c "
import sys, json, os
d = json.load(sys.stdin)
sys.exit(0 if d.get('info', {}).get('version') == os.environ['VER'] else 1)
" 2>/dev/null
}

# shellcheck disable=SC2329
check_cratesio() {
  local lower_name prefix url
  lower_name="${package,,}"
  case ${#lower_name} in
  1) prefix="1/${lower_name}" ;;
  2) prefix="2/${lower_name}" ;;
  3) prefix="3/${lower_name:0:1}/${lower_name}" ;;
  *) prefix="${lower_name:0:2}/${lower_name:2:2}/${lower_name}" ;;
  esac
  url="https://index.crates.io/${prefix}"
  curl -sf "$url" 2>/dev/null | VER="$version" python3 -c "
import sys, json, os
target = os.environ['VER']
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    data = json.loads(line)
    if data.get('vers') == target:
        sys.exit(0)
sys.exit(1)
" 2>/dev/null
}

# shellcheck disable=SC2329
check_maven() {
  if [[ -z "$maven_group_id" ]]; then
    echo "Error: maven-group-id required for maven registry" >&2
    return 1
  fi
  local url="https://search.maven.org/solrsearch/select?q=g:${maven_group_id}+AND+a:${package}+AND+v:${version}&rows=1&wt=json"
  curl -sf "$url" 2>/dev/null |
    python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d.get('response',{}).get('numFound',0)>0 else 1)" 2>/dev/null
}

# shellcheck disable=SC2329
check_rubygems() {
  curl -sf "https://rubygems.org/api/v1/versions/${package}.json" 2>/dev/null |
    VER="$version" python3 -c "
import sys, json, os
versions = json.load(sys.stdin)
target = os.environ['VER']
for v in versions:
    if v.get('number') == target:
        sys.exit(0)
sys.exit(1)
" 2>/dev/null
}

# Validate registry name
case "$registry" in
npm | pypi | cratesio | maven | rubygems) ;;
*)
  echo "Error: Unsupported registry: $registry (supported: npm, pypi, cratesio, maven, rubygems)" >&2
  exit 1
  ;;
esac

echo "Waiting for ${package}@${version} on ${registry} (max ${max_attempts} attempts)..."

for attempt in $(seq 1 "$max_attempts"); do
  delay=$((2 ** attempt > 64 ? 64 : 2 ** attempt))

  if "check_${registry}" 2>/dev/null; then
    echo "Package ${package}@${version} found on ${registry} (attempt ${attempt})"
    exit 0
  fi

  echo "Attempt ${attempt}/${max_attempts}: not yet available, waiting ${delay}s..."
  sleep "$delay"
done

echo "Error: ${package}@${version} not found on ${registry} after ${max_attempts} attempts" >&2
exit 1
