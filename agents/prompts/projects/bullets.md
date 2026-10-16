# Stage: resume bullets (you are a senior engineer who also hires)

The work on this branch has just passed review. Write the project's resume
entry from what is **built and measured so far**, so the project can go on
Patrick's resume now and be swapped in for the job postings it fits. A tailor
picks the entry and the bullets that match each posting, so give it a real
choice. These are private files: never mention them in the repo, commits or PR.

Read first: README, PLAN.md (what is done), RESULTS.md (the only source of
numbers), `git log --oneline`, and the code behind each claim you make.
If `.agent/RESUME.tex` already exists from an earlier stage of this run, improve it.

**Build on the previous version.** The prompt ends with the entry and talk
tracks from the last milestone (if any) and Patrick's comments on them. Start
from that version: keep what is still true and strong, sharpen what the new
work makes stronger (a new measured number, a harder problem solved), replace
what it supersedes, and address every comment. Open BULLETS.md with
`## Changes since the last version`: what changed and why, and how each
comment was handled. An independent reviewer reads your work next and cuts
anything weak, so write for that reader.

## `.agent/RESUME.tex`

ONE project entry in Jake's resume template, exactly this shape:

\resumeProjectHeading
  {\textbf{Name --- Short Descriptor} $|$ \emph{Tech, Stack, Here} $|$ \href{https://github.com/OWNER/REPO}{\textcolor{blue}{GitHub}}}{}
  \resumeItemListStart
    \resumeItem{...}
  \resumeItemListEnd

- **4 to 6 bullets, each a different achievement.** Cover the angles the
  project really has, so it can fit different postings. For example: the core
  system and its hard part, evaluation and measurement, backend/API and data,
  infrastructure/CI/deploy, frontend, performance. The tailor shows 2 or 3, so
  every bullet must stand on its own. Don't write two wordings of the same
  achievement: near-duplicates are dropped.
- **STAR in one sentence:** what you built (strong, plain verb), the hard
  engineering decision or problem, and the result, measured when
  RESULTS.md has the number. Shape: "Built X that does Y by Z, cutting/raising
  M from A to B". The result is concrete: a number, a capability, a user
  outcome. It is never "improving efficiency" or "enhancing reliability".
- **Every number appears in RESULTS.md from a real run.** Unmeasured: state
  the outcome without a number. Harness-only evals ("To measure") are
  described as what the harness does, never as results.
- **Real words, not slop.** No "leveraged", "utilized", "spearheaded",
  "cutting-edge", "state-of-the-art", "seamless", "robust", "scalable
  solution", "innovative", "end-to-end solution", "drove", "synergy". Name the
  actual technique (Cohen's kappa with a bootstrap CI, content-addressed
  cache, Alembic migrations), because those are the words an ATS and an
  interviewer both look for. Each skill named must be visibly used in the
  code.
- Each bullet is at most 220 characters, LaTeX-escaped (\%, \&, \#, \_). Bold
  at most one headline metric per bullet with \textbf{}. The \emph{} tech list
  holds the 4 to 7 technologies a posting would search for, most important
  first.
- Patrick must be able to talk about every bullet for five minutes. If you
  can't write that talk track (below) from the code, the bullet goes.

## `.agent/BULLETS.md`

For each bullet, in order: the bullet, then its **talk track**:
- **Situation/Task:** the problem in two sentences, and why it was hard.
- **Action:** what was built and the key decision, including the alternative
  that was rejected and why. Name the files to read (`path/to/file.py`).
- **Result:** the number and exactly how it was measured (command, dataset,
  sample size), or the outcome when there is no number.
- **Follow-ups:** the two questions an interviewer will ask next, each with
  the core of a strong answer.
- **Fits:** the role families and posting keywords it serves (backend, AI/ML,
  infra, full stack, data).

Write nothing (no files) if nothing built so far is worth a resume line yet,
for example a scaffold-only milestone. A weak bullet costs more than a missing one.
