import importlib.util
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "check-registry" / "scripts" / "check.py"


def _import_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check_mod = _import_script("check", _SCRIPT_PATH)


# ---------------------------------------------------------------------------
# check_url_exists
# ---------------------------------------------------------------------------


def test_check_url_exists_200(monkeypatch):
    monkeypatch.setattr(check_mod, "http_get", lambda url: (200, "body"))
    assert check_mod.check_url_exists("https://example.com/pkg") is True


def test_check_url_exists_404(monkeypatch):
    calls = []

    def mock_http_get(url):
        calls.append(url)
        return 404, ""

    monkeypatch.setattr(check_mod, "http_get", mock_http_get)
    monkeypatch.setattr(check_mod.time, "sleep", lambda _: None)

    assert check_mod.check_url_exists("https://example.com/pkg") is False
    assert len(calls) == 1  # no retry on 404


def test_check_url_exists_retries_on_500(monkeypatch):
    responses = [(500, ""), (500, ""), (200, "ok")]
    call_count = {"n": 0}

    def mock_http_get(url):
        status, body = responses[call_count["n"]]
        call_count["n"] += 1
        return status, body

    monkeypatch.setattr(check_mod, "http_get", mock_http_get)
    monkeypatch.setattr(check_mod.time, "sleep", lambda _: None)

    assert check_mod.check_url_exists("https://example.com/pkg") is True
    assert call_count["n"] == 3


# ---------------------------------------------------------------------------
# fetch_json
# ---------------------------------------------------------------------------


def test_fetch_json_success(monkeypatch):
    payload = {"name": "kreuzberg", "version": "4.4.6"}
    monkeypatch.setattr(check_mod, "http_get", lambda url: (200, json.dumps(payload)))

    result = check_mod.fetch_json("https://example.com/pkg.json")
    assert result == payload


def test_fetch_json_404(monkeypatch):
    monkeypatch.setattr(check_mod, "http_get", lambda url: (404, ""))

    result = check_mod.fetch_json("https://example.com/missing.json")
    assert result is None


# ---------------------------------------------------------------------------
# check_pypi
# ---------------------------------------------------------------------------


def test_check_pypi(monkeypatch):
    visited = []

    def mock_check_url_exists(url):
        visited.append(url)
        return True

    monkeypatch.setattr(check_mod, "check_url_exists", mock_check_url_exists)

    assert check_mod.check_pypi("kreuzberg", "4.4.6") is True
    assert visited[0] == "https://pypi.org/pypi/kreuzberg/4.4.6/json"


# ---------------------------------------------------------------------------
# check_npm
# ---------------------------------------------------------------------------


def test_check_npm_scoped(monkeypatch):
    visited = []

    def mock_check_url_exists(url):
        visited.append(url)
        return True

    monkeypatch.setattr(check_mod, "check_url_exists", mock_check_url_exists)

    assert check_mod.check_npm("@scope/pkg", "1.0.0") is True
    assert "%40scope%2Fpkg" in visited[0]


# ---------------------------------------------------------------------------
# check_nuget
# ---------------------------------------------------------------------------


def test_check_nuget_lowercases(monkeypatch):
    visited = []

    def mock_check_url_exists(url):
        visited.append(url)
        return True

    monkeypatch.setattr(check_mod, "check_url_exists", mock_check_url_exists)

    assert check_mod.check_nuget("MyPackage", "1.0.0-Beta") is True
    assert "mypackage" in visited[0]
    assert "1.0.0-beta" in visited[0]
    assert "MyPackage" not in visited[0]


# ---------------------------------------------------------------------------
# check_rubygems
# ---------------------------------------------------------------------------


def test_check_rubygems_found(monkeypatch):
    versions = [{"number": "1.2.3"}, {"number": "1.2.4"}]
    monkeypatch.setattr(check_mod, "fetch_json", lambda url: versions)

    assert check_mod.check_rubygems("my_gem", "1.2.3") is True


def test_check_rubygems_not_found(monkeypatch):
    versions = [{"number": "1.2.3"}]
    monkeypatch.setattr(check_mod, "fetch_json", lambda url: versions)

    assert check_mod.check_rubygems("my_gem", "9.9.9") is False


def test_check_rubygems_dash_to_dot(monkeypatch):
    # version "1.0.0-beta" should match gem number "1.0.0.beta"
    versions = [{"number": "1.0.0.beta"}]
    monkeypatch.setattr(check_mod, "fetch_json", lambda url: versions)

    assert check_mod.check_rubygems("my_gem", "1.0.0-beta") is True


def test_check_rubygems_fetch_returns_none(monkeypatch):
    monkeypatch.setattr(check_mod, "fetch_json", lambda url: None)

    assert check_mod.check_rubygems("my_gem", "1.0.0") is False


# ---------------------------------------------------------------------------
# check_hex
# ---------------------------------------------------------------------------


def test_check_hex_found(monkeypatch):
    data = {"releases": [{"version": "0.5.0"}, {"version": "0.6.0"}]}
    monkeypatch.setattr(check_mod, "fetch_json", lambda url: data)

    assert check_mod.check_hex("my_pkg", "0.5.0") is True


def test_check_hex_not_found(monkeypatch):
    data = {"releases": [{"version": "0.5.0"}]}
    monkeypatch.setattr(check_mod, "fetch_json", lambda url: data)

    assert check_mod.check_hex("my_pkg", "9.9.9") is False


def test_check_hex_fetch_returns_none(monkeypatch):
    monkeypatch.setattr(check_mod, "fetch_json", lambda url: None)

    assert check_mod.check_hex("my_pkg", "1.0.0") is False


# ---------------------------------------------------------------------------
# check_maven
# ---------------------------------------------------------------------------


def test_check_maven_valid(monkeypatch):
    visited = []

    def mock_check_url_exists(url):
        visited.append(url)
        return True

    monkeypatch.setattr(check_mod, "check_url_exists", mock_check_url_exists)

    assert check_mod.check_maven("com.example:artifact", "1.0.0") is True
    assert "com/example/artifact/1.0.0/artifact-1.0.0.jar" in visited[0]


def test_check_maven_missing_colon(monkeypatch):
    monkeypatch.setattr(check_mod, "check_url_exists", lambda url: True)

    assert check_mod.check_maven("invalid", "1.0.0") is False


# ---------------------------------------------------------------------------
# check_packagist
# ---------------------------------------------------------------------------


def test_check_packagist_exact_version(monkeypatch):
    data: dict[str, Any] = {"packages": {"vendor/pkg": [{"version": "1.0.0"}]}}
    monkeypatch.setattr(check_mod, "fetch_json", lambda url: data)

    assert check_mod.check_packagist("vendor/pkg", "1.0.0") is True


def test_check_packagist_with_v_prefix(monkeypatch):
    data: dict[str, Any] = {"packages": {"vendor/pkg": [{"version": "v1.0.0"}]}}
    monkeypatch.setattr(check_mod, "fetch_json", lambda url: data)

    assert check_mod.check_packagist("vendor/pkg", "1.0.0") is True


def test_check_packagist_not_found(monkeypatch):
    data: dict[str, Any] = {"packages": {"vendor/pkg": [{"version": "2.0.0"}]}}
    monkeypatch.setattr(check_mod, "fetch_json", lambda url: data)

    assert check_mod.check_packagist("vendor/pkg", "1.0.0") is False


# ---------------------------------------------------------------------------
# check_homebrew
# ---------------------------------------------------------------------------


def test_check_homebrew_found_version_string(monkeypatch):
    monkeypatch.setattr(check_mod, "http_get", lambda url: (200, 'version "3.1.4"'))

    assert check_mod.check_homebrew("myformula", "3.1.4", tap_repo="owner/tap") is True


def test_check_homebrew_found_tarball_url(monkeypatch):
    monkeypatch.setattr(check_mod, "http_get", lambda url: (200, "url https://example.com/v3.1.4.tar.gz"))

    assert check_mod.check_homebrew("myformula", "3.1.4", tap_repo="owner/tap") is True


def test_check_homebrew_not_found(monkeypatch):
    monkeypatch.setattr(check_mod, "http_get", lambda url: (200, 'version "9.9.9"'))

    assert check_mod.check_homebrew("myformula", "3.1.4", tap_repo="owner/tap") is False


def test_check_homebrew_http_failure(monkeypatch):
    monkeypatch.setattr(check_mod, "http_get", lambda url: (404, ""))

    assert check_mod.check_homebrew("myformula", "3.1.4", tap_repo="owner/tap") is False


def test_check_homebrew_no_tap_repo(monkeypatch):
    monkeypatch.setattr(check_mod, "http_get", lambda url: (200, 'version "3.1.4"'))

    assert check_mod.check_homebrew("myformula", "3.1.4", tap_repo="") is False


# ---------------------------------------------------------------------------
# check_github_release
# ---------------------------------------------------------------------------


def test_check_github_release_found(monkeypatch):
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = json.dumps({"assets": [{"name": "my-app-linux.tar.gz"}]})

    monkeypatch.setattr(check_mod.subprocess, "run", lambda *a, **kw: mock_result)

    assert check_mod.check_github_release("my-app", "1.0.0", repo="owner/repo") is True


def test_check_github_release_with_assets(monkeypatch):
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = json.dumps(
        {
            "assets": [
                {"name": "my-app-linux.tar.gz"},
                {"name": "my-app-macos.tar.gz"},
            ]
        }
    )

    monkeypatch.setattr(check_mod.subprocess, "run", lambda *a, **kw: mock_result)

    assert (
        check_mod.check_github_release(
            "my-app", "1.0.0", assets="my-app-linux.tar.gz,my-app-macos.tar.gz", repo="owner/repo"
        )
        is True
    )


def test_check_github_release_with_assets_missing(monkeypatch):
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = json.dumps({"assets": [{"name": "my-app-linux.tar.gz"}]})

    monkeypatch.setattr(check_mod.subprocess, "run", lambda *a, **kw: mock_result)

    assert (
        check_mod.check_github_release(
            "my-app", "1.0.0", assets="my-app-linux.tar.gz,my-app-windows.zip", repo="owner/repo"
        )
        is False
    )


def test_check_github_release_gh_not_found(monkeypatch):
    def raise_file_not_found(*args, **kwargs):
        raise FileNotFoundError("gh not found")

    monkeypatch.setattr(check_mod.subprocess, "run", raise_file_not_found)

    assert check_mod.check_github_release("my-app", "1.0.0", repo="owner/repo") is False


def test_check_github_release_nonzero_returncode(monkeypatch):
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stdout = ""

    monkeypatch.setattr(check_mod.subprocess, "run", lambda *a, **kw: mock_result)

    assert check_mod.check_github_release("my-app", "1.0.0", repo="owner/repo") is False


def test_check_github_release_with_asset_prefix(monkeypatch):
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = json.dumps({"assets": [{"name": "my-app-1.0.0-linux.tar.gz"}]})

    monkeypatch.setattr(check_mod.subprocess, "run", lambda *a, **kw: mock_result)

    assert check_mod.check_github_release("my-app", "1.0.0", asset_prefix="my-app-1.0.0", repo="owner/repo") is True


# ---------------------------------------------------------------------------
# write_output
# ---------------------------------------------------------------------------


def test_write_output_to_github_output(tmp_path, monkeypatch, capsys):
    output_file = tmp_path / "github_output.txt"
    output_file.touch()
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))

    check_mod.write_output("exists", "true")

    captured = capsys.readouterr()
    assert "exists=true" in captured.out
    assert output_file.read_text() == "exists=true\n"


def test_write_output_stdout_only(monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)

    check_mod.write_output("exists", "false")

    captured = capsys.readouterr()
    assert "exists=false" in captured.out


# ---------------------------------------------------------------------------
# REGISTRIES dict
# ---------------------------------------------------------------------------


def test_registries_dict_contains_all():
    expected_keys = {
        "pypi",
        "npm",
        "cratesio",
        "nuget",
        "rubygems",
        "hex",
        "maven",
        "packagist",
        "homebrew",
        "github-release",
    }
    assert set(check_mod.REGISTRIES.keys()) == expected_keys
    assert len(check_mod.REGISTRIES) == 10
    for key, fn in check_mod.REGISTRIES.items():
        assert callable(fn), f"REGISTRIES[{key!r}] must be callable"
