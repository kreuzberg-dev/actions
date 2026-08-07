#!/usr/bin/env bash
# ~keep Sourced helper, not run directly — no shebang execution, no set -euo pipefail here so it
# doesn't override the caller's shell options.

# sha256_of FILE — print the lowercase hex sha256 of FILE. Prefers sha256sum (Linux, Windows via
# Git Bash); falls back to shasum -a 256 (macOS has no sha256sum by default).
sha256_of() {
	local file="$1"
	if command -v sha256sum >/dev/null 2>&1; then
		sha256sum "$file" | cut -d' ' -f1
	else
		shasum -a 256 "$file" | cut -d' ' -f1
	fi
}
