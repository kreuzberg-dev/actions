from pathlib import Path

import pytest


@pytest.fixture
def tmp_path_with_files(tmp_path: Path) -> Path:
    """Create a temp directory with a few test files for hashing."""
    (tmp_path / "a.rs").write_text("fn main() {}")
    (tmp_path / "b.rs").write_text("fn test() {}")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "c.rs").write_text("mod sub;")
    return tmp_path


@pytest.fixture
def github_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a temp file for GITHUB_OUTPUT and set the env var."""
    output_file = tmp_path / "github_output.txt"
    output_file.touch()
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
    return output_file
