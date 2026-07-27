#!/usr/bin/env python3
"""Render a NuGet ``runtime.json`` from a ``runtime.json.template``.

Substitutes the literal token ``{{VERSION}}`` in the template with the release
version, validates that the result is placeholder-free valid JSON, and writes it
beside the template (or to an explicit output path).

Usage (GitHub Actions via env vars):
    INPUT_TEMPLATE_PATH=packages/csharp/Xberg/runtime.json.template \
    INPUT_VERSION=1.2.3 python3 render.py
"""

import json
import os
import sys
from pathlib import Path

VERSION_PLACEHOLDER = "{{VERSION}}"
TEMPLATE_SUFFIX = ".template"


def render_template(text: str, version: str) -> str:
    """Replace every ``{{VERSION}}`` token in the template text with the version."""
    return text.replace(VERSION_PLACEHOLDER, version)


def compute_output_path(template_path: str, output_path: str) -> str:
    """Return the render target.

    The explicit output path if given, otherwise the template path with its
    trailing ``.template`` suffix stripped.
    """
    if output_path:
        return output_path
    if not template_path.endswith(TEMPLATE_SUFFIX):
        raise ValueError(
            f"template path {template_path!r} does not end in {TEMPLATE_SUFFIX!r} and no output-path was given",
        )
    return template_path[: -len(TEMPLATE_SUFFIX)]


def main() -> None:
    template_path = os.environ.get("INPUT_TEMPLATE_PATH", "")
    if not template_path:
        print("Error: INPUT_TEMPLATE_PATH is required", file=sys.stderr)
        sys.exit(1)

    version = os.environ.get("INPUT_VERSION", "")
    if not version:
        print("Error: INPUT_VERSION is required", file=sys.stderr)
        sys.exit(1)

    template = Path(template_path)
    if not template.is_file():
        print(f"Error: template file does not exist: {template_path}", file=sys.stderr)
        sys.exit(1)

    output_path_input = os.environ.get("INPUT_OUTPUT_PATH", "")
    try:
        output_path = compute_output_path(template_path, output_path_input)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    rendered = render_template(template.read_text(encoding="utf-8"), version)

    if VERSION_PLACEHOLDER in rendered:
        print(
            f"Error: rendered output still contains {VERSION_PLACEHOLDER} after substitution",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        json.loads(rendered)
    except json.JSONDecodeError as exc:
        print(f"Error: rendered output is not valid JSON: {exc}", file=sys.stderr)
        sys.exit(1)

    output = Path(output_path)
    output.write_text(rendered, encoding="utf-8")
    print(f"Rendered {output_path} from {template_path} with version {version}")

    github_output = os.environ.get("GITHUB_OUTPUT", "")
    if github_output:
        with Path(github_output).open("a") as fh:
            fh.write(f"rendered-path={output_path}\n")


if __name__ == "__main__":
    main()
