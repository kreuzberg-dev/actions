import importlib.util
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "publish-crates" / "scripts" / "publish.py"


def _import_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


crates_mod = _import_script("publish_crates", _SCRIPT_PATH)


def test_is_already_published_uploaded():
    assert crates_mod.is_already_published("error: crate version has already uploaded") is True


def test_is_already_published_exists():
    assert crates_mod.is_already_published("error: already exists in the registry") is True


def test_is_already_published_false():
    assert crates_mod.is_already_published("error: could not find `Cargo.toml`") is False


def test_is_new_crate_trusted_publishing_true():
    output = (
        "error: failed to publish to registry at https://crates.io\n"
        "Caused by:\n"
        "  the remote server responded with an error (status 400 Bad Request): "
        "Trusted Publishing tokens do not support creating new crates. "
        "Publish the crate manually, first"
    )
    assert crates_mod.is_new_crate_trusted_publishing(output) is True


def test_is_new_crate_trusted_publishing_false():
    assert crates_mod.is_new_crate_trusted_publishing("error: already exists in the registry") is False


def test_build_manifest_args_empty():
    assert crates_mod.build_manifest_args("") == []


def test_build_manifest_args_set():
    result = crates_mod.build_manifest_args("Cargo.toml")
    assert result == ["--manifest-path", "Cargo.toml"]


def test_parse_crate_list():
    result = crates_mod.parse_crate_list("crate1 crate2")
    assert result == ["crate1", "crate2"]


def test_parse_crate_list_extra_whitespace():
    result = crates_mod.parse_crate_list("  crate1   crate2  ")
    assert result == ["crate1", "crate2"]


def test_parse_crate_list_single():
    result = crates_mod.parse_crate_list("only-one")
    assert result == ["only-one"]


def test_publish_crate_always_passes_allow_dirty(monkeypatch):
    captured: list[list[str]] = []

    def fake_run(cmd: list[str]):
        captured.append(cmd)
        return 0, "ok"

    monkeypatch.setattr(crates_mod, "_run", fake_run)
    exit_code, _ = crates_mod.publish_crate("xberg-tesseract", ["--manifest-path", "Cargo.toml"])
    assert exit_code == 0
    assert captured == [["cargo", "publish", "-p", "xberg-tesseract", "--manifest-path", "Cargo.toml", "--allow-dirty"]]


def test_publish_crate_does_not_retry_new_crate_trusted_publishing(monkeypatch):
    """A new-crate OIDC rejection must fail fast — retrying never grants create permission."""
    calls = 0

    def fake_run(cmd: list[str]):
        nonlocal calls
        calls += 1
        return 1, "Trusted Publishing tokens do not support creating new crates. Publish the crate manually, first"

    slept: list[float] = []

    def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(crates_mod, "_run", fake_run)
    monkeypatch.setattr(crates_mod.time, "sleep", fake_sleep)

    exit_code, output = crates_mod.publish_crate("xberg-candle-ocr", [])

    assert exit_code == 1
    assert crates_mod.is_new_crate_trusted_publishing(output) is True
    assert calls == 1, "must not retry the new-crate rejection"
    assert slept == [], "must not sleep between (non-existent) retries"


def test_normalize_release_version_strips_tag_prefix():
    assert crates_mod.normalize_release_version("v1.16.0") == "1.16.0"
    assert crates_mod.normalize_release_version("  1.16.0 ") == "1.16.0"
    assert crates_mod.normalize_release_version("") == ""


def test_inject_path_dep_versions_leaves_the_package_version_untouched():
    """Version injection rewrites dependency sections only, so a stale `[package] version` survives it."""
    manifest = '[package]\nname = "demo"\nversion = "1.15.12"\n\n[dependencies]\ninner = { path = "../inner" }\n'

    rewritten = crates_mod.inject_path_dep_versions(manifest, "1.16.0")

    assert 'version = "1.15.12"' in rewritten
    assert 'inner = { path = "../inner", version = "1.16.0" }' in rewritten


def test_assert_crates_match_release_accepts_matching_versions():
    crates_mod.assert_crates_match_release([("core", "1.16.0"), ("cli", "1.16.0")], "1.16.0")


def test_assert_crates_match_release_fails_on_a_stale_manifest():
    """tree-sitter-language-pack v1.16.0 published manifests still carrying 1.15.12."""
    with pytest.raises(SystemExit) as exc_info:
        crates_mod.assert_crates_match_release([("tree-sitter-language-pack", "1.15.12")], "1.16.0")

    assert exc_info.value.code == 1


def test_assert_crates_match_release_fails_when_a_version_is_unreadable():
    with pytest.raises(SystemExit) as exc_info:
        crates_mod.assert_crates_match_release([("core", "1.16.0"), ("ghost", None)], "1.16.0")

    assert exc_info.value.code == 1


def _prepare_main(
    monkeypatch: pytest.MonkeyPatch,
    packages: dict,
    *,
    version: str = "1.16.0",
) -> None:
    """Point `main()` at a fake workspace so no cargo subprocess is required."""
    monkeypatch.setenv("INPUT_CRATES", " ".join(packages))
    monkeypatch.setenv("INPUT_VERSION", version)
    monkeypatch.setenv("INPUT_DRY_RUN", "false")
    monkeypatch.setenv("INPUT_MANIFEST_PATH", "")
    monkeypatch.setattr(crates_mod, "_discover_workspace_packages", lambda manifest_args: packages)


def _package(version: str, name: str = "demo") -> "crates_mod.WorkspacePackage":
    return crates_mod.WorkspacePackage(f"/nonexistent/{name}/Cargo.toml", version)


def test_main_refuses_a_stale_crate_before_publishing_anything(monkeypatch: pytest.MonkeyPatch):
    """A stale manifest must fail the job, and must not publish the crates ahead of it.

    crates.io forbids republishing a version, so a mismatch caught mid-list is unrecoverable —
    tree-sitter-language-pack v1.16.0 is the incident this guards.
    """
    packages = {"fresh": _package("1.16.0", "fresh"), "stale": _package("1.15.12", "stale")}
    calls: list[list[str]] = []
    monkeypatch.setattr(crates_mod, "_run", lambda cmd: calls.append(cmd) or (0, ""))
    _prepare_main(monkeypatch, packages)

    with pytest.raises(SystemExit) as exc_info:
        crates_mod.main()

    assert exc_info.value.code == 1
    assert calls == [], "no crate may be published once a stale manifest is present"


def test_main_still_skips_an_already_published_release_version(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """An idempotent re-run of the version being released stays a success-with-skip."""
    _prepare_main(monkeypatch, {"demo": _package("1.16.0")})
    monkeypatch.setattr(crates_mod, "_run", lambda cmd: (1, "error: crate version 1.16.0 is already uploaded"))
    monkeypatch.setattr(crates_mod, "wait_for_index", lambda crate, version: True)

    crates_mod.main()

    out = capsys.readouterr().out
    assert "demo@1.16.0 already published, skipping" in out
    assert "All crates published successfully" in out


def test_main_fails_when_an_already_published_skip_is_not_backed_by_the_index(monkeypatch: pytest.MonkeyPatch):
    """An 'already published' claim the index cannot corroborate must fail, never warn-and-continue."""
    _prepare_main(monkeypatch, {"demo": _package("1.16.0")})
    monkeypatch.setattr(crates_mod, "_run", lambda cmd: (1, "error: already exists in the registry"))
    monkeypatch.setattr(crates_mod, "wait_for_index", lambda crate, version: False)

    with pytest.raises(SystemExit) as exc_info:
        crates_mod.main()

    assert exc_info.value.code == 1


def test_main_treats_index_lag_after_a_successful_publish_as_a_warning(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """After a confirmed upload an absent index entry is propagation lag, so the run continues."""
    _prepare_main(monkeypatch, {"demo": _package("1.16.0")})
    monkeypatch.setattr(crates_mod, "_run", lambda cmd: (0, ""))
    monkeypatch.setattr(crates_mod, "wait_for_index", lambda crate, version: False)

    crates_mod.main()

    captured = capsys.readouterr()
    assert "All crates published successfully" in captured.out
    assert "proceeding anyway" in captured.err
