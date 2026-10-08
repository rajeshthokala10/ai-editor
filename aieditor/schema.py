"""Edition data model.

An edition is plain JSON so it can be written by hand, by the research
pipeline (aieditor.research), or by any other tool, and rendered to PDF and
PPTX without touching the renderers. Every object lists all of its fields as
required (empty string / empty list when unused) so the same schema works with
Claude structured outputs.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import jsonschema

PAGE_SECTIONS = [
    "Front Page",
    "Model Watch",
    "Agentic AI Evolution",
    "Healthcare AI",
    "Voices & X Posts",
    "Developer Desk",
    "Money, Chips & Trust",
    "India & Global IT",
    "What It Means for Rajesh",
    "Watchlist & Source Desk",
]

BLOCK_TYPES = ["headlines", "story", "table", "list", "callout"]
LABELS = [
    "Fact", "Analysis", "Background", "Opinion", "No significant verified update",
    # evidence stages for healthcare and research items
    "Research", "Clinical validation", "Deployment", "",
]


def _obj(props: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "object",
        "properties": props,
        "required": required if required is not None else list(props),
        "additionalProperties": False,
    }


_STR = {"type": "string"}
_STRS = {"type": "array", "items": {"type": "string"}}
_INTS = {"type": "array", "items": {"type": "integer"}}

BLOCK_SCHEMA = _obj(
    {
        "type": {"type": "string", "enum": BLOCK_TYPES},
        # "full" spans the page width; "column" flows in the two-column grid.
        "span": {"type": "string", "enum": ["full", "column"]},
        "kicker": _STR,
        "title": _STR,
        "label": {"type": "string", "enum": LABELS},
        "what": _STR,
        "why": _STR,
        "impact": _STR,
        "body": _STRS,
        "columns": _STRS,
        "rows": {"type": "array", "items": _STRS},
        "items": _STRS,
        "cites": _INTS,
    }
)

PAGE_SCHEMA = _obj(
    {
        "number": {"type": "integer"},
        "section": {"type": "string", "enum": PAGE_SECTIONS},
        "headline": _STR,
        "dek": _STR,
        "blocks": {"type": "array", "items": BLOCK_SCHEMA},
        "slide": _obj(
            {
                "title": _STR,
                "takeaways": _STRS,
                "notes": _STR,
                "cites": _INTS,
            }
        ),
    }
)

SOURCE_SCHEMA = _obj(
    {
        "id": {"type": "integer"},
        "publisher": _STR,
        "title": _STR,
        "url": _STR,
        "published": _STR,
    }
)

EDITION_SCHEMA = _obj(
    {
        "meta": _obj(
            {
                "title": _STR,
                "edition_date": _STR,
                "window_start": _STR,
                "window_end": _STR,
                "timezone": _STR,
                "generated_at": _STR,
                "status_note": _STR,
            }
        ),
        "summary_headlines": _STRS,
        "sources": {"type": "array", "items": SOURCE_SCHEMA},
        "pages": {"type": "array", "items": PAGE_SCHEMA},
    }
)

CITE_RE = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")


def blank_block(**kw) -> dict:
    """A block with every field present; override what you need."""
    block = {
        "type": "story", "span": "column", "kicker": "", "title": "", "label": "",
        "what": "", "why": "", "impact": "", "body": [], "columns": [], "rows": [],
        "items": [], "cites": [],
    }
    block.update(kw)
    return block


def _text_fields(edition: dict, include_slides: bool = True):
    for page in edition["pages"]:
        yield page["headline"]
        yield page["dek"]
        for b in page["blocks"]:
            yield from (b["what"], b["why"], b["impact"], b["title"])
            yield from b["body"]
            yield from b["items"]
            for row in b["rows"]:
                yield from row
        if include_slides:
            yield from page["slide"]["takeaways"]
            yield page["slide"]["notes"]


def validate(edition: dict) -> list[str]:
    """Return a list of problems; empty means the edition is renderable."""
    problems: list[str] = []
    try:
        jsonschema.validate(edition, EDITION_SCHEMA)
    except jsonschema.ValidationError as e:
        path = "/".join(str(p) for p in e.absolute_path)
        return [f"schema: {path}: {e.message}"]

    pages = edition["pages"]
    if len(pages) != 10:
        problems.append(f"expected exactly 10 pages, got {len(pages)}")
    for i, page in enumerate(pages, 1):
        if page["number"] != i:
            problems.append(f"page {i} has number {page['number']}")
        if i <= len(PAGE_SECTIONS) and page["section"] != PAGE_SECTIONS[i - 1]:
            problems.append(f"page {i} section should be {PAGE_SECTIONS[i - 1]!r}")
        if not page["blocks"]:
            problems.append(f"page {i} has no blocks")

    ids = [s["id"] for s in edition["sources"]]
    if len(ids) != len(set(ids)):
        problems.append("duplicate source ids")
    known = set(ids)
    for s in edition["sources"]:
        if not s["url"].startswith(("https://", "http://")):
            problems.append(f"source {s['id']} has no absolute URL")

    used: set[int] = set()
    for page in pages:
        used.update(page["slide"]["cites"])
        for b in page["blocks"]:
            used.update(b["cites"])
    for text in _text_fields(edition):
        for m in CITE_RE.finditer(text):
            used.update(int(n) for n in m.group(1).split(","))
    missing = sorted(used - known)
    if missing:
        problems.append(f"citations reference unknown sources: {missing}")
    return problems


def load(path: str | Path) -> dict:
    edition = json.loads(Path(path).read_text(encoding="utf-8"))
    problems = validate(edition)
    if problems:
        raise ValueError("invalid edition:\n  " + "\n  ".join(problems))
    return edition


def word_count(edition: dict, include_slides: bool = False) -> int:
    """Words of editorial copy (the newspaper), optionally plus slide text and notes."""
    text = " ".join(_text_fields(edition, include_slides))
    text = CITE_RE.sub("", text)
    return len(re.findall(r"\b[\w'’.-]+\b", text))
