import hashlib
import importlib.util
from pathlib import Path
from urllib.error import URLError

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "publish-homebrew" / "scripts" / "publish.py"

spec = importlib.util.spec_from_file_location("publish_homebrew", str(_SCRIPT))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


# ---------------------------------------------------------------------------
# validate_sha256
# ---------------------------------------------------------------------------


def test_validate_sha256_valid():
    digest = "a" * 64
    assert mod.validate_sha256(digest) is True


def test_validate_sha256_valid_hex_chars():
    digest = "0123456789abcdef" * 4
    assert mod.validate_sha256(digest) is True


def test_validate_sha256_invalid_short():
    assert mod.validate_sha256("a" * 63) is False


def test_validate_sha256_invalid_chars():
    # Uppercase is not valid (the regex requires lowercase only)
    digest = "A" * 64
    assert mod.validate_sha256(digest) is False


def test_validate_sha256_invalid_non_hex():
    digest = "g" * 64
    assert mod.validate_sha256(digest) is False


# ---------------------------------------------------------------------------
# compute_sha256
# ---------------------------------------------------------------------------


def test_compute_sha256(tmp_path):
    f = tmp_path / "test.bin"
    content = b"hello world"
    f.write_bytes(content)

    expected = hashlib.sha256(content).hexdigest()
    result = mod.compute_sha256(f)

    assert result == expected
    assert mod.validate_sha256(result) is True


def test_compute_sha256_missing_file(tmp_path):
    with pytest.raises(ValueError, match="File not found"):
        mod.compute_sha256(tmp_path / "nonexistent.bin")


def test_compute_sha256_empty_file(tmp_path):
    f = tmp_path / "empty.bin"
    f.write_bytes(b"")

    expected = hashlib.sha256(b"").hexdigest()
    assert mod.compute_sha256(f) == expected


# ---------------------------------------------------------------------------
# parse_bottle_tag
# ---------------------------------------------------------------------------


def test_parse_bottle_tag():
    result = mod.parse_bottle_tag("kreuzberg-4.4.5.arm64_sequoia.bottle.tar.gz", "kreuzberg")
    assert result == "arm64_sequoia"


def test_parse_bottle_tag_ventura():
    result = mod.parse_bottle_tag("myformula-1.0.0.ventura.bottle.tar.gz", "myformula")
    assert result == "ventura"


def test_parse_bottle_tag_no_match():
    with pytest.raises(ValueError, match="Could not parse bottle tag"):
        mod.parse_bottle_tag("invalid-filename.tar.gz", "kreuzberg")


def test_parse_bottle_tag_wrong_formula():
    with pytest.raises(ValueError, match="Could not parse bottle tag"):
        mod.parse_bottle_tag("other-4.4.5.arm64_sequoia.bottle.tar.gz", "kreuzberg")


# ---------------------------------------------------------------------------
# build_bottle_block
# ---------------------------------------------------------------------------


def test_build_bottle_block():
    bottle_hashes = {"arm64_sequoia": "a" * 64}
    bottle_tags = ["arm64_sequoia"]
    result = mod.build_bottle_block("org/repo", "v1.0.0", bottle_hashes, bottle_tags)

    assert "bottle do" in result
    assert 'root_url "https://github.com/org/repo/releases/download/v1.0.0"' in result
    assert f'sha256 cellar: :any_skip_relocation, arm64_sequoia: "{"a" * 64}"' in result
    assert result.strip().endswith("end")


def test_build_bottle_block_multiple_tags():
    bottle_hashes = {
        "arm64_sequoia": "a" * 64,
        "ventura": "b" * 64,
        "monterey": "c" * 64,
    }
    bottle_tags = ["arm64_sequoia", "ventura", "monterey"]
    result = mod.build_bottle_block("org/repo", "v2.3.4", bottle_hashes, bottle_tags)

    assert "arm64_sequoia" in result
    assert "ventura" in result
    assert "monterey" in result
    # Verify ordering matches bottle_tags
    pos_arm64 = result.index("arm64_sequoia")
    pos_ventura = result.index("ventura")
    pos_monterey = result.index("monterey")
    assert pos_arm64 < pos_ventura < pos_monterey


def test_build_bottle_block_indentation():
    bottle_hashes = {"sequoia": "d" * 64}
    bottle_tags = ["sequoia"]
    result = mod.build_bottle_block("org/repo", "v1.0.0", bottle_hashes, bottle_tags)
    lines = result.splitlines()

    assert lines[0] == "  bottle do"
    assert lines[-1] == "  end"
    for line in lines[1:-1]:
        assert line.startswith("    ")


# ---------------------------------------------------------------------------
# update_formula_url_and_sha
# ---------------------------------------------------------------------------


_OLD_SHA = "a1b2c3d4e5f6" * 4 + "a1b2c3d4e5f6a1b2c3d4"  # 64 hex chars

SAMPLE_FORMULA = f"""\
class Kreuzberg < Formula
  desc "A tool"
  homepage "https://github.com/org/repo"
  url "https://github.com/org/repo/archive/v1.0.0.tar.gz"
  sha256 "{_OLD_SHA}"
  license "MIT"

  depends_on :macos
end
"""


def test_update_formula_url_and_sha():
    new_sha = "n" * 64
    result = mod.update_formula_url_and_sha(SAMPLE_FORMULA, "org/repo", "v2.0.0", new_sha)

    assert 'url "https://github.com/org/repo/archive/v2.0.0.tar.gz"' in result
    assert f'sha256 "{new_sha}"' in result
    assert "v1.0.0" not in result
    assert _OLD_SHA not in result


def test_update_formula_url_and_sha_single_quoted_sha():
    content = """\
  url "https://github.com/org/repo/archive/v1.0.0.tar.gz"
  sha256 'abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890'
"""
    new_sha = "f" * 64
    result = mod.update_formula_url_and_sha(content, "org/repo", "v2.0.0", new_sha)

    assert f'sha256 "{new_sha}"' in result
    assert "abcdef" not in result


def test_update_formula_url_and_sha_preserves_rest():
    new_sha = "e" * 64
    result = mod.update_formula_url_and_sha(SAMPLE_FORMULA, "org/repo", "v2.0.0", new_sha)

    assert 'desc "A tool"' in result
    assert 'license "MIT"' in result
    assert "depends_on :macos" in result


# ---------------------------------------------------------------------------
# remove_bottle_blocks
# ---------------------------------------------------------------------------


FORMULA_WITH_BOTTLE = """\
class Kreuzberg < Formula
  url "https://github.com/org/repo/archive/v1.0.0.tar.gz"
  sha256 "aabbccdd" * 8

  bottle do
    root_url "https://github.com/org/repo/releases/download/v1.0.0"
    sha256 cellar: :any_skip_relocation, arm64_sequoia: "aabbcc"
  end

  depends_on :macos
end
"""

FORMULA_WITH_COMMENTED_BOTTLE = """\
class Kreuzberg < Formula
  url "https://github.com/org/repo/archive/v1.0.0.tar.gz"

  # bottle do
  #   sha256 cellar: :any_skip_relocation, arm64_sequoia: "aabbcc"
  # end

  depends_on :macos
end
"""


def test_remove_bottle_blocks():
    result = mod.remove_bottle_blocks(FORMULA_WITH_BOTTLE)

    assert "bottle do" not in result
    assert "root_url" not in result
    assert "depends_on :macos" in result


def test_remove_bottle_blocks_commented():
    result = mod.remove_bottle_blocks(FORMULA_WITH_COMMENTED_BOTTLE)

    assert "# bottle do" not in result
    assert "# end" not in result
    assert "depends_on :macos" in result


def test_remove_bottle_blocks_no_existing():
    content = """\
class Kreuzberg < Formula
  url "https://github.com/org/repo/archive/v1.0.0.tar.gz"
  depends_on :macos
end
"""
    result = mod.remove_bottle_blocks(content)
    assert result == content


# ---------------------------------------------------------------------------
# insert_bottle_block
# ---------------------------------------------------------------------------


FORMULA_WITH_DEPENDS_ON = """\
class Kreuzberg < Formula
  url "https://github.com/org/repo/archive/v1.0.0.tar.gz"
  sha256 "{sha}"

  depends_on :macos
end
""".format(sha="a" * 64)

BOTTLE_BLOCK = """\
  bottle do
    root_url "https://github.com/org/repo/releases/download/v1.0.0"
    sha256 cellar: :any_skip_relocation, arm64_sequoia: "{sha}"
  end""".format(sha="b" * 64)


def test_insert_bottle_block():
    result = mod.insert_bottle_block(FORMULA_WITH_DEPENDS_ON, BOTTLE_BLOCK)

    bottle_pos = result.index("bottle do")
    depends_pos = result.index("depends_on")
    assert bottle_pos < depends_pos


def test_insert_bottle_block_blank_line_between():
    result = mod.insert_bottle_block(FORMULA_WITH_DEPENDS_ON, BOTTLE_BLOCK)
    lines = result.splitlines()

    end_idx = next(i for i, ln in enumerate(lines) if ln.strip() == "end" and "bottle" not in lines[max(0, i - 5) : i])
    # There should be a blank line between the bottle block end and depends_on
    assert lines[end_idx + 1].strip() == ""


def test_insert_bottle_block_no_depends_on():
    formula = """\
class Kreuzberg < Formula
  url "https://github.com/org/repo/archive/v1.0.0.tar.gz"
end
"""
    result = mod.insert_bottle_block(formula, BOTTLE_BLOCK)
    # Block should still be present (appended)
    assert "bottle do" in result


def test_insert_bottle_block_no_consecutive_blanks():
    formula = """\
class Kreuzberg < Formula
  url "https://github.com/org/repo/archive/v1.0.0.tar.gz"


  depends_on :macos
end
"""
    result = mod.insert_bottle_block(formula, BOTTLE_BLOCK)
    lines = result.splitlines()
    for i in range(len(lines) - 1):
        assert not (lines[i].strip() == "" and lines[i + 1].strip() == ""), f"Consecutive blank lines at index {i}"


# ---------------------------------------------------------------------------
# download_with_retry
# ---------------------------------------------------------------------------


def test_download_with_retry_success(tmp_path, monkeypatch):
    output = tmp_path / "file.tar.gz"
    call_count = 0

    def mock_urlretrieve(url, dest):
        nonlocal call_count
        call_count += 1
        Path(dest).write_bytes(b"data")

    monkeypatch.setattr(mod.urllib.request, "urlretrieve", mock_urlretrieve)
    monkeypatch.setattr(mod.time, "sleep", lambda _: None)

    result = mod.download_with_retry("https://example.com/file.tar.gz", output, max_retries=3, retry_delay=0)

    assert result is True
    assert call_count == 1


def test_download_with_retry_fails_then_succeeds(tmp_path, monkeypatch):
    output = tmp_path / "file.tar.gz"
    call_count = 0

    def mock_urlretrieve(url, dest):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise URLError("connection reset")
        Path(dest).write_bytes(b"data")

    monkeypatch.setattr(mod.urllib.request, "urlretrieve", mock_urlretrieve)
    monkeypatch.setattr(mod.time, "sleep", lambda _: None)

    result = mod.download_with_retry("https://example.com/file.tar.gz", output, max_retries=3, retry_delay=0)

    assert result is True
    assert call_count == 3


def test_download_with_retry_all_fail(tmp_path, monkeypatch):
    output = tmp_path / "file.tar.gz"

    def mock_urlretrieve(url, dest):
        raise URLError("timeout")

    monkeypatch.setattr(mod.urllib.request, "urlretrieve", mock_urlretrieve)
    monkeypatch.setattr(mod.time, "sleep", lambda _: None)

    result = mod.download_with_retry("https://example.com/file.tar.gz", output, max_retries=3, retry_delay=0)

    assert result is False


def test_download_with_retry_respects_retry_delay(tmp_path, monkeypatch):
    output = tmp_path / "file.tar.gz"
    sleep_calls: list[float] = []
    call_count = 0

    def mock_urlretrieve(url, dest):
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise URLError("timeout")
        Path(dest).write_bytes(b"data")

    monkeypatch.setattr(mod.urllib.request, "urlretrieve", mock_urlretrieve)
    monkeypatch.setattr(mod.time, "sleep", sleep_calls.append)

    mod.download_with_retry("https://example.com/file.tar.gz", output, max_retries=3, retry_delay=7)

    assert sleep_calls == [7]
