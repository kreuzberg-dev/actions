import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "verify-platform-packages" / "scripts" / "verify.py"

TARGETS = [
    "x86_64-unknown-linux-gnu",
    "aarch64-unknown-linux-gnu",
    "x86_64-apple-darwin",
    "aarch64-apple-darwin",
    "x86_64-pc-windows-msvc",
    "aarch64-pc-windows-msvc",
    "x86_64-unknown-linux-musl",
    "aarch64-unknown-linux-musl",
]

PLATFORM_NAMES = [f"@xberg-io/demo-node-{t}" for t in TARGETS]

PARENT_VERSION = "3.11.0"


def _import_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


verify_mod = _import_script("verify_platform_packages", _SCRIPT_PATH)


def _write_parent(
    tmp_path: Path,
    *,
    declared: list[str],
    targets: list[str] | None = TARGETS,
    version: str = PARENT_VERSION,
) -> Path:
    manifest: dict = {
        "name": "@xberg-io/demo-node",
        "version": version,
        "optionalDependencies": dict.fromkeys(declared, version),
    }
    if targets is not None:
        manifest["napi"] = {"binaryName": "demo", "targets": targets}
    path = tmp_path / "package.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def _write_platform_dirs(
    tmp_path: Path,
    names: list[str],
    *,
    with_binary: set[str] | None = None,
    version: str = PARENT_VERSION,
) -> Path:
    """Materialise npm/<target>/ dirs exactly as `napi create-npm-dirs` would."""
    root = tmp_path / "npm"
    root.mkdir(exist_ok=True)
    binaries = set(names) if with_binary is None else with_binary
    for index, name in enumerate(names):
        directory = root / f"target-{index}"
        directory.mkdir()
        (directory / "package.json").write_text(
            json.dumps({"name": name, "version": version}),
            encoding="utf-8",
        )
        if name in binaries:
            (directory / "demo.node").write_bytes(b"\x00" * 64)
    return root


def _wait_module(resolvable: set[str] | None = None):
    """Stand-in for the wait-for-package module; resolves only listed packages."""
    known = resolvable

    def wait_for_package(registry, package, version, max_attempts, maven_group_id=""):
        return True if known is None else package in known

    return SimpleNamespace(wait_for_package=wait_for_package)


@pytest.fixture
def env_base() -> dict[str, str]:
    return {"INPUT_MODE": "binaries", "INPUT_MAX_ATTEMPTS": "1"}


def test_should_pass_when_every_declared_package_has_a_binary(tmp_path, env_base, capsys):
    manifest = _write_parent(tmp_path, declared=PLATFORM_NAMES)
    _write_platform_dirs(tmp_path, PLATFORM_NAMES)

    env = {**env_base, "INPUT_MANIFEST_PATH": str(manifest)}
    assert verify_mod.run(env, _wait_module()) == 0

    out = capsys.readouterr().out
    assert "Platform directories examined: 8" in out


def test_should_fail_when_a_declared_package_has_no_built_binary(tmp_path, env_base, capsys):
    manifest = _write_parent(tmp_path, declared=PLATFORM_NAMES)
    _write_platform_dirs(tmp_path, PLATFORM_NAMES, with_binary=set(PLATFORM_NAMES[:6]))

    env = {**env_base, "INPUT_MANIFEST_PATH": str(manifest)}
    assert verify_mod.run(env, _wait_module()) == 1

    out = capsys.readouterr().out
    assert "no non-empty *.node" in out
    assert out.count("no non-empty *.node") >= 2


def test_should_fail_when_a_binary_is_zero_bytes(tmp_path, env_base):
    manifest = _write_parent(tmp_path, declared=PLATFORM_NAMES)
    root = _write_platform_dirs(tmp_path, PLATFORM_NAMES)
    (root / "target-0" / "demo.node").write_bytes(b"")

    env = {**env_base, "INPUT_MANIFEST_PATH": str(manifest)}
    assert verify_mod.run(env, _wait_module()) == 1


def test_should_fail_when_the_platform_glob_matches_nothing(tmp_path, env_base, capsys):
    manifest = _write_parent(tmp_path, declared=PLATFORM_NAMES)
    (tmp_path / "npm").mkdir()

    env = {**env_base, "INPUT_MANIFEST_PATH": str(manifest)}
    assert verify_mod.run(env, _wait_module()) == 1

    out = capsys.readouterr().out
    assert "no platform packages found" in out
    assert "Examined (platform directories): 0" in out


def test_should_fail_when_the_platform_directory_is_absent(tmp_path, env_base, capsys):
    manifest = _write_parent(tmp_path, declared=PLATFORM_NAMES)

    env = {**env_base, "INPUT_MANIFEST_PATH": str(manifest)}
    assert verify_mod.run(env, _wait_module()) == 1
    assert "platform directory not found" in capsys.readouterr().out


def test_should_fail_when_declared_count_is_below_napi_target_count(tmp_path, env_base, capsys):
    manifest = _write_parent(tmp_path, declared=PLATFORM_NAMES[:6])
    _write_platform_dirs(tmp_path, PLATFORM_NAMES[:6])

    env = {**env_base, "INPUT_MANIFEST_PATH": str(manifest)}
    assert verify_mod.run(env, _wait_module()) == 1

    out = capsys.readouterr().out
    assert "cardinality mismatch: 6 declared optionalDependencies vs 8 expected from napi.targets" in out


def test_should_fail_when_optional_dependencies_is_empty(tmp_path, env_base, capsys):
    manifest = _write_parent(tmp_path, declared=[])

    env = {**env_base, "INPUT_MANIFEST_PATH": str(manifest)}
    assert verify_mod.run(env, _wait_module()) == 1

    out = capsys.readouterr().out
    assert "optionalDependencies is empty or absent" in out
    assert "Declared: 0" in out


def test_should_fail_when_expected_count_cannot_be_established(tmp_path, env_base, capsys):
    manifest = _write_parent(tmp_path, declared=PLATFORM_NAMES, targets=None)
    _write_platform_dirs(tmp_path, PLATFORM_NAMES)

    env = {**env_base, "INPUT_MANIFEST_PATH": str(manifest)}
    with pytest.raises(SystemExit):
        verify_mod.run(env, _wait_module())


def test_should_accept_explicit_expected_count_without_napi_targets(tmp_path, env_base):
    manifest = _write_parent(tmp_path, declared=PLATFORM_NAMES, targets=None)
    _write_platform_dirs(tmp_path, PLATFORM_NAMES)

    env = {**env_base, "INPUT_MANIFEST_PATH": str(manifest), "INPUT_EXPECTED_COUNT": "8"}
    assert verify_mod.run(env, _wait_module()) == 0


def test_should_fail_when_a_directory_is_not_declared(tmp_path, env_base, capsys):
    manifest = _write_parent(tmp_path, declared=PLATFORM_NAMES)
    _write_platform_dirs(tmp_path, [*PLATFORM_NAMES, "@xberg-io/demo-node-rogue"])

    env = {**env_base, "INPUT_MANIFEST_PATH": str(manifest)}
    assert verify_mod.run(env, _wait_module()) == 1
    assert "is not declared in optionalDependencies" in capsys.readouterr().out


def test_should_fail_when_a_declared_package_has_no_directory(tmp_path, env_base, capsys):
    manifest = _write_parent(tmp_path, declared=PLATFORM_NAMES)
    _write_platform_dirs(tmp_path, PLATFORM_NAMES[:7])

    env = {**env_base, "INPUT_MANIFEST_PATH": str(manifest)}
    assert verify_mod.run(env, _wait_module()) == 1

    out = capsys.readouterr().out
    assert "but no directory under" in out
    assert "examined 7 platform directories but 8 are declared" in out


def test_should_fail_when_a_platform_version_does_not_match_the_parent(tmp_path, env_base, capsys):
    manifest = _write_parent(tmp_path, declared=PLATFORM_NAMES)
    _write_platform_dirs(tmp_path, PLATFORM_NAMES, version="3.10.9")

    env = {**env_base, "INPUT_MANIFEST_PATH": str(manifest)}
    assert verify_mod.run(env, _wait_module()) == 1
    assert "does not match parent version" in capsys.readouterr().out


def test_should_pass_registry_mode_when_every_package_resolves(tmp_path, capsys):
    manifest = _write_parent(tmp_path, declared=PLATFORM_NAMES)

    env = {"INPUT_MANIFEST_PATH": str(manifest), "INPUT_MODE": "registry", "INPUT_MAX_ATTEMPTS": "1"}
    assert verify_mod.run(env, _wait_module(set(PLATFORM_NAMES))) == 0

    out = capsys.readouterr().out
    assert "Registry packages resolved: 8/8" in out


def test_should_fail_registry_mode_when_two_packages_never_resolve(tmp_path, capsys):
    manifest = _write_parent(tmp_path, declared=PLATFORM_NAMES)

    env = {"INPUT_MANIFEST_PATH": str(manifest), "INPUT_MODE": "registry", "INPUT_MAX_ATTEMPTS": "1"}
    assert verify_mod.run(env, _wait_module(set(PLATFORM_NAMES[:6]))) == 1

    out = capsys.readouterr().out
    assert "Registry packages resolved: 6/8" in out
    assert "resolved 6 packages but 8 are declared" in out


def test_should_query_every_declared_package_not_a_subset(tmp_path):
    manifest = _write_parent(tmp_path, declared=PLATFORM_NAMES)
    queried: list[str] = []

    def wait_for_package(registry, package, version, max_attempts, maven_group_id=""):
        queried.append(package)
        return True

    env = {"INPUT_MANIFEST_PATH": str(manifest), "INPUT_MODE": "registry", "INPUT_MAX_ATTEMPTS": "1"}
    assert verify_mod.run(env, SimpleNamespace(wait_for_package=wait_for_package)) == 0
    assert sorted(queried) == sorted(PLATFORM_NAMES)


def test_should_verify_binaries_and_registry_in_both_mode(tmp_path, capsys):
    manifest = _write_parent(tmp_path, declared=PLATFORM_NAMES)
    _write_platform_dirs(tmp_path, PLATFORM_NAMES)

    env = {"INPUT_MANIFEST_PATH": str(manifest), "INPUT_MODE": "both", "INPUT_MAX_ATTEMPTS": "1"}
    assert verify_mod.run(env, _wait_module(set(PLATFORM_NAMES))) == 0

    out = capsys.readouterr().out
    assert "Examined (platform directories): 8" in out
    assert "Resolved (registry): 8" in out


def test_should_reject_an_unknown_mode(tmp_path, capsys):
    manifest = _write_parent(tmp_path, declared=PLATFORM_NAMES)

    env = {"INPUT_MANIFEST_PATH": str(manifest), "INPUT_MODE": "sometimes"}
    assert verify_mod.run(env, _wait_module()) == 2
    assert "Invalid mode" in capsys.readouterr().out


def test_should_fail_when_the_manifest_is_missing(tmp_path):
    env = {"INPUT_MANIFEST_PATH": str(tmp_path / "nope.json"), "INPUT_MODE": "registry"}
    with pytest.raises(SystemExit):
        verify_mod.run(env, _wait_module())


def test_should_fail_when_the_manifest_is_not_json(tmp_path):
    manifest = tmp_path / "package.json"
    manifest.write_text("{not json", encoding="utf-8")

    env = {"INPUT_MANIFEST_PATH": str(manifest), "INPUT_MODE": "registry"}
    with pytest.raises(SystemExit):
        verify_mod.run(env, _wait_module())


def test_should_use_the_version_input_over_the_manifest_version(tmp_path):
    manifest = _write_parent(tmp_path, declared=PLATFORM_NAMES)
    versions: list[str] = []

    def wait_for_package(registry, package, version, max_attempts, maven_group_id=""):
        versions.append(version)
        return True

    env = {
        "INPUT_MANIFEST_PATH": str(manifest),
        "INPUT_MODE": "registry",
        "INPUT_VERSION": "4.0.0",
        "INPUT_MAX_ATTEMPTS": "1",
    }
    assert verify_mod.run(env, SimpleNamespace(wait_for_package=wait_for_package)) == 0
    assert set(versions) == {"4.0.0"}


def test_should_write_counts_to_github_output(tmp_path, github_output, env_base):
    manifest = _write_parent(tmp_path, declared=PLATFORM_NAMES)
    _write_platform_dirs(tmp_path, PLATFORM_NAMES)

    env = {**env_base, "INPUT_MANIFEST_PATH": str(manifest)}
    assert verify_mod.run(env, _wait_module()) == 0

    written = github_output.read_text(encoding="utf-8")
    assert "declared-count=8" in written
    assert "expected-count=8" in written
    assert "examined-count=8" in written


def test_should_reject_a_non_integer_max_attempts():
    with pytest.raises(SystemExit):
        verify_mod.parse_max_attempts("soon")


def test_should_reject_a_zero_max_attempts():
    with pytest.raises(SystemExit):
        verify_mod.parse_max_attempts("0")


def test_should_default_max_attempts_when_unset():
    assert verify_mod.parse_max_attempts("") == verify_mod.DEFAULT_MAX_ATTEMPTS


def test_should_load_the_real_wait_for_package_module():
    module = verify_mod.load_wait_module()
    assert callable(module.wait_for_package)


def test_should_fail_when_the_wait_script_is_absent(tmp_path):
    with pytest.raises(SystemExit):
        verify_mod.load_wait_module(tmp_path / "missing" / "wait.py")
