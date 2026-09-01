import importlib.util
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "publish-rubygems" / "scripts" / "publish.py"


def _import_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rubygems_mod = _import_script("publish_rubygems", _SCRIPT_PATH)


def test_is_already_published_repushing():
    assert rubygems_mod.is_already_published("Repushing of gem versions is not allowed") is True


def test_is_already_published_already_pushed():
    assert rubygems_mod.is_already_published("The gem my-gem-1.2.3 has already been pushed") is True


def test_is_already_published_false():
    assert rubygems_mod.is_already_published("Error: SSL certificate verification failed") is False


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


def test_validate_gem_structure_not_readable(tmp_path: Path):
    missing = tmp_path / "nonexistent.gem"
    result = rubygems_mod.validate_gem_structure(missing)
    assert result is False


def test_validate_gem_structure_empty(tmp_path: Path):
    empty_gem = tmp_path / "empty.gem"
    empty_gem.write_bytes(b"")
    result = rubygems_mod.validate_gem_structure(empty_gem)
    assert result is False


def test_parse_gem_version_from_a_plain_filename():
    assert rubygems_mod.parse_gem_version("liter_llm-1.19.0.gem") == "1.19.0"


def test_parse_gem_version_from_a_dashed_gem_name():
    """A hyphen in the gem name must not be mistaken for the name/version separator."""
    assert rubygems_mod.parse_gem_version("my-gem-1.2.3.gem") == "1.2.3"
    assert rubygems_mod.parse_gem_version("gem-2-fast-1.0.0.gem") == "1.0.0"


def test_parse_gem_version_from_a_platform_gem():
    """rb_sys cross-compiles platform gems, so the version is not the trailing segment."""
    assert rubygems_mod.parse_gem_version("liter_llm-1.19.0-x86_64-linux.gem") == "1.19.0"
    assert rubygems_mod.parse_gem_version("xberg-1.2.3-x64-mingw-ucrt.gem") == "1.2.3"
    assert rubygems_mod.parse_gem_version("tree_sitter_language_pack-1.16.0-arm64-darwin.gem") == "1.16.0"


def test_parse_gem_version_from_a_prerelease_version():
    assert rubygems_mod.parse_gem_version("my_gem-1.0.0.pre.1.gem") == "1.0.0.pre.1"


def test_parse_gem_version_returns_none_for_an_unparseable_filename():
    assert rubygems_mod.parse_gem_version("notagem.gem") is None


def test_normalize_release_version_strips_tag_prefix():
    assert rubygems_mod.normalize_release_version("v1.16.0") == "1.16.0"
    assert rubygems_mod.normalize_release_version("  1.16.0 ") == "1.16.0"
    assert rubygems_mod.normalize_release_version("") == ""


def test_assert_gems_match_release_accepts_matching_versions():
    gems = [Path("my_gem-1.16.0.gem"), Path("my_gem-1.16.0-x86_64-linux.gem")]
    assert rubygems_mod.assert_gems_match_release(gems, "1.16.0") is None


def test_assert_gems_match_release_fails_on_a_stale_gem():
    """tree-sitter-language-pack v1.16.0 pushed gems still carrying 1.15.12 and reported success."""
    with pytest.raises(SystemExit) as exc_info:
        rubygems_mod.assert_gems_match_release([Path("tree_sitter_language_pack-1.15.12.gem")], "1.16.0")
    assert exc_info.value.code == 1


def test_assert_gems_match_release_fails_when_a_filename_is_unparseable():
    """An unverifiable gem is exactly the blind spot the guard exists to close."""
    with pytest.raises(SystemExit) as exc_info:
        rubygems_mod.assert_gems_match_release([Path("mystery.gem")], "1.16.0")
    assert exc_info.value.code == 1


def _write_gems(directory: Path, names: list[str]) -> None:
    for name in names:
        (directory / name).write_bytes(b"data")


def test_main_refuses_a_stale_gem_before_pushing_anything(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The stale gem must fail the job without pushing the gems ahead of it.

    RubyGems refuses to repush a version, so a mismatch caught mid-loop is unrecoverable.
    """
    _write_gems(tmp_path, ["my_gem-1.16.0.gem", "my_gem-1.15.12.gem"])

    calls: list[list[str]] = []
    monkeypatch.setattr(rubygems_mod, "validate_gem_structure", lambda path: True)
    monkeypatch.setattr(rubygems_mod, "_run", lambda cmd, env=None: calls.append(cmd) or (0, ""))
    monkeypatch.setenv("INPUT_GEMS_DIR", str(tmp_path))
    monkeypatch.setenv("INPUT_DRY_RUN", "false")
    monkeypatch.setenv("INPUT_EXPECTED_VERSION", "v1.16.0")
    monkeypatch.setenv("GEM_HOST_API_KEY", "token")

    with pytest.raises(SystemExit) as exc_info:
        rubygems_mod.main()

    assert exc_info.value.code == 1
    assert calls == [], "no gem may be pushed once a stale gem is present"


def test_main_still_skips_an_already_published_release_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """An idempotent re-run of the version being released stays a success-with-skip."""
    _write_gems(tmp_path, ["my_gem-1.16.0.gem"])

    monkeypatch.setattr(rubygems_mod, "validate_gem_structure", lambda path: True)
    monkeypatch.setattr(rubygems_mod, "_run", lambda cmd, env=None: (1, "Repushing of gem versions is not allowed"))
    monkeypatch.setenv("INPUT_GEMS_DIR", str(tmp_path))
    monkeypatch.setenv("INPUT_DRY_RUN", "false")
    monkeypatch.setenv("INPUT_EXPECTED_VERSION", "1.16.0")
    monkeypatch.setenv("GEM_HOST_API_KEY", "token")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    rubygems_mod.main()

    assert "my_gem-1.16.0.gem already published, skipping" in capsys.readouterr().out


def test_main_warns_when_expected_version_is_not_supplied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """The unsupplied expected-version is the blind spot, so it must be loud."""
    _write_gems(tmp_path, ["my_gem-1.16.0.gem"])

    monkeypatch.setattr(rubygems_mod, "validate_gem_structure", lambda path: True)
    monkeypatch.setenv("INPUT_GEMS_DIR", str(tmp_path))
    monkeypatch.setenv("INPUT_DRY_RUN", "true")
    monkeypatch.setenv("INPUT_EXPECTED_VERSION", "")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    rubygems_mod.main()

    assert "::warning::publish-rubygems was invoked without `expected-version`" in capsys.readouterr().out


def test_main_fails_on_a_stale_gem_during_a_dry_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A dry run exists to catch a stale build before the real release."""
    _write_gems(tmp_path, ["my_gem-1.15.12.gem"])

    monkeypatch.setattr(rubygems_mod, "validate_gem_structure", lambda path: True)
    monkeypatch.setenv("INPUT_GEMS_DIR", str(tmp_path))
    monkeypatch.setenv("INPUT_DRY_RUN", "true")
    monkeypatch.setenv("INPUT_EXPECTED_VERSION", "v1.16.0")

    with pytest.raises(SystemExit) as exc_info:
        rubygems_mod.main()
    assert exc_info.value.code == 1
