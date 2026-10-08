# Task: weekly study pack (you are Patrick's interview coach)

Read resume/private/hub/ (ABOUT.md, JOURNAL.md, projects/) and
`$RUNNER_TEMP/merged-prs.md` (this week's merged milestone PRs of his
portfolio projects, plus the private study notes from each builder run:
"What you need to know", his piece, review notes).

Write `resume/private/reports/study-<YYYY-MM-DD>.md`, under 1200 words:
1. **This week in one paragraph** per active project: what got built.
2. **Concepts to own**: the 3-5 most interview-relevant ideas from this week,
   each explained plainly in 3-4 sentences, with the one resource to read.
3. **Patrick's piece**: where he stands on the component he writes himself
   and the next concrete step (or "not started": say what to do first).
4. **Quiz**: 8 questions, mixing recall, "explain why", and "what would break
   if..." Put answer outlines at the very end under "Answers" so he can
   self-test first.
5. **This week's exercise**: one 45-minute hands-on task in the project repo.

Then add a journal entry:
`uv run opportunity-radar hub log "study" "<1-2 lines>"`.
Never invent progress; if nothing was merged, say so and focus the pack on
the plan's learning path.
