#!/usr/bin/env python3
"""Publish NuGet packages from a directory.

Authentication: either OIDC trusted publishing (preferred when NuGet is
configured for the repo) or a static NUGET_API_KEY. The script auto-detects
which one to use:

  - If NUGET_API_KEY is set, it's used directly with `dotnet nuget push --api-key`.
  - Otherwise, if running under GitHub Actions with `id-token: write`
    permission, an OIDC token is exchanged at api.nuget.org's
    `/v3/oidc/login` endpoint for a short-lived API key, which is then
    used for the push.

Usage (GitHub Actions via env vars):
    INPUT_PACKAGES_DIR=./dist INPUT_DRY_RUN=false python3 publish.py
"""

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path


def find_nupkg_files(directory: Path) -> list[Path]:
    """Return all .nupkg files found directly in directory (non-recursive)."""
    return sorted(directory.glob("*.nupkg"))


def is_publish_error(exit_code: int, output: str) -> bool:  # noqa: ARG001
    """Return True if the exit code indicates a real publish failure."""
    return exit_code != 0


def _run(cmd: list[str]) -> tuple[int, str]:
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return result.returncode, result.stdout + result.stderr


def _fetch_oidc_token(audience: str = "https://www.nuget.org") -> str | None:
    """Fetch a GitHub Actions OIDC ID token for the given audience.

    Requires `permissions: id-token: write` on the calling workflow/job.
    Returns None when not running under Actions or when the token endpoint
    is unreachable; the caller should then fall back to a static API key.
    """
    request_url = os.environ.get("ACTIONS_ID_TOKEN_REQUEST_URL")
    request_token = os.environ.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN")
    if not (request_url and request_token):
        return None

    url = f"{request_url}&audience={audience}"
    req = urllib.request.Request(url, headers={"Authorization": f"bearer {request_token}"})  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
            data = json.loads(resp.read().decode())
        value = data.get("value")
        return value if isinstance(value, str) else None
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        print(f"Warning: OIDC token fetch failed: {e}", file=sys.stderr)
        return None


def _exchange_oidc_for_nuget_key(oidc_token: str, nuget_username: str) -> str | None:
    """Exchange a GitHub OIDC token for a short-lived NuGet API key.

    Mirrors the protocol used by the official `NuGet/login@v1` action:
    POST `https://www.nuget.org/api/v2/token` with body
    `{"username": "<nuget-username>", "tokenType": "ApiKey"}` and the
    OIDC token in the `Authorization: Bearer <token>` header. Audience
    on the OIDC token must be `https://www.nuget.org`. Returns None on
    failure; the caller treats that as a hard error.
    """
    url = "https://www.nuget.org/api/v2/token"
    body = json.dumps({"username": nuget_username, "tokenType": "ApiKey"}).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {oidc_token}",
            "User-Agent": "xberg-io-actions/publish-nuget",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            data = json.loads(resp.read().decode())
        api_key = data.get("apiKey") or data.get("api_key")
        return api_key if isinstance(api_key, str) else None
    except urllib.error.HTTPError as e:
        body_text = e.read().decode(errors="replace") if e.fp else ""
        print(
            f"Error: NuGet OIDC token exchange failed: HTTP {e.code}: {e.reason} {body_text}".rstrip(),
            file=sys.stderr,
        )
        return None
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"Error: NuGet OIDC token exchange failed: {e}", file=sys.stderr)
        return None


def _resolve_api_key() -> str | None:
    """Resolve a NuGet API key.

    Priority:
      1. NUGET_API_KEY env var (static, traditional flow)
      2. OIDC trusted publishing (when ACTIONS_ID_TOKEN_REQUEST_* is set)
    """
    static_key = os.environ.get("NUGET_API_KEY", "").strip()
    if static_key:
        print("Using static NUGET_API_KEY")
        return static_key

    nuget_username = os.environ.get("INPUT_NUGET_USER", "").strip()
    if not nuget_username:
        print(
            "Error: NUGET_API_KEY is empty and `nuget-user` input is not set. "
            "OIDC trusted publishing requires the nuget.org username (profile name, not email).",
            file=sys.stderr,
        )
        return None

    print(f"NUGET_API_KEY not set; attempting OIDC trusted-publishing flow as nuget user '{nuget_username}'")
    oidc_token = _fetch_oidc_token()
    if oidc_token is None:
        print(
            "Error: OIDC token unavailable. Either set NUGET_API_KEY or run with `permissions: id-token: write`.",
            file=sys.stderr,
        )
        return None

    api_key = _exchange_oidc_for_nuget_key(oidc_token, nuget_username)
    if api_key is None:
        print(
            "Error: failed to exchange OIDC token for a NuGet API key. Verify the trusted publisher is configured for this repo + workflow.",
            file=sys.stderr,
        )
        return None

    print("Obtained short-lived NuGet API key via OIDC")
    return api_key


def main() -> None:
    packages_dir_str = os.environ.get("INPUT_PACKAGES_DIR", "")
    source_url = os.environ.get("INPUT_SOURCE", "https://api.nuget.org/v3/index.json")
    dry_run = os.environ.get("INPUT_DRY_RUN", "false").lower() == "true"

    if not packages_dir_str:
        print("Error: INPUT_PACKAGES_DIR is required", file=sys.stderr)
        sys.exit(1)

    packages_dir = Path(packages_dir_str)

    if not packages_dir.is_dir():
        print(f"Error: packages directory not found: {packages_dir}", file=sys.stderr)
        sys.exit(1)

    nupkg_files = find_nupkg_files(packages_dir)

    if not nupkg_files:
        print(f"Error: no .nupkg files found in {packages_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Publishing {len(nupkg_files)} NuGet package(s)...")

    api_key = None
    if not dry_run:
        api_key = _resolve_api_key()
        if api_key is None:
            sys.exit(1)

    failed = 0
    published = 0

    for nupkg in nupkg_files:
        name = nupkg.name
        print(f"Publishing {name}...")

        if dry_run:
            print(f"  [dry-run] dotnet nuget push {name}")
            published += 1
            continue

        assert api_key is not None  # noqa: S101 - guarded above when not dry_run
        exit_code, output = _run(
            [
                "dotnet",
                "nuget",
                "push",
                str(nupkg),
                "--api-key",
                api_key,
                "--source",
                source_url,
                "--skip-duplicate",
            ]
        )

        if is_publish_error(exit_code, output):
            print(f"  Error publishing {name}:", file=sys.stderr)
            print(output, file=sys.stderr)
            failed += 1
        else:
            print(f"  Published {name}")
            published += 1

    print(f"Published: {published}, Failed: {failed}")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
