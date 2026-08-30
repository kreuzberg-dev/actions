#!/usr/bin/env python3
"""Package and push a Helm chart to an OCI registry.

Reads inputs from environment variables (composite action contract):

    INPUT_CHART_PATH     Path to chart directory
    INPUT_VERSION        Semver chart version (no leading 'v')
    INPUT_APP_VERSION    Optional appVersion (defaults to version)
    INPUT_REGISTRY       Full OCI URL (e.g. oci://ghcr.io/org/charts)
    INPUT_USERNAME       Registry username
    INPUT_PASSWORD       Registry password / token
    INPUT_DRY_RUN        'true' to skip login and push

Stamps version + appVersion in Chart.yaml, runs `helm dependency build`,
`helm package`, and `helm push`. Detects "already exists" output from
`helm push` and exits 0 with skipped=true (idempotency contract).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

ALREADY_EXISTS_PATTERN = re.compile(
    r"already exists|conflict|cannot push.*exists",
    re.IGNORECASE,
)

SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")


def validate_version(version: str) -> None:
    """Reject versions that aren't valid semver or have a leading 'v'."""
    if not version:
        print("Error: version is required", file=sys.stderr)
        sys.exit(1)
    if version.startswith("v"):
        print(
            f"Error: version must not start with 'v' (got {version!r}); strip the prefix in the caller workflow",
            file=sys.stderr,
        )
        sys.exit(1)
    if not SEMVER_PATTERN.match(version):
        print(f"Error: version {version!r} is not valid semver", file=sys.stderr)
        sys.exit(1)


def stamp_chart_yaml(chart_yaml: Path, version: str, app_version: str) -> None:
    """Rewrite the version and appVersion fields in Chart.yaml in place."""
    if not chart_yaml.is_file():
        print(f"Error: Chart.yaml not found at {chart_yaml}", file=sys.stderr)
        sys.exit(1)

    text = chart_yaml.read_text()
    text = re.sub(r"^version:.*$", f"version: {version}", text, count=1, flags=re.MULTILINE)
    text = re.sub(
        r"^appVersion:.*$",
        f'appVersion: "{app_version}"',
        text,
        count=1,
        flags=re.MULTILINE,
    )
    chart_yaml.write_text(text)
    print(f"Stamped {chart_yaml}: version={version}, appVersion={app_version}")


def extract_registry_host(registry_url: str) -> str:
    """Extract the host part from an oci:// URL for `helm registry login`."""
    if not registry_url.startswith("oci://"):
        print(
            f"Error: registry must start with 'oci://' (got {registry_url!r})",
            file=sys.stderr,
        )
        sys.exit(1)
    parsed = urlparse(registry_url)
    if not parsed.netloc:
        print(f"Error: could not extract host from {registry_url!r}", file=sys.stderr)
        sys.exit(1)
    return parsed.netloc


def is_already_published(output: str) -> bool:
    """Return True if helm push output indicates the chart version already exists."""
    return bool(ALREADY_EXISTS_PATTERN.search(output))


def write_outputs(**outputs: str) -> None:
    """Append key=value pairs to GITHUB_OUTPUT."""
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        for key, value in outputs.items():
            print(f"::set-output name={key}::{value}")
        return
    with Path(output_path).open("a") as fh:
        for key, value in outputs.items():
            fh.write(f"{key}={value}\n")


def _run(cmd: list[str], cwd: Path | None = None) -> tuple[int, str]:
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, check=False)
    return result.returncode, result.stdout + result.stderr


def _run_or_exit(argv: list[str], failure_message: str) -> None:
    code, output = _run(argv)
    if code != 0:
        print(failure_message, file=sys.stderr)
        print(output, file=sys.stderr)
        sys.exit(1)


def _package_chart(chart_path: Path, version: str) -> Path:
    """Build dependencies, package the chart, and return the resulting tarball."""
    print(f"Building chart dependencies for {chart_path}")
    _run_or_exit(["helm", "dependency", "build", "--skip-refresh", str(chart_path)], "helm dependency build failed:")

    print(f"Packaging {chart_path}")
    _run_or_exit(["helm", "package", str(chart_path)], "helm package failed:")

    cwd = Path.cwd()
    matches = sorted(cwd.glob(f"*-{version}.tgz"))
    if not matches:
        print(f"Error: packaged chart not found in {cwd} (expected *-{version}.tgz)", file=sys.stderr)
        sys.exit(1)
    tarball = matches[-1].resolve()
    print(f"Packaged: {tarball}")
    return tarball


def _registry_login(registry: str, username: str, password: str) -> None:
    host = extract_registry_host(registry)
    print(f"Logging in to {host}")
    login = subprocess.run(
        ["helm", "registry", "login", "-u", username, "--password-stdin", host],
        input=password,
        text=True,
        capture_output=True,
        check=False,
    )
    if login.returncode != 0:
        print("helm registry login failed:", file=sys.stderr)
        print(login.stdout + login.stderr, file=sys.stderr)
        sys.exit(1)


def _push_chart(tarball: Path, registry: str, version: str) -> None:
    print(f"Pushing {tarball.name} to {registry}")
    code, output = _run(["helm", "push", str(tarball), registry])
    if code == 0:
        print("Pushed successfully")
        write_outputs(published="true", skipped="false", **{"chart-tarball": str(tarball)})
        return

    if is_already_published(output):
        print(f"Version {version} already exists in {registry}, skipping")
        write_outputs(published="false", skipped="true", **{"chart-tarball": str(tarball)})
        return

    print("helm push failed:", file=sys.stderr)
    print(output, file=sys.stderr)
    sys.exit(1)


def main() -> None:
    chart_path = Path(os.environ.get("INPUT_CHART_PATH", ""))
    version = os.environ.get("INPUT_VERSION", "").strip()
    app_version = os.environ.get("INPUT_APP_VERSION", "").strip() or version
    registry = os.environ.get("INPUT_REGISTRY", "").strip()
    username = os.environ.get("INPUT_USERNAME", "")
    password = os.environ.get("INPUT_PASSWORD", "")
    dry_run = os.environ.get("INPUT_DRY_RUN", "false").lower() == "true"

    validate_version(version)
    if app_version != version:
        validate_version(app_version)

    if not chart_path.is_dir():
        print(f"Error: chart path {chart_path} is not a directory", file=sys.stderr)
        sys.exit(1)

    chart_yaml = chart_path / "Chart.yaml"
    stamp_chart_yaml(chart_yaml, version, app_version)

    tarball = _package_chart(chart_path, version)

    if dry_run:
        print("Dry run — skipping registry login and push")
        write_outputs(published="false", skipped="false", **{"chart-tarball": str(tarball)})
        return

    if not registry or not username or not password:
        print("Error: registry, username, and password are required (unless dry-run=true)", file=sys.stderr)
        sys.exit(1)

    _registry_login(registry, username, password)
    _push_chart(tarball, registry, version)


if __name__ == "__main__":
    main()
