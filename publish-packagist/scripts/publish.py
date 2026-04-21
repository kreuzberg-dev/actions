#!/usr/bin/env python3
"""Trigger a Packagist update and poll until the package version is available.

Usage (GitHub Actions via env vars):
    INPUT_USERNAME=myuser INPUT_PACKAGE_NAME=vendor/pkg INPUT_VERSION=1.2.3 \
    INPUT_REPOSITORY_URL=https://github.com/vendor/pkg python3 publish.py
"""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

CONNECT_TIMEOUT = 30
HTTP_OK = 200


def http_get(url: str, *, timeout: int = CONNECT_TIMEOUT) -> tuple[int, str]:
    """GET a URL, return (status_code, body). Returns (0, '') on connection error."""
    if not url.startswith(("https://", "http://")):
        return 0, ""
    req = urllib.request.Request(url, headers={"User-Agent": "publish-packagist/1.0"})  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except (urllib.error.URLError, OSError, TimeoutError):
        return 0, ""


def http_post(url: str, body: str, *, timeout: int = CONNECT_TIMEOUT) -> tuple[int, str]:
    """POST JSON body to a URL, return (status_code, response_body)."""
    if not url.startswith(("https://", "http://")):
        return 0, ""
    data = body.encode("utf-8")
    req = urllib.request.Request(  # noqa: S310
        url,
        data=data,
        headers={
            "User-Agent": "publish-packagist/1.0",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except (urllib.error.URLError, OSError, TimeoutError):
        return 0, ""


def trigger_packagist_update(username: str, api_token: str, repository_url: str) -> bool:
    """POST to the Packagist API to trigger a package update. Returns True on success."""
    encoded_user = urllib.parse.quote(username, safe="")
    encoded_token = urllib.parse.quote(api_token, safe="")
    url = f"https://packagist.org/api/update-package?username={encoded_user}&apiToken={encoded_token}"
    payload = json.dumps({"repository": {"url": repository_url}})
    status, response = http_post(url, payload)
    if status == HTTP_OK:
        return True
    print(f"Warning: Packagist API trigger failed (status {status}): {response}")
    return False


def check_packagist_version(package_name: str, version: str) -> bool:
    """Return True if the given version is listed on Packagist for the package."""
    status, body = http_get(f"https://packagist.org/packages/{package_name}.json")
    if status != HTTP_OK or not body:
        return False
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return False
    versions: dict[str, object] = data.get("package", {}).get("versions", {})
    target = version.lstrip("v")
    for version_key in versions:
        normalized = version_key.lstrip("v")
        if normalized == target or version_key == version:
            return True
    return False


def poll_packagist(package_name: str, version: str, max_attempts: int, poll_interval: int) -> bool:
    """Poll Packagist until version is found or attempts are exhausted. Returns True if found."""
    print(f"Polling Packagist for {package_name}@{version} (max {max_attempts} attempts, {poll_interval}s interval)...")

    for attempt in range(1, max_attempts + 1):
        if check_packagist_version(package_name, version):
            print(f"Package {package_name}@{version} found on Packagist (attempt {attempt})")
            return True
        print(f"Attempt {attempt}/{max_attempts}: not yet available, waiting {poll_interval}s...")
        time.sleep(poll_interval)

    print(f"Warning: {package_name}@{version} not found on Packagist after {max_attempts} attempts")
    print("The package may still appear after webhook processing completes")
    return False


def main() -> None:
    username = os.environ.get("INPUT_USERNAME", "")
    package_name = os.environ.get("INPUT_PACKAGE_NAME", "")
    version = os.environ.get("INPUT_VERSION", "")
    repository_url = os.environ.get("INPUT_REPOSITORY_URL", "")
    max_attempts_str = os.environ.get("INPUT_MAX_ATTEMPTS", "12")
    poll_interval_str = os.environ.get("INPUT_POLL_INTERVAL", "10")
    dry_run = os.environ.get("INPUT_DRY_RUN", "false").lower() == "true"
    api_token = os.environ.get("PACKAGIST_API_TOKEN", "")

    for name, value in [
        ("INPUT_USERNAME", username),
        ("INPUT_PACKAGE_NAME", package_name),
        ("INPUT_VERSION", version),
        ("INPUT_REPOSITORY_URL", repository_url),
    ]:
        if not value:
            print(f"Error: {name} is required", file=sys.stderr)
            sys.exit(1)

    if dry_run:
        print(f"[dry-run] Would trigger Packagist update for {package_name}@{version}")
        sys.exit(0)

    try:
        max_attempts = int(max_attempts_str)
        poll_interval = int(poll_interval_str)
    except ValueError as exc:
        print(f"Error: invalid integer value: {exc}", file=sys.stderr)
        sys.exit(1)

    if api_token:
        print(f"Triggering Packagist update for {package_name}...")
        if trigger_packagist_update(username, api_token, repository_url):
            print("Packagist API triggered successfully")
        else:
            print("Warning: Packagist API trigger failed (will rely on webhook)")
    else:
        print("No PACKAGIST_API_TOKEN set, relying on automatic webhook")

    poll_packagist(package_name, version, max_attempts, poll_interval)
    # Exit 0 even on timeout — package may appear after webhook processing
    sys.exit(0)


if __name__ == "__main__":
    main()
