"""Tests for ensure_release.py."""

from __future__ import annotations

import json
import sys
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import ensure_release  # type: ignore[import-not-found]

if TYPE_CHECKING:
    from pytest_mock import MockerFixture

_BASE_ENV = {
    "INPUT_TAG": "v1.0.0",
    "INPUT_TITLE": "Release 1.0.0",
    "INPUT_GENERATE_NOTES": "false",
    "INPUT_DRAFT": "false",
    "INPUT_PRERELEASE": "false",
    "INPUT_NOTES": "",
    "INPUT_TARGET": "",
    "INPUT_DRY_RUN": "false",
    "GH_TOKEN": "token123",
    "GITHUB_REPOSITORY": "owner/repo",
}


@pytest.fixture
def action_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set the action's inputs to a working default; override individual keys per test."""
    for key, value in _BASE_ENV.items():
        monkeypatch.setenv(key, value)


@pytest.fixture
def empty_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _BASE_ENV:
        monkeypatch.delenv(key, raising=False)


def _http_error(status: int, body: bytes = b"") -> Exception:
    return ensure_release.urllib.error.HTTPError("http://api.github.com/test", status, "error", {}, BytesIO(body))


def _request_body(mock: Any) -> dict[str, Any]:
    """The JSON body github_request was called with (4th positional arg)."""
    body: dict[str, Any] = mock.call_args[0][3]
    return body


def test_github_request_get_returns_status_and_json(mocker: MockerFixture) -> None:
    response = mocker.MagicMock()
    response.status = 200
    response.read.return_value = json.dumps({"id": 123, "tag_name": "v1.0.0"}).encode()
    response.__enter__.return_value = response
    mocker.patch.object(ensure_release.urllib.request, "urlopen", return_value=response)

    status, data = ensure_release.github_request("GET", "http://api.github.com/test", "token123")

    assert status == 200
    assert data == {"id": 123, "tag_name": "v1.0.0"}


def test_github_request_get_treats_404_as_graceful_not_found(mocker: MockerFixture) -> None:
    mocker.patch.object(ensure_release.urllib.request, "urlopen", side_effect=_http_error(404))

    status, data = ensure_release.github_request("GET", "http://api.github.com/test", "token123")

    assert status == 404
    assert data == {}


def test_github_request_post_exits_on_server_error(mocker: MockerFixture) -> None:
    mocker.patch.object(
        ensure_release.urllib.request,
        "urlopen",
        side_effect=_http_error(500, b'{"message": "Server error"}'),
    )

    with pytest.raises(SystemExit) as excinfo:
        ensure_release.github_request("POST", "http://api.github.com/test", "token123", {"foo": "bar"})

    assert excinfo.value.code == 1


def test_get_release_by_tag_returns_existing_release(mocker: MockerFixture) -> None:
    release = {"id": 456, "tag_name": "v2.0.0", "draft": False}
    request = mocker.patch.object(ensure_release, "github_request", return_value=(200, release))

    assert ensure_release.get_release_by_tag("owner", "repo", "v2.0.0", "token") == release
    request.assert_called_once_with("GET", "https://api.github.com/repos/owner/repo/releases/tags/v2.0.0", "token")


def test_get_release_by_tag_retries_until_the_replica_catches_up(mocker: MockerFixture) -> None:
    """A freshly created release can 404 on the read replica for a beat."""
    release = {"id": 999, "tag_name": "v3.1.0", "draft": True}
    request = mocker.patch.object(ensure_release, "github_request", side_effect=[(404, {}), (404, {}), (200, release)])
    sleep = mocker.patch.object(ensure_release.time, "sleep")

    assert ensure_release.get_release_by_tag("owner", "repo", "v3.1.0", "token") == release
    assert request.call_count == 3
    assert sleep.call_count == 2


def test_get_release_by_tag_returns_none_after_exhausting_retries(mocker: MockerFixture) -> None:
    request = mocker.patch.object(ensure_release, "github_request", return_value=(404, {}))
    sleep = mocker.patch.object(ensure_release.time, "sleep")

    assert ensure_release.get_release_by_tag("owner", "repo", "v4.0.0", "token") is None
    assert request.call_count == 20
    assert sleep.call_count == 19


def test_create_release_sends_literal_notes_instead_of_generating_them(mocker: MockerFixture) -> None:
    release = {"id": 789, "tag_name": "v1.0.0"}
    request = mocker.patch.object(ensure_release, "github_request", return_value=(201, release))

    result = ensure_release.create_release(
        "owner",
        "repo",
        "v1.0.0",
        "Release 1.0.0",
        generate_notes=True,
        draft=False,
        prerelease=False,
        notes="Manual notes here",
        token="token",
    )

    assert result == release
    body = _request_body(request)
    assert body["body"] == "Manual notes here"
    assert "generate_release_notes" not in body


def test_create_release_generates_notes_when_none_given(mocker: MockerFixture) -> None:
    request = mocker.patch.object(ensure_release, "github_request", return_value=(201, {"id": 789}))

    ensure_release.create_release(
        "owner",
        "repo",
        "v1.0.0",
        "Release 1.0.0",
        generate_notes=True,
        draft=False,
        prerelease=False,
        notes="",
        token="token",
    )

    body = _request_body(request)
    assert body["generate_release_notes"]
    assert "body" not in body


def test_create_release_passes_target_commitish(mocker: MockerFixture) -> None:
    request = mocker.patch.object(ensure_release, "github_request", return_value=(201, {"id": 789}))

    ensure_release.create_release(
        "owner",
        "repo",
        "v1.0.0",
        "Release 1.0.0",
        generate_notes=False,
        draft=False,
        prerelease=False,
        target="main",
        token="token",
    )

    assert _request_body(request)["target_commitish"] == "main"


def test_tag_exists_on_git_is_true_when_ref_resolves(mocker: MockerFixture) -> None:
    request = mocker.patch.object(ensure_release, "github_request", return_value=(200, {"ref": "refs/tags/v1.0.0"}))

    assert ensure_release.tag_exists_on_git("owner", "repo", "v1.0.0", "token") is True
    request.assert_called_once_with("GET", "https://api.github.com/repos/owner/repo/git/refs/tags/v1.0.0", "token")


def test_tag_exists_on_git_is_false_on_404(mocker: MockerFixture) -> None:
    mocker.patch.object(ensure_release, "github_request", return_value=(404, {}))

    assert ensure_release.tag_exists_on_git("owner", "repo", "v2.0.0", "token") is False


def test_list_releases_returns_the_payload(mocker: MockerFixture) -> None:
    releases = [
        {"id": 1, "tag_name": "v1.0.0", "name": "v1.0.0"},
        {"id": 2, "tag_name": "untagged-xyz", "name": "v1.1.0"},
    ]
    mocker.patch.object(ensure_release, "github_request", return_value=(200, releases))

    assert ensure_release.list_releases("owner", "repo", "token") == releases


@pytest.mark.parametrize(
    "response",
    [(200, []), (500, {"message": "error"})],
    ids=["empty", "server-error"],
)
def test_list_releases_returns_empty_list(mocker: MockerFixture, response: tuple[int, Any]) -> None:
    mocker.patch.object(ensure_release, "github_request", return_value=response)

    assert ensure_release.list_releases("owner", "repo", "token") == []


def test_update_release_publishes_a_draft(mocker: MockerFixture) -> None:
    updated = {"id": 456, "tag_name": "v2.0.0", "draft": False}
    request = mocker.patch.object(ensure_release, "github_request", return_value=(200, updated))

    assert ensure_release.update_release("owner", "repo", 456, draft=False, token="token") == updated
    assert _request_body(request)["draft"] is False


def test_update_release_sets_tag_name(mocker: MockerFixture) -> None:
    updated = {"id": 456, "tag_name": "v2.0.0", "draft": False}
    request = mocker.patch.object(ensure_release, "github_request", return_value=(200, updated))

    assert ensure_release.update_release("owner", "repo", 456, tag_name="v2.0.0", token="token") == updated
    assert _request_body(request)["tag_name"] == "v2.0.0"


def test_update_release_sets_draft_and_tag_name_together(mocker: MockerFixture) -> None:
    updated = {"id": 456, "tag_name": "v2.0.0", "draft": False}
    request = mocker.patch.object(ensure_release, "github_request", return_value=(200, updated))

    ensure_release.update_release("owner", "repo", 456, draft=False, tag_name="v2.0.0", token="token")

    body = _request_body(request)
    assert body["draft"] is False
    assert body["tag_name"] == "v2.0.0"


@pytest.mark.usefixtures("action_env")
def test_main_creates_release_when_absent(mocker: MockerFixture, capsys: pytest.CaptureFixture[str]) -> None:
    mocker.patch.object(ensure_release, "get_release_by_tag", return_value=None)
    mocker.patch.object(ensure_release, "tag_exists_on_git", return_value=True)
    mocker.patch.object(ensure_release, "list_releases", return_value=[])
    mocker.patch.object(ensure_release, "update_release")
    mocker.patch.object(ensure_release, "create_release", return_value={"id": 123, "tag_name": "v1.0.0"})

    ensure_release.main()

    out = capsys.readouterr().out
    assert "Creating release v1.0.0" in out
    assert "Release v1.0.0 ready" in out


@pytest.mark.usefixtures("action_env")
def test_main_leaves_a_published_release_alone(mocker: MockerFixture, capsys: pytest.CaptureFixture[str]) -> None:
    mocker.patch.object(
        ensure_release, "get_release_by_tag", return_value={"id": 123, "tag_name": "v1.0.0", "draft": False}
    )
    update = mocker.patch.object(ensure_release, "update_release")

    ensure_release.main()

    out = capsys.readouterr().out
    assert "Release v1.0.0 already exists" in out
    assert "Release v1.0.0 ready" in out
    update.assert_not_called()


@pytest.mark.usefixtures("action_env")
def test_main_repairs_an_existing_release_with_a_placeholder_tag(
    mocker: MockerFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    mocker.patch.object(
        ensure_release,
        "get_release_by_tag",
        return_value={"id": 456, "tag_name": "untagged-broken", "draft": False},
    )
    update = mocker.patch.object(
        ensure_release, "update_release", return_value={"id": 456, "tag_name": "v1.0.0", "draft": False}
    )

    ensure_release.main()

    captured = capsys.readouterr()
    assert "Repaired tag_name to v1.0.0" in captured.out
    assert "Warning: release has tag_name=untagged-broken" in captured.err
    update.assert_called_once_with("owner", "repo", 456, tag_name="v1.0.0", token="token123")


@pytest.mark.usefixtures("action_env")
def test_main_exits_when_repairing_an_existing_tag_name_does_not_stick(mocker: MockerFixture) -> None:
    mocker.patch.object(
        ensure_release,
        "get_release_by_tag",
        return_value={"id": 456, "tag_name": "untagged-broken", "draft": False},
    )
    mocker.patch.object(
        ensure_release,
        "update_release",
        return_value={"id": 456, "tag_name": "untagged-still-broken", "draft": False},
    )

    with pytest.raises(SystemExit) as excinfo:
        ensure_release.main()

    assert excinfo.value.code == 1


@pytest.mark.usefixtures("action_env")
def test_main_publishes_an_existing_draft(mocker: MockerFixture, capsys: pytest.CaptureFixture[str]) -> None:
    mocker.patch.object(
        ensure_release, "get_release_by_tag", return_value={"id": 456, "tag_name": "v1.0.0", "draft": True}
    )
    update = mocker.patch.object(ensure_release, "update_release", return_value={"id": 456, "draft": False})

    ensure_release.main()

    assert "Publishing draft release v1.0.0" in capsys.readouterr().out
    update.assert_called_once_with("owner", "repo", 456, draft=False, token="token123")


@pytest.mark.usefixtures("action_env")
def test_main_dry_run_makes_no_network_calls(
    monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("INPUT_DRY_RUN", "true")
    get_release = mocker.patch.object(ensure_release, "get_release_by_tag")

    with pytest.raises(SystemExit) as excinfo:
        ensure_release.main()

    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "[dry-run]" in out
    assert "Would create/ensure release" in out
    get_release.assert_not_called()


@pytest.mark.usefixtures("empty_env")
def test_main_exits_without_a_tag() -> None:
    with pytest.raises(SystemExit) as excinfo:
        ensure_release.main()

    assert excinfo.value.code == 1


@pytest.mark.usefixtures("action_env")
def test_main_exits_without_a_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GH_TOKEN", "")

    with pytest.raises(SystemExit) as excinfo:
        ensure_release.main()

    assert excinfo.value.code == 1


@pytest.mark.usefixtures("action_env")
def test_main_exits_when_the_tag_never_appears_on_the_remote(mocker: MockerFixture) -> None:
    """Creating a release for an unpushed tag would make GitHub invent an `untagged-*` one."""
    mocker.patch.object(ensure_release, "get_release_by_tag", return_value=None)
    mocker.patch.object(ensure_release, "list_releases", return_value=[])
    mocker.patch.object(ensure_release.time, "sleep")
    tag_exists = mocker.patch.object(ensure_release, "tag_exists_on_git", return_value=False)

    with pytest.raises(SystemExit) as excinfo:
        ensure_release.main()

    assert excinfo.value.code == 1
    assert tag_exists.call_count == ensure_release.MAX_TAG_WAIT_ATTEMPTS


@pytest.mark.usefixtures("action_env")
def test_main_creates_once_the_tag_becomes_visible(mocker: MockerFixture, capsys: pytest.CaptureFixture[str]) -> None:
    mocker.patch.object(ensure_release, "get_release_by_tag", return_value=None)
    mocker.patch.object(ensure_release, "list_releases", return_value=[])
    mocker.patch.object(ensure_release, "create_release", return_value={"id": 123, "tag_name": "v1.0.0"})
    sleep = mocker.patch.object(ensure_release.time, "sleep")
    tag_exists = mocker.patch.object(ensure_release, "tag_exists_on_git", side_effect=[False, True])

    ensure_release.main()

    out = capsys.readouterr().out
    assert "Creating release v1.0.0" in out
    assert "Release v1.0.0 ready" in out
    assert tag_exists.call_count == 2
    sleep.assert_called_once()


@pytest.mark.usefixtures("action_env")
def test_main_repairs_a_created_release_with_a_placeholder_tag(
    mocker: MockerFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    mocker.patch.object(ensure_release, "get_release_by_tag", return_value=None)
    mocker.patch.object(ensure_release, "tag_exists_on_git", return_value=True)
    mocker.patch.object(ensure_release, "list_releases", return_value=[])
    mocker.patch.object(
        ensure_release, "create_release", return_value={"id": 123, "tag_name": "untagged-xyz", "draft": False}
    )
    update = mocker.patch.object(
        ensure_release, "update_release", return_value={"id": 123, "tag_name": "v1.0.0", "draft": False}
    )

    ensure_release.main()

    assert "Repaired tag_name to v1.0.0" in capsys.readouterr().out
    update.assert_called_once_with("owner", "repo", 123, tag_name="v1.0.0", token="token123")


@pytest.mark.usefixtures("action_env")
def test_main_exits_when_repairing_a_created_tag_name_does_not_stick(mocker: MockerFixture) -> None:
    mocker.patch.object(ensure_release, "get_release_by_tag", return_value=None)
    mocker.patch.object(ensure_release, "tag_exists_on_git", return_value=True)
    mocker.patch.object(ensure_release, "list_releases", return_value=[])
    mocker.patch.object(
        ensure_release, "create_release", return_value={"id": 123, "tag_name": "untagged-xyz", "draft": False}
    )
    mocker.patch.object(
        ensure_release, "update_release", return_value={"id": 123, "tag_name": "untagged-xyz", "draft": False}
    )

    with pytest.raises(SystemExit) as excinfo:
        ensure_release.main()

    assert excinfo.value.code == 1


@pytest.mark.usefixtures("action_env")
def test_main_reuses_a_pre_existing_broken_draft_instead_of_creating_a_second_release(
    mocker: MockerFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    mocker.patch.object(ensure_release, "get_release_by_tag", return_value=None)
    mocker.patch.object(ensure_release, "tag_exists_on_git", return_value=True)
    mocker.patch.object(
        ensure_release,
        "list_releases",
        return_value=[{"id": 999, "tag_name": "untagged-broken", "name": "v1.0.0", "draft": True}],
    )
    create = mocker.patch.object(ensure_release, "create_release")
    update = mocker.patch.object(
        ensure_release, "update_release", return_value={"id": 999, "tag_name": "v1.0.0", "draft": True}
    )

    ensure_release.main()

    out = capsys.readouterr().out
    assert "Found pre-existing broken draft" in out
    assert "Repaired broken draft" in out
    create.assert_not_called()
    update.assert_called_once()
