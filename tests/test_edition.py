"""Fast tests: schema, theme selection, layout grouping, email assembly, scheduler wiring."""

import copy
import json
from pathlib import Path

import pytest

from aieditor import schema
from aieditor.render_pdf import layout_pages, render_html
from aieditor.themes import THEMES, choose_theme, score_themes

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "editions" / "2026-10-08" / "edition.json"


@pytest.fixture
def edition():
    return json.loads(SAMPLE.read_text(encoding="utf-8"))


def test_sample_edition_is_valid(edition):
    assert schema.validate(edition) == []
    assert len(edition["pages"]) == 10
    assert [p["section"] for p in edition["pages"]] == schema.PAGE_SECTIONS


def test_unknown_citation_is_rejected(edition):
    bad = copy.deepcopy(edition)
    bad["pages"][1]["blocks"][1]["what"] += " [999]"
    assert any("999" in p for p in schema.validate(bad))


def test_wrong_page_count_is_rejected(edition):
    bad = copy.deepcopy(edition)
    bad["pages"].pop()
    assert any("exactly 10 pages" in p for p in schema.validate(bad))


def test_relative_source_url_is_rejected(edition):
    bad = copy.deepcopy(edition)
    bad["sources"][0]["url"] = "/relative"
    assert any("absolute URL" in p for p in schema.validate(bad))


def test_editorial_word_budget(edition):
    # brief asks for roughly 1,800-2,500 words of copy; tables push the total higher
    assert 1500 <= schema.word_count(edition) <= 3600


def test_theme_follows_content(edition):
    money = copy.deepcopy(edition)
    for p in money["pages"]:
        p["headline"] = "Funding round, acquisition and billion-dollar investment deal valuation"
    assert choose_theme(money).key == "markets"


def test_theme_rotates_away_from_previous(edition):
    first = choose_theme(edition)
    second = choose_theme(edition, previous=first.key)
    assert second.key != first.key


def test_theme_override(edition):
    assert choose_theme(edition, override="trust").key == "trust"
    with pytest.raises(KeyError):
        choose_theme(edition, override="nope")


def test_every_theme_has_scores(edition):
    assert set(score_themes(edition)) == set(THEMES)


def test_front_page_lead_layouts(edition):
    split = layout_pages(edition, THEMES["modelday"])[0]["groups"]
    banner = layout_pages(edition, THEMES["builder"])[0]["groups"]
    assert split[0]["kind"] == "split"
    assert [g["kind"] for g in banner[:2]] == ["full", "full"]


def test_citations_become_links(edition):
    html = render_html(edition, THEMES["broadsheet"])
    assert 'href="https://www.anthropic.com/claude-haiku-5-5"' in html
    assert html.count('<section class="page"') == 10
    assert "<script" not in html.lower()


def test_email_body_and_transport_selection(edition, tmp_path, monkeypatch):
    from aieditor import mailer

    pdf = tmp_path / "e.pdf"
    pdf.write_bytes(b"%PDF-1.4 test")
    for var in ("MAIL_TO", "RESEND_API_KEY", "SMTP_HOST"):
        monkeypatch.delenv(var, raising=False)
    assert mailer.send_edition(edition, "Test", [pdf]).startswith("skipped")

    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, context=None, timeout=None):
            sent["host"] = host

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def login(self, user, pw):
            sent["user"] = user

        def send_message(self, msg):
            sent["msg"] = msg

    monkeypatch.setenv("MAIL_TO", "reader@example.com")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_USER", "bot@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "x")
    monkeypatch.setattr(mailer.smtplib, "SMTP_SSL", FakeSMTP)
    out = mailer.send_edition(edition, "Test", [pdf])
    assert "reader@example.com" in out
    msg = sent["msg"]
    assert msg["To"] == "reader@example.com"
    assert "8 October 2026" in msg["Subject"]
    assert [p.get_filename() for p in msg.iter_attachments()] == ["e.pdf"]


def test_railway_schedule_is_10am_and_6pm_ist():
    cfg = json.loads((ROOT / "railway.json").read_text())
    minute, hours, *_ = cfg["deploy"]["cronSchedule"].split()
    # Railway cron runs in UTC; IST = UTC+05:30
    ist = sorted(((int(h) * 60 + int(minute) + 330) // 60 % 24, (int(minute) + 30) % 60) for h in hours.split(","))
    assert ist == [(10, 0), (18, 0)]
    assert cfg["deploy"]["restartPolicyType"] == "NEVER"
