# Project builder: agent-built portfolio projects

Projects are the main signal internship screeners use to judge whether
Patrick can do an AI-leaning SWE role. This pipeline turns that into
background work on his Max plan, with Patrick deciding what to build and
approving every step. Decision record: AD-32.

## The loop

```mermaid
flowchart LR
  S[Scout · Fable · weekly] -->|3 proposals + Discord| P{Patrick approves any}
  P --> C[Create repo TheAsianFish/slug · private]
  C --> PL[Plan · Fable · PR with PLAN.md]
  PL -->|Patrick merges / comments| B[Build next milestone · Opus + subagents]
  B --> R[Independent review · Fable · fixes + verdict]
  R -->|pass| BU[Bullets · Fable · PR in career-private]
  R -->|one PR + Discord| W{Patrick}
  W -->|comments| A[Address · Opus, then Fable review]
  A --> W
  W -->|merge| B
  B -->|all milestones merged| E[Evolve · Fable · run it, add ≤3 measured milestones or none]
  E -->|reviewed plan PR| W
  E -->|nothing clears the bar, or 2 rounds done| F[Finish · release readiness + resume entry]
  F -->|PR in career-private, numbers from RESULTS.md only| V{Patrick merges = true}
```

- **Several projects side by side, one open PR each (AD-41).** Every
  approved project is in the pool. Each run picks one: an autopilot merge or
  a CI re-run first (no session needed), then the first project, in
  `projects.yaml` order, that has work. A project waiting on its PR never
  stalls the others. Sessions still run one at a time (one workflow
  concurrency group), so Max usage stays sequential.
- **Autopilot (opt-in per project).** With `autopilot: true` in
  `projects.yaml`, a PR that passed the Fable review (a hidden `<!-- review:
  pass -->` marker in its body; the review itself is private), has green CI, and had no activity for 5 hours (one Max usage window) is
  merged by the builder. Off by default. A review that writes no verdict is
  run once more; if it still writes none, `#projects` says autopilot won't
  merge that PR.
- **Wake-up (AD-35).** The ~10-minute scan chain starts the builder as soon as
  it has work (your merge or comments, an autopilot merge, the next
  milestone) and posts what it started to `#projects`.
- **Cadence.** A builder step every 3 hours (`17 */3 * * *`, unreliable on
  GitHub, hence the wake-up above), a scout run on Mondays 09:00 PT, a study
  pack on Sundays. Hard caps: Opus build ≤ 230 min, Fable review ≤ 70 min.
  Replay's M1 (scaffold, CI, first vertical slice, review) took 49 minutes.
- **Red CI (AD-40).** A failed run is first re-run once (outages and flaky
  jobs). If it fails again, the builder goes back to fix it (Opus, with the
  failed jobs' log, then the review), at most twice per PR, counting sessions
  that crash (`ci_fix_started` in `projects.yaml`). After that the PR waits
  for Patrick. Before 2026-10-13 a red check left the
  PR waiting silently (Replay M5 sat 3 days on a CI cleanup timeout).
- **Saved work.** If a session fails (usage limit, timeout, a review that
  dies after a good build), its commits are pushed to the `dev/` branch
  without a PR, and the next run continues from them (AD-39).
- **Progress pings (AD-36).** While a session runs, `#projects` gets a line
  every 20 minutes (elapsed time, commits, latest commit, files changed);
  two quiet intervals are flagged as possibly stuck.
- **Notifications.** When a PR opens, `#projects` says whether autopilot will
  merge it (review passed) or it needs Patrick; `#study` links the private
  study notes for that run.

## Authorship (AD-34)

Everything in a project repo reads as Patrick's own work: commits authored
and committed as TheAsianFish (commit-msg hook strips attribution lines),
`dev/...` branches, first-person PR text, CONTRIBUTING.md instead of a tracked
CLAUDE.md (copied to an untracked one for sessions), no mention of AI
authorship or of Patrick in third person. Agents commit often, one logical
step per commit. All teaching, "his piece", review notes and the verdict stay
private: `.agent/learn.md` and `.agent/review.md` are saved to
`career-private/study/<slug>/<date>-<stage>.md` and announced in `#study`.

## What Patrick does

| To... | Do this |
|---|---|
| Approve a proposed project | Actions → **Project builder** → Run workflow → `approve`, project `<slug>` (GitHub app works), or set `status: approved` in `resume/private/projects.yaml`, or `uv run opportunity-radar projects approve <slug>` |
| Request changes | Comment on the agent's PR (any comment counts; addressed next run) |
| Continue | Merge the PR |
| Stop / never build | `pause` / `reject` the same way |
| Get new ideas now | Run workflow → `scout` |
| Let it run unattended | `autopilot: true` on that project |
| Publish / deploy | Follow the project's `RELEASE.md` (agents never sign up for services or use credentials) |

## Models and roles

| Stage | Model | Why |
|---|---|---|
| Scout, plan, review, finish, study | Fable 5.1 (`--model fable`, falls back to Opus) | Most capable: research, architecture, a demanding review that re-runs tests/evals, and the resume entry, results write-up and interview prep |
| Build, address comments | Opus 5.5 (`--model opus`) | Long agentic coding sessions |
| Subagents (any stage) | Chosen per task | `fable` for hard reasoning and adversarial verification, `opus` for big implementation, `sonnet` for routine well-specified work, `haiku` for search and CI/log triage; as many or as few as the work needs (`standards.md`) |
| Replay/Kiln's own model calls | Cheapest that answers | No API key in sessions (AD-39), so live evals are harness-only for now; the model per call is recorded in RESULTS.md |

All prompts live in `agents/prompts/projects/` and start with
`standards.md` (the quality bar: real users, depth over breadth, measured
claims only, production engineering, AI stack used well, no AI attribution).

## Safety and privacy

- The build job never checks out the private career repo; sessions get only
  a skills summary. The resume stays private.
- `AGENT_GH_TOKEN` is used in clone/push/PR steps only. The Claude sessions
  run with credential-free remotes and only `CLAUDE_CODE_OAUTH_TOKEN` (Max
  plan) in the environment, so an agent cannot push, create repos, or touch
  other repos. **Never give the sessions `ANTHROPIC_API_KEY`**: Claude Code
  uses an API key in preference to the Max token, so every session gets billed
  to the key (AD-39: ~$197 of credits went in two days). `project_agent.sh`
  strips every API-key and cloud-provider variable and refuses to start
  without the Max token. Evals that need a live model ship as harness-only until a
  separate, explicitly approved way to fund them exists. `keycheck` still
  tests the `PROJECTS_ANTHROPIC_API_KEY` secret (one 1-token call).
- `AGENT_GH_TOKEN` (fine-grained PAT, all repos) needs read/write on
  Contents, Pull requests, Administration (create repos) and Workflows, plus
  **read** on Actions and Commit statuses: the builder reads a PR's CI result
  before it decides anything (from the PR's checks, or from the Actions runs of
  its head commit when the token can't read check runs). If any step can't decide, `#projects` gets a
  "needs attention" message (repeats at most every 3 hours until fixed).
  **Actions: write** lets it re-run a red PR's failed jobs once before
  spending a fix session (AD-40); without it the builder goes straight to
  the fix.
- A `commit-msg` hook strips AI attribution; commits are authored as
  TheAsianFish.
- This repo is public, so workflow logs print stages and run statistics only.
  GitHub prints every step's env values, so the run context (hub, skills)
  and the sessions' private outputs (resume entry, talk tracks, study notes)
  travel between jobs encrypted with the `PAYLOAD_KEY` secret
  (`scripts/seal.sh`, AD-43) and are read from files, never from env.

## Usage governor (AD-42)

The builder never eats the Claude Max allowance. Before each decision it
reads the plan's real meters: one one-word Haiku call in stream-json
(`scripts/usage_probe.sh`) returns the 5-hour and 7-day utilization. It then
scales how many projects may start sessions, like an autoscaler:
- **4 projects** while the 7-day meter is well behind a straight-line pace to
  85% at the weekly reset, stepping down to **1** as it catches up, and **0**
  past the pace, at the 85% ceiling, or while a limit is hit.
- **The 5-hour window:** one project above 50%, none above 80%, so your own
  sessions always have room.
- Merges and CI re-runs always go through.

Every run is recorded in the private `usage/builder.jsonl`.
`uv run opportunity-radar projects usage` shows the meter, the current
capacity, spend per project, and how many more runs fit this week.

## Problem first, evolving plans, steering (AD-44)

- **Problem first.** Each project in `projects.yaml` has a `problem` (one
  plain sentence) and `questions` (experiments from simple to hard, each
  ending in a number). The scout writes them before choosing a stack, and
  plans open with them. A technology is only there if the problem needs it.
- **Evolve.** When a plan's milestones are all merged, an evolve session runs
  the project and asks whether the results justify going further: a weak
  number, an unanswered question, a harder version of the core problem.
  Subagents propose candidates and another argues against each. Up to 3
  milestones that clear the bar (deepen the core, measured, practical, one
  PR) are added to PLAN.md in a reviewed PR that autopilot can merge, so you
  have 5 hours to comment. If nothing clears the bar, the project finishes.
  At most 2 rounds per project.
- **Steer.** `uv run opportunity-radar projects steer <slug> "direction"`
  adds a direction every later session on that project must follow
  (`--clear` drops them; no text lists them). Use it to redirect a project
  between PRs.

## Resume bullets during the build (AD-41)

After every milestone whose review passes, a Fable session writes the
project's entry from what is built and measured so far:
- **`.agent/RESUME.tex`:** 4-6 STAR bullets, each a different achievement
  (core system, evals, backend, infra, frontend...), so the tailor can choose
  per posting.
- **`.agent/BULLETS.md`:** a talk track for each bullet: situation, action
  with the rejected alternative, how the number was measured, follow-up
  questions, and the role families it fits.

Rules are in `agents/prompts/projects/bullets.md`: numbers from RESULTS.md
only, no buzzword slop, every named skill used in the code. Each milestone
starts from the previous version and your comments on the bullets PR, and an
independent reviewer that reads the code then cuts or rewrites anything a
recruiter, interviewer or editor would reject (AD-45; verdict at the top of
the PR, critique in `prep/<slug>-bullets-review.md`). `projects bullets`
puts the entry in one private PR per project (`projects/<slug>-bullets`,
updated by later milestones; the talk tracks go to `prep/<slug>-bullets.md`)
and pings `#resume`. Merging that PR adds the project to the pool now. The
finish stage still opens the final PR with the mock-interview gate.

## Truth

A project reaches the resume only through a pull request in the private repo
that adds it as a commented-out (reserve) entry (or updates the entry already
there). The builder flags any number
in its bullets that does not appear in the project's `RESULTS.md` (measured
by a real run), and merging means "this is true". Patrick should be able to
explain every line; the private study notes for each milestone
(`career-private/study/<slug>/`), the Sunday study pack and the mock interview
written at the finish stage are how he learns the codebase.
