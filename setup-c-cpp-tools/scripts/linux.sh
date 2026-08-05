#!/usr/bin/env bash
set -euo pipefail

CPPCHECK_VERSION="${CPPCHECK_VERSION:-2.20.0}"
INSTALL_CLANG_FORMAT="${INSTALL_CLANG_FORMAT:-true}"
INSTALL_SHELLCHECK="${INSTALL_SHELLCHECK:-true}"

apt_packages=()
[[ "$INSTALL_SHELLCHECK" == "true" ]] && apt_packages+=(shellcheck)

if ((${#apt_packages[@]} > 0)); then
	sudo apt-get update -qq
	sudo apt-get install -y --no-install-recommends "${apt_packages[@]}"
fi

if [[ "$INSTALL_CLANG_FORMAT" == "true" ]]; then
	"$(dirname "${BASH_SOURCE[0]}")/clang-format.sh"
fi

installed_version=""
if command -v cppcheck >/dev/null 2>&1; then
	installed_version="$(cppcheck --version | awk '{print $2}')"
fi

if [[ "$installed_version" == "$CPPCHECK_VERSION" ]]; then
	echo "cppcheck $CPPCHECK_VERSION already installed."
	exit 0
fi

echo "Building cppcheck $CPPCHECK_VERSION from source (system: ${installed_version:-none})..."
sudo apt-get install -y --no-install-recommends build-essential cmake libpcre3-dev

work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT
cd "$work_dir"

curl -fsSL "https://github.com/danmar/cppcheck/archive/refs/tags/${CPPCHECK_VERSION}.tar.gz" | tar xz
src_dir="cppcheck-${CPPCHECK_VERSION}"

cmake -S "$src_dir" -B "$src_dir/build" \
	-DCMAKE_BUILD_TYPE=Release \
	-DCMAKE_INSTALL_PREFIX=/usr/local \
	-DHAVE_RULES=ON \
	-DUSE_MATCHCOMPILER=Auto

cmake --build "$src_dir/build" -j"$(nproc)"
sudo cmake --install "$src_dir/build"

cppcheck --version
