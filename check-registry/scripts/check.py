#!/usr/bin/env python3
"""Check if a package version exists on a registry.

Supports: pypi, npm, rubygems, cratesio, nuget, maven, packagist, hex, homebrew, github-release

Usage (CLI):
    python3 check.py <registry> <package> <version> [options]

Usage (GitHub Actions via env vars):
    INPUT_REGISTRY=pypi INPUT_PACKAGE=kreuzberg INPUT_VERSION=4.4.6 python3 check.py
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

MAX_ATTEMPTS = 3
CONNECT_TIMEOUT = 30

HTTP_OK = 200
HTTP_NOT_FOUND = 404

logger = logging.getLogger(__name__)

CheckFn = Callable[..., bool]


def http_get(url: str, *, timeout: int = CONNECT_TIMEOUT) -> tuple[int, str]:
    """GET a URL, return (status_code, body). Returns (0, '') on connection error."""
    if not url.startswith(("https://", "http://")):
        return 0, ""
    req = urllib.request.Request(url, headers={"User-Agent": "check-registry/1.0"})  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except (urllib.error.URLError, OSError, TimeoutError):
        return 0, ""


def check_url_exists(url: str) -> bool:
    """Check if a URL returns 200, with retries."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        status, _ = http_get(url)
        if status == HTTP_OK:
            return True
        if status == HTTP_NOT_FOUND:
            return False
        logger.info("  Attempt %d: HTTP %d for %s", attempt, status, url)
        if attempt < MAX_ATTEMPTS:
            time.sleep(attempt * 5)
    return False


def fetch_json(url: str) -> Any:
    """Fetch JSON from a URL with retries. Returns None on failure."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        status, body = http_get(url)
        if status == HTTP_OK:
            return json.loads(body)
        if status == HTTP_NOT_FOUND:
            return None
        logger.info("  Attempt %d: HTTP %d for %s", attempt, status, url)
        if attempt < MAX_ATTEMPTS:
            time.sleep(attempt * 5)
    return None


# --- Registry checks ---


def check_pypi(package: str, version: str, **_: str) -> bool:
    return check_url_exists(f"https://pypi.org/pypi/{package}/{version}/json")


def check_npm(package: str, version: str, **_: str) -> bool:
    encoded = urllib.parse.quote(package, safe="")
    return check_url_exists(f"https://registry.npmjs.org/{encoded}/{version}")


def check_cratesio(package: str, version: str, **_: str) -> bool:
    return check_url_exists(f"https://crates.io/api/v1/crates/{package}/{version}")


def check_nuget(package: str, version: str, **_: str) -> bool:
    lower_pkg = package.lower()
    lower_ver = version.lower()
    return check_url_exists(f"https://api.nuget.org/v3-flatcontainer/{lower_pkg}/{lower_ver}/{lower_pkg}.nuspec")


def check_rubygems(package: str, version: str, **_: str) -> bool:
    ruby_ver = version.replace("-", ".")
    data = fetch_json(f"https://rubygems.org/api/v1/versions/{package}.json")
    if data is None:
        return False
    return any(v.get("number") == ruby_ver for v in data)


def check_hex(package: str, version: str, **_: str) -> bool:
    data = fetch_json(f"https://hex.pm/api/packages/{package}")
    if data is None:
        return False
    return any(r.get("version") == version for r in data.get("releases", []))


def check_maven(package: str, version: str, **_: str) -> bool:
    if ":" not in package:
        logger.error("  maven package must be group:artifact, got '%s'", package)
        return False
    group, artifact = package.split(":", 1)
    group_path = group.replace(".", "/")
    return check_url_exists(
        f"https://repo1.maven.org/maven2/{group_path}/{artifact}/{version}/{artifact}-{version}.jar"
    )


def check_packagist(package: str, version: str, **_: str) -> bool:
    data = fetch_json(f"https://repo.packagist.org/p2/{package}.json")
    if data is None:
        return False
    pkgs = data.get("packages", {}).get(package, [])
    return any(p.get("version") in (version, f"v{version}") for p in pkgs)


def check_homebrew(package: str, version: str, *, tap_repo: str = "", **_: str) -> bool:
    if not tap_repo:
        logger.error("  --tap-repo is required for homebrew registry")
        return False
    url = f"https://raw.githubusercontent.com/{tap_repo}/main/Formula/{package}.rb"
    status, body = http_get(url)
    if status != HTTP_OK:
        return False
    return f'version "{version}"' in body or f"/v{version}.tar.gz" in body or f"/v{version}/" in body


def check_github_release(
    _package: str,
    version: str,
    *,
    tag: str = "",
    assets: str = "",
    asset_prefix: str = "",
    repo: str = "",
    **_: str,
) -> bool:
    if not tag:
        tag = f"v{version}"
    if not repo:
        repo = "kreuzberg-dev/kreuzberg"

    try:
        result = subprocess.run(
            ["gh", "release", "view", tag, "--repo", repo, "--json", "assets"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except FileNotFoundError:
        logger.warning("  gh CLI not found")
        return False
    except subprocess.TimeoutExpired:
        logger.warning("  gh CLI timed out")
        return False

    if result.returncode != 0:
        return False

    data = json.loads(result.stdout)
    asset_names = {a["name"] for a in data.get("assets", [])}

    if assets:
        required = [a.strip() for a in assets.split(",") if a.strip()]
        return all(r in asset_names for r in required)

    if asset_prefix:
        return any(name.startswith(asset_prefix) for name in asset_names)

    return len(asset_names) > 0


REGISTRIES: dict[str, CheckFn] = {
    "pypi": check_pypi,
    "npm": check_npm,
    "cratesio": check_cratesio,
    "nuget": check_nuget,
    "rubygems": check_rubygems,
    "hex": check_hex,
    "maven": check_maven,
    "packagist": check_packagist,
    "homebrew": check_homebrew,
    "github-release": check_github_release,
}


def write_output(key: str, value: str) -> None:
    """Write key=value to stdout and $GITHUB_OUTPUT if set."""
    line = f"{key}={value}"
    sys.stdout.write(line + "\n")
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with Path(github_output).open("a") as f:
            f.write(line + "\n")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)

    # Support both CLI args and env vars (for GitHub Actions)
    registry = os.environ.get("INPUT_REGISTRY", "")
    package = os.environ.get("INPUT_PACKAGE", "")
    version = os.environ.get("INPUT_VERSION", "")
    extra_packages_str = os.environ.get("INPUT_EXTRA_PACKAGES", "")
    tap_repo = os.environ.get("INPUT_TAP_REPO", "")
    env_tag = os.environ.get("INPUT_TAG", "")
    env_asset_prefix = os.environ.get("INPUT_ASSET_PREFIX", "")
    env_assets = os.environ.get("INPUT_ASSETS", "")
    env_repo = os.environ.get("INPUT_REPO", "")

    parser = argparse.ArgumentParser(description="Check if a package version exists on a registry")
    parser.add_argument("registry", nargs="?", default=registry, help="Registry name")
    parser.add_argument("package", nargs="?", default=package, help="Package name")
    parser.add_argument("version", nargs="?", default=version, help="Version to check")
    parser.add_argument("--tap-repo", default=tap_repo, help="Homebrew tap repository")
    parser.add_argument("--tag", default=env_tag, help="GitHub release tag")
    parser.add_argument("--assets", default=env_assets, help="Required release assets (comma-separated)")
    parser.add_argument("--asset-prefix", default=env_asset_prefix, help="Release asset prefix to match")
    parser.add_argument("--repo", default=env_repo, help="GitHub repo (owner/repo)")
    parser.add_argument("--extra", action="append", default=[], help="Extra package: key=package_name")
    parser.add_argument("--output-key", default="exists", help="Output key name (default: exists)")

    args = parser.parse_args()

    if not args.registry or not args.package or not args.version:
        parser.error("registry, package, and version are required")

    if args.registry not in REGISTRIES:
        logger.error("Error: unsupported registry: %s", args.registry)
        logger.error("Supported: %s", ", ".join(sorted(REGISTRIES)))
        sys.exit(1)

    check_fn = REGISTRIES[args.registry]
    kwargs = {
        "tap_repo": args.tap_repo,
        "tag": args.tag,
        "assets": args.assets,
        "asset_prefix": args.asset_prefix,
        "repo": args.repo,
    }

    # Check primary package
    result = check_fn(args.package, args.version, **kwargs)
    write_output(args.output_key, "true" if result else "false")
    status = "exists" if result else "not found"
    logger.info("%s: %s@%s -> %s", args.registry, args.package, args.version, status)

    # Check extra packages (from --extra flags or INPUT_EXTRA_PACKAGES env)
    extras: list[tuple[str, str]] = []
    for extra in args.extra:
        if "=" in extra:
            key, pkg = extra.split("=", 1)
            extras.append((key, pkg))

    if extra_packages_str:
        for raw_line in extra_packages_str.strip().splitlines():
            stripped = raw_line.strip()
            if stripped and "=" in stripped:
                key, pkg = stripped.split("=", 1)
                extras.append((key.strip(), pkg.strip()))

    for key, pkg in extras:
        extra_result = check_fn(pkg, args.version, **kwargs)
        write_output(key, "true" if extra_result else "false")
        extra_status = "exists" if extra_result else "not found"
        logger.info("%s: %s@%s -> %s=%s", args.registry, pkg, args.version, key, extra_status)


if __name__ == "__main__":
    main()
