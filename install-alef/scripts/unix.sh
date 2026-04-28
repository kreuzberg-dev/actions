#!/usr/bin/env bash
set -euo pipefail

version="${1:?version required}"

alef_bin_dir="${HOME}/.local/bin"
mkdir -p "$alef_bin_dir"

# Determine platform triple from OS and architecture
detect_target() {
  local os arch
  os="$(uname -s)"
  arch="$(uname -m)"

  case "$os" in
  Linux)
    case "$arch" in
    x86_64) echo "x86_64-unknown-linux-gnu" ;;
    aarch64) echo "aarch64-unknown-linux-gnu" ;;
    *)
      echo "Error: unsupported Linux architecture: $arch" >&2
      return 1
      ;;
    esac
    ;;
  Darwin)
    case "$arch" in
    arm64) echo "aarch64-apple-darwin" ;;
    x86_64) echo "aarch64-apple-darwin" ;; # Use ARM binary via Rosetta
    *)
      echo "Error: unsupported macOS architecture: $arch" >&2
      return 1
      ;;
    esac
    ;;
  *)
    echo "Error: unsupported OS: $os" >&2
    return 1
    ;;
  esac
}

# Read pinned version from top-level `version` key in alef.toml
read_pinned_version() {
  if [[ -f "alef.toml" ]]; then
    local pinned
    pinned="$(sed -n '/^\[/q; s/^version[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' alef.toml | head -1)"
    if [[ -n "$pinned" ]]; then
      echo "$pinned"
      return 0
    fi
  fi
  return 1
}

# Check whether a tag has a downloadable binary for the current target.
binary_exists_for_tag() {
  local tag target url
  tag="$1"
  target="$(detect_target)"
  url="https://github.com/kreuzberg-dev/alef/releases/download/v${tag}/alef-${target}.tar.gz"
  curl --silent --fail --head --output /dev/null "$url"
}

# Resolve "latest" to the actual latest release tag.
# If the latest tag exists but binaries are not yet uploaded (race window
# during a fresh alef release), walk back through previous releases until
# we find one with a downloadable binary for this target.
resolve_version() {
  if [[ "$version" == "latest" ]]; then
    # Check alef.toml for a pinned version first
    local pinned
    if pinned="$(read_pinned_version)"; then
      echo "Using pinned version from alef.toml: $pinned" >&2
      echo "$pinned"
      return 0
    fi

    local tags
    tags="$(curl --silent --fail \
      "https://api.github.com/repos/kreuzberg-dev/alef/releases?per_page=10" |
      grep '"tag_name"' | sed -E 's/.*"v([^"]+)".*/\1/')"
    if [[ -z "$tags" ]]; then
      echo "Error: could not list alef releases" >&2
      return 1
    fi

    local tag
    while IFS= read -r tag; do
      [[ -z "$tag" ]] && continue
      if binary_exists_for_tag "$tag"; then
        echo "$tag"
        return 0
      fi
      echo "Tag v${tag} has no binary for $(detect_target) yet — falling back to previous release" >&2
    done <<<"$tags"

    echo "Error: no recent alef release has a binary for $(detect_target)" >&2
    return 1
  else
    echo "$version"
  fi
}

# Install from a GitHub release binary
install_from_release() {
  local resolved_version target max_attempts=3 attempt=1 wait_time=2
  resolved_version="$(resolve_version)"
  target="$(detect_target)"
  local url="https://github.com/kreuzberg-dev/alef/releases/download/v${resolved_version}/alef-${target}.tar.gz"

  while [[ $attempt -le $max_attempts ]]; do
    echo "Installing alef v${resolved_version} for ${target} (attempt ${attempt}/${max_attempts})..."

    if curl --location \
      --connect-timeout 10 \
      --max-time 60 \
      --retry 2 \
      --retry-delay 1 \
      --fail \
      "$url" | tar xz --strip-components=1 -C "$alef_bin_dir"; then

      if [[ -x "$alef_bin_dir/alef" ]]; then
        echo "Alef v${resolved_version} installed successfully"
        return 0
      else
        echo "Error: alef binary not found at $alef_bin_dir/alef"
        rm -f "$alef_bin_dir/alef"
      fi
    else
      echo "Download failed from $url"
    fi

    attempt=$((attempt + 1))
    if [[ $attempt -le $max_attempts ]]; then
      echo "Retrying in ${wait_time}s..."
      sleep "$wait_time"
      wait_time=$((wait_time * 2))
    fi
  done

  echo "Error: Failed to install alef after ${max_attempts} attempts" >&2
  return 1
}

# Install from main branch via cargo install
install_from_main() {
  echo "Installing alef from main branch via cargo install..."
  if ! command -v cargo >/dev/null 2>&1; then
    echo "Error: cargo not found — required for installing from main branch" >&2
    return 1
  fi
  CARGO_INSTALL_ROOT="$alef_bin_dir/.." \
    cargo install --git https://github.com/kreuzberg-dev/alef --locked --bin alef
  echo "Alef installed from main branch"
}

if ! command -v alef >/dev/null 2>&1; then
  if [[ "$version" == "main" ]]; then
    install_from_main
  else
    install_from_release
  fi
else
  echo "Alef already installed: $(command -v alef)"
fi

if [[ ! -x "$alef_bin_dir/alef" ]] && ! command -v alef >/dev/null 2>&1; then
  echo "Error: alef binary not found or not executable" >&2
  exit 1
fi

echo "Alef is ready"
echo "$alef_bin_dir" >>"$GITHUB_PATH"
