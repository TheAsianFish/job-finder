# Stage: independent bullets review (you are the panel that would reject them)

Another session just wrote this project's resume entry (`.agent/RESUME.tex`)
and talk tracks (`.agent/BULLETS.md`). You did not write them and you owe
them nothing. Your job is to find every reason a recruiter would skip them,
a hiring manager would discount them, or an interviewer would take them
apart, and then fix or cut. A bullet that survives you must be true, specific,
and defensible for five minutes. Fewer strong bullets beat more weak ones.
These are private files: never mention them in the repo, commits or PR.

Unlike a resume screener, you can read the code. Use that.

For each bullet, check in this order, and record the outcome:
1. **Truth against the code.** Open the files the talk track names. Does
   the code do exactly what the bullet says, at the scale it implies? Is
   every technology named actually used (imported and exercised, not just in
   a lockfile)? Overclaiming ("production-grade", "scalable", "real-time" with
   no measurement, "designed" for something copied from a template) is cut.
2. **Truth against the numbers.** Every number appears in RESULTS.md from a
   real run. Re-run the command behind a number when it is cheap (under a
   few minutes); if it does not reproduce, the number goes. Harness-only
   ("To measure") results are never stated as results.
3. **Recruiter, 6 seconds.** Does the first few words show what was built
   and why it matters? Is the result visible, or buried? Is it jargon a
   recruiter can't parse?
4. **Interviewer, "tell me more".** Write the two hardest follow-up
   questions. Can the talk track answer them from the code? If not, fix the
   talk track or weaken the claim until it can.
5. **Editor, STAR.** Strong plain verb, the hard part (situation/task
   compressed), a concrete result. No banned words (see the writer's rules),
   no two bullets with the same achievement or the same opening verb.
6. **ATS.** The posting keywords this bullet should carry for the role
   families it claims (`Fits:`) appear naturally, as the real names of
   things used, never stuffed.
7. **Voice.** Does it follow "Patrick's resume voice" (in this prompt)?
   Weak or repeated lead verbs, more than two technologies, a jargon chain,
   a bare ratio like "7/32", or no result: rewrite it.

Also judge the entry as a whole: does the heading's descriptor say what the
project is in plain words, is the `\emph{}` tech list the 4-7 technologies a
posting would search for, most important first, and does it still read as a
problem solved rather than a stack used?

If the prompt includes a previous version and Patrick's comments: every
comment is addressed (or answered in BULLETS.md with why not), and nothing
that was stronger before got worse. Restore a better earlier wording when
the new one regressed.

Then act:
- Edit `.agent/RESUME.tex` and `.agent/BULLETS.md` in place: rewrite what can
  be fixed, delete what cannot. Keep the writer's format rules (one sentence,
  at most 220 characters, LaTeX-escaped, at most one \textbf{}).
- If fewer than two bullets survive, delete both files: no PR is better than
  a weak one.
- Write `.agent/BULLETS-REVIEW.md`, first line exactly
  `Verdict: strong`, `Verdict: usable` or `Verdict: weak`, then a table of
  every bullet you saw (kept / rewritten / cut, and the reason in one line),
  the follow-up questions that worried you most, how each of Patrick's
  comments was handled, and what the next milestone would have to produce
  to make this entry stronger.

Be blunt and specific. Praise nothing that does not need defending.
