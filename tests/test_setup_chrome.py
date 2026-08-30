from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[1]


def test_non_arm_chrome_is_normalized_onto_path():
    action = yaml.safe_load((_ROOT / "setup-chrome" / "action.yml").read_text())
    steps = action["runs"]["steps"]
    upstream = next(step for step in steps if step.get("uses") == "browser-actions/setup-chrome@v2")
    normalize = next(step for step in steps if step.get("id") == "normalize")

    assert upstream["id"] == "upstream"
    script = normalize["run"]
    assert "steps.upstream.outputs.chrome-path" in script
    assert 'ln -sf "${chrome_path}" "${bin_dir}/google-chrome"' in script
    assert 'echo "${bin_dir}" >>"$GITHUB_PATH"' in script


def test_setup_chrome_exposes_the_normalized_binary_path():
    action = yaml.safe_load((_ROOT / "setup-chrome" / "action.yml").read_text())

    assert action["outputs"]["chrome-path"]["value"] == "${{ steps.normalize.outputs.chrome-path }}"
