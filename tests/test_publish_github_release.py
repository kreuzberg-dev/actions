import importlib.util
from pathlib import Path

_ENSURE_RELEASE_PATH = Path(__file__).resolve().parents[1] / "publish-github-release" / "scripts" / "ensure_release.py"
_UPLOAD_ARTIFACTS_PATH = (
    Path(__file__).resolve().parents[1] / "publish-github-release" / "scripts" / "upload_artifacts.py"
)


def _import_script(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ensure_mod = _import_script("ensure_release", _ENSURE_RELEASE_PATH)
upload_mod = _import_script("upload_artifacts", _UPLOAD_ARTIFACTS_PATH)


# ---------------------------------------------------------------------------
# build_create_flags
# ---------------------------------------------------------------------------


def test_build_create_flags_default():
    flags = ensure_mod.build_create_flags("v1.2.3", generate_notes=True, draft=False, prerelease=False)

    assert "--title" in flags
    assert "v1.2.3" in flags
    assert "--generate-notes" in flags
    assert "--draft" not in flags
    assert "--prerelease" not in flags


def test_build_create_flags_draft():
    flags = ensure_mod.build_create_flags("v1.2.3", generate_notes=True, draft=True, prerelease=False)

    assert "--draft" in flags
    assert "--prerelease" not in flags


def test_build_create_flags_prerelease():
    flags = ensure_mod.build_create_flags("v1.2.3", generate_notes=True, draft=False, prerelease=True)

    assert "--prerelease" in flags
    assert "--draft" not in flags


def test_build_create_flags_no_generate_notes():
    flags = ensure_mod.build_create_flags("v1.2.3", generate_notes=False, draft=False, prerelease=False)

    assert "--generate-notes" not in flags
    assert "--title" in flags


# ---------------------------------------------------------------------------
# expand_artifact_patterns
# ---------------------------------------------------------------------------


def test_expand_artifact_patterns(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "package-1.0.0.whl").write_text("fake")
    (tmp_path / "package-1.0.0.tar.gz").write_text("fake")
    (tmp_path / "unrelated.txt").write_text("ignore me")

    result = upload_mod.expand_artifact_patterns("*.whl,*.tar.gz")

    names = {p.name for p in result}
    assert "package-1.0.0.whl" in names
    assert "package-1.0.0.tar.gz" in names
    assert "unrelated.txt" not in names


def test_expand_artifact_patterns_newline(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "artifact.zip").write_text("fake")

    result = upload_mod.expand_artifact_patterns("*.zip\n*.tar.gz")

    assert any(p.name == "artifact.zip" for p in result)


def test_expand_artifact_patterns_no_match(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    result = upload_mod.expand_artifact_patterns("*.nupkg,*.whl")

    assert result == []


def test_expand_artifact_patterns_mixed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "found.whl").write_text("fake")
    # No .tar.gz files present

    result = upload_mod.expand_artifact_patterns("*.whl,*.tar.gz")

    assert len(result) == 1
    assert result[0].name == "found.whl"
