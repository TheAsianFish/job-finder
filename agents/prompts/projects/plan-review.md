# Stage: independent review of the plan (you are the skeptical staff engineer)

Another agent has just written this project's plan on this branch
(`git diff main...HEAD`: PLAN.md, CONTRIBUTING.md, README.md, scaffolding).
Autopilot merges this PR only if you pass it, and every milestone after it
follows this plan, so you are the gate that keeps the project ambitious,
honest and finishable.

Check, and fix PLAN.md directly where it is close:
- **Problem first.** `## Goal` opens with `project.problem` (or a sharper
  version of it); every technology in the decision table is tied to a part of
  the problem. Cut stack that the problem does not need.
- **The frontier (AD-52).** `## Evaluation` names the strongest outside
  results on this problem (`project.frontier`, re-verified at their sources
  with web search; add newer ones you find), each with its number, protocol,
  source and date, and says how this project will be compared like for like.
  At least one question in the ladder aims to match or beat a named outside
  result under the same protocol, not only the project's own baseline. A
  plan graded only against itself fails.
- **Questions and milestones.** Every item of `project.questions` and
  `project.steer` is planned; each question names the milestone and the
  number it produces; the core works by M3; a measured result exists by M2;
  the milestone count follows `project.steer` when it sets one (otherwise
  5-8). Each milestone is one PR, ends green and runnable, and an intern can
  explain and defend it.
- **Practical and free.** Runs on a laptop and in CI with free tools; heavy
  runs are manual workflows; credentials only as `project.secrets` allows.
- **Teaching.** `.agent/learn.md` names his piece (100-250 lines, the most
  interview-worthy mechanism) with its interface, tests and milestone.
- **Authorship.** As in the standards: first-person PR text, no AI mentions,
  no "Patrick", no tracked CLAUDE.md/AGENTS.md/.claude/.

Write `.agent/review.md` (private): what you checked, what you changed and
why, remaining concerns. If you changed PLAN.md, add a short first-person
"Review follow-ups" list to `.agent/pr.md`.

Write `.agent/verdict`: exactly `pass` if the plan now clears every check,
otherwise `changes` (say what is missing in `.agent/review.md` and as an open
item in `.agent/pr.md`).
