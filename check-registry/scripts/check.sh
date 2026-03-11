#!/usr/bin/env bash
set -euo pipefail

registry="${INPUT_REGISTRY:?INPUT_REGISTRY is required}"
package="${INPUT_PACKAGE:?INPUT_PACKAGE is required}"
version="${INPUT_VERSION:?INPUT_VERSION is required}"
extra_packages="${INPUT_EXTRA_PACKAGES:-}"
tap_repo="${INPUT_TAP_REPO:-}"

MAX_ATTEMPTS=3
CONNECT_TIMEOUT=10
MAX_TIME=30

# --- Utility functions ---

check_url_status() {
  local url="$1"
  local attempt=1

  while [[ $attempt -le $MAX_ATTEMPTS ]]; do
    local status
    status=$(curl -s -o /dev/null -w "%{http_code}" \
      --retry 2 --retry-delay 3 \
      --connect-timeout "$CONNECT_TIMEOUT" --max-time "$MAX_TIME" \
      "$url") || status="000"

    if [[ "$status" == "200" ]]; then
      echo "true"
      return 0
    elif [[ "$status" == "404" ]]; then
      echo "false"
      return 0
    fi

    echo "Attempt $attempt: unexpected HTTP $status for $url" >&2
    if [[ $attempt -lt $MAX_ATTEMPTS ]]; then
      sleep $((attempt * 5))
    fi
    ((attempt++))
  done

  echo "false"
  return 0
}

check_url_json() {
  local url="$1"
  local attempt=1

  while [[ $attempt -le $MAX_ATTEMPTS ]]; do
    local response
    local status
    response=$(curl -s -w "\n%{http_code}" \
      --connect-timeout "$CONNECT_TIMEOUT" --max-time "$MAX_TIME" \
      "$url") || { status="000"; }

    status=$(echo "$response" | tail -1)
    local body
    body=$(echo "$response" | sed '$d')

    if [[ "$status" == "200" ]]; then
      echo "$body"
      return 0
    elif [[ "$status" == "404" ]]; then
      echo ""
      return 1
    fi

    echo "Attempt $attempt: unexpected HTTP $status for $url" >&2
    if [[ $attempt -lt $MAX_ATTEMPTS ]]; then
      sleep $((attempt * 5))
    fi
    ((attempt++))
  done

  echo ""
  return 1
}

# --- Registry-specific check functions ---

check_pypi() {
  local pkg="$1" ver="$2"
  check_url_status "https://pypi.org/pypi/${pkg}/${ver}/json"
}

check_npm() {
  local pkg="$1" ver="$2"
  # npm uses URL-encoded package names for scoped packages
  local encoded_pkg="${pkg//@/%40}"
  encoded_pkg="${encoded_pkg//\//%2F}"
  check_url_status "https://registry.npmjs.org/${encoded_pkg}/${ver}"
}

check_cratesio() {
  local pkg="$1" ver="$2"
  check_url_status "https://crates.io/api/v1/crates/${pkg}/${ver}"
}

check_nuget() {
  local pkg="$1" ver="$2"
  local lower_pkg="${pkg,,}"
  local lower_ver="${ver,,}"
  check_url_status "https://api.nuget.org/v3-flatcontainer/${lower_pkg}/${lower_ver}/${lower_pkg}.nuspec"
}

check_rubygems() {
  local pkg="$1" ver="$2"
  # RubyGems uses dots for pre-release instead of hyphens
  local ruby_ver="${ver//-/.}"

  local body
  if body=$(check_url_json "https://rubygems.org/api/v1/versions/${pkg}.json"); then
    if echo "$body" | python3 -c "
import sys, json
versions = json.load(sys.stdin)
target = '${ruby_ver}'
found = any(v.get('number') == target for v in versions)
print('true' if found else 'false')
" 2>/dev/null; then
      return 0
    fi
  fi
  echo "false"
}

check_hex() {
  local pkg="$1" ver="$2"

  local body
  if body=$(check_url_json "https://hex.pm/api/packages/${pkg}"); then
    if echo "$body" | python3 -c "
import sys, json
data = json.load(sys.stdin)
releases = data.get('releases', [])
target = '${ver}'
found = any(r.get('version') == target for r in releases)
print('true' if found else 'false')
" 2>/dev/null; then
      return 0
    fi
  fi
  echo "false"
}

check_maven() {
  local pkg="$1" ver="$2"
  # pkg format: group:artifact (e.g. dev.kreuzberg:kreuzberg)
  local group="${pkg%%:*}"
  local artifact="${pkg##*:}"
  local group_path="${group//.//}"
  check_url_status "https://repo1.maven.org/maven2/${group_path}/${artifact}/${ver}/${artifact}-${ver}.jar"
}

check_packagist() {
  local pkg="$1" ver="$2"

  local body
  if body=$(check_url_json "https://repo.packagist.org/p2/${pkg}.json"); then
    if echo "$body" | python3 -c "
import sys, json
data = json.load(sys.stdin)
pkgs = data.get('packages', {}).get('${pkg}', [])
target = '${ver}'
found = any(p.get('version') == target or p.get('version') == 'v' + target for p in pkgs)
print('true' if found else 'false')
" 2>/dev/null; then
      return 0
    fi
  fi
  echo "false"
}

check_homebrew() {
  local pkg="$1" ver="$2"
  if [[ -z "$tap_repo" ]]; then
    echo "Error: tap-repo is required for homebrew registry" >&2
    echo "false"
    return 0
  fi

  local formula_url="https://raw.githubusercontent.com/${tap_repo}/main/Formula/${pkg}.rb"
  if curl -sf "$formula_url" 2>/dev/null | grep -q "version \"${ver}\""; then
    echo "true"
  else
    echo "false"
  fi
}

# --- Main logic ---

check_package() {
  local reg="$1" pkg="$2" ver="$3"
  case "$reg" in
  pypi) check_pypi "$pkg" "$ver" ;;
  npm) check_npm "$pkg" "$ver" ;;
  cratesio) check_cratesio "$pkg" "$ver" ;;
  nuget) check_nuget "$pkg" "$ver" ;;
  rubygems) check_rubygems "$pkg" "$ver" ;;
  hex) check_hex "$pkg" "$ver" ;;
  maven) check_maven "$pkg" "$ver" ;;
  packagist) check_packagist "$pkg" "$ver" ;;
  homebrew) check_homebrew "$pkg" "$ver" ;;
  *)
    echo "Error: unsupported registry: $reg" >&2
    exit 1
    ;;
  esac
}

# Check primary package
result=$(check_package "$registry" "$package" "$version")
echo "exists=${result}" >>"$GITHUB_OUTPUT"
echo "${registry}: ${package}@${version} → exists=${result}"

# Check extra packages
if [[ -n "$extra_packages" ]]; then
  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    output_key="${line%%=*}"
    extra_pkg="${line#*=}"
    extra_result=$(check_package "$registry" "$extra_pkg" "$version")
    echo "${output_key}=${extra_result}" >>"$GITHUB_OUTPUT"
    echo "${registry}: ${extra_pkg}@${version} → ${output_key}=${extra_result}"
  done <<<"$extra_packages"
fi
