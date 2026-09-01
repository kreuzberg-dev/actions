import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "publish-pypi" / "scripts" / "publish.py"

spec = importlib.util.spec_from_file_location("publish_pypi", str(_SCRIPT))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


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


class _FakeResponse:
    """Minimal stand-in for the object `urllib.request.urlopen` yields."""

    def __init__(self, status: int, payload: bytes):
        self.status = status
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def read(self):
        return self._payload


def _urlopen_returning(status: int, payload: bytes = b'{"info": {}}'):
    def _fake(url, timeout=None):
        return _FakeResponse(status, payload)

    return _fake


def _run_main(monkeypatch, tmp_path, dist_files, expected_version, github_output):
    dist = tmp_path / "dist"
    dist.mkdir(exist_ok=True)
    for filename in dist_files:
        (dist / filename).write_text("fake")

    monkeypatch.setenv("INPUT_PACKAGES_DIR", str(dist))
    monkeypatch.setenv("INPUT_DRY_RUN", "false")
    monkeypatch.setenv("INPUT_EXPECTED_VERSION", expected_version)
    monkeypatch.setenv("GITHUB_OUTPUT", str(github_output))
    mod.main()
    return github_output.read_text() if github_output.exists() else ""


def test_normalize_release_version_strips_tag_prefix():
    assert mod.normalize_release_version("v1.19.0") == "1.19.0"
    assert mod.normalize_release_version("  1.19.0 ") == "1.19.0"
    assert mod.normalize_release_version("") == ""


def test_assert_dists_match_release_accepts_matching_versions():
    mod.assert_dists_match_release({("liter-llm", "1.19.0"), ("liter-llm-hermes-plugin", "1.19.0")}, "1.19.0")


def test_assert_dists_match_release_fails_on_stale_wheel():
    """liter-llm v1.19.0 rebuilt a 1.18.4 wheel; that must fail, not resolve to a skip."""
    with pytest.raises(SystemExit) as exc_info:
        mod.assert_dists_match_release({("liter-llm-hermes-plugin", "1.18.4")}, "1.19.0")
    assert exc_info.value.code == 1


def test_assert_dists_match_release_fails_when_nothing_parseable():
    with pytest.raises(SystemExit) as exc_info:
        mod.assert_dists_match_release(set(), "1.19.0")
    assert exc_info.value.code == 1


def test_main_fails_on_stale_wheel_even_when_already_on_the_registry(monkeypatch, tmp_path):
    """The exact liter-llm v1.19.0 failure: a 1.18.4 wheel that PyPI already has.

    Before the fix this printed "Skipping publish" and exited 0, shipping nothing for the tag.
    """
    monkeypatch.setattr(mod.urllib.request, "urlopen", _urlopen_returning(200))
    output = tmp_path / "gh_output"

    with pytest.raises(SystemExit) as exc_info:
        _run_main(
            monkeypatch,
            tmp_path,
            ["liter_llm_hermes_plugin-1.18.4-py3-none-any.whl"],
            "1.19.0",
            output,
        )

    assert exc_info.value.code == 1
    assert "version_published=true" not in (output.read_text() if output.exists() else "")


def test_main_still_skips_an_idempotent_rerun_of_the_release_version(monkeypatch, tmp_path):
    """Re-running a publish for the version being released stays a success-with-skip."""
    monkeypatch.setattr(mod.urllib.request, "urlopen", _urlopen_returning(200))
    output = tmp_path / "gh_output"

    result = _run_main(monkeypatch, tmp_path, ["liter_llm-1.19.0-py3-none-any.whl"], "1.19.0", output)

    assert "version_published=true" in result


def test_main_publishes_when_version_matches_and_is_absent(monkeypatch, tmp_path):
    monkeypatch.setattr(mod.urllib.request, "urlopen", _urlopen_returning(404))
    output = tmp_path / "gh_output"

    result = _run_main(monkeypatch, tmp_path, ["liter_llm-1.19.0-py3-none-any.whl"], "1.19.0", output)

    assert "version_published=false" in result


def test_main_warns_when_expected_version_is_not_supplied(monkeypatch, tmp_path, capsys):
    """The unsupplied expected-version is the blind spot, so it must be loud."""
    monkeypatch.setattr(mod.urllib.request, "urlopen", _urlopen_returning(404))

    _run_main(monkeypatch, tmp_path, ["liter_llm-1.19.0-py3-none-any.whl"], "", tmp_path / "gh_output")

    assert "::warning::" in capsys.readouterr().out


def test_main_fails_on_stale_wheel_during_a_dry_run(monkeypatch, tmp_path):
    """A dry run exists to catch a stale build before the real release."""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "liter_llm-1.18.4-py3-none-any.whl").write_text("fake")
    monkeypatch.setenv("INPUT_PACKAGES_DIR", str(dist))
    monkeypatch.setenv("INPUT_DRY_RUN", "true")
    monkeypatch.setenv("INPUT_EXPECTED_VERSION", "v1.19.0")

    with pytest.raises(SystemExit) as exc_info:
        mod.main()
    assert exc_info.value.code == 1
