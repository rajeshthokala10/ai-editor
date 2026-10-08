"""Slow tests: real Chromium/PPTX rendering and the daily pipeline with Claude mocked out."""

import json
import shutil
from pathlib import Path

import pytest

from aieditor import build as build_mod
from aieditor import daily

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "editions" / "2026-10-08" / "edition.json"


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    monkeypatch.setattr(build_mod, "EDITIONS", tmp_path)
    d = tmp_path / "2026-10-08"
    d.mkdir()
    shutil.copy(SAMPLE, d / "edition.json")
    return d


@pytest.mark.parametrize("theme", ["broadsheet", "markets", "trust"])
def test_build_produces_ten_pages_and_slides(workdir, theme):
    result = build_mod.build(workdir / "edition.json", theme)
    assert result["problems"] == []
    assert result["pdf"]["pages"] == 10 and result["pdf"]["links"] > 50
    assert result["pptx"]["slides"] == 10 and result["pptx"]["with_notes"] == 10
    assert all(f["overflow_px"] == 0 for f in result["pdf"]["fit"])


def test_daily_pipeline_with_mocked_claude(tmp_path, monkeypatch):
    """research -> compose -> repair -> build, with the API replaced by fakes."""
    from aieditor import research

    sample = json.loads(SAMPLE.read_text())
    broken = json.loads(json.dumps(sample))
    broken["pages"] = broken["pages"][:9]  # first draft is invalid -> must trigger one repair
    calls = {"repair": []}

    class FakeComposer:
        def __init__(self, window, dossier):
            assert "Haiku" in dossier

        def compose(self):
            return broken

        def repair(self, problems):
            calls["repair"].append(problems)
            return sample

    monkeypatch.setattr(research, "research", lambda window: "dossier about Haiku 5.5")
    monkeypatch.setattr(research, "Composer", FakeComposer)
    monkeypatch.setattr(build_mod, "EDITIONS", tmp_path)
    monkeypatch.setenv("EDITIONS_DIR", str(tmp_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    assert daily.main(["--no-email"]) == 0
    assert len(calls["repair"]) == 1 and "exactly 10 pages" in calls["repair"][0][0]
    out = next(tmp_path.glob("*/build.json"))
    report = json.loads(out.read_text())
    assert report["pdf"]["pages"] == 10 and report["problems"] == []


def test_missing_api_key_fails_fast_with_clear_message(monkeypatch, caplog):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert daily.main(["--no-email"]) == 2
    assert "ANTHROPIC_API_KEY is not set" in caplog.text


def test_unexpected_error_is_logged_not_raised(monkeypatch, caplog):
    from aieditor import research

    def boom(window):
        raise RuntimeError("upstream exploded")

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(research, "research", boom)
    assert daily.main(["--no-email"]) == 1
    assert "RUN FAILED: RuntimeError: upstream exploded" in caplog.text
