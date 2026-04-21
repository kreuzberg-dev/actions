import importlib.util
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "publish-maven" / "scripts" / "deploy.py"


def _import_script(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


maven_mod = _import_script("deploy_maven", _SCRIPT_PATH)


# ---------------------------------------------------------------------------
# build_mvn_args
# ---------------------------------------------------------------------------


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
    # Base args are still present
    assert "-B" in args
    assert "--no-transfer-progress" in args


# ---------------------------------------------------------------------------
# is_already_published
# ---------------------------------------------------------------------------


def test_is_already_published_true():
    log = (
        "[ERROR] Failed: component with package url maven:/com.example:mylib:1.2.3 already exists\n"
        "[ERROR] See https://issues.sonatype.org for details"
    )
    assert maven_mod.is_already_published(log) is True


def test_is_already_published_false():
    log = "[ERROR] Some other deployment error occurred\n[ERROR] Connection refused"
    assert maven_mod.is_already_published(log) is False
