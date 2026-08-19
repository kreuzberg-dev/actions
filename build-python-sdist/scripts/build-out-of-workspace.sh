#!/bin/bash

set -euo pipefail

INPUT="${1:-}"
OUTPUT_DIR="${2:-.}"
WORKSPACE_ROOT="${3:-.}"

if [ -z "$INPUT" ]; then
	echo "Error: missing input (manifest-path or package-dir)" >&2
	exit 1
fi

BUILD_TEMP=$(mktemp -d)
trap 'rm -rf "$BUILD_TEMP"' EXIT

WORKSPACE_ROOT="$(cd "$WORKSPACE_ROOT" && pwd)"
mkdir -p "$OUTPUT_DIR"

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

if [ -f "$WORKSPACE_ROOT/$INPUT" ]; then
	FULL_MANIFEST_PATH="$WORKSPACE_ROOT/$INPUT"
	PARENT_DIR=$(dirname "$FULL_MANIFEST_PATH")

	cp -r "$PARENT_DIR" "$BUILD_TEMP/crate"
	cd "$BUILD_TEMP/crate"

	echo "Building sdist from manifest: $INPUT"
else
	FULL_PACKAGE_DIR="$WORKSPACE_ROOT/$INPUT"

	if [ ! -d "$FULL_PACKAGE_DIR" ]; then
		echo "Error: input not found at $FULL_PACKAGE_DIR (neither file nor dir)" >&2
		exit 1
	fi

	if [ ! -f "$FULL_PACKAGE_DIR/Cargo.toml" ]; then
		if [ ! -f "$FULL_PACKAGE_DIR/pyproject.toml" ]; then
			echo "Error: $FULL_PACKAGE_DIR has neither Cargo.toml nor pyproject.toml" >&2
			exit 1
		fi
		echo "Split layout detected; isolating $FULL_PACKAGE_DIR + crate into a single-member workspace"
		if [[ ! "$OUTPUT_DIR" =~ ^/ ]]; then
			abs_output_dir="$WORKSPACE_ROOT/$OUTPUT_DIR"
		else
			abs_output_dir="$OUTPUT_DIR"
		fi

		rel_manifest=$(sed -n 's/^[[:space:]]*manifest-path[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' \
			"$FULL_PACKAGE_DIR/pyproject.toml" | head -1)
		if [ -z "$rel_manifest" ]; then
			echo "Error: split layout but no [tool.maturin] manifest-path in $FULL_PACKAGE_DIR/pyproject.toml" >&2
			exit 1
		fi
		CRATE_DIR=$(cd "$FULL_PACKAGE_DIR" && cd "$(dirname "$rel_manifest")" && pwd)

		pkg_rel=$(python3 -c "import os,sys;print(os.path.relpath(sys.argv[1],sys.argv[2]))" "$FULL_PACKAGE_DIR" "$WORKSPACE_ROOT")
		crate_rel=$(python3 -c "import os,sys;print(os.path.relpath(sys.argv[1],sys.argv[2]))" "$CRATE_DIR" "$WORKSPACE_ROOT")

		ISO="$BUILD_TEMP/iso"
		mkdir -p "$ISO/$(dirname "$pkg_rel")" "$ISO/$(dirname "$crate_rel")"
		cp -r "$FULL_PACKAGE_DIR" "$ISO/$pkg_rel"
		cp -r "$CRATE_DIR" "$ISO/$crate_rel"
		strip_internal_paths "$ISO/$crate_rel/Cargo.toml"

		python3 - "$WORKSPACE_ROOT/Cargo.toml" "$ISO/Cargo.toml" "$crate_rel" <<'PY'
import re, sys

src, dst, member = sys.argv[1], sys.argv[2], sys.argv[3]
text = open(src).read()


def section(name):
    m = re.search(r'(?m)^\[' + re.escape(name) + r'\][ \t]*$', text)
    if not m:
        return ''
    start = m.end()
    nxt = re.search(r'(?m)^\[', text[start:])
    return text[start: start + nxt.start()] if nxt else text[start:]


pkg = section('workspace.package')
deps = section('workspace.dependencies')
# Drop `path = "..."` (with any adjacent comma) — the version key remains, so
# inherited internal crates resolve from the registry.
deps = re.sub(r'path[ \t]*=[ \t]*"[^"]*"[ \t]*,[ \t]*', '', deps)
deps = re.sub(r'[ \t]*,?[ \t]*path[ \t]*=[ \t]*"[^"]*"', '', deps)

out = ['[workspace]', 'resolver = "2"', f'members = ["{member}"]', '']
if pkg.strip():
    out += ['[workspace.package]', pkg.strip('\n'), '']
if deps.strip():
    out += ['[workspace.dependencies]', deps.strip('\n'), '']
open(dst, 'w').write('\n'.join(out) + '\n')
PY

		if [ -f "$WORKSPACE_ROOT/Cargo.lock" ]; then
			cp "$WORKSPACE_ROOT/Cargo.lock" "$ISO/Cargo.lock"
		fi
		(cd "$ISO" && (cargo generate-lockfile || {
			rm -f Cargo.lock
			cargo generate-lockfile
		}))

		cd "$ISO/$pkg_rel"
		maturin sdist --out "$abs_output_dir"
		exit 0
	fi

	cp -r "$FULL_PACKAGE_DIR" "$BUILD_TEMP/package"
	cd "$BUILD_TEMP/package"

	echo "Building sdist from package: $INPUT"
fi

if [ -f Cargo.toml ] && grep -q 'workspace = true' Cargo.toml 2>/dev/null; then
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
	echo "Stripped workspace inheritance from binding crate Cargo.toml"
fi

if [ -f "$WORKSPACE_ROOT/Cargo.lock" ]; then
	cp "$WORKSPACE_ROOT/Cargo.lock" Cargo.lock
fi

strip_internal_paths Cargo.toml

cargo generate-lockfile

maturin sdist --out "$OUTPUT_DIR"
