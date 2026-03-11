#!/usr/bin/env bash
set -euo pipefail

if [ -d "${SCCACHE_PATH:-}" ] && [ -f "${SCCACHE_PATH:-}/sccache" ]; then
  echo "${SCCACHE_PATH}" >>"$GITHUB_PATH"
  echo "Added sccache to PATH"
else
  echo "Warning: sccache not available at ${SCCACHE_PATH:-}, proceeding without sccache"
fi
