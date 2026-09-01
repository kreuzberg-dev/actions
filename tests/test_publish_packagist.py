import importlib.util
import json
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "publish-packagist" / "scripts" / "publish.py"


def _import_script(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


packagist_mod = _import_script("publish_packagist", _SCRIPT_PATH)


def test_check_packagist_version_found(monkeypatch):
    body = json.dumps({"package": {"versions": {"1.2.3": {}, "1.2.2": {}}}})
    monkeypatch.setattr(packagist_mod, "http_get", lambda url, **kwargs: (200, body))

    assert packagist_mod.check_packagist_version("vendor/pkg", "1.2.3") is True


def test_check_packagist_version_with_v_prefix(monkeypatch):
    body = json.dumps({"package": {"versions": {"v1.2.3": {}, "v1.2.2": {}}}})
    monkeypatch.setattr(packagist_mod, "http_get", lambda url, **kwargs: (200, body))

    assert packagist_mod.check_packagist_version("vendor/pkg", "1.2.3") is True


def test_check_packagist_version_not_found(monkeypatch):
    body = json.dumps({"package": {"versions": {"1.2.2": {}, "1.2.1": {}}}})
    monkeypatch.setattr(packagist_mod, "http_get", lambda url, **kwargs: (200, body))

    assert packagist_mod.check_packagist_version("vendor/pkg", "1.2.3") is False


def test_trigger_packagist_update_success(monkeypatch):
    monkeypatch.setattr(packagist_mod, "http_post", lambda url, body, **kwargs: (200, "OK"))

    result = packagist_mod.trigger_packagist_update("myuser", "secret-token", "https://github.com/vendor/pkg")

    assert result is True


def test_trigger_packagist_update_failure(monkeypatch):
    monkeypatch.setattr(packagist_mod, "http_post", lambda url, body, **kwargs: (0, ""))

    result = packagist_mod.trigger_packagist_update("myuser", "bad-token", "https://github.com/vendor/pkg")

    assert result is False


def test_poll_packagist_found(monkeypatch):
    call_count = 0

    def mock_check(package_name, version):
        nonlocal call_count
        call_count += 1
        return call_count >= 2

    monkeypatch.setattr(packagist_mod, "check_packagist_version", mock_check)
    monkeypatch.setattr(packagist_mod.time, "sleep", lambda _: None)

    result = packagist_mod.poll_packagist("vendor/pkg", "1.2.3", max_attempts=5, poll_interval=0)

    assert result is True
    assert call_count == 2


def test_poll_packagist_timeout(monkeypatch):
    monkeypatch.setattr(packagist_mod, "check_packagist_version", lambda package_name, version: False)
    monkeypatch.setattr(packagist_mod.time, "sleep", lambda _: None)

    result = packagist_mod.poll_packagist("vendor/pkg", "1.2.3", max_attempts=3, poll_interval=0)

    assert result is False


def _set_required_env(monkeypatch):
    monkeypatch.setenv("INPUT_USERNAME", "myuser")
    monkeypatch.setenv("INPUT_PACKAGE_NAME", "vendor/pkg")
    monkeypatch.setenv("INPUT_VERSION", "1.2.3")
    monkeypatch.setenv("INPUT_REPOSITORY_URL", "https://github.com/vendor/pkg")
    monkeypatch.setenv("INPUT_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("INPUT_POLL_INTERVAL", "0")
    monkeypatch.setenv("INPUT_DRY_RUN", "false")
    monkeypatch.delenv("PACKAGIST_API_TOKEN", raising=False)


def test_main_exits_nonzero_when_version_never_appears(monkeypatch):
    _set_required_env(monkeypatch)
    monkeypatch.setattr(packagist_mod, "poll_packagist", lambda *args, **kwargs: False)

    with pytest.raises(SystemExit) as excinfo:
        packagist_mod.main()

    assert excinfo.value.code == 1


def test_main_exits_zero_when_version_is_found(monkeypatch):
    _set_required_env(monkeypatch)
    monkeypatch.setattr(packagist_mod, "poll_packagist", lambda *args, **kwargs: True)

    with pytest.raises(SystemExit) as excinfo:
        packagist_mod.main()

    assert excinfo.value.code == 0


def test_main_polls_for_the_requested_version(monkeypatch):
    _set_required_env(monkeypatch)
    polled = []

    def mock_poll(package_name, version, max_attempts, poll_interval):
        polled.append((package_name, version, max_attempts, poll_interval))
        return True

    monkeypatch.setattr(packagist_mod, "poll_packagist", mock_poll)

    with pytest.raises(SystemExit):
        packagist_mod.main()

    assert polled == [("vendor/pkg", "1.2.3", 3, 0)]
