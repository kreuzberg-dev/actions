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
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

# ~keep `dotnet nuget push --skip-duplicate` turns a 409 Conflict into exit code 0, so a duplicate
# is only visible in the push output. Without this pattern a duplicate is logged as
# "Published <name>" and a release that shipped nothing reads exactly like one that shipped
# everything. That indistinguishability is what made the npm and PyPI stale-artifact releases
# (tree-sitter-language-pack v1.16.0, liter-llm v1.19.0) so slow to diagnose.
ALREADY_PUBLISHED_PATTERN = re.compile(
    r"already exists|already contains",
    re.IGNORECASE,
)

# ~keep A nupkg filename is `<Id>.<Version>.nupkg` and the Id itself is dotted
# (`Xberg.Core.1.2.3.nupkg`), so the Id is matched lazily and the version is anchored as the
# longest trailing dotted-numeric run, plus an optional SemVer prerelease tag.
_NUPKG_FILENAME_RE = re.compile(r"^(?P<id>.+?)\.(?P<version>\d+(?:\.\d+)+(?:-[0-9A-Za-z.-]+)?)\.nupkg$")


def find_nupkg_files(directory: Path) -> list[Path]:
    """Return all .nupkg files found directly in directory (non-recursive)."""
    return sorted(directory.glob("*.nupkg"))


def is_publish_error(exit_code: int, output: str) -> bool:  # noqa: ARG001
    """Return True if the exit code indicates a real publish failure."""
    return exit_code != 0


def is_already_published(output: str) -> bool:
    """Return True if the push output indicates the package was already on the source."""
    return bool(ALREADY_PUBLISHED_PATTERN.search(output))


def parse_nupkg_version(filename: str) -> str | None:
    """Return the version encoded in an `<Id>.<Version>.nupkg` filename, or None."""
    match = _NUPKG_FILENAME_RE.match(filename)
    return match["version"] if match else None


DRY_RUN_TAG_MARKER = "-dryrun-"


def normalize_release_version(version: str) -> str:
    """Strip whitespace and a leading `v` so a tag (`v1.16.0`) compares to a nupkg version.

    ~keep A dry run synthesizes its tag as `<version>-dryrun-<sha>` (see the
    prepare-release-metadata action), a version no manifest will ever declare. Stripping the
    suffix keeps the release-version assertion running on dry runs -- which is the point of a
    dry run -- instead of failing every one of them on a correct checkout. Only the literal
    `-dryrun-` marker is stripped, so a prerelease such as `1.2.3-rc.1` is compared in full.
    """
    normalized = version.strip().removeprefix("v")
    marker_index = normalized.find(DRY_RUN_TAG_MARKER)
    return normalized[:marker_index] if marker_index != -1 else normalized


def assert_packages_match_release(nupkg_files: list[Path], expected_version: str) -> None:
    """Fail before any push when a package carries a version other than the release being published.

    ~keep This guard is what makes the `--skip-duplicate` behaviour below safe, and the two must
    not be collapsed. Treating a duplicate as an idempotent re-run is legitimate ONLY when the
    package's version IS the release version; it is a silent data-loss bug when the package is
    stale. This exact shape shipped two broken releases on sibling registries: tree-sitter-language-pack
    v1.16.0 on npm and liter-llm v1.19.0 on npm and PyPI each published a stale artifact, matched
    the registry's already-published response, and reported success having shipped nothing for the
    tag. publish-nuget had the same hole, widened by `--skip-duplicate` hiding it entirely.

    ~keep Runs as a pre-flight over every package rather than inline per push because nuget.org
    does not allow republishing a version: a stale package caught halfway through has already
    pushed the packages ahead of it, and those cannot be corrected afterwards.
    """
    parsed = [(nupkg.name, parse_nupkg_version(nupkg.name)) for nupkg in nupkg_files]

    # ~keep An unparseable filename fails rather than warns: it is exactly the blind spot the
    # guard exists to close, since an unverifiable package is indistinguishable from a stale one.
    unparseable = sorted(name for name, version in parsed if version is None)
    if unparseable:
        print(
            f"Error: expected-version {expected_version} was supplied but no version could be "
            f"parsed from {', '.join(unparseable)}, so the package(s) cannot be verified",
            file=sys.stderr,
        )
        sys.exit(1)

    # ~keep The unparseable guard above exits on any None, so every entry is non-None here;
    # re-bound into a narrowed list so the declared type says so rather than suppressing it.
    verified: list[tuple[str, str]] = [(name, version) for name, version in parsed if version is not None]
    mismatched = sorted(
        f"{name} carries {version}"
        for name, version in verified
        if normalize_release_version(version) != expected_version
    )
    if mismatched:
        print(
            f"Error: package(s) carry a version other than the release version {expected_version}: "
            f"{'; '.join(mismatched)}",
            file=sys.stderr,
        )
        print(
            "The built packages are stale. Publishing them would ship the wrong version, or be "
            "silently swallowed as a `--skip-duplicate` no-op.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Verified {len(parsed)} package(s) carry the release version {expected_version}")


def warn_expected_version_missing() -> None:
    """Warn that the stale-artifact guard is disabled because no expected-version was supplied."""
    print(
        "::warning::publish-nuget was invoked without `expected-version`; a stale package cannot "
        "be detected and nuget.org's duplicate response will be treated as an idempotent skip. "
        "Pass the release version from the caller to close this gap."
    )


def verify_release_versions(nupkg_files: list[Path], raw_expected_version: str) -> None:
    """Apply the stale-artifact guard, or warn loudly that it has been left disabled.

    ~keep Called before the API-key resolution and before the dry-run branch on purpose: a dry run
    exists to catch a stale build ahead of the real release, so it must apply the same assertion
    the real release does.
    """
    expected_version = normalize_release_version(raw_expected_version)
    if expected_version:
        assert_packages_match_release(nupkg_files, expected_version)
    else:
        warn_expected_version_missing()


def build_push_command(nupkg: Path, api_key: str, source_url: str) -> list[str]:
    """Build the `dotnet nuget push` command line for one package.

    ~keep `--skip-duplicate` is retained deliberately: it is what lets an idempotent re-run of the
    release succeed instead of failing on a 409. What makes it safe is the version pre-flight in
    `assert_packages_match_release` — the package is already proven to carry the release version,
    so a duplicate really is a re-push of this release rather than a stale package standing in for
    it. Dropping either half reintroduces the silent skip.
    """
    return ["dotnet", "nuget", "push", str(nupkg), "--api-key", api_key, "--source", source_url, "--skip-duplicate"]


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

    verify_release_versions(nupkg_files, os.environ.get("INPUT_EXPECTED_VERSION", ""))

    print(f"Publishing {len(nupkg_files)} NuGet package(s)...")

    api_key = None
    if not dry_run:
        api_key = _resolve_api_key()
        if api_key is None:
            sys.exit(1)

    failed = 0
    published = 0
    skipped = 0

    for nupkg in nupkg_files:
        name = nupkg.name
        print(f"Publishing {name}...")

        if dry_run:
            print(f"  [dry-run] dotnet nuget push {name}")
            published += 1
            continue

        assert api_key is not None  # noqa: S101 - guarded above when not dry_run
        exit_code, output = _run(build_push_command(nupkg, api_key, source_url))

        if is_publish_error(exit_code, output):
            print(f"  Error publishing {name}:", file=sys.stderr)
            print(output, file=sys.stderr)
            failed += 1
        elif is_already_published(output):
            # ~keep Reported as a skip, never as a publish. `--skip-duplicate` exits 0 on a
            # duplicate, so claiming "Published" here made a release that shipped nothing look
            # identical in the log to one that shipped everything.
            print(f"  {name} already published, skipping")
            skipped += 1
        else:
            print(f"  Published {name}")
            published += 1

    print(f"Published: {published}, Failed: {failed}, Skipped: {skipped}")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
