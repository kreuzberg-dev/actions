#!/usr/bin/env python3
"""Deploy a Maven project to Maven Central.

Usage (GitHub Actions via env vars):
    INPUT_POM_FILE=pom.xml INPUT_DRY_RUN=false python3 deploy.py
"""

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


def build_mvn_args(pom_file: str, maven_profile: str, extra_args: str) -> list[str]:
    """Build the Maven argument list from config values."""
    args: list[str] = [
        "-f",
        pom_file,
        "-P",
        maven_profile,
        "-B",
        "--no-transfer-progress",
    ]
    if extra_args.strip():
        args.extend(extra_args.split())
    return args


def is_already_published(log_content: str) -> bool:
    """Return True if the Maven log indicates the version already exists."""
    return bool(re.search(r"component with package url.*already exists", log_content, re.IGNORECASE))


def main() -> None:
    pom_file = os.environ.get("INPUT_POM_FILE", "")
    maven_profile = os.environ.get("INPUT_MAVEN_PROFILE", "publish")
    extra_args = os.environ.get("INPUT_EXTRA_ARGS", "")
    dry_run = os.environ.get("INPUT_DRY_RUN", "false").lower() == "true"

    if not pom_file:
        print("Error: INPUT_POM_FILE is required", file=sys.stderr)
        sys.exit(1)

    if not Path(pom_file).is_file():
        print(f"Error: POM file not found: {pom_file}", file=sys.stderr)
        sys.exit(1)

    mvn_args = build_mvn_args(pom_file, maven_profile, extra_args)

    if dry_run:
        print(f"[dry-run] mvn clean deploy {' '.join(mvn_args)}")
        subprocess.run(["mvn", "-f", pom_file, "clean", "verify", "-B", "--no-transfer-progress"], check=False)
        sys.exit(0)

    print("Deploying to Maven Central...")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            ["mvn", "clean", "deploy", *mvn_args],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        log_content = result.stdout or ""
        Path(tmp_path).write_text(log_content)
        print(log_content, end="")

        if result.returncode == 0:
            print("Maven deploy completed successfully")
        elif is_already_published(log_content):
            print("Version already published to Maven Central, skipping")
            github_actions = os.environ.get("GITHUB_ACTIONS", "")
            if github_actions:
                print("::notice::Version already exists on Maven Central")
        else:
            print("Maven deploy failed", file=sys.stderr)
            sys.exit(1)
    finally:
        Path(tmp_path).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
