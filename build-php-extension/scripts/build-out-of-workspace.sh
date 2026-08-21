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

# ~keep The crate is built from a copy placed outside the workspace, so every
# `workspace = true` in its manifest points at a root cargo can no longer find
# ("failed to find a workspace root"). Inherited keys are replaced with the workspace's
# concrete values rather than deleted, because `version`, `edition` and `license` are
# required for the package to parse at all. Three spellings are recognised: the dotted
# form (`version.workspace = true`, what cargo and alef emit), the inline-table form
# (`version = { workspace = true }`), and the bare form under a table such as `[lints]`,
# which has no key to resolve and is dropped.
deinherit_workspace() {
	python3 - "$1" "$2" <<'PY'
import os, re, sys

crate_manifest, workspace_manifest = sys.argv[1], sys.argv[2]

# `readme` and `license-file` name files that live beside the workspace manifest and are
# not copied into the out-of-workspace build dir, so inheriting them would point cargo at
# paths that do not exist. They are publish-only metadata; drop them instead.
PATH_VALUED_PACKAGE_KEYS = {'readme', 'license-file'}

HEADER = re.compile(r'\s*\[([^\]]+)\]\s*$')
COMMENT = re.compile(r'\s*#')
ASSIGNMENT = re.compile(r'\s*([A-Za-z0-9_.-]+)\s*=\s*(\S.*?)\s*$')
DOTTED_INHERIT = re.compile(r'\s*([A-Za-z0-9_-]+)\s*\.\s*workspace\s*=\s*true\s*$')
INLINE_INHERIT = re.compile(r'\s*([A-Za-z0-9_-]+)\s*=\s*\{\s*workspace\s*=\s*true\s*,?\s*\}\s*$')
BARE_INHERIT = re.compile(r'\s*workspace\s*=\s*true\s*$')
ANY_INHERIT = re.compile(r'workspace\s*=\s*true')
DEPENDENCY_TABLE = re.compile(r'(^|\.)(build-|dev-)?dependencies$')


def read_table(path, name):
    values = {}
    if not os.path.exists(path):
        return values
    in_table = False
    with open(path, encoding='utf-8') as handle:
        for raw in handle:
            line = raw.rstrip('\n')
            header = HEADER.match(line)
            if header:
                in_table = header.group(1).strip() == name
                continue
            if not in_table or COMMENT.match(line):
                continue
            assignment = ASSIGNMENT.match(line)
            if assignment:
                values[assignment.group(1)] = assignment.group(2)
    return values


package_values = read_table(workspace_manifest, 'workspace.package')
dependency_values = read_table(workspace_manifest, 'workspace.dependencies')

section = ''
out = []
with open(crate_manifest, encoding='utf-8') as handle:
    for raw in handle:
        line = raw.rstrip('\n')
        header = HEADER.match(line)
        if header:
            section = header.group(1).strip()
            out.append(line)
            continue
        # Comments are copied verbatim and never inspected: alef-generated manifests carry
        # prose that mentions `workspace = true`, and reading that as inheritance would
        # fail the build on a comment.
        if COMMENT.match(line):
            out.append(line)
            continue

        dotted = DOTTED_INHERIT.match(line)
        inline = INLINE_INHERIT.match(line)
        key = dotted.group(1) if dotted else (inline.group(1) if inline else None)
        if key is None:
            if BARE_INHERIT.match(line):
                continue
            if ANY_INHERIT.search(line):
                sys.exit("error: cannot de-inherit '%s' in %s: unsupported workspace "
                         "inheritance form" % (line.strip(), crate_manifest))
            out.append(line)
            continue

        if DEPENDENCY_TABLE.search(section):
            if key not in dependency_values:
                sys.exit("error: dependency '%s' inherits from the workspace but "
                         "[workspace.dependencies] in %s has no entry for it"
                         % (key, workspace_manifest))
            out.append('%s = %s' % (key, dependency_values[key]))
        elif key in PATH_VALUED_PACKAGE_KEYS:
            continue
        elif key in package_values:
            out.append('%s = %s' % (key, package_values[key]))

with open(crate_manifest, 'w', encoding='utf-8') as handle:
    handle.write('\n'.join(out) + '\n')
PY
}

cp -r "$CRATE_DIR" "$BUILD_TEMP/crate"
cd "$BUILD_TEMP/crate"

deinherit_workspace Cargo.toml "$WORKSPACE_ROOT/Cargo.toml"
# ~keep Progress goes to stderr: this script's stdout is captured verbatim into
# `extension-path`, and a second line there makes the runner reject the whole
# `$GITHUB_OUTPUT` write ("Unable to process file command 'output' successfully").
echo "Resolved workspace inheritance in binding crate Cargo.toml" >&2

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
