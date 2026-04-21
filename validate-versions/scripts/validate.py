#!/usr/bin/env python3
"""Validate version consistency across package manifests.

Reads EXPECTED_VERSION and MANIFEST_PATHS from environment variables.
MANIFEST_PATHS is newline-separated type=path pairs, e.g.:
    cargo=Cargo.toml
    pyproject=packages/python/pyproject.toml
    package_json=typescript/package.json

Supported types: cargo, pyproject, package_json, gemspec, pom, mix, csproj, composer
"""

import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

MAVEN_NS = "{http://maven.apache.org/POM/4.0.0}"

CHECK = "\u2713"
CROSS = "\u2717"


def extract_cargo_version(path: Path) -> str | None:
    """Extract version from Cargo.toml by matching ^version = "..."."""
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r'^version\s*=\s*"([^"]+)"', line)
        if m:
            return m.group(1)
    return None


def extract_pyproject_version(path: Path) -> str | None:
    """Extract version from pyproject.toml by matching ^version = "..."."""
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r'^version\s*=\s*"([^"]+)"', line)
        if m:
            return m.group(1)
    return None


def extract_package_json_version(path: Path) -> str | None:
    """Extract version from package.json by parsing JSON."""
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return str(data["version"]) if "version" in data else None


def extract_gemspec_version(path: Path) -> str | None:
    """Extract version from a gemspec file.

    Matches spec.version = '...' or VERSION = '...' with single or double quotes.
    """
    if not path.exists():
        return None
    content = path.read_text(encoding="utf-8")
    for pattern in (
        r"""spec\.version\s*=\s*['"]([^'"]+)['"]""",
        r"""VERSION\s*=\s*['"]([^'"]+)['"]""",
    ):
        m = re.search(pattern, content)
        if m:
            return m.group(1)
    return None


def extract_pom_version(path: Path) -> str | None:
    """Extract version from pom.xml — first <version> child of root <project>.

    Handles both bare and Maven-namespaced roots.
    """
    if not path.exists():
        return None
    root = ET.parse(str(path)).getroot()  # noqa: S314
    # Try namespaced tag first, then bare
    for tag in (f"{MAVEN_NS}version", "version"):
        elem = root.find(tag)
        if elem is not None and elem.text:
            return elem.text.strip()
    return None


def extract_mix_version(path: Path) -> str | None:
    """Extract version from mix.exs by matching @version "..."."""
    if not path.exists():
        return None
    m = re.search(r'@version\s+"([^"]+)"', path.read_text(encoding="utf-8"))
    return m.group(1) if m else None


def extract_csproj_version(path: Path) -> str | None:
    """Extract version from a .csproj file by finding the <Version> element."""
    if not path.exists():
        return None
    root = ET.parse(str(path)).getroot()  # noqa: S314
    elem = root.find(".//Version")
    if elem is not None and elem.text:
        return elem.text.strip()
    return None


def extract_composer_version(path: Path) -> str | None:
    """Extract version from composer.json by parsing JSON."""
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return str(data["version"]) if "version" in data else None


def normalize_pep440_to_semver(version: str) -> str:
    """Normalize a PEP 440 pre-release suffix to semver notation.

    Examples:
        "1.0.0rc1"  -> "1.0.0-rc.1"
        "1.0.0a1"   -> "1.0.0-alpha.1"
        "1.0.0b2"   -> "1.0.0-beta.2"
        "1.0.0"     -> "1.0.0"
    """
    suffix_map = {"rc": "rc", "a": "alpha", "b": "beta"}
    m = re.match(r"^(\d+\.\d+\.\d+)(rc|a|b)(\d+)$", version)
    if not m:
        return version
    base, suffix, num = m.group(1), m.group(2), m.group(3)
    return f"{base}-{suffix_map[suffix]}.{num}"


def normalize_gem_version(version: str) -> str:
    """Normalize a RubyGems pre-release version to semver notation.

    Examples:
        "1.0.0.pre.1" -> "1.0.0-1"
        "1.0.0"       -> "1.0.0"
    """
    m = re.match(r"^(\d+\.\d+\.\d+)\.pre\.(\d+)$", version)
    if not m:
        return version
    return f"{m.group(1)}-{m.group(2)}"


def validate_all(
    expected: str,
    manifests: dict[str, str | None],
) -> tuple[bool, list[str]]:
    """Check all extracted versions against the expected version.

    Skips entries whose extracted version is None (file not found).
    Returns (all_match, list_of_mismatch_descriptions).
    """
    mismatches: list[str] = []
    for name, got in manifests.items():
        if got is None:
            continue
        if got != expected:
            mismatches.append(f"{name}: expected {expected}, got {got}")
    return (len(mismatches) == 0, mismatches)


_EXTRACTORS = {
    "cargo": extract_cargo_version,
    "pyproject": extract_pyproject_version,
    "package_json": extract_package_json_version,
    "gemspec": extract_gemspec_version,
    "pom": extract_pom_version,
    "mix": extract_mix_version,
    "csproj": extract_csproj_version,
    "composer": extract_composer_version,
}

_NORMALIZERS: dict[str, str] = {
    "pyproject": "pep440",
    "gemspec": "gem",
}


def _normalize(version: str, manifest_type: str) -> str:
    normalizer = _NORMALIZERS.get(manifest_type)
    if normalizer == "pep440":
        return normalize_pep440_to_semver(version)
    if normalizer == "gem":
        return normalize_gem_version(version)
    return version


def main() -> int:
    """Entry point for the GitHub Actions step."""
    expected = os.environ.get("EXPECTED_VERSION", "").strip()
    manifest_paths_raw = os.environ.get("MANIFEST_PATHS", "").strip()

    if not expected:
        print("Error: EXPECTED_VERSION is not set", file=sys.stderr)
        return 1

    manifests: dict[str, str | None] = {}
    for line in manifest_paths_raw.splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        manifest_type, _, raw_path = line.partition("=")
        manifest_type = manifest_type.strip()
        raw_path = raw_path.strip()

        if manifest_type not in _EXTRACTORS:
            print(f"Warning: unknown manifest type '{manifest_type}', skipping", file=sys.stderr)
            continue

        extractor = _EXTRACTORS[manifest_type]
        path = Path(raw_path)
        raw_version = extractor(path)
        normalized = _normalize(raw_version, manifest_type) if raw_version is not None else None
        manifests[f"{manifest_type}({raw_path})"] = normalized

    all_match, mismatches = validate_all(expected, manifests)

    for name, got in manifests.items():
        if got is None:
            print(f"  - {name}: (not found, skipped)")
        elif got == expected:
            print(f"  {CHECK} {name}: {got}")
        else:
            print(f"  {CROSS} {name}: {got} (expected {expected})")

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        mismatches_json = json.dumps(mismatches)
        with Path(github_output).open("a", encoding="utf-8") as f:
            f.write(f"valid={'true' if all_match else 'false'}\n")
            f.write(f"mismatches={mismatches_json}\n")

    if not all_match:
        print(f"\nVersion mismatch(es) detected ({len(mismatches)}):", file=sys.stderr)
        for desc in mismatches:
            print(f"  {CROSS} {desc}", file=sys.stderr)
        return 1

    print(f"\nAll versions match: {expected}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
