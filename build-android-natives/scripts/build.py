#!/usr/bin/env python3
"""Build a Rust crate for Android ABIs using cargo-ndk and stage the libraries.

cargo-ndk copies the crate's own cdylib (lib{crate soname}.so) into
{output-dir}/{abi}/. After building, this verifies that lib{lib-name}.so exists and
is non-empty for every ABI, failing loudly otherwise — so lib-name must match the
crate's [lib] name. No rename is performed (renaming an _ffi lib to _jni would hide
a library that lacks the JNI entry points). See html-to-markdown#446.

Inputs (env vars):
    INPUT_CRATE_NAME: cargo package name (required)
    INPUT_LIB_NAME: expected library base name; must match the crate's [lib] name
        (default = crate-name with - → _)
    INPUT_ABIS: comma-separated Android ABIs (default arm64-v8a,x86_64)
    INPUT_API_LEVEL: Android API level (default 21)
    INPUT_OUTPUT_DIR: staging root (default dist/android-natives)
    INPUT_DRY_RUN: "true" to skip cargo build (default false)
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ABI_TO_RUST_TARGET = {
    "arm64-v8a": "aarch64-linux-android",
    "x86_64": "x86_64-linux-android",
    "x86": "i686-linux-android",
    "armeabi-v7a": "armv7-linux-androideabi",
}


def run_command(cmd: list[str]) -> None:
    print(f"[build-android-natives] Running: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def write_github_output(name: str, value: str) -> None:
    sink = os.environ.get("GITHUB_OUTPUT", "")
    line = f"{name}={value}\n"
    if sink:
        with Path(sink).open("a", encoding="utf-8") as handle:
            handle.write(line)
    else:
        sys.stdout.write(line)


def ensure_input(name: str, value: str) -> str:
    if not value:
        print(f"Error: {name} is required", file=sys.stderr)
        sys.exit(1)
    return value


def verify_staged_libs(output_dir: Path, abis: list[str], lib_name: str) -> None:
    """Fail loudly if cargo-ndk did not stage lib{lib_name}.so for every ABI.

    cargo-ndk copies the built crate's own cdylib soname verbatim, and exits 0 even
    when it copied nothing (e.g. the crate has no android cdylib target). Without
    this check a missing or misnamed library produces a jni-less/wrong-lib AAR that
    only fails at runtime with UnsatisfiedLinkError. See html-to-markdown#446.
    """
    missing = []
    for abi in abis:
        lib_path = output_dir / abi / f"lib{lib_name}.so"
        if not lib_path.is_file() or lib_path.stat().st_size == 0:
            missing.append((abi, lib_path))
    if missing:
        print(
            f"Error: expected lib{lib_name}.so was not staged for: {', '.join(abi for abi, _ in missing)}",
            file=sys.stderr,
        )
        for abi, lib_path in missing:
            abi_dir = lib_path.parent
            found = sorted(p.name for p in abi_dir.glob("*.so")) if abi_dir.is_dir() else []
            print(
                f"  {abi}: missing {lib_path} (found in {abi_dir}: {found or 'nothing'})",
                file=sys.stderr,
            )
        print(
            "Check that crate-name builds an android cdylib and that lib-name matches its [lib] name.",
            file=sys.stderr,
        )
        sys.exit(1)


def main() -> None:
    crate_name = ensure_input("INPUT_CRATE_NAME", os.environ.get("INPUT_CRATE_NAME", ""))
    lib_name = os.environ.get("INPUT_LIB_NAME", "") or crate_name.replace("-", "_")
    abis_str = os.environ.get("INPUT_ABIS", "arm64-v8a,x86_64")
    api_level = os.environ.get("INPUT_API_LEVEL", "21")
    output_dir = Path(os.environ.get("INPUT_OUTPUT_DIR", "") or "dist/android-natives")
    features = os.environ.get("INPUT_FEATURES", "")
    no_default_features = os.environ.get("INPUT_NO_DEFAULT_FEATURES", "false").lower() == "true"
    dry_run = os.environ.get("INPUT_DRY_RUN", "false").lower() == "true"

    abis = [a.strip() for a in abis_str.split(",") if a.strip()]
    if not abis:
        print("Error: no ABIs specified", file=sys.stderr)
        sys.exit(1)

    rust_targets_with_none: list[str | None] = [ABI_TO_RUST_TARGET.get(abi) for abi in abis]
    if None in rust_targets_with_none:
        invalid = [abis[i] for i, t in enumerate(rust_targets_with_none) if t is None]
        print(f"Error: unknown ABIs: {', '.join(invalid)}", file=sys.stderr)
        sys.exit(1)
    rust_targets: list[str] = [t for t in rust_targets_with_none if t is not None]

    if dry_run:
        print("[build-android-natives] dry-run: skipping cargo-ndk build")
        print(f"  crate:     {crate_name}")
        print(f"  lib:       {lib_name}")
        print(f"  abis:      {', '.join(abis)}")
        print(f"  api-level: {api_level}")
        print(f"  output:    {output_dir}")
        for abi, _target in zip(abis, rust_targets, strict=True):
            lib_path = output_dir / abi / f"lib{lib_name}.so"
            print(f"    {abi:12} -> {lib_path}")
        write_github_output("output-dir", str(output_dir.resolve() if output_dir.exists() else output_dir))
        return

    unique_targets = list(dict.fromkeys(rust_targets))
    for target in unique_targets:
        run_command(["rustup", "target", "add", target])

    try:
        subprocess.run(["which", "cargo-ndk"], check=True, capture_output=True)
        print("[build-android-natives] cargo-ndk already installed")
    except subprocess.CalledProcessError:
        print("[build-android-natives] Installing cargo-ndk...")
        run_command(["cargo", "install", "cargo-ndk", "--locked"])

    for abi, _target in zip(abis, rust_targets, strict=True):
        cmd = [
            "cargo",
            "ndk",
            "--target",
            abi,
            "--platform",
            api_level,
            "-o",
            str(output_dir),
            "build",
            "--locked",
            "-p",
            crate_name,
            "--release",
        ]
        if no_default_features:
            cmd.append("--no-default-features")
        if features:
            cmd.extend(["--features", features])
        run_command(cmd)

    verify_staged_libs(output_dir, abis, lib_name)

    print(f"[build-android-natives] staged libraries under: {output_dir.resolve()}")

    write_github_output("output-dir", str(output_dir.resolve()))


if __name__ == "__main__":
    main()
