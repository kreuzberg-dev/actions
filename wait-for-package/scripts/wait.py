#!/usr/bin/env python3
"""Wait for a package version to appear on a registry with exponential backoff.

Supports: npm, pypi, cratesio, maven, rubygems

Usage (GitHub Actions via env vars):
    INPUT_REGISTRY=pypi INPUT_PACKAGE=kreuzberg INPUT_VERSION=4.4.6 python3 wait.py
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable

CONNECT_TIMEOUT = 30
HTTP_OK = 200

CheckFn = Callable[[str, str], bool]


def http_get(url: str, *, timeout: int = CONNECT_TIMEOUT) -> tuple[int, str]:
    """GET a URL, return (status_code, body). Returns (0, '') on connection error."""
    if not url.startswith(("https://", "http://")):
        return 0, ""
    req = urllib.request.Request(url, headers={"User-Agent": "wait-for-package/1.0"})  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except (urllib.error.URLError, OSError, TimeoutError):
        return 0, ""


def validate_version(version: str) -> bool:
    """Return True if version matches the required semver-like prefix pattern."""
    return bool(re.match(r"^\d+\.\d+\.\d+", version))


def check_npm(package: str, version: str) -> bool:
    """Check npm registry via the npmjs.org REST API (no npm CLI required)."""
    encoded = urllib.parse.quote(package, safe="")
    status, _ = http_get(f"https://registry.npmjs.org/{encoded}/{version}")
    return status == HTTP_OK


def check_pypi(package: str, version: str) -> bool:
    """Check PyPI JSON API for the exact version."""
    status, body = http_get(f"https://pypi.org/pypi/{package}/{version}/json")
    if status != HTTP_OK or not body:
        return False
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return False
    return bool(data.get("info", {}).get("version") == version)


def _cratesio_prefix(name: str) -> str:
    """Compute the crates.io index path prefix for a crate name.

    See https://doc.rust-lang.org/cargo/reference/registry-index.html#index-files
    """
    lower = name.lower()
    length = len(lower)
    if length == 1:
        return f"1/{lower}"
    if length == 2:
        return f"2/{lower}"
    if length == 3:
        return f"3/{lower[0]}/{lower}"
    return f"{lower[0:2]}/{lower[2:4]}/{lower}"


def check_cratesio(package: str, version: str) -> bool:
    """Check the crates.io sparse index for the exact version."""
    prefix = _cratesio_prefix(package)
    status, body = http_get(f"https://index.crates.io/{prefix}")
    if status != HTTP_OK or not body:
        return False
    for raw_line in body.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if data.get("vers") == version:
            return True
    return False


def check_maven(package: str, version: str, group_id: str = "") -> bool:
    """Check Maven Central solrsearch API. Requires group_id."""
    if not group_id:
        print("Error: maven-group-id required for maven registry", file=sys.stderr)
        return False
    url = f"https://search.maven.org/solrsearch/select?q=g:{group_id}+AND+a:{package}+AND+v:{version}&rows=1&wt=json"
    status, body = http_get(url)
    if status != HTTP_OK or not body:
        return False
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return False
    return int(data.get("response", {}).get("numFound", 0)) > 0


def check_rubygems(package: str, version: str) -> bool:
    """Check RubyGems API version list for the exact version."""
    status, body = http_get(f"https://rubygems.org/api/v1/versions/{package}.json")
    if status != HTTP_OK or not body:
        return False
    try:
        versions = json.loads(body)
    except json.JSONDecodeError:
        return False
    return any(v.get("number") == version for v in versions)


REGISTRIES: dict[str, CheckFn] = {
    "npm": check_npm,
    "pypi": check_pypi,
    "cratesio": check_cratesio,
    "maven": check_maven,
    "rubygems": check_rubygems,
}

SUPPORTED_REGISTRIES = ", ".join(sorted(REGISTRIES))


def wait_for_package(
    registry: str,
    package: str,
    version: str,
    max_attempts: int,
    maven_group_id: str = "",
) -> bool:
    """Poll the registry until the package version is found or attempts are exhausted."""
    print(f"Waiting for {package}@{version} on {registry} (max {max_attempts} attempts)...")

    for attempt in range(1, max_attempts + 1):
        delay = min(2**attempt, 64)

        if registry == "maven":
            found = check_maven(package, version, group_id=maven_group_id)
        else:
            found = REGISTRIES[registry](package, version)

        if found:
            print(f"Package {package}@{version} found on {registry} (attempt {attempt})")
            return True

        print(f"Attempt {attempt}/{max_attempts}: not yet available, waiting {delay}s...")
        time.sleep(delay)

    print(f"Error: {package}@{version} not found on {registry} after {max_attempts} attempts", file=sys.stderr)
    return False


def main() -> None:
    registry = os.environ.get("INPUT_REGISTRY", "")
    package = os.environ.get("INPUT_PACKAGE", "")
    version = os.environ.get("INPUT_VERSION", "")
    max_attempts_str = os.environ.get("INPUT_MAX_ATTEMPTS", "10")
    maven_group_id = os.environ.get("INPUT_MAVEN_GROUP_ID", "")

    if not registry:
        print("Error: INPUT_REGISTRY is required", file=sys.stderr)
        sys.exit(1)
    if not package:
        print("Error: INPUT_PACKAGE is required", file=sys.stderr)
        sys.exit(1)
    if not version:
        print("Error: INPUT_VERSION is required", file=sys.stderr)
        sys.exit(1)

    if not validate_version(version):
        print(f"Error: Invalid version format: {version}", file=sys.stderr)
        sys.exit(1)

    if registry not in REGISTRIES:
        print(
            f"Error: Unsupported registry: {registry} (supported: {SUPPORTED_REGISTRIES})",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        max_attempts = int(max_attempts_str)
    except ValueError:
        print(f"Error: INPUT_MAX_ATTEMPTS must be an integer, got: {max_attempts_str}", file=sys.stderr)
        sys.exit(1)

    success = wait_for_package(registry, package, version, max_attempts, maven_group_id)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
