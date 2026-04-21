import importlib.util
import json
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "validate-versions" / "scripts" / "validate.py"

spec = importlib.util.spec_from_file_location("validate_versions", str(_SCRIPT))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


# ---------------------------------------------------------------------------
# extract_cargo_version
# ---------------------------------------------------------------------------


def test_extract_cargo_version(tmp_path):
    f = tmp_path / "Cargo.toml"
    f.write_text('[package]\nname = "foo"\nversion = "1.2.3"\n')
    assert mod.extract_cargo_version(f) == "1.2.3"


def test_extract_cargo_version_missing(tmp_path):
    assert mod.extract_cargo_version(tmp_path / "nonexistent.toml") is None


# ---------------------------------------------------------------------------
# extract_pyproject_version
# ---------------------------------------------------------------------------


def test_extract_pyproject_version(tmp_path):
    f = tmp_path / "pyproject.toml"
    f.write_text('[project]\nname = "bar"\nversion = "2.0.1"\n')
    assert mod.extract_pyproject_version(f) == "2.0.1"


# ---------------------------------------------------------------------------
# extract_package_json_version
# ---------------------------------------------------------------------------


def test_extract_package_json_version(tmp_path):
    f = tmp_path / "package.json"
    f.write_text(json.dumps({"name": "pkg", "version": "3.1.0"}))
    assert mod.extract_package_json_version(f) == "3.1.0"


def test_extract_package_json_missing(tmp_path):
    assert mod.extract_package_json_version(tmp_path / "package.json") is None


# ---------------------------------------------------------------------------
# extract_gemspec_version
# ---------------------------------------------------------------------------


def test_extract_gemspec_version_single_quotes(tmp_path):
    f = tmp_path / "mygem.gemspec"
    f.write_text("Gem::Specification.new do |spec|\n  spec.version = '1.2.3'\nend\n")
    assert mod.extract_gemspec_version(f) == "1.2.3"


def test_extract_gemspec_version_constant(tmp_path):
    f = tmp_path / "mygem.gemspec"
    f.write_text("VERSION = '1.2.3'\n")
    assert mod.extract_gemspec_version(f) == "1.2.3"


# ---------------------------------------------------------------------------
# extract_pom_version
# ---------------------------------------------------------------------------


def test_extract_pom_version(tmp_path):
    f = tmp_path / "pom.xml"
    f.write_text("<?xml version='1.0'?>\n<project>\n  <version>1.2.3</version>\n  <dependencies/>\n</project>\n")
    assert mod.extract_pom_version(f) == "1.2.3"


def test_extract_pom_version_with_namespace(tmp_path):
    f = tmp_path / "pom.xml"
    f.write_text(
        "<?xml version='1.0'?>\n"
        "<project xmlns='http://maven.apache.org/POM/4.0.0'>\n"
        "  <version>1.2.3</version>\n"
        "</project>\n"
    )
    assert mod.extract_pom_version(f) == "1.2.3"


# ---------------------------------------------------------------------------
# extract_mix_version
# ---------------------------------------------------------------------------


def test_extract_mix_version(tmp_path):
    f = tmp_path / "mix.exs"
    f.write_text('defmodule Foo.MixProject do\n  @version "1.2.3"\nend\n')
    assert mod.extract_mix_version(f) == "1.2.3"


# ---------------------------------------------------------------------------
# extract_csproj_version
# ---------------------------------------------------------------------------


def test_extract_csproj_version(tmp_path):
    f = tmp_path / "MyLib.csproj"
    f.write_text(
        "<Project Sdk='Microsoft.NET.Sdk'>\n"
        "  <PropertyGroup>\n"
        "    <Version>1.2.3</Version>\n"
        "  </PropertyGroup>\n"
        "</Project>\n"
    )
    assert mod.extract_csproj_version(f) == "1.2.3"


# ---------------------------------------------------------------------------
# extract_composer_version
# ---------------------------------------------------------------------------


def test_extract_composer_version(tmp_path):
    f = tmp_path / "composer.json"
    f.write_text(json.dumps({"name": "vendor/pkg", "version": "1.2.3"}))
    assert mod.extract_composer_version(f) == "1.2.3"


# ---------------------------------------------------------------------------
# normalize_pep440_to_semver
# ---------------------------------------------------------------------------


def test_normalize_pep440_rc():
    assert mod.normalize_pep440_to_semver("1.0.0rc1") == "1.0.0-rc.1"


def test_normalize_pep440_alpha():
    assert mod.normalize_pep440_to_semver("1.0.0a1") == "1.0.0-alpha.1"


def test_normalize_pep440_beta():
    assert mod.normalize_pep440_to_semver("1.0.0b2") == "1.0.0-beta.2"


def test_normalize_pep440_no_change():
    assert mod.normalize_pep440_to_semver("1.0.0") == "1.0.0"


# ---------------------------------------------------------------------------
# normalize_gem_version
# ---------------------------------------------------------------------------


def test_normalize_gem_pre():
    assert mod.normalize_gem_version("1.0.0.pre.1") == "1.0.0-1"


def test_normalize_gem_no_change():
    assert mod.normalize_gem_version("1.0.0") == "1.0.0"


# ---------------------------------------------------------------------------
# validate_all
# ---------------------------------------------------------------------------


def test_validate_all_pass():
    ok, mismatches = mod.validate_all("1.0.0", {"cargo": "1.0.0", "pyproject": "1.0.0"})
    assert ok is True
    assert mismatches == []


def test_validate_all_mismatch():
    ok, mismatches = mod.validate_all("1.0.0", {"cargo": "1.0.1"})
    assert ok is False
    assert mismatches == ["cargo: expected 1.0.0, got 1.0.1"]


def test_validate_all_skips_none():
    ok, mismatches = mod.validate_all("1.0.0", {"cargo": "1.0.0", "pyproject": None})
    assert ok is True
    assert mismatches == []


# ---------------------------------------------------------------------------
# main entry point
# ---------------------------------------------------------------------------


def test_main_success(tmp_path, monkeypatch):
    cargo = tmp_path / "Cargo.toml"
    cargo.write_text('[package]\nversion = "1.0.0"\n')

    output_file = tmp_path / "github_output.txt"
    output_file.touch()

    monkeypatch.setenv("EXPECTED_VERSION", "1.0.0")
    monkeypatch.setenv("MANIFEST_PATHS", f"cargo={cargo}")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))

    result = mod.main()
    assert result == 0

    output = output_file.read_text()
    assert "valid=true" in output


def test_main_failure(tmp_path, monkeypatch):
    cargo = tmp_path / "Cargo.toml"
    cargo.write_text('[package]\nversion = "1.0.1"\n')

    output_file = tmp_path / "github_output.txt"
    output_file.touch()

    monkeypatch.setenv("EXPECTED_VERSION", "1.0.0")
    monkeypatch.setenv("MANIFEST_PATHS", f"cargo={cargo}")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))

    result = mod.main()
    assert result == 1

    output = output_file.read_text()
    assert "valid=false" in output
    mismatches_line = next(line for line in output.splitlines() if line.startswith("mismatches="))
    mismatches = json.loads(mismatches_line[len("mismatches=") :])
    assert len(mismatches) == 1
    assert "1.0.1" in mismatches[0]
