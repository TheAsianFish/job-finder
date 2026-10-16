# Task: scout portfolio projects (you are Patrick's technical mentor)

Read, in this order: resume/private/hub/ (ABOUT.md, JOURNAL.md and
projects/: shared memory, his preferences and every project so far),
CLAUDE.md and docs/roadmap.md (ground rules),
reports/skill-demand.md (what employers ask for), resume/private/resume.tex
(what Patrick can already claim; never copy it anywhere public),
resume/private/reports/project-queue.md (projects suggested by per-role
resume reviews; may be absent) and resume/private/projects.yaml (existing
proposals and their status; never re-propose a title already there).

Propose the 3 projects that would most increase his interview rate for
backend, applied-AI, data, infra and full-stack internships at top
companies. He is judged on **technical depth and ATS fit, and he is an
intern**: the projects should show curiosity and go above and beyond while
staying practical, working, and explainable by him line by line. Adoption
numbers and launches are not goals.

**Start from a problem, never from a stack.** Projects chosen from a skills
gap list read as "I used Kafka because the posting said Kafka", and they fail
the interview's first question ("why?"). For each proposal, in this order:
1. **The problem**, in one plain sentence a non-specialist understands:
   whose problem, and why it is hard (e.g. "card transactions must be scored
   within a second, and none may be lost or counted twice while servers
   crash"). Real engineering teams must have this problem; cite where (an
   engineering blog, a postmortem, a paper, an issue tracker).
2. **The questions**: 3-6 questions the project answers by experiment, from
   simple to hard (the curiosity ladder), each ending in a number or a
   demonstrable capability. The first is answerable by milestone 2; the last
   is genuinely open or under-documented. These are what make it curious
   rather than a tutorial.
3. **The stack**, last: only what the problem needs, each choice tied to a
   part of the problem. Then check the fit: which role families and
   top-demand skills (cite counts from the report and which reviewed roles
   asked) it serves honestly.

Use subagents to think: a `fable` subagent proposes problems from real
engineering sources for the thinnest families, another plays a hiring panel
for those teams (recruiter skim, hiring manager, deep-dive interviewer) and
attacks each candidate: is it stack salad, is any part overreach an intern
could not defend, is the core done by milestone 3? Keep what survives.

Each must be buildable by an agent team in 5-8 milestone PRs, on a laptop
and in CI (no paid cloud, no GPU, no credentials), with a measured result
by the second milestone. Differentiate from what exists; no clones of
tutorials. Agentic AI is welcome where the problem calls for it (he likes
it); never bolt an agent onto a problem that does not need one.

The projects form a **pool** (AD-41): the tailor swaps projects and their
bullets per posting, so the pool must cover the role families he applies to
(backend, applied AI/ML, infra/systems, full stack, data), and the keywords
those postings screen for. Map the pool first: which families and top-demand
skills do the existing projects (building, approved, done) already
cover, and which are thin? Then find problems in the thinnest families. Two
projects in one family are fine when they attack different problems.

Write `resume/private/reports/project-scout-<YYYY-MM-DD>.md` (your reasoning,
under 800 words) and `/tmp/scout.json`:
{"projects": [{"title": "...", "slug": "kebab-case",
  "problem": "one plain sentence: whose problem, why it is hard",
  "questions": ["simple question -> the number it produces", "...", "hardest, open question"],
  "pitch": "2 sentences: what it does about the problem",
  "why": "where real teams hit this (sources) + demand evidence + gap closed",
  "skills": ["..."], "stack": ["each one needed by the problem"],
  "release": "how anyone runs it (package, CLI, Docker/Helm, Action)"}]}
Do not edit projects.yaml yourself and do not create repositories. Finally
record what you proposed and why:
`uv run opportunity-radar hub log "scout" "<2-4 lines>"`.
