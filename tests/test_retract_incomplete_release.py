import importlib.util
from pathlib import Path

import pytest

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "retract-incomplete-release" / "scripts" / "retract_incomplete_release.py"
)


def _import_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


retract_incomplete_release = _import_script("retract_incomplete_release", _SCRIPT_PATH)


def test_parse_consumers_reads_named_pairs():
    parsed = retract_incomplete_release.parse_consumers("homebrew=success,scoop=skipped")

    assert parsed == [("homebrew", "success"), ("scoop", "skipped")]


def test_parse_consumers_accepts_newlines_and_whitespace():
    parsed = retract_incomplete_release.parse_consumers("\n  homebrew=success  \n\n  scoop=failure \n")

    assert parsed == [("homebrew", "success"), ("scoop", "failure")]


def test_parse_consumers_names_bare_results_by_position():
    parsed = retract_incomplete_release.parse_consumers("success,skipped")

    assert parsed == [("consumer-1", "success"), ("consumer-2", "skipped")]


def test_parse_consumers_lowercases_results():
    parsed = retract_incomplete_release.parse_consumers("homebrew=SUCCESS")

    assert parsed == [("homebrew", "success")]


def test_parse_consumers_returns_empty_for_blank_input():
    assert retract_incomplete_release.parse_consumers("") == []
    assert retract_incomplete_release.parse_consumers("  ,\n , ") == []


def test_blocking_consumers_names_only_the_published_ones():
    entries = [("homebrew", "success"), ("homebrew-bottles", "skipped"), ("scoop", "success")]

    assert retract_incomplete_release.blocking_consumers(entries) == ["homebrew", "scoop"]


def test_blocking_consumers_is_empty_when_nothing_published():
    entries = [("homebrew", "skipped"), ("scoop", "failure"), ("other", "cancelled")]

    assert retract_incomplete_release.blocking_consumers(entries) == []


def test_should_retract_when_no_consumer_published(monkeypatch, github_output, capsys):
    """No channel advertises the release, so the draft state is still private bookkeeping."""
    calls: list[str] = []
    monkeypatch.setattr(retract_incomplete_release, "retract", lambda tag: calls.append(tag) or True)
    monkeypatch.setenv("INPUT_TAG", "v1.5.1")
    monkeypatch.setenv("INPUT_CONSUMER_RESULTS", "homebrew=skipped,scoop=skipped")
    monkeypatch.delenv("INPUT_DRY_RUN", raising=False)

    assert retract_incomplete_release.main() == 0

    assert calls == ["v1.5.1"]
    assert "retracted=true" in github_output.read_text()
    assert "reverted it to a draft release" in capsys.readouterr().out


def test_should_not_retract_when_homebrew_already_published(monkeypatch, github_output, capsys):
    """The regression from crawlberg#41: the tap already resolves this tag's assets."""
    calls: list[str] = []
    monkeypatch.setattr(retract_incomplete_release, "retract", lambda tag: calls.append(tag) or True)
    monkeypatch.setenv("INPUT_TAG", "v1.5.0")
    monkeypatch.setenv("INPUT_CONSUMER_RESULTS", "homebrew=success,scoop=skipped")
    monkeypatch.delenv("INPUT_DRY_RUN", raising=False)

    assert retract_incomplete_release.main() == 0

    assert calls == []
    output = github_output.read_text()
    assert "retracted=blocked" in output
    assert "blocking-consumers=homebrew" in output
    assert "Incomplete release left published" in capsys.readouterr().out


def test_should_retract_when_no_consumers_are_configured(monkeypatch, github_output):
    """A repo with no tap or bucket keeps the original unconditional behavior."""
    calls: list[str] = []
    monkeypatch.setattr(retract_incomplete_release, "retract", lambda tag: calls.append(tag) or True)
    monkeypatch.setenv("INPUT_TAG", "v2.0.0")
    monkeypatch.setenv("INPUT_CONSUMER_RESULTS", "")
    monkeypatch.delenv("INPUT_DRY_RUN", raising=False)

    assert retract_incomplete_release.main() == 0

    assert calls == ["v2.0.0"]
    assert "retracted=true" in github_output.read_text()


def test_should_report_error_when_the_edit_fails(monkeypatch, github_output, capsys):
    monkeypatch.setattr(retract_incomplete_release, "retract", lambda tag: False)
    monkeypatch.setenv("INPUT_TAG", "v1.5.1")
    monkeypatch.setenv("INPUT_CONSUMER_RESULTS", "homebrew=skipped")
    monkeypatch.delenv("INPUT_DRY_RUN", raising=False)

    assert retract_incomplete_release.main() == 0

    assert "retracted=error" in github_output.read_text()
    assert "could not revert" in capsys.readouterr().out


def test_should_not_touch_the_release_on_dry_run(monkeypatch, github_output):
    calls: list[str] = []
    monkeypatch.setattr(retract_incomplete_release, "retract", lambda tag: calls.append(tag) or True)
    monkeypatch.setenv("INPUT_TAG", "v1.5.1")
    monkeypatch.setenv("INPUT_CONSUMER_RESULTS", "homebrew=skipped")
    monkeypatch.setenv("INPUT_DRY_RUN", "true")

    assert retract_incomplete_release.main() == 0

    assert calls == []
    assert "retracted=dry-run" in github_output.read_text()


def test_should_report_error_when_no_tag_is_given(monkeypatch, github_output):
    monkeypatch.setattr(retract_incomplete_release, "retract", lambda tag: pytest.fail("must not edit any release"))
    monkeypatch.setenv("INPUT_TAG", "")
    monkeypatch.setenv("INPUT_CONSUMER_RESULTS", "")
    monkeypatch.delenv("INPUT_DRY_RUN", raising=False)

    assert retract_incomplete_release.main() == 0

    assert "retracted=error" in github_output.read_text()
