# Architecture Decisions

Significant deviations from and interpretations of the master spec, with reasoning.
The spec's own priority order governed every call: **reliability > accuracy >
maintainability > breadth > speed > visual polish.**

## AD-1: Synchronous SQLAlchemy instead of aiosqlite

The spec suggests `aiosqlite`. We use synchronous SQLAlchemy 2.x on `sqlite3`:

- Network I/O (the actual bottleneck) is fully async via httpx; DB writes are
  local microsecond operations on a single-user SQLite file.
- Alembic and sync sessions are first-class and battle-tested; async ORM
  sessions add a class of subtle bugs (lazy-load in wrong context, greenlet
  plumbing) with zero benefit at this scale.
- The scanner serializes DB writes behind an asyncio lock, avoiding SQLite
  writer contention entirely. WAL mode is enabled for reader concurrency.

## AD-2: Custom asyncio scheduler loop instead of APScheduler

The daemon is a plain asyncio loop that ticks every 30 seconds, maintains
per-company `next_run_at` times (tier interval + jitter), and detects
sleep/wake by watching for wall-clock jumps. APScheduler would add a
dependency and its own persistence/timezone complexity for what is, at core,
"scan whatever is due." Catch-up after Mac sleep is inherent: overdue entries
are simply due, and each is scanned exactly once.

## AD-3: Central normalization, thin adapters

The spec's adapter contract includes `normalize()`. Instead, adapters return a
minimal `RawJob` and all enrichment (title classification, season parsing,
eligibility, scoring, explanations, hashing) happens once in
`pipeline/normalizer.py`. Every source gets identical matching behavior, and a
scoring fix never requires touching seven adapters.

## AD-4: Three-tier identity for deduplication

Per spec §6.2, each job registers three aliases: exact source identity
(adapter+company+job id), canonical apply URL (tracking params stripped), and
a fuzzy key of company + normalized title + **city-level** locations.
City-level (not full-string) location keys let an ATS listing merge with the
careers-site copy of the same role ("San Francisco, CA" vs "San Francisco")
while different cities stay distinct. Titles alone never merge jobs.

## AD-5: Closure requires two consecutive *successful* misses

A per-job `consecutive_misses` counter increments only when a successful scan
omits the job; failures never advance it. A source that previously reported
≥5 jobs and suddenly reports zero triggers an anomaly warning and skips
closure processing entirely (likely outage or site migration, spec §22).

## AD-6: Baseline auto-guard

Beyond the explicit `baseline` command, `scan` detects "first run + empty
database + baseline never recorded" and silently converts to baseline mode
with a prominent log line. Alert flooding on first run is impossible, not
merely discouraged.

## AD-7: Playwright is an optional extra

`uv sync` does not install Playwright; `uv sync --extra browser` does. The
adapter degrades to a clear config error with install instructions. Rationale:
the default install stays light, and browser automation is a last resort per
spec §8.7.

## AD-8: Unsupported-ATS adapters are explicit placeholders

Workday, SmartRecruiters, iCIMS, Eightfold, SuccessFactors, and Taleo raise a
structured `unsupported` error explaining the configuration alternatives
(jsonld/sitemap/html_generic/playwright). Spec §8.8 forbids building on
undocumented endpoints; big-tech seed companies using those systems ship
`enabled: false` with notes so a fresh install has zero permanently-failing
sources.

## AD-9: Alert-level decision happens at ingest, delivery is separate

The scanner classifies each new job (immediate / digest / dashboard /
suppress) and records digest-pending state; the Discord notifier is a separate
layer that consumes job IDs, marks `alerted_at`, and refuses to re-alert.
Crash between classify and send can only cause a missed alert, never a
duplicate.

## AD-10: File-based settings, read-only settings page

The dashboard settings page displays loaded config but does not edit it. YAML
+ .env are the single source of truth (versionable, diffable); a write path
from the web UI would need validation, locking, and reload semantics that buy
nothing for a single local user.

## AD-11: CSRF via HMAC of the app secret

State-changing dashboard POSTs require a token derived as
`HMAC(secret_key, constant)`. With a single local user and a
localhost-bound server, this is sufficient to block cross-site form posts;
full session-based tokens would add state without adding protection here.

## AD-12: Season inference never promotes low confidence

`SeasonResult.confidence` is carried end-to-end: 1.0 only for explicit
title season+year; description evidence 0.9; start-month phrases 0.85–0.9;
season-word-without-year 0.7. There is deliberately **no** posting-month
heuristic (spec §11.2's example: a generic November posting stays
"unspecified"). The Discord embed labels anything under 0.9 as "(inferred)".

## AD-13: Conditional HTTP requests deferred

ETag/If-None-Match plumbing between source_state and adapters is scaffolded
(columns exist) but not wired. The ATS APIs polled here return small JSON
payloads at 20-120 minute intervals; the politeness win is marginal against
the complexity of 304-handling in every adapter. Revisit if scan volume grows.

## AD-14: Same-source fuzzy matches never merge distinct requisitions

The fuzzy alias (company + normalized title + location set) exists to bridge
the *same posting* seen through different sources (e.g. Greenhouse API vs
JSON-LD). Real boards also post genuinely distinct requisitions with
identical title and location (shift/team variants — SpaceX's board carried
22 such pairs at last check). Merging those made the stored description
flip-flop on every scan, generating perpetual bogus "changed" rows. Rule: a
fuzzy match is rejected when both records carry different concrete
`source_job_id`s from the same adapter; only cross-source matches may merge
on the fuzzy key. Alias registration skips (kind, hash) pairs owned by a
sibling job, so the first requisition keeps the fuzzy alias.

## AD-15: Cloud scan state lives in the Actions cache, not artifacts

`actions/download-artifact@v4` only sees artifacts of the current run unless
given an explicit `run-id` + token, so artifact-based restore silently failed
and every hourly cloud run re-baselined an empty database — the baseline
no-flood guard then (correctly) suppressed all alerts, forever.
`actions/cache/restore` with a `radar-db-` prefix restore-key matches the
most recent prior run's save, giving rolling continuity with first-party
actions. Cache eviction (10 GB LRU) just causes one silent re-baseline,
which the no-flood guard already makes safe.
