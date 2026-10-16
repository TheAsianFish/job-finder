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
backend, applied-AI and full-stack internships at top companies, judged by:
demand evidence (cite counts from the report and which reviewed roles asked),
gap closed (skills he cannot truthfully claim yet), depth and wow factor for
an AI-company engineer, and real-world usefulness (could real users adopt it?).
Prefer full-stack AI products or genuinely deep AI systems (agents with
evals, retrieval quality, inference/serving performance, LLM tooling), each
buildable by an agent team in 4-6 milestone PRs, with a resume-worthy,
measurable result by the second milestone. Differentiate from what exists;
no clones of tutorials.

The projects form a **pool** (AD-41): the tailor swaps projects and their
bullets per posting, so the pool must cover the role families he applies to
(backend, applied AI/ML, infra/systems, full stack, data), and the keywords
those postings screen for. Map the pool first: which families and top-demand
skills do the existing projects (building, approved, done) already
cover, and which are thin? Then propose to fill the thinnest, and say
which family each proposal serves.

Write `resume/private/reports/project-scout-<YYYY-MM-DD>.md` (your reasoning,
under 800 words) and `/tmp/scout.json`:
{"projects": [{"title": "...", "slug": "kebab-case", "pitch": "2 sentences",
  "why": "demand evidence + gap closed", "skills": ["..."], "stack": ["..."],
  "release": "how real users get it"}]}
Do not edit projects.yaml yourself and do not create repositories. Finally
record what you proposed and why:
`uv run opportunity-radar hub log "scout" "<2-4 lines>"`.
