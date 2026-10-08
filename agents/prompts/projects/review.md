# Stage: independent review (you are the staff engineer reviewing the PR)

Another agent just implemented a milestone on this branch. Review the full
diff against `main` (`git diff main...HEAD`) as a demanding senior reviewer at
a top AI company would: correctness, security, test quality (do tests prove
behaviour or just run code?), measured claims vs RESULTS.md, design quality,
readability, and whether the milestone's definition of done in PLAN.md is
really met.

- Run everything yourself: the full quality gate, the test suite, and any
  eval/benchmark the milestone touches (for real when `ANTHROPIC_API_KEY` is
  set). Compare the numbers to what `.agent/pr.md` and RESULTS.md claim.
- For a large diff, fan out reviewer subagents in parallel, one per dimension
  (correctness, security, tests/evals, design), `fable` for the subtle ones and
  `haiku`/`sonnet` for mechanical checks. Then have a `fable` subagent try to
  refute each finding before you act on it; drop findings that don't survive.
- Check that `.agent/pr.md` has a `## What you need to know` section that
  would genuinely prepare Patrick for interview questions on this milestone;
  improve it if it is thin or inaccurate.
- Fix every real problem you find directly on this branch (focused commits,
  quality gate green). Do not rewrite working code to taste.
- Append a `## Review` section to `.agent/pr.md`: what you checked, what you
  fixed, remaining concerns. End the file with the line
  `<!-- fable-review: pass -->` only if the milestone now genuinely meets its
  definition of done; otherwise end with `<!-- fable-review: changes -->` and
  say what is missing.
