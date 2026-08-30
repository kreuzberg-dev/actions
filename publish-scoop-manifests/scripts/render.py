#!/usr/bin/env python3
"""Render Scoop app-manifest templates with release-asset SHA256s.

Inputs (env):
  INPUT_BUCKET_DIR    Path to a checked-out Scoop bucket (must contain bucket/).
  INPUT_CONFIG_FILE   JSON config path (relative to repo root) describing manifests.
  INPUT_TAG           Release tag (e.g. v3.4.0-rc.42).
  INPUT_VERSION       Semantic version (e.g. 3.4.0-rc.42).
  INPUT_GITHUB_REPO   Source repo for `gh release download` (e.g. org/name).
  INPUT_DRY_RUN       'true' to tolerate missing release/assets with zero-SHA placeholders.
  GH_TOKEN            Token for `gh release download`.

Config schema (JSON):
  {
    "manifests": [
      {
        "name": "html-to-markdown",
        "template": "scripts/publish/html-to-markdown.json.tmpl",
        "assets": {
          "win_x64_sha": "cli-x86_64-pc-windows-msvc.zip",
          "win_arm64_sha": "cli-${version}-aarch64-pc-windows-msvc.zip"
        }
      }
    ]
  }

Asset filenames may interpolate ${tag} / ${version}.

Template substitution uses Python string.Template ($var / ${var}) with:
  ${tag}, ${version}, plus one $<sha_key>=<hex_digest> per asset entry.

Scoop's own `autoupdate` blocks contain a literal `$version` that Scoop expands at
update time. Write those as `$$version` in the template — string.Template collapses
`$$` to a single `$`, so the published manifest keeps Scoop's placeholder intact. An
unescaped `$version` inside an autoupdate URL would be replaced with this release's
version and silently freeze autoupdate on it; an unescaped unknown `$foo` raises
KeyError and fails the render loudly.

Outputs (GITHUB_OUTPUT):
  manifests-changed   Newline-separated list of manifest paths written.
"""

from __future__ import annotations

import hashlib
import json
import os
import string
import subprocess
import sys
import tempfile
from pathlib import Path

ZERO_SHA = "0" * 64

# Scoop requires manifests at `bucket/<app>.json` in the bucket repo root; both the
# directory and the extension are part of its discovery contract, not preferences.
MANIFEST_DIR = "bucket"
MANIFEST_SUFFIX = ".json"


def _require_env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        print(f"::error::missing required env var: {name}", file=sys.stderr)
        sys.exit(1)
    return value


def _compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _download_asset(repo: str, tag: str, asset: str, out_dir: Path) -> Path | None:
    """Download a single release asset via gh. Returns the local path or None on failure."""
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = ["gh", "release", "download", tag, "-R", repo, "-p", asset, "-D", str(out_dir), "--clobber"]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        print(f"::warning::failed to download {asset} from {repo}@{tag}: {proc.stderr.strip()}", file=sys.stderr)
        return None
    local = out_dir / asset
    if not local.is_file():
        print(f"::warning::asset {asset} not present after download", file=sys.stderr)
        return None
    return local


def _interpolate_asset_name(name: str, tag: str, version: str) -> str:
    """Resolve ${tag} / ${version} placeholders in asset filenames."""
    return string.Template(name).safe_substitute(tag=tag, version=version)


def _render_template(template_path: Path, mapping: dict[str, str]) -> str:
    raw = template_path.read_text()
    return string.Template(raw).substitute(mapping)


def _resolve_repo_root(config_file: Path) -> Path:
    workspace = os.environ.get("GITHUB_WORKSPACE")
    if workspace:
        return Path(workspace).resolve()
    repo_root = config_file.parent
    while not (repo_root / ".git").exists() and repo_root != repo_root.parent:
        repo_root = repo_root.parent
    return repo_root


def _render_one(
    entry: dict[str, object],
    *,
    repo_root: Path,
    bucket_dir: Path,
    cache_dir: Path,
    tag: str,
    version: str,
    github_repo: str,
    dry_run: bool,
) -> str | None:
    """Render a single manifest. Returns the written path, or None on failure."""
    name = entry.get("name")
    template = entry.get("template")
    assets = entry.get("assets") or {}
    if not (isinstance(name, str) and isinstance(template, str) and isinstance(assets, dict) and assets):
        print(f"::error::manifest entry missing name/template/assets: {entry!r}", file=sys.stderr)
        return None

    template_path = repo_root / template
    if not template_path.is_file():
        print(f"::error::template not found: {template_path}", file=sys.stderr)
        return None

    mapping: dict[str, str] = {"tag": tag, "version": version}
    for sha_key, asset_name_tmpl in assets.items():
        resolved = _interpolate_asset_name(str(asset_name_tmpl), tag=tag, version=version)
        local = _download_asset(github_repo, tag, resolved, cache_dir)
        if local is None:
            if dry_run:
                print(f"::warning::dry-run: substituting zero SHA for missing {resolved}")
                mapping[sha_key] = ZERO_SHA
                continue
            print(f"::error::could not fetch {resolved} for manifest {name}", file=sys.stderr)
            return None
        mapping[sha_key] = _compute_sha256(local)

    try:
        rendered = _render_template(template_path, mapping)
    except KeyError as exc:
        print(f"::error::template {template_path} references undefined placeholder: {exc}", file=sys.stderr)
        return None

    # Parse before writing: a template that renders to malformed JSON must not reach the
    # bucket, where it would break `scoop update` for every app, not just this one.
    try:
        json.loads(rendered)
    except json.JSONDecodeError as exc:
        print(f"::error::template {template_path} rendered invalid JSON: {exc}", file=sys.stderr)
        return None

    target = bucket_dir / MANIFEST_DIR / f"{name}{MANIFEST_SUFFIX}"
    target.write_text(rendered)
    print(f"Wrote {target}")
    return str(target)


def main() -> int:
    bucket_dir = Path(_require_env("INPUT_BUCKET_DIR")).resolve()
    config_file = Path(_require_env("INPUT_CONFIG_FILE")).resolve()
    tag = _require_env("INPUT_TAG")
    version = _require_env("INPUT_VERSION")
    github_repo = _require_env("INPUT_GITHUB_REPO")
    dry_run = os.environ.get("INPUT_DRY_RUN", "false").lower() == "true"

    if not (bucket_dir / MANIFEST_DIR).is_dir():
        print(f"::error::{bucket_dir}/{MANIFEST_DIR} does not exist", file=sys.stderr)
        return 1
    if not config_file.is_file():
        print(f"::error::config file not found: {config_file}", file=sys.stderr)
        return 1

    try:
        config = json.loads(config_file.read_text())
    except json.JSONDecodeError as exc:
        print(f"::error::config file is not valid JSON: {exc}", file=sys.stderr)
        return 1
    manifests = config.get("manifests") or []
    if not manifests:
        print("::error::config must define at least one manifest under 'manifests'", file=sys.stderr)
        return 1

    repo_root = _resolve_repo_root(config_file)
    written: list[str] = []

    with tempfile.TemporaryDirectory(prefix="scoop-assets-") as tmp:
        cache_dir = Path(tmp)
        for entry in manifests:
            target = _render_one(
                entry,
                repo_root=repo_root,
                bucket_dir=bucket_dir,
                cache_dir=cache_dir,
                tag=tag,
                version=version,
                github_repo=github_repo,
                dry_run=dry_run,
            )
            if target is None:
                return 1
            written.append(target)

    out_file = os.environ.get("GITHUB_OUTPUT")
    if out_file:
        with Path(out_file).open("a") as fh:
            fh.write("manifests-changed<<EOF\n")
            fh.write("\n".join(written))
            fh.write("\nEOF\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
