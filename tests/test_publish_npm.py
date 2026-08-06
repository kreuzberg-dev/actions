import importlib.util
import io
import json
import tarfile
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "publish-npm" / "scripts" / "publish.py"


def _import_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


npm_mod = _import_script("publish_npm", _SCRIPT_PATH)


def test_validate_inputs_both_set():
    with pytest.raises(SystemExit) as exc_info:
        npm_mod.validate_inputs("packages/", "package/")
    assert exc_info.value.code == 1


def test_validate_inputs_neither_set():
    with pytest.raises(SystemExit) as exc_info:
        npm_mod.validate_inputs("", "")
    assert exc_info.value.code == 1


def test_validate_inputs_packages_dir():
    result = npm_mod.validate_inputs("packages/", "")
    assert result == "tgz"


def test_validate_inputs_package_dir():
    result = npm_mod.validate_inputs("", "package/")
    assert result == "dir"


def test_build_publish_flags_default():
    flags = npm_mod.build_publish_flags("public", "latest", provenance=True, dry_run=False)
    assert "--access" in flags
    assert "public" in flags
    assert "--tag" in flags
    assert "latest" in flags
    assert "--ignore-scripts" in flags
    assert "--provenance" in flags
    assert "--dry-run" not in flags


def test_build_publish_flags_no_provenance():
    flags = npm_mod.build_publish_flags("public", "latest", provenance=False, dry_run=False)
    assert "--provenance" not in flags


def test_build_publish_flags_dry_run():
    flags = npm_mod.build_publish_flags("public", "latest", provenance=False, dry_run=True)
    assert "--dry-run" in flags


def test_is_already_published_true():
    assert npm_mod.is_already_published("error: previously published version") is True


def test_is_already_published_cannot_publish():
    assert npm_mod.is_already_published("403 Forbidden: cannot publish over existing version") is True


def test_is_already_published_false():
    assert npm_mod.is_already_published("Error: network timeout") is False


def test_sigstore_entry_already_exists_is_not_already_published():
    """A Rekor conflict must not be read as a version conflict — it means the publish failed."""
    output = "npm error 409 Conflict - POST https://rekor.sigstore.dev/api/v1/log/entries - entry already exists"
    assert npm_mod.is_already_published(output) is False


def test_find_tgz_files(tmp_path: Path):
    (tmp_path / "pkg-1.0.0.tgz").write_bytes(b"data")
    (tmp_path / "pkg-2.0.0.tgz").write_bytes(b"data")
    (tmp_path / "README.md").write_text("readme")

    results = npm_mod.find_tgz_files(tmp_path)
    names = [p.name for p in results]

    assert len(results) == 2
    assert "pkg-1.0.0.tgz" in names
    assert "pkg-2.0.0.tgz" in names


def test_find_tgz_files_empty(tmp_path: Path):
    results = npm_mod.find_tgz_files(tmp_path)
    assert results == []


def _make_tgz(path: Path, package_json: dict, *, with_node: bool = False) -> Path:
    """Write a minimal npm-style .tgz (members under `package/`)."""
    with tarfile.open(path, "w:gz") as tar:
        raw = json.dumps(package_json).encode("utf-8")
        info = tarfile.TarInfo("package/package.json")
        info.size = len(raw)
        tar.addfile(info, io.BytesIO(raw))
        if with_node:
            blob = b"\x00binary"
            ninfo = tarfile.TarInfo("package/index.node")
            ninfo.size = len(blob)
            tar.addfile(ninfo, io.BytesIO(blob))
    return path


def _should_skip(tgz: Path) -> bool:
    return npm_mod.is_platform_package(tgz) and not npm_mod.has_native_binding(tgz)


def test_platform_package_with_os_and_cpu(tmp_path: Path):
    tgz = _make_tgz(tmp_path / "p-linux-x64-gnu.tgz", {"name": "@s/p-linux-x64-gnu", "os": ["linux"], "cpu": ["x64"]})
    assert npm_mod.is_platform_package(tgz) is True


def test_umbrella_package_has_no_os_or_cpu(tmp_path: Path):
    tgz = _make_tgz(tmp_path / "p.tgz", {"name": "@s/p", "optionalDependencies": {"@s/p-linux-x64-gnu": "1.0.0"}})
    assert npm_mod.is_platform_package(tgz) is False


def test_umbrella_package_is_published_not_skipped(tmp_path: Path):
    tgz = _make_tgz(tmp_path / "p.tgz", {"name": "@s/p", "optionalDependencies": {"@s/p-linux-x64-gnu": "1.0.0"}})
    assert _should_skip(tgz) is False


def test_platform_stub_without_binary_is_skipped(tmp_path: Path):
    tgz = _make_tgz(tmp_path / "p-linux-x64-musl.tgz", {"name": "@s/p-linux-x64-musl", "os": ["linux"], "cpu": ["x64"]})
    assert _should_skip(tgz) is True


def test_platform_package_with_binary_is_published(tmp_path: Path):
    tgz = _make_tgz(
        tmp_path / "p-linux-x64-gnu.tgz",
        {"name": "@s/p-linux-x64-gnu", "os": ["linux"], "cpu": ["x64"]},
        with_node=True,
    )
    assert _should_skip(tgz) is False


def test_read_package_identity(tmp_path: Path):
    tgz = _make_tgz(tmp_path / "p.tgz", {"name": "@s/p", "version": "1.2.3"})
    assert npm_mod.read_package_identity(tgz) == ("@s/p", "1.2.3")


def test_read_package_identity_missing_version(tmp_path: Path):
    tgz = _make_tgz(tmp_path / "p.tgz", {"name": "@s/p"})
    assert npm_mod.read_package_identity(tgz) is None


def test_read_package_identity_unreadable(tmp_path: Path):
    corrupt = tmp_path / "p.tgz"
    corrupt.write_bytes(b"not a tarball")
    assert npm_mod.read_package_identity(corrupt) is None


def test_registry_has_version_true(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(npm_mod.urllib.request, "urlopen", _fake_urlopen(200))
    assert npm_mod.registry_has_version("@s/p", "1.2.3") is True


def test_registry_has_version_gives_up_on_404(monkeypatch: pytest.MonkeyPatch):
    """A version that never lands must be reported as absent rather than retried forever."""
    monkeypatch.setattr(npm_mod, "REGISTRY_CHECK_BACKOFF_SECONDS", 0)
    monkeypatch.setattr(npm_mod.urllib.request, "urlopen", _fake_urlopen(404))
    assert npm_mod.registry_has_version("@s/p", "1.2.3") is False


def _fake_urlopen(status: int):
    """Build a urlopen stand-in returning `status`, raising HTTPError for error codes."""

    class _Response:
        def __init__(self) -> None:
            self.status = status

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> bool:
            return False

    def _urlopen(request, timeout=None):  # noqa: ARG001
        if status >= 400:
            raise npm_mod.urllib.error.HTTPError(request.full_url, status, "err", {}, None)
        return _Response()

    return _urlopen
