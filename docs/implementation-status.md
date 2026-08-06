# Implementation Status vs. Acceptance Criteria (spec §30)

Last updated: 2026-08-05

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
| 12 | Winter/Spring/Fall timing priority | ✅ | Off-cycle timing boost + immediate-alert override for explicit off-season roles at core/strong |
| 13 | Dashboard works locally | ✅ | 127.0.0.1:8765; home/jobs/detail/companies/health/settings |
| 14 | CLI: scan, daemon, status, companies, job status changes | ✅ | Full command tree per spec §17 |
| 15 | Daemon survives transient network failures | ✅ | Per-scan exception isolation; failures recorded, never crash the loop |
| 16 | launchd installer works | ✅ | `scripts/install_launchd.sh`, KeepAlive, logs to ~/Library/Logs/OpportunityRadar |
| 17 | Tests pass | ✅ | 143 tests, offline (respx fixtures) |
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

## Known gaps / deferred (with reasons)

- **Workday / SmartRecruiters / iCIMS / Eightfold / SuccessFactors / Taleo**:
  placeholder adapters by spec §8.8 (no stable public APIs; the spec forbids
  building on undocumented endpoints). Big-tech seeds using them ship
  `enabled: false` with notes.
- **Conditional HTTP requests (ETag/304)**: columns scaffolded, plumbing
  deferred — see AD-13.
- **Optional local-LLM features (spec §27)**: not built; deterministic app is
  complete without them, per spec ordering.
- **Secondary sources (spec §28, GitHub lists/YC/Wellfound)**: not built;
  employer source-of-truth ingestion is complete. Highest-value next add.
- **Some seed board tokens are best-effort**: run
  `opportunity-radar companies validate` after install; `companies discover`
  re-fingerprints failures.
