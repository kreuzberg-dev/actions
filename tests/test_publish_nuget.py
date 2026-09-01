import importlib.util
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "publish-nuget" / "scripts" / "publish.py"


def _import_script(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


nuget_mod = _import_script("publish_nuget", _SCRIPT_PATH)


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


def test_is_publish_error_success():
    assert nuget_mod.is_publish_error(0, "Package pushed successfully.") is False


def test_is_publish_error_failure():
    assert nuget_mod.is_publish_error(1, "Error: some unexpected failure occurred") is True


def test_parse_nupkg_version_from_a_simple_id():
    assert nuget_mod.parse_nupkg_version("Xberg.1.16.0.nupkg") == "1.16.0"


def test_parse_nupkg_version_from_a_dotted_id():
    """The Id contains dots too, so the version is the trailing dotted-numeric run."""
    assert nuget_mod.parse_nupkg_version("Xberg.Core.1.2.3.nupkg") == "1.2.3"
    assert nuget_mod.parse_nupkg_version("Xberg.TreeSitter.LanguagePack.1.16.0.nupkg") == "1.16.0"


def test_parse_nupkg_version_from_an_id_ending_in_digits():
    assert nuget_mod.parse_nupkg_version("Xberg.Net6.1.2.3.nupkg") == "1.2.3"


def test_parse_nupkg_version_from_a_prerelease_version():
    assert nuget_mod.parse_nupkg_version("Xberg.Core.1.2.3-beta.1.nupkg") == "1.2.3-beta.1"


def test_parse_nupkg_version_returns_none_for_an_unparseable_filename():
    assert nuget_mod.parse_nupkg_version("broken.nupkg") is None


def test_is_already_published_detects_a_skipped_duplicate():
    output = "warn : Your package was not pushed since it already exists in your source."
    assert nuget_mod.is_already_published(output) is True


def test_is_already_published_false_for_a_normal_push():
    assert nuget_mod.is_already_published("Your package was pushed.") is False


def test_normalize_release_version_strips_tag_prefix():
    assert nuget_mod.normalize_release_version("v1.16.0") == "1.16.0"
    assert nuget_mod.normalize_release_version("  1.16.0 ") == "1.16.0"
    assert nuget_mod.normalize_release_version("") == ""


def test_assert_packages_match_release_accepts_matching_versions():
    packages = [Path("Xberg.Core.1.16.0.nupkg"), Path("Xberg.Cli.1.16.0.nupkg")]
    assert nuget_mod.assert_packages_match_release(packages, "1.16.0") is None


def test_assert_packages_match_release_fails_on_a_stale_package():
    """tree-sitter-language-pack v1.16.0 pushed artifacts still carrying 1.15.12 and reported success."""
    with pytest.raises(SystemExit) as exc_info:
        nuget_mod.assert_packages_match_release([Path("Xberg.Core.1.15.12.nupkg")], "1.16.0")
    assert exc_info.value.code == 1


def test_assert_packages_match_release_fails_when_a_filename_is_unparseable():
    """An unverifiable package is exactly the blind spot the guard exists to close."""
    with pytest.raises(SystemExit) as exc_info:
        nuget_mod.assert_packages_match_release([Path("mystery.nupkg")], "1.16.0")
    assert exc_info.value.code == 1


def _write_packages(directory, names):
    for name in names:
        (directory / name).write_text("fake")


def test_main_refuses_a_stale_package_before_pushing_anything(tmp_path, monkeypatch):
    """The stale package must fail the job without pushing the packages ahead of it.

    nuget.org does not allow republishing a version, so a mismatch caught mid-loop is
    unrecoverable.
    """
    _write_packages(tmp_path, ["Xberg.Core.1.16.0.nupkg", "Xberg.Cli.1.15.12.nupkg"])

    calls = []
    monkeypatch.setattr(nuget_mod, "_run", lambda cmd: calls.append(cmd) or (0, "pushed"))
    monkeypatch.setenv("INPUT_PACKAGES_DIR", str(tmp_path))
    monkeypatch.setenv("INPUT_DRY_RUN", "false")
    monkeypatch.setenv("INPUT_EXPECTED_VERSION", "v1.16.0")
    monkeypatch.setenv("NUGET_API_KEY", "key")

    with pytest.raises(SystemExit) as exc_info:
        nuget_mod.main()

    assert exc_info.value.code == 1
    assert calls == [], "no package may be pushed once a stale package is present"


def test_main_reports_a_skipped_duplicate_as_a_skip_not_a_publish(tmp_path, monkeypatch, capsys):
    """`--skip-duplicate` exits 0 on a duplicate; the log must not claim a publish happened."""
    _write_packages(tmp_path, ["Xberg.Core.1.16.0.nupkg"])

    duplicate = "warn : Your package was not pushed since it already exists in your source."
    monkeypatch.setattr(nuget_mod, "_run", lambda cmd: (0, duplicate))
    monkeypatch.setenv("INPUT_PACKAGES_DIR", str(tmp_path))
    monkeypatch.setenv("INPUT_DRY_RUN", "false")
    monkeypatch.setenv("INPUT_EXPECTED_VERSION", "1.16.0")
    monkeypatch.setenv("NUGET_API_KEY", "key")

    nuget_mod.main()

    out = capsys.readouterr().out
    assert "Xberg.Core.1.16.0.nupkg already published, skipping" in out
    assert "Published: 0, Failed: 0, Skipped: 1" in out


def test_main_reports_a_real_push_as_published(tmp_path, monkeypatch, capsys):
    _write_packages(tmp_path, ["Xberg.Core.1.16.0.nupkg"])

    monkeypatch.setattr(nuget_mod, "_run", lambda cmd: (0, "Your package was pushed."))
    monkeypatch.setenv("INPUT_PACKAGES_DIR", str(tmp_path))
    monkeypatch.setenv("INPUT_DRY_RUN", "false")
    monkeypatch.setenv("INPUT_EXPECTED_VERSION", "1.16.0")
    monkeypatch.setenv("NUGET_API_KEY", "key")

    nuget_mod.main()

    out = capsys.readouterr().out
    assert "  Published Xberg.Core.1.16.0.nupkg" in out
    assert "Published: 1, Failed: 0, Skipped: 0" in out


def test_main_warns_when_expected_version_is_not_supplied(tmp_path, monkeypatch, capsys):
    """The unsupplied expected-version is the blind spot, so it must be loud."""
    _write_packages(tmp_path, ["Xberg.Core.1.16.0.nupkg"])

    monkeypatch.setenv("INPUT_PACKAGES_DIR", str(tmp_path))
    monkeypatch.setenv("INPUT_DRY_RUN", "true")
    monkeypatch.setenv("INPUT_EXPECTED_VERSION", "")

    nuget_mod.main()

    assert "::warning::publish-nuget was invoked without `expected-version`" in capsys.readouterr().out


def test_main_fails_on_a_stale_package_during_a_dry_run(tmp_path, monkeypatch):
    """A dry run exists to catch a stale build before the real release."""
    _write_packages(tmp_path, ["Xberg.Core.1.15.12.nupkg"])

    monkeypatch.setenv("INPUT_PACKAGES_DIR", str(tmp_path))
    monkeypatch.setenv("INPUT_DRY_RUN", "true")
    monkeypatch.setenv("INPUT_EXPECTED_VERSION", "v1.16.0")

    with pytest.raises(SystemExit) as exc_info:
        nuget_mod.main()
    assert exc_info.value.code == 1
