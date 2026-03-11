#!/usr/bin/env bash
set -euo pipefail

# Clean stale cargo fingerprints that can cause build failures,
# especially on Windows where file locking and path separators cause issues.

echo "=== Cleaning Cargo Fingerprints ==="

# Clean general cargo state
echo "Cleaning general Cargo state..."

if [ -d "target/.cargo-ok" ]; then
  rm -rf target/.cargo-ok
  echo "  Removed target/.cargo-ok"
fi

# Clean incremental compilation cache (most likely source of corruption)
if [ -d "target/incremental" ]; then
  rm -rf target/incremental
  echo "  Removed incremental compilation cache"
fi

# Clean profile-specific incremental caches
for profile in debug release; do
  if [ -d "target/$profile/incremental" ]; then
    rm -rf "target/$profile/incremental"
    echo "  Removed $profile incremental cache"
  fi
done

# For cross-compilation targets
for target_dir in target/*/; do
  if [ -d "${target_dir}incremental" ]; then
    rm -rf "${target_dir}incremental"
    echo "  Removed ${target_dir}incremental"
  fi
done

# Windows-specific cleanup: Remove registry state files that can be corrupted
if [[ "${RUNNER_OS:-}" == "Windows" ]] || [[ "${OS:-}" == "Windows_NT" ]]; then
  echo "Detected Windows platform - performing Windows-specific cleanup..."

  if [ -d ~/.cargo/registry/index ]; then
    rm -rf ~/.cargo/registry/index
    echo "  Removed cargo registry index"
  fi

  rm -f ~/.cargo/registry/cache/.cargo-ok 2>/dev/null || true
  echo "  Removed registry cache marker"

  echo "  Forcing cargo to rebuild registry state..."
  cargo metadata --quiet 2>/dev/null || true
fi

# Remove stale fingerprint metadata from target directory
if [ -d "target" ]; then
  find target -name ".cargo-ok" -delete 2>/dev/null || true
  find target -type f -name "*.json" -path "*fingerprint*" -delete 2>/dev/null || true
  echo "  Cleaned fingerprint metadata"
fi

# Verify cargo can still access its state
echo "Verifying Cargo state..."
if ! cargo --version &>/dev/null; then
  echo "ERROR: Cargo is broken after cleanup!"
  exit 1
fi

echo "Fingerprint cleanup completed successfully"
