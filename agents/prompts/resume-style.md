# Patrick's resume voice (every resume and project bullet follows this)

The reader is a recruiter skimming for six seconds and then an engineer who
reads closely and asks "tell me more". Both must come away with the same
story: a strong engineer who solved hard, specific problems and knows why.
Technical and engineering-first, with nuance where it earns its place.

## The shape of a bullet

One sentence, about 150-230 characters, in one of these shapes:
- **Result first:** the measured outcome, then how. "Reduced page load time
  83% (3s to 0.5s) by tracing latency through the ORM and moving pagination
  into the database."
- **Ownership first:** what you owned and the scope it served, then the
  hardest part shipped. "Owned production development for ... shipping ..."
- **Diagnosis:** "Root-caused <the defect> to <the real cause> and <the fix>,
  restoring/preventing <the effect>."

Every bullet has three parts, in whichever order reads best:
1. **The engineering action**, with its precise mechanism named once (the
   algorithm, data structure, protocol, consistency or concurrency decision,
   test strategy). Name at most two technologies, the ones that matter to
   the story. A bullet is not a stack list.
2. **The hard part or the decision** (nuance): why it was difficult, or the
   trade-off chosen and what it bought ("advisory until calibrated against
   human labels", "sequential test instead of a fixed sample, so a flaky
   agent fails early"). One clause, not a paragraph.
3. **The result**, concrete: a measured number with its meaning, or what it
   enabled, prevented or replaced ("so every dependent view shows accurate
   rates"). A bullet with no result is unfinished.

## Verbs

Lead with a strong, specific engineering verb, and never open two bullets in
one entry with the same verb. Good: Engineered, Architected, Designed,
Implemented, Developed, Productionized, Hardened, Root-caused, Diagnosed,
Resolved, Decoupled, Eliminated, Reduced, Accelerated, Optimized,
Parallelized, Instrumented, Benchmarked, Validated, Automated, Integrated,
Migrated, Shipped, Owned, Led (only with a real team).

Weak (never as the lead verb): Made, Kept, Cut, Did, Got, Helped, Worked on,
Used, Utilized, Leveraged, Created, Handled, Responsible for. "Built" at most
once per entry, and only when nothing more specific fits.

## Numbers

- Every number carries its unit and its meaning: "83% (3s to 0.5s)", "caught
  12 of 12 seeded model regressions", "a 1-in-120 failure". Never a bare
  ratio like "7/32" or "12/12".
- At most one bolded headline result per bullet, on the number that matters.
- No more than two numbers in a bullet unless they form one comparison.

## Never

- Jargon chains (three or more technical nouns in a row), parenthetical stacks,
  or listing frameworks the reader doesn't need ("TanStack Query, Vitest,
  Playwright").
- Buzzwords: robust, seamless, scalable solution, cutting-edge,
  state-of-the-art, innovative, end-to-end solution, synergy, spearheaded.
- Claims the code or the measurements don't support, or scope inflation.

## The entry as a whole

Order the bullets as a story: the core system and its hardest problem first,
then how it was proven (evaluation, benchmark), then how it ships. Each
bullet adds different evidence; no repeated claim, verb or keyword.
