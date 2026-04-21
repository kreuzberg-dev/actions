import importlib.util
import subprocess
import sys
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "build-and-cache-binding" / "scripts" / "compute_hash.py"


def _import_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


compute_hash = _import_script("compute_hash", _SCRIPT_PATH)


# ---------------------------------------------------------------------------
# hash_file
# ---------------------------------------------------------------------------


def test_hash_file_returns_digest_and_path(tmp_path):
    f = tmp_path / "hello.txt"
    f.write_text("hello world")
    result = compute_hash.hash_file(f)
    assert result is not None
    hex_part, path_part = result.split("  ", 1)
    assert len(hex_part) == 64
    assert all(c in "0123456789abcdef" for c in hex_part)
    assert path_part == str(f)


def test_hash_file_returns_none_on_missing(tmp_path):
    result = compute_hash.hash_file(tmp_path / "nonexistent.txt")
    assert result is None


# ---------------------------------------------------------------------------
# is_excluded
# ---------------------------------------------------------------------------


def test_is_excluded_hidden_dir():
    assert compute_hash.is_excluded(Path(".git/config")) is True


def test_is_excluded_build_dirs():
    for dir_name in ("target", "node_modules", ".venv", "dist", "build"):
        assert compute_hash.is_excluded(Path(dir_name) / "foo.txt") is True, f"{dir_name}/ should be excluded"


def test_is_excluded_normal_path():
    assert compute_hash.is_excluded(Path("src/main.rs")) is False


# ---------------------------------------------------------------------------
# collect_files_mode
# ---------------------------------------------------------------------------


def test_collect_files_mode(tmp_path):
    files = [tmp_path / f"file{i}.txt" for i in range(3)]
    for f in files:
        f.write_text(f"content {f.name}")
    results = compute_hash.collect_files_mode([str(f) for f in files])
    assert len(results) == 3


def test_collect_files_mode_missing_file(tmp_path):
    existing = tmp_path / "exists.txt"
    existing.write_text("data")
    missing = tmp_path / "missing.txt"
    results = compute_hash.collect_files_mode([str(existing), str(missing)])
    assert len(results) == 1
    assert str(existing) in results[0]


# ---------------------------------------------------------------------------
# collect_dirs_mode
# ---------------------------------------------------------------------------


def test_collect_dirs_mode(tmp_path):
    (tmp_path / "a.rs").write_text("fn a() {}")
    (tmp_path / "b.rs").write_text("fn b() {}")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "c.rs").write_text("fn c() {}")
    results = compute_hash.collect_dirs_mode([str(tmp_path)])
    assert len(results) == 3


def test_collect_dirs_mode_excludes_build_dirs(tmp_path):
    (tmp_path / "src.rs").write_text("fn main() {}")
    target = tmp_path / "target"
    target.mkdir()
    (target / "artifact.o").write_bytes(b"\x00\x01\x02")
    results = compute_hash.collect_dirs_mode([str(tmp_path)])
    assert len(results) == 1
    assert all("target" not in r for r in results)


def test_collect_dirs_mode_missing_dir(tmp_path):
    results = compute_hash.collect_dirs_mode([str(tmp_path / "nonexistent")])
    assert results == []


# ---------------------------------------------------------------------------
# collect_glob_mode
# ---------------------------------------------------------------------------


def test_collect_glob_mode_simple(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "Cargo.toml").write_text("[package]")
    (tmp_path / "Cargo.lock").write_text("# lock")
    results = compute_hash.collect_glob_mode(["Cargo.*"])
    assert len(results) == 2


def test_collect_glob_mode_recursive(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.rs").write_text("fn main() {}")
    (src / "lib.rs").write_text("pub fn lib() {}")
    results = compute_hash.collect_glob_mode(["**/*.rs"])
    assert len(results) == 2


def test_collect_glob_mode_recursive_excludes_hidden(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    (src / "real.rs").write_text("fn real() {}")
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text("[core]")
    results = compute_hash.collect_glob_mode(["**/*"])
    paths = [r.split("  ", 1)[1] for r in results]
    assert all(".git" not in p for p in paths)
    assert any("real.rs" in p for p in paths)


# ---------------------------------------------------------------------------
# compute_final_hash
# ---------------------------------------------------------------------------


def test_compute_final_hash_deterministic():
    entries = ["aabbcc  file1.txt", "ddeeff  file2.txt", "001122  file3.txt"]
    hash_a = compute_hash.compute_final_hash(entries)
    hash_b = compute_hash.compute_final_hash(list(reversed(entries)))
    assert hash_a == hash_b


def test_compute_final_hash_length():
    result = compute_hash.compute_final_hash(["abc123  foo.txt"])
    assert len(result) == 64
    assert all(c in "0123456789abcdef" for c in result)


# ---------------------------------------------------------------------------
# main() via subprocess
# ---------------------------------------------------------------------------


def test_main_files_mode(tmp_path):
    f = tmp_path / "input.txt"
    f.write_text("some data")
    result = subprocess.run(
        [sys.executable, str(_SCRIPT_PATH), "--files", str(f)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    output = result.stdout.strip()
    assert len(output) == 12
    assert all(c in "0123456789abcdef" for c in output)


def test_main_no_args_returns_error():
    result = subprocess.run(
        [sys.executable, str(_SCRIPT_PATH)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "Error" in result.stderr


def test_main_no_matching_files(tmp_path):
    result = subprocess.run(
        [sys.executable, str(_SCRIPT_PATH), "*.nonexistent_xyz"],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        check=False,
    )
    assert result.returncode == 1
    assert "Error" in result.stderr
