#!/usr/bin/env bash
set -euo pipefail

# ~keep clang-format's output gates `poly fmt --check`, so an unpinned install makes formatting
# non-deterministic across machines. apt ships 18 on Ubuntu while brew ships 22 on macOS, and 18
# misformats C# nullable types (`object? x` -> `object ? x`), so the same tree passed locally and
# failed in CI. The PyPI wheel is the only source that gives every platform the same binary.
CLANG_FORMAT_VERSION="${CLANG_FORMAT_VERSION:?clang-format version required}"

if command -v clang-format >/dev/null 2>&1; then
	installed="$(clang-format --version | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)"
	if [[ "$installed" == "$CLANG_FORMAT_VERSION" ]]; then
		echo "clang-format $CLANG_FORMAT_VERSION already installed."
		exit 0
	fi
fi

venv_dir="${RUNNER_TEMP:-/tmp}/clang-format-venv"

# ~keep A venv sidesteps PEP 668 ("externally-managed-environment"), which rejects both a plain
# and a --user pip install against the runners' system python.
#
# ~keep uv is preferred because `python3 -m venv` needs ensurepip, which some runner images'
# system python does not ship — it fails with "you need to install the python3-venv package",
# which is how this script took down callers that had not separately set up Python. uv creates
# the venv without ensurepip and fetches its own interpreter if none is suitable. action.yml
# installs uv, so the fallback only applies when the script is run directly.
if command -v uv >/dev/null 2>&1; then
	uv venv --quiet "$venv_dir"
	uv pip install --quiet --python "$venv_dir/bin/python" "clang-format==${CLANG_FORMAT_VERSION}"
else
	python3 -m venv "$venv_dir"
	"$venv_dir/bin/pip" install --quiet --disable-pip-version-check "clang-format==${CLANG_FORMAT_VERSION}"
fi

echo "$venv_dir/bin" >>"$GITHUB_PATH"
"$venv_dir/bin/clang-format" --version
