#!/usr/bin/env bash
set -euo pipefail

target="${1:?target required}"
configure_musl_cc="${2:-true}"
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

if [[ "$target" == *"-unknown-linux-musl" ]] && [[ "$RUNNER_OS" == "Linux" ]]; then
	# ~keep cargo-zigbuild and cargo-xwin set CC_<target>/CARGO_TARGET_<TARGET>_LINKER with
	# add_env_if_missing, so anything exported here wins and silently disables the zig
	# cross-compile the caller asked for. Callers building through zig opt out.
	if [[ "$configure_musl_cc" != "true" ]]; then
		echo "configure-musl-cc=false; leaving CC/linker unset for $target (zig or another cross toolchain owns them)"
		exit 0
	fi

	# ~keep musl-gcc is a wrapper around the host gcc and only ever emits host-arch objects.
	# Exporting it for a foreign-arch target does not cross-compile, it just shadows the
	# toolchain that could have.
	host_arch=$(uname -m)
	target_arch="${target%%-*}"
	if [[ "$target_arch" != "$host_arch" ]]; then
		echo "::warning::musl-gcc cannot target $target_arch from a $host_arch runner; leaving CC/linker unset. Cross-compile with cargo-zigbuild or a target-specific toolchain."
		exit 0
	fi

	echo "Installing musl-tools for target: $target"
	sudo apt-get update && sudo apt-get install -y musl-tools

	cc_rs_var=$(echo "$target" | tr '-' '_')

	echo "Configuring cc-rs environment variables for musl target"
	{
		echo "CC_${cc_rs_var}=musl-gcc"
		echo "AR_${cc_rs_var}=ar"
		echo "CARGO_TARGET_${cc_rs_var^^}_LINKER=musl-gcc"
	} >>"$GITHUB_ENV"

	echo "Set CC_${cc_rs_var}=musl-gcc"
	echo "Set AR_${cc_rs_var}=ar"
	echo "Set CARGO_TARGET_${cc_rs_var^^}_LINKER=musl-gcc"
fi
