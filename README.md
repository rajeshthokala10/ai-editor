# AI Editor: Rajesh's AI & IT Daily

AI Editor produces a researched, ten-page newspaper PDF and a matching ten-slide 16:9 PPTX briefing covering the **rolling 24 hours before each run** (Asia/Kolkata). It emails both files after every run.

```
research (Claude + live web search/fetch)  →  edition.json (validated schema)
      →  theme chosen from content  →  PDF (Chromium, auto-fit pages)  +  PPTX (speaker notes, links)
      →  QA (10 pages, 10 slides, notes, links, no overflow)  →  email
```

## The ten pages

| # | Section | What it holds |
|---|---|---|
| 1 | Front Page | Top five headlines, lead story, executive summary, exact coverage window |
| 2 | Model Watch | Coding, reasoning, multimodal, voice/TTS, open and small models; pricing and API changes; comparison table |
| 3 | Agentic AI Evolution | Capability changes, workflow impact, maturity, limitations |
| 4 | Healthcare AI | Medical models, imaging, clinical assistants, hospital agents, drug discovery, genomics. Each item is labelled **Research**, **Clinical validation** or **Deployment** |
| 5 | Voices & X Posts | 3–5 sourced X posts plus named commentary, each with an evidence-quality rating |
| 6 | Developer Desk | Coding/testing agents, Java/Python tooling, APIs, open source |
| 7 | Money, Chips & Trust | Deals (no double counting), chips, cloud, security, regulation |
| 8 | India & Global IT | Indian IT services and startups, enterprise software, workforce, non-AI tech |
| 9 | What It Means for Rajesh | Three implications and one experiment, labelled as analysis |
| 10 | Watchlist & Source Desk | Upcoming events, open questions, three takeaways, indexed linked sources |

Every page carries inline `[n]` citations that link to the source. Facts and inference are labelled separately, and quiet beats are marked "No significant verified update" rather than padded.

## Dynamic design: a different look each run

`aieditor/themes.py` defines seven editorial themes. Each one sets the type pairing, palette, masthead (centred, flag or colour band), front-page lead layout (banner or split) and drop caps:

| Theme | Picked when the day is about |
|---|---|
| Broadsheet Classic | a balanced mix of news |
| Model Day | model launches and research |
| Markets & Money | funding, deals, compute spend |
| Infrastructure & Trust | security, chips, cloud, regulation |
| India Desk | Indian IT, startups, policy |
| Builder's Edition | agents, coding tools, developer platforms |
| Clinical Edition | healthcare AI and biology |

The theme is scored from the edition's own text, weighted toward the front page. The renderer skips the previous edition's theme so consecutive runs look different. Within a page, layout adapts too:

- short stories flow into three columns, longer ones into two;
- tables and leads run full width;
- each page's type scale is auto-fitted (binary search in Chromium) so the page is full without being clipped.

The build fails, and no email is sent, if a page still overflows at the minimum readable size.

## Run locally

```bash
pip install -r requirements-dev.txt
python -m playwright install chromium          # once

# Render an existing edition (no API key needed)
python -m aieditor.build editions/2026-10-08/edition.json
python -m aieditor.build editions/2026-10-08/edition.json --theme markets   # force a theme

# Full pipeline: research the last 24h, build, email
export ANTHROPIC_API_KEY=...        # see .env.example for mail settings
python -m aieditor.daily --no-email # or drop --no-email to send

python -m pytest -q                 # 18 tests: schema, themes, layout, rendering, mocked pipeline, email
```

Outputs land in `editions/<date>/`: `edition.json`, `rajesh-ai-it-daily-<date>.pdf`, `.pptx`, `edition.html` and `build.json` (theme, word count, per-page fit, QA results).

## Deploy on Railway (runs at 10:00 and 18:00 IST)

`railway.json` defines a **cron service**. Railway evaluates cron schedules in UTC, so `30 4,12 * * *` means 10:00 and 18:00 IST. Each run researches the 24 hours ending at run time, builds both files, emails them and exits (`restartPolicyType: NEVER`). The root `Dockerfile` installs Chromium through Playwright.

1. In Railway: **New Project → Deploy from GitHub repo → `rajeshthokala10/ai-editor`**. Railway detects the `Dockerfile` and reads the cron schedule from `railway.json`.
2. Under **Variables**, add:

   | Variable | Value |
   |---|---|
   | `ANTHROPIC_API_KEY` | your Claude API key |
   | `MAIL_TO` | `rajeshthokala10@gmail.com` (comma-separate for more) |
   | `RESEND_API_KEY` | from resend.com (recommended: Railway blocks outbound SMTP on some plans) |
   | `MAIL_FROM` | `AI Editor <onboarding@resend.dev>` works for sending to the email you signed up to Resend with; use a verified domain to send elsewhere |

   For SMTP instead of Resend, set `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=465`, `SMTP_USER` and `SMTP_PASSWORD` (a Gmail app password). Note that Railway's lower plans may block SMTP ports.
3. Check **Settings → Cron Schedule** shows `30 4,12 * * *`. Trigger one run from the dashboard and read the logs: each run logs the window, theme, word count and email result.

Optional settings:

- `AIEDITOR_MODEL` (default `claude-opus-5-5`)
- `AIEDITOR_MAX_SEARCHES` and `AIEDITOR_MAX_FETCHES` (default 40 each)
- `EDITIONS_DIR`: point it at a mounted Railway volume to keep past editions. Theme rotation uses that history; without a volume, every run starts fresh and email is the delivery record.

## Integrity rules built into the pipeline

- The research prompt requires live web search and fetch, event-date checks against the window, and labelled verification levels. Context from outside the window is marked as context.
- The model and composer must state "Not disclosed" rather than guess, label vendor versus independent benchmarks, and never invent quotes or engagement numbers.
- The schema validator rejects editions without exactly ten pages in the fixed section order, with citations pointing at unknown sources, or with non-absolute source URLs. Problems go back to the composer for up to three repair rounds. After that the job fails rather than sending a broken edition.

## Layout

```
aieditor/
  schema.py        edition JSON schema (also used for Claude structured outputs) + validator
  themes.py        editorial themes + content-based selection
  render_pdf.py    Jinja → HTML → Chromium PDF, per-page auto-fit
  render_pptx.py   python-pptx 16:9 deck, takeaways, panels, linked sources, speaker notes
  research.py      Claude research (web_search/web_fetch) and composer with repair loop
  daily.py         scheduled-job entry point
  mailer.py        Resend API or SMTP delivery
  templates/edition.html.j2
assets/fonts/      open-licence fonts (OFL), licences alongside
editions/          generated editions (sample: 2026-10-08)
```
