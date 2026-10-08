"""Editorial themes and content-driven theme selection.

Each theme is a complete look: type pairing, palette, masthead treatment and
layout habits. `choose_theme` scores the edition's content against each
theme's beat, so a day dominated by model launches looks different from a
day dominated by funding deals or security incidents. It also avoids reusing
the previous edition's theme so consecutive days don't look identical.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Theme:
    key: str
    name: str
    beat: str  # what kind of news day this theme is for
    head_font: str  # font-family names declared in the template
    body_font: str
    ui_font: str
    head_weight: int
    paper: str
    ink: str
    primary: str  # headlines, rules, table headers
    accent: str  # kickers, citation marks, numbers
    accent_soft: str  # callout background
    rule: str
    stripe: str  # alternate table row
    masthead: str  # "centered" | "flag" | "band"
    lead: str  # "banner" | "split"
    dropcap: bool
    headline_case: str = "none"  # css text-transform for page headlines
    keywords: tuple[str, ...] = field(default_factory=tuple)
    # PPTX equivalents (fonts PowerPoint ships, so the deck renders true)
    pptx_head: str = "Cambria"
    pptx_body: str = "Calibri"


THEMES: dict[str, Theme] = {
    t.key: t
    for t in [
        Theme(
            key="broadsheet", name="Broadsheet Classic", beat="balanced news day",
            head_font="Playfair", body_font="SourceSerif", ui_font="InterUI", head_weight=800,
            paper="#FCFAF4", ink="#1A1F2B", primary="#14284B", accent="#0E6E6E",
            accent_soft="#E3F0EE", rule="#C9C3B4", stripe="#F4F1E8",
            masthead="centered", lead="banner", dropcap=True,
            keywords=(),
        ),
        Theme(
            key="modelday", name="Model Day", beat="model launches and research",
            head_font="Fraunces", body_font="Newsreader", ui_font="SpaceGrotesk", head_weight=700,
            paper="#FFFFFF", ink="#191B2A", primary="#232A6B", accent="#0B7A8A",
            accent_soft="#E6F3F5", rule="#CFD3E2", stripe="#F3F4FA",
            masthead="flag", lead="split", dropcap=False,
            keywords=("model", "weights", "benchmark", "llm", "slm", "parameters", "context window",
                      "multimodal", "reasoning", "open-weight", "release", "preview", "tts", "speech"),
            pptx_head="Bookman Old Style",
        ),
        Theme(
            key="markets", name="Markets & Money", beat="funding, deals and compute spend",
            head_font="DMSerif", body_font="Literata", ui_font="PlexSans", head_weight=400,
            paper="#FBF8F1", ink="#1B1D1A", primary="#123B2E", accent="#A86A12",
            accent_soft="#F6EBD7", rule="#D2C7AE", stripe="#F3EEE2",
            masthead="band", lead="banner", dropcap=True,
            keywords=("funding", "raise", "valuation", "acquisition", "acquire", "billion", "investment",
                      "invest", "deal", "revenue", "ipo", "stake", "series", "crore", "earnings", "shares"),
            pptx_head="Cambria",
        ),
        Theme(
            key="trust", name="Infrastructure & Trust", beat="security, chips, cloud and regulation",
            head_font="Bodoni", body_font="SourceSerif", ui_font="PlexSans", head_weight=700,
            paper="#FFFFFF", ink="#1C1C1E", primary="#26272B", accent="#A4262C",
            accent_soft="#F7E8E8", rule="#D3D0CC", stripe="#F5F3F1",
            masthead="centered", lead="split", dropcap=False, headline_case="none",
            keywords=("vulnerability", "cve", "breach", "outage", "security", "attack", "regulation",
                      "act", "compliance", "chip", "gpu", "data center", "datacenter", "export", "governance"),
            pptx_head="Century Schoolbook",
        ),
        Theme(
            key="indiadesk", name="India Desk", beat="Indian IT, startups and policy",
            head_font="Playfair", body_font="Literata", ui_font="InterUI", head_weight=800,
            paper="#FDFAF3", ink="#1D1F26", primary="#1B2F5B", accent="#B5541B",
            accent_soft="#F8E9DD", rule="#D6CDBB", stripe="#F5F0E4",
            masthead="band", lead="split", dropcap=True,
            keywords=("india", "indian", "bengaluru", "bangalore", "tcs", "infosys", "wipro", "hcl",
                      "tech mahindra", "meity", "indiaai", "rupee", "crore", "nasscom", "gcc", "sebi"),
            pptx_head="Bookman Old Style",
        ),
        Theme(
            key="clinical", name="Clinical Edition", beat="healthcare AI, biology and drug discovery",
            head_font="Literata", body_font="SourceSerif", ui_font="PlexSans", head_weight=700,
            paper="#FFFFFF", ink="#18222B", primary="#0D3B4F", accent="#1F8A70",
            accent_soft="#E4F3EE", rule="#C9D6D8", stripe="#F1F7F6",
            masthead="band", lead="split", dropcap=False,
            keywords=("clinical", "patient", "hospital", "medical", "health", "fda", "radiology", "imaging",
                      "drug", "genomic", "protein", "trial", "diagnos", "cdsco", "biotech"),
            pptx_head="Cambria",
        ),
        Theme(
            key="builder", name="Builder's Edition", beat="agents, coding tools and developer platforms",
            head_font="SpaceGrotesk", body_font="Newsreader", ui_font="SpaceGrotesk", head_weight=700,
            paper="#FFFFFF", ink="#16181D", primary="#0F2A3D", accent="#0F7B5F",
            accent_soft="#E2F2EC", rule="#CBD5D3", stripe="#F1F6F4",
            masthead="flag", lead="banner", dropcap=False, headline_case="none",
            keywords=("agent", "agentic", "mcp", "sdk", "api", "github", "copilot", "codex", "cursor",
                      "langchain", "langgraph", "framework", "python", "java", "spring", "open source",
                      "cli", "rag", "eval"),
            pptx_head="Calibri",
        ),
    ]
}


def _edition_text(edition: dict) -> str:
    parts: list[str] = list(edition.get("summary_headlines", []))
    for page in edition["pages"]:
        weight = 3 if page["number"] == 1 else 1  # the front page sets the day's tone
        chunk = [page["headline"], page["dek"]]
        for b in page["blocks"]:
            chunk += [b["title"], b["what"], b["why"]]
        parts += chunk * weight
    return " ".join(parts).lower()


def score_themes(edition: dict) -> dict[str, float]:
    text = _edition_text(edition)
    words = max(1, len(text.split()))
    scores = {}
    for key, theme in THEMES.items():
        hits = sum(len(re.findall(r"\b" + re.escape(k) + r"\w*", text)) for k in theme.keywords)
        scores[key] = 1000.0 * hits / words
    scores["broadsheet"] = 6.0  # baseline: wins only when no beat clearly dominates
    return scores


def choose_theme(edition: dict, previous: str | None = None, override: str | None = None) -> Theme:
    if override:
        if override not in THEMES:
            raise KeyError(f"unknown theme {override!r}; choose from {sorted(THEMES)}")
        return THEMES[override]
    ranked = sorted(score_themes(edition).items(), key=lambda kv: kv[1], reverse=True)
    for key, _ in ranked:
        if key != previous:
            return THEMES[key]
    return THEMES[ranked[0][0]]
