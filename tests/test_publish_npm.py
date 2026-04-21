import importlib.util
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "publish-npm" / "scripts" / "publish.py"


def _import_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


npm_mod = _import_script("publish_npm", _SCRIPT_PATH)


# ---------------------------------------------------------------------------
# validate_inputs
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# build_publish_flags
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# is_already_published
# ---------------------------------------------------------------------------


def test_is_already_published_true():
    assert npm_mod.is_already_published("error: previously published version") is True


def test_is_already_published_cannot_publish():
    assert npm_mod.is_already_published("403 Forbidden: cannot publish over existing version") is True


def test_is_already_published_already_exists():
    assert npm_mod.is_already_published("already exists in the registry") is True


def test_is_already_published_false():
    assert npm_mod.is_already_published("Error: network timeout") is False


# ---------------------------------------------------------------------------
# find_tgz_files
# ---------------------------------------------------------------------------


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
