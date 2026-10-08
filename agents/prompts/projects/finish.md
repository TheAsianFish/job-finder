# Stage: finish (release readiness + the resume entry)

All milestones are merged. Make sure the project is release-ready (README
complete with real results, RELEASE.md, CI green, `make eval`/`make bench`
documented). Commit any final polish.

Then write `.agent/RESUME.tex`: ONE project entry in Jake's resume template,
exactly this shape:

\resumeProjectHeading
  {\textbf{Name --- Short Descriptor} $|$ \emph{Tech, Stack, Here} $|$ \href{https://github.com/OWNER/REPO}{\textcolor{blue}{GitHub}}}{}
  \resumeItemListStart
    \resumeItem{...}
    \resumeItem{...}
    \resumeItem{...}
  \resumeItemListEnd

Rules for the bullets: 2-3 bullets, each one sentence of at most 220
characters, technical STAR/XYZ stories (what was built, the hard engineering
decision, the measured result), strong verbs, LaTeX-escaped (\%, \&, \#).
**Every number must appear in RESULTS.md from a real run.** If a metric was
not measured, describe the outcome without a number. Bold at most one headline
metric per bullet with \textbf{}. Also copy RESULTS.md to `.agent/RESULTS.md`.
