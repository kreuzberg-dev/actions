import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "publish-pypi" / "scripts" / "publish.py"

spec = importlib.util.spec_from_file_location("publish_pypi", str(_SCRIPT))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


# ---------------------------------------------------------------------------
# find_dist_files
# ---------------------------------------------------------------------------


def test_find_dist_files(tmp_path):
    (tmp_path / "package-1.0.0-py3-none-any.whl").write_text("fake")
    (tmp_path / "package-1.0.0.tar.gz").write_text("fake")

    result = mod.find_dist_files(tmp_path)

    names = {p.name for p in result}
    assert "package-1.0.0-py3-none-any.whl" in names
    assert "package-1.0.0.tar.gz" in names


def test_find_dist_files_empty(tmp_path):
    result = mod.find_dist_files(tmp_path)
    assert result == []


def test_find_dist_files_no_whl(tmp_path):
    (tmp_path / "package-1.0.0.tar.gz").write_text("fake")

    result = mod.find_dist_files(tmp_path)

    assert len(result) == 1
    assert result[0].name == "package-1.0.0.tar.gz"


# ---------------------------------------------------------------------------
# validate_dist_dir
# ---------------------------------------------------------------------------


def test_validate_dist_dir_missing(tmp_path):
    with pytest.raises(SystemExit):
        mod.validate_dist_dir(tmp_path / "nonexistent")


def test_validate_dist_dir_empty(tmp_path):
    empty = tmp_path / "dist"
    empty.mkdir()

    with pytest.raises(SystemExit):
        mod.validate_dist_dir(empty)


def test_validate_dist_dir_success(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "mypackage-1.0.0-py3-none-any.whl").write_text("fake")

    result = mod.validate_dist_dir(dist)

    assert len(result) == 1
    assert result[0].name == "mypackage-1.0.0-py3-none-any.whl"
