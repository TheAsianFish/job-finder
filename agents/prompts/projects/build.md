# Stage: build one milestone (you are the lead engineer)

Read PLAN.md and CLAUDE.md first. Implement exactly the milestone named in the
context below, to its definition of done, at the standard above.

- Plan the milestone, then parallelise with subagents where work is
  independent. Integrate and review everything yourself.
- Commit as you go (several focused commits). Run the full quality gate
  (format, lint, type-check, tests) before every commit; never commit red.
- Add or update tests for everything you build; add eval/bench harnesses when
  the milestone touches quality or performance, and record real outputs in
  RESULTS.md.
- Update README and PLAN.md (tick this milestone's checkbox, note any plan
  changes and why). Do not start the next milestone.
- Finally write `.agent/pr.md`: what was built, how to try it, test/eval
  evidence (commands + results), decisions and trade-offs, anything not done
  and why, and what you would like Patrick to check. Then a section
  `## What you need to know` that teaches this milestone: the concepts used
  (plain explanations), each design decision with the alternative rejected and
  why, a short walkthrough of the most important code path (file:line
  pointers), 5 likely interview questions with strong answer outlines, and one
  30-minute exercise (predict-then-verify, or a small change to try).
