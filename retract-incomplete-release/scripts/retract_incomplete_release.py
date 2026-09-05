"""Return an incomplete release to draft, unless a channel already advertises it.

A publish run creates the release as a draft, promotes it out of draft early so
cargo-binstall and the bottle builders have resolvable assets, and only then
publishes the registry targets. When a target fails, the run wants the release
back in the draft state it would never have left.

That is safe right up until a downstream channel has been pointed at the release.
A Homebrew formula pins `root_url .../releases/download/<tag>` and a Scoop manifest
pins the same asset URLs; once either is pushed to its public tap or bucket, the
draft state stops being private bookkeeping and becomes a 404 for every `brew
upgrade` and `scoop update` in the world. Retracting there is strictly worse than
shipping an incomplete release: the incomplete release still installs.

So retraction is conditional. If no consumer published, retract as before. If one
did, report the incomplete release loudly and leave it published — it must be
rolled forward by the next release, never retracted.

This script never fails the step. The caller has already failed the job on the
release verdict; a retraction problem is reported, not stacked on top.

Inputs (env vars):
    INPUT_TAG: release tag (required)
    INPUT_CONSUMER_RESULTS: comma/newline-separated job results, optionally
        `name=result` pairs (e.g. "homebrew=success,scoop=skipped")
    INPUT_DRY_RUN: "true" to skip mutations (default false)
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

SUCCESS_RESULT = "success"


def env_str(key: str, default: str = "") -> str:
    value = os.environ.get(key, default) or default
    return value.strip()


def env_bool(key: str, default: bool = False) -> bool:
    raw = os.environ.get(key, "").strip().lower()
    if not raw:
        return default
    return raw in {"true", "1", "yes", "y", "on"}


def parse_consumers(raw: str) -> list[tuple[str, str]]:
    """Parse `consumer-results` into (name, result) pairs.

    Accepts commas and newlines as separators, and both bare results
    (`success`) and named pairs (`homebrew=success`). A bare result is named by
    its position so a report can still point at which entry blocked.
    """
    entries: list[tuple[str, str]] = []
    for chunk in raw.replace("\n", ",").split(","):
        item = chunk.strip()
        if not item:
            continue
        if "=" in item:
            name, _, result = item.partition("=")
            entries.append((name.strip(), result.strip().lower()))
        else:
            entries.append((f"consumer-{len(entries) + 1}", item.lower()))
    return entries


def blocking_consumers(entries: list[tuple[str, str]]) -> list[str]:
    """Names of the consumers that published, and therefore block retraction."""
    return [name for name, result in entries if result == SUCCESS_RESULT]


def write_output(name: str, value: str) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT", "")
    if not output_path:
        return
    with Path(output_path).open("a", encoding="utf-8") as handle:
        handle.write(f"{name}={value}\n")


def retract(tag: str) -> bool:
    result = subprocess.run(
        ["gh", "release", "edit", tag, "--draft=true"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.returncode != 0 and result.stderr.strip():
        print(result.stderr.strip(), file=sys.stderr)
    return result.returncode == 0


def main() -> int:
    tag = env_str("INPUT_TAG")
    if not tag:
        print("::warning::retract-incomplete-release: no tag given; nothing to do.")
        write_output("retracted", "error")
        write_output("blocking-consumers", "")
        return 0

    entries = parse_consumers(env_str("INPUT_CONSUMER_RESULTS"))
    blocking = blocking_consumers(entries)
    write_output("blocking-consumers", ",".join(blocking))

    if blocking:
        names = ", ".join(blocking)
        print(
            f"::error title=Incomplete release left published::{tag} did not reach every enabled "
            f"publish target, but {names} already published a channel that resolves its release "
            f"assets. Returning {tag} to a draft would 404 every install resolving through that "
            f"channel, so it stays published. Roll forward with a new patch release; do not "
            f"retract this one."
        )
        write_output("retracted", "blocked")
        return 0

    if env_bool("INPUT_DRY_RUN"):
        print(f"[dry-run] would return {tag} to a draft release.")
        write_output("retracted", "dry-run")
        return 0

    if retract(tag):
        print(f"::warning::{tag} did not reach every enabled publish target; reverted it to a draft release.")
        write_output("retracted", "true")
    else:
        print(f"::warning::could not revert {tag} to a draft; check the release page manually.")
        write_output("retracted", "error")
    return 0


if __name__ == "__main__":
    sys.exit(main())
