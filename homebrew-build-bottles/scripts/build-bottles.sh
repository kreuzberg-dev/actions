#!/usr/bin/env bash
set -euo pipefail

tag="${TAG:?TAG is required}"
version="${VERSION:?VERSION is required}"
tap="${TAP:?TAP is required (e.g. xberg-io/tap)}"
formulas_raw="${FORMULAS:?FORMULAS is required (newline-separated list)}"
out_dir="${OUT_DIR:?OUT_DIR is required}"
github_repo="${GITHUB_REPO:?GITHUB_REPO is required (e.g. xberg-io/foo)}"
# When "false", stage the renamed tarball into OUT_DIR instead of uploading it here.
# A from-source bottle build can outlast the 1h GitHub App token TTL, so the caller
# uploads afterwards with a freshly minted token rather than the one this build started
# with (that stale-token 401 is what failed the rc.36 sequoia leg). Default "true" keeps
# the self-contained behavior for other callers. ~keep
upload="${UPLOAD:-true}"

# Homebrew 6.0.13 regressed `brew install --build-bottle` on Linux: the keg builds
# (🍺 prints) but the process then exits 1 with the underlying error swallowed, which
# aborts this script under `set -e` before `brew bottle` runs. 6.0.12 was the last
# green Linux bottle build, whereas 6.0.13 fails it (seen on crawlberg v1.0.11). macOS
# is unaffected, so we pin only the Linux leg. Override via LINUX_BREW_PIN if needed.
linux_brew_pin="${LINUX_BREW_PIN:-6.0.12}"

mkdir -p "$out_dir"
work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT
cd "$work_dir"

echo "::group::brew env"
set +o pipefail
brew --version
brew config | head -20 || true
set -o pipefail
echo "::endgroup::"

echo "::group::Tap ${tap}"
export HOMEBREW_NO_INSTALL_FROM_API=1
if [[ "${RUNNER_OS:-}" == "Linux" ]]; then
	# Pin to the last-known-good brew instead of updating to latest (see linux_brew_pin).
	brew_repo="$(brew --repository)"
	git -C "$brew_repo" fetch --force --tags origin "refs/tags/${linux_brew_pin}:refs/tags/${linux_brew_pin}"
	git -C "$brew_repo" -c advice.detachedHead=false checkout --force --quiet "$linux_brew_pin"
	export HOMEBREW_NO_AUTO_UPDATE=1
	echo "Pinned Linux Homebrew to ${linux_brew_pin}: $(brew --version | head -1)"
else
	brew update --quiet || true
fi
export HOMEBREW_NO_SANDBOX_LINUX=1
brew tap "$tap"
brew trust "$tap" || echo "warning: brew trust unavailable; relying on env-var bypass"
echo "::endgroup::"

normalize_tapped_formula() {
	local formula="$1"
	local repo formula_file
	repo="$(brew --repository "$tap" 2>/dev/null)" || return 0
	for formula_file in "${repo}/Formula/${formula}.rb" "${repo}/${formula}.rb"; do
		[[ -f "$formula_file" ]] || continue
		python3 - "$formula_file" <<'PYEOF'
import re
import sys

path = sys.argv[1]
with open(path) as fh:
    content = fh.read()

bottle_re = re.compile(r"^[ \t]*bottle do\b.*?^[ \t]*end(?:\n|\Z)", re.MULTILINE | re.DOTALL)
stripped = bottle_re.sub("", content)
stripped = re.sub(r"\n{3,}", "\n\n", stripped)

if stripped != content:
    with open(path, "w") as fh:
        fh.write(stripped)
    sys.stderr.write(f"normalize_tapped_formula: stripped stale bottle block(s) from {path}\n")
PYEOF
		return 0
	done
}

retry() {
	local -r max_attempts=5
	local attempt=1
	local delay=5
	local status=0
	while true; do
		"$@" && return 0
		status=$?
		if ((attempt >= max_attempts)); then
			echo "ERROR: command failed after ${max_attempts} attempts (exit ${status}): $*" >&2
			return "$status"
		fi
		echo "warning: attempt ${attempt}/${max_attempts} failed (exit ${status}); retrying in ${delay}s: $*" >&2
		sleep "$delay"
		attempt=$((attempt + 1))
		delay=$((delay * 2))
	done
}

build_one_bottle() {
	local formula="$1"
	echo "::group::Building bottle for ${formula}"

	brew uninstall --force "${tap}/${formula}" 2>/dev/null || true

	normalize_tapped_formula "$formula"

	if brew list libheif &>/dev/null; then
		local libheif_prefix
		libheif_prefix="$(brew --prefix libheif)"
		export PKG_CONFIG_PATH="${libheif_prefix}/lib/pkgconfig${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}"
	fi

	brew install --build-bottle --verbose "${tap}/${formula}"

	brew bottle --json --no-rebuild "${tap}/${formula}"

	local original_tarball
	shopt -s nullglob
	local tarballs=("${formula}--${version}".*.bottle.tar.gz)
	shopt -u nullglob
	if [[ ${#tarballs[@]} -eq 0 ]]; then
		echo "ERROR: no bottle tarball produced for ${formula}" >&2
		ls -la
		return 1
	fi
	original_tarball="${tarballs[0]}"

	local renamed_tarball="${original_tarball/--/-}"
	if [[ "$renamed_tarball" != "$original_tarball" ]]; then
		cp "$original_tarball" "$renamed_tarball"
	fi

	shopt -s nullglob
	local json_files=("${formula}--${version}".*.bottle.json)
	shopt -u nullglob
	for jf in "${json_files[@]}"; do
		cp "$jf" "$out_dir/"
	done

	# Always stage the tarball so the caller can upload it (with a fresh token) even
	# when we don't upload here.
	cp "$renamed_tarball" "$out_dir/"

	if [[ "$upload" == "true" ]]; then
		echo "Uploading ${renamed_tarball} to release ${tag}"
		retry gh release upload "$tag" "$renamed_tarball" --clobber --repo "$github_repo" </dev/null
	else
		echo "UPLOAD=false: staged ${renamed_tarball} in ${out_dir} for caller-side upload"
	fi

	echo "::endgroup::"
}

while IFS= read -r formula <&3; do
	formula="${formula// /}"
	[[ -z "$formula" ]] && continue
	build_one_bottle "$formula"
done 3<<<"$formulas_raw"

echo "Bottles built; JSON manifests saved to ${out_dir}:"
ls -la "$out_dir"
