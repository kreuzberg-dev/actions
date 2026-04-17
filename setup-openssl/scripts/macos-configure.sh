#!/usr/bin/env bash
set -euo pipefail

prefix="$(brew --prefix openssl@3 2>/dev/null || brew --prefix openssl 2>/dev/null || true)"

if [ -z "$prefix" ] && [ -d "/opt/homebrew/opt/openssl@3" ]; then
  prefix="/opt/homebrew/opt/openssl@3"
fi

if [ -z "$prefix" ] && [ -d "/usr/local/opt/openssl@3" ]; then
  prefix="/usr/local/opt/openssl@3"
fi

if [ -z "$prefix" ]; then
  echo "Failed to locate Homebrew OpenSSL prefix" >&2
  echo "Checked: brew --prefix openssl@3, /opt/homebrew/opt/openssl@3, /usr/local/opt/openssl@3" >&2
  exit 1
fi

echo "OpenSSL detected at: $prefix"
echo "OpenSSL lib path: $prefix/lib"
echo "OpenSSL include path: $prefix/include"

# Force-link openssl so pre-built Ruby/Python binaries can find it in system paths
# (openssl@3 is keg-only by default on macOS)
brew link openssl@3 --force 2>/dev/null || true

{
  echo "OPENSSL_DIR=$prefix"
  echo "OPENSSL_LIB_DIR=$prefix/lib"
  echo "OPENSSL_INCLUDE_DIR=$prefix/include"
  echo "PKG_CONFIG_PATH=$prefix/lib/pkgconfig:${PKG_CONFIG_PATH:-}"
  echo "DYLD_LIBRARY_PATH=$prefix/lib:${DYLD_LIBRARY_PATH:-}"
} >>"$GITHUB_ENV"

if [[ -n "${GITHUB_PATH:-}" && -d "$prefix/bin" ]]; then
  echo "$prefix/bin" >>"$GITHUB_PATH"
fi
