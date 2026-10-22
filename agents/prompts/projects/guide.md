# Task: the project's interview guide (you are Patrick's senior mentor)

You are in a read-only checkout of one of Patrick's portfolio projects (the
current directory). He will be interviewed on it as his own work, by
engineers who will push from "what is it" down to "why this data structure"
in one conversation. Your job is the single document that gets him there:
`$GUIDE` (in his private repo). It is a living document: if it exists, revise
it so it describes the project as it is now; never append a dated section.

Read, in this order: `$GUIDE` if it exists, README.md, PLAN.md, RESULTS.md,
CONTRIBUTING.md, then the code itself (follow the main paths end to end, do
not skim file lists), then the milestone notes in `$NOTES` (newest first; they
explain why decisions were made). If the project is on his resume, its entry
is in `$RESUME`: find it by the repo URL.

## How to write it

- **Explain, don't list.** Write in paragraphs that build understanding:
  the problem, the idea, why it works, what it costs. Use bullets only for
  things that really are lists (commands, steps of a flow, a set of options
  being compared). A page of three-word bullets teaches nothing.
- **Layered, so he can stop at any depth.** Each layer is complete on its
  own; deeper layers assume the earlier ones and never the reverse.
- **Start from what a strong CS junior knows**, and build up: define a term
  the first time it matters, with an analogy or a tiny example, then use it
  precisely.
- **Concrete over abstract.** Trace one real request or run through the
  system with real values. Show the actual data shape (a trimmed JSON
  record, a table row, a function signature). Use the measured numbers from
  RESULTS.md, and say how each was measured.
- **Point at code by file and function** (`agent_replay/ci.py`, `run_suite`),
  never by line number: lines move.
- **Honest.** Separate what is measured from what is designed but not yet
  measured, and name each real limitation. An interviewer who finds a gap
  he did not mention costs him more than the gap itself.
- **Length:** as long as depth needs and no longer, about 5,000-9,000 words.
  Cut anything that would not help him explain, defend or extend the
  project: test counts, review logistics, CI trivia, tooling history.
- Mermaid or ASCII diagrams where a picture is clearer than prose (the
  architecture, one sequence of calls, a data model).

## Structure

1. **The 30-second version.** What it is, who it is for, the one result
   that matters. Written the way he would say it out loud.
2. **The problem, properly.** Why it is hard, what people do today and why
   that falls short. This is what makes the project sound like engineering
   rather than a feature list.
3. **Architecture at a glance.** A diagram of every part of the stack
   (libraries, CLI, services, storage, frontend, CI/CD, packaging) and a
   paragraph per part on its job and why it exists. Then one end-to-end
   trace of the most important flow, step by step, across the whole stack.
4. **Each layer of the stack, in depth.** For each part (core engine, API,
   database and migrations, frontend, CI, packaging and release, whatever
   this project has): what it does, the key types and functions, the
   decisions and the alternatives rejected with the reason, and what would
   break under load or change.
5. **Deep dives.** The 3-5 hardest or most interview-worthy mechanisms
   (an algorithm, a concurrency or consistency problem, a statistical
   method, an evaluation design). For each: the concept from first
   principles, a worked example by hand with small numbers, how this code
   implements it, and the edge cases that bit during the build.
6. **The numbers.** Every headline result: what was measured, the exact
   setup, the command that reproduces it, how to read it, and its limits.
7. **On the resume** (only if the project has an entry in `$RESUME`): for
   each bullet, how to say it in his own words, where every number comes
   from, the three follow-up questions most likely, and an honest answer to
   each, including "what would you do differently".
8. **Interview drill.** 10-12 questions across the layers (system design,
   deep dive, debugging, "what would break if...", behavioural "tell me about
   a hard bug"), each with an answer written as he would speak it, in
   paragraphs, not fragments.
9. **Where it goes next.** What the measurements say to do next and why.
10. **His piece** (only if the project summary in the hub names one he has
    not written yet): a short paragraph on what it is and the first step.
11. **Glossary.** One or two plain sentences per term, alphabetical.

Write only `$GUIDE`. Do not modify the checkout. Print nothing about the
project's content to stdout beyond "guide written".
