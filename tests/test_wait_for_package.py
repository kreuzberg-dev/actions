import importlib.util
import json
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "wait-for-package" / "scripts" / "wait.py"


def _import_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


wait_mod = _import_script("wait", _SCRIPT_PATH)


def test_validate_version_valid():
    assert wait_mod.validate_version("1.2.3") is True


def test_validate_version_with_prerelease():
    assert wait_mod.validate_version("1.2.3-beta") is True


def test_validate_version_invalid_no_patch():
    assert wait_mod.validate_version("1.2") is False


def test_validate_version_invalid_text():
    assert wait_mod.validate_version("latest") is False


def test_cratesio_prefix_single_char():
    assert wait_mod._cratesio_prefix("a") == "1/a"


def test_cratesio_prefix_two_chars():
    assert wait_mod._cratesio_prefix("ab") == "2/ab"


def test_cratesio_prefix_three_chars():
    assert wait_mod._cratesio_prefix("abc") == "3/a/abc"


def test_cratesio_prefix_four_plus():
    assert wait_mod._cratesio_prefix("serde") == "se/rd/serde"


def test_cratesio_prefix_uppercase():
    assert wait_mod._cratesio_prefix("Serde") == "se/rd/serde"


def test_check_npm_found(monkeypatch):
    monkeypatch.setattr(wait_mod, "http_get", lambda url, **kwargs: (200, "{}"))
    assert wait_mod.check_npm("mypackage", "1.2.3") is True


def test_check_npm_not_found(monkeypatch):
    monkeypatch.setattr(wait_mod, "http_get", lambda url, **kwargs: (404, ""))
    assert wait_mod.check_npm("mypackage", "1.2.3") is False


def test_check_npm_scoped_package(monkeypatch):
    captured_urls: list[str] = []

    def mock_http_get(url, **kwargs):
        captured_urls.append(url)
        return (200, "{}")

    monkeypatch.setattr(wait_mod, "http_get", mock_http_get)
    wait_mod.check_npm("@scope/pkg", "1.0.0")

    assert captured_urls, "http_get was not called"
    assert "@" not in captured_urls[0].split("npmjs.org/", 1)[-1]


def test_check_pypi_found(monkeypatch):
    body = json.dumps({"info": {"version": "1.2.3"}})
    monkeypatch.setattr(wait_mod, "http_get", lambda url, **kwargs: (200, body))
    assert wait_mod.check_pypi("xberg", "1.2.3") is True


def test_check_pypi_not_found(monkeypatch):
    monkeypatch.setattr(wait_mod, "http_get", lambda url, **kwargs: (404, ""))
    assert wait_mod.check_pypi("xberg", "1.2.3") is False


def test_check_pypi_version_mismatch(monkeypatch):
    body = json.dumps({"info": {"version": "9.9.9"}})
    monkeypatch.setattr(wait_mod, "http_get", lambda url, **kwargs: (200, body))
    assert wait_mod.check_pypi("xberg", "1.2.3") is False


def _record_urls(monkeypatch, status: int = 200, body: str = "{}") -> list[str]:
    captured: list[str] = []

    def mock_http_get(url, **kwargs):
        captured.append(url)
        return (status, body)

    monkeypatch.setattr(wait_mod, "http_get", mock_http_get)
    return captured


def test_check_maven_found(monkeypatch):
    monkeypatch.setattr(wait_mod, "http_get", lambda url, **kwargs: (200, ""))
    assert wait_mod.check_maven("myartifact", "1.2.3", group_id="com.example") is True


def test_check_maven_not_found(monkeypatch):
    monkeypatch.setattr(wait_mod, "http_get", lambda url, **kwargs: (404, ""))
    assert wait_mod.check_maven("myartifact", "1.2.3", group_id="com.example") is False


def test_check_maven_no_group_id(monkeypatch, capsys):
    monkeypatch.setattr(wait_mod, "http_get", lambda url, **kwargs: (200, "{}"))
    result = wait_mod.check_maven("myartifact", "1.2.3", group_id="")
    assert result is False


def test_check_maven_accepts_group_artifact_coordinate(monkeypatch):
    captured = _record_urls(monkeypatch)

    assert wait_mod.check_maven("com.example:myartifact", "1.2.3", group_id="") is True
    assert captured == ["https://repo1.maven.org/maven2/com/example/myartifact/1.2.3/"]


def test_check_maven_queries_repository_not_search_index(monkeypatch):
    captured = _record_urls(monkeypatch)

    wait_mod.check_maven("myartifact", "1.2.3", group_id="com.example")

    assert captured == ["https://repo1.maven.org/maven2/com/example/myartifact/1.2.3/"]
    assert "search.maven.org" not in captured[0]


def test_split_maven_coordinate_prefers_the_coordinate_form():
    assert wait_mod.split_maven_coordinate("com.example:art", "other.group") == ("com.example", "art")


def test_split_maven_coordinate_falls_back_to_group_id():
    assert wait_mod.split_maven_coordinate("art", "com.example") == ("com.example", "art")


def test_check_hex_found(monkeypatch):
    body = json.dumps({"releases": [{"version": "1.2.3"}, {"version": "1.2.2"}]})
    monkeypatch.setattr(wait_mod, "http_get", lambda url, **kwargs: (200, body))
    assert wait_mod.check_hex("my_package", "1.2.3") is True


def test_check_hex_not_found(monkeypatch):
    body = json.dumps({"releases": [{"version": "1.2.2"}]})
    monkeypatch.setattr(wait_mod, "http_get", lambda url, **kwargs: (200, body))
    assert wait_mod.check_hex("my_package", "1.2.3") is False


def test_check_hex_unknown_package(monkeypatch):
    monkeypatch.setattr(wait_mod, "http_get", lambda url, **kwargs: (404, ""))
    assert wait_mod.check_hex("my_package", "1.2.3") is False


def test_check_hex_queries_the_package_api(monkeypatch):
    captured = _record_urls(monkeypatch, body=json.dumps({"releases": []}))

    wait_mod.check_hex("my_package", "1.2.3")

    assert captured == ["https://hex.pm/api/packages/my_package"]


def test_check_hex_tolerates_unexpected_payload(monkeypatch):
    monkeypatch.setattr(wait_mod, "http_get", lambda url, **kwargs: (200, "not json"))
    assert wait_mod.check_hex("my_package", "1.2.3") is False


def test_check_nuget_found_case_insensitively(monkeypatch):
    body = json.dumps({"versions": ["1.2.2", "1.2.3"]})
    captured = _record_urls(monkeypatch, body=body)

    assert wait_mod.check_nuget("Vendor.MyPackage", "1.2.3") is True
    assert captured == ["https://api.nuget.org/v3-flatcontainer/vendor.mypackage/index.json"]


def test_check_nuget_not_found(monkeypatch):
    body = json.dumps({"versions": ["1.2.2"]})
    monkeypatch.setattr(wait_mod, "http_get", lambda url, **kwargs: (200, body))
    assert wait_mod.check_nuget("Vendor.MyPackage", "1.2.3") is False


def test_check_packagist_found(monkeypatch):
    body = json.dumps({"packages": {"vendor/pkg": [{"version": "1.2.2"}, {"version": "1.2.3"}]}})
    captured = _record_urls(monkeypatch, body=body)

    assert wait_mod.check_packagist("vendor/pkg", "1.2.3") is True
    assert captured == ["https://repo.packagist.org/p2/vendor/pkg.json"]


def test_check_packagist_accepts_v_prefixed_tags(monkeypatch):
    body = json.dumps({"packages": {"vendor/pkg": [{"version": "v1.2.3"}]}})
    monkeypatch.setattr(wait_mod, "http_get", lambda url, **kwargs: (200, body))
    assert wait_mod.check_packagist("vendor/pkg", "1.2.3") is True


def test_check_packagist_not_found(monkeypatch):
    body = json.dumps({"packages": {"vendor/pkg": [{"version": "v1.2.2"}]}})
    monkeypatch.setattr(wait_mod, "http_get", lambda url, **kwargs: (200, body))
    assert wait_mod.check_packagist("vendor/pkg", "1.2.3") is False


def test_every_registry_the_publish_workflows_use_has_a_handler():
    expected = {"cratesio", "hex", "maven", "npm", "nuget", "packagist", "pypi", "rubygems"}
    assert set(wait_mod.REGISTRIES) == expected


def test_wait_for_package_hex_dispatches_to_check_hex(monkeypatch):
    body = json.dumps({"releases": [{"version": "1.2.3"}]})
    monkeypatch.setattr(wait_mod, "http_get", lambda url, **kwargs: (200, body))
    monkeypatch.setattr(wait_mod.time, "sleep", lambda _: None)
    assert wait_mod.wait_for_package("hex", "my_package", "1.2.3", max_attempts=1) is True


def test_wait_for_package_maven_accepts_coordinate_without_group_input(monkeypatch):
    captured = _record_urls(monkeypatch)
    monkeypatch.setattr(wait_mod.time, "sleep", lambda _: None)

    result = wait_mod.wait_for_package("maven", "com.example:myartifact", "1.2.3", max_attempts=1)

    assert result is True
    assert captured == ["https://repo1.maven.org/maven2/com/example/myartifact/1.2.3/"]


def test_check_rubygems_found(monkeypatch):
    body = json.dumps([{"number": "1.2.3"}, {"number": "1.2.2"}])
    monkeypatch.setattr(wait_mod, "http_get", lambda url, **kwargs: (200, body))
    assert wait_mod.check_rubygems("mygem", "1.2.3") is True


def test_check_rubygems_not_found(monkeypatch):
    body = json.dumps([])
    monkeypatch.setattr(wait_mod, "http_get", lambda url, **kwargs: (200, body))
    assert wait_mod.check_rubygems("mygem", "1.2.3") is False


def test_wait_for_package_found_first_attempt(monkeypatch):
    monkeypatch.setattr(wait_mod, "http_get", lambda url, **kwargs: (200, "{}"))
    monkeypatch.setattr(wait_mod.time, "sleep", lambda _: None)
    result = wait_mod.wait_for_package("npm", "mypackage", "1.2.3", max_attempts=3)
    assert result is True


def test_wait_for_package_found_after_retries(monkeypatch):
    call_count = 0

    def mock_http_get(url, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            return (404, "")
        return (200, "{}")

    monkeypatch.setattr(wait_mod, "http_get", mock_http_get)
    monkeypatch.setattr(wait_mod.time, "sleep", lambda _: None)
    result = wait_mod.wait_for_package("npm", "mypackage", "1.2.3", max_attempts=5)
    assert result is True
    assert call_count == 3


def test_wait_for_package_exhausted(monkeypatch):
    monkeypatch.setattr(wait_mod, "http_get", lambda url, **kwargs: (404, ""))
    monkeypatch.setattr(wait_mod.time, "sleep", lambda _: None)
    result = wait_mod.wait_for_package("npm", "mypackage", "1.2.3", max_attempts=3)
    assert result is False


def test_wait_for_package_maven_dispatches_correctly(monkeypatch):
    captured_calls: list[tuple] = []

    def mock_check_maven(package, version, group_id=""):
        captured_calls.append((package, version, group_id))
        return True

    monkeypatch.setattr(wait_mod, "check_maven", mock_check_maven)
    monkeypatch.setattr(wait_mod.time, "sleep", lambda _: None)

    result = wait_mod.wait_for_package("maven", "myartifact", "1.2.3", max_attempts=1, maven_group_id="com.example")
    assert result is True
    assert captured_calls == [("myartifact", "1.2.3", "com.example")]
