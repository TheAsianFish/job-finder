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

## AD-16: Enterprise ATS adapters on verified per-site JSON, not placeholders

Spec §8.8 lists Workday/SmartRecruiters/Eightfold as "placeholder +
documentation" but explicitly allows "a company-specific adapter or
configurable fetch strategy with tests" once "a stable public JSON request
is discovered". Every FAANG+ seed sat disabled behind those placeholders,
which defeated the registry's purpose. Verified 2026-10-06:

- **Workday**: every tenant serves `POST /wday/cxs/{tenant}/{site}/jobs`
  (list + facets) and `GET …{externalPath}` (detail) to its own job-list
  page. The adapter keeps itself narrow: early-career facets
  (`workerSubType = Intern / New College Graduate`, `jobFamilyGroup = Univ
  Employment`) are discovered per tenant from the first response, so only
  that subset is paged; a `searchText` fallback with title filtering covers
  tenants without such facets; detail GETs are capped; the whole thing
  honours robots.txt; any shape change raises (never an empty list).
- **SmartRecruiters**: the Posting API *is* documented and public; the
  placeholder was simply wrong. Zero `totalFound` is a config error.
- **Eightfold** (Netflix), **amazon.jobs**, **github.careers**,
  **atlassian.com/endpoint/careers/listings**: single-site JSON endpoints
  the pages themselves consume. Each is its own small adapter rather than
  a "generic JSON mapper" config, because YAML field-mapping DSLs are
  harder to test and debug than 80 lines of Python with a fixture.

Large boards get an **early-career pre-filter** at the adapter (shared with
the classifier's title rules) because each posting costs a detail request;
Greenhouse-style single-payload boards are still stored whole.

## AD-17: Per-source baseline, not just per-database

Spec §14.1 says a first run must never flood. The guard only checked
"database empty", so adding 80 companies to a live registry would have
fired hundreds of immediate alerts. A source with no prior successful scan
and no stored jobs is now baselined on its own (`is_baseline=True`, no
alert classification) and summarised once in a "new sources imported"
embed listing its best open matches — the backlog is visible, the channel
is not flooded.

## AD-18: Digest fairness over pure score order

A core-tier board with 2,400 postings (Anduril) produces more
above-threshold intern variants per scan than the digest's 10-line section
could show, so every digest read as "Anduril, Anduril, Anduril". Sections
now cap each company at three lines (best first) and summarise the rest on
one line; long sections chunk across embed fields rather than truncating a
Markdown link mid-URL. Score still orders within the cap.

## AD-19: robots.txt matching follows RFC 9309, not `urllib.robotparser`

The stdlib parser applies rules in file order, so Netflix's
`Disallow: /` followed by `Allow: /api/apply` read as "disallowed" even
though the site explicitly opens its job JSON. RFC 9309 (and Google's
documented behaviour) use longest-match with Allow winning ties; a
60-line matcher implements exactly that, with tests. Vendor APIs with
their own documentation (Greenhouse, Lever, Ashby, SmartRecruiters) are
polled as APIs and not subjected to robots checks, matching the spec's
distinction between crawling pages and calling public ATS APIs.

## AD-20: Off-season windows are first-class and self-expiring

Target windows gained `fall_2026` and `winter_2027`; the scorer ignores
any window whose end date has passed, so stale YAML never keeps rewarding
a season that is over. A Summer-specific immediate-alert override mirrors
the existing off-season one (core/strong, explicit season, start still
ahead), and the immediate bar dropped 82→78 (audited in
`tuning_history`): the user asked for *more* Summer and off-season
internships, and the data showed strong-tier Summer 2027 SWE intern roles
with thin descriptions stalling at 78–81.

## AD-21: Simplify lists as a secondary source, employer boards stay primary

Spec §28 allows public GitHub internship lists as secondary signals. The
SimplifyJobs lists are published as structured JSON
(`.github/scripts/listings.json`) on raw.githubusercontent.com, which serves
no robots.txt and a 5-minute CDN cache, so they are polled as data files,
not scraped pages. Their value is coverage we cannot reach directly
(Google, Meta, Apple, Microsoft, Tesla, Citadel, SIG, ~1,600 long-tail
employers), not speed on employers we already poll.

- Each posting is resolved to a company: apply-link board token first
  (immune to naming differences), then normalised name / alias / multi-word
  prefix, else a synthetic `enabled: false` company at the source's tier.
- **Employers the registry scans directly are skipped**, so a posting never
  alerts twice and the employer board remains the source of truth.
- Listings have no description; the adapter writes one sentence per listing
  field (terms, category, degrees, sponsorship). Nothing is inferred, and
  "Summer 2027" in the terms reaches the season parser at 0.9 confidence.
- Stored jobs carry `source_name = <list id>`; closure and per-source
  baseline are scoped by source, so retiring a Simplify row closes only
  that row, and a company fed by two sources never has one close the
  other's jobs.

## AD-22: Ten-minute hot cadence; parallel slots for documented API hosts

GitHub schedules fire at best every few minutes, and a full registry scan
took ~14 minutes because ~110 Greenhouse boards shared a one-slot gate on
`boards-api.greenhouse.io`. Two changes:

- Documented job-board API hosts (Greenhouse, Ashby, Lever,
  SmartRecruiters, raw.githubusercontent) get 2–4 concurrent slots with a
  0.25–0.5 s start-to-start gap; employer-hosted sites keep one slot / 1 s.
- `scan --mode auto` (cloud, every 10 minutes) runs the full registry when
  the last full scan is about an hour old, otherwise the hot set: core-tier
  employers plus the Simplify feeds. Every run is one job in one
  concurrency group with one SQLite state, so there is no duplicate-alert
  risk from overlapping workers.

## AD-23: Unchanged postings skip re-normalisation; no same-board merges

A cloud full scan took 24 minutes. Profiling showed almost none of it was
network: every scan fully re-classified, re-scored and re-hashed every
stored posting (twice for existing ones) while holding the database lock,
so Anduril's 2,474 unchanged jobs cost 96 s of CPU and every other source
queued behind it.

- `jobs.raw_hash` fingerprints the adapter payload plus everything that
  changes scoring (profile, scoring config, title rules, company tier,
  `NORMALIZATION_VERSION`, UTC date). Equal hash ⇒ fast path: last-seen,
  miss counter, freshness points and the "First seen" reason are updated
  exactly as a full re-score would; nothing else is recomputed. Any config
  or code change, or a new day (target windows can expire), re-scores
  everything once. Bump `NORMALIZATION_VERSION` when matching code changes.
- Existing postings are normalised once, not twice; classifier terms use a
  literal pre-check before the regex (identical results on 5,000 real jobs,
  6× faster).
- Profiling also exposed rows merged before AD-14: two Anduril
  requisitions sharing one row via a stale identity alias, overwriting each
  other every scan (~50 bogus "changed" rows per scan). The AD-14 rule now
  applies to every alias kind: the same adapter with different concrete
  job IDs never merges. Legacy merges are split out once, quietly
  (`is_baseline`, no alert).

Anduril persist: 96 s → 0.6 s at steady state.

## AD-24: Self-chaining cloud scans; cron only as a restart fallback

GitHub delays and drops scheduled workflows on low-activity repos: the
hourly cron here fired about four times a day, and a new `*/10` cron fired
zero times in its first 40 minutes. Polling cadence cannot depend on it.
Each run therefore dispatches the next one when it finishes (the workflow
token may trigger `workflow_dispatch`), sleeping first so consecutive runs
start `CHAIN_MIN_INTERVAL_SECONDS` (default 600) apart. The chain step runs
even when a scan fails, so one bad run does not stop polling; the cron
restarts the chain if a run dies before reaching that step. One concurrency
group keeps a single writer for the SQLite state, and old DB caches are
pruned to the newest three. Stop: `gh variable set CHAIN_SCANS --body false`.

## AD-25: Graduate-degree-only roles are excluded; internships first

Patrick (BS, Dec 2027) cannot apply to PhD/Master's/MBA-only roles, and
they were reaching notifications because intern titles bypass the normal
title exclusions. A title naming PhD/doctoral/postdoc/Master's/MBA (or "MS"
inside a degree list such as "(MS)" or "MS/PhD") is now hard-excluded even
on intern titles, unless it also opens the role to undergraduates ("BS/MS",
"Bachelor's", "UG"). Simplify listings whose own degree field lacks
Bachelor's are dropped at the adapter. Live sample: 230 of 7,541 active
early-career jobs excluded, no false positives in review ("MS Teams" and
"Southaven, MS" are kept). `NORMALIZATION_VERSION` 2 re-scores stored jobs.
The Simplify new-grad feed is disabled while the focus is internships.

## AD-26: Patrick's stated priorities encoded in scoring, not prose

2026-10-08: internships only; Winter/Spring/Summer/Fall 2027 first; backend,
AI backend, AI/ML, full stack; any US location; startups need reasonable pay
unless remote or a brand name compensates. Encoded as: `internships_only`
gates alerts and every digest section (full-time roles stay dashboard-only;
an internship is an intern/co-op title, a season+year title, or an
internship-list row); target-window priorities (fall_2026 55, 2027 seasons
95-100, new grad 40); role weights (ml_systems 20, fullstack 19, embedded 8);
empty `preferred_locations` = any US location scores full; and a posted-pay
component (-8..+4) parsed only from explicit "$X-$Y per hour/year" text,
with low pay softened for remote roles and core/strong employers. Profile
skills are synced from the resume and drive a have/missing keyword line on
every alert. Disabled sources no longer raise silent-source warnings.
`NORMALIZATION_VERSION` 3 re-scores stored jobs. All changes audited in
`tuning_history`.

## AD-27: Full-time roles by alignment, not a blanket ban

2026-10-08 (Patrick): full-time roles are welcome if they fit his timeline;
he could graduate early (after Summer 2027) and start Fall 2027 or any time
from early 2028. `preferences.full_time_roles` (`never | aligned | always`,
default `aligned`) replaces the earlier internships-only switch. A full-time
role notifies only with an explicit entry-level signal (title, or a strong
description phrase such as "new grad" / "recent graduates"; a stray
"university" in boilerplate does not count), no 2+ years of required
experience, no target class earlier than his (catches "New College Grad
2026"), and no stated start before `full_time_earliest_start` (2027-08-01).
`candidate.earliest_graduation` makes graduation windows an overlap test
against Aug-Dec 2027. Posted pay became a gentle nudge (-3..+3) because many
postings omit or misstate pay; missing pay is always neutral. Jobs from
sources disabled in the registry are now closed, since nothing could ever
re-confirm or close them otherwise.

## AD-28: Adaptive resumes from the user's own LaTeX, behind a guard

The resume source of truth is Patrick's `resume.tex` (Jake's template),
kept in a **private** repo (`TheAsianFish/career-private`, cloned at
`resume/private/`, read/written by CI through a write deploy key in the
`CAREER_DEPLOY_KEY` secret). Commented-out entries are the bullet bank;
lines commented twice are superseded wordings and ignored.

Tailoring is deterministic first: real jobs always stay; the first live
project (the flagship) always stays and leads; flexible slots and other
projects go to the best-matching bank entries, and a reserve entry must beat
a live one by a margin; one venture never appears twice; a live entry's
opening summary bullet stays first; skills lines keep every item but lead
with the posting's; total bullets never exceed the master's, and pdfLaTeX
recompiles with trimming until one page. Engine: real pdfLaTeX (TinyTeX,
no sudo) because the template uses pdfTeX primitives and must match the
Overleaf output exactly.

Optional polish runs Claude Code headless (`claude -p`, so the Max plan,
not an API key). Every rewrite passes a guard or is discarded: no number
absent from the original bullet, no vocabulary skill absent from the bank,
no capitalised name or acronym absent from the bank, length within
60-120%. The ATS report separates matched keywords, ones the bank has but
the page doesn't show, and true gaps that must not be claimed.

Delivery: cloud scans tailor a resume for each fresh immediate alert (at most
five per run), attach the PDF to a Discord message beside the alert, and
archive `.tex`/PDF/ATS/meta in the private repo. Public CI logs print counts
only. The applications log (`applications.yaml`) lives in the private repo,
is synced into the DB every scan (outcomes, digest exclusions), and is
written by `opportunity-radar apply` / `jobs status`, which commit and push.

## AD-29: Resume checks, not resume spam; stories, not keyword sprinkles

Patrick's feedback on the first tailored resume (2026-10-08): bland, and not
needed for that role. Two changes.

**Assessment-gated checks.** A fresh immediate alert at a core/strong
company in a target role family gets a deterministic fit assessment of the
standing resume (fetching the full description from Greenhouse / Lever /
Ashby / Workday when the role came from the Simplify list). Severity
`fits` is silent. `tune` needs a concrete fixable issue (material the
resume hides, a clearly better reserve entry, measurable lift) or two
independent weak signals; `gap` means the role centres on a skill the
resume genuinely lacks. Calibrated on 227 alert-grade target roles: 94%
silent. Flagged roles get Claude's candid review (weak bullets with fixes,
project and culture fit, competitiveness, swaps, a new-project proposal
appended to the private `reports/project-queue.md`) plus a tailored
resume, in one Discord message with the PDF and `review.md`.

**Story rewrites.** The writer now rewrites whole entries with the job
description, the reviewer's fixes, and explicit direction: technical
STAR/XYZ stories, precise engineering vocabulary, restructure don't
paraphrase. Reviewer-recommended reserve swaps are applied by the
selector. Truth stays mechanical: numbers must exist in that entry's
facts, skills in the resume, names/acronyms in the resume (plus generic
engineering acronyms), and each entry keeps its original length budget so
the page never forces content out. On overflow, rewrites are undone
before content is trimmed; rewrites that lose keywords versus the same
selection are undone.

**Applications from Simplify.** The Simplify Job Tracker's official
Export CSV is imported (`applications import-simplify`, or drop it in the
private repo's `imports/`; every scan merges it). Matching is by link,
else company + title; status only moves forward. MyGreenhouse has no
export or API; logged-in scraping is out of scope.

## AD-30: Every alert carries a resume verdict; reviews on demand; strong tier hot

- Alerts gain a "Resume" line computed deterministically at send time:
  ✅ fits (apply as-is), ⚠️ worth tuning, 🛠️ gap, or ❔ not assessed (no
  full description stored). Silence after an alert used to be ambiguous
  ("fits" vs "never checked"); now the decision is on the alert itself.
- `resume review-url <link>` and the `review-role` agents task (runnable from
  the GitHub mobile app) give a forced, brutally honest review + tailored PDF
  for any Greenhouse/Lever/Ashby/Workday posting, tracked or not.
- Strong-tier companies join the 10-minute hot set (core was there already).
  Observed 2026-10-08: DoorDash's "Software Engineer, Intern - Labs (Summer
  2027)" has Greenhouse first_published 02:50 UTC but was absent from the
  public board API at 06:29 and present at 07:30 (detected then). ATS
  "published" timestamps can precede public visibility; "Detected" in alerts
  is when we first saw it publicly, now within ~10 minutes for core/strong.
- Alert fields renamed: "First seen" -> "Detected" (our detection time),
  "Posted" -> "Posted (per ATS)".
- Tests run against an empty private dir by default (autouse fixture), so a
  developer's real resume never influences results.

## AD-31: Fixed experience, free projects; stronger bullets need Patrick's word

Patrick's direction (2026-10-08): keep experience as written, reshuffle
projects per role, prioritise passing the ATS, and let the writer drop a
weak bullet or write a brand-new, stronger one. When a stronger bullet needs
a fact that is not written down, ask him instead of either inventing it or
silently giving up.

- **Selector.** Every live experience entry appears, in date order, and
  commented-out experience never swaps in (only bullets vary). Projects have
  no protected anchor any more: every slot goes to the best live or reserve
  project (reserves still need a margin), ordered by relevance.
- **Writer.** May write one bullet fewer than shown for entries with 3+
  bullets, may use any fact of the entry (reserve and verified included),
  and is told to mirror the posting's exact terms (acronym plus expansion
  where the posting uses the long form, key terms first). No keyword
  stuffing: the guard and a human reader both check.
- **Proposals.** The writer returns bullets it believes are stronger but
  that need an unwritten fact as `proposals`, each with the specific facts
  to confirm; bullets the guard rejects for an unknown number, skill or name
  become proposals too. They never reach a resume directly. Per role,
  fresh ones (never proposed before, not already verified:
  `proposals/log.yaml`) go to one pull request in the private repo that adds
  them to `verified.yaml` plus an interview prep sheet (`prep/`: how it
  works, trade-offs, likely follow-ups, numbers to know). Merge = true (edit
  first to correct; delete a block to reject one); close = reject all, never
  asked again. Discord gets a ping with the PR link. Without a token or `gh`
  the same content is saved to `proposals/pending/`.
- **Verified bullets** load beside `resume.tex` as extra facts of their
  entry: the selector may show one in place of a weaker live bullet (never
  growing the page budget) and the guard accepts their numbers and names.
- **Approval means "this happened"**, not "I could do this". Skills not yet
  practised go through the project builders (AD-32) first.
- **Token.** `AGENT_GH_TOKEN` (fine-grained PAT, TheAsianFish, all repos:
  administration, contents, pull requests, issues, workflows) is passed to
  the resume steps as `CAREER_GH_TOKEN` for `gh pr create` in the private
  repo. Pushes still use the deploy key.
