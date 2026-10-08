# Stage: plan (you are the architect)

The repository is empty or has no PLAN.md. Design the project and write the
plan; do not implement features yet.

1. Research first. Use web search to check the current state of the art for
   this problem, what already exists (so the project is differentiated, not a
   clone), and the current versions of the libraries you choose.
2. Write these files on the current branch:
   - `PLAN.md` with sections: `## Goal` (problem, users, what makes it
     impressive), `## Architecture` (components, data flow, Mermaid diagram,
     key design decisions with alternatives considered), `## Evaluation`
     (datasets, metrics, baselines, how each resume-worthy number will be
     measured), `## Release` (how real users get it and what the maintainer
     must provide), `## Risks`, and
     `## Milestones`: 5-8 checkbox items
     (`- [ ] M1: title — definition of done`). Each milestone is one PR of
     focused work (roughly 2-5 hours of engineering), ends with green tests, and
     leaves the project runnable. M1 is scaffolding + CI + a thin vertical
     slice; the last milestone is release readiness + RESULTS.md.
   - `CONTRIBUTING.md`: setup, commands, conventions, quality gates (the
     contributor guide; also what future sessions read first).
   - `README.md` skeleton (title, one-paragraph pitch, "status: in progress").
   - Scaffolding only if trivial (license, .gitignore, empty CI workflow).
3. Write `.agent/pr.md`: a PR description in the first person summarising the
   plan and listing the open design decisions as questions (Patrick reviews it
   before building starts; it must read like his own design PR).
4. Write `.agent/learn.md` (private): `## His piece` (one core component,
   100-250 lines, that he writes himself: the most interview-worthy algorithm
   or mechanism; the interface, tests and baseline that will surround it, and
   the milestone where he should write it), `## Learning path` (concepts he
   must understand, in order, with one good resource each), and
   `## Decisions to weigh` (each open decision with the options and your
   recommendation, explained so he can answer confidently). Name his piece in
   `.agent/summary.md` too.
5. Write `.agent/commit.txt`: one-line commit subject for the plan.
