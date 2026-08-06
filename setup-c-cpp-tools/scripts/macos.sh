#!/usr/bin/env bash
set -euo pipefail

CPPCHECK_VERSION="${CPPCHECK_VERSION:-2.20.0}"
INSTALL_CLANG_FORMAT="${INSTALL_CLANG_FORMAT:-true}"
INSTALL_CPPCHECK="${INSTALL_CPPCHECK:-true}"
INSTALL_SHELLCHECK="${INSTALL_SHELLCHECK:-true}"

brew_packages=()
[[ "$INSTALL_CPPCHECK" == "true" ]] && brew_packages+=(cppcheck)
[[ "$INSTALL_SHELLCHECK" == "true" ]] && brew_packages+=(shellcheck)

if ((${#brew_packages[@]} > 0)); then
	brew install "${brew_packages[@]}" || brew upgrade "${brew_packages[@]}"
fi

if [[ "$INSTALL_CLANG_FORMAT" == "true" ]]; then
	"$(dirname "${BASH_SOURCE[0]}")/clang-format.sh"
fi

if [[ "$INSTALL_CPPCHECK" != "true" ]]; then
	exit 0
fi

installed_version="$(cppcheck --version | awk '{print $2}')"
if [[ "$installed_version" != "$CPPCHECK_VERSION" ]]; then
	echo "Warning: brew installed cppcheck $installed_version, expected $CPPCHECK_VERSION" >&2
fi

cppcheck --version
