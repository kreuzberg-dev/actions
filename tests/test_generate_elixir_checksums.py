import hashlib
import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "generate-elixir-checksums" / "scripts" / "generate.py"

spec = importlib.util.spec_from_file_location("generate_elixir_checksums", str(_SCRIPT))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


# ---------------------------------------------------------------------------
# build_nif_artifact_name
# ---------------------------------------------------------------------------


def test_build_nif_artifact_name_linux():
    result = mod.build_nif_artifact_name("kreuzberg", "1.2.3", "2.17", "x86_64-unknown-linux-gnu")
    assert result == "libkreuzberg-v1.2.3-nif-2.17-x86_64-unknown-linux-gnu.so.tar.gz"


def test_build_nif_artifact_name_darwin():
    result = mod.build_nif_artifact_name("kreuzberg", "1.2.3", "2.16", "aarch64-apple-darwin")
    assert result == "libkreuzberg-v1.2.3-nif-2.16-aarch64-apple-darwin.dylib.tar.gz"


def test_build_nif_artifact_name_windows():
    result = mod.build_nif_artifact_name("mylib", "0.5.0", "2.17", "x86_64-pc-windows-msvc")
    assert result == "libmylib-v0.5.0-nif-2.17-x86_64-pc-windows-msvc.dll.tar.gz"


# ---------------------------------------------------------------------------
# build_download_url
# ---------------------------------------------------------------------------


def test_build_download_url():
    result = mod.build_download_url("org/repo", "v1.2.3", "libfoo-v1.2.3-nif-2.17-x86_64-unknown-linux-gnu.so.tar.gz")
    assert result == (
        "https://github.com/org/repo/releases/download/v1.2.3/libfoo-v1.2.3-nif-2.17-x86_64-unknown-linux-gnu.so.tar.gz"
    )


# ---------------------------------------------------------------------------
# format_checksum_file
# ---------------------------------------------------------------------------


def test_format_checksum_file_single():
    checksums = {"libfoo-v1.0.0-nif-2.17-x86_64-unknown-linux-gnu.so.tar.gz": "a" * 64}
    result = mod.format_checksum_file(checksums)

    assert result.startswith("%{")
    assert "sha256:" in result
    assert result.strip().endswith("}")


def test_format_checksum_file_multiple():
    checksums = {
        "libfoo-v1.0.0-nif-2.17-x86_64-unknown-linux-gnu.so.tar.gz": "a" * 64,
        "libfoo-v1.0.0-nif-2.16-aarch64-apple-darwin.dylib.tar.gz": "b" * 64,
    }
    result = mod.format_checksum_file(checksums)

    assert result.count("sha256:") == 2
    assert "libfoo-v1.0.0-nif-2.17" in result
    assert "libfoo-v1.0.0-nif-2.16" in result


def test_format_checksum_file_empty():
    result = mod.format_checksum_file({})
    assert result == "%{\n}\n"


def test_format_checksum_file_sorted():
    checksums = {
        "z_file.so.tar.gz": "z" * 64,
        "a_file.so.tar.gz": "a" * 64,
        "m_file.so.tar.gz": "m" * 64,
    }
    result = mod.format_checksum_file(checksums)
    lines = [ln.strip() for ln in result.splitlines() if "=>" in ln]

    keys = [ln.split('"')[1] for ln in lines]
    assert keys == sorted(keys)


# ---------------------------------------------------------------------------
# compute_sha256_hex
# ---------------------------------------------------------------------------


def test_compute_sha256_hex():
    data = b"hello elixir"
    expected = hashlib.sha256(data).hexdigest()
    assert mod.compute_sha256_hex(data) == expected


def test_compute_sha256_hex_empty():
    expected = hashlib.sha256(b"").hexdigest()
    assert mod.compute_sha256_hex(b"") == expected
