"""Automated research + composition with the Claude API.

Stage 1 (research): Claude searches and reads the live web with the server-side
web_search / web_fetch tools and writes a dated, sourced research dossier for
the rolling 24-hour window.

Stage 2 (compose): Claude turns the dossier into an edition JSON that matches
aieditor.schema.EDITION_SCHEMA (enforced with structured outputs). Validation
or layout problems are sent back in the same conversation for a repair pass.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import anthropic

from .schema import EDITION_SCHEMA, PAGE_SECTIONS

log = logging.getLogger("aieditor.research")

IST = ZoneInfo("Asia/Kolkata")
MODEL = os.environ.get("AIEDITOR_MODEL", "claude-opus-5-5")
BETAS = ["server-side-fallback-2026-07-01"]  # re-run on a fallback model if a request is declined

WEB_TOOLS = [
    {"type": "web_search_20260209", "name": "web_search", "max_uses": int(os.environ.get("AIEDITOR_MAX_SEARCHES", "40"))},
    {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": int(os.environ.get("AIEDITOR_MAX_FETCHES", "40"))},
]


@dataclass
class Window:
    start: datetime
    end: datetime

    @classmethod
    def ending_now(cls, now: datetime | None = None) -> "Window":
        end = (now or datetime.now(IST)).astimezone(IST).replace(second=0, microsecond=0)
        return cls(end - timedelta(hours=24), end)

    def fmt(self, dt: datetime) -> str:
        return dt.strftime("%-d %b %Y, %H:%M IST")

    @property
    def label(self) -> str:
        return f"{self.fmt(self.start)} to {self.fmt(self.end)} (Asia/Kolkata)"


AUDIENCE = """Audience: Rajesh, an experienced Java/Python full-stack AI engineer and startup builder in India.
Prioritise agentic AI, LLMs/SLMs, RAG, coding/testing agents, voice AI/TTS, APIs, open-source models,
enterprise adoption, cloud infrastructure and Indian IT. Include consequential global IT news beyond AI.
Write accessible professional English with useful technical depth."""

RESEARCH_PROMPT = """You are the research desk for "Rajesh's AI & IT Daily".

Coverage window: {window}. Today in India is {today}.
{audience}

Research the LIVE web with web_search and web_fetch. Never use remembered headlines as current news.

1. Gather candidates from primary sources (official model announcements, model cards, release notes,
   research papers, GitHub releases, investor relations and regulatory filings) and reputable reporting.
   Use TLDR AI, The Rundown AI, The Decoder, VentureBeat, Reuters and other established publications for
   discovery, and LangChain's blog for agent engineering. Verify substantive technical claims on primary
   sources with web_fetch. Do not rely on search snippets where the full source is accessible; when a
   page cannot be fetched, say the fact rests on search results only.
2. Check the EVENT date against the window, not just the publication date. Older events republished today
   are not new: list them separately as context. Deduplicate. Rank by material impact, credibility and
   relevance, not hype. Aim for 12-18 substantive in-window developments if they exist; if the day is
   quiet, say so instead of padding.
3. Models launched or changed: exact model/version, company, release date, preview vs GA, open weights vs
   open source vs proprietary, modalities, API/self-hosting availability, pricing with units, reported
   capabilities and limitations. Write "Not disclosed" for anything unpublished. Label vendor benchmarks
   versus independent tests.
4. People discussing models: name, affiliation, model, paraphrase, timestamp, original source. Separate
   personal opinion, vendor marketing and independent evaluation. Never invent quotations.
5. Company bets: investor/buyer, recipient/provider, model/platform, purpose, amount and currency, stage.
   Separate equity, acquisitions, cloud spend, purchase commitments and partnerships; separate announced
   from completed; never double-count.
6. Broad model coverage: coding, reasoning, multimodal, voice/TTS/speech, open-weight and small models,
   and API pricing, deprecation or rate-limit changes from any provider.
7. Agentic AI evolution: which capabilities changed (memory, planning, computer/browser use, multi-agent,
   evaluations, protocols such as MCP/A2A), how they improve existing workflows, maturity (experimental,
   beta, GA), limitations.
8. Healthcare AI: medical models, imaging, clinical assistants, hospital agents, drug discovery and
   genomics. Classify each item's evidence stage as RESEARCH (paper/preprint/benchmark), CLINICAL
   VALIDATION (prospective study, trial, peer-reviewed clinical evaluation, regulatory submission) or
   DEPLOYMENT (live use, regulatory clearance, commercial launch). Distinguish preprints from
   peer-reviewed work.
9. X/Twitter: 5-8 candidate posts from named AI/IT people inside the window, with author, handle,
   affiliation, the direct x.com status URL, timestamp, an accurate paraphrase and why it matters. State
   how each was verified. Never present unverifiable posts or engagement figures as facts.
10. Verified upcoming events (next ~3 weeks) with dates and sources.

Output a research dossier in Markdown. For every item give: headline; event date/time with timezone;
facts; numbers exactly as published; why it matters for Rajesh; verification level (primary page read /
multiple reports / single source); and every source URL with publisher and publication date."""

COMPOSE_PROMPT = """You are the editor of "Rajesh's AI & IT Daily". Turn the research dossier below into
the edition JSON. Use ONLY facts in the dossier; do not add news from memory.

Edition date: {edition_date}. Coverage window: {window_start} to {window_end}, timezone Asia/Kolkata.
Set meta.title to "Rajesh's AI & IT Daily", meta.generated_at to "{generated_at}", and meta.status_note to a
one-sentence description of how facts were verified.

Write exactly ten pages, numbered 1-10, with these sections in order: {sections}.
- Page 1: a "headlines" block (span "full") with the top five headlines; then the lead story (type
  "story" with what/why/impact); then a "callout" executive summary (items) and a short callout on the
  coverage window and verification method.
- Page 2 (Model Watch): launches and material updates across coding, reasoning, multimodal, voice/TTS,
  open-source and small models, plus pricing and API changes. Include a compact factual "table" (span
  "full") of model, company, date and status, licence and access, modalities and limits, and pricing
  with units. Label vendor and independent benchmarks.
- Page 3 (Agentic AI Evolution): what capabilities changed, how they improve existing workflows,
  maturity (experimental, beta or GA), limitations and practical implications. A small maturity table
  is welcome.
- Page 4 (Healthcare AI): medical models, imaging, clinical assistants, hospital agents, drug discovery
  and genomics. Label every block's evidence stage with "Research", "Clinical validation" or
  "Deployment", and state limitations such as sample size, retrospective design or regulatory status.
  If nothing verified happened, say so with "No significant verified update" and add brief background.
- Page 5 (Voices & X Posts): a table of 3-5 X/Twitter posts (author and handle, post paraphrase,
  timestamp, why it matters, evidence), each citing its x.com URL as a source; then a commentary table
  or stories of named people with affiliation, model, paraphrase, date/source and evidence quality; and
  a note on disagreements. Never present engagement numbers or unverifiable posts as facts.
- Page 6 (Developer Desk): coding/testing agents, Java/Python tooling, APIs, open source.
- Page 7 (Money, Chips & Trust): a deal table (buyer, recipient, type, amount, stage, purpose)
  separating equity, acquisitions, credit, purchase commitments and partnerships without double
  counting; then chips, cloud, security, reliability, governance and regulation.
- Page 8 (India & Global IT): Indian IT services and startups, enterprise software, workforce, major
  non-AI tech news.
- Page 9 ("What It Means for Rajesh"): three actionable implications (engineering, security or
  architecture, career or startup) and one small experiment, all labelled "Analysis", grounded in this
  edition. No personalised investment advice.
- Page 10: watchlist of upcoming verified events, unresolved questions, three takeaways, and finally a
  block with type "list", span "full", title "__sources__" (the renderer prints the full source list there).

Rules:
- Major stories use "what" (facts), "why" (why it matters) and "impact" (likely practical impact, which
  is inference). Keep fact and inference separate; label blocks "Fact", "Analysis", "Background",
  "Opinion" or "No significant verified update".
- If a beat had no verified news, include a short block labelled "No significant verified update".
- Mark context items from outside the window as context.
- Cite inline with bracketed source ids such as [3] or [3, 7], matching "sources". Every source needs an
  absolute URL, its publisher, title and publication date. Cite on every page.
- Total editorial prose about 1,800-2,500 words across the ten pages (tables extra). Each page must fit
  one A4 newspaper page: roughly 160-300 words of prose plus at most two tables of up to 7 rows each.
  Page 10 must stay short (under 150 words before the source list).
- Use "span": "column" for normal stories (two-column flow) and "full" for tables, callouts and the lead.
- Fill unused fields with "" or []. "slide" per page: a short title, 4-5 concise takeaways with
  citations, detailed speaker notes (120-200 words, plain text), and the cited source ids.
- summary_headlines: the five top headlines without citation markers.

RESEARCH DOSSIER
================
{dossier}"""


def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(max_retries=4, timeout=1800)


def _final(client: anthropic.Anthropic, **kw):
    with client.beta.messages.stream(**kw) as stream:
        return stream.get_final_message()


def _text(msg) -> str:
    return "".join(b.text for b in msg.content if b.type == "text")


def _check_refusal(msg, stage: str) -> None:
    if msg.stop_reason == "refusal":
        detail = getattr(msg, "stop_details", None)
        raise RuntimeError(f"{stage}: request declined ({detail})")


def research(window: Window, client: anthropic.Anthropic | None = None) -> str:
    client = client or _client()
    prompt = RESEARCH_PROMPT.format(
        window=window.label, today=window.end.strftime("%A, %-d %B %Y"), audience=AUDIENCE
    )
    messages = [{"role": "user", "content": prompt}]
    for _ in range(8):  # server tools can pause long turns; resume until the dossier is finished
        msg = _final(
            client, model=MODEL, max_tokens=64000, betas=BETAS, fallbacks="default",
            thinking={"type": "adaptive"}, output_config={"effort": "high"},
            tools=WEB_TOOLS, messages=messages,
        )
        _check_refusal(msg, "research")
        if msg.stop_reason != "pause_turn":
            break
        messages.append({"role": "assistant", "content": msg.content})
    dossier = _text(msg)
    if not dossier.strip():
        raise RuntimeError("research returned no dossier text")
    log.info("dossier: %d chars, stop=%s", len(dossier), msg.stop_reason)
    return dossier


class Composer:
    """Keeps the compose conversation so repair requests stay append-only."""

    def __init__(self, window: Window, dossier: str, client: anthropic.Anthropic | None = None):
        self.client = client or _client()
        now = datetime.now(IST)
        prompt = COMPOSE_PROMPT.format(
            edition_date=window.end.strftime("%A, %-d %B %Y"),
            window_start=window.fmt(window.start),
            window_end=window.fmt(window.end),
            generated_at=now.strftime("%-d %b %Y, %H:%M IST"),
            sections=", ".join(f"{i}. {s}" for i, s in enumerate(PAGE_SECTIONS, 1)),
            dossier=dossier,
        )
        self.messages: list[dict] = [{"role": "user", "content": prompt}]

    def _ask(self) -> dict:
        msg = _final(
            self.client, model=MODEL, max_tokens=64000, betas=BETAS, fallbacks="default",
            thinking={"type": "adaptive"}, output_config={
                "effort": "high",
                "format": {"type": "json_schema", "schema": EDITION_SCHEMA},
            },
            messages=self.messages,
        )
        _check_refusal(msg, "compose")
        if msg.stop_reason == "max_tokens":
            raise RuntimeError("compose hit max_tokens; edition JSON incomplete")
        self.messages.append({"role": "assistant", "content": msg.content})
        return json.loads(_text(msg))

    def compose(self) -> dict:
        return self._ask()

    def repair(self, problems: list[str]) -> dict:
        self.messages.append({
            "role": "user",
            "content": "Fix these problems and return the complete corrected edition JSON. "
                       "Shorten copy where a page overflows; do not drop citations or required blocks.\n- "
                       + "\n- ".join(problems),
        })
        return self._ask()
