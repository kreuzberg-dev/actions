"""Extract and validate release metadata from GitHub workflow events."""

import os
import re
import sys
from pathlib import Path

DEFAULT_AVAILABLE_TARGETS = "python,node,ruby,cli,crates,docker,homebrew,java,csharp,go,wasm,php,elixir,r,c_ffi"

TARGET_ALIASES: dict[str, str] = {
    "csharp": "csharp",
    "dotnet": "csharp",
    "cs": "csharp",
    "nuget": "csharp",
    "go": "go",
    "golang": "go",
    "wasm": "wasm",
    "webassembly": "wasm",
    "elixir": "elixir",
    "hex": "elixir",
    "c-ffi": "c_ffi",
    "c_ffi": "c_ffi",
    "cffi": "c_ffi",
    "r": "r",
    "rproject": "r",
}


def validate_tag(tag: str) -> str:
    if not tag:
        print("ERROR: tag is empty", file=sys.stderr)
        sys.exit(1)
    if not tag.startswith("v"):
        print(f"ERROR: tag must start with 'v', got: {tag!r}", file=sys.stderr)
        sys.exit(1)
    return tag[1:]


def determine_npm_tag(version: str) -> str:
    if re.search(r"-(?:rc|alpha|beta|pre)", version):
        return "next"
    return "latest"


def resolve_ref(ref_input: str, tag: str) -> tuple[str, str, str, str, bool]:
    def strip_prefix(s: str) -> str:
        if s.startswith("refs/heads/"):
            return s[len("refs/heads/") :]
        if s.startswith("refs/tags/"):
            return s[len("refs/tags/") :]
        return s

    if not ref_input or ref_input == tag:
        ref = f"refs/tags/{tag}"
        return ref, ref, "", tag, True

    if re.fullmatch(r"[0-9a-f]{40}", ref_input):
        checkout_ref = "refs/heads/main"
        return ref_input, checkout_ref, ref_input, "main", False

    if ref_input.startswith("refs/"):
        is_tag = ref_input.startswith("refs/tags/")
        matrix_ref = strip_prefix(ref_input)
        return ref_input, ref_input, "", matrix_ref, is_tag

    if ref_input.startswith("v") and len(ref_input) > 1 and ref_input[1].isdigit():
        ref = f"refs/tags/{ref_input}"
        return ref, ref, "", ref_input, True

    checkout_ref = f"refs/heads/{ref_input}"
    return checkout_ref, checkout_ref, "", ref_input, False


def route_event(event_name: str, env: dict[str, str]) -> dict[str, str]:
    if event_name == "workflow_dispatch":
        return {
            "tag": env.get("INPUT_TAG", ""),
            "dry_run": env.get("INPUT_DRY_RUN", "false"),
            "force_republish": env.get("INPUT_FORCE_REPUBLISH", "false"),
            "ref": env.get("INPUT_REF", ""),
            "targets": env.get("INPUT_TARGETS", ""),
        }

    if event_name == "release":
        tag = env.get("EVENT_RELEASE_TAG", "")
        return {
            "tag": tag,
            "dry_run": "false",
            "force_republish": "false",
            "ref": f"refs/tags/{tag}",
            "targets": "",
        }

    if event_name == "repository_dispatch":
        return {
            "tag": env.get("EVENT_DISPATCH_TAG", ""),
            "dry_run": env.get("EVENT_DISPATCH_DRY_RUN", "false"),
            "force_republish": env.get("EVENT_DISPATCH_FORCE_REPUBLISH", "false"),
            "ref": env.get("EVENT_DISPATCH_REF", ""),
            "targets": env.get("EVENT_DISPATCH_TARGETS", ""),
        }

    tag = env.get("GITHUB_REF_NAME", "")
    is_prerelease = bool(re.search(r"-(?:pre|rc)", tag))
    return {
        "tag": tag,
        "dry_run": "true" if is_prerelease else "false",
        "force_republish": "false",
        "ref": "",
        "targets": "",
    }


def parse_targets(targets_input: str, available: list[str]) -> dict[str, bool]:
    normalized = targets_input.strip().lower()

    if not normalized or normalized in ("all", "*"):
        return dict.fromkeys(available, True)

    if normalized == "none":
        return dict.fromkeys(available, False)

    result = dict.fromkeys(available, False)
    parts = [p.strip().lower() for p in normalized.split(",") if p.strip()]

    for part in parts:
        canonical = TARGET_ALIASES.get(part, part)
        if canonical not in result:
            print(f"ERROR: unknown target: {part!r}. Available: {available}", file=sys.stderr)
            sys.exit(1)
        result[canonical] = True

    if result.get("homebrew") and not result.get("cli"):
        result["cli"] = True

    return result


def main() -> None:
    env = dict(os.environ)
    event_name = env.get("GITHUB_EVENT_NAME", "")

    routed = route_event(event_name, env)
    tag = routed["tag"]
    dry_run = routed["dry_run"]
    force_republish = routed["force_republish"]
    ref_input = routed["ref"]
    targets_input = routed["targets"]

    version = validate_tag(tag)
    npm_tag = determine_npm_tag(version)
    ref, checkout_ref, target_sha, matrix_ref, is_tag = resolve_ref(ref_input, tag)

    available_raw = env.get("AVAILABLE_TARGETS", DEFAULT_AVAILABLE_TARGETS)
    available = [t.strip() for t in available_raw.split(",") if t.strip()]

    targets = parse_targets(targets_input, available)

    enabled = [t for t, v in targets.items() if v]
    release_targets = ",".join(enabled) if enabled else "none"
    release_any = "true" if enabled else "false"

    github_output = env.get("GITHUB_OUTPUT", "")
    outputs: dict[str, str] = {
        "tag": tag,
        "version": version,
        "npm_tag": npm_tag,
        "ref": ref,
        "checkout_ref": checkout_ref,
        "target_sha": target_sha,
        "matrix_ref": matrix_ref,
        "is_tag": str(is_tag).lower(),
        "dry_run": dry_run,
        "force_republish": force_republish,
        "release_targets": release_targets,
        "release_any": release_any,
    }
    for target in available:
        outputs[f"release_{target}"] = str(targets.get(target, False)).lower()

    if github_output:
        with Path(github_output).open("a") as fh:
            fh.writelines(f"{key}={value}\n" for key, value in outputs.items())

    print("=== Release Metadata ===")
    for key, value in outputs.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
