#!/usr/bin/env python3
"""Render Homebrew source-formula templates with release-asset SHA256s.

Inputs (env):
  INPUT_TAP_DIR       Path to a checked-out tap (must contain Formula/).
  INPUT_CONFIG_FILE   JSON config path (relative to repo root) describing formulas.
  INPUT_TAG           Release tag (e.g. v3.4.0-rc.42).
  INPUT_VERSION       Semantic version (e.g. 3.4.0-rc.42).
  INPUT_GITHUB_REPO   Source repo for `gh release download` (e.g. org/name).
  INPUT_DRY_RUN       'true' to tolerate missing release/assets with zero-SHA placeholders.
  GH_TOKEN            Token for `gh release download`.

Config schema (JSON):
  {
    "formulas": [
      {
        "name": "html-to-markdown",
        "template": "scripts/publish/html-to-markdown.rb.tmpl",
        "assets": {
          "cli_macos_arm_sha": "cli-aarch64-apple-darwin.tar.gz",
          "ffi_macos_arm_sha": "html-to-markdown-rs-ffi-${tag}-aarch64-apple-darwin.tar.gz"
        }
      }
    ]
  }

Asset filenames may interpolate ${tag} / ${version}.

Template substitution uses Python string.Template ($var / ${var}) with:
  ${tag}, ${version}, plus one $<sha_key>=<hex_digest> per asset entry.

Outputs (GITHUB_OUTPUT):
  formulas-changed   Newline-separated list of formula paths written.
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
    tap_dir: Path,
    cache_dir: Path,
    tag: str,
    version: str,
    github_repo: str,
    dry_run: bool,
) -> str | None:
    """Render a single formula. Returns the written path, or None on failure."""
    name = entry.get("name")
    template = entry.get("template")
    assets = entry.get("assets") or {}
    if not (isinstance(name, str) and isinstance(template, str) and isinstance(assets, dict) and assets):
        print(f"::error::formula entry missing name/template/assets: {entry!r}", file=sys.stderr)
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
            print(f"::error::could not fetch {resolved} for formula {name}", file=sys.stderr)
            return None
        mapping[sha_key] = _compute_sha256(local)

    try:
        rendered = _render_template(template_path, mapping)
    except KeyError as exc:
        print(f"::error::template {template_path} references undefined placeholder: {exc}", file=sys.stderr)
        return None

    target = tap_dir / "Formula" / f"{name}.rb"
    target.write_text(rendered)
    print(f"Wrote {target}")
    return str(target)


def main() -> int:
    tap_dir = Path(_require_env("INPUT_TAP_DIR")).resolve()
    config_file = Path(_require_env("INPUT_CONFIG_FILE")).resolve()
    tag = _require_env("INPUT_TAG")
    version = _require_env("INPUT_VERSION")
    github_repo = _require_env("INPUT_GITHUB_REPO")
    dry_run = os.environ.get("INPUT_DRY_RUN", "false").lower() == "true"

    if not (tap_dir / "Formula").is_dir():
        print(f"::error::{tap_dir}/Formula does not exist", file=sys.stderr)
        return 1
    if not config_file.is_file():
        print(f"::error::config file not found: {config_file}", file=sys.stderr)
        return 1

    try:
        config = json.loads(config_file.read_text())
    except json.JSONDecodeError as exc:
        print(f"::error::config file is not valid JSON: {exc}", file=sys.stderr)
        return 1
    formulas = config.get("formulas") or []
    if not formulas:
        print("::error::config must define at least one formula under 'formulas'", file=sys.stderr)
        return 1

    repo_root = _resolve_repo_root(config_file)
    written: list[str] = []

    with tempfile.TemporaryDirectory(prefix="homebrew-assets-") as tmp:
        cache_dir = Path(tmp)
        for entry in formulas:
            target = _render_one(
                entry,
                repo_root=repo_root,
                tap_dir=tap_dir,
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
            fh.write("formulas-changed<<EOF\n")
            fh.write("\n".join(written))
            fh.write("\nEOF\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
