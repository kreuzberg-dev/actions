import importlib.util
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "publish-rubygems" / "scripts" / "publish.py"


def _import_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rubygems_mod = _import_script("publish_rubygems", _SCRIPT_PATH)


# ---------------------------------------------------------------------------
# is_already_published
# ---------------------------------------------------------------------------


def test_is_already_published_repushing():
    assert rubygems_mod.is_already_published("Repushing of gem versions is not allowed") is True


def test_is_already_published_already_pushed():
    assert rubygems_mod.is_already_published("The gem my-gem-1.2.3 has already been pushed") is True


def test_is_already_published_false():
    assert rubygems_mod.is_already_published("Error: SSL certificate verification failed") is False


# ---------------------------------------------------------------------------
# find_gem_files
# ---------------------------------------------------------------------------


def test_find_gem_files(tmp_path: Path):
    (tmp_path / "my-gem-1.0.0.gem").write_bytes(b"data")
    (tmp_path / "my-gem-2.0.0.gem").write_bytes(b"data")
    (tmp_path / "README.md").write_text("readme")

    results = rubygems_mod.find_gem_files(tmp_path)
    names = [p.name for p in results]

    assert len(results) == 2
    assert "my-gem-1.0.0.gem" in names
    assert "my-gem-2.0.0.gem" in names


def test_find_gem_files_empty(tmp_path: Path):
    results = rubygems_mod.find_gem_files(tmp_path)
    assert results == []


# ---------------------------------------------------------------------------
# validate_gem_structure
# ---------------------------------------------------------------------------


def test_validate_gem_structure_not_readable(tmp_path: Path):
    missing = tmp_path / "nonexistent.gem"
    result = rubygems_mod.validate_gem_structure(missing)
    assert result is False


def test_validate_gem_structure_empty(tmp_path: Path):
    empty_gem = tmp_path / "empty.gem"
    empty_gem.write_bytes(b"")
    result = rubygems_mod.validate_gem_structure(empty_gem)
    assert result is False
