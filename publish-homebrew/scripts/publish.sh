#!/usr/bin/env bash
set -euo pipefail

bottles_dir="${INPUT_BOTTLES_DIR:?INPUT_BOTTLES_DIR is required}"
formula_name="${INPUT_FORMULA_NAME:?INPUT_FORMULA_NAME is required}"
tap_repo="${INPUT_TAP_REPO:?INPUT_TAP_REPO is required}"
tag="${INPUT_TAG:?INPUT_TAG is required}"
version="${INPUT_VERSION:?INPUT_VERSION is required}"
github_repo="${INPUT_GITHUB_REPO:?INPUT_GITHUB_REPO is required}"
bot_name="${INPUT_BOT_NAME:-kreuzberg-bot}"
bot_email="${INPUT_BOT_EMAIL:-bot@kreuzberg.dev}"
dry_run="${INPUT_DRY_RUN:-false}"
max_retries=3
retry_delay=5

if [[ ! -d "$bottles_dir" ]]; then
  echo "Error: Bottles directory not found: $bottles_dir" >&2
  exit 1
fi

echo "=== Updating Homebrew formula ==="
echo "Formula: $formula_name"
echo "Tag: $tag"
echo "Version: $version"
echo "Tap: $tap_repo"

# --- Quick idempotency check ---

formula_url="https://raw.githubusercontent.com/${tap_repo}/main/Formula/${formula_name}.rb"
if curl -sf "$formula_url" 2>/dev/null | grep -q "archive/${tag}.tar.gz"; then
  echo "Formula already references tag ${tag}, skipping update"
  exit 0
fi

# --- Utility functions ---

validate_sha256() {
  local sha256="$1"
  [[ $sha256 =~ ^[a-f0-9]{64}$ ]]
}

compute_sha256() {
  local file="$1"
  local sha256
  sha256=$(shasum -a 256 "$file" | cut -d' ' -f1)
  if ! validate_sha256 "$sha256"; then
    echo "Error: Invalid SHA256 for $file" >&2
    return 1
  fi
  echo "$sha256"
}

download_with_retry() {
  local url="$1"
  local output_file="$2"
  local attempt=1

  while [[ $attempt -le $max_retries ]]; do
    echo "Downloading $url (attempt $attempt/$max_retries)..."
    if curl -f -L --max-time 120 --retry 1 --retry-delay 2 -o "$output_file" "$url" 2>/dev/null; then
      return 0
    fi
    if [[ $attempt -lt $max_retries ]]; then
      echo "Retrying in ${retry_delay}s..."
      sleep "$retry_delay"
    fi
    ((attempt++))
  done

  echo "Error: Failed to download after $max_retries attempts: $url" >&2
  return 1
}

# --- Download bottles from GitHub Release and compute checksums ---

declare -A bottle_hashes
declare -a bottle_tags

temp_dir=$(mktemp -d)
trap 'rm -rf "$temp_dir"' EXIT

for bottle in "$bottles_dir/${formula_name}"-*.bottle.tar.gz; do
  [[ -f "$bottle" ]] || continue

  filename="$(basename "$bottle")"
  without_suffix="${filename%.bottle.tar.gz}"
  bottle_tag="${without_suffix##*.}"

  echo "Processing bottle: $filename ($bottle_tag)"

  # Download from GitHub Release to ensure checksums match what users get
  bottle_url="https://github.com/${github_repo}/releases/download/${tag}/${filename}"
  downloaded="$temp_dir/$filename"

  if ! download_with_retry "$bottle_url" "$downloaded"; then
    echo "Error: Failed to download bottle: $bottle_url" >&2
    exit 1
  fi

  # Verify integrity
  if ! tar -tzf "$downloaded" >/dev/null 2>&1; then
    echo "Error: Downloaded bottle is corrupted: $filename" >&2
    exit 1
  fi

  sha256=$(compute_sha256 "$downloaded")
  bottle_hashes[$bottle_tag]=$sha256
  bottle_tags+=("$bottle_tag")
  echo "  $bottle_tag: $sha256"
done

if [[ ${#bottle_hashes[@]} -eq 0 ]]; then
  echo "Error: No bottle artifacts found matching ${formula_name}-*.bottle.tar.gz in $bottles_dir" >&2
  exit 1
fi

echo "Validated ${#bottle_hashes[@]} bottles"

# --- Download and hash source tarball ---

tarball_url="https://github.com/${github_repo}/archive/${tag}.tar.gz"
tarball_temp="$temp_dir/source.tar.gz"

echo "Downloading source tarball..."
if ! download_with_retry "$tarball_url" "$tarball_temp"; then
  echo "Error: Failed to download source tarball" >&2
  exit 1
fi

if ! tar -tzf "$tarball_temp" >/dev/null 2>&1; then
  echo "Error: Source tarball is corrupted" >&2
  exit 1
fi

tarball_sha256=$(compute_sha256 "$tarball_temp")
echo "Source tarball SHA256: $tarball_sha256"

# --- Clone tap and update formula ---

tap_dir="$temp_dir/tap"
echo "Cloning tap repository..."
git clone "https://github.com/${tap_repo}.git" "$tap_dir"

formula_path="$tap_dir/Formula/${formula_name}.rb"
if [[ ! -f "$formula_path" ]]; then
  echo "Error: Formula not found at Formula/${formula_name}.rb" >&2
  exit 1
fi

formula_content=$(<"$formula_path")

# Build bottle block
bottle_block="  bottle do"
bottle_block+=$'\n'"    root_url \"https://github.com/${github_repo}/releases/download/${tag}\""

for bottle_tag in "${bottle_tags[@]}"; do
  sha256=${bottle_hashes[$bottle_tag]}
  bottle_block+=$'\n'"    sha256 cellar: :any_skip_relocation, $bottle_tag: \"$sha256\""
done
bottle_block+=$'\n'"  end"

# Update URL and sha256
new_formula=$(echo "$formula_content" | sed \
  -e "s|url \"https://github.com/${github_repo}/archive/.*\.tar\.gz\"|url \"https://github.com/${github_repo}/archive/${tag}.tar.gz\"|" \
  -e "s|sha256 ['\"'][a-f0-9]*['\"']|sha256 \"${tarball_sha256}\"|")

# Remove existing bottle blocks
new_formula=$(echo "$new_formula" | sed '/^  bottle do$/,/^  end$/d')
new_formula=$(echo "$new_formula" | sed '/^  # bottle do$/,/^  # end$/d')

# Insert bottle block before first depends_on using Python for reliability
new_formula=$(
  python3 <<PYTHON_SCRIPT
import sys

formula = """$new_formula"""
bottle_block = """$bottle_block"""

lines = formula.split('\n')
result = []
prev_blank = False

for line in lines:
    is_blank = line.strip() == ''
    if is_blank and prev_blank:
        continue
    prev_blank = is_blank
    result.append(line)

final = []
inserted = False
for line in result:
    if line.startswith('  depends_on') and not inserted:
        final.append(bottle_block)
        final.append('')
        inserted = True
    final.append(line)

print('\n'.join(final))
PYTHON_SCRIPT
)

echo "$new_formula" >"$formula_path"

echo ""
echo "=== Updated formula (first 30 lines) ==="
head -30 "$formula_path"
echo "..."

if [[ "$dry_run" == "true" ]]; then
  echo ""
  echo "[dry-run] Formula updated locally but not pushed"
  if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
    echo "### Homebrew (dry-run)" >>"$GITHUB_STEP_SUMMARY"
    echo "Formula \`${formula_name}\` would be updated to version ${version}" >>"$GITHUB_STEP_SUMMARY"
  fi
  exit 0
fi

# --- Commit and push ---

cd "$tap_dir"
git config user.name "$bot_name"
git config user.email "$bot_email"

if git diff --quiet "Formula/${formula_name}.rb"; then
  echo "No changes to formula"
  exit 0
fi

git add "Formula/${formula_name}.rb"
git commit -m "chore(homebrew): update ${formula_name} to ${version}

Auto-update from release ${tag}

Includes pre-built bottles for macOS"

echo "Pushing to ${tap_repo}..."
git push origin main

echo "Formula updated successfully"

if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  {
    echo "### Homebrew Published"
    echo "- **Formula**: ${formula_name}"
    echo "- **Version**: ${version}"
    echo "- **Bottles**: ${#bottle_hashes[@]}"
  } >>"$GITHUB_STEP_SUMMARY"
fi

