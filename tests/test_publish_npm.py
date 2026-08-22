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
    _silence_sleep(monkeypatch)
    monkeypatch.setattr(npm_mod.urllib.request, "urlopen", _fake_urlopen(404))
    assert npm_mod.registry_has_version("@s/p", "1.2.3") is False


def test_registry_check_window_spans_npm_propagation_notice():
    """npm says propagation takes minutes, so the check must poll for minutes."""
    delays = npm_mod.registry_check_delays()
    assert sum(delays) >= npm_mod.REGISTRY_CHECK_WINDOW_SECONDS
    assert npm_mod.REGISTRY_CHECK_WINDOW_SECONDS >= 300
    assert max(delays) == npm_mod.REGISTRY_CHECK_MAX_BACKOFF_SECONDS
    assert delays[0] == npm_mod.REGISTRY_CHECK_INITIAL_BACKOFF_SECONDS


def test_registry_has_version_retries_until_the_version_appears(monkeypatch: pytest.MonkeyPatch):
    """The first read can 404 while the write has already landed; the retry must find it."""
    slept = _silence_sleep(monkeypatch)
    monkeypatch.setattr(npm_mod.urllib.request, "urlopen", _fake_urlopen_sequence([404, 404, 200]))
    assert npm_mod.registry_has_version("@s/p", "1.2.3") is True
    assert len(slept) == 2


def test_confirm_registry_presence_reports_a_lagging_package_without_failing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """A publish npm accepted stays published even if the read side never catches up."""
    _silence_sleep(monkeypatch)
    monkeypatch.setattr(npm_mod.urllib.request, "urlopen", _fake_urlopen(404))

    unconfirmed = npm_mod.confirm_registry_presence([("@s/p", "1.2.3")])

    assert unconfirmed == ["@s/p@1.2.3"]
    assert "::warning::@s/p@1.2.3 was accepted by npm" in capsys.readouterr().out


def _silence_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Replace time.sleep with a recorder so backoff costs no wall-clock time."""
    slept: list[float] = []
    monkeypatch.setattr(npm_mod.time, "sleep", slept.append)
    return slept


def _fake_urlopen_sequence(statuses: list[int]):
    """Build a urlopen stand-in returning each status in turn, repeating the last one."""
    remaining = list(statuses)

    def _urlopen(request, timeout=None):
        status = remaining.pop(0) if len(remaining) > 1 else remaining[0]
        return _fake_urlopen(status)(request, timeout)

    return _urlopen


def _record_publishes(monkeypatch: pytest.MonkeyPatch, exit_codes: dict[str, tuple[int, str]] | None = None):
    """Stub npm publish, recording each invocation's target; returns the recorded targets."""
    calls: list[str] = []
    outcomes = exit_codes or {}

    def _publish(cmd: list[str], cwd: Path | None = None) -> tuple[int, str]:
        target = cmd[2]
        calls.append(target)
        for fragment, outcome in outcomes.items():
            if fragment in target:
                return outcome
        return 0, "+ published"

    monkeypatch.setattr(npm_mod, "_run_publish_with_retry", _publish)
    return calls


def test_package_absent_on_first_check_is_still_reported_as_published(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """The liter-llm 1.17.3 race: npm accepted the publish, the registry had not caught up yet."""
    _make_tgz(tmp_path / "p-win32-x64-msvc.tgz", {"name": "@s/p-win32-x64-msvc", "version": "1.17.3"})
    _silence_sleep(monkeypatch)
    _record_publishes(monkeypatch)
    monkeypatch.setattr(npm_mod.urllib.request, "urlopen", _fake_urlopen_sequence([404, 200]))

    npm_mod.publish_tgz_directory(str(tmp_path), ["--tag", "latest"], "latest", dry_run=False)

    out = capsys.readouterr().out
    assert "Published: 1, Failed: 0, Skipped: 0" in out
    assert "Confirmed @s/p-win32-x64-msvc@1.17.3 on the npm registry" in out


def test_a_package_that_never_appears_does_not_fail_the_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """A check that can only produce false negatives must never turn an accepted publish into a failure."""
    _make_tgz(tmp_path / "p.tgz", {"name": "@s/p", "version": "1.17.3"})
    _silence_sleep(monkeypatch)
    _record_publishes(monkeypatch)
    monkeypatch.setattr(npm_mod.urllib.request, "urlopen", _fake_urlopen(404))

    npm_mod.publish_tgz_directory(str(tmp_path), ["--tag", "latest"], "latest", dry_run=False)

    out = capsys.readouterr().out
    assert "Published: 1, Failed: 0, Skipped: 0" in out
    assert "Accepted by npm but not yet readable from the registry: @s/p@1.17.3" in out


def test_a_lagging_package_does_not_skip_the_publishes_after_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """One package's verification outcome must not strand the rest — that stranded the main package."""
    for platform in ("linux-x64-gnu", "win32-x64-msvc", "darwin-arm64"):
        _make_tgz(tmp_path / f"p-{platform}.tgz", {"name": f"@s/p-{platform}", "version": "1.17.3"})
    _make_tgz(tmp_path / "p.tgz", {"name": "@s/p", "version": "1.17.3"})
    _silence_sleep(monkeypatch)
    calls = _record_publishes(monkeypatch)
    monkeypatch.setattr(npm_mod.urllib.request, "urlopen", _fake_urlopen(404))

    npm_mod.publish_tgz_directory(str(tmp_path), ["--tag", "latest"], "latest", dry_run=False)

    assert len(calls) == 4
    assert any(call.endswith("/p.tgz") for call in calls)
    assert "Published: 4, Failed: 0, Skipped: 0" in capsys.readouterr().out


def test_every_package_is_published_before_any_is_verified(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Verification is deferred so propagation lag on one package cannot delay the next publish."""
    _make_tgz(tmp_path / "a.tgz", {"name": "@s/a", "version": "1.0.0"})
    _make_tgz(tmp_path / "b.tgz", {"name": "@s/b", "version": "1.0.0"})
    _silence_sleep(monkeypatch)

    events: list[str] = []

    def _publish(cmd: list[str], cwd: Path | None = None) -> tuple[int, str]:
        events.append("publish")
        return 0, "+ published"

    def _verify(package: str, version: str) -> bool:
        events.append("verify")
        return True

    monkeypatch.setattr(npm_mod, "_run_publish_with_retry", _publish)
    monkeypatch.setattr(npm_mod, "registry_has_version", _verify)

    npm_mod.publish_tgz_directory(str(tmp_path), ["--tag", "latest"], "latest", dry_run=False)

    assert events == ["publish", "publish", "verify", "verify"]


def test_a_real_publish_failure_still_fails_the_step(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Only npm rejecting the publish is fatal — the registry read is not."""
    _make_tgz(tmp_path / "p.tgz", {"name": "@s/p", "version": "1.0.0"})
    _silence_sleep(monkeypatch)
    _record_publishes(monkeypatch, {"p.tgz": (1, "npm error 403 Forbidden")})
    monkeypatch.setattr(npm_mod.urllib.request, "urlopen", _fake_urlopen(200))

    with pytest.raises(SystemExit) as exc_info:
        npm_mod.publish_tgz_directory(str(tmp_path), ["--tag", "latest"], "latest", dry_run=False)
    assert exc_info.value.code == 1


def test_single_directory_publish_survives_a_lagging_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """The crawlberg WASM case: one package, accepted by npm, absent from the first read."""
    (tmp_path / "package.json").write_text(json.dumps({"name": "@s/p-wasm", "version": "1.3.2"}))
    _silence_sleep(monkeypatch)
    _record_publishes(monkeypatch)
    monkeypatch.setattr(npm_mod.urllib.request, "urlopen", _fake_urlopen(404))

    npm_mod.publish_package_directory(str(tmp_path), ["--tag", "latest"], dry_run=False)

    assert "::warning::@s/p-wasm@1.3.2 was accepted by npm" in capsys.readouterr().out


def _fake_urlopen(status: int):
    """Build a urlopen stand-in returning `status`, raising HTTPError for error codes."""

    class _Response:
        def __init__(self) -> None:
            self.status = status

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> bool:
            return False

    def _urlopen(request, timeout=None):
        if status >= 400:
            raise npm_mod.urllib.error.HTTPError(request.full_url, status, "err", {}, None)
        return _Response()

    return _urlopen
