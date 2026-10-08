"""Scheduled job entry point: research -> compose -> render -> QA -> email.

    python -m aieditor.daily                 # full run for the 24h ending now (IST)
    python -m aieditor.daily --no-email      # build only
    python -m aieditor.daily --from-json editions/2026-10-08/edition.json   # skip research, render + email

Exits non-zero if the edition cannot be produced, so the scheduler records a failure
instead of emailing a broken or fabricated edition.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from . import schema
from .build import EDITIONS, build
from .render_pdf import LayoutError

log = logging.getLogger("aieditor.daily")

MAX_REPAIRS = 3


def produce(edition_dir: Path) -> Path:
    from .research import Composer, Window, research

    window = Window.ending_now()
    log.info("window %s", window.label)
    dossier = research(window)
    (edition_dir / "dossier.md").write_text(dossier, encoding="utf-8")

    composer = Composer(window, dossier)
    edition = composer.compose()
    path = edition_dir / "edition.json"
    for attempt in range(MAX_REPAIRS + 1):
        path.write_text(json.dumps(edition, ensure_ascii=False, indent=2), encoding="utf-8")
        problems = schema.validate(edition)
        if not problems:
            try:
                result = build(path)
            except LayoutError as e:
                problems = [f"{e}. Shorten the copy on those pages by about 15-25%."]
            else:
                problems = result["problems"]
                if not problems:
                    return path
        if attempt == MAX_REPAIRS:
            raise RuntimeError(f"edition still has problems after {MAX_REPAIRS} repairs: {problems}")
        log.warning("repair %d: %s", attempt + 1, problems)
        edition = composer.repair(problems)
    return path


def preflight(need_api: bool) -> list[str]:
    """Log which settings are present (never their values) and return blocking problems."""
    names = ["ANTHROPIC_API_KEY", "AIEDITOR_MODEL", "MAIL_TO", "RESEND_API_KEY", "MAIL_FROM",
             "SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "EDITIONS_DIR"]
    log.info("config: %s", ", ".join(f"{n}={'set' if os.environ.get(n) else 'unset'}" for n in names))
    problems = []
    if need_api and not os.environ.get("ANTHROPIC_API_KEY"):
        problems.append("ANTHROPIC_API_KEY is not set: add it under the service's Variables")
    if os.environ.get("MAIL_TO") and not (os.environ.get("RESEND_API_KEY") or os.environ.get("SMTP_HOST")):
        log.warning("MAIL_TO is set but no RESEND_API_KEY or SMTP_HOST: the edition will not be emailed")
    return problems


def check() -> int:
    """--check: verify settings, Claude API access and Chromium without a full run."""
    problems = preflight(need_api=True)
    if not problems:
        from .research import ping

        try:
            log.info("Claude API ok (%s)", ping())
        except Exception as e:  # report any API failure in one readable line
            problems.append(f"Claude API call failed: {type(e).__name__}: {e}")
    try:
        from playwright.sync_api import sync_playwright

        from .render_pdf import chromium_path

        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=chromium_path())
            b.close()
        log.info("Chromium ok")
    except Exception as e:
        problems.append(f"Chromium failed to start: {e}")
    for p in problems:
        log.error("CHECK FAILED: %s", p)
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-email", action="store_true")
    ap.add_argument("--from-json", type=Path, help="render and send an existing edition.json")
    ap.add_argument("--check", action="store_true", help="verify settings, API access and Chromium, then exit")
    args = ap.parse_args(argv)

    if args.check:
        return check()
    problems = preflight(need_api=not args.from_json)
    if problems:
        for p in problems:
            log.error("RUN FAILED: %s", p)
        return 2
    try:
        return run(args)
    except Exception as e:
        log.exception("RUN FAILED: %s: %s", type(e).__name__, e)
        return 1


def run(args) -> int:
    if args.from_json:
        path = args.from_json.resolve()
        result = build(path)
        if result["problems"]:
            log.error("QA problems: %s", result["problems"])
            return 1
    else:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        stamp = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d-%H%M")
        edition_dir = Path(os.environ.get("EDITIONS_DIR", EDITIONS)) / stamp
        edition_dir.mkdir(parents=True, exist_ok=True)
        path = produce(edition_dir)

    report = json.loads((path.parent / "build.json").read_text())
    log.info("built %s (theme %s, %s words)", path.parent.name, report["theme_name"], report["words"])
    if args.no_email:
        return 0

    from .mailer import send_edition

    edition = schema.load(path)
    files = [path.parent / report["pdf"]["file"], path.parent / report["pptx"]["file"]]
    log.info(send_edition(edition, report["theme_name"], files))
    return 0


if __name__ == "__main__":
    sys.exit(main())
