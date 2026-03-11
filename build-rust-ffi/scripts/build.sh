#!/usr/bin/env bash
set -euo pipefail

crate_name="${CRATE_NAME:?CRATE_NAME required}"
features="${FEATURES:-}"
target="${TARGET:-}"
build_profile="${BUILD_PROFILE:-release}"
verbose="${VERBOSE:-true}"
additional_flags="${ADDITIONAL_FLAGS:-}"
manifest_path="${MANIFEST_PATH:-}"
disable_sccache="${DISABLE_SCCACHE:-true}"

echo "=== Building Rust FFI library ==="

# Build cargo args
if [ -n "$manifest_path" ]; then
  CARGO_ARGS=("build" "--manifest-path" "$manifest_path")
else
  CARGO_ARGS=("build" "--package" "$crate_name")
fi

if [ "$build_profile" = "release" ]; then
  CARGO_ARGS+=("--release")
  PROFILE_DIR="release"
else
  PROFILE_DIR="debug"
fi

if [ -n "$features" ]; then
  CARGO_ARGS+=("--features" "$features")
fi

if [ -n "$target" ]; then
  CARGO_ARGS+=("--target" "$target")
  TARGET_SUBDIR="${target}/"
else
  TARGET_SUBDIR=""
fi

if [ "$verbose" = "true" ]; then
  CARGO_ARGS+=("-vv")
fi

if [ -n "$additional_flags" ]; then
  read -ra EXTRA_FLAGS <<<"$additional_flags"
  CARGO_ARGS+=("${EXTRA_FLAGS[@]}")
fi

echo "Build command: cargo ${CARGO_ARGS[*]}"
echo ""

echo "=== Build Environment ==="
echo "Rust version: $(rustc --version)"
echo "Cargo version: $(cargo --version)"
echo "Working directory: $(pwd)"
echo "CARGO_TARGET_DIR: ${CARGO_TARGET_DIR:-<not set>}"
if [ -n "$target" ]; then
  echo "Target: $target"
fi
echo ""

# Disable sccache for FFI builds if requested (common for cdylib builds)
if [ "$disable_sccache" = "true" ]; then
  export RUSTC_WRAPPER=""
  export CARGO_BUILD_RUSTC_WRAPPER=""
  export SCCACHE_GHA_ENABLED="false"
fi

# Pass through OpenSSL env vars if set
if [ -n "${OPENSSL_DIR:-}" ]; then
  echo "OPENSSL_DIR: $OPENSSL_DIR"
fi

# Build with error diagnostics
BUILD_LOG="$(mktemp)"
trap 'rm -f "$BUILD_LOG"' EXIT

if ! cargo "${CARGO_ARGS[@]}" 2>&1 | tee "$BUILD_LOG"; then
  echo ""
  echo "=== Build Failed ==="
  echo "Command: cargo ${CARGO_ARGS[*]}"
  echo ""
  echo "Last 50 lines of build output:"
  tail -50 "$BUILD_LOG"
  echo ""
  echo "Checking for common errors:"

  if grep -i "link" "$BUILD_LOG" | grep -i "error" | head -5 2>/dev/null; then
    echo "Linking errors detected. Check library paths and dependencies."
  fi

  if grep -i "could not find" "$BUILD_LOG" | head -5 2>/dev/null; then
    echo "Missing dependencies detected."
  fi

  if grep -i "openssl" "$BUILD_LOG" | grep -i "error" | head -5 2>/dev/null; then
    echo "OpenSSL errors detected. Verify OPENSSL_DIR is set correctly."
  fi

  exit 1
fi

# Determine output directory
if [ -n "${CARGO_TARGET_DIR:-}" ]; then
  TARGET_DIR="$CARGO_TARGET_DIR"
else
  TARGET_DIR="target"
fi

FULL_TARGET_DIR="${TARGET_DIR}/${TARGET_SUBDIR}${PROFILE_DIR}"

echo ""
echo "=== Build Successful ==="
echo "Target directory: $FULL_TARGET_DIR"
echo ""

# Derive library name from crate name (hyphens -> underscores)
lib_stem="${crate_name//-/_}"

# Search for built library artifacts
LIB_PATTERNS="lib${lib_stem}.so lib${lib_stem}.dylib ${lib_stem}.dll lib${lib_stem}.a"

FOUND_LIB=""
for pattern in $LIB_PATTERNS; do
  if [ -f "$FULL_TARGET_DIR/$pattern" ]; then
    FOUND_LIB="$FULL_TARGET_DIR/$pattern"
    echo "Found library: $FOUND_LIB"
    ls -lh "$FOUND_LIB"
    break
  fi
done

if [ -z "$FOUND_LIB" ]; then
  echo "Could not find expected library artifact. Listing library files:"
  shopt -s nullglob
  candidates=(
    "$FULL_TARGET_DIR"/*.so
    "$FULL_TARGET_DIR"/*.dylib
    "$FULL_TARGET_DIR"/*.dll
    "$FULL_TARGET_DIR"/*.a
  )
  if ((${#candidates[@]})); then
    ls -lh "${candidates[@]}"
    # Use the first found as fallback
    FOUND_LIB="${candidates[0]}"
    echo "Using: $FOUND_LIB"
  else
    echo "No library files found in $FULL_TARGET_DIR"
  fi
fi

echo "library-path=$FOUND_LIB" >>"$GITHUB_OUTPUT"
echo "target-dir=$FULL_TARGET_DIR" >>"$GITHUB_OUTPUT"

echo ""
echo "=== FFI Build Complete ==="
