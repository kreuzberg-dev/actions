import importlib.util
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "publish-maven" / "scripts" / "deploy.py"


def _import_script(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


maven_mod = _import_script("deploy_maven", _SCRIPT_PATH)


def test_build_mvn_args_default():
    args = maven_mod.build_mvn_args("pom.xml", "publish", "")

    assert args[0] == "-f"
    assert args[1] == "pom.xml"
    assert "-P" in args
    assert "publish" in args
    assert "-B" in args
    assert "--no-transfer-progress" in args


def test_build_mvn_args_with_extras():
    args = maven_mod.build_mvn_args("pom.xml", "publish", "-Dgpg.skip=true -DstagingProgressTimeoutMinutes=10")

    assert "-Dgpg.skip=true" in args
    assert "-DstagingProgressTimeoutMinutes=10" in args
    assert "-B" in args
    assert "--no-transfer-progress" in args


def test_is_already_published_true():
    log = (
        "[ERROR] Failed: component with package url maven:/com.example:mylib:1.2.3 already exists\n"
        "[ERROR] See https://issues.sonatype.org for details"
    )
    assert maven_mod.is_already_published(log) is True


def test_is_already_published_false():
    log = "[ERROR] Some other deployment error occurred\n[ERROR] Connection refused"
    assert maven_mod.is_already_published(log) is False


def test_classifier_remap_osx_to_macos():
    """Verify osx-* classifiers are remapped to macos-* for NativeLib resolution."""
    cases = [
        ("osx-aarch64", "macos-aarch64"),
        ("osx-x86_64", "macos-x86_64"),
        ("linux-aarch64", "linux-aarch64"),
        ("linux-x86_64", "linux-x86_64"),
        ("windows-aarch64", "windows-aarch64"),
        ("windows-x86_64", "windows-x86_64"),
    ]
    for classifier, expected_rid in cases:
        rid = classifier.replace("osx-", "macos-")
        assert rid == expected_rid, f"Failed to remap {classifier} → {expected_rid}"


def _write_pom(directory: Path, body: str) -> str:
    """Write a namespaced pom.xml containing `body` and return its path."""
    pom = directory / "pom.xml"
    pom.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<project xmlns="http://maven.apache.org/POM/4.0.0">\n'
        f"{body}\n"
        "</project>\n"
    )
    return str(pom)


def test_normalize_release_version_strips_tag_prefix():
    assert maven_mod.normalize_release_version("v1.19.0") == "1.19.0"
    assert maven_mod.normalize_release_version("  1.19.0 ") == "1.19.0"
    assert maven_mod.normalize_release_version("") == ""


def test_read_pom_version_reads_the_project_version(tmp_path: Path):
    pom = _write_pom(tmp_path, "  <artifactId>liter-llm</artifactId>\n  <version>1.19.0</version>")

    assert maven_mod.read_pom_version(pom) == "1.19.0"


def test_read_pom_version_falls_back_to_the_inherited_parent_version(tmp_path: Path):
    pom = _write_pom(
        tmp_path,
        "  <parent>\n    <groupId>io.xberg</groupId>\n    <artifactId>parent</artifactId>\n"
        "    <version>1.19.0</version>\n  </parent>\n  <artifactId>liter-llm</artifactId>",
    )

    assert maven_mod.read_pom_version(pom) == "1.19.0"


def test_read_pom_version_reads_a_pom_without_a_namespace(tmp_path: Path):
    pom = tmp_path / "pom.xml"
    pom.write_text("<project>\n  <artifactId>liter-llm</artifactId>\n  <version>1.19.0</version>\n</project>\n")

    assert maven_mod.read_pom_version(str(pom)) == "1.19.0"


def test_read_pom_version_returns_none_for_a_property_placeholder(tmp_path: Path):
    """`${revision}` resolves only at build time, so the version must be reported undeterminable."""
    pom = _write_pom(tmp_path, "  <artifactId>liter-llm</artifactId>\n  <version>${revision}</version>")

    assert maven_mod.read_pom_version(pom) is None


def test_extract_published_version_reads_a_purl():
    log = "[ERROR] component with package url 'pkg:maven/io.xberg/liter-llm@1.18.4' already exists"

    assert maven_mod.extract_published_version(log) == "1.18.4"


def test_extract_published_version_reads_a_legacy_coordinate():
    log = "[ERROR] Failed: component with package url maven:/com.example:mylib:1.2.3 already exists"

    assert maven_mod.extract_published_version(log) == "1.2.3"


def test_extract_published_version_returns_none_without_a_coordinate():
    assert maven_mod.extract_published_version("[ERROR] Connection refused") is None


def test_assert_pom_matches_release_accepts_the_release_version():
    assert maven_mod.assert_pom_matches_release("1.19.0", "1.19.0") is True


def test_assert_pom_matches_release_fails_on_a_stale_pom():
    """liter-llm v1.19.0 deployed a checkout still carrying the previous version."""
    with pytest.raises(SystemExit) as exc_info:
        maven_mod.assert_pom_matches_release("1.18.4", "1.19.0")

    assert exc_info.value.code == 1


def test_assert_pom_matches_release_warns_when_the_version_is_undeterminable(capsys: pytest.CaptureFixture[str]):
    assert maven_mod.assert_pom_matches_release(None, "1.19.0") is False
    assert "::warning::" in capsys.readouterr().out


def test_assert_already_published_is_release_accepts_a_purl_naming_the_release():
    log = "[ERROR] component with package url 'pkg:maven/io.xberg/liter-llm@1.19.0' already exists"

    maven_mod.assert_already_published_is_release(log, "1.19.0", pom_verified=True)


def test_assert_already_published_is_release_fails_when_the_purl_names_another_version():
    """The 1.18.4 conflict that made liter-llm v1.19.0 report success having published nothing."""
    log = "[ERROR] component with package url 'pkg:maven/io.xberg/liter-llm@1.18.4' already exists"

    with pytest.raises(SystemExit) as exc_info:
        maven_mod.assert_already_published_is_release(log, "1.19.0", pom_verified=True)

    assert exc_info.value.code == 1


def test_assert_already_published_is_release_falls_back_to_a_verified_pom(capsys: pytest.CaptureFixture[str]):
    log = "[ERROR] component with package url already exists"

    maven_mod.assert_already_published_is_release(log, "1.19.0", pom_verified=True)

    assert "::warning::" in capsys.readouterr().out


def test_assert_already_published_is_release_fails_when_nothing_names_a_version():
    log = "[ERROR] component with package url already exists"

    with pytest.raises(SystemExit) as exc_info:
        maven_mod.assert_already_published_is_release(log, "1.19.0", pom_verified=False)

    assert exc_info.value.code == 1


def _prepare_main(monkeypatch: pytest.MonkeyPatch, pom: str, expected_version: str) -> None:
    """Point `main()` at `pom` with no credentials, so no settings.xml is written."""
    monkeypatch.setenv("INPUT_POM_FILE", pom)
    monkeypatch.setenv("INPUT_DRY_RUN", "false")
    monkeypatch.setenv("INPUT_EXPECTED_VERSION", expected_version)
    for name in ("MAVEN_USERNAME", "MAVEN_PASSWORD", "MAVEN_GPG_PASSPHRASE", "GITHUB_ACTIONS"):
        monkeypatch.delenv(name, raising=False)


def test_main_refuses_a_stale_pom_before_deploying_anything(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The stale POM must fail the job without invoking `mvn deploy`.

    Maven Central forbids republishing a version, so a mismatch noticed after the deploy has
    already shipped the wrong artifacts.
    """
    pom = _write_pom(tmp_path, "  <artifactId>liter-llm</artifactId>\n  <version>1.18.4</version>")
    calls: list[list[str]] = []
    monkeypatch.setattr(maven_mod, "run_mvn_with_streaming", lambda cmd, timeout: calls.append(cmd) or (0, ""))
    _prepare_main(monkeypatch, pom, "1.19.0")

    with pytest.raises(SystemExit) as exc_info:
        maven_mod.main()

    assert exc_info.value.code == 1
    assert calls == [], "nothing may be deployed once the POM is known to be stale"


def test_main_still_skips_an_already_published_release_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """An idempotent re-run of the version being released stays a success-with-skip."""
    pom = _write_pom(tmp_path, "  <artifactId>liter-llm</artifactId>\n  <version>1.19.0</version>")
    log = "[ERROR] component with package url 'pkg:maven/io.xberg/liter-llm@1.19.0' already exists"
    monkeypatch.setattr(maven_mod, "run_mvn_with_streaming", lambda cmd, timeout: (1, log))
    _prepare_main(monkeypatch, pom, "v1.19.0")

    maven_mod.main()

    assert "Version already published to Maven Central, skipping" in capsys.readouterr().out


def test_main_fails_when_the_already_exists_response_names_another_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A failed deploy must not resolve to success on a conflict belonging to a different version."""
    pom = _write_pom(tmp_path, "  <artifactId>liter-llm</artifactId>\n  <version>1.19.0</version>")
    log = "[ERROR] component with package url 'pkg:maven/io.xberg/liter-llm@1.18.4' already exists"
    monkeypatch.setattr(maven_mod, "run_mvn_with_streaming", lambda cmd, timeout: (1, log))
    _prepare_main(monkeypatch, pom, "1.19.0")

    with pytest.raises(SystemExit) as exc_info:
        maven_mod.main()

    assert exc_info.value.code == 1


def test_main_warns_when_expected_version_is_not_supplied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """The unsupplied expected-version is the blind spot, so it must be loud."""
    pom = _write_pom(tmp_path, "  <artifactId>liter-llm</artifactId>\n  <version>1.19.0</version>")
    monkeypatch.setattr(maven_mod, "run_mvn_with_streaming", lambda cmd, timeout: (0, ""))
    _prepare_main(monkeypatch, pom, "")

    maven_mod.main()

    assert "::warning::" in capsys.readouterr().out
