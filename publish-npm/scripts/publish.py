#!/usr/bin/env python3
"""Publish npm packages from a directory or a .tgz file.

Usage (GitHub Actions via env vars):
    INPUT_PACKAGE_DIR=dist/ python3 publish.py
    INPUT_PACKAGES_DIR=dist/packages/ python3 publish.py
"""

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# ~keep Matches only npm's version-conflict wording. A bare `already exists` also matches
# Sigstore/Rekor's "entry already exists" and other unrelated failures, which is how
# @xberg-io/html-to-markdown 3.10.5 and 3.10.6 were reported as published without ever
# reaching the registry.
ALREADY_PUBLISHED_PATTERN = re.compile(
    r"previously published|cannot publish over",
    re.IGNORECASE,
)

TRANSIENT_PUBLISH_PATTERN = re.compile(
    r"TLOG_CREATE_ENTRY_ERROR|error creating tlog entry|ETIMEDOUT|ECONNRESET|"
    r"ECONNREFUSED|EAI_AGAIN|socket hang up|aborted|fetch failed|5\d\d ",
    re.IGNORECASE,
)
MAX_PUBLISH_RETRIES = 4
PUBLISH_RETRY_BACKOFF_SECONDS = 5

# ~keep npm's own post-publish notice — "Your package is being processed and may take a few
# minutes to become available" — describes the registry read path lagging the write path.
# A presence check that gives up in seconds turns that lag into a reported failure:
# @xberg-io/liter-llm 1.17.3 published all six napi platform packages, failed this check on
# one of them, exited 1, and so never reached the main package — which stayed at 1.16.0 while
# its optionalDependencies pinned platform versions that only existed at 1.17.3.
REGISTRY_CHECK_WINDOW_SECONDS = 300
REGISTRY_CHECK_INITIAL_BACKOFF_SECONDS = 5
REGISTRY_CHECK_MAX_BACKOFF_SECONDS = 30
REGISTRY_CHECK_TIMEOUT_SECONDS = 30
HTTP_OK = 200
HTTP_NOT_FOUND = 404
HTTP_TOO_MANY_REQUESTS = 429
HTTP_SERVER_ERROR = 500

SETUP_NODE_PLACEHOLDER = "XXXXX-XXXXX-XXXXX-XXXXX"


def validate_inputs(packages_dir: str, package_dir: str) -> str:
    """Validate mutually exclusive inputs; return mode 'tgz' or 'dir'.

    Raises SystemExit on invalid combinations.
    """
    if packages_dir and package_dir:
        print("Error: packages-dir and package-dir are mutually exclusive", file=sys.stderr)
        sys.exit(1)
    if not packages_dir and not package_dir:
        print("Error: either packages-dir or package-dir must be provided", file=sys.stderr)
        sys.exit(1)
    return "tgz" if packages_dir else "dir"


def build_publish_flags(access: str, npm_tag: str, provenance: bool, dry_run: bool) -> list[str]:
    """Build the list of flags to pass to `npm publish`.

    Note: --force bypasses npm's pre-publish validation for new scoped packages.
    This is required for platform-specific subpackages (e.g. @xberg-io/node-linux-arm64-musl)
    on their first publish, as npm CLI cannot validate the package exists before creation.
    """
    flags: list[str] = ["--access", access, "--tag", npm_tag, "--ignore-scripts", "--force"]
    if provenance:
        flags.append("--provenance")
    if dry_run:
        flags.append("--dry-run")
    return flags


def is_already_published(output: str) -> bool:
    """Return True if the npm output indicates the package was already published."""
    return bool(ALREADY_PUBLISHED_PATTERN.search(output))


def find_tgz_files(directory: Path) -> list[Path]:
    """Return all *.tgz files in directory (non-recursive) and subdirectories."""
    return sorted(directory.glob("**/*.tgz"))


def has_native_binding(tgz_path: Path) -> bool:
    """Check if a .tgz tarball contains a .node native binding file.

    Returns False for stub packages (placeholders without prebuilt binaries),
    which should be skipped during publishing to avoid npm Sigstore validation
    failures on empty payloads.
    """
    import tarfile

    try:
        with tarfile.open(tgz_path, "r:gz") as tar:
            for member in tar.getmembers():
                if member.name.endswith(".node"):
                    return True
    except Exception:
        pass
    return False


def is_platform_package(tgz_path: Path) -> bool:
    """Check whether a .tgz is a per-platform binding package.

    napi-rs platform sub-packages (e.g. `@scope/pkg-linux-x64-gnu`) pin `os`
    and/or `cpu` in their package.json; the pure-JS umbrella package (the one
    consumers install, whose binaries resolve via `optionalDependencies`) sets
    neither. Only platform packages may be skipped as empty stubs — the umbrella
    package has no `.node` of its own and must still publish.
    """
    import tarfile

    try:
        with tarfile.open(tgz_path, "r:gz") as tar:
            for member in tar.getmembers():
                if member.name.endswith("package.json") and member.name.count("/") == 1:
                    extracted = tar.extractfile(member)
                    if extracted is None:
                        continue
                    pkg = json.loads(extracted.read().decode("utf-8"))
                    return bool(pkg.get("os") or pkg.get("cpu"))
    except Exception:
        pass
    return False


def read_package_identity(tgz_path: Path) -> tuple[str, str] | None:
    """Return (name, version) from a .tgz's top-level package.json, or None if unreadable."""
    import tarfile

    try:
        with tarfile.open(tgz_path, "r:gz") as tar:
            for member in tar.getmembers():
                if member.name.endswith("package.json") and member.name.count("/") == 1:
                    extracted = tar.extractfile(member)
                    if extracted is None:
                        continue
                    pkg = json.loads(extracted.read().decode("utf-8"))
                    name, version = pkg.get("name"), pkg.get("version")
                    if name and version:
                        return name, version
    except (OSError, tarfile.TarError, json.JSONDecodeError, UnicodeDecodeError):
        pass
    return None


def registry_check_delays() -> list[int]:
    """Backoff delays spanning at least REGISTRY_CHECK_WINDOW_SECONDS, doubling up to the cap."""
    delays: list[int] = []
    delay = REGISTRY_CHECK_INITIAL_BACKOFF_SECONDS
    elapsed = 0
    while elapsed < REGISTRY_CHECK_WINDOW_SECONDS:
        delay = min(delay, REGISTRY_CHECK_MAX_BACKOFF_SECONDS)
        delays.append(delay)
        elapsed += delay
        delay *= 2
    return delays


def registry_has_version(package: str, version: str) -> bool:
    """Poll the npm registry for `package@version` across the full propagation window.

    npm reports success for publishes that never land — a Sigstore failure, a
    trusted-publisher mismatch, or a misclassified error all exit the CLI without the
    version reaching the registry. Confirming against the registry is the only check
    that distinguishes "published" from "claimed to publish".
    """
    encoded = urllib.parse.quote(package, safe="")
    url = f"https://registry.npmjs.org/{encoded}/{version}"
    for delay in [*registry_check_delays(), None]:
        request = urllib.request.Request(url, headers={"User-Agent": "publish-npm/1.0"})
        try:
            with urllib.request.urlopen(request, timeout=REGISTRY_CHECK_TIMEOUT_SECONDS) as response:  # noqa: S310
                if response.status == HTTP_OK:
                    return True
        except urllib.error.HTTPError as error:
            if error.code not in (HTTP_NOT_FOUND, HTTP_TOO_MANY_REQUESTS) and error.code < HTTP_SERVER_ERROR:
                return False
        except (urllib.error.URLError, OSError, TimeoutError):
            pass
        if delay is None:
            break
        time.sleep(delay)
    return False


def confirm_registry_presence(identities: list[tuple[str, str]]) -> list[str]:
    """Report which of the already-accepted `identities` are not yet readable from the registry.

    Advisory only, and deliberately so. Every identity here is one npm accepted, so an absent
    result is registry read lag far more often than a lost publish. Failing the step on it
    strands whatever has not been published yet — the platform packages after this one, and the
    main package whose optionalDependencies pin them — which is strictly worse than shipping a
    package the read path has not caught up to. Real losses are caught by the dedicated
    `check-registry` / `verify-platform-packages` gates, which run against a settled registry.
    """
    unconfirmed: list[str] = []
    for name, version in identities:
        if registry_has_version(name, version):
            print(f"Confirmed {name}@{version} on the npm registry")
            continue
        unconfirmed.append(f"{name}@{version}")
        print(
            f"::warning::{name}@{version} was accepted by npm but is not readable from the registry "
            f"after {REGISTRY_CHECK_WINDOW_SECONDS}s; npm reports propagation can take several minutes"
        )
    return unconfirmed


def _run(cmd: list[str], cwd: Path | None = None) -> tuple[int, str]:
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, check=False)
    return result.returncode, result.stdout + result.stderr


def _run_publish_with_retry(cmd: list[str], cwd: Path | None = None) -> tuple[int, str]:
    """Run an `npm publish` command, retrying on Sigstore Rekor / transient network errors.

    Returns the final `(exit_code, output)` of the last attempt.
    Non-transient failures (auth, schema, already-published, etc.) return immediately.
    """
    last_output = ""
    for attempt in range(1, MAX_PUBLISH_RETRIES + 1):
        exit_code, output = _run(cmd, cwd=cwd)
        last_output = output
        if exit_code == 0:
            return exit_code, output
        if is_already_published(output):
            return exit_code, output
        if not TRANSIENT_PUBLISH_PATTERN.search(output):
            return exit_code, output
        if attempt == MAX_PUBLISH_RETRIES:
            break
        delay = PUBLISH_RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1))
        print(
            f"  Transient npm publish error (attempt {attempt}/{MAX_PUBLISH_RETRIES}); retrying in {delay}s",
            file=sys.stderr,
        )
        time.sleep(delay)
    return 1, last_output


def _strip_empty_npm_auth_token() -> None:
    """Strip empty NODE_AUTH_TOKEN env + _authToken lines in .npmrc.

    When a caller writes `NODE_AUTH_TOKEN: ${{ secrets.NPM_TOKEN }}` and the
    secret is undefined, the env var is set to "" and `setup-node` writes a
    `//registry.npmjs.org/:_authToken=${NODE_AUTH_TOKEN}` line into .npmrc.
    npm CLI then sees an empty token and skips OIDC trusted publishing, even
    though npm@11+ would otherwise exchange the GHA OIDC token for a
    short-lived credential automatically. Strip both so OIDC can take over.

    Note: `setup-node` writes the literal placeholder string
    `_authToken=${NODE_AUTH_TOKEN}` to .npmrc and relies on npm CLI to expand
    the env var at read time. When NODE_AUTH_TOKEN is empty/unset, that
    expansion produces an empty token but the line itself is non-empty —
    so we must strip lines matching the placeholder form too, not just the
    post-expansion `_authToken=` form.
    """
    token = os.environ.get("NODE_AUTH_TOKEN", "")
    if token.strip() and token.strip() != SETUP_NODE_PLACEHOLDER:
        print(f"NODE_AUTH_TOKEN is set ({len(token)} chars); skipping OIDC fallback strip")
        return

    if token.strip() == SETUP_NODE_PLACEHOLDER:
        print("NODE_AUTH_TOKEN is set to setup-node@v6's placeholder; treating as unset for OIDC")
    os.environ.pop("NODE_AUTH_TOKEN", None)

    candidates: list[Path] = []
    if cfg := os.environ.get("NPM_CONFIG_USERCONFIG"):
        candidates.append(Path(cfg))
    candidates.extend([Path.home() / ".npmrc", Path.cwd() / ".npmrc"])

    strip_pattern = re.compile(r"^\s*//[^:]+:_authToken\s*=")

    seen: set[Path] = set()
    for raw in candidates:
        try:
            npmrc_path = raw.resolve()
        except OSError:
            continue
        if npmrc_path in seen:
            continue
        seen.add(npmrc_path)
        if not npmrc_path.is_file():
            continue

        original = npmrc_path.read_text()
        cleaned = "".join(line for line in original.splitlines(keepends=True) if not strip_pattern.match(line))
        if cleaned != original:
            npmrc_path.write_text(cleaned)
            print(f"Stripped _authToken lines from {npmrc_path}; npm will use OIDC trusted publishing")
        else:
            print(f"No _authToken line found in {npmrc_path} (file present, no strip needed)")


def publish_package_directory(package_dir: str, flags: list[str], *, dry_run: bool) -> None:
    """Publish a single package from a working directory."""
    pkg_path = Path(package_dir)
    if not pkg_path.is_dir():
        print(f"Error: package directory not found: {package_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Publishing from directory: {package_dir}")
    exit_code, output = _run_publish_with_retry(["npm", "publish", ".", *flags], cwd=pkg_path)

    if exit_code == 0:
        print("Published successfully")
    elif is_already_published(output):
        print("Package already published, skipping")
        print(output, file=sys.stderr)
    else:
        print("Error publishing:", file=sys.stderr)
        print(output, file=sys.stderr)
        sys.exit(1)

    if dry_run:
        return

    manifest = json.loads((pkg_path / "package.json").read_text())
    confirm_registry_presence([(manifest["name"], manifest["version"])])


def publish_tgz_directory(packages_dir: str, flags: list[str], npm_tag: str, *, dry_run: bool) -> None:
    """Publish every non-stub .tgz under `packages_dir`, then confirm the accepted ones.

    Publishing runs to completion before any registry confirmation so that no package's
    propagation lag can delay — or, via a non-zero exit, prevent — the publishes after it.
    """
    pkgs_path = Path(packages_dir)
    if not pkgs_path.is_dir():
        print(f"Error: packages directory not found: {packages_dir}", file=sys.stderr)
        sys.exit(1)

    tgz_files = find_tgz_files(pkgs_path)
    if not tgz_files:
        print(f"Error: no .tgz files found in {packages_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Publishing {len(tgz_files)} package(s) with tag '{npm_tag}'...")

    failed = 0
    published = 0
    skipped = 0
    accepted: list[tuple[str, str]] = []

    for tgz in tgz_files:
        name = tgz.name

        if is_platform_package(tgz) and not has_native_binding(tgz):
            print(f"  Skipping {name} (platform stub with no .node binding)")
            skipped += 1
            continue

        print(f"Publishing {name}...")
        exit_code, output = _run_publish_with_retry(["npm", "publish", str(tgz.resolve()), *flags])

        if exit_code == 0:
            print(f"  Published {name}")
        elif is_already_published(output):
            print(f"  {name} already published, skipping")
            print(output, file=sys.stderr)
        else:
            print(f"  Error publishing {name}:", file=sys.stderr)
            print(output, file=sys.stderr)
            failed += 1
            continue

        published += 1
        if identity := read_package_identity(tgz):
            accepted.append(identity)

    print(f"Published: {published}, Failed: {failed}, Skipped: {skipped}")

    if not dry_run and accepted and (unconfirmed := confirm_registry_presence(accepted)):
        print(f"Accepted by npm but not yet readable from the registry: {', '.join(unconfirmed)}")

    if failed > 0:
        sys.exit(1)


def main() -> None:
    packages_dir = os.environ.get("INPUT_PACKAGES_DIR", "")
    package_dir = os.environ.get("INPUT_PACKAGE_DIR", "")
    npm_tag = os.environ.get("INPUT_NPM_TAG", "latest")
    access = os.environ.get("INPUT_ACCESS", "public")
    provenance = os.environ.get("INPUT_PROVENANCE", "true").lower() == "true"
    dry_run = os.environ.get("INPUT_DRY_RUN", "false").lower() == "true"

    _strip_empty_npm_auth_token()

    mode = validate_inputs(packages_dir, package_dir)
    flags = build_publish_flags(access, npm_tag, provenance, dry_run)

    if mode == "dir":
        publish_package_directory(package_dir, flags, dry_run=dry_run)
    else:
        publish_tgz_directory(packages_dir, flags, npm_tag, dry_run=dry_run)


if __name__ == "__main__":
    main()
