import importlib.util
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "publish-crates" / "scripts" / "publish.py"


def _import_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


crates_mod = _import_script("publish_crates", _SCRIPT_PATH)


# ---------------------------------------------------------------------------
# is_already_published
# ---------------------------------------------------------------------------


def test_is_already_published_uploaded():
    assert crates_mod.is_already_published("error: crate version has already uploaded") is True


def test_is_already_published_exists():
    assert crates_mod.is_already_published("error: already exists in the registry") is True


def test_is_already_published_false():
    assert crates_mod.is_already_published("error: could not find `Cargo.toml`") is False


# ---------------------------------------------------------------------------
# build_manifest_args
# ---------------------------------------------------------------------------


def test_build_manifest_args_empty():
    assert crates_mod.build_manifest_args("") == []


def test_build_manifest_args_set():
    result = crates_mod.build_manifest_args("Cargo.toml")
    assert result == ["--manifest-path", "Cargo.toml"]


# ---------------------------------------------------------------------------
# parse_crate_list
# ---------------------------------------------------------------------------


def test_parse_crate_list():
    result = crates_mod.parse_crate_list("crate1 crate2")
    assert result == ["crate1", "crate2"]


def test_parse_crate_list_extra_whitespace():
    result = crates_mod.parse_crate_list("  crate1   crate2  ")
    assert result == ["crate1", "crate2"]


def test_parse_crate_list_single():
    result = crates_mod.parse_crate_list("only-one")
    assert result == ["only-one"]
