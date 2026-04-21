import importlib.util
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "publish-nuget" / "scripts" / "publish.py"


def _import_script(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


nuget_mod = _import_script("publish_nuget", _SCRIPT_PATH)


# ---------------------------------------------------------------------------
# find_nupkg_files
# ---------------------------------------------------------------------------


def test_find_nupkg_files(tmp_path):
    (tmp_path / "package.nupkg").write_text("fake")
    (tmp_path / "other.nupkg").write_text("fake")
    (tmp_path / "readme.txt").write_text("not a nupkg")

    result = nuget_mod.find_nupkg_files(tmp_path)

    assert len(result) == 2
    assert all(p.suffix == ".nupkg" for p in result)
    assert {p.name for p in result} == {"package.nupkg", "other.nupkg"}


def test_find_nupkg_files_empty(tmp_path):
    result = nuget_mod.find_nupkg_files(tmp_path)
    assert result == []


# ---------------------------------------------------------------------------
# is_publish_error
# ---------------------------------------------------------------------------


def test_is_publish_error_success():
    assert nuget_mod.is_publish_error(0, "Package pushed successfully.") is False


def test_is_publish_error_failure():
    assert nuget_mod.is_publish_error(1, "Error: some unexpected failure occurred") is True
