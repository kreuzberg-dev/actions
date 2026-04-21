import importlib.util
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "build-rust-ffi" / "scripts" / "build.py"


def _import_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build_mod = _import_script("build", _SCRIPT_PATH)


# ---------------------------------------------------------------------------
# build_cargo_args
# ---------------------------------------------------------------------------


def test_build_cargo_args_default():
    args = build_mod.build_cargo_args(
        crate_name="mylib",
        manifest_path="",
        build_profile="release",
        features="",
        target="",
        verbose=True,
        additional_flags="",
    )
    assert args == ["build", "--package", "mylib", "--release", "-vv"]


def test_build_cargo_args_with_manifest():
    args = build_mod.build_cargo_args(
        crate_name="mylib",
        manifest_path="/path/to/Cargo.toml",
        build_profile="release",
        features="",
        target="",
        verbose=True,
        additional_flags="",
    )
    assert args[:3] == ["build", "--manifest-path", "/path/to/Cargo.toml"]
    assert "--package" not in args
    assert "--release" in args
    assert "-vv" in args


def test_build_cargo_args_debug_profile():
    args = build_mod.build_cargo_args(
        crate_name="mylib",
        manifest_path="",
        build_profile="dev",
        features="",
        target="",
        verbose=False,
        additional_flags="",
    )
    assert "--release" not in args
    assert "-vv" not in args


def test_build_cargo_args_with_features():
    args = build_mod.build_cargo_args(
        crate_name="mylib",
        manifest_path="",
        build_profile="release",
        features="serde,json",
        target="",
        verbose=False,
        additional_flags="",
    )
    assert "--features" in args
    assert args[args.index("--features") + 1] == "serde,json"


def test_build_cargo_args_with_target():
    args = build_mod.build_cargo_args(
        crate_name="mylib",
        manifest_path="",
        build_profile="release",
        features="",
        target="x86_64-unknown-linux-gnu",
        verbose=False,
        additional_flags="",
    )
    assert "--target" in args
    assert args[args.index("--target") + 1] == "x86_64-unknown-linux-gnu"


def test_build_cargo_args_with_additional_flags():
    args = build_mod.build_cargo_args(
        crate_name="mylib",
        manifest_path="",
        build_profile="release",
        features="",
        target="",
        verbose=False,
        additional_flags="--cfg feature=foobar",
    )
    assert "--cfg" in args
    assert "feature=foobar" in args


def test_build_cargo_args_no_verbose():
    args = build_mod.build_cargo_args(
        crate_name="mylib",
        manifest_path="",
        build_profile="release",
        features="",
        target="",
        verbose=False,
        additional_flags="",
    )
    assert "-vv" not in args


# ---------------------------------------------------------------------------
# validate_inputs
# ---------------------------------------------------------------------------


def test_validate_inputs_with_manifest(tmp_path):
    manifest = tmp_path / "Cargo.toml"
    manifest.write_text("[package]")
    # Should not raise
    build_mod.validate_inputs("mylib", str(manifest))


def test_validate_inputs_missing_manifest(tmp_path):
    missing = tmp_path / "nonexistent" / "Cargo.toml"
    with pytest.raises(SystemExit) as exc_info:
        build_mod.validate_inputs("mylib", str(missing))
    assert exc_info.value.code == 1


def test_validate_inputs_standard_crate(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    crate_dir = tmp_path / "crates" / "mylib"
    crate_dir.mkdir(parents=True)
    (crate_dir / "Cargo.toml").write_text("[package]")
    # No manifest_path, standard crates/{name}/Cargo.toml layout
    build_mod.validate_inputs("mylib", "")


def test_validate_inputs_missing_crate(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as exc_info:
        build_mod.validate_inputs("noexist", "")
    assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# find_library
# ---------------------------------------------------------------------------


def test_find_library_exact_match(tmp_path):
    (tmp_path / "libfoo.so").write_bytes(b"\x7fELF")
    result = build_mod.find_library(tmp_path, "foo")
    assert result == tmp_path / "libfoo.so"


def test_find_library_dylib(tmp_path):
    (tmp_path / "libfoo.dylib").write_bytes(b"\xcf\xfa\xed\xfe")
    result = build_mod.find_library(tmp_path, "foo")
    assert result == tmp_path / "libfoo.dylib"


def test_find_library_dll(tmp_path):
    (tmp_path / "foo.dll").write_bytes(b"MZ")
    result = build_mod.find_library(tmp_path, "foo")
    assert result == tmp_path / "foo.dll"


def test_find_library_fallback(tmp_path):
    # No canonical match; any .so should be found via fallback
    (tmp_path / "other_name.so").write_bytes(b"\x7fELF")
    result = build_mod.find_library(tmp_path, "foo")
    assert result is not None
    assert result.suffix == ".so"


def test_find_library_none(tmp_path):
    result = build_mod.find_library(tmp_path, "foo")
    assert result is None


def test_find_library_hyphens_to_underscores(tmp_path):
    (tmp_path / "libmy_crate.so").write_bytes(b"\x7fELF")
    result = build_mod.find_library(tmp_path, "my-crate")
    assert result == tmp_path / "libmy_crate.so"


# ---------------------------------------------------------------------------
# diagnose_build_failure
# ---------------------------------------------------------------------------


def test_diagnose_build_failure_link_errors(capsys):
    log = "compiling...\nerror: linking failed\nsome other line"
    build_mod.diagnose_build_failure(log)
    captured = capsys.readouterr()
    assert "Linking errors detected" in captured.out


def test_diagnose_build_failure_missing_deps(capsys):
    log = "compiling...\ncould not find crate `serde`\nsome other line"
    build_mod.diagnose_build_failure(log)
    captured = capsys.readouterr()
    assert "Missing dependencies detected" in captured.out


def test_diagnose_build_failure_openssl(capsys):
    log = "checking...\nerror: openssl not found\nsome other line"
    build_mod.diagnose_build_failure(log)
    captured = capsys.readouterr()
    assert "OpenSSL errors detected" in captured.out


# ---------------------------------------------------------------------------
# _full_target_dir
# ---------------------------------------------------------------------------


def test_full_target_dir_release():
    config = build_mod.BuildConfig(
        crate_name="mylib",
        features="",
        target="",
        build_profile="release",
        verbose=False,
        additional_flags="",
        manifest_path="",
        disable_sccache=False,
        cargo_target_dir="",
        openssl_dir="",
    )
    result = build_mod._full_target_dir(config)
    assert result == Path("target/release")


def test_full_target_dir_debug():
    config = build_mod.BuildConfig(
        crate_name="mylib",
        features="",
        target="",
        build_profile="dev",
        verbose=False,
        additional_flags="",
        manifest_path="",
        disable_sccache=False,
        cargo_target_dir="",
        openssl_dir="",
    )
    result = build_mod._full_target_dir(config)
    assert result == Path("target/debug")


def test_full_target_dir_with_target():
    config = build_mod.BuildConfig(
        crate_name="mylib",
        features="",
        target="aarch64-unknown-linux-gnu",
        build_profile="release",
        verbose=False,
        additional_flags="",
        manifest_path="",
        disable_sccache=False,
        cargo_target_dir="",
        openssl_dir="",
    )
    result = build_mod._full_target_dir(config)
    assert result == Path("target/aarch64-unknown-linux-gnu/release")


def test_full_target_dir_custom_dir():
    config = build_mod.BuildConfig(
        crate_name="mylib",
        features="",
        target="",
        build_profile="release",
        verbose=False,
        additional_flags="",
        manifest_path="",
        disable_sccache=False,
        cargo_target_dir="custom",
        openssl_dir="",
    )
    result = build_mod._full_target_dir(config)
    assert result == Path("custom/release")


# ---------------------------------------------------------------------------
# _build_env
# ---------------------------------------------------------------------------


def test_build_env_disables_sccache(monkeypatch):
    monkeypatch.setenv("RUSTC_WRAPPER", "sccache")
    monkeypatch.setenv("CARGO_BUILD_RUSTC_WRAPPER", "sccache")
    config = build_mod.BuildConfig(
        crate_name="mylib",
        features="",
        target="",
        build_profile="release",
        verbose=False,
        additional_flags="",
        manifest_path="",
        disable_sccache=True,
        cargo_target_dir="",
        openssl_dir="",
    )
    env = build_mod._build_env(config)
    assert env["RUSTC_WRAPPER"] == ""
    assert env["CARGO_BUILD_RUSTC_WRAPPER"] == ""
    assert env["SCCACHE_GHA_ENABLED"] == "false"


def test_build_env_keeps_sccache(monkeypatch):
    monkeypatch.setenv("RUSTC_WRAPPER", "sccache")
    config = build_mod.BuildConfig(
        crate_name="mylib",
        features="",
        target="",
        build_profile="release",
        verbose=False,
        additional_flags="",
        manifest_path="",
        disable_sccache=False,
        cargo_target_dir="",
        openssl_dir="",
    )
    env = build_mod._build_env(config)
    assert env.get("RUSTC_WRAPPER") == "sccache"


# ---------------------------------------------------------------------------
# _write_github_output
# ---------------------------------------------------------------------------


def test_write_github_output(tmp_path, monkeypatch):
    output_file = tmp_path / "github_output.txt"
    output_file.touch()
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))

    lib_path = tmp_path / "libmylib.so"
    lib_path.write_bytes(b"\x7fELF")
    target_dir = tmp_path / "target" / "release"

    build_mod._write_github_output(lib_path, target_dir)

    content = output_file.read_text()
    assert f"library-path={lib_path}" in content
    assert f"target-dir={target_dir}" in content


def test_write_github_output_no_lib(tmp_path, monkeypatch):
    output_file = tmp_path / "github_output.txt"
    output_file.touch()
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))

    target_dir = tmp_path / "target" / "release"
    build_mod._write_github_output(None, target_dir)

    content = output_file.read_text()
    assert "library-path=\n" in content
    assert f"target-dir={target_dir}" in content


# ---------------------------------------------------------------------------
# BuildConfig.from_env
# ---------------------------------------------------------------------------


def test_build_config_from_env(monkeypatch):
    monkeypatch.setenv("CRATE_NAME", "my-ffi")
    monkeypatch.setenv("FEATURES", "serde")
    monkeypatch.setenv("TARGET", "x86_64-unknown-linux-gnu")
    monkeypatch.setenv("BUILD_PROFILE", "release")
    monkeypatch.setenv("VERBOSE", "false")
    monkeypatch.setenv("ADDITIONAL_FLAGS", "--cfg test")
    monkeypatch.setenv("MANIFEST_PATH", "/some/Cargo.toml")
    monkeypatch.setenv("DISABLE_SCCACHE", "false")
    monkeypatch.setenv("CARGO_TARGET_DIR", "/tmp/cargo")
    monkeypatch.setenv("OPENSSL_DIR", "/usr/local/openssl")

    config = build_mod.BuildConfig.from_env()

    assert config.crate_name == "my-ffi"
    assert config.features == "serde"
    assert config.target == "x86_64-unknown-linux-gnu"
    assert config.build_profile == "release"
    assert config.verbose is False
    assert config.additional_flags == "--cfg test"
    assert config.manifest_path == "/some/Cargo.toml"
    assert config.disable_sccache is False
    assert config.cargo_target_dir == "/tmp/cargo"
    assert config.openssl_dir == "/usr/local/openssl"
