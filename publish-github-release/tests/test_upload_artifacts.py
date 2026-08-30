"""Tests for upload_artifacts.py."""

from __future__ import annotations

import json
import sys
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import upload_artifacts  # type: ignore[import-not-found]

if TYPE_CHECKING:
    from pytest_mock import MockerFixture

_BASE_ENV = {
    "INPUT_TAG": "v1.0.0",
    "INPUT_ARTIFACTS": "dist/*.whl",
    "GH_TOKEN": "token123",
    "GITHUB_REPOSITORY": "owner/repo",
}

_UPLOAD_URL = "https://uploads.github.com/repos/owner/repo/releases/123/assets"


@pytest.fixture
def action_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set the action's inputs to a working default; override individual keys per test."""
    for key, value in _BASE_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("INPUT_FAIL_IF_EMPTY", raising=False)


@pytest.fixture
def empty_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (*_BASE_ENV, "INPUT_FAIL_IF_EMPTY"):
        monkeypatch.delenv(key, raising=False)


def _urlopen_response(mocker: MockerFixture, payload: dict[str, Any] | None = None) -> Any:
    response = mocker.MagicMock()
    if payload is not None:
        response.read.return_value = json.dumps(payload).encode()
    response.__enter__.return_value = response
    return mocker.patch.object(upload_artifacts.urllib.request, "urlopen", return_value=response)


def _http_error(status: int, body: bytes) -> Exception:
    return upload_artifacts.urllib.error.HTTPError("http://api.github.com/test", status, "error", {}, BytesIO(body))


def _staged_wheel(tmp_path: Path, name: str = "package.whl", content: bytes = b"wheel content") -> Path:
    target = tmp_path / "dist" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return target


def test_expand_artifact_patterns_expands_a_single_glob(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "test1.txt").touch()
    (tmp_path / "test2.txt").touch()
    monkeypatch.chdir(tmp_path)

    result = upload_artifacts.expand_artifact_patterns("*.txt")

    assert {path.name for path in result} == {"test1.txt", "test2.txt"}


def test_expand_artifact_patterns_expands_comma_separated_globs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "file.whl").touch()
    (tmp_path / "file.tar.gz").touch()
    monkeypatch.chdir(tmp_path)

    result = upload_artifacts.expand_artifact_patterns("*.whl,*.tar.gz")

    assert {path.name for path in result} == {"file.whl", "file.tar.gz"}


def test_expand_artifact_patterns_returns_empty_when_nothing_matches() -> None:
    assert upload_artifacts.expand_artifact_patterns("nonexistent/*.xyz") == []


def test_get_release_by_tag_returns_the_release(mocker: MockerFixture) -> None:
    release = {
        "id": 123,
        "tag_name": "v1.0.0",
        "upload_url": f"{_UPLOAD_URL}{{?name,label}}",
        "assets": [{"id": 456, "name": "old_file.whl"}],
    }
    _urlopen_response(mocker, release)

    assert upload_artifacts.get_release_by_tag("owner", "repo", "v1.0.0", "token") == release


def test_get_release_by_tag_exits_on_404(mocker: MockerFixture) -> None:
    mocker.patch.object(
        upload_artifacts.urllib.request,
        "urlopen",
        side_effect=_http_error(404, b'{"message": "Not Found"}'),
    )

    with pytest.raises(SystemExit) as excinfo:
        upload_artifacts.get_release_by_tag("owner", "repo", "v1.0.0", "token")

    assert excinfo.value.code == 1


def test_delete_asset_succeeds(mocker: MockerFixture) -> None:
    _urlopen_response(mocker)

    upload_artifacts.delete_asset("owner", "repo", 456, "token")


def test_delete_asset_exits_on_server_error(mocker: MockerFixture) -> None:
    mocker.patch.object(
        upload_artifacts.urllib.request,
        "urlopen",
        side_effect=_http_error(500, b'{"message": "Server error"}'),
    )

    with pytest.raises(SystemExit) as excinfo:
        upload_artifacts.delete_asset("owner", "repo", 456, "token")

    assert excinfo.value.code == 1


def test_upload_asset_targets_the_named_asset_url(tmp_path: Path, mocker: MockerFixture) -> None:
    artifact = tmp_path / "test.whl"
    artifact.write_bytes(b"test content")
    urlopen = _urlopen_response(mocker)

    upload_artifacts.upload_asset(f"{_UPLOAD_URL}{{?name,label}}", "test.whl", artifact, "token")

    request = urlopen.call_args[0][0]
    assert _UPLOAD_URL in request.full_url
    assert "name=test.whl" in request.full_url


def test_upload_asset_strips_the_url_template(tmp_path: Path, mocker: MockerFixture) -> None:
    """GitHub returns upload_url with a literal `{?name,label}` suffix that must not be sent."""
    artifact = tmp_path / "file.tar.gz"
    artifact.write_bytes(b"archive")
    urlopen = _urlopen_response(mocker)

    upload_artifacts.upload_asset(f"{_UPLOAD_URL}{{?name,label}}", "file.tar.gz", artifact, "token")

    request = urlopen.call_args[0][0]
    assert "{?name,label}" not in request.full_url
    assert "name=file.tar.gz" in request.full_url


def test_upload_asset_detects_the_mime_type(tmp_path: Path, mocker: MockerFixture) -> None:
    artifact = tmp_path / "archive.tar.gz"
    artifact.write_bytes(b"gzip data")
    urlopen = _urlopen_response(mocker)

    upload_artifacts.upload_asset(_UPLOAD_URL, "archive.tar.gz", artifact, "token")

    content_type = urlopen.call_args[0][0].headers.get("Content-type")
    assert content_type in {"application/x-tar", "application/gzip", "application/x-gzip"}


def test_upload_asset_falls_back_to_octet_stream(tmp_path: Path, mocker: MockerFixture) -> None:
    artifact = tmp_path / "file.unknown_ext_12345"
    artifact.write_bytes(b"unknown")
    urlopen = _urlopen_response(mocker)

    upload_artifacts.upload_asset(_UPLOAD_URL, "file.unknown_ext_12345", artifact, "token")

    assert urlopen.call_args[0][0].headers.get("Content-type") == "application/octet-stream"


@pytest.mark.usefixtures("action_env")
def test_main_uploads_when_no_asset_exists_yet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    _staged_wheel(tmp_path)
    monkeypatch.chdir(tmp_path)
    mocker.patch.object(
        upload_artifacts,
        "get_release_by_tag",
        return_value={"id": 123, "upload_url": _UPLOAD_URL, "assets": []},
    )
    upload = mocker.patch.object(upload_artifacts, "upload_asset")

    upload_artifacts.main()

    out = capsys.readouterr().out
    assert "Uploading 1 artifact(s)" in out
    assert "Uploading package.whl" in out
    assert "All artifacts uploaded" in out
    upload.assert_called_once()


@pytest.mark.usefixtures("action_env")
def test_main_clobbers_an_existing_asset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    """Re-running a release must replace the asset, not fail on the name collision."""
    _staged_wheel(tmp_path, content=b"new wheel content")
    monkeypatch.chdir(tmp_path)
    mocker.patch.object(
        upload_artifacts,
        "get_release_by_tag",
        return_value={
            "id": 123,
            "upload_url": _UPLOAD_URL,
            "assets": [{"id": 999, "name": "package.whl"}],
        },
    )
    upload = mocker.patch.object(upload_artifacts, "upload_asset")
    delete = mocker.patch.object(upload_artifacts, "delete_asset")

    upload_artifacts.main()

    assert "Removing existing package.whl" in capsys.readouterr().out
    delete.assert_called_once()
    upload.assert_called_once()


@pytest.mark.usefixtures("action_env")
def test_main_fails_closed_when_nothing_matches(
    monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    """A green upload job that shipped zero assets is worse than a red one."""
    monkeypatch.setenv("INPUT_ARTIFACTS", "nonexistent/*.xyz")
    get_release = mocker.patch.object(upload_artifacts, "get_release_by_tag")

    with pytest.raises(SystemExit) as excinfo:
        upload_artifacts.main()

    assert excinfo.value.code == 1
    assert "no files matched artifact pattern(s)" in capsys.readouterr().err
    get_release.assert_not_called()


@pytest.mark.usefixtures("action_env")
def test_main_skips_when_empty_match_is_opted_into(
    monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("INPUT_ARTIFACTS", "nonexistent/*.xyz")
    monkeypatch.setenv("INPUT_FAIL_IF_EMPTY", "false")
    get_release = mocker.patch.object(upload_artifacts, "get_release_by_tag")

    upload_artifacts.main()

    assert "::warning::" in capsys.readouterr().out
    get_release.assert_not_called()


@pytest.mark.usefixtures("empty_env")
def test_main_exits_without_a_tag() -> None:
    with pytest.raises(SystemExit) as excinfo:
        upload_artifacts.main()

    assert excinfo.value.code == 1


@pytest.mark.usefixtures("action_env")
def test_main_exits_without_a_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GH_TOKEN", "")

    with pytest.raises(SystemExit) as excinfo:
        upload_artifacts.main()

    assert excinfo.value.code == 1


@pytest.mark.usefixtures("action_env")
def test_main_exits_without_artifacts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INPUT_ARTIFACTS", "")

    with pytest.raises(SystemExit) as excinfo:
        upload_artifacts.main()

    assert excinfo.value.code == 1
