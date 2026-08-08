#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${script_dir}/retry.sh"

echo "::group::Installing macOS dependencies"

if [[ -d "/opt/homebrew/bin" ]]; then
	export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:${PATH}"
	echo "/opt/homebrew/bin" >>"$GITHUB_PATH"
	echo "/opt/homebrew/sbin" >>"$GITHUB_PATH"
fi
if [[ -d "/usr/local/bin" ]]; then
	export PATH="/usr/local/bin:/usr/local/sbin:${PATH}"
	echo "/usr/local/bin" >>"$GITHUB_PATH"
	echo "/usr/local/sbin" >>"$GITHUB_PATH"
fi

if ! brew list cmake &>/dev/null; then
	echo "Installing CMake..."
	retry_with_backoff brew install cmake || {
		echo "::error::Failed to install CMake after retries"
		exit 1
	}
else
	echo "✓ CMake already installed"
fi

if ! command -v cmake >/dev/null 2>&1; then
	echo "CMake not on PATH after install; attempting brew link..."
	brew link --overwrite cmake >/dev/null 2>&1 || true
fi

if ! brew list tesseract &>/dev/null; then
	echo "Installing Tesseract..."
	retry_with_backoff brew install tesseract || {
		echo "::error::Failed to install Tesseract after retries"
		exit 1
	}
else
	echo "✓ Tesseract already installed"
fi

if ! command -v tesseract >/dev/null 2>&1; then
	echo "Tesseract not on PATH after install; attempting brew link..."
	brew link --overwrite tesseract >/dev/null 2>&1 || true
fi

if ! brew list tesseract-lang &>/dev/null; then
	echo "Installing Tesseract language packs..."
	retry_with_backoff brew install tesseract-lang || {
		echo "::warning::Failed to install tesseract-lang, some languages may be unavailable"
	}
else
	echo "✓ Tesseract language packs already installed"
fi

if ! brew list libmagic &>/dev/null; then
	echo "Installing libmagic..."
	retry_with_backoff brew install libmagic || {
		echo "::warning::Failed to install libmagic after retries"
	}
else
	echo "✓ libmagic already installed"
fi

if ! brew list libheif &>/dev/null; then
	echo "Installing libheif..."
	retry_with_backoff brew install libheif || {
		echo "::warning::Failed to install libheif after retries"
	}
else
	echo "✓ libheif already installed"
fi

if ! brew list boost &>/dev/null; then
	echo "Installing boost (build-time header dep of librevenge + libwpd)..."
	retry_with_backoff brew install boost || {
		echo "::warning::Failed to install boost after retries"
	}
else
	echo "✓ boost already installed"
fi

if ! brew list pkg-config &>/dev/null; then
	echo "Installing pkg-config..."
	retry_with_backoff brew install pkg-config || {
		echo "::error::Failed to install pkg-config after retries"
		exit 1
	}
else
	echo "✓ pkg-config already installed"
fi

# Only install PHP if none is active. When a job has already run
# shivammathur/setup-php (the php-extension build matrix does, per matrix.php),
# an active `php` is on PATH — brew-installing the unversioned `php` formula
# pours the latest (e.g. 8.5) and UNLINKS the matrix-selected keg (php@8.4),
# so ext-php-rs then builds against the wrong PHP. Guard on `command -v php`,
# not `brew list php` (which misses the versioned php@X.Y keg setup-php links),
# mirroring the Windows script. ~keep
if command -v php >/dev/null 2>&1; then
	echo "✓ PHP already active: $(php --version | head -1)"
else
	echo "Installing PHP..."
	retry_with_backoff brew install php || {
		echo "::error::Failed to install PHP after retries"
		exit 1
	}
	command -v php >/dev/null 2>&1 || brew link --overwrite php >/dev/null 2>&1 || true
fi

echo "::endgroup::"

echo "::group::Verifying macOS installations"

echo "CMake:"
if command -v cmake >/dev/null 2>&1; then
	cmake --version | head -1
	CMAKE_FULL_PATH="$(command -v cmake)"
	if [[ -n "$GITHUB_ENV" ]]; then
		echo "CMAKE=$CMAKE_FULL_PATH" >>"$GITHUB_ENV"
		echo "✓ Set CMAKE=$CMAKE_FULL_PATH in GITHUB_ENV"
	fi
	CMAKE_BIN="$(dirname "$CMAKE_FULL_PATH")"
	if [[ -n "$GITHUB_PATH" && -d "$CMAKE_BIN" ]]; then
		echo "$CMAKE_BIN" >>"$GITHUB_PATH"
		echo "✓ Added cmake directory to GITHUB_PATH: $CMAKE_BIN"
	fi
else
	echo "::error::CMake not found on PATH after installation"
	echo "PATH=$PATH"
	brew --prefix cmake 2>/dev/null || true
	exit 1
fi

echo ""
echo "Tesseract:"
if command -v tesseract >/dev/null 2>&1; then
	tesseract --version | head -1
else
	echo "::error::Tesseract not found on PATH after installation"
	echo "PATH=$PATH"
	brew --prefix tesseract 2>/dev/null || true
	exit 1
fi

echo ""
echo "Available languages:"
tesseract --list-langs | head -5

echo ""
echo "pkg-config:"
if command -v pkg-config >/dev/null 2>&1; then
	pkg-config --version
	echo "✓ pkg-config available"
else
	echo "::error::pkg-config not found on PATH after installation"
	echo "PATH=$PATH"
	exit 1
fi

echo ""
echo "PHP:"
if command -v php >/dev/null 2>&1; then
	php --version | head -1
else
	echo "::error::PHP not found on PATH after installation"
	echo "PATH=$PATH"
	exit 1
fi

echo "::endgroup::"
