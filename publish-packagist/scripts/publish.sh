#!/usr/bin/env bash
set -euo pipefail

username="${INPUT_USERNAME:?INPUT_USERNAME is required}"
package_name="${INPUT_PACKAGE_NAME:?INPUT_PACKAGE_NAME is required}"
version="${INPUT_VERSION:?INPUT_VERSION is required}"
repository_url="${INPUT_REPOSITORY_URL:?INPUT_REPOSITORY_URL is required}"
max_attempts="${INPUT_MAX_ATTEMPTS:-12}"
poll_interval="${INPUT_POLL_INTERVAL:-10}"
dry_run="${INPUT_DRY_RUN:-false}"

if [[ "$dry_run" == "true" ]]; then
  echo "[dry-run] Would trigger Packagist update for ${package_name}@${version}"
  exit 0
fi

# Trigger Packagist update via API
if [[ -n "${PACKAGIST_API_TOKEN:-}" ]]; then
  echo "Triggering Packagist update for ${package_name}..."

  set +e
  response=$(curl -sf -X POST \
    "https://packagist.org/api/update-package?username=${username}&apiToken=${PACKAGIST_API_TOKEN}" \
    -d "{\"repository\":{\"url\":\"${repository_url}\"}}" \
    -H "Content-Type: application/json" 2>&1)
  api_exit=$?
  set -e

  if [[ $api_exit -eq 0 ]]; then
    echo "Packagist API triggered successfully"
  else
    echo "Warning: Packagist API trigger failed (will rely on webhook): $response"
  fi
else
  echo "No PACKAGIST_API_TOKEN set, relying on automatic webhook"
fi

# Poll for version availability
echo "Polling Packagist for ${package_name}@${version} (max ${max_attempts} attempts, ${poll_interval}s interval)..."

for attempt in $(seq 1 "$max_attempts"); do
  set +e
  pkg_json=$(curl -sf "https://packagist.org/packages/${package_name}.json" 2>/dev/null)
  set -e

  if [[ -n "$pkg_json" ]]; then
    if echo "$pkg_json" | VERSION="$version" python3 -c "
import sys, json, os
data = json.load(sys.stdin)
versions = data.get('package', {}).get('versions', {})
target = os.environ['VERSION']
for v_key in versions:
    normalized = v_key.lstrip('v')
    if normalized == target or v_key == target:
        sys.exit(0)
sys.exit(1)
" 2>/dev/null; then
      echo "Package ${package_name}@${version} found on Packagist (attempt ${attempt})"
      exit 0
    fi
  fi

  echo "Attempt ${attempt}/${max_attempts}: not yet available, waiting ${poll_interval}s..."
  sleep "$poll_interval"
done

echo "Warning: ${package_name}@${version} not found on Packagist after ${max_attempts} attempts"
echo "The package may still appear after webhook processing completes"
exit 0
