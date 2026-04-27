#!/usr/bin/env python3
"""Build a Rust FFI library via cargo and emit outputs to GITHUB_OUTPUT."""

import dataclasses
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

# Cargo and rustc emit utf-8 (build-script author names, diagnostics with non-ascii
# identifiers, etc.). On Windows runners sys.stdout/stderr default to cp1252 which
# crashes on the first non-latin1 byte we forward via print().
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

_TAIL_LINES = 50


@dataclasses.dataclass(frozen=True)
class BuildConfig:
    """All configuration for a single cargo FFI build."""

    crate_name: str
    features: str
    target: str
    build_profile: str
    verbose: bool
    additional_flags: str
    manifest_path: str
    disable_sccache: bool
    cargo_target_dir: str
    openssl_dir: str

    @classmethod
    def from_env(cls) -> "BuildConfig":
        """Construct a BuildConfig by reading environment variables."""
        env = os.environ
        return cls(
            crate_name=env.get("CRATE_NAME", ""),
            features=env.get("FEATURES", ""),
            target=env.get("TARGET", ""),
            build_profile=env.get("BUILD_PROFILE", "release"),
            verbose=env.get("VERBOSE", "true").lower() == "true",
            additional_flags=env.get("ADDITIONAL_FLAGS", ""),
            manifest_path=env.get("MANIFEST_PATH", ""),
            disable_sccache=env.get("DISABLE_SCCACHE", "true").lower() == "true",
            cargo_target_dir=env.get("CARGO_TARGET_DIR", ""),
            openssl_dir=env.get("OPENSSL_DIR", ""),
        )


def validate_inputs(crate_name: str, manifest_path: str) -> None:
    """Validate build inputs before invoking cargo.

    Raises SystemExit with a non-zero code on validation failure.
    """
    print("=== Validating FFI build inputs ===")
    print(f"Crate: {crate_name}")

    if manifest_path:
        if not Path(manifest_path).is_file():
            print(f"Error: manifest-path '{manifest_path}' does not exist", file=sys.stderr)
            raise SystemExit(1)
        print(f"Manifest: {manifest_path}")
    elif Path(f"crates/{crate_name}/Cargo.toml").is_file():
        print(f"Found crate at crates/{crate_name}/")
    else:
        print(
            f"Error: Crate '{crate_name}' not found at crates/{crate_name}/Cargo.toml",
            file=sys.stderr,
        )
        print("Hint: Use manifest-path input for non-standard crate locations", file=sys.stderr)
        raise SystemExit(1)

    print("Validation passed")


def build_cargo_args(
    *,
    crate_name: str,
    manifest_path: str,
    build_profile: str,
    features: str,
    target: str,
    verbose: bool,
    additional_flags: str,
) -> list[str]:
    """Construct the cargo build argument list from build parameters."""
    args: list[str] = ["build"]

    if manifest_path:
        args += ["--manifest-path", manifest_path]
    else:
        args += ["--package", crate_name]

    if build_profile == "release":
        args.append("--release")

    if features:
        args += ["--features", features]

    if target:
        args += ["--target", target]

    if verbose:
        args.append("-vv")

    if additional_flags:
        args += shlex.split(additional_flags)

    return args


def find_library(target_dir: Path, crate_name: str) -> Path | None:
    """Search for the compiled library artifact in target_dir.

    Returns the Path of the first match against the canonical naming patterns,
    or falls back to any .so/.dylib/.dll/.a file present. Returns None if nothing
    is found.
    """
    lib_stem = crate_name.replace("-", "_")
    candidates = [
        target_dir / f"lib{lib_stem}.so",
        target_dir / f"lib{lib_stem}.dylib",
        target_dir / f"{lib_stem}.dll",
        target_dir / f"lib{lib_stem}.a",
    ]

    for candidate in candidates:
        if candidate.is_file():
            return candidate

    # Fallback: first library file of any known extension
    for extension in [".so", ".dylib", ".dll", ".a"]:
        matches = list(target_dir.glob(f"*{extension}"))
        if matches:
            return matches[0]

    return None


def diagnose_build_failure(log_content: str) -> None:
    """Print diagnostic information extracted from a failed build log."""
    lines = log_content.splitlines()
    tail = lines[-_TAIL_LINES:] if len(lines) > _TAIL_LINES else lines
    print("Last 50 lines of build output:")
    print("\n".join(tail))
    print()
    print("Checking for common errors:")

    link_errors = [line for line in lines if "link" in line.lower() and "error" in line.lower()]
    if link_errors:
        for line in link_errors[:5]:
            print(line)
        print("Linking errors detected. Check library paths and dependencies.")

    missing_dep_lines = [line for line in lines if "could not find" in line.lower()]
    if missing_dep_lines:
        for line in missing_dep_lines[:5]:
            print(line)
        print("Missing dependencies detected.")

    openssl_errors = [line for line in lines if "openssl" in line.lower() and "error" in line.lower()]
    if openssl_errors:
        for line in openssl_errors[:5]:
            print(line)
        print("OpenSSL errors detected. Verify OPENSSL_DIR is set correctly.")


def _print_build_environment(config: BuildConfig) -> None:
    """Print build tool versions and relevant environment settings."""
    rust_ver = subprocess.run(
        ["rustc", "--version"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    cargo_ver = subprocess.run(
        ["cargo", "--version"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    print(f"Rust version: {rust_ver}")
    print(f"Cargo version: {cargo_ver}")
    print(f"Working directory: {Path.cwd()}")
    print(f"CARGO_TARGET_DIR: {config.cargo_target_dir or '<not set>'}")
    if config.target:
        print(f"Target: {config.target}")
    if config.openssl_dir:
        print(f"OPENSSL_DIR: {config.openssl_dir}")


def _build_env(config: BuildConfig) -> dict[str, str]:
    """Return a modified copy of the environment with sccache disabled if requested."""
    env = dict(os.environ)
    if config.disable_sccache:
        env["RUSTC_WRAPPER"] = ""
        env["CARGO_BUILD_RUSTC_WRAPPER"] = ""
        env["SCCACHE_GHA_ENABLED"] = "false"
    return env


def _run_cargo_build(cargo_args: list[str], build_env: dict[str, str]) -> None:
    """Run cargo with the given args, streaming output to stdout.

    Raises SystemExit(1) on build failure.
    """
    log_lines: list[str] = []

    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as log_file:
        log_path = Path(log_file.name)

    try:
        with subprocess.Popen(
            ["cargo", *cargo_args],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=build_env,
        ) as proc:
            assert proc.stdout is not None  # noqa: S101
            for line in proc.stdout:
                print(line, end="")
                log_lines.append(line)

        log_content = "".join(log_lines)
        log_path.write_text(log_content)
    finally:
        log_path.unlink(missing_ok=True)

    if proc.returncode != 0:
        print()
        print("=== Build Failed ===")
        print(f"Command: cargo {' '.join(cargo_args)}")
        print()
        diagnose_build_failure(log_content)
        raise SystemExit(1)


def _full_target_dir(config: BuildConfig) -> Path:
    """Compute the cargo output directory for the given build configuration."""
    base = config.cargo_target_dir or "target"
    target_subdir = f"{config.target}/" if config.target else ""
    profile_dir = "release" if config.build_profile == "release" else "debug"
    return Path(base) / f"{target_subdir}{profile_dir}"


def _report_library(found_lib: Path | None, target_dir: Path) -> None:
    """Print the found library path and size, or list fallback candidates."""
    if found_lib is not None:
        print(f"Found library: {found_lib}")
        size_kb = found_lib.stat().st_size / 1024
        print(f"  size: {size_kb:.1f}K")
        return

    print(f"Could not find expected library artifact. Listing library files in {target_dir}:")
    if not target_dir.is_dir():
        print(f"Directory does not exist: {target_dir}")
        return

    all_libs: list[Path] = []
    for extension in [".so", ".dylib", ".dll", ".a"]:
        all_libs.extend(target_dir.glob(f"*{extension}"))

    if all_libs:
        for lib in all_libs:
            print(f"  {lib}")
    else:
        print(f"No library files found in {target_dir}")


def _write_github_output(found_lib: Path | None, target_dir: Path) -> None:
    """Write library-path and target-dir to GITHUB_OUTPUT (or stdout if unset)."""
    lib_str = str(found_lib) if found_lib is not None else ""
    github_output = os.environ.get("GITHUB_OUTPUT", "")
    if github_output:
        with Path(github_output).open("a") as output_file:
            output_file.write(f"library-path={lib_str}\n")
            output_file.write(f"target-dir={target_dir}\n")
    else:
        print(f"library-path={lib_str}")
        print(f"target-dir={target_dir}")


def main() -> None:
    """Orchestrate validation, cargo build, artifact discovery, and output writing."""
    validate_only = "--validate-only" in sys.argv

    config = BuildConfig.from_env()

    if not config.crate_name:
        print("Error: CRATE_NAME is required", file=sys.stderr)
        raise SystemExit(1)

    validate_inputs(config.crate_name, config.manifest_path)

    if validate_only:
        return

    print("=== Building Rust FFI library ===")

    cargo_args = build_cargo_args(
        crate_name=config.crate_name,
        manifest_path=config.manifest_path,
        build_profile=config.build_profile,
        features=config.features,
        target=config.target,
        verbose=config.verbose,
        additional_flags=config.additional_flags,
    )

    print(f"Build command: cargo {' '.join(cargo_args)}")
    print()
    print("=== Build Environment ===")
    _print_build_environment(config)
    print()

    _run_cargo_build(cargo_args, _build_env(config))

    target_dir = _full_target_dir(config)

    print()
    print("=== Build Successful ===")
    print(f"Target directory: {target_dir}")
    print()

    found_lib = find_library(target_dir, config.crate_name)
    _report_library(found_lib, target_dir)
    _write_github_output(found_lib, target_dir)

    print()
    print("=== FFI Build Complete ===")


if __name__ == "__main__":
    main()
