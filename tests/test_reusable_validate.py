from pathlib import Path

_WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "reusable-validate.yml"


def _workflow_content() -> str:
    return _WORKFLOW.read_text()


def test_fixture_snippet_gate_is_backward_compatible():
    content = _workflow_content()

    assert "check-fixture-snippets:" in content
    assert "alef-version:" in content
    assert "default: false" in content
    assert 'default: "latest"' in content


def test_fixture_snippet_gate_installs_generates_checks_drift_and_validates():
    content = _workflow_content()
    expected_in_order = [
        "uses: xberg-io/actions/install-alef@v1",
        "run: alef e2e generate",
        "run: git diff --exit-code",
        "run: alef snippets check --strict --cache off",
    ]

    positions = [content.index(fragment) for fragment in expected_in_order]
    assert positions == sorted(positions)
    assert "version: ${{ inputs.alef-version }}" in content


def test_every_snippet_gated_step_is_accounted_for():
    """Pin the exact set of steps gated on `check-fixture-snippets`, by name.

    A bare count broke the moment the pnpm/wasm-pack setup steps were added, and a count
    cannot tell "someone added a gated step" from "someone dropped a gate". Naming them
    fails loudly in both directions: an ungated addition never appears here, and a step
    that silently loses its gate disappears from this set. ~keep
    """
    gated = []
    current_name = None
    for line in _workflow_content().splitlines():
        stripped = line.strip()
        if stripped.startswith("- name:"):
            current_name = stripped.removeprefix("- name:").strip()
        elif "inputs.check-fixture-snippets" in stripped and stripped.startswith("if:"):
            gated.append(current_name)

    assert gated == [
        "Install alef CLI",
        "Generate fixture snippets",
        "Check fixture snippet drift",
        "Set up Node.js and pnpm",
        "Set up wasm-pack",
        "Validate fixture snippets",
    ]
