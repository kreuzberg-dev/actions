#!/usr/bin/env python3
"""Verify a napi-style parent package's declared platform packages are real.

Two failure modes are covered, both observed in production:

1. Pre-publish (``mode: binaries``): ``napi create-npm-dirs`` materialises a
   directory for every entry in ``napi.targets`` regardless of which build legs
   actually ran, so a directory listing looks complete while some directories
   hold no compiled artifact. Every declared platform directory must contain a
   non-empty ``*.node`` and carry the parent's version.
2. Post-publish (``mode: registry``): every package named in the parent's
   ``optionalDependencies`` must resolve on the registry at the parent version,
   not merely a hardcoded subset of them.

The declared set is always read from ``optionalDependencies``; the expected
cardinality from ``napi.targets`` (or the ``expected-count`` override). An empty
declared set, an unmatched glob, or any cardinality/set mismatch is a hard
failure — this script never passes by examining nothing.

Usage (GitHub Actions composite, env vars set by action.yml):
    INPUT_MANIFEST_PATH=crates/foo-node/package.json INPUT_MODE=both python3 verify.py
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import ModuleType

DEFAULT_REGISTRY = "npm"
DEFAULT_MAX_ATTEMPTS = 10
DEFAULT_PLATFORM_SUBDIR = "npm"
BINARY_GLOB = "*.node"
VALID_MODES = ("binaries", "registry", "both")

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2

_WAIT_SCRIPT = Path(__file__).resolve().parents[2] / "wait-for-package" / "scripts" / "wait.py"


def load_wait_module(path: Path = _WAIT_SCRIPT) -> ModuleType:
    """Load the sibling ``wait-for-package`` polling script as a module.

    Registry polling, backoff and per-registry resolution already live there;
    reusing the module keeps one implementation of "is this version live yet".
    """
    if not path.is_file():
        msg = f"wait-for-package script not found at {path}"
        raise SystemExit(msg)
    spec = importlib.util.spec_from_file_location("wait_for_package_wait", path)
    if spec is None or spec.loader is None:
        msg = f"Could not load module spec from {path}"
        raise SystemExit(msg)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_manifest(path: Path) -> dict[str, object]:
    """Read and parse the parent package manifest."""
    if not path.is_file():
        msg = f"Manifest not found: {path}"
        raise SystemExit(msg)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        msg = f"Manifest is not valid JSON ({path}): {exc}"
        raise SystemExit(msg) from exc
    if not isinstance(data, dict):
        msg = f"Manifest must be a JSON object: {path}"
        raise SystemExit(msg)
    return data


def declared_packages(manifest: dict[str, object]) -> list[str]:
    """Return the sorted platform package names from ``optionalDependencies``."""
    optional = manifest.get("optionalDependencies")
    if not isinstance(optional, dict) or not optional:
        return []
    return sorted(str(name) for name in optional)


def napi_target_count(manifest: dict[str, object]) -> int | None:
    """Return the number of entries in ``napi.targets``, or None when absent."""
    napi = manifest.get("napi")
    if not isinstance(napi, dict):
        return None
    targets = napi.get("targets")
    if not isinstance(targets, list):
        return None
    return len(targets)


def discover_platform_dirs(root: Path) -> dict[str, Path]:
    """Map platform package name → directory for every ``*/package.json`` under root."""
    found: dict[str, Path] = {}
    for manifest_path in sorted(root.glob("*/package.json")):
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"::error::Platform manifest is not valid JSON: {manifest_path}")
            continue
        name = data.get("name") if isinstance(data, dict) else None
        if not isinstance(name, str) or not name:
            print(f"::error::Platform manifest has no name: {manifest_path}")
            continue
        found[name] = manifest_path.parent
    return found


def binary_errors(name: str, directory: Path, expected_version: str) -> list[str]:
    """Return the reasons a platform directory does not hold a publishable build."""
    errors: list[str] = []
    binaries = [p for p in sorted(directory.glob(BINARY_GLOB)) if p.is_file() and p.stat().st_size > 0]
    if not binaries:
        errors.append(f"{name}: no non-empty {BINARY_GLOB} in {directory}")

    manifest_path = directory / "package.json"
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"{name}: unreadable {manifest_path}: {exc}")
        return errors

    version = data.get("version") if isinstance(data, dict) else None
    if version != expected_version:
        errors.append(f"{name}: version {version!r} does not match parent version {expected_version!r}")
    return errors


def verify_binaries(declared: list[str], platform_root: Path, expected_version: str) -> tuple[int, list[str]]:
    """Verify every declared platform directory holds a built binary.

    Returns (examined_count, errors). A directory set that does not equal the
    declared set is an error in both directions: a missing directory means a
    build leg never ran, an extra one means the parent will not reference it.
    """
    if not platform_root.is_dir():
        return 0, [f"platform directory not found: {platform_root}"]

    discovered = discover_platform_dirs(platform_root)
    if not discovered:
        return 0, [f"no platform packages found under {platform_root}/*/package.json"]

    errors: list[str] = []
    missing = sorted(set(declared) - set(discovered))
    extra = sorted(set(discovered) - set(declared))
    for name in missing:
        errors.append(f"{name}: declared in optionalDependencies but no directory under {platform_root}")
    for name in extra:
        errors.append(f"{name}: directory under {platform_root} is not declared in optionalDependencies")

    examined = 0
    for name in declared:
        directory = discovered.get(name)
        if directory is None:
            continue
        examined += 1
        errors.extend(binary_errors(name, directory, expected_version))

    print(f"Platform directories examined: {examined} (declared {len(declared)}, discovered {len(discovered)})")
    return examined, errors


def verify_registry(
    declared: list[str],
    version: str,
    registry: str,
    max_attempts: int,
    wait_module: ModuleType,
) -> tuple[int, list[str]]:
    """Verify every declared package resolves on the registry at ``version``.

    Returns (resolved_count, errors).
    """
    resolved = 0
    errors: list[str] = []
    for name in declared:
        found = bool(wait_module.wait_for_package(registry, name, version, max_attempts))
        if found:
            resolved += 1
        else:
            errors.append(f"{name}@{version} did not resolve on {registry}")
    print(f"Registry packages resolved: {resolved}/{len(declared)} on {registry} at {version}")
    return resolved, errors


def write_outputs(values: dict[str, str]) -> None:
    """Append key=value pairs to GITHUB_OUTPUT when running under Actions."""
    out = os.environ.get("GITHUB_OUTPUT")
    if not out:
        return
    with Path(out).open("a", encoding="utf-8") as handle:
        handle.writelines(f"{key}={value}\n" for key, value in values.items())


def resolve_expected_count(manifest: dict[str, object], override: str) -> tuple[int, str]:
    """Resolve the expected platform-package cardinality and its source label."""
    if override:
        try:
            return int(override), "expected-count input"
        except ValueError as exc:
            msg = f"expected-count must be an integer, got: {override!r}"
            raise SystemExit(msg) from exc
    target_count = napi_target_count(manifest)
    if target_count is None:
        msg = "Cannot establish expected platform-package count: manifest has no napi.targets and no expected-count input was given"
        raise SystemExit(msg)
    return target_count, "napi.targets"


def parse_max_attempts(raw: str) -> int:
    """Parse the polling attempt budget, rejecting non-integer and non-positive values."""
    if not raw:
        return DEFAULT_MAX_ATTEMPTS
    try:
        value = int(raw)
    except ValueError as exc:
        msg = f"max-attempts must be an integer, got: {raw!r}"
        raise SystemExit(msg) from exc
    if value < 1:
        msg = f"max-attempts must be >= 1, got: {value}"
        raise SystemExit(msg)
    return value


def run(env: dict[str, str], wait_module: ModuleType) -> int:
    """Execute the verification described by ``env`` and return a process exit code."""
    mode = env.get("INPUT_MODE", "registry").strip() or "registry"
    if mode not in VALID_MODES:
        print(f"::error::Invalid mode: {mode!r} (expected one of {', '.join(VALID_MODES)})")
        return EXIT_USAGE

    manifest_path = Path(env.get("INPUT_MANIFEST_PATH", "").strip())
    if not str(manifest_path):
        print("::error::manifest-path is required")
        return EXIT_USAGE

    manifest = load_manifest(manifest_path)
    parent_name = str(manifest.get("name", ""))
    version = env.get("INPUT_VERSION", "").strip() or str(manifest.get("version", ""))
    if not version:
        print(f"::error::No version given and manifest has none: {manifest_path}")
        return EXIT_USAGE

    declared = declared_packages(manifest)
    expected_count, count_source = resolve_expected_count(manifest, env.get("INPUT_EXPECTED_COUNT", "").strip())

    print(f"::group::Platform package set — {parent_name}@{version}")
    print(f"Declared in optionalDependencies: {len(declared)}")
    for name in declared:
        print(f"  - {name}")
    print(f"Expected count ({count_source}): {expected_count}")
    print("::endgroup::")

    errors: list[str] = []
    if not declared:
        errors.append(f"optionalDependencies is empty or absent in {manifest_path}; nothing would be verified")
    if declared and len(declared) != expected_count:
        errors.append(
            f"cardinality mismatch: {len(declared)} declared optionalDependencies "
            f"vs {expected_count} expected from {count_source}"
        )

    examined = 0
    resolved = 0
    if declared and not errors:
        if mode in ("binaries", "both"):
            configured_root = env.get("INPUT_PLATFORM_DIR", "").strip()
            platform_root = Path(configured_root) if configured_root else manifest_path.parent / DEFAULT_PLATFORM_SUBDIR
            examined, binary_problems = verify_binaries(declared, platform_root, version)
            errors.extend(binary_problems)
            if examined != len(declared):
                errors.append(f"examined {examined} platform directories but {len(declared)} are declared")
        if mode in ("registry", "both"):
            max_attempts = parse_max_attempts(env.get("INPUT_MAX_ATTEMPTS", "").strip())
            registry = env.get("INPUT_REGISTRY", "").strip() or DEFAULT_REGISTRY
            resolved, registry_problems = verify_registry(declared, version, registry, max_attempts, wait_module)
            errors.extend(registry_problems)
            if resolved != len(declared):
                errors.append(f"resolved {resolved} packages but {len(declared)} are declared")

    print(f"::group::Verification summary — {parent_name}@{version} (mode: {mode})")
    print(f"Declared: {len(declared)}")
    print(f"Expected: {expected_count}")
    print(f"Examined (platform directories): {examined}")
    print(f"Resolved (registry): {resolved}")
    print(f"Errors: {len(errors)}")
    for problem in errors:
        print(f"  - {problem}")
    print("::endgroup::")

    write_outputs(
        {
            "declared-count": str(len(declared)),
            "expected-count": str(expected_count),
            "examined-count": str(examined),
            "resolved-count": str(resolved),
            "packages": ",".join(declared),
        }
    )

    if errors:
        for problem in errors:
            print(f"::error::{problem}")
        print(f"::error::Platform package verification failed with {len(errors)} problem(s)")
        return EXIT_FAILED

    print(f"Verified {len(declared)} platform package(s) for {parent_name}@{version}")
    return EXIT_OK


def main() -> int:
    """Entry point: run the verification against the process environment."""
    try:
        return run(dict(os.environ), load_wait_module())
    except SystemExit as exc:
        message = exc.code if isinstance(exc.code, str) else "verification aborted"
        print(f"::error::{message}")
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
