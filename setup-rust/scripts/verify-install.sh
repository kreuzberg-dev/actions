#!/usr/bin/env bash
set -euo pipefail

target="${1:-}"

echo "Rust toolchain information:"
rustc --version
rustup --version
cargo --version
echo "Available targets:"
if [ -n "$target" ]; then
  rustup target list | grep -E "installed|${target}" | head -5 || true
else
  rustup target list | grep "installed" | head -5 || true
fi
