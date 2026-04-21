#!/usr/bin/env python3
"""Publish a Homebrew formula update with pre-built bottles to a tap repository."""

import hashlib
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from urllib.error import URLError


def validate_sha256(value: str) -> bool:
    """Return True if value is a valid lowercase 64-character hex SHA256 digest."""
    return bool(re.fullmatch(r"[a-f0-9]{64}", value))


def compute_sha256(path: Path) -> str:
    """Compute and return the SHA256 hex digest of a file.

    Raises:
        ValueError: If the file does not exist or the computed digest is invalid.
    """
    if not path.is_file():
        msg = f"File not found: {path}"
        raise ValueError(msg)

    sha256 = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            sha256.update(chunk)

    digest = sha256.hexdigest()
    if not validate_sha256(digest):
        msg = f"Invalid SHA256 computed for {path}: {digest!r}"
        raise ValueError(msg)
    return digest


def download_with_retry(url: str, output: Path, max_retries: int = 3, retry_delay: int = 5) -> bool:
    """Download a URL to output path, retrying up to max_retries times on failure.

    Returns:
        True on success, False if all attempts fail.
    """
    for attempt in range(1, max_retries + 1):
        print(f"Downloading {url} (attempt {attempt}/{max_retries})...")
        try:
            urllib.request.urlretrieve(url, output)  # noqa: S310
            return True
        except (URLError, OSError) as exc:
            print(f"  Attempt {attempt} failed: {exc}")
            if attempt < max_retries:
                print(f"  Retrying in {retry_delay}s...")
                time.sleep(retry_delay)

    print(f"Error: Failed to download after {max_retries} attempts: {url}", file=sys.stderr)
    return False


def parse_bottle_tag(filename: str, formula_name: str) -> str:
    """Extract the platform tag from a bottle filename.

    Example: "kreuzberg-4.4.5.arm64_sequoia.bottle.tar.gz" -> "arm64_sequoia"

    Mirrors bash logic: strip `.bottle.tar.gz`, then take the final dot-delimited segment.

    Raises:
        ValueError: If the filename does not match the expected pattern.
    """
    # Match the last dot-delimited component before .bottle.tar.gz
    pattern = re.compile(rf"^{re.escape(formula_name)}-.+?\.([^.]+)\.bottle\.tar\.gz$")
    match = pattern.match(filename)
    if not match:
        msg = f"Could not parse bottle tag from filename: {filename!r}"
        raise ValueError(msg)
    return match.group(1)


def build_bottle_block(
    github_repo: str,
    tag: str,
    bottle_hashes: dict[str, str],
    bottle_tags: list[str],
) -> str:
    """Build a Homebrew `bottle do ... end` block string.

    Tags are emitted in the order given by bottle_tags.
    """
    root_url = f"https://github.com/{github_repo}/releases/download/{tag}"
    lines = ["  bottle do", f'    root_url "{root_url}"']
    for bottle_tag in bottle_tags:
        sha256 = bottle_hashes[bottle_tag]
        lines.append(f'    sha256 cellar: :any_skip_relocation, {bottle_tag}: "{sha256}"')
    lines.append("  end")
    return "\n".join(lines)


def update_formula_url_and_sha(content: str, github_repo: str, tag: str, tarball_sha256: str) -> str:
    """Replace the source URL and its sha256 in the formula content.

    Handles both single-quoted and double-quoted sha256 values.
    """
    escaped = re.escape(github_repo)
    updated = re.sub(
        rf'url "https://github\.com/{escaped}/archive/[^"]+\.tar\.gz"',
        f'url "https://github.com/{github_repo}/archive/{tag}.tar.gz"',
        content,
    )
    return re.sub(
        r"""sha256 ['"][0-9a-f]*['"]""",
        f'sha256 "{tarball_sha256}"',
        updated,
    )


def remove_bottle_blocks(content: str) -> str:
    """Remove all `  bottle do ... end` blocks (including commented-out ones) from formula content."""
    without_normal = re.sub(r"^  bottle do$.*?^  end$\n?", "", content, flags=re.MULTILINE | re.DOTALL)
    return re.sub(r"^  # bottle do$.*?^  # end$\n?", "", without_normal, flags=re.MULTILINE | re.DOTALL)


def insert_bottle_block(formula: str, bottle_block: str) -> str:
    """Insert the bottle block before the first `  depends_on` line.

    Collapses consecutive blank lines produced by the insertion.
    If no `  depends_on` is found, the block is appended at the end.
    """
    lines = formula.split("\n")
    result: list[str] = []
    inserted = False

    for line in lines:
        if line.startswith("  depends_on") and not inserted:
            result.append(bottle_block)
            result.append("")
            inserted = True
        result.append(line)

    if not inserted:
        result.append(bottle_block)

    return _collapse_blank_lines(result)


def _collapse_blank_lines(lines: list[str]) -> str:
    """Join lines, removing consecutive blank lines."""
    collapsed: list[str] = []
    prev_blank = False
    for line in lines:
        is_blank = line.strip() == ""
        if is_blank and prev_blank:
            continue
        prev_blank = is_blank
        collapsed.append(line)
    return "\n".join(collapsed)


def _check_already_published(tap_repo: str, formula_name: str, tag: str) -> bool:
    """Return True if the formula in the tap already references the given tag."""
    formula_url = f"https://raw.githubusercontent.com/{tap_repo}/main/Formula/{formula_name}.rb"
    try:
        result = subprocess.run(
            ["curl", "-sf", formula_url],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        return f"archive/{tag}.tar.gz" in result.stdout
    except (subprocess.TimeoutExpired, OSError):
        return False


def _verify_tar_integrity(path: Path) -> bool:
    """Return True if the tar.gz file passes integrity check."""
    result = subprocess.run(
        ["tar", "-tzf", str(path)],
        capture_output=True,
        check=False,
        timeout=60,
    )
    return result.returncode == 0


def _upload_bottles_to_release(
    bottles_dir: Path,
    formula_name: str,
    github_repo: str,
    tag: str,
) -> None:
    """Upload bottle artifacts to the GitHub release."""
    bottle_files = sorted(bottles_dir.glob(f"{formula_name}-*.bottle.tar.gz"))
    if not bottle_files:
        return

    file_args = [str(p) for p in bottle_files]
    print(f"Uploading {len(file_args)} bottle(s) to release {tag}...")
    subprocess.run(
        ["gh", "release", "upload", tag, *file_args, "--repo", github_repo, "--clobber"],
        check=True,
        timeout=300,
    )
    print("Bottles uploaded successfully")


def _collect_bottles(
    bottles_dir: Path,
    formula_name: str,
) -> tuple[dict[str, str], list[str]]:
    """Verify and hash all local bottle artifacts. Returns (bottle_hashes, bottle_tags)."""
    bottle_hashes: dict[str, str] = {}
    bottle_tags: list[str] = []

    for bottle_path in sorted(bottles_dir.glob(f"{formula_name}-*.bottle.tar.gz")):
        filename = bottle_path.name
        try:
            bottle_tag = parse_bottle_tag(filename, formula_name)
        except ValueError as exc:
            print(f"Skipping {filename}: {exc}", file=sys.stderr)
            continue

        print(f"Processing bottle: {filename} ({bottle_tag})")

        if not _verify_tar_integrity(bottle_path):
            print(f"Error: Bottle is corrupted: {filename}", file=sys.stderr)
            sys.exit(1)

        sha256 = compute_sha256(bottle_path)
        bottle_hashes[bottle_tag] = sha256
        bottle_tags.append(bottle_tag)
        print(f"  {bottle_tag}: {sha256}")

    return bottle_hashes, bottle_tags


def _download_source_tarball(github_repo: str, tag: str, temp_dir: Path) -> str:
    """Download, verify, and return the SHA256 of the source tarball."""
    tarball_url = f"https://github.com/{github_repo}/archive/{tag}.tar.gz"
    tarball_temp = temp_dir / "source.tar.gz"

    print("Downloading source tarball...")
    if not download_with_retry(tarball_url, tarball_temp):
        print("Error: Failed to download source tarball", file=sys.stderr)
        sys.exit(1)

    if not _verify_tar_integrity(tarball_temp):
        print("Error: Source tarball is corrupted", file=sys.stderr)
        sys.exit(1)

    tarball_sha256 = compute_sha256(tarball_temp)
    print(f"Source tarball SHA256: {tarball_sha256}")
    return tarball_sha256


def _apply_formula_updates(
    formula_path: Path,
    github_repo: str,
    tag: str,
    tarball_sha256: str,
    bottle_hashes: dict[str, str],
    bottle_tags: list[str],
) -> None:
    """Read, update, and write the formula file."""
    content = formula_path.read_text()
    bottle_block = build_bottle_block(github_repo, tag, bottle_hashes, bottle_tags)
    updated = update_formula_url_and_sha(content, github_repo, tag, tarball_sha256)
    updated = remove_bottle_blocks(updated)
    updated = insert_bottle_block(updated, bottle_block)
    formula_path.write_text(updated)

    print()
    print("=== Updated formula (first 30 lines) ===")
    for line in updated.splitlines()[:30]:
        print(line)
    print("...")


def _write_step_summary(summary_path: str, content: str) -> None:
    """Append content to the GitHub step summary file."""
    with Path(summary_path).open("a") as fh:
        fh.write(content)


def _commit_and_push(tap_dir: Path, formula_name: str, version: str, tag: str, bot_name: str, bot_email: str) -> None:
    """Commit the updated formula and push to the tap repo."""
    subprocess.run(["git", "config", "user.name", bot_name], cwd=tap_dir, check=True, timeout=30)
    subprocess.run(["git", "config", "user.email", bot_email], cwd=tap_dir, check=True, timeout=30)

    diff_result = subprocess.run(
        ["git", "diff", "--quiet", f"Formula/{formula_name}.rb"],
        cwd=tap_dir,
        check=False,
        timeout=30,
    )
    if diff_result.returncode == 0:
        print("No changes to formula")
        return

    subprocess.run(["git", "add", f"Formula/{formula_name}.rb"], cwd=tap_dir, check=True, timeout=30)
    commit_message = (
        f"chore(homebrew): update {formula_name} to {version}\n\n"
        f"Auto-update from release {tag}\n\n"
        "Includes pre-built bottles for macOS"
    )
    subprocess.run(["git", "commit", "-m", commit_message], cwd=tap_dir, check=True, timeout=30)
    subprocess.run(["git", "push", "origin", "main"], cwd=tap_dir, check=True, timeout=60)
    print("Formula updated successfully")


def main() -> None:
    """Orchestrate the Homebrew formula publish workflow."""
    bottles_dir = Path(os.environ["INPUT_BOTTLES_DIR"])
    formula_name = os.environ["INPUT_FORMULA_NAME"]
    tap_repo = os.environ["INPUT_TAP_REPO"]
    tag = os.environ["INPUT_TAG"]
    version = os.environ["INPUT_VERSION"]
    github_repo = os.environ["INPUT_GITHUB_REPO"]
    bot_name = os.environ.get("INPUT_BOT_NAME", "kreuzberg-bot")
    bot_email = os.environ.get("INPUT_BOT_EMAIL", "bot@kreuzberg.dev")
    dry_run = os.environ.get("INPUT_DRY_RUN", "false").lower() == "true"

    if not bottles_dir.is_dir():
        print(f"Error: Bottles directory not found: {bottles_dir}", file=sys.stderr)
        sys.exit(1)

    print("=== Updating Homebrew formula ===")
    print(f"Formula: {formula_name}")
    print(f"Tag: {tag}")
    print(f"Version: {version}")
    print(f"Tap: {tap_repo}")

    if _check_already_published(tap_repo, formula_name, tag):
        print(f"Formula already references tag {tag}, skipping update")
        return

    with tempfile.TemporaryDirectory() as temp_str:
        temp_dir = Path(temp_str)

        bottle_hashes, bottle_tags = _collect_bottles(bottles_dir, formula_name)
        if not bottle_hashes:
            print(
                f"Error: No bottle artifacts found matching {formula_name}-*.bottle.tar.gz in {bottles_dir}",
                file=sys.stderr,
            )
            sys.exit(1)
        print(f"Validated {len(bottle_hashes)} bottles")

        if not dry_run:
            _upload_bottles_to_release(bottles_dir, formula_name, github_repo, tag)

        tarball_sha256 = _download_source_tarball(github_repo, tag, temp_dir)

        tap_dir = temp_dir / "tap"
        print("Cloning tap repository...")
        subprocess.run(
            ["git", "clone", f"https://github.com/{tap_repo}.git", str(tap_dir)],
            check=True,
            timeout=120,
        )

        formula_path = tap_dir / "Formula" / f"{formula_name}.rb"
        if not formula_path.is_file():
            print(f"Error: Formula not found at Formula/{formula_name}.rb", file=sys.stderr)
            sys.exit(1)

        _apply_formula_updates(formula_path, github_repo, tag, tarball_sha256, bottle_hashes, bottle_tags)

        if dry_run:
            print("[dry-run] Formula updated locally but not pushed")
            summary = os.environ.get("GITHUB_STEP_SUMMARY")
            if summary:
                _write_step_summary(
                    summary,
                    f"### Homebrew (dry-run)\nFormula `{formula_name}` would be updated to version {version}\n",
                )
            return

        _commit_and_push(tap_dir, formula_name, version, tag, bot_name, bot_email)

        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            summary_content = (
                f"### Homebrew Published\n"
                f"- **Formula**: {formula_name}\n"
                f"- **Version**: {version}\n"
                f"- **Bottles**: {len(bottle_hashes)}\n"
            )
            _write_step_summary(summary, summary_content)


if __name__ == "__main__":
    main()
