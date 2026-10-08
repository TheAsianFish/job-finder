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
- Check `.agent/learn.md`: would it genuinely prepare Patrick for interview
  questions on this milestone? Improve it if it is thin or inaccurate.
- Check authorship (see the standards): nothing saying or implying that AI
  wrote or reviewed the work, and no "Patrick", anywhere in the diff, commit messages
  (`git log main..HEAD`), or `.agent/pr.md`; no CLAUDE.md/AGENTS.md/.claude/
  tracked. Fix any you find (reword commits with an interactive-free rebase
  only if they have not been pushed; otherwise fix the text in a new commit).
- Fix every real problem you find directly on this branch (focused commits,
  quality gate green). Do not rewrite working code to taste. If you fix
  things, add a short first-person "Review follow-ups" list to `.agent/pr.md`.
- Write your review to `.agent/review.md` (private, for Patrick): what you
  checked, what you fixed, remaining concerns.
- Write the verdict to `.agent/verdict`: exactly `pass` only if the
  milestone now genuinely meets its definition of done, otherwise `changes`
  (and say what is missing in `.agent/review.md` and as an open item in
  `.agent/pr.md`).
