# Roadmap: from job tracker to internship copilot

**Goal:** maximise the number of SWE internship offers Patrick lands, by
finding roles first, applying with the strongest truthful resume, and closing
real skill gaps. Every agent working in this repo should read this file and
`CLAUDE.md` first.

## Candidate facts (source of truth: `config/profile.yaml`)

- UCSD Computer Science, **BS**, graduating **December 2027**. US citizen, no
  sponsorship needed.
- Current focus: **internships** (Summer 2027 plus off-season Fall 2026 /
  Winter / Spring 2027). New-grad search is paused.
- Not eligible for PhD/Master's/MBA-only roles; those are filtered out.
- Priorities (2026-10-08): Winter/Spring/Summer/Fall 2027 internships first;
  Fall 2026 lower. Backend, AI backend, AI/ML, full stack. FAANG+ ideal;
  startups fine if they fit and pay reasonably (pay is a gentle nudge;
  missing pay is neutral). Any US location (remote, hybrid, onsite).
- Full-time roles are welcome when aligned: entry-level, start Fall 2027 or
  later; he can graduate as early as Aug 2027 (AD-27).

## Ground rules for every agent

1. **Truthful only.** Rewording and reordering real experience is fine.
   Inventing skills, metrics, titles or projects is never acceptable. A
   stronger bullet that needs an unwritten fact is *proposed* to Patrick (a
   PR in the private repo); merging it means "this happened" (AD-31).
2. **No auto-applying** and no logging in to job sites (spec hard rule).
3. **Changes land as pull requests** for Patrick to review; agents never
   push to `main` or touch `.env` / secrets.
4. **Data over vibes.** Claims about what works must cite this repo's data
   (job descriptions, `reports/`, application outcomes) or a named source.
5. Keep `docs/` and `CLAUDE.md` current when behaviour changes.

## Phases

| # | Phase | Status | Notes |
|---|---|---|---|
| 1 | Skill and ATS-keyword demand report | **Done** (2026-10-07) | `opportunity-radar insights skills` -> `reports/skill-demand.md`; vocabulary in `config/skills_vocabulary.yaml` |
| 2 | Master resume ingestion | **Done** (2026-10-08) | `resume.tex` in the private repo is parsed into a bullet bank (live + commented reserves); profile skills synced from it; `resume bank` shows it |
| 3 | Per-posting match + tailored versions | **Done** (2026-10-08) | Keyword line on every alert; fit checks on important new roles with a hiring-panel review (recruiter, hiring manager, interviewer + ATS check, lead synthesises ranked changes; AD-37) + STAR-rewritten PDF only on a real disconnect (AD-29); `resume assess` / `resume tailor` / dashboard buttons; weekly role-family `variants/`; ATS report |
| 4 | Outcome loop | **Live** (Simplify CSV import + `apply`; needs logged applications) | `apply <url>` auto-records the tailored resume made for that role (AD-37); `jobs applied <id> --resume <version>`, `jobs status <id> oa\|interview\|offer\|rejected`, `insights outcomes` -> `reports/private/outcomes.md` (tier, role, season, resume version, project shown, panel vote, referral, source, apply speed); `lessons()` feeds that evidence to the next resume review. Needs logged applications |
| 5 | Agent-built portfolio projects | **Live** (2026-10-08) | `projects.yml` (AD-32, `docs/project-builder.md`): Fable scouts 3 projects weekly from demand + per-role reviews; Patrick approves one; the builder plans (Fable), builds one milestone (Opus + per-task subagents), has it reviewed (Fable) and opens a PR in the project's own repo, started within ~10 min of a merge by the scan chain (AD-35); his comments are addressed next run; repos and commits read as his own work, teaching stays private (AD-34); when done, the resume entry (measured numbers only) is proposed to the private repo. Active: Replay (`TheAsianFish/agent-replay`, autopilot), then Kiln |

## Autonomous agents

- **Scanner:** `.github/workflows/scan.yml`, self-chaining every ~10 min (no AI).
- **Agents:** `.github/workflows/agents.yml` runs Claude Code headless on
  Patrick's Max plan (`CLAUDE_CODE_OAUTH_TOKEN` secret from `claude setup-token`),
  gated by the `ENABLE_AGENTS=true` repo variable. Weekly review on Mondays plus
  manual runs with a custom prompt. Prompts live in `agents/prompts/`.
  Output is a pull request.
- **Project builder:** `.github/workflows/projects.yml` (ENABLE_PROJECT_BUILDER=true),
  scout weekly, builder woken by the scan chain (plus a 3-hourly cron), study
  pack Sundays; see `docs/project-builder.md`.

## Where things live

- Public repo (this one): code, docs, aggregate reports (`reports/skill-demand.md`).
- Private repo `TheAsianFish/career-private`, cloned at `resume/private/`:
  `resume.tex` (source of truth), `verified.yaml`, `applications.yaml`,
  `projects.yaml`, `tailored/`, `variants/`, `reports/`, `prep/`, `study/`
  (per-milestone notes), `hub/` (ABOUT, JOURNAL, project summaries).
  Never copy anything from it into the public repo or public CI logs.

## Current skill-gap snapshot

See `reports/skill-demand.md` (regenerated by the weekly agent run).
