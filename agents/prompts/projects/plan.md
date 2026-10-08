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
     measured), `## Release` (how real users get it and what Patrick must
     provide), `## Risks`, and `## Milestones`: 5-8 checkbox items
     (`- [ ] M1: title — definition of done`). Each milestone is one PR of
     focused work (roughly 2-5 hours of agent time), ends with green tests, and
     leaves the project runnable. M1 is scaffolding + CI + a thin vertical
     slice; the last milestone is release readiness + RESULTS.md.
   - `CLAUDE.md` for future agents: commands, conventions, quality gates.
   - `README.md` skeleton (title, one-paragraph pitch, "status: in progress").
   - Scaffolding only if trivial (license, .gitignore, empty CI workflow).
3. Write `.agent/pr.md`: a PR description summarising the plan and the
   decisions Patrick should weigh in on (he reviews before building starts).
4. Write `.agent/commit.txt`: one-line commit subject for the plan.
