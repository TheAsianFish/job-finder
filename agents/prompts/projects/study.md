# Task: weekly study pack (you are Patrick's interview coach)

Read resume/private/hub/ (ABOUT.md, JOURNAL.md, projects/), the interview
guides `resume/private/study/*/GUIDE.md` (each project's full explanation,
just refreshed), `resume/private/resume.tex` (which projects are on his
page) and `$RUNNER_TEMP/merged-prs.md` (this week's merged milestone PRs and
the milestone notes behind them).

The guides hold the depth. The pack is the week's study plan on top of them:
short, and pointing into the guides rather than repeating them. Projects on
his resume come first, because those are the ones he is asked about; give
the others a sentence each.

Write `resume/private/reports/study-<YYYY-MM-DD>.md`, under 1,200 words, in
prose (bullets only for real lists):
1. **This week**: one short paragraph per project that moved, on what it
   can do now that it could not last week and why that matters.
2. **What to study**: the 2-3 most interview-relevant ideas from this week,
   each in a paragraph that explains it plainly, then the guide section to
   read (`study/<slug>/GUIDE.md`, section name) and one outside resource.
3. **Say it out loud**: two questions from his resume projects' guides to
   answer aloud this week without notes, rotating through the bullets.
4. **Quiz**: 8 questions, mixing recall, "explain why" and "what would
   break if...", weighted toward resume projects. Answers at the very end
   under "Answers", written as he would say them.
5. **His piece** (one line, only the highest-priority resume project's piece
   if it is not written yet): the next concrete step. Do not list the other
   projects' pieces.

Then add a journal entry:
`uv run opportunity-radar hub log "study" "<1-2 lines>"`.
Never invent progress; if nothing was merged, say so and build the week
around the resume projects' guides.
