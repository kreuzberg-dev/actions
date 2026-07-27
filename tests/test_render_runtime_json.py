import importlib.util
import json
import subprocess
import sys
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "render-runtime-json" / "scripts" / "render.py"

spec = importlib.util.spec_from_file_location("render_runtime_json", str(_SCRIPT))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

_RID_GRAPH = json.dumps(
    {
        "runtimes": {
            "linux-x64": {"xberg": {"xberg.runtime.linux-x64": "{{VERSION}}"}},
            "osx-arm64": {"xberg": {"xberg.runtime.osx-arm64": "{{VERSION}}"}},
        },
    },
)


def _run(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_SCRIPT)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_render_template_replaces_all_tokens():
    result = mod.render_template("a {{VERSION}} b {{VERSION}}", "1.2.3")
    assert result == "a 1.2.3 b 1.2.3"


def test_compute_output_path_strips_template_suffix():
    result = mod.compute_output_path("pkg/runtime.json.template", "")
    assert result == "pkg/runtime.json"


def test_compute_output_path_honors_explicit_output():
    result = mod.compute_output_path("pkg/runtime.json.template", "other/out.json")
    assert result == "other/out.json"


def test_main_renders_default_output_path(tmp_path):
    template = tmp_path / "runtime.json.template"
    template.write_text(_RID_GRAPH)
    output = tmp_path / "runtime.json"

    result = _run({"INPUT_TEMPLATE_PATH": str(template), "INPUT_VERSION": "0.5.0"})

    assert result.returncode == 0
    assert output.is_file()
    rendered = output.read_text()
    assert "{{VERSION}}" not in rendered
    assert "0.5.0" in rendered
    assert json.loads(rendered)["runtimes"]["linux-x64"]["xberg"]["xberg.runtime.linux-x64"] == "0.5.0"


def test_main_honors_explicit_output_path(tmp_path):
    template = tmp_path / "runtime.json.template"
    template.write_text(_RID_GRAPH)
    output = tmp_path / "nested" / "custom.json"
    output.parent.mkdir()

    result = _run(
        {
            "INPUT_TEMPLATE_PATH": str(template),
            "INPUT_VERSION": "2.0.0",
            "INPUT_OUTPUT_PATH": str(output),
        },
    )

    assert result.returncode == 0
    assert not (tmp_path / "runtime.json").exists()
    assert output.is_file()
    assert "{{VERSION}}" not in output.read_text()


def test_main_writes_github_output(tmp_path):
    template = tmp_path / "runtime.json.template"
    template.write_text(_RID_GRAPH)
    output = tmp_path / "runtime.json"
    github_output = tmp_path / "github_output.txt"
    github_output.touch()

    result = _run(
        {
            "INPUT_TEMPLATE_PATH": str(template),
            "INPUT_VERSION": "1.0.0",
            "GITHUB_OUTPUT": str(github_output),
        },
    )

    assert result.returncode == 0
    assert github_output.read_text().strip() == f"rendered-path={output}"


def test_main_errors_when_template_missing(tmp_path):
    result = _run(
        {
            "INPUT_TEMPLATE_PATH": str(tmp_path / "missing.json.template"),
            "INPUT_VERSION": "1.0.0",
        },
    )

    assert result.returncode == 1
    assert "does not exist" in result.stderr


def test_main_errors_when_rendered_output_invalid_json(tmp_path):
    template = tmp_path / "runtime.json.template"
    template.write_text('{"version": {{VERSION}} not valid json')

    result = _run({"INPUT_TEMPLATE_PATH": str(template), "INPUT_VERSION": "1.0.0"})

    assert result.returncode == 1
    assert "not valid JSON" in result.stderr


def test_main_errors_when_template_path_has_no_suffix_and_no_output(tmp_path):
    template = tmp_path / "runtime.json"
    template.write_text(_RID_GRAPH)

    result = _run({"INPUT_TEMPLATE_PATH": str(template), "INPUT_VERSION": "1.0.0"})

    assert result.returncode == 1
    assert ".template" in result.stderr
