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
    assert content.count("if: ${{ inputs.check-fixture-snippets }}") == len(expected_in_order)
    assert "version: ${{ inputs.alef-version }}" in content
