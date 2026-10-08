# Opportunity Radar 📡

Local-first monitor for SWE internships and new-grad roles. Watches employer
source-of-truth career systems (Greenhouse, Lever, Ashby, JSON-LD career
pages), detects newly posted roles across **all** recruiting seasons — Winter,
Spring, Summer, Fall, off-cycle, year-round — ranks them against Patrick's
profile, and sends fast Discord alerts with direct application links.

**What it is not:** an auto-application bot, a LinkedIn scraper, or anything
that bypasses logins, CAPTCHAs, or rate limits. It polls public endpoints
politely and leaves the applying to you.

---

## Install (macOS)

```bash
git clone <repo>
cd job-finder
brew install uv
uv sync
cp .env.example .env
cp config/settings.example.yaml config/settings.yaml
cp config/profile.example.yaml config/profile.yaml
cp config/companies.example.yaml config/companies.yaml
cp config/scoring.example.yaml config/scoring.yaml
uv run opportunity-radar init      # idempotent: creates missing configs + migrates DB
uv run opportunity-radar doctor    # verifies everything
```

Or run the whole flow in one step:

```bash
scripts/install_macos.sh
```

Optional browser fallback (only needed for `adapter: playwright` companies):

```bash
uv sync --extra browser
uv run playwright install chromium
```

## Discord setup

1. Create a private Discord server (or pick a private channel).
2. Channel **Settings → Integrations → Webhooks → New Webhook**.
3. Copy the webhook URL into `.env` as `DISCORD_WEBHOOK_URL=...`.
4. Test it:

```bash
uv run opportunity-radar notify test
```

## First run — baseline (important)

The first scan imports everything that is already posted **without sending
per-job alerts**, so you don't get 500 pings for old listings:

```bash
uv run opportunity-radar baseline
```

You get one summary message (counts by score and source). After that, every
`scan` alerts only on genuinely new or meaningfully changed roles. If you want
alerts for already-open roles instead: `opportunity-radar baseline --alert-existing`.
(Safety net: even a plain `scan` on an empty database auto-converts to
baseline mode.)

## Daily usage

```bash
uv run opportunity-radar scan                     # scan everything now
uv run opportunity-radar scan --company stripe    # one company
uv run opportunity-radar scan --adapter greenhouse
uv run opportunity-radar serve                    # dashboard at http://127.0.0.1:8765
uv run opportunity-radar status                   # counts + recent scans
uv run opportunity-radar jobs list --min-score 60
uv run opportunity-radar jobs show 42
uv run opportunity-radar jobs save 42
uv run opportunity-radar jobs applied 42 --resume backend_infrastructure
uv run opportunity-radar jobs export --format csv -o jobs.csv
uv run opportunity-radar sources health
uv run opportunity-radar notify digest            # send a digest now
```

## Run automatically (launchd)

```bash
scripts/install_launchd.sh
```

This installs a login agent that runs `opportunity-radar daemon`: scans core
companies every 20 min, strong every 45, broad every 2 h, exploratory every
6 h (configurable in `config/settings.yaml`), sends immediate alerts, and
posts morning/evening digests. Logs land in `~/Library/Logs/OpportunityRadar/`.

- Stop: `launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.patrick.opportunity-radar.plist`
- Uninstall: `scripts/uninstall_launchd.sh`

**Sleep behavior:** scans don't run while the Mac is fully asleep. On wake the
daemon notices the time jump and runs one catch-up pass over overdue sources —
no duplicate backlog.

## Docker (optional)

```bash
docker compose up -d          # daemon + dashboard on 127.0.0.1:8765
```

## GitHub Actions (optional)

`.github/workflows/scan.yml` can scan hourly while your Mac is offline. It is
off by default: set repository variable `ENABLE_CLOUD_SCAN=true` and add
`DISCORD_WEBHOOK_URL` to Actions secrets. SQLite state persists as a workflow
artifact (best-effort). Local mode remains canonical.

---

## Hands-off maintenance

The system tunes and repairs itself from how you actually use it:

```bash
uv run opportunity-radar tune            # show recommended parameter nudges
uv run opportunity-radar tune --apply    # write them to config/scoring.yaml
uv run opportunity-radar companies repair  # re-discover ATS config for failing sources
```

- **Tuning** learns from saves/applies/dismissals: role families you dismiss
  lose a point of weight, families you save gain one; if you dismiss most
  immediate alerts the alert threshold rises, if you keep saving digest-tier
  jobs it falls. Changes are bounded (±1 weight / ±2 threshold per run, hard
  caps), need minimum sample sizes, and every change is written with its
  reason to `tuning_history` in `config/scoring.yaml`. Company demotions are
  only ever suggested, never applied automatically.
- **Repair** re-fingerprints companies whose sources keep failing (stale
  board token, ATS migration), trial-validates the discovered config against
  the live API, and only then rewrites `config/companies.yaml`.

With `scheduler.auto_tune: true` in `config/settings.yaml`, the daemon runs
both weekly and posts a self-maintenance summary to Discord.

## Adding a company

Edit `config/companies.yaml` (or `opportunity-radar companies add`):

```yaml
- id: newco
  name: NewCo
  domain: newco.com
  tier: strong            # core | strong | broad | exploratory
  adapter: auto           # fingerprints greenhouse/lever/ashby from career_urls
  career_urls:
    - https://boards.greenhouse.io/newco
```

Explicit adapters when you know the source:

```yaml
  adapter: greenhouse
  adapter_config: { board_token: newco }

  adapter: lever
  adapter_config: { site: newco }        # region: eu for jobs.eu.lever.co

  adapter: ashby
  adapter_config: { job_board_name: newco }

  adapter: workday                       # host + site from the careers URL
  adapter_config: { host: newco.wd5.myworkdayjobs.com, site: NewCoCareers }
  #   optional: search_texts, max_pages, detail_limit (200), early_career_only (true)

  adapter: smartrecruiters               # documented public Posting API
  adapter_config: { company: NewCo }

  adapter: eightfold                     # Eightfold-hosted career sites
  adapter_config: { base_url: https://explore.jobs.newco.net, domain: newco.com }

  adapter: html_generic                  # CSS-selector scraping
  adapter_config:
    list_url: https://newco.com/careers
    selectors: { card: ".job-card", title: ".job-title", location: ".job-loc", url: "a@href" }

  adapter: playwright                    # last resort, JS-rendered pages
  adapter_config: { list_url: https://newco.com/careers, wait_selector: ".job-card" }
```

Then check it: `uv run opportunity-radar companies validate --company newco`.
Not sure what ATS a company uses? `uv run opportunity-radar companies discover newco.com`
(it fingerprints the careers page and, failing that, probes the public
Greenhouse/Ashby/Lever APIs with the company's slug). A source that keeps
returning 0 jobs shows as `0 (silent)` in `sources health`;
`companies repair` re-discovers and rewrites it when a real board is found.

Enterprise boards (Workday, SmartRecruiters, Eightfold, amazon.jobs) are
large and need a detail request per posting, so those adapters only pull
early-career postings by default (`early_career_only: false` to pull all).
Adding a company to a live registry imports its board as a per-source
baseline: one "new sources imported" summary, no per-job alert flood.

## Simplify feeds and scan cadence

Two registry entries (`simplify-internships`, `simplify-new-grad`) poll the
SimplifyJobs lists' published JSON. Postings from employers the registry
already scans directly are skipped; everything else is stored under its own
company (Google, Meta, Tesla, … get their registry tier; unknown employers
get the list's tier). Disable either entry to turn it off.

`scan --mode hot` scans core-tier employers plus the Simplify feeds;
`--mode auto` runs a full scan when the last one is older than
`scheduler.full_scan_interval_minutes` (60) and a hot scan otherwise. The
GitHub Actions workflow runs `--mode auto` every 10 minutes.

## Adaptive resumes and the applications log

Your resume source lives in a private repo cloned at `resume/private/`
(git-ignored here). Commented-out entries in `resume.tex` are the bullet
bank: true content the tailor can swap in when a posting needs it.

```
uv run opportunity-radar resume bank                 # what was parsed (live vs reserve)
uv run opportunity-radar resume tailor 34723         # tailor to a job id or apply URL (Claude polish on)
uv run opportunity-radar resume tailor 34723 --no-polish
uv run opportunity-radar resume variants             # backend / ai-ml / fullstack / infrastructure / general
uv run opportunity-radar resume ats some.pdf --job 34723
uv run opportunity-radar resume assess 34723 --review   # does my resume compete? (Claude review)
uv run opportunity-radar resume review-url <link>       # brutal review + tailored PDF to Discord, any posting
uv run opportunity-radar apply 34723 --resume backend   # log an application (commits + pushes privately)
uv run opportunity-radar jobs status <id-or-url> interview
uv run opportunity-radar insights outcomes            # what works: response rates by tier, role, version, speed
```

Each tailored resume lands in `resume/private/tailored/<date>-<company>-<role>/`
with the PDF, `.tex`, an ATS report and a `meta.json` of every decision.

Every high-priority alert carries a resume verdict (✅ apply as-is / ⚠️ tune /
🛠️ gap). From your phone: GitHub app -> Actions -> Opportunity Radar Agents ->
Run workflow -> task `review-role` + the posting link, for a brutal review of any role.

Cloud scans don't tailor every alert. For important new roles they run a fit
check (`uv run opportunity-radar resume assess <job> [--review]` does the same
locally) and only when your standing resume has a real disconnect do you get
one Discord message: Claude's review (weak bullets, project and culture fit,
competitiveness, swaps, a new-project idea) plus a tailored PDF rewritten as
technical STAR stories. The dashboard's job page has "Tailored resume" buttons.

Import what you applied to through the Simplify extension: Simplify Job Tracker
-> Export CSV, then `uv run opportunity-radar applications import-simplify
export.csv` (or upload it to the private repo's `imports/` folder; every cloud
scan merges it).

Guarantees: tailoring only selects, orders and rewords content already in
`resume.tex`; Claude rewrites are discarded unless every number, skill and
name already exists in your resume. PDFs compile with real pdfLaTeX
(`scripts/install_tinytex.sh`, no sudo) so they match your Overleaf output.

## Adding an adapter

1. Subclass `BaseAdapter` in `src/opportunity_radar/adapters/`, implement
   `fetch_jobs() -> list[RawJob]` (raise `AdapterError` on failure — never
   return `[]` to mask one).
2. Register it in `adapters/registry.py`.
3. Add a sanitized fixture in `tests/fixtures/` and a test.
   Normalization, scoring, dedupe, and alerts come for free.

## Configuration files

| File | Purpose |
|---|---|
| `.env` | secrets: Discord webhook, DB URL, app secret |
| `config/profile.yaml` | graduation date, work-auth answers, skills, preferences |
| `config/companies.yaml` | target registry (tiers, adapters, intervals) |
| `config/scoring.yaml` | score weights, target windows, alert thresholds |
| `config/settings.yaml` | scan intervals, concurrency, digest hours |
| `config/title_rules.yaml` | title patterns, exclusions, role families |

Unknown personal fields (`us_citizen`, `requires_sponsorship`,
`clearance_eligible`) default to `null` = unknown: the eligibility engine
surfaces them as risks instead of guessing.

## Development

```bash
make check     # ruff format check + lint + mypy + pytest
make test
make fmt
uv run pytest --cov
```

Tests run entirely offline against fixtures (respx-mocked HTTP).

## Safety and etiquette

- Official/public ATS APIs preferred; generic page fetches honor robots.txt.
- Descriptive User-Agent, per-domain serialization, backoff, `Retry-After`.
- No LinkedIn, no CAPTCHA bypass, no proxy rotation, no auto-applications.
- Dashboard binds to 127.0.0.1; job HTML is escaped; Discord content is
  sanitized with mentions disabled; secrets stay in `.env` (gitignored).
