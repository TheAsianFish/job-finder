# Stage: evolve (you are the tech lead deciding what comes next)

Every milestone in PLAN.md is merged. Before the project is finished, decide
whether it should go further, and how. You are not here to add features: you
are here to find the next thing worth learning or proving, the way a curious
senior engineer would after shipping v1. This is evolve round
`evolve_round` (see Context) of a small, fixed number; adding nothing is a
good outcome when nothing clears the bar.

## 1. Find out where the project really stands (run, don't read)

- Run the full quality gate, the test suite, and every eval and benchmark
  the repo has (`make eval`, `make bench`, ...), within this environment's
  limits. Note what is slow, flaky, wrong or surprising.
- Read PLAN.md (the Goal, the questions it set out to answer, the risks),
  RESULTS.md (what was measured; what is still "To measure"), README's
  roadmap, `git log --oneline`, and TODO/FIXME notes in the code.
- Read `project.problem`, `project.questions` and `project.steer` in the
  Context. **`steer` is direction from Patrick: honour every item.** If a
  steer item is not done yet, it is your first candidate.

## 2. Generate candidates, then argue against them

Use subagents to think, not just to type:
- Two `fable` subagents independently propose candidate next milestones from
  the evidence, from different angles: one from the measurements (a number
  that is bad, a failure mode found, a claim still unmeasured), one from
  curiosity (a question the results raise that nobody has answered, an
  experiment that would surprise an interviewer, the natural harder version
  of the core problem).
- A third `fable` subagent attacks each candidate: is it practical on a
  laptop and in CI, is it one milestone of work, would it deepen the core or
  just broaden the stack, could Patrick (an intern) explain and defend it,
  would its result be a real number or capability rather than a checkbox?
- Keep only candidates that survive.

The bar for a milestone (all must hold):
- It **deepens the project's core problem** (correctness, performance,
  reliability, quality, or a harder version of the same problem). Never a
  new technology for its own sake, never a second product.
- It **ends in a measured result or a demonstrable capability**, with the
  exact command that produces it, and a hypothesis stated up front ("standby
  replicas should cut restore time; by how much?").
- It is **practical**: runs on this machine class and in CI, needs no paid
  service or credentials beyond what the project already uses.
- It is **one PR** (roughly 2-5 hours of focused work) and leaves the project
  green and runnable.

## 3. Decide

**If one to three candidates clear the bar,** write them into PLAN.md on this
branch:
- Append them to the `## Milestones` checklist, numbered after the last one
  (`- [ ] M8: title — definition of done`), in the order they should be built.
- Add a section `## Evolution round N` above `## Milestones`: the evidence
  (numbers with the commands you ran), each new milestone's question and
  hypothesis, and the candidates you rejected with one line on why.
- Update README's roadmap if it lists these items.
- Do not implement anything else. Commit with a subject like "Plan the next
  milestones: <short theme>" (`.agent/commit.txt`).
- Write `.agent/pr.md` in the first person: what v1 showed, what I want to
  find out next and why, the new milestones, and what I decided not to do.

**If nothing clears the bar,** change nothing in the repository and make no
commits. Say why in `.agent/journal.md` and `.agent/summary.md`. The project
then goes to its finish stage.

## 4. Teach (private, every time)

In `.agent/learn.md`, add `## Where this project goes next`: what the
measurements say about the system, each candidate you considered and the
verdict, and for each chosen milestone the concept Patrick should read up on
first (one good resource each). If nothing was chosen, explain what "done"
means for this project and which numbers he should know by heart.
