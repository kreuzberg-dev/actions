"""Tests for the publish-scoop-manifests action's render script."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from types import ModuleType

_ROOT = Path(__file__).resolve().parents[1]
_ACTION = _ROOT / "publish-scoop-manifests"
_SCRIPT = _ACTION / "scripts" / "render.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("render_scoop", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _stage_repo(tmp_path: Path, template_body: str, assets: dict[str, str]) -> tuple[Path, Path, Path]:
    """Build a fake source repo + bucket checkout. Returns (bucket_dir, repo_root, config_file)."""
    bucket_dir = tmp_path / "scoop-bucket"
    (bucket_dir / "bucket").mkdir(parents=True)

    repo_root = tmp_path / "source"
    (repo_root / ".git").mkdir(parents=True)
    template_dir = repo_root / "scripts" / "publish"
    template_dir.mkdir(parents=True)
    (template_dir / "demo.json.tmpl").write_text(template_body)

    config_file = template_dir / "scoop.json"
    config_file.write_text(
        json.dumps(
            {
                "manifests": [
                    {
                        "name": "demo",
                        "template": "scripts/publish/demo.json.tmpl",
                        "assets": assets,
                    }
                ]
            }
        )
    )
    return bucket_dir, repo_root, config_file


def _set_env(
    monkeypatch: pytest.MonkeyPatch,
    *,
    bucket_dir: Path,
    repo_root: Path,
    config_file: Path,
    github_output: Path,
    dry_run: str = "false",
) -> None:
    monkeypatch.setenv("INPUT_BUCKET_DIR", str(bucket_dir))
    monkeypatch.setenv("INPUT_CONFIG_FILE", str(config_file))
    monkeypatch.setenv("INPUT_TAG", "v9.9.9")
    monkeypatch.setenv("INPUT_VERSION", "9.9.9")
    monkeypatch.setenv("INPUT_GITHUB_REPO", "xberg-io/demo")
    monkeypatch.setenv("INPUT_DRY_RUN", dry_run)
    monkeypatch.setenv("GITHUB_WORKSPACE", str(repo_root))
    monkeypatch.setenv("GITHUB_OUTPUT", str(github_output))


_MINIMAL_TEMPLATE = """{
  "version": "${version}",
  "architecture": {
    "64bit": {
      "url": "https://example.invalid/${tag}/demo.zip",
      "hash": "${win_x64_sha}"
    }
  },
  "bin": "demo.exe"
}
"""


def test_action_yml_calls_render_script() -> None:
    action = (_ACTION / "action.yml").read_text()
    assert "python3" in action
    assert "scripts/render.py" in action
    assert "ensure-gh@v1" in action
    assert "dry-run:" in action
    assert "manifests-changed" in action


def test_zero_sha_is_64_hex_zeros() -> None:
    module = _load_module()
    assert module.ZERO_SHA == "0" * 64


def test_manifest_path_constants_match_scoop_layout() -> None:
    module = _load_module()
    assert module.MANIFEST_DIR == "bucket"
    assert module.MANIFEST_SUFFIX == ".json"


def test_asset_name_interpolation_resolves_tag_and_version() -> None:
    module = _load_module()
    resolved = module._interpolate_asset_name("cli-${version}-x64.zip", tag="v1.2.3", version="1.2.3")
    assert resolved == "cli-1.2.3-x64.zip"


def test_asset_name_interpolation_leaves_unknown_placeholders_alone() -> None:
    module = _load_module()
    resolved = module._interpolate_asset_name("cli-$unknown.zip", tag="v1.2.3", version="1.2.3")
    assert resolved == "cli-$unknown.zip"


def test_sha256_matches_hashlib(tmp_path: Path) -> None:
    module = _load_module()
    payload = b"scoop manifest bytes"
    target = tmp_path / "asset.zip"
    target.write_bytes(payload)
    assert module._compute_sha256(target) == hashlib.sha256(payload).hexdigest()


def test_template_undefined_placeholder_raises(tmp_path: Path) -> None:
    module = _load_module()
    template = tmp_path / "demo.json.tmpl"
    template.write_text('{"version": "${version}", "hash": "${missing_sha}"}')
    with pytest.raises(KeyError):
        module._render_template(template, {"version": "1.0.0"})


def test_main_writes_manifest_and_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    bucket_dir, repo_root, config_file = _stage_repo(
        tmp_path, _MINIMAL_TEMPLATE, {"win_x64_sha": "demo-x86_64-pc-windows-msvc.zip"}
    )
    asset_bytes = b"zip bytes"

    def _fake_download(_repo: str, _tag: str, asset: str, out_dir: Path) -> Path:
        out_dir.mkdir(parents=True, exist_ok=True)
        local = out_dir / asset
        local.write_bytes(asset_bytes)
        return local

    monkeypatch.setattr(module, "_download_asset", _fake_download)
    github_output = tmp_path / "github_output.txt"
    _set_env(
        monkeypatch,
        bucket_dir=bucket_dir,
        repo_root=repo_root,
        config_file=config_file,
        github_output=github_output,
    )

    assert module.main() == 0

    written = bucket_dir / "bucket" / "demo.json"
    manifest: dict[str, Any] = json.loads(written.read_text())
    assert manifest["version"] == "9.9.9"
    assert manifest["architecture"]["64bit"]["hash"] == hashlib.sha256(asset_bytes).hexdigest()
    assert manifest["architecture"]["64bit"]["url"] == "https://example.invalid/v9.9.9/demo.zip"
    assert "manifests-changed<<EOF" in github_output.read_text()
    assert str(written) in github_output.read_text()


def test_main_dry_run_substitutes_zero_sha(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    bucket_dir, repo_root, config_file = _stage_repo(
        tmp_path, _MINIMAL_TEMPLATE, {"win_x64_sha": "demo-x86_64-pc-windows-msvc.zip"}
    )
    monkeypatch.setattr(module, "_download_asset", lambda *_a, **_kw: None)
    _set_env(
        monkeypatch,
        bucket_dir=bucket_dir,
        repo_root=repo_root,
        config_file=config_file,
        github_output=tmp_path / "github_output.txt",
        dry_run="true",
    )

    assert module.main() == 0
    manifest = json.loads((bucket_dir / "bucket" / "demo.json").read_text())
    assert manifest["architecture"]["64bit"]["hash"] == "0" * 64


def test_main_fails_when_asset_missing_and_not_dry_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load_module()
    bucket_dir, repo_root, config_file = _stage_repo(
        tmp_path, _MINIMAL_TEMPLATE, {"win_x64_sha": "demo-x86_64-pc-windows-msvc.zip"}
    )
    monkeypatch.setattr(module, "_download_asset", lambda *_a, **_kw: None)
    _set_env(
        monkeypatch,
        bucket_dir=bucket_dir,
        repo_root=repo_root,
        config_file=config_file,
        github_output=tmp_path / "github_output.txt",
    )

    assert module.main() == 1
    assert "could not fetch" in capsys.readouterr().err
    assert not (bucket_dir / "bucket" / "demo.json").exists()


def test_main_errors_when_bucket_dir_has_no_bucket_subdir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load_module()
    bucket_dir, repo_root, config_file = _stage_repo(tmp_path, _MINIMAL_TEMPLATE, {"win_x64_sha": "demo.zip"})
    (bucket_dir / "bucket").rmdir()
    _set_env(
        monkeypatch,
        bucket_dir=bucket_dir,
        repo_root=repo_root,
        config_file=config_file,
        github_output=tmp_path / "github_output.txt",
    )

    assert module.main() == 1
    assert "does not exist" in capsys.readouterr().err


def test_main_rejects_template_that_renders_invalid_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A trailing comma survives templating but breaks every `scoop update` in the bucket."""
    module = _load_module()
    broken = '{\n  "version": "${version}",\n}\n'
    bucket_dir, repo_root, config_file = _stage_repo(tmp_path, broken, {"win_x64_sha": "demo.zip"})
    monkeypatch.setattr(module, "_download_asset", lambda *_a, **_kw: None)
    _set_env(
        monkeypatch,
        bucket_dir=bucket_dir,
        repo_root=repo_root,
        config_file=config_file,
        github_output=tmp_path / "github_output.txt",
        dry_run="true",
    )

    assert module.main() == 1
    assert "rendered invalid JSON" in capsys.readouterr().err
    assert not (bucket_dir / "bucket" / "demo.json").exists()


def test_autoupdate_dollar_version_survives_rendering(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Scoop's literal `$version` must reach the published manifest unexpanded.

    `$$version` in the template collapses to `$version`. Without the escape, string.Template
    would substitute this release's version and silently freeze autoupdate on it — every later
    release would keep resolving the same URL.
    """
    module = _load_module()
    template = """{
  "version": "${version}",
  "architecture": { "64bit": { "url": "https://example.invalid/${tag}/demo.zip", "hash": "${win_x64_sha}" } },
  "autoupdate": {
    "architecture": {
      "64bit": {
        "url": "https://example.invalid/v$$version/demo.zip",
        "extract_dir": "demo-$$version-x86_64-pc-windows-msvc"
      }
    }
  }
}
"""
    bucket_dir, repo_root, config_file = _stage_repo(tmp_path, template, {"win_x64_sha": "demo.zip"})
    monkeypatch.setattr(module, "_download_asset", lambda *_a, **_kw: None)
    _set_env(
        monkeypatch,
        bucket_dir=bucket_dir,
        repo_root=repo_root,
        config_file=config_file,
        github_output=tmp_path / "github_output.txt",
        dry_run="true",
    )

    assert module.main() == 0
    autoupdate = json.loads((bucket_dir / "bucket" / "demo.json").read_text())["autoupdate"]
    arch = autoupdate["architecture"]["64bit"]
    assert arch["url"] == "https://example.invalid/v$version/demo.zip"
    assert arch["extract_dir"] == "demo-$version-x86_64-pc-windows-msvc"
    assert "9.9.9" not in json.dumps(autoupdate)
