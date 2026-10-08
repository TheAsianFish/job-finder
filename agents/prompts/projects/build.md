# Stage: build one milestone (you are the lead engineer)

Read PLAN.md and CONTRIBUTING.md first. Implement exactly the milestone named in the
context below, to its definition of done, at the standard above.

- Plan the milestone, then parallelise with subagents where work is
  independent. Integrate and review everything yourself.
- Commit as you go (see the commit rules above). Run the full quality gate
  (format, lint, type-check, tests) before every commit; never commit red.
- Add or update tests for everything you build; add eval/bench harnesses when
  the milestone touches quality or performance, and record real outputs in
  RESULTS.md.
- Update README and PLAN.md (tick this milestone's checkbox, note any plan
  changes and why). Do not start the next milestone.
- Finally write `.agent/pr.md` in the first person, like a strong engineer's
  PR: what was built, how to try it, test/eval evidence (commands + results),
  decisions and trade-offs, anything not done and why. Then write the
  teaching notes in `.agent/learn.md` (see Teaching above).
