#!/bin/bash

set -euo pipefail

CRATE_NAME="$1"
LIB_NAME="$2"
WORKSPACE_ROOT="$3"

CRATE_DIR="${WORKSPACE_ROOT}/crates/${CRATE_NAME}"
if [ ! -d "$CRATE_DIR" ]; then
	CRATE_DIR="${WORKSPACE_ROOT}/packages/${CRATE_NAME}"
fi

if [ ! -d "$CRATE_DIR" ]; then
	echo "Error: crate directory not found at $CRATE_DIR" >&2
	exit 1
fi

BUILD_TEMP=$(mktemp -d)
trap 'rm -rf "$BUILD_TEMP"' EXIT

strip_internal_paths() {
	python3 - "$1" <<'PY'
import re, sys
p = sys.argv[1]
lines = open(p).read().splitlines(keepends=True)
dep_hdr = re.compile(r'^\s*\[(build-|dev-)?dependencies(\.[^\]]+)?\]\s*$')
tgt_dep_hdr = re.compile(r'^\s*\[target\.[^\]]+\.(build-|dev-)?dependencies(\.[^\]]+)?\]\s*$')
any_hdr = re.compile(r'^\s*\[')
path_rel = re.compile(r'(,\s*)?path\s*=\s*"(\.[^"]*|[^"]*/[^"]*)"(\s*,)?')
def repl(m):
    return ',' if (m.group(1) and m.group(3)) else ''
in_deps = False
out = []
for ln in lines:
    if any_hdr.match(ln):
        in_deps = bool(dep_hdr.match(ln) or tgt_dep_hdr.match(ln))
    out.append(path_rel.sub(repl, ln) if in_deps and 'path' in ln else ln)
open(p, 'w').write(''.join(out))
PY
}

cp -r "$CRATE_DIR" "$BUILD_TEMP/crate"
cd "$BUILD_TEMP/crate"

if grep -q 'workspace = true' Cargo.toml 2>/dev/null; then
	ws_version=""
	ws_edition=""
	ws_license=""

	if grep -q "^\[workspace\.package\]" "$WORKSPACE_ROOT/Cargo.toml"; then
		ws_section=$(sed -n '/^\[workspace\.package\]/,/^\[/p' "$WORKSPACE_ROOT/Cargo.toml" | head -n -1)
		ws_version=$(echo "$ws_section" | grep "^version" | head -1 | sed 's/.*= *"\([^"]*\)".*/\1/')
		ws_edition=$(echo "$ws_section" | grep "^edition" | head -1 | sed 's/.*= *"\([^"]*\)".*/\1/')
		ws_license=$(echo "$ws_section" | grep "^license" | head -1 | sed 's/.*= *"\([^"]*\)".*/\1/')
	fi

	# ~keep The dotted form (`version.workspace = true`) is what cargo emits and what
	# alef generates; it is NOT matched by the `^version = ` deletes below, so without
	# this rule `s/workspace = true//` truncated it to a bare `version.` and every
	# rewritten manifest became invalid TOML ("Invalid initial character for a key
	# part"). Delete the whole line instead: the three keys we can recover are re-added
	# from [workspace.package] just below, and the rest (readme/keywords/categories) are
	# publish-only metadata this build does not need. The trailing bare substitution
	# stays for `[lints]`-style `workspace = true`, which has no key to delete.
	sed -i.bak \
		-e '/^[A-Za-z0-9_-]*\.workspace[[:space:]]*=[[:space:]]*true/d' \
		-e '/^edition = /d' \
		-e '/^version = /d' \
		-e '/^license = /d' \
		-e 's/workspace = true//' \
		Cargo.toml

	if [ -n "$ws_version" ] && ! grep -q "^version =" Cargo.toml; then
		sed -i.bak "s/^\[package\]/[package]\nversion = \"$ws_version\"/" Cargo.toml
	fi
	if [ -n "$ws_edition" ] && ! grep -q "^edition =" Cargo.toml; then
		sed -i.bak "s/^\[package\]/[package]\nedition = \"$ws_edition\"/" Cargo.toml
	fi
	if [ -n "$ws_license" ] && ! grep -q "^license =" Cargo.toml; then
		sed -i.bak "s/^\[package\]/[package]\nlicense = \"$ws_license\"/" Cargo.toml
	fi

	rm -f Cargo.toml.bak
	# ~keep Progress goes to stderr: this script's stdout is captured verbatim into
	# `extension-path`, and a second line there makes the runner reject the whole
	# `$GITHUB_OUTPUT` write ("Unable to process file command 'output' successfully").
	echo "Stripped workspace inheritance from binding crate Cargo.toml" >&2
fi

strip_internal_paths Cargo.toml

# ~keep The workspace lock is a seed, not a formality: it is what keeps this build on
# the same dependency versions as every other job. `cargo generate-lockfile` used to run
# here and threw those pins away, re-resolving everything to latest — which is how a
# broken `zune-core` release reached the PHP job alone while every `--locked` job stayed
# green. Letting cargo update the lock *minimally* instead preserves every pin the
# manifest rewrite did not invalidate.
#
# `--locked` cannot be used with that seed: `strip_internal_paths` above rewrites sibling
# path dependencies into registry ones, so the copied lock legitimately no longer matches
# this manifest and `--locked` would hard-fail. (It was vacuous before anyway, sitting
# directly after a `generate-lockfile` that had just made the lock match by construction.)
if [ -f "$WORKSPACE_ROOT/Cargo.lock" ]; then
	cp "$WORKSPACE_ROOT/Cargo.lock" Cargo.lock
else
	cargo generate-lockfile >&2
fi

cargo update -p time --precise 0.3.47 >&2 || true

# ~keep Every build command sends its stdout to stderr: stdout is this script's value
# channel and the caller reads it straight into `extension-path`.
cargo build --release ${CARGO_FEATURES:+--features "$CARGO_FEATURES"} >&2

mkdir -p "$WORKSPACE_ROOT/target/release"

if [[ "${RUNNER_OS:-}" == "macOS" ]] || [[ "$(uname)" == "Darwin" ]]; then
	cp "$BUILD_TEMP/crate/target/release/lib${LIB_NAME}.dylib" "$WORKSPACE_ROOT/target/release/"
	echo "$WORKSPACE_ROOT/target/release/lib${LIB_NAME}.dylib"
else
	cp "$BUILD_TEMP/crate/target/release/lib${LIB_NAME}.so" "$WORKSPACE_ROOT/target/release/"
	echo "$WORKSPACE_ROOT/target/release/lib${LIB_NAME}.so"
fi
