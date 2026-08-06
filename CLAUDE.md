# CLAUDE.md — project instructions for Claude Code sessions

This file is loaded automatically by Claude Code in this repo. Follow it.

## What this project is

**Opportunity Radar**: a local-first monitor that polls employer ATS APIs
(Greenhouse/Lever/Ashby/JSON-LD) for SWE internships and new-grad roles,
scores them against Patrick's profile (UCSD CS, graduating **December 2027**),
and sends Discord alerts with direct apply links. The authoritative product
spec is `docs/opportunity-radar-master-spec.md`; deviations are recorded in
`docs/architecture-decisions.md`; progress vs. acceptance criteria in
`docs/implementation-status.md`. Read those before making significant changes.

## Patrick's standing rules

- **Git**: commit often — one commit per logical phase, like a real team.
  ALL commits authored solely as **TheAsianFish <jmchung2006@gmail.com>**.
  Never add "Claude", "AI", "Co-Authored-By", or any agent attribution to
  commit messages. Push to `origin main` when a work session concludes.
- **Hands-off operation**: Patrick does not want to hand-tune parameters.
  Prefer feedback-driven, bounded, audited automation (see `tuning.py`) over
  asking him to edit YAML. Never make tuning a black box: every automatic
  change must carry a reason and land in `tuning_history` in scoring.yaml.
- **Completeness**: finish features fully — code + tests + docs. No stub
  implementations, no "TODO later" unless it genuinely requires credentials
  or external decisions.

## Hard product rules (from the spec — never violate)

- No LinkedIn scraping, no CAPTCHA/login/anti-bot bypassing, no proxy
  rotation, no auto-submitting applications.
- Respect robots.txt and rate limits; official/public ATS APIs preferred;
  Playwright only as last resort.
- Never invent eligibility, dates, compensation, or job status; low-confidence
  season inferences stay labeled as inferred.
- Baseline safety: a first run must never flood alerts.
- Secrets live in `.env` (gitignored). Local config copies
  (`config/*.yaml` except `*.example.yaml` and `title_rules.yaml`) and
  `data/*.db` are gitignored — keep it that way.
- Dashboard binds to 127.0.0.1 only.

## How to work in this repo

- Toolchain: `uv` + Python 3.12. Install: `uv sync`.
- Quality gates (must be green before any commit):
  `uv run ruff format --check src tests && uv run ruff check src tests &&
  uv run mypy src && uv run pytest -q`  (or just `make check`).
- Tests are fully offline (respx-mocked HTTP + fixtures in `tests/fixtures/`).
  New adapters need a sanitized fixture + tests; new parsing logic needs unit
  tests. Live network calls only for explicit verification, politely.
- Schema changes: edit `db/tables.py`, then
  `uv run alembic revision --autogenerate -m "..."` and verify with
  `uv run alembic check`. Never edit applied migrations.
- Adapters return `RawJob` and raise `AdapterError` on failure (never an
  empty list to mask one); all enrichment happens in `pipeline/normalizer.py`.

## Operational state (update when it changes)

- Discord webhook configured in `.env`; alerts verified working live.
- GitHub remote: https://github.com/TheAsianFish/job-finder (push to main).
- Cloud scanning: `.github/workflows/scan.yml`, gated on the repo variable
  `ENABLE_CLOUD_SCAN=true` + `DISCORD_WEBHOOK_URL` Actions secret.
- Local daemon: `scripts/install_launchd.sh`; weekly self-maintenance
  (`tune` + `companies repair`) runs when `scheduler.auto_tune: true`.
- Known-disabled seeds (custom ATS, need adapter work): Google, Meta, Apple,
  Amazon, Microsoft, NVIDIA, Netflix, IBM, Adobe, Salesforce, Snowflake,
  GitHub, Atlassian, Uber, Spotify, Jane Street, Citadel, Two Sigma, SIG,
  CrowdStrike, Procore, Esri, Snyk, HashiCorp, Replicate, Tempus.

## Priorities when extending

Spec ordering: **reliability > accuracy > maintainability > breadth > speed >
visual polish.** Next highest-value items are tracked at the bottom of
`docs/implementation-status.md`.
