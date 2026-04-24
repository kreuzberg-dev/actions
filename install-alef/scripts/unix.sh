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

install_alef() {
  local target max_attempts=3 attempt=1 wait_time=2
  target="$(detect_target)"
  local url="https://github.com/kreuzberg-dev/alef/releases/download/v${version}/alef-${target}.tar.gz"

  while [[ $attempt -le $max_attempts ]]; do
    echo "Installing alef v${version} for ${target} (attempt ${attempt}/${max_attempts})..."

    if curl --location \
      --connect-timeout 10 \
      --max-time 60 \
      --retry 2 \
      --retry-delay 1 \
      --fail \
      "$url" | tar xz -C "$alef_bin_dir"; then

      if [[ -x "$alef_bin_dir/alef" ]]; then
        echo "Alef installation successful"
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

if ! command -v alef >/dev/null 2>&1; then
  install_alef
else
  echo "Alef already installed: $(command -v alef)"
fi

if [[ ! -x "$alef_bin_dir/alef" ]] && ! command -v alef >/dev/null 2>&1; then
  echo "Error: alef binary not found or not executable" >&2
  exit 1
fi

echo "Alef is ready"
echo "$alef_bin_dir" >>"$GITHUB_PATH"
