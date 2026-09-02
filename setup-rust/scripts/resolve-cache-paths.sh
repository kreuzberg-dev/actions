#!/usr/bin/env bash
# Decide which paths the Rust build cache covers, and explain the one exclusion.
#
# `target/` is excluded on macOS. Measured on xberg CI run 33656679479: every
# build, test, doctest and clippy step on macos-latest SUCCEEDED, finishing
# 130 minutes in. The job then spent 24 minutes in the actions/cache POST step
# without finishing and was killed by the 150-minute timeout, so a green run
# was reported as `cancelled`. The same POST step completes in 3.6 minutes on
# ubuntu-latest, 4.2 on ubuntu-24.04-arm and under 2 on windows-latest.
#
# A `--all-features` workspace target/ directory is tens of GB, and macOS
# runners cannot compress and upload one inside a job's lifetime. Raising the
# timeout does not fix this: the build already fits, and the save does not
# converge -- it was still running 24 minutes in with no sign of completing.
#
# Excluding it is affordable because sccache is configured with
# SCCACHE_GHA_ENABLED (see configure-flags.sh), so compiled artifacts are
# already cached through the Actions cache backend independently of this step.
# What is lost is the part sccache does not cover -- build-script output and
# proc-macro expansion -- not the compilation itself.
set -euo pipefail

# shellcheck disable=SC2088 # the tilde is deliberate: these strings are never
# expanded by this shell, they are handed to actions/cache, which does its own
# per-platform expansion. Substituting $HOME here would emit a POSIX path on
# Windows runners, where the cache action expects a Windows one.
paths=(
	"~/.cargo/registry/index"
	"~/.cargo/registry/cache"
	"~/.cargo/git/db"
)

if [ "${RUNNER_OS:-}" = "macOS" ]; then
	echo "macOS: excluding target/ from the build cache (see resolve-cache-paths.sh)"
else
	paths+=("target/")
fi

{
	echo "RUST_CACHE_PATHS<<__XBERG_CACHE_PATHS__"
	printf '%s\n' "${paths[@]}"
	echo "__XBERG_CACHE_PATHS__"
} >>"$GITHUB_ENV"

echo "Rust cache paths:"
printf '  %s\n' "${paths[@]}"
