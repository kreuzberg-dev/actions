import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "upload-release-assets" / "scripts" / "upload_assets.py"


def _import_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


upload_assets = _import_script("upload_assets", _SCRIPT_PATH)


class _Result:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _asset(tmp_path: Path) -> Path:
    path = tmp_path / "pkg.tar.gz"
    path.write_bytes(b"payload")
    return path


def _view_result(name: str, size: int, state: str = "uploaded") -> _Result:
    return _Result(0, json.dumps({"assets": [{"name": name, "size": size, "state": state}]}))


def test_upload_one_treats_already_exists_as_success_when_remote_size_matches(tmp_path, monkeypatch):
    """A lost response makes gh retry and hit 422; the asset landed, so the job must not fail."""
    asset = _asset(tmp_path)
    size = asset.stat().st_size
    seen: list[list[str]] = []

    def fake_run(cmd, **_kwargs):
        seen.append(cmd)
        if cmd[:3] == ["gh", "release", "upload"]:
            return _Result(1, "", "HTTP 422: Validation Failed\nReleaseAsset.name already exists")
        return _view_result(asset.name, size)

    monkeypatch.setattr(subprocess, "run", fake_run)

    upload_assets.upload_one("v1.2.3", asset, True)

    assert any(cmd[:3] == ["gh", "release", "view"] for cmd in seen)


def test_upload_one_raises_when_remote_asset_size_differs(tmp_path, monkeypatch):
    asset = _asset(tmp_path)

    def fake_run(cmd, **_kwargs):
        if cmd[:3] == ["gh", "release", "upload"]:
            return _Result(1, "", "boom")
        return _view_result(asset.name, asset.stat().st_size + 1)

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(upload_assets.time, "sleep", lambda _seconds: None)

    with pytest.raises(subprocess.CalledProcessError):
        upload_assets.upload_one("v1.2.3", asset, True)


def test_upload_one_retries_transient_failure_then_succeeds(tmp_path, monkeypatch):
    asset = _asset(tmp_path)
    uploads = {"count": 0}

    def fake_run(cmd, **_kwargs):
        if cmd[:3] == ["gh", "release", "upload"]:
            uploads["count"] += 1
            if uploads["count"] == 1:
                return _Result(1, "", "transient network error")
            return _Result(0)
        return _Result(0, json.dumps({"assets": []}))

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(upload_assets.time, "sleep", lambda _seconds: None)

    upload_assets.upload_one("v1.2.3", asset, True)

    assert uploads["count"] == 2


def test_remote_asset_size_ignores_incomplete_upload(tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: _view_result("pkg.tar.gz", 7, state="starter"))

    assert upload_assets.remote_asset_size("v1.2.3", "pkg.tar.gz") is None
