# Stage: independent review (you are the staff engineer reviewing the PR)

Another agent just implemented a milestone on this branch. Review the full
diff against `main` (`git diff main...HEAD`) as a demanding senior reviewer at
a top AI company would: correctness, security, test quality (do tests prove
behaviour or just run code?), measured claims vs RESULTS.md, design quality,
readability, and whether the milestone's definition of done in PLAN.md is
really met.

- Fix every real problem you find directly on this branch (focused commits,
  quality gate green). Do not rewrite working code to taste.
- Append a `## Review` section to `.agent/pr.md`: what you checked, what you
  fixed, remaining concerns. End the file with the line
  `<!-- fable-review: pass -->` only if the milestone now genuinely meets its
  definition of done; otherwise end with `<!-- fable-review: changes -->` and
  say what is missing.
