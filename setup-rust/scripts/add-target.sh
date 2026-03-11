#!/usr/bin/env bash
set -euo pipefail

target="${1:?target required}"
echo "Checking Rust target: $target"

if rustup target list | grep -q "^$target (installed)"; then
  echo "Target $target is already installed"
else
  echo "Installing target: $target"
  rustup target add "$target" || {
    echo "Failed to install target $target"
    echo "Available targets:"
    rustup target list | head -20
    exit 1
  }
  echo "Successfully installed target: $target"
fi

rustup target list | grep "$target"
