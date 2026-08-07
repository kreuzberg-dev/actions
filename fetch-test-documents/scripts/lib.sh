#!/usr/bin/env bash
# ~keep Sourced helper, not run directly — no shebang execution, no set -euo pipefail here so it
# doesn't override the caller's shell options.

# to_posix_path PATH — echo PATH in a form this shell can actually use.
#
# ~keep On Windows runners the values GitHub hands us (runner.temp, github.action_path) are native
# paths like `D:\a\_temp`. Git Bash cannot open those, and worse, `\a` and `\_` are read as escape
# sequences, so an unquoted expansion silently collapses to `D:a_temp`. cygpath exists only on
# Windows, so elsewhere this is a no-op.
to_posix_path() {
	local path="$1"
	if command -v cygpath >/dev/null 2>&1; then
		cygpath -u "$path"
	else
		printf '%s' "$path"
	fi
}

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
