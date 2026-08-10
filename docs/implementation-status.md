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
| 17 | Tests pass | ✅ | 154 tests, offline (respx fixtures) |
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
