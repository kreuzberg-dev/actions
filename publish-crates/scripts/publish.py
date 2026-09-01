#!/usr/bin/env python3
"""Publish Rust crates to crates.io.

Usage (GitHub Actions via env vars):
    INPUT_CRATES="crate-a crate-b" INPUT_VERSION="1.2.3" python3 publish.py

After publishing each crate, waits for the new version to appear in the
crates.io sparse index before proceeding. This is required because cargo
resolves intra-workspace path-dependencies via the index when packaging
downstream crates — without this wait the next ``cargo publish`` immediately
fails with ``failed to select a version for the requirement ...``.

Before each publish, the crate's manifest is rewritten so that every
intra-workspace ``path`` dependency that lacks a ``version`` constraint gains
``version = "<INPUT_VERSION>"``. ``cargo publish`` rejects path-only deps with
``all dependencies must have a version requirement specified``, but some
manifests omit the version constraint deliberately to work around unrelated
build-graph bugs (e.g. xberg ``xberg-tesseract`` for the maturin sdist
"links collision" workaround). The original manifest is restored after each
publish attempt, success or failure.
"""

import contextlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import NamedTuple

sys.stdout.reconfigure(line_buffering=True)  # type: ignore[union-attr]
sys.stderr.reconfigure(line_buffering=True)  # type: ignore[union-attr]

ALREADY_PUBLISHED_PATTERN = re.compile(
    r"already uploaded|already exists",
    re.IGNORECASE,
)

DEPENDENCY_NOT_READY_PATTERN = re.compile(
    r"failed to select a version for",
    re.IGNORECASE,
)

NEW_CRATE_TRUSTED_PUBLISHING_PATTERN = re.compile(
    r"Trusted Publishing tokens do not support creating new crates",
    re.IGNORECASE,
)

INDEX_POLL_TIMEOUT_SECONDS = 600
INDEX_POLL_INTERVAL_SECONDS = 5

PUBLISH_RETRY_ATTEMPTS = 10
PUBLISH_RETRY_DELAY_SECONDS = 60


def is_already_published(output: str) -> bool:
    """Return True if cargo publish output indicates the crate was already published."""
    return bool(ALREADY_PUBLISHED_PATTERN.search(output))


def is_dependency_not_ready(output: str) -> bool:
    """Return True if cargo publish failed because an upstream crate has not propagated."""
    return bool(DEPENDENCY_NOT_READY_PATTERN.search(output))


def is_new_crate_trusted_publishing(output: str) -> bool:
    """Return True if the publish failed because a new crate can't be created via OIDC.

    crates.io Trusted Publishing tokens cannot create a crate that has never been
    published. This is a one-time bootstrap problem, not a transient one: retrying
    never helps, because the OIDC token will never gain create permission.
    """
    return bool(NEW_CRATE_TRUSTED_PUBLISHING_PATTERN.search(output))


def build_manifest_args(manifest_path: str) -> list[str]:
    """Return --manifest-path flag list, or empty list if manifest_path is blank."""
    if not manifest_path:
        return []
    return ["--manifest-path", manifest_path]


def parse_crate_list(crates: str) -> list[str]:
    """Split a whitespace-separated crate list into individual names."""
    return crates.split()


def _run(cmd: list[str]) -> tuple[int, str]:
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return result.returncode, result.stdout + result.stderr


def _sparse_index_url(crate: str) -> str:
    """Return the crates.io sparse-index URL for ``crate``.

    crates.io shards index entries by name length: ``1/``, ``2/``, ``3/<a>/``,
    then ``<ab>/<cd>/``.
    """
    name = crate.lower()
    if len(name) == 1:
        prefix = "1"
    elif len(name) == 2:
        prefix = "2"
    elif len(name) == 3:
        prefix = f"3/{name[0]}"
    else:
        prefix = f"{name[0:2]}/{name[2:4]}"
    return f"https://index.crates.io/{prefix}/{name}"


def wait_for_index(crate: str, version: str) -> bool:
    """Poll the crates.io sparse index for ``crate@version``; return whether it became visible.

    Cargo resolves dependency versions through the index; immediately after
    ``cargo publish`` returns, the new version is uploaded but not yet present
    in the sparse index. Downstream crates that depend on it cannot be
    packaged until propagation completes (typically 5-30 seconds).

    ~keep Reports the outcome instead of warning and returning, because the two callers need
    opposite severities and only the caller knows which applies. After a successful publish an
    absent version is index propagation lag and stays a warning. After an ``already published``
    skip it is the entire question being asked — the skip is legitimate only if the release
    version really is on the registry — so absence there is fatal.
    """
    url = _sparse_index_url(crate)
    deadline = time.monotonic() + INDEX_POLL_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        request = urllib.request.Request(  # noqa: S310 — fixed crates.io URL
            url,
            headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310 — fixed crates.io URL
                body = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                print(f"  index poll for {crate}: HTTP {exc.code}", file=sys.stderr)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            print(f"  index poll for {crate}: transient {exc}", file=sys.stderr)
        else:
            if f'"vers":"{version}"' in body:
                print(f"  index has {crate}@{version}")
                return True
        time.sleep(INDEX_POLL_INTERVAL_SECONDS)
    return False


def normalize_release_version(version: str) -> str:
    """Strip whitespace and a leading `v` so a tag (`v1.16.0`) compares to a manifest version."""
    return version.strip().removeprefix("v")


def assert_crates_match_release(crate_versions: list[tuple[str, str | None]], expected_version: str) -> None:
    """Fail before any publish when a crate's manifest carries a version other than the release's.

    ``cargo publish -p <crate>`` ships whatever ``[package] version`` that crate's own Cargo.toml
    declares. ``INPUT_VERSION`` otherwise only feeds path-dep injection and the index poll, and
    :func:`inject_path_dep_versions` deliberately rewrites dependency sections only — never
    ``[package]`` — so nothing else compares the manifest version to the release version.

    ~keep This guard is what makes the `is_already_published` skip below safe, and the two must
    not be collapsed. Skipping is legitimate ONLY when the crate's version IS the release version
    (an idempotent re-run); it is silent data loss when the checkout is stale.
    This exact shape shipped two broken releases on sibling registries: tree-sitter-language-pack
    v1.16.0 on npm and liter-llm v1.19.0 on npm and PyPI each published a stale artifact, matched
    the registry's already-published response, and reported success having shipped nothing for the
    tag. publish-crates had the same unguarded skip; the guard is here so it never gets a turn.

    ~keep Runs as a pre-flight over every crate rather than inline per crate because crates.io
    publishes are irreversible: a stale manifest caught halfway through the list has already
    shipped the crates ahead of it, and crates.io forbids republishing a version to correct them.
    """
    unreadable = sorted(crate for crate, crate_version in crate_versions if crate_version is None)
    if unreadable:
        print(
            f"Error: `cargo metadata` reported no version for {', '.join(unreadable)}, so the "
            f"crate(s) cannot be verified against the release version {expected_version}",
            file=sys.stderr,
        )
        sys.exit(1)

    mismatched = sorted(
        f"{crate} carries {crate_version}"
        for crate, crate_version in crate_versions
        if crate_version != expected_version
    )
    if mismatched:
        print(
            f"Error: crate manifest(s) carry a version other than the release version {expected_version}: "
            f"{'; '.join(mismatched)}",
            file=sys.stderr,
        )
        print(
            "The checked-out manifests are stale. Publishing them would ship the wrong version, or be "
            "silently swallowed as an 'already published' skip.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Verified {len(crate_versions)} crate(s) carry the release version {expected_version}")


def warn_if_index_lags(crate: str, version: str) -> None:
    """Warn, without failing, when a just-published version has not reached the index yet.

    The upload was confirmed by ``cargo publish`` itself, so an absent index entry here is
    propagation lag and must not fail the release.
    """
    if wait_for_index(crate, version):
        return
    print(
        f"  WARNING: {crate}@{version} not visible in crates.io index after "
        f"{INDEX_POLL_TIMEOUT_SECONDS}s; proceeding anyway",
        file=sys.stderr,
    )


def confirm_already_published_skip(crate: str, version: str, output: str) -> None:
    """Fail unless the crates.io index really carries ``crate@version`` behind an already-published skip.

    ~keep The skip path must corroborate the release version against the index, and its timeout
    must be fatal here even though the same poll is only a warning after a successful publish.
    ``already uploaded|already exists`` also matches failures that have nothing to do with this
    version, and a stale manifest makes crates.io report the conflict for the version the manifest
    carries rather than the one being released — which is how a release reports success having
    published nothing.
    """
    if wait_for_index(crate, version):
        return
    print(
        f"  Error: cargo reported {crate} as already published, but {crate}@{version} is not in "
        f"the crates.io index after {INDEX_POLL_TIMEOUT_SECONDS}s. The skip cannot be attributed "
        f"to this release, so nothing was published for {version}.",
        file=sys.stderr,
    )
    print(output, file=sys.stderr)
    sys.exit(1)


DEPENDENCY_SECTION_PATTERN = re.compile(
    r"""
    ^\[
    (?:
        (?P<plain>(?:dependencies|dev-dependencies|build-dependencies))
        (?:\.(?P<plain_dep>[\w\-]+))?
        |
        target\.(?P<target_cfg>(?:'[^']*'|"[^"]*"|[^.\]]+))
        \.(?P<target_kind>dependencies|dev-dependencies|build-dependencies)
        (?:\.(?P<target_dep>[\w\-]+))?
    )
    \]\s*$
    """,
    re.VERBOSE,
)

PATH_VALUE_PATTERN = re.compile(r"""path\s*=\s*("(?:[^"\\]|\\.)*"|'[^']*')""")
VERSION_KEY_PATTERN = re.compile(r"(?<![\w-])version\s*=")
WORKSPACE_TRUE_PATTERN = re.compile(r"(?<![\w-])workspace\s*=\s*true(?![\w-])")
INLINE_DEP_START_PATTERN = re.compile(r"""^\s*(?P<name>[A-Za-z0-9_\-]+)\s*=\s*\{""")


def _is_dependency_section(header: str) -> tuple[bool, str | None]:
    """Return (is_dep_section, dotted_dep_name).

    ``dotted_dep_name`` is non-None for ``[dependencies.foo]`` style sections.
    """
    match = DEPENDENCY_SECTION_PATTERN.match(header.strip())
    if not match:
        return False, None
    dep_name = match.group("plain_dep") or match.group("target_dep")
    return True, dep_name


def _strip_toml_comment(line: str) -> str:
    """Return ``line`` with any trailing TOML comment removed (respecting quoted strings)."""
    in_single = False
    in_double = False
    escape = False
    for index, char in enumerate(line):
        if escape:
            escape = False
            continue
        if in_double and char == "\\":
            escape = True
            continue
        if char == '"' and not in_single:
            in_double = not in_double
            continue
        if char == "'" and not in_double:
            in_single = not in_single
            continue
        if char == "#" and not in_single and not in_double:
            return line[:index]
    return line


def _count_braces(line: str) -> tuple[int, int]:
    """Return (opens, closes) of unquoted ``{`` and ``}`` in ``line``."""
    no_comment = _strip_toml_comment(line)
    in_single = False
    in_double = False
    escape = False
    opens = 0
    closes = 0
    for char in no_comment:
        if escape:
            escape = False
            continue
        if in_double and char == "\\":
            escape = True
            continue
        if char == '"' and not in_single:
            in_double = not in_double
            continue
        if char == "'" and not in_double:
            in_single = not in_single
            continue
        if in_single or in_double:
            continue
        if char == "{":
            opens += 1
        elif char == "}":
            closes += 1
    return opens, closes


def _inject_version_into_inline_table(block: str, version: str) -> str:
    """Insert ``version = "<version>"`` into the inline table spanning ``block``.

    ``block`` is the substring starting at ``{`` and ending at the matching ``}``
    (multi-line allowed). The insertion goes immediately after the ``path = "..."``
    value so the placement is stable and minimal.
    """
    path_match = PATH_VALUE_PATTERN.search(block)
    if not path_match:
        return block
    insertion = f', version = "{version}"'
    end = path_match.end()
    return block[:end] + insertion + block[end:]


def _inject_version_into_dotted_block(block_lines: list[str], version: str) -> list[str]:
    """Insert a ``version = "<version>"`` line under a ``[dependencies.foo]`` block.

    The insertion goes immediately after the section header line so the placement
    is stable and minimal. ``block_lines`` is mutated-but-returned for clarity.
    """
    if not block_lines:
        return block_lines
    return [block_lines[0], f'version = "{version}"\n', *block_lines[1:]]


def _entry_needs_version(text: str) -> bool:
    """Return True if the dependency entry ``text`` has a path but no version and is not workspace-inherited."""
    if not PATH_VALUE_PATTERN.search(text):
        return False
    if WORKSPACE_TRUE_PATTERN.search(text):
        return False
    return not VERSION_KEY_PATTERN.search(text)


def _collect_inline_entry(lines: list[str], index: int) -> tuple[list[str], int]:
    """Gather a dependency entry that may span lines, following brace depth.

    Returns the entry's lines and the index of its last line.
    """
    opens, closes = _count_braces(lines[index])
    entry_lines = [lines[index]]
    depth = opens - closes
    cursor = index
    while depth > 0 and cursor + 1 < len(lines):
        cursor += 1
        entry_lines.append(lines[cursor])
        opened, closed = _count_braces(lines[cursor])
        depth += opened - closed
    return entry_lines, cursor


def _find_inline_table_close(entry_text: str, brace_pos: int) -> int:
    """Index of the `}` closing the inline table opened at `brace_pos`, or -1.

    Brace counting has to ignore braces inside strings: a `cfg(...)` target or a path
    containing a brace would otherwise close the table early and corrupt the manifest. ~keep
    """
    depth = 0
    in_single = False
    in_double = False
    escape = False
    for position in range(brace_pos, len(entry_text)):
        char = entry_text[position]
        if escape:
            escape = False
            continue
        if in_double and char == "\\":
            escape = True
            continue
        if char == '"' and not in_single:
            in_double = not in_double
            continue
        if char == "'" and not in_double:
            in_single = not in_single
            continue
        if in_single or in_double:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return position
    return -1


def _rewrite_inline_entry(entry_lines: list[str], version: str) -> list[str]:
    """Inject a version into one inline-table dependency entry, or return it unchanged."""
    entry_text = "".join(entry_lines)
    brace_pos = entry_text.find("{", entry_text.find("="))
    close_pos = _find_inline_table_close(entry_text, brace_pos)
    if close_pos == -1:
        return entry_lines

    inline_block = entry_text[brace_pos : close_pos + 1]
    if not _entry_needs_version(inline_block):
        return entry_lines

    rewritten_block = _inject_version_into_inline_table(inline_block, version)
    return [entry_text[:brace_pos] + rewritten_block + entry_text[close_pos + 1 :]]


def inject_path_dep_versions(manifest: str, version: str) -> str:
    """Return ``manifest`` with ``version = "<version>"`` injected into every path-dep that needs it.

    Idempotent: deps that already declare ``version`` or ``workspace = true`` are
    left untouched. Inline tables, multi-line inline tables, and dotted-table
    (``[dependencies.foo]``) forms are all handled. Only ``[dependencies]``,
    ``[dev-dependencies]``, ``[build-dependencies]`` and their
    ``[target.'cfg(...)'.<kind>]`` variants are scanned.
    """
    lines = manifest.splitlines(keepends=True)
    output: list[str] = []
    index = 0
    in_dep_section = False
    dotted_dep_active = False
    dotted_block: list[str] = []

    def flush_dotted() -> None:
        nonlocal dotted_block, dotted_dep_active
        if not dotted_dep_active:
            return
        block_text = "".join(dotted_block)
        if _entry_needs_version(block_text):
            output.extend(_inject_version_into_dotted_block(dotted_block, version))
        else:
            output.extend(dotted_block)
        dotted_block = []
        dotted_dep_active = False

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if stripped.startswith("["):
            flush_dotted()
            is_dep, dotted_dep_name = _is_dependency_section(stripped)
            if is_dep and dotted_dep_name is not None:
                in_dep_section = False
                dotted_dep_active = True
                dotted_block = [line]
                index += 1
                continue
            in_dep_section = is_dep
            output.append(line)
            index += 1
            continue

        if dotted_dep_active:
            dotted_block.append(line)
            index += 1
            continue

        if not in_dep_section:
            output.append(line)
            index += 1
            continue

        match = INLINE_DEP_START_PATTERN.match(line)
        if not match:
            output.append(line)
            index += 1
            continue

        entry_lines, cursor = _collect_inline_entry(lines, index)
        output.extend(_rewrite_inline_entry(entry_lines, version))
        index = cursor + 1

    flush_dotted()
    return "".join(output)


class WorkspacePackage(NamedTuple):
    """A workspace member's manifest location and the ``[package] version`` it declares."""

    manifest_path: str
    version: str


def _discover_workspace_packages(workspace_manifest_args: list[str]) -> dict[str, WorkspacePackage]:
    """Return a ``{crate_name: WorkspacePackage}`` mapping from ``cargo metadata``.

    ``workspace_manifest_args`` is the existing ``--manifest-path`` list (may be empty).
    Falls back to an empty dict if cargo metadata cannot be invoked; callers then treat every
    crate version as unknown rather than assuming it matches the release.
    """
    cmd = ["cargo", "metadata", "--format-version", "1", "--no-deps", *workspace_manifest_args]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        print(
            "  WARNING: `cargo metadata` failed; cannot map crate names to manifest paths "
            f"for version injection. stderr:\n{result.stderr}",
            file=sys.stderr,
        )
        return {}
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        print(f"  WARNING: `cargo metadata` returned invalid JSON: {exc}", file=sys.stderr)
        return {}
    return {
        package["name"]: WorkspacePackage(package["manifest_path"], package["version"])
        for package in data.get("packages", [])
    }


@contextlib.contextmanager
def _temporarily_inject_versions(manifest_path: str | None, version: str) -> Iterator[bool]:
    """Inject path-dep versions into ``manifest_path`` for the duration of the context.

    Yields ``True`` if the manifest was actually rewritten (and therefore the git
    working tree is now dirty), ``False`` otherwise. Callers use this to decide
    whether ``cargo publish`` must be invoked with ``--allow-dirty``: the injected
    edit is an intentional, ephemeral publish-time transform, but ``cargo publish``
    aborts on any uncommitted manifest change unless ``--allow-dirty`` is passed.

    Restores the original manifest content (byte-for-byte) on exit, regardless of
    whether the wrapped block raises.
    """
    if not manifest_path:
        yield False
        return
    path = Path(manifest_path)
    if not path.is_file():
        yield False
        return
    original_bytes = path.read_bytes()
    try:
        original_text = original_bytes.decode("utf-8")
    except UnicodeDecodeError:
        yield False
        return
    rewritten = inject_path_dep_versions(original_text, version)
    injected = rewritten != original_text
    if injected:
        path.write_bytes(rewritten.encode("utf-8"))
    try:
        yield injected
    finally:
        path.write_bytes(original_bytes)


def publish_crate(crate: str, manifest_args: list[str]) -> tuple[int, str]:
    """Run ``cargo publish`` for ``crate``, retrying while an upstream crate is still propagating.

    Each retry re-invokes ``cargo publish``, which re-fetches the sparse index,
    so a dependency that finished propagating between attempts is picked up.

    Always passes ``--allow-dirty`` because path-dep version injection at publish time
    is an intentional, transient transform that may dirty the working tree.
    """
    exit_code, output = 0, ""
    for attempt in range(1, PUBLISH_RETRY_ATTEMPTS + 1):
        exit_code, output = _run(["cargo", "publish", "-p", crate, *manifest_args, "--allow-dirty"])
        if is_new_crate_trusted_publishing(output):
            return exit_code, output
        if exit_code == 0 or is_already_published(output) or not is_dependency_not_ready(output):
            return exit_code, output
        if attempt < PUBLISH_RETRY_ATTEMPTS:
            print(
                f"  {crate}: an upstream dependency is not yet resolvable on the index "
                f"(attempt {attempt}/{PUBLISH_RETRY_ATTEMPTS}); retrying in "
                f"{PUBLISH_RETRY_DELAY_SECONDS}s",
                file=sys.stderr,
            )
            time.sleep(PUBLISH_RETRY_DELAY_SECONDS)
    return exit_code, output


def main() -> None:
    crates_input = os.environ.get("INPUT_CRATES", "")
    version = normalize_release_version(os.environ.get("INPUT_VERSION", ""))
    dry_run = os.environ.get("INPUT_DRY_RUN", "false").lower() == "true"
    manifest_path = os.environ.get("INPUT_MANIFEST_PATH", "")

    if not crates_input:
        print("Error: INPUT_CRATES is required", file=sys.stderr)
        sys.exit(1)
    if not version:
        print("Error: INPUT_VERSION is required", file=sys.stderr)
        sys.exit(1)

    crate_list = parse_crate_list(crates_input)
    manifest_args = build_manifest_args(manifest_path)
    total = len(crate_list)
    workspace_packages = _discover_workspace_packages(manifest_args)

    # ~keep Runs before the dry-run branch below on purpose: a dry run exists to catch a stale
    # checkout before the real release, so it must apply the same version assertion.
    assert_crates_match_release(
        [(crate, package.version if (package := workspace_packages.get(crate)) else None) for crate in crate_list],
        version,
    )

    new_crates_needing_manual_publish: list[str] = []

    for index, crate in enumerate(crate_list, start=1):
        print(f"Publishing {crate} ({index}/{total})...")
        workspace_package = workspace_packages.get(crate)
        crate_manifest = workspace_package.manifest_path if workspace_package else None

        if dry_run:
            print(f"  [dry-run] cargo publish -p {crate} --dry-run")
            with _temporarily_inject_versions(crate_manifest, version) as injected:
                dirty_args = ["--allow-dirty"] if injected else []
                _run(["cargo", "publish", "-p", crate, *manifest_args, "--dry-run", *dirty_args])
            continue

        with _temporarily_inject_versions(crate_manifest, version):
            exit_code, output = publish_crate(crate, manifest_args)

        if exit_code == 0:
            print(f"  Published {crate}@{version}")
            warn_if_index_lags(crate, version)
        elif is_already_published(output):
            print(f"  {crate}@{version} already published, skipping")
            confirm_already_published_skip(crate, version, output)
        elif is_new_crate_trusted_publishing(output):
            new_crates_needing_manual_publish.append(crate)
            print(
                f"  {crate} does not exist on crates.io and cannot be created via "
                "Trusted Publishing (OIDC). A maintainer must publish it once, "
                "manually, with a classic API token (see end-of-run summary).",
                file=sys.stderr,
            )
        else:
            print(f"  Error publishing {crate}:", file=sys.stderr)
            print(output, file=sys.stderr)
            sys.exit(1)

    if new_crates_needing_manual_publish:
        names = " ".join(new_crates_needing_manual_publish)
        print(
            "\nERROR: the following crate(s) have never been published and cannot be "
            "created by a Trusted Publishing (OIDC) token:\n"
            f"  {names}\n\n"
            "crates.io requires the *first* publish of a new crate to be done once, "
            "manually, by a maintainer holding a classic API token. After that, every "
            "subsequent release publishes automatically via OIDC. To bootstrap each "
            "crate above, run locally with a token that has publish-new scope:\n"
            f"  CARGO_REGISTRY_TOKEN=<classic-token> cargo publish -p <crate> --allow-dirty\n\n"
            "Then re-run this release; the crate will be recognized and published via OIDC.",
            file=sys.stderr,
        )
        sys.exit(1)

    print("All crates published successfully")


if __name__ == "__main__":
    main()
