"""Unit tests for upload_artifacts.py."""

import json
import sys
import unittest
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import pytest
import upload_artifacts  # type: ignore[import-not-found]


class TestExpandArtifactPatterns(unittest.TestCase):
    """Test expand_artifact_patterns function."""

    def test_expand_single_pattern(self) -> None:
        """Test expanding a single glob pattern."""
        with TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "test1.txt").touch()
            (Path(tmpdir) / "test2.txt").touch()

            import os

            old_cwd = Path.cwd()
            try:
                os.chdir(tmpdir)
                result = upload_artifacts.expand_artifact_patterns("*.txt")
                filenames = {p.name for p in result}
                assert filenames == {"test1.txt", "test2.txt"}
            finally:
                os.chdir(old_cwd)

    def test_expand_comma_separated(self) -> None:
        """Test expanding comma-separated patterns."""
        with TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "file.whl").touch()
            (Path(tmpdir) / "file.tar.gz").touch()

            import os

            old_cwd = Path.cwd()
            try:
                os.chdir(tmpdir)
                result = upload_artifacts.expand_artifact_patterns("*.whl,*.tar.gz")
                filenames = {p.name for p in result}
                assert filenames == {"file.whl", "file.tar.gz"}
            finally:
                os.chdir(old_cwd)

    def test_expand_no_matches(self) -> None:
        """Test pattern with no matches returns empty list."""
        result = upload_artifacts.expand_artifact_patterns("nonexistent/*.xyz")
        assert result == []


class TestGetReleaseByTag(unittest.TestCase):
    """Test get_release_by_tag function."""

    @patch("upload_artifacts.urllib.request.urlopen")
    def test_get_release_success(self, mock_urlopen) -> None:
        """Test successful release fetch."""
        release_data = {
            "id": 123,
            "tag_name": "v1.0.0",
            "upload_url": "https://uploads.github.com/repos/owner/repo/releases/123/assets{?name,label}",
            "assets": [{"id": 456, "name": "old_file.whl"}],
        }
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(release_data).encode("utf-8")
        mock_response.__enter__.return_value = mock_response

        mock_urlopen.return_value = mock_response

        result = upload_artifacts.get_release_by_tag("owner", "repo", "v1.0.0", "token")

        assert result == release_data

    @patch("upload_artifacts.urllib.request.urlopen")
    def test_get_release_error_404(self, mock_urlopen) -> None:
        """Test 404 error during release fetch exits."""
        from io import BytesIO

        error_response = BytesIO(b'{"message": "Not Found"}')
        mock_error = upload_artifacts.urllib.error.HTTPError(
            "http://api.github.com/test", 404, "Not Found", {}, error_response
        )
        mock_urlopen.side_effect = mock_error

        with pytest.raises(SystemExit) as ctx:
            upload_artifacts.get_release_by_tag("owner", "repo", "v1.0.0", "token")

        assert ctx.value.code == 1


class TestDeleteAsset(unittest.TestCase):
    """Test delete_asset function."""

    @patch("upload_artifacts.urllib.request.urlopen")
    def test_delete_asset_success(self, mock_urlopen) -> None:
        """Test successful asset deletion."""
        mock_response = MagicMock()
        mock_response.__enter__.return_value = mock_response

        mock_urlopen.return_value = mock_response

        upload_artifacts.delete_asset("owner", "repo", 456, "token")

    @patch("upload_artifacts.urllib.request.urlopen")
    def test_delete_asset_error(self, mock_urlopen) -> None:
        """Test error during asset deletion exits."""
        from io import BytesIO

        error_response = BytesIO(b'{"message": "Server error"}')
        mock_error = upload_artifacts.urllib.error.HTTPError(
            "http://api.github.com/test", 500, "Server Error", {}, error_response
        )
        mock_urlopen.side_effect = mock_error

        with pytest.raises(SystemExit) as ctx:
            upload_artifacts.delete_asset("owner", "repo", 456, "token")

        assert ctx.value.code == 1


class TestUploadAsset(unittest.TestCase):
    """Test upload_asset function."""

    @patch("upload_artifacts.urllib.request.urlopen")
    def test_upload_asset_success(self, mock_urlopen) -> None:
        """Test successful asset upload."""
        with TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.whl"
            test_file.write_bytes(b"test content")

            mock_response = MagicMock()
            mock_response.__enter__.return_value = mock_response

            mock_urlopen.return_value = mock_response

            upload_url = "https://uploads.github.com/repos/owner/repo/releases/123/assets{?name,label}"

            upload_artifacts.upload_asset(upload_url, "test.whl", test_file, "token")

            call_args = mock_urlopen.call_args
            request = call_args[0][0]
            assert "https://uploads.github.com/repos/owner/repo/releases/123/assets" in request.full_url
            assert "name=test.whl" in request.full_url

    @patch("upload_artifacts.urllib.request.urlopen")
    def test_upload_asset_template_stripping(self, mock_urlopen) -> None:
        """Test URL template {?name,label} is correctly stripped."""
        with TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "file.tar.gz"
            test_file.write_bytes(b"archive")

            mock_response = MagicMock()
            mock_response.__enter__.return_value = mock_response

            mock_urlopen.return_value = mock_response

            upload_url = "https://uploads.github.com/repos/owner/repo/releases/999/assets{?name,label}"

            upload_artifacts.upload_asset(upload_url, "file.tar.gz", test_file, "token")

            call_args = mock_urlopen.call_args
            request = call_args[0][0]
            assert "{?name,label}" not in request.full_url
            assert "name=file.tar.gz" in request.full_url

    @patch("upload_artifacts.urllib.request.urlopen")
    def test_upload_asset_mime_type_detection(self, mock_urlopen) -> None:
        """Test MIME type is correctly detected and set."""
        with TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "archive.tar.gz"
            test_file.write_bytes(b"gzip data")

            mock_response = MagicMock()
            mock_response.__enter__.return_value = mock_response

            mock_urlopen.return_value = mock_response

            upload_url = "https://uploads.github.com/repos/owner/repo/releases/123/assets"

            upload_artifacts.upload_asset(upload_url, "archive.tar.gz", test_file, "token")

            call_args = mock_urlopen.call_args
            request = call_args[0][0]
            assert request.headers.get("Content-type") in [
                "application/x-tar",
                "application/gzip",
                "application/x-gzip",
            ]

    @patch("upload_artifacts.urllib.request.urlopen")
    def test_upload_asset_unknown_mime_type(self, mock_urlopen) -> None:
        """Test unknown MIME type defaults to application/octet-stream."""
        with TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "file.unknown_ext_12345"
            test_file.write_bytes(b"unknown")

            mock_response = MagicMock()
            mock_response.__enter__.return_value = mock_response

            mock_urlopen.return_value = mock_response

            upload_url = "https://uploads.github.com/repos/owner/repo/releases/123/assets"

            upload_artifacts.upload_asset(upload_url, "file.unknown_ext_12345", test_file, "token")

            call_args = mock_urlopen.call_args
            request = call_args[0][0]
            assert request.headers.get("Content-type") == "application/octet-stream"


class TestMain(unittest.TestCase):
    """Test main function."""

    @patch("upload_artifacts.upload_asset")
    @patch("upload_artifacts.get_release_by_tag")
    @patch.dict(
        "os.environ",
        {
            "INPUT_TAG": "v1.0.0",
            "INPUT_ARTIFACTS": "dist/*.whl",
            "GH_TOKEN": "token123",
            "GITHUB_REPOSITORY": "owner/repo",
        },
    )
    def test_main_single_file_no_existing_asset(self, mock_get_release, mock_upload) -> None:
        """Test uploading single file when no existing asset present."""
        with TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "dist" / "package.whl"
            test_file.parent.mkdir(parents=True, exist_ok=True)
            test_file.write_bytes(b"wheel content")

            mock_get_release.return_value = {
                "id": 123,
                "upload_url": "https://uploads.github.com/repos/owner/repo/releases/123/assets",
                "assets": [],
            }

            import os

            old_cwd = Path.cwd()
            try:
                os.chdir(tmpdir)

                with patch("sys.stdout", new=StringIO()) as mock_stdout:
                    upload_artifacts.main()
                    output = mock_stdout.getvalue()
                    assert "Uploading 1 artifact(s)" in output
                    assert "Uploading package.whl" in output
                    assert "All artifacts uploaded" in output

                assert mock_upload.called
            finally:
                os.chdir(old_cwd)

    @patch("upload_artifacts.delete_asset")
    @patch("upload_artifacts.upload_asset")
    @patch("upload_artifacts.get_release_by_tag")
    @patch.dict(
        "os.environ",
        {
            "INPUT_TAG": "v1.0.0",
            "INPUT_ARTIFACTS": "dist/*.whl",
            "GH_TOKEN": "token123",
            "GITHUB_REPOSITORY": "owner/repo",
        },
    )
    def test_main_clobber_existing_asset(self, mock_get_release, mock_upload, mock_delete) -> None:
        """Test clobber semantics: existing asset is deleted then re-uploaded."""
        with TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "dist" / "package.whl"
            test_file.parent.mkdir(parents=True, exist_ok=True)
            test_file.write_bytes(b"new wheel content")

            mock_get_release.return_value = {
                "id": 123,
                "upload_url": "https://uploads.github.com/repos/owner/repo/releases/123/assets",
                "assets": [{"id": 999, "name": "package.whl"}],
            }

            import os

            old_cwd = Path.cwd()
            try:
                os.chdir(tmpdir)

                with patch("sys.stdout", new=StringIO()) as mock_stdout:
                    upload_artifacts.main()
                    output = mock_stdout.getvalue()
                    assert "Removing existing package.whl" in output

                mock_delete.assert_called_once()
                mock_upload.assert_called_once()
            finally:
                os.chdir(old_cwd)

    @patch("upload_artifacts.get_release_by_tag")
    @patch.dict(
        "os.environ",
        {
            "INPUT_TAG": "v1.0.0",
            "INPUT_ARTIFACTS": "nonexistent/*.xyz",
            "GH_TOKEN": "token123",
            "GITHUB_REPOSITORY": "owner/repo",
        },
    )
    def test_main_no_artifacts_matched_fails_closed(self, mock_get_release) -> None:
        """An empty match exits 1: a green upload job with zero assets is worse than a red one."""
        with patch("sys.stderr", new=StringIO()) as mock_stderr:
            with pytest.raises(SystemExit) as ctx:
                upload_artifacts.main()
            assert ctx.value.code == 1
            assert "no files matched artifact pattern(s)" in mock_stderr.getvalue()

        mock_get_release.assert_not_called()

    @patch("upload_artifacts.get_release_by_tag")
    @patch.dict(
        "os.environ",
        {
            "INPUT_TAG": "v1.0.0",
            "INPUT_ARTIFACTS": "nonexistent/*.xyz",
            "INPUT_FAIL_IF_EMPTY": "false",
            "GH_TOKEN": "token123",
            "GITHUB_REPOSITORY": "owner/repo",
        },
    )
    def test_main_no_artifacts_matched_skips_when_opted_out(self, mock_get_release) -> None:
        """fail-if-empty: 'false' is the documented escape hatch for an expected empty match."""
        with patch("sys.stdout", new=StringIO()) as mock_stdout:
            upload_artifacts.main()
            assert "::warning::" in mock_stdout.getvalue()

        mock_get_release.assert_not_called()

    @patch.dict("os.environ", {}, clear=True)
    def test_main_missing_tag_exits(self) -> None:
        """Test missing INPUT_TAG causes exit."""
        with pytest.raises(SystemExit) as ctx:
            upload_artifacts.main()
        assert ctx.value.code == 1

    @patch.dict(
        "os.environ",
        {
            "INPUT_TAG": "v1.0.0",
            "INPUT_ARTIFACTS": "dist/*.whl",
            "GH_TOKEN": "",
            "GITHUB_REPOSITORY": "owner/repo",
        },
    )
    def test_main_missing_token_exits(self) -> None:
        """Test missing GH_TOKEN causes exit."""
        with pytest.raises(SystemExit) as ctx:
            upload_artifacts.main()
        assert ctx.value.code == 1

    @patch.dict(
        "os.environ",
        {
            "INPUT_TAG": "v1.0.0",
            "INPUT_ARTIFACTS": "",
            "GH_TOKEN": "token123",
            "GITHUB_REPOSITORY": "owner/repo",
        },
    )
    def test_main_missing_artifacts_exits(self) -> None:
        """Test missing INPUT_ARTIFACTS causes exit."""
        with pytest.raises(SystemExit) as ctx:
            upload_artifacts.main()
        assert ctx.value.code == 1


if __name__ == "__main__":
    unittest.main()
