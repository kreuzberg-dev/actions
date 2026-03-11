#!/usr/bin/env bash
set -euo pipefail

use_sccache="${1:-false}"
macos_dynamic_lookup="${2:-true}"

echo "Configuring Rust compilation environment..."

if [ "$use_sccache" = "true" ]; then
  if command -v sccache &>/dev/null; then
    sccache_version="$(sccache --version 2>&1 || echo "unknown")"
    echo "sccache is available (version: $sccache_version), enabling as RUSTC_WRAPPER"
    {
      echo "SCCACHE_GHA_ENABLED=true"
      echo "RUSTC_WRAPPER=sccache"
      echo "SCCACHE_STARTUP_TIMEOUT=120"
      echo "SCCACHE_IDLE_TIMEOUT=0"
      if [[ "${RUNNER_OS:-}" == "Windows" ]]; then
        echo "SCCACHE_NO_DAEMON=1"
        echo "SCCACHE_DIR=$RUNNER_TEMP/sccache"
      fi
    } >>"$GITHUB_ENV"
  else
    echo "Warning: sccache requested but not found in PATH"
    echo "Checking SCCACHE_PATH environment variable..."
    if [ -n "${SCCACHE_PATH:-}" ] && [ -f "${SCCACHE_PATH}/sccache" ]; then
      echo "Found sccache at SCCACHE_PATH: ${SCCACHE_PATH}/sccache"
      echo "SCCACHE_GHA_ENABLED=true" >>"$GITHUB_ENV"
      echo "RUSTC_WRAPPER=${SCCACHE_PATH}/sccache" >>"$GITHUB_ENV"
    else
      echo "sccache not available, proceeding with direct compilation"
      echo "SCCACHE_GHA_ENABLED=false" >>"$GITHUB_ENV"
      echo "RUSTC_WRAPPER=" >>"$GITHUB_ENV"
    fi
  fi
else
  echo "sccache disabled by configuration"
  echo "SCCACHE_GHA_ENABLED=false" >>"$GITHUB_ENV"
  echo "RUSTC_WRAPPER=" >>"$GITHUB_ENV"
fi

base="${RUSTFLAGS:+$RUSTFLAGS }-D warnings"

# On macOS, optionally add linker flags for undefined symbol lookup (needed for extension builds)
if [ "$macos_dynamic_lookup" = "true" ]; then
  if [[ "${RUNNER_OS:-}" == "macOS" ]] || [[ "$(uname)" == "Darwin" ]]; then
    echo "Detected macOS, adding -undefined dynamic_lookup for extension builds"
    base+=" -C link-arg=-undefined -C link-arg=dynamic_lookup"
  fi
fi

check_output=""
if ! check_output="$(printf 'fn main() {}\n' | RUSTC_COLOR=never rustc -W unpredictable-function-pointer-comparisons - 2>&1)"; then
  :
fi
if grep -qi "unknown lint" <<<"$check_output"; then
  echo "unpredictable-function-pointer-comparisons lint unavailable on $(rustc -V); skipping flag"
else
  base+=" -A unpredictable-function-pointer-comparisons"
  echo "Detected unpredictable-function-pointer-comparisons lint support; appended suppression flag"
fi

check_output=""
if ! check_output="$(printf 'fn main() {}\n' | RUSTC_COLOR=never rustc -W mismatched-lifetime-syntaxes - 2>&1)"; then
  :
fi
if grep -qi "unknown lint" <<<"$check_output"; then
  echo "mismatched-lifetime-syntaxes lint unavailable on $(rustc -V); skipping flag"
else
  base+=" -A mismatched-lifetime-syntaxes"
  echo "Detected mismatched-lifetime-syntaxes lint support; appended suppression flag"
fi

check_output=""
if ! check_output="$(printf 'fn main() {}\n' | RUSTC_COLOR=never rustc -W fn_ptr_eq - 2>&1)"; then
  :
fi
if grep -qi "unknown lint" <<<"$check_output"; then
  echo "fn_ptr_eq lint unavailable on $(rustc -V); skipping flag"
else
  base+=" -A fn_ptr_eq --cfg has_fn_ptr_eq_lint"
  echo "Detected fn_ptr_eq lint support; appended suppression flags"
fi

echo "Setting RUSTFLAGS to: $base"
echo "RUSTFLAGS=$base" >>"$GITHUB_ENV"
