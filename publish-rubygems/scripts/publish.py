#!/usr/bin/env python3
"""Publish RubyGems packages from a directory.

Usage (GitHub Actions via env vars):
    INPUT_GEMS_DIR=dist/gems/ python3 publish.py
"""

import os
import re
import subprocess
import sys
from pathlib import Path

ALREADY_PUBLISHED_PATTERN = re.compile(
    r"repushing.*not allowed|already been pushed",
    re.IGNORECASE,
)

# ~keep A gem filename is `<name>-<version>[-<platform>].gem` and both halves may contain hyphens:
# a hyphenated gem name is legal (`my-gem-1.2.3.gem`), and rb_sys cross-compiles platform gems
# (`liter_llm-1.19.0-x86_64-linux.gem`). The version is therefore anchored as the last
# hyphen-delimited run starting with a digit, optionally followed by a platform tag, which always
# starts with a letter. Matching the plain form first keeps a plain gem from being read as a
# platform gem.
_GEM_FILENAME_RE = re.compile(r"^(?P<name>.+)-(?P<version>\d[0-9A-Za-z.]*)\.gem$")
_PLATFORM_GEM_FILENAME_RE = re.compile(
    r"^(?P<name>.+)-(?P<version>\d[0-9A-Za-z.]*)-(?P<platform>[A-Za-z][0-9A-Za-z._-]*)\.gem$"
)


def is_already_published(output: str) -> bool:
    """Return True if the gem push output indicates the gem was already published."""
    return bool(ALREADY_PUBLISHED_PATTERN.search(output))


def parse_gem_version(filename: str) -> str | None:
    """Return the version encoded in a `<name>-<version>[-<platform>].gem` filename, or None."""
    for pattern in (_GEM_FILENAME_RE, _PLATFORM_GEM_FILENAME_RE):
        if match := pattern.match(filename):
            return match["version"]
    return None


def validate_gem_structure(path: Path) -> bool:
    """Return True if path is a non-empty, readable gem with valid structure.

    On `gem spec` failure, surface stderr to the GitHub Actions log so the
    underlying cause (corrupt archive, missing metadata, gem command issue,
    etc.) is visible — otherwise the caller only sees a generic
    "invalid gem structure" with no diagnostic detail.
    """
    if not path.is_file() or not os.access(path, os.R_OK) or path.stat().st_size == 0:
        print(f"  Diagnostic: {path.name} is missing/unreadable/empty", file=sys.stderr)
        return False
    result = subprocess.run(["gem", "spec", str(path)], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        print(
            f"  Diagnostic: `gem spec {path.name}` exited with code {result.returncode}",
            file=sys.stderr,
        )
        if result.stderr.strip():
            print(f"    stderr: {result.stderr.strip()[:500]}", file=sys.stderr)
        if result.stdout.strip():
            print(f"    stdout (first 200 chars): {result.stdout.strip()[:200]}", file=sys.stderr)
        return False
    return True


def find_gem_files(directory: Path) -> list[Path]:
    """Return all *.gem files in directory or subdirectories.

    GitHub Actions download-artifact with merge-multiple: true creates nested
    directory structure (dist/rubygems-{label}/*.gem), so we search recursively.
    """
    return sorted(directory.rglob("*.gem"))


def _run(cmd: list[str], env: dict[str, str] | None = None) -> tuple[int, str]:
    result = subprocess.run(cmd, capture_output=True, text=True, check=False, env=env)
    return result.returncode, result.stdout + result.stderr


def _resolve_push_key() -> str:
    """Return the rubygems push API key from the env, or empty string.

    `gem push` reads `GEM_HOST_API_KEY`. When the caller's workflow sets
    `GEM_HOST_API_KEY` at step-level via an empty secret, that empty value
    shadows whatever `rubygems/configure-rubygems-credentials` wrote via
    `core.exportVariable`. We recover the credential from `BUNDLE_GEM__PUSH_KEY`
    (also exported by configure-rubygems-credentials and not overridden by the
    caller's step env), with `RUBYGEMS_API_KEY` as a third fallback.
    """
    for var in ("GEM_HOST_API_KEY", "BUNDLE_GEM__PUSH_KEY", "RUBYGEMS_API_KEY"):
        value = os.environ.get(var, "").strip()
        if value:
            return value
    return ""


def normalize_release_version(version: str) -> str:
    """Strip whitespace and a leading `v` so a tag (`v1.19.0`) compares to a gem filename version."""
    return version.strip().removeprefix("v")


def assert_gems_match_release(gem_files: list[Path], expected_version: str) -> None:
    """Fail before any push when a gem carries a version other than the release being published.

    ~keep This guard is what makes the `is_already_published` skip below safe, and the two must
    not be collapsed. Skipping is legitimate ONLY when the gem's version IS the release version
    (an idempotent re-run); it is a silent data-loss bug when the gem is stale.
    This exact shape shipped two broken releases on sibling registries: tree-sitter-language-pack
    v1.16.0 on npm and liter-llm v1.19.0 on npm and PyPI each published a stale artifact, matched
    the registry's already-published response, and reported success having shipped nothing for the
    tag. publish-rubygems had the same unguarded skip; the guard is here so it never gets a turn.

    ~keep Runs as a pre-flight over every gem rather than inline per push because RubyGems refuses
    to repush a version: a stale gem caught halfway through has already pushed the gems ahead of
    it, and those cannot be corrected afterwards.
    """
    parsed = [(gem.name, parse_gem_version(gem.name)) for gem in gem_files]

    # ~keep An unparseable filename fails rather than warns: it is exactly the blind spot the
    # guard exists to close, since an unverifiable gem is indistinguishable from a stale one.
    unparseable = sorted(name for name, version in parsed if version is None)
    if unparseable:
        print(
            f"Error: expected-version {expected_version} was supplied but no version could be "
            f"parsed from {', '.join(unparseable)}, so the gem(s) cannot be verified",
            file=sys.stderr,
        )
        sys.exit(1)

    mismatched = sorted(f"{name} carries {version}" for name, version in parsed if version != expected_version)
    if mismatched:
        print(
            f"Error: gem(s) carry a version other than the release version {expected_version}: {'; '.join(mismatched)}",
            file=sys.stderr,
        )
        print(
            "The built gems are stale. Publishing them would ship the wrong version, or be "
            "silently swallowed as an 'already published' skip.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Verified {len(parsed)} gem(s) carry the release version {expected_version}")


def warn_expected_version_missing() -> None:
    """Warn that the stale-artifact guard is disabled because no expected-version was supplied."""
    print(
        "::warning::publish-rubygems was invoked without `expected-version`; a stale gem cannot "
        "be detected and RubyGems' 'has already been pushed' response will be treated as an "
        "idempotent skip. Pass the release version from the caller to close this gap."
    )


def verify_release_versions(gem_files: list[Path], raw_expected_version: str) -> None:
    """Apply the stale-artifact guard, or warn loudly that it has been left disabled.

    ~keep Called before the credential resolution and before the dry-run branch on purpose: a dry
    run exists to catch a stale build ahead of the real release, so it must apply the same
    assertion the real release does.
    """
    expected_version = normalize_release_version(raw_expected_version)
    if expected_version:
        assert_gems_match_release(gem_files, expected_version)
    else:
        warn_expected_version_missing()


def build_push_env(dry_run: bool) -> dict[str, str] | None:
    """Return the environment for `gem push`, or None for a dry run.

    Exits with status 1 when a real push has no credential available.
    """
    if dry_run:
        return None
    push_key = _resolve_push_key()
    if not push_key:
        print(
            "Error: no rubygems push credential available "
            "(GEM_HOST_API_KEY/BUNDLE_GEM__PUSH_KEY/RUBYGEMS_API_KEY all empty)",
            file=sys.stderr,
        )
        sys.exit(1)
    return {**os.environ, "GEM_HOST_API_KEY": push_key}


def main() -> None:
    gems_dir = os.environ.get("INPUT_GEMS_DIR", "")
    dry_run = os.environ.get("INPUT_DRY_RUN", "false").lower() == "true"

    if not gems_dir:
        print("Error: INPUT_GEMS_DIR is required", file=sys.stderr)
        sys.exit(1)

    gems_path = Path(gems_dir)
    if not gems_path.is_dir():
        print(f"Error: gems directory not found: {gems_dir}", file=sys.stderr)
        sys.exit(1)

    gem_files = find_gem_files(gems_path)
    if not gem_files:
        print(f"Error: no .gem files found in {gems_dir}", file=sys.stderr)
        sys.exit(1)

    verify_release_versions(gem_files, os.environ.get("INPUT_EXPECTED_VERSION", ""))

    failed = 0
    published = 0

    push_env = build_push_env(dry_run)

    print(f"Publishing {len(gem_files)} gem(s)...")

    for gem_file in gem_files:
        name = gem_file.name

        if not gem_file.is_file() or not os.access(gem_file, os.R_OK) or gem_file.stat().st_size == 0:
            print(f"  Error: {name} is missing, unreadable, or empty", file=sys.stderr)
            failed += 1
            continue

        if not validate_gem_structure(gem_file):
            print(f"  Error: {name} has invalid gem structure", file=sys.stderr)
            failed += 1
            continue

        print(f"Publishing {name}...")

        if dry_run:
            print(f"  [dry-run] gem push {name}")
            published += 1
            continue

        exit_code, output = _run(["gem", "push", str(gem_file)], env=push_env)

        if exit_code == 0:
            print(f"  Published {name}")
            published += 1
        elif is_already_published(output):
            # ~keep Counted as published only because the pre-flight above has already proven this
            # gem carries the release version, which makes the registry hit a genuine idempotent
            # re-run rather than a stale gem silently standing in for the release.
            print(f"  {name} already published, skipping")
            published += 1
        else:
            print(f"  Error publishing {name}:", file=sys.stderr)
            print(output, file=sys.stderr)
            failed += 1

    print(f"Published: {published}, Failed: {failed}")

    if failed > 0:
        sys.exit(1)

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY", "")
    if summary_path:
        with Path(summary_path).open("a") as fh:
            fh.write("### RubyGems Publish\n")
            fh.write(f"- Published: {published}\n")
            fh.write(f"- Failed: {failed}\n")


if __name__ == "__main__":
    main()
