"""Render an edition JSON to a ten-page A4 newspaper PDF via headless Chromium.

The HTML is laid out page by page; an auto-fit pass then tunes each page's
type scale so it is full without being clipped, and the renderer refuses to
write a PDF if any page still overflows.
"""

from __future__ import annotations

import html
import os
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from markupsafe import Markup

from .schema import CITE_RE
from .themes import Theme

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "assets" / "fonts"
TEMPLATES = Path(__file__).resolve().parent / "templates"

MIN_SCALE, MAX_SCALE = 0.80, 1.32


def chromium_path() -> str | None:
    """Prefer an explicitly configured browser, then the sandbox's preinstalled one."""
    for cand in (os.environ.get("CHROMIUM_PATH"), "/opt/pw-browsers/chromium"):
        if cand and Path(cand).exists():
            return cand
    return None  # let Playwright use its own downloaded browser


def _words(b: dict) -> int:
    text = " ".join([b["what"], b["why"], b["impact"], *b["body"], *b["items"]])
    return len(text.split())


def layout_pages(edition: dict, theme: Theme) -> list[dict]:
    """Group blocks into full-width rows, split leads, and 2- or 3-column runs."""
    pages = []
    for page in edition["pages"]:
        blocks = [dict(b) for b in page["blocks"]]
        for b in blocks:
            b["long"] = _words(b) > 170
            b["lead"] = False
        groups: list[dict] = []

        # Front page: the first story is the lead; pair it with the top-five list
        # in "split" themes, or run it full width under the headlines in "banner" ones.
        if page["number"] == 1:
            heads = next((b for b in blocks if b["type"] == "headlines"), None)
            lead = next((b for b in blocks if b["type"] == "story"), None)
            if lead:
                lead["lead"] = True
                lead["span"] = "full"
            if heads and lead and theme.lead == "split":
                groups.append({"kind": "split", "main": lead, "aside": heads})
                blocks = [b for b in blocks if b is not heads and b is not lead]
            elif heads and lead:
                groups.append({"kind": "full", "blocks": [heads]})
                groups.append({"kind": "full", "blocks": [lead]})
                blocks = [b for b in blocks if b is not heads and b is not lead]

        run: list[dict] = []

        def flush():
            if not run:
                return
            if len(run) == 1:  # a lone story reads better across the page than in half a column
                groups.append({"kind": "full", "blocks": list(run)})
                run.clear()
                return
            avg = sum(_words(b) for b in run) / len(run)
            short_run = (len(run) >= 5 and avg < 95) or (len(run) >= 3 and avg < 60)
            ncols = 3 if short_run and not any(b["type"] == "table" for b in run) else 2
            groups.append({"kind": "cols", "ncols": ncols, "blocks": list(run)})
            run.clear()

        for b in blocks:
            if b["span"] == "full" or b["type"] in ("table", "headlines") or b["title"] == "__sources__":
                flush()
                groups.append({"kind": "full", "blocks": [b]})
            else:
                run.append(b)
        flush()
        pages.append({**page, "groups": groups})
    return pages


def _make_env(sources: dict[int, dict]) -> Environment:
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=True)

    def link(n: int) -> str:
        s = sources.get(n)
        href = html.escape(s["url"], quote=True) if s else f"#s{n}"
        return f'<a href="{href}">{n}</a>'

    def cite(text: str) -> Markup:
        """Escape text and turn [3] / [3, 7] markers into clickable superscripts."""
        out, pos = [], 0
        for m in CITE_RE.finditer(text):
            out.append(html.escape(text[pos:m.start()].rstrip(" ")))
            nums = [int(n) for n in m.group(1).split(",")]
            out.append('<sup class="c">[' + ",".join(link(n) for n in nums) + "]</sup>")
            pos = m.end()
        out.append(html.escape(text[pos:]))
        return Markup("".join(out))

    def cites(nums: list[int]) -> Markup:
        if not nums:
            return Markup("")
        return Markup('<sup class="c">[' + ",".join(link(n) for n in nums) + "]</sup>")

    def shorturl(url: str) -> str:
        """Readable link text; the href keeps the full URL."""
        from urllib.parse import urlsplit
        u = urlsplit(url)
        text = (u.netloc.removeprefix("www.") + u.path).rstrip("/")
        return text if len(text) <= 46 else text[:44] + "…"

    def domain(url: str) -> str:
        from urllib.parse import urlsplit
        return urlsplit(url).netloc.removeprefix("www.")

    env.filters["domain"] = domain
    env.filters["cite"] = cite
    env.filters["shorturl"] = shorturl
    env.filters["cites"] = cites
    return env


def render_html(edition: dict, theme: Theme) -> str:
    sources = {s["id"]: s for s in edition["sources"]}
    env = _make_env(sources)
    tpl = env.get_template("edition.html.j2")
    return tpl.render(
        meta=edition["meta"],
        pages=layout_pages(edition, theme),
        sources=edition["sources"],
        t=theme,
        fonts=FONTS.as_uri(),
    )


# Binary-search each page's --fs so content fills the page without overflowing.
AUTOFIT_JS = """
([minS, maxS]) => {
  const report = [];
  for (const page of document.querySelectorAll('.page')) {
    const box = page.querySelector('.content');
    const fits = s => { page.style.setProperty('--fs', s); return box.scrollHeight <= box.clientHeight + 0.5; };
    let lo = minS, hi = maxS, best = null;
    if (fits(maxS)) { best = maxS; }
    else {
      for (let i = 0; i < 14; i++) {
        const mid = (lo + hi) / 2;
        if (fits(mid)) { best = mid; lo = mid; } else { hi = mid; }
      }
    }
    const scale = best === null ? minS : best;
    page.style.setProperty('--fs', scale);
    const over = box.scrollHeight - box.clientHeight;
    const used = Math.min(1, box.scrollHeight / box.clientHeight);
    // how much of the content area is actually covered by laid-out blocks
    let bottom = 0;
    for (const el of box.querySelectorAll('.blk, .pagehead')) {
      bottom = Math.max(bottom, el.getBoundingClientRect().bottom);
    }
    const fill = (bottom - box.getBoundingClientRect().top) / box.clientHeight;
    report.push({page: +page.dataset.page, scale: +scale.toFixed(3), overflow_px: Math.max(0, over), fill: +fill.toFixed(3)});
  }
  return report;
}
"""


class LayoutError(RuntimeError):
    pass


def render_pdf(edition: dict, theme: Theme, out_pdf: Path, html_out: Path | None = None) -> list[dict]:
    from playwright.sync_api import sync_playwright

    doc = render_html(edition, theme)
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    tmp_html = html_out or out_pdf.with_suffix(".html")
    tmp_html.write_text(doc, encoding="utf-8")

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chromium_path())
        page = browser.new_page()
        page.emulate_media(media="print")
        page.goto(tmp_html.as_uri(), wait_until="networkidle")
        page.evaluate("document.fonts.ready")
        report = page.evaluate(AUTOFIT_JS, [MIN_SCALE, MAX_SCALE])
        bad = [r for r in report if r["overflow_px"] > 1]
        if bad:
            browser.close()
            raise LayoutError(f"pages still overflow at minimum type scale: {bad}")
        page.pdf(path=str(out_pdf), format="A4", print_background=True, prefer_css_page_size=True)
        # keep the fitted HTML so the web view matches the PDF
        tmp_html.write_text(_bake_scales(doc, report), encoding="utf-8")
        browser.close()
    return report


def _bake_scales(doc: str, report: list[dict]) -> str:
    for r in report:
        doc = re.sub(
            rf'(<section class="page" id="p{r["page"]}" data-page="{r["page"]}")',
            rf'\1 style="--fs:{r["scale"]}"',
            doc,
            count=1,
        )
    return doc
