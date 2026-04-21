import hashlib
import importlib.util
import stat
import tarfile
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "build-homebrew-bottle" / "scripts" / "build_bottle.py"

spec = importlib.util.spec_from_file_location("build_bottle", str(_SCRIPT))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


# ---------------------------------------------------------------------------
# build_bottle_dir_structure
# ---------------------------------------------------------------------------


def test_build_bottle_dir_structure(tmp_path):
    binary = tmp_path / "mytool"
    binary.write_bytes(b"\x7fELF")

    dest = tmp_path / "bottle"
    result = mod.build_bottle_dir_structure(binary, "mytool", "1.2.3", dest)

    assert result == dest
    assert (dest / "mytool" / "1.2.3" / "bin" / "mytool").exists()


def test_build_bottle_dir_structure_binary_executable(tmp_path):
    binary = tmp_path / "mytool"
    binary.write_bytes(b"\x7fELF")
    binary.chmod(0o755)

    dest = tmp_path / "bottle"
    mod.build_bottle_dir_structure(binary, "mytool", "1.2.3", dest)

    copied = dest / "mytool" / "1.2.3" / "bin" / "mytool"
    mode = copied.stat().st_mode
    assert mode & stat.S_IXUSR


def test_build_bottle_dir_structure_missing_binary(tmp_path):
    dest = tmp_path / "bottle"
    with pytest.raises(SystemExit):
        mod.build_bottle_dir_structure(tmp_path / "nonexistent", "mytool", "1.2.3", dest)


# ---------------------------------------------------------------------------
# create_bottle_tarball
# ---------------------------------------------------------------------------


def test_create_bottle_tarball(tmp_path):
    bottle_root = tmp_path / "bottle"
    (bottle_root / "mytool" / "1.2.3" / "bin").mkdir(parents=True)
    (bottle_root / "mytool" / "1.2.3" / "bin" / "mytool").write_bytes(b"binary")

    tarball = mod.create_bottle_tarball(bottle_root, "mytool", "1.2.3", "arm64_sequoia")

    assert tarball.exists()
    assert tarfile.is_tarfile(str(tarball))


def test_create_bottle_tarball_filename(tmp_path):
    bottle_root = tmp_path / "bottle"
    (bottle_root / "mytool" / "1.2.3" / "bin").mkdir(parents=True)
    (bottle_root / "mytool" / "1.2.3" / "bin" / "mytool").write_bytes(b"binary")

    tarball = mod.create_bottle_tarball(bottle_root, "mytool", "1.2.3", "ventura")

    assert tarball.name == "mytool-1.2.3.ventura.bottle.tar.gz"


# ---------------------------------------------------------------------------
# compute_bottle_sha256
# ---------------------------------------------------------------------------


def test_compute_bottle_sha256(tmp_path):
    content = b"hello homebrew"
    f = tmp_path / "bottle.tar.gz"
    f.write_bytes(content)

    expected = hashlib.sha256(content).hexdigest()
    assert mod.compute_bottle_sha256(f) == expected


def test_compute_bottle_sha256_deterministic(tmp_path):
    f = tmp_path / "bottle.tar.gz"
    f.write_bytes(b"deterministic")

    assert mod.compute_bottle_sha256(f) == mod.compute_bottle_sha256(f)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def test_main_creates_outputs(tmp_path, monkeypatch):
    binary = tmp_path / "mytool"
    binary.write_bytes(b"\x7fELF")
    binary.chmod(0o755)

    output_file = tmp_path / "github_output.txt"
    output_file.touch()

    monkeypatch.setenv("INPUT_BINARY_PATH", str(binary))
    monkeypatch.setenv("INPUT_FORMULA_NAME", "mytool")
    monkeypatch.setenv("INPUT_VERSION", "1.2.3")
    monkeypatch.setenv("INPUT_BOTTLE_TAG", "arm64_sequoia")
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))

    mod.main()

    output_text = output_file.read_text()
    assert "filename=" in output_text
    assert "sha256=" in output_text
    assert "path=" in output_text
    assert "mytool-1.2.3.arm64_sequoia.bottle.tar.gz" in output_text


def test_main_missing_binary(tmp_path, monkeypatch):
    output_file = tmp_path / "github_output.txt"
    output_file.touch()

    monkeypatch.setenv("INPUT_BINARY_PATH", str(tmp_path / "nonexistent"))
    monkeypatch.setenv("INPUT_FORMULA_NAME", "mytool")
    monkeypatch.setenv("INPUT_VERSION", "1.2.3")
    monkeypatch.setenv("INPUT_BOTTLE_TAG", "arm64_sequoia")
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))

    with pytest.raises(SystemExit):
        mod.main()
