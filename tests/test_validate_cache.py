import importlib.util
import sys
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "build-and-cache-binding" / "scripts" / "validate_cache.py"


def _import_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validate_cache = _import_script("validate_cache", _SCRIPT_PATH)


# ---------------------------------------------------------------------------
# check_wasm_magic
# ---------------------------------------------------------------------------


def test_check_wasm_magic_valid(tmp_path):
    f = tmp_path / "module.wasm"
    f.write_bytes(b"\x00asm\x01\x00\x00\x00")
    assert validate_cache.check_wasm_magic(f) is True


def test_check_wasm_magic_invalid(tmp_path):
    f = tmp_path / "module.wasm"
    f.write_bytes(b"\xff\xfe\xfd\xfc")
    assert validate_cache.check_wasm_magic(f) is False


# ---------------------------------------------------------------------------
# validate_wasm_dir
# ---------------------------------------------------------------------------


def test_validate_wasm_dir_valid_files(tmp_path):
    for i in range(3):
        (tmp_path / f"mod{i}.wasm").write_bytes(b"\x00asm\x01\x00\x00\x00" + b"\x00" * 8)
    valid, invalid, missing = validate_cache.validate_wasm_dir(tmp_path)
    assert valid == 3
    assert invalid == 0
    assert missing == 0


def test_validate_wasm_dir_empty_file(tmp_path):
    (tmp_path / "empty.wasm").write_bytes(b"")
    valid, invalid, missing = validate_cache.validate_wasm_dir(tmp_path)
    assert valid == 0
    assert invalid == 1
    assert missing == 0


def test_validate_wasm_dir_invalid_magic(tmp_path):
    (tmp_path / "bad.wasm").write_bytes(b"\xde\xad\xbe\xef")
    valid, invalid, missing = validate_cache.validate_wasm_dir(tmp_path)
    assert valid == 0
    assert invalid == 1
    assert missing == 0


def test_validate_wasm_dir_no_wasm_files(tmp_path):
    (tmp_path / "README.txt").write_text("nothing here")
    valid, invalid, missing = validate_cache.validate_wasm_dir(tmp_path)
    assert valid == 0
    assert invalid == 0
    assert missing == 1


# ---------------------------------------------------------------------------
# validate_ffi_dir
# ---------------------------------------------------------------------------


def test_validate_ffi_dir_no_ffi_files(tmp_path):
    (tmp_path / "README.txt").write_text("no libraries here")
    valid, invalid, missing = validate_cache.validate_ffi_dir(tmp_path)
    assert valid == 0
    assert invalid == 0
    assert missing == 1


def test_validate_ffi_dir_empty_file(tmp_path):
    (tmp_path / "lib.so").write_bytes(b"")
    valid, invalid, missing = validate_cache.validate_ffi_dir(tmp_path)
    assert valid == 0
    assert invalid == 1
    assert missing == 0


# ---------------------------------------------------------------------------
# validate_path
# ---------------------------------------------------------------------------


def test_validate_path_directory_generic(tmp_path):
    (tmp_path / "artifact.bin").write_bytes(b"\x01\x02\x03")
    valid, invalid, missing = validate_cache.validate_path("generic", str(tmp_path))
    assert valid == 1
    assert invalid == 0
    assert missing == 0


def test_validate_path_missing_file(tmp_path):
    valid, invalid, missing = validate_cache.validate_path("generic", str(tmp_path / "nonexistent.so"))
    assert valid == 0
    assert invalid == 0
    assert missing == 1


def test_validate_path_empty_file(tmp_path):
    f = tmp_path / "empty.bin"
    f.write_bytes(b"")
    valid, invalid, missing = validate_cache.validate_path("generic", str(f))
    assert valid == 0
    assert invalid == 1
    assert missing == 0


def test_validate_path_valid_file(tmp_path):
    f = tmp_path / "artifact.bin"
    f.write_bytes(b"\xca\xfe\xba\xbe")
    valid, invalid, missing = validate_cache.validate_path("generic", str(f))
    assert valid == 1
    assert invalid == 0
    assert missing == 0


# ---------------------------------------------------------------------------
# main() entry point
# ---------------------------------------------------------------------------


def test_main_wasm_valid(tmp_path, monkeypatch):
    wasm_dir = tmp_path / "wasm_out"
    wasm_dir.mkdir()
    (wasm_dir / "module.wasm").write_bytes(b"\x00asm\x01\x00\x00\x00")
    monkeypatch.setattr(sys, "argv", ["validate_cache.py", "wasm", str(wasm_dir)])
    assert validate_cache.main() == 0


def test_main_invalid_returns_1(tmp_path, monkeypatch):
    wasm_dir = tmp_path / "wasm_out"
    wasm_dir.mkdir()
    (wasm_dir / "bad.wasm").write_bytes(b"\xff\xff\xff\xff")
    monkeypatch.setattr(sys, "argv", ["validate_cache.py", "wasm", str(wasm_dir)])
    assert validate_cache.main() == 1


def test_main_no_valid_returns_1(tmp_path, monkeypatch):
    empty_dir = tmp_path / "empty_out"
    empty_dir.mkdir()
    monkeypatch.setattr(sys, "argv", ["validate_cache.py", "wasm", str(empty_dir)])
    assert validate_cache.main() == 1


def test_main_too_few_args(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["validate_cache.py", "wasm"])
    assert validate_cache.main() == 1
