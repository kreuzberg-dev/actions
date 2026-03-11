#!/usr/bin/env bash
set +e

echo "Checking sccache installation..."
if command -v sccache &>/dev/null; then
  echo "sccache found in PATH"
  which sccache
  sccache --version || echo "sccache version check failed"
elif [ -n "${SCCACHE_PATH:-}" ] && [ -d "${SCCACHE_PATH}" ]; then
  echo "SCCACHE_PATH is set to: ${SCCACHE_PATH}"
  if [ -f "${SCCACHE_PATH}/sccache" ]; then
    echo "sccache executable found at SCCACHE_PATH"
    "${SCCACHE_PATH}/sccache" --version || echo "sccache version check failed"
  else
    echo "sccache executable NOT found at SCCACHE_PATH"
    ls -la "${SCCACHE_PATH}" || echo "Failed to list SCCACHE_PATH contents"
  fi
else
  echo "Warning: sccache not found in PATH and SCCACHE_PATH not set or invalid"
  echo "Continuing without sccache"
fi

exit 0
