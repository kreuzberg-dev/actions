import importlib.util
import json
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "publish-packagist" / "scripts" / "publish.py"


def _import_script(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


packagist_mod = _import_script("publish_packagist", _SCRIPT_PATH)


# ---------------------------------------------------------------------------
# check_packagist_version
# ---------------------------------------------------------------------------


def test_check_packagist_version_found(monkeypatch):
    body = json.dumps({"package": {"versions": {"1.2.3": {}, "1.2.2": {}}}})
    monkeypatch.setattr(packagist_mod, "http_get", lambda url, **kwargs: (200, body))

    assert packagist_mod.check_packagist_version("vendor/pkg", "1.2.3") is True


def test_check_packagist_version_with_v_prefix(monkeypatch):
    # Packagist stores keys as "v1.2.3"; target version is "1.2.3"
    body = json.dumps({"package": {"versions": {"v1.2.3": {}, "v1.2.2": {}}}})
    monkeypatch.setattr(packagist_mod, "http_get", lambda url, **kwargs: (200, body))

    assert packagist_mod.check_packagist_version("vendor/pkg", "1.2.3") is True


def test_check_packagist_version_not_found(monkeypatch):
    body = json.dumps({"package": {"versions": {"1.2.2": {}, "1.2.1": {}}}})
    monkeypatch.setattr(packagist_mod, "http_get", lambda url, **kwargs: (200, body))

    assert packagist_mod.check_packagist_version("vendor/pkg", "1.2.3") is False


# ---------------------------------------------------------------------------
# trigger_packagist_update
# ---------------------------------------------------------------------------


def test_trigger_packagist_update_success(monkeypatch):
    monkeypatch.setattr(packagist_mod, "http_post", lambda url, body, **kwargs: (200, "OK"))

    result = packagist_mod.trigger_packagist_update("myuser", "secret-token", "https://github.com/vendor/pkg")

    assert result is True


def test_trigger_packagist_update_failure(monkeypatch):
    monkeypatch.setattr(packagist_mod, "http_post", lambda url, body, **kwargs: (0, ""))

    result = packagist_mod.trigger_packagist_update("myuser", "bad-token", "https://github.com/vendor/pkg")

    assert result is False


# ---------------------------------------------------------------------------
# poll_packagist
# ---------------------------------------------------------------------------


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

    # Should return False but NOT raise — caller exits 0 regardless
    result = packagist_mod.poll_packagist("vendor/pkg", "1.2.3", max_attempts=3, poll_interval=0)

    assert result is False
