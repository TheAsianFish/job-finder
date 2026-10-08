# Implementation Status vs. Acceptance Criteria (spec §30)

Last updated: 2026-10-06

| # | Criterion | Status | Notes |
|---|---|---|---|
| 1 | Fresh install works from README on macOS | ✅ | `uv sync` → `init` → `doctor`; also `scripts/install_macos.sh` |
| 2 | Discord webhook test message | ✅ | `notify test` |
| 3 | Baseline scan without alert flood | ✅ | `baseline` command + auto-baseline guard on empty DB; single summary embed |
| 4 | Greenhouse/Lever/Ashby against fixtures and one live board each | ✅ | Fixture tests in `tests/unit/test_*_adapter.py`; live-verified against stripe (GH), palantir (Lever), openai (Ashby) — see verification log below |
| 5 | JSON-LD fallback works | ✅ | Single object, arrays, `@graph`, nested; malformed blocks tolerated |
| 6 | Jobs normalized into one schema | ✅ | `JobRecord`; all adapters flow through `pipeline/normalizer.py` |
| 7 | Duplicates merged safely | ✅ | 3-tier aliases (identity/URL/fuzzy); city-level location keys; cross-adapter merge tested |
| 8 | New jobs produce one alert | ✅ | `alerted_at` guard; e2e test asserts no re-alert |
| 9 | Changed jobs tracked, optionally alerted | ✅ | `job_changes` table; meaningful-change filter; digest section; `alerts.alert_on_changes` |
| 10 | No false closure after source failure | ✅ | Misses counted only on successful scans; zero-drop anomaly guard; tested |
| 11 | Scoring reflects Patrick's profile | ✅ | Skill/concept weights from profile.yaml; component breakdown stored per job |
| 12 | Winter/Spring/Fall timing priority | ✅ | Off-cycle timing boost + immediate-alert overrides for explicit off-season *and* Summer roles at core/strong; fall_2026/winter_2027 windows; expired windows ignored |
| 13 | Dashboard works locally | ✅ | 127.0.0.1:8765; home/jobs/detail/companies/health/settings |
| 14 | CLI: scan, daemon, status, companies, job status changes | ✅ | Full command tree per spec §17 |
| 15 | Daemon survives transient network failures | ✅ | Per-scan exception isolation; failures recorded, never crash the loop |
| 16 | launchd installer works | ✅ | `scripts/install_launchd.sh`, KeepAlive, logs to ~/Library/Logs/OpportunityRadar |
| 17 | Tests pass | ✅ | 247 tests, offline (respx fixtures) |
| 18 | Type checking and linting pass | ✅ | ruff format+lint, mypy clean |
| 19 | Secrets not committed | ✅ | `.env`, local yaml configs, and DB gitignored; log redaction for webhook keys |
| 20 | No auto-application functionality | ✅ | Read-only GETs only; apply URLs surfaced for manual use |
| 21 | Docs explain adding company and adapter | ✅ | README sections |
| 22 | Source-health failures visible | ✅ | `/health` page, `sources health` CLI, digest section, core-failure Discord notice |
| 23 | CSV export works | ✅ | `jobs export --format csv|json` |
| 24 | Direct application links preserved | ✅ | `apply_url` on every record/alert/page; preserved through closure |
| 25 | Runs without paid API or LLM | ✅ | Zero paid dependencies; optional flags unused by default |

## Live verification log (2026-08-05)

`companies validate` against real public boards (single polite GET each):
- stripe (greenhouse) — OK, 548 jobs
- palantir (lever) — OK, 301 jobs
- openai (ashby) — OK, 735 jobs
- sentry/benchling/applied-intuition (ashby), shield-ai (lever),
  five-rings (greenhouse) — OK after re-fingerprinting with `companies discover`

Full live baseline run: **94 sources scanned, 13,793 jobs fetched, 13,291
imported** with zero per-job alerts (baseline mode) and one summary. Ten seed
sources 404'd on stale board tokens; five were re-pointed via built-in ATS
discovery, four were disabled with notes, one (skydio) fell back to auto.
Dashboard verified serving all pages on 127.0.0.1:8765 against the live
database; a real Roblox "[Summer 2027] Software Engineer Intern" scored 90.5
with correct season, direct apply URL, and extracted eligibility sentence.

Second full live scan (dedupe proof): **90 sources, 14,611 jobs seen, 812
new** — the new records correspond almost exactly to the five freshly
re-pointed sources (~816 jobs); every previously imported job deduplicated
against its existing record. 319 meaningful changes tracked, 0 false
closures, 90/94 sources healthy. Final DB: 14,103 active jobs, of which 22
clear the immediate-alert bar and 933 are early-career (91 off-season) —
high recall, low noise, as designed.

## Post-launch additions (2026-08-06)

- Discord webhook configured and verified live (test message, real alerts for
  Anduril and Roblox Summer 2027 intern roles).
- Fixed alias unique-constraint crash on fuzzy-key collisions after title
  changes; persistence errors now isolated per company.
- Feedback-driven tuning (`tune` command, bounded + audited) and automatic
  source repair (`companies repair`); both run weekly from the daemon when
  `scheduler.auto_tune: true`.
- `CLAUDE.md` added for future Claude Code session continuity.

## Post-launch fixes (2026-08-10)

Root-caused "digests repeat the same items and real openings get missed":

- **Cloud scans never alerted.** `actions/download-artifact@v4` cannot fetch
  an artifact from a previous run without an explicit `run-id`, so every
  hourly cloud run restored nothing, auto-baselined an empty database, and
  sent no new-job alerts (only noise digests). State now persists via
  `actions/cache` restore/save with a `radar-db-` prefix key (see AD-14).
- **Distinct requisitions were fuzzy-merged.** Boards post separate
  requisitions with identical title+location (SpaceX had 22 such pairs);
  the fuzzy dedup key collapsed them into one row whose description
  flip-flopped every scan, flooding "Changed / reopened". Fuzzy matches are
  now rejected when both sides carry different concrete job IDs from the
  same adapter; cross-source bridging is unchanged (see AD-14).
- **Digest changes now report once and pass the relevance bar.** The
  "Changed / reopened" window starts at the previous digest (was: fixed
  24 h, so morning and evening overlapped), and changed jobs are filtered
  by `digest_min_score` + active status — senior/non-SWE roles no longer
  appear. Scanner applies the same score gate to `digest_pending`.
- **Empty digests say so.** A scheduled digest with nothing to report sends
  a compact "No new updates since the last digest (N hours ago)" notice, so
  a quiet channel is distinguishable from a broken monitor.
- **Non-software roles never notify.** Civil/electrical/hardware interns at
  core companies were out-scoring the digest bar on tier + timing points
  alone. `decide_alert_level` now caps non-software classifications at
  dashboard regardless of score, the digest applies the same `role_family`
  guard to every section, "engineer" signals also match "engineering"
  (catching e.g. "Civil Engineering Internship"), and the non-software
  signal list gained hardware/aerospace/industrial/technician/supply-chain
  disciplines. "Quantitative development" was added to the quant family.
- **Digest bar lowered 60 → 50** at Patrick's request (mass-applying):
  on-target SWE roles at broad/exploratory-tier companies now reach the
  digest instead of sitting dashboard-only. Audited in `tuning_history`.
- **Non-US roles never notify** (regression: a Lisbon-based Cloudflare
  intern role alerted at high score). `is_us_accessible` gates alerts and
  every digest section: clearly non-US locations and non-USD pay cap at
  dashboard regardless of score; unknown locations never gate. The non-US
  hint list grew from ~20 cities to broad country/city coverage; bare state
  abbreviations now only count after a comma ("London or Dublin" is no
  longer Oregon); non-US remote earns no remote bonus. Profile now records
  `us_citizen: true` / `requires_sponsorship: false`, so citizenship-required
  roles (SpaceX/Anduril/Palantir) stop taking "uncertain" penalties.

## Coverage expansion (2026-10-06)

Root-caused "only Anduril shows up, no FAANG+":

- **32 enabled seeds were silent.** `adapter: auto` on JS-rendered career
  pages fell through to JSON-LD and "succeeded" with 0 jobs every scan, so
  xAI, Waymo, Perplexity, Cursor, Skydio, Figure, IMC, Optiver, Rocket Lab
  and two dozen more never contributed a single posting, and `repair` only
  looked at hard failures. All re-pointed to verified public boards;
  discovery now guesses board tokens from the company slug and `repair`
  targets 0-job sources too (AD-16 ff.).
- **Every big-tech seed was disabled** behind spec-§8.8 placeholders. New
  adapters (Workday, SmartRecruiters, Eightfold, amazon.jobs, GitHub,
  Atlassian) enable NVIDIA, Adobe, Salesforce, CrowdStrike, Intel,
  Autodesk, Zoom, Workday, Broadcom, ServiceNow, Netflix, Amazon, GitHub,
  Atlassian, Snowflake (Ashby), Jane Street (Greenhouse), Spotify (Lever).
- **Registry grew 117 → 199 companies (178 enabled)** with ~85 new
  verified boards across AI, infra, fintech, quant, security, autonomy,
  health (Cerebras, Cohere, Glean, Harvey, Sierra, Verkada, Rubrik, Nuro,
  Zoox, Tower, Virtu, DV Trading, Riot, Epic, Pure Storage, …).
- **Digest fairness**: ≤3 lines per company per section (AD-18).
- **Season breadth**: fall_2026 + winter_2027 windows, Summer immediate
  override, immediate bar 78 (AD-20).
- **New sources never flood**: per-source baseline + one summary (AD-17).

Live verification (`companies validate`, one polite fetch per source,
2026-10-06): **177 of 178 enabled sources returned jobs**; the one
zero (Broadcom, Workday) has no intern/new-grad facet or titles today, which
the pre-filtering adapters report legitimately (they are exempt from the
silent-source warning). Workday/SmartRecruiters/Eightfold/amazon/GitHub/
Atlassian were each exercised end-to-end against their real endpoints;
NVIDIA's facet-driven pass returns 192 early-career postings (47 software).

Still disabled (no public JSON found, never scraped around): Google, Meta,
Apple (401), Microsoft (blocked), IBM, Uber, Citadel (bot challenge), Two
Sigma (Avature), SIG, Hugging Face (Workable), Procore (SmartRecruiters id
unknown), Replicate, HashiCorp (IBM), W&B, Groq, Postman, DigitalOcean,
dbt Labs, Canva, Grammarly, Tempus, Rippling.

## Freshness + Simplify (2026-10-07)

- **Simplify feeds ingested** (AD-21): Summer 2027 internships and new-grad
  lists, ~4,300 relevant live postings. Live dry run: 361 + 213 postings
  skipped because the employer is scanned directly; Google, Meta, Apple,
  Microsoft, Citadel, Two Sigma, SIG, Tesla, AMD, Intuit and Palo Alto
  Networks postings now arrive at their registry tiers. Baseline
  classification of the live internship list: 83 immediate-grade, 941
  digest-grade, so steady state is a handful of pings a day.
- **Cloud cadence** (AD-22): every 10 minutes in `--mode auto`; full
  registry hourly. Greenhouse/Ashby/Lever get parallel API slots.
- **Dependencies upgraded** (SQLAlchemy 2.1, FastAPI 0.142, ...), Actions
  bumped to checkout v7 / cache v6 / setup-uv v10.

## Career copilot (2026-10-08)

- Full-time roles notify when aligned with graduation (AD-27); posted pay is
  a gentle nudge; disabled sources' jobs are closed.
- Adaptive resumes (AD-28): bullet bank from the private `resume.tex`,
  deterministic selection, guarded Claude polish, pdfLaTeX one-page compile,
  ATS report; auto-attached to immediate alerts in Discord; dashboard button;
  weekly role-family variants.
- Applications log in the private repo, synced every scan; digests skip
  roles already applied to or dismissed; outcomes report live.
- Weekly review and project plans written to the private repo and posted to
  Discord.

- Resume rules v2 (AD-31): experience fixed, projects reshuffled per role,
  ATS-first writer that may drop/replace weak bullets; bullets needing an
  unwritten fact become an approval PR in the private repo with an interview
  prep sheet; merged ones live in `verified.yaml` and feed every later resume.
- Project builder (AD-32): weekly Fable scout, Patrick-approved projects built
  in their own repos one milestone PR at a time (Fable plan/review, Opus
  build), comments addressed automatically, resume entry proposed from
  measured results. `opportunity-radar projects list|approve|pause|reject|step`.
- Shared memory + Discord hub (AD-33): `hub/` in the private repo (ABOUT,
  journal, project summaries) read by every agent; bot-created channels
  (#resume, #projects, #study, #agent-log); learning layer (PR study notes,
  Patrick's piece, Sunday study pack, mock-interview gate).

## Known gaps / deferred (with reasons)

- **iCIMS / SuccessFactors / Taleo**: placeholder adapters by spec §8.8 (no
  stable JSON found). Workday, SmartRecruiters and Eightfold now have real
  adapters (AD-16); the remaining disabled seeds are listed above.
- **Conditional HTTP requests (ETag/304)**: columns scaffolded, plumbing
  deferred — see AD-13.
- **Optional local-LLM features (spec §27)**: not built; deterministic app is
  complete without them, per spec ordering.
- **Secondary sources (spec §28)**: Simplify lists done (AD-21). YC /
  Wellfound still open; see `docs/proposals/yc-spring-radar.md`.
- **Some seed board tokens are best-effort**: run
  `opportunity-radar companies validate` after install; `companies discover`
  re-fingerprints failures.
