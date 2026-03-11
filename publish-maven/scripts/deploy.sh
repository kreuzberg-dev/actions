#!/usr/bin/env bash
set -euo pipefail

pom_file="${INPUT_POM_FILE:?INPUT_POM_FILE is required}"
maven_profile="${INPUT_MAVEN_PROFILE:-publish}"
dry_run="${INPUT_DRY_RUN:-false}"

# Parse extra args safely from env var
extra_args=()
if [[ -n "${INPUT_EXTRA_ARGS:-}" ]]; then
  read -ra extra_args <<<"$INPUT_EXTRA_ARGS"
fi

if [[ ! -f "$pom_file" ]]; then
  echo "Error: POM file not found: $pom_file" >&2
  exit 1
fi

mvn_args=(
  -f "$pom_file"
  -P "$maven_profile"
  -B
  --no-transfer-progress
)

if [[ ${#extra_args[@]} -gt 0 ]]; then
  mvn_args+=("${extra_args[@]}")
fi

if [[ "$dry_run" == "true" ]]; then
  echo "[dry-run] mvn clean deploy ${mvn_args[*]}"
  mvn -f "$pom_file" clean verify -B --no-transfer-progress 2>&1 || true
  exit 0
fi

echo "Deploying to Maven Central..."

tmplog=$(mktemp)
trap 'rm -f "$tmplog"' EXIT

set +e
mvn clean deploy "${mvn_args[@]}" 2>&1 | tee "$tmplog"
exit_code=${PIPESTATUS[0]}
set -e

if [[ $exit_code -eq 0 ]]; then
  echo "Maven deploy completed successfully"
elif grep -qi "component with package url.*already exists" "$tmplog"; then
  echo "Version already published to Maven Central, skipping"
  if [[ -n "${GITHUB_ACTIONS:-}" ]]; then
    echo "::notice::Version already exists on Maven Central"
  fi
else
  echo "Maven deploy failed" >&2
  exit 1
fi
