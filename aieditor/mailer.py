"""Email the finished edition.

Two transports, chosen by which environment variables are set:
  RESEND_API_KEY            -> Resend HTTPS API (works on hosts that block SMTP ports)
  SMTP_HOST/SMTP_USER/...   -> plain SMTP, e.g. Gmail with an app password
Recipients come from MAIL_TO (comma-separated).
"""

from __future__ import annotations

import base64
import html
import json
import logging
import os
import smtplib
import ssl
import urllib.request
from email.message import EmailMessage
from pathlib import Path

log = logging.getLogger("aieditor.mailer")


def _body(edition: dict, theme_name: str) -> tuple[str, str]:
    meta = edition["meta"]
    heads = edition.get("summary_headlines") or []
    text = "\n".join(
        [f"{meta['title']} — {meta['edition_date']}",
         f"Coverage window: {meta['window_start']} to {meta['window_end']} ({meta['timezone']})", "",
         "Top headlines:", *[f"  {i}. {h}" for i, h in enumerate(heads, 1)], "",
         "The ten-page PDF and the ten-slide PPTX briefing are attached.",
         f"Theme: {theme_name}. {meta['status_note']}"]
    )
    items = "".join(f"<li style='margin:0 0 6px'>{html.escape(h)}</li>" for h in heads)
    page = f"""<div style="font-family:Georgia,serif;max-width:620px;color:#1a1f2b">
<p style="font:700 11px Arial,sans-serif;letter-spacing:.15em;text-transform:uppercase;color:#0e6e6e;margin:0">Daily briefing</p>
<h1 style="font-size:28px;margin:4px 0;color:#14284b">{html.escape(meta['title'])}</h1>
<p style="font:13px Arial,sans-serif;margin:0 0 14px">{html.escape(meta['edition_date'])} · {html.escape(meta['window_start'])} to {html.escape(meta['window_end'])} IST</p>
<ol style="font-size:16px;line-height:1.35;padding-left:20px">{items}</ol>
<p style="font:13px Arial,sans-serif;color:#555">The ten-page PDF and ten-slide PPTX briefing are attached. {html.escape(meta['status_note'])}</p>
</div>"""
    return text, page


def send_edition(edition: dict, theme_name: str, files: list[Path]) -> str:
    to = [a.strip() for a in os.environ.get("MAIL_TO", "").split(",") if a.strip()]
    if not to:
        log.warning("MAIL_TO not set; skipping email")
        return "skipped: MAIL_TO not set"
    subject = f"{edition['meta']['title']} — {edition['meta']['edition_date']}"
    text, page = _body(edition, theme_name)
    if os.environ.get("RESEND_API_KEY"):
        return _send_resend(to, subject, text, page, files)
    if os.environ.get("SMTP_HOST"):
        return _send_smtp(to, subject, text, page, files)
    log.warning("no mail transport configured (RESEND_API_KEY or SMTP_HOST); skipping email")
    return "skipped: no transport"


def _send_resend(to, subject, text, page, files) -> str:
    payload = {
        "from": os.environ.get("MAIL_FROM", "AI Editor <onboarding@resend.dev>"),
        "to": to,
        "subject": subject,
        "text": text,
        "html": page,
        "attachments": [
            {"filename": f.name, "content": base64.b64encode(f.read_bytes()).decode()} for f in files
        ],
    }
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {os.environ['RESEND_API_KEY']}",
                 "Content-Type": "application/json", "User-Agent": "ai-editor/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = resp.read().decode()
    log.info("resend accepted: %s", body)
    return f"sent via Resend: {body}"


def _send_smtp(to, subject, text, page, files) -> str:
    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "465"))
    user = os.environ.get("SMTP_USER", "")
    sender = os.environ.get("MAIL_FROM", user)
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, sender, ", ".join(to)
    msg.set_content(text)
    msg.add_alternative(page, subtype="html")
    for f in files:
        maintype, subtype = (
            ("application", "pdf") if f.suffix == ".pdf"
            else ("application", "vnd.openxmlformats-officedocument.presentationml.presentation")
        )
        msg.add_attachment(f.read_bytes(), maintype=maintype, subtype=subtype, filename=f.name)
    ctx = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=ctx, timeout=60) as s:
            s.login(user, os.environ["SMTP_PASSWORD"])
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=60) as s:
            s.starttls(context=ctx)
            s.login(user, os.environ["SMTP_PASSWORD"])
            s.send_message(msg)
    log.info("smtp sent to %s", to)
    return f"sent via SMTP to {', '.join(to)}"
