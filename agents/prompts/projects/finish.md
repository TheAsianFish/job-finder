# Stage: finish (release readiness + the resume entry)

All milestones are merged. Make sure the project is release-ready (README
complete with real results, RELEASE.md, CI green, `make eval`/`make bench`
documented). Commit any final polish, and write `.agent/pr.md`: a short
first-person release-readiness PR description. The resume entry and
interview are private files: never mention them in the repo or PR.

The resume entry (`.agent/RESUME.tex`, `.agent/BULLETS.md`) is written by
the bullets session that runs right after you. Copy RESULTS.md to
`.agent/RESULTS.md`.

Finally write `.agent/INTERVIEW.md`: a mock interview Patrick must pass before
this project's resume entry is approved: 12 questions a strong interviewer would ask about this
project (overview, architecture, the hard part, his piece, trade-offs,
failure modes, how each number in RESULTS.md was measured, what he'd do next), each
with what a strong answer must contain.
