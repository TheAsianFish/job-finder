# Proposal (draft): YC Spring/Off-Season Radar

**Status: draft — nothing here is wired into the pipeline.**
Goal: never miss a good off-season (especially **Spring 2027**) SWE
opportunity, with YC startups as the primary flexible-employer pool.
Patrick already reads the Simplify repos manually, so this must add
coverage *those lists miss* without adding notification noise.

## Why YC + spring

- Off-season postings are rare and structurally under-tracked: Simplify's
  off-season list carries ~182 SWE roles total (Aug 2026) vs ~355 for
  summer. Startups often *don't* post "Spring 2027 Intern" — they post a
  generic "Software Engineer Intern" year-round and are flexible on dates.
  That means the win is *watching flexible employers continuously*, not
  keyword-matching "spring".
- YC companies skew engineering-led, hire young, move fast, and mostly use
  pollable ATSes (Ashby heavily in recent batches, plus Greenhouse/Lever) —
  a perfect match for the existing adapter stack.

## Data source (verified 2026-08-13)

`yc-oss/api` (github.com/yc-oss/api): unofficial but purpose-built public
JSON dumps of the YC directory, regenerated daily by GitHub Actions from
YC's own Algolia index — no scraping on our side, one HTTPS GET.

- `https://yc-oss.github.io/api/companies/hiring.json` — companies with
  active YC job listings. **1,484 hiring today; 1,237 US-region.**
- Fields we can filter on: `regions`, `industry`/`industries`, `tags`,
  `team_size`, `batch`, `top_company`, `website`, `one_liner`, `isHiring`.

## Options considered

### A. Registry expansion via auto-discovery (recommended core)

Pipeline (a periodic script, not a new subsystem):

1. Pull `hiring.json` (one request, daily at most).
2. Filter: US region · software-ish industry/tags · `team_size >= 10`
   (below that, internships are word-of-mouth, not posted) · skip domains
   already in `companies.yaml`.
3. Run the **existing** `discovery.career_links.discover()` on each
   candidate domain (robots-respecting, few requests, already rate-limited)
   to fingerprint Greenhouse/Lever/Ashby boards.
4. Emit draft `companies.yaml` entries (tier `exploratory`, tags
   `[yc, yc-<batch>]`, `enabled: false`) into a review file —
   **never auto-registered**; Patrick reviews and pastes in what he wants.

Capacity math: exploratory tier scans every **360 min**, so even +200 YC
sources ≈ 13 extra requests/hour cloud-side — well within politeness
budget. Discovery itself is ~3-5 requests per domain, run once (and
re-run via the existing weekly `companies repair` for drift).

Draft implementation: `scripts/yc_discover.py` (in this repo, standalone,
safe to run; writes `data/yc_candidates.yaml`, which is gitignored).

### B. Spring/off-cycle alert promotion (one-line scoring change)

Today the "explicit off-season role → immediate alert" override in
`decide_alert_level` only fires for **core/strong** tier. YC startups
would be exploratory, so a genuine "Spring 2027 SWE Intern" at a YC
company lands in the digest at best. Because off-season postings are
globally rare (≈180 SWE at any time across *all* companies), promoting
explicit winter/spring/off-cycle SWE roles to immediate for **any** tier
is inherently noise-bounded — likely a few alerts per month.

### C. Weekly "Off-season spotlight" digest section

Once a week (e.g. Sunday morning digest), list every *active* role with
season ∈ {off_cycle, winter, spring} and score ≥ dashboard bar — a
bounded recap so nothing rots unseen in the dashboard band. Zero extra
notifications the other 13 digests of the week.

### D. Work at a Startup (workatastartup.com) — rejected

YC's own job board would be the direct source for YC *roles* (not just
companies), but role search is login-gated and has no public API;
polling it would violate the no-login/no-undocumented-endpoints rules.
The yc-oss company list + company-side ATS polling gets the same roles
from the employers' own public boards instead.

## Recommendation (when/if we build)

**A + B together**, C optional later:

- A gives the coverage: the flexible employers themselves, polled cheaply.
- B gives the guarantee: when an explicit spring/off-cycle SWE role
  appears anywhere in the registry, it pings immediately instead of
  waiting for a digest slot.
- Rollout: run `yc_discover.py`, review the draft file, enable ~50-150
  entries (start with `top_company` + recent batches), watch a week of
  digests, then decide on B's one-liner + tests.

## Noise controls (why this won't spam)

- Everything lands at `exploratory` tier: 14 company-quality points, so
  only genuinely on-target roles clear even the 50-point digest bar.
- All existing gates still apply: non-software cap, non-US cap,
  once-per-job alerting, baseline no-flood.
- Draft entries ship `enabled: false`; nothing scans until reviewed.
