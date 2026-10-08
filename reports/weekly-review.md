# Weekly review — 2026-10-08

Source: `data/opportunity_radar.db`. The filter matches `insights skills`: active, early-career,
score > 0, relevant role family, not (likely) ineligible, title contains intern/co-op,
US-workable. No application records exist yet, so nothing was excluded as dismissed or applied.

## Apply this week

1,525 postings in the pool were first seen within 21 days. Non-US rows were removed by hand:
Tower Montreal, Snowflake Berlin, Waymo Warsaw and Databricks EU.

| # | Company | Title | Season | Score | Apply |
|---|---|---|---|---|---|
| 1 | Amazon / AWS | SDE Intern – Summer 2027 (USA) | Summer 2027 | 98.0 | [apply](https://account.amazon.jobs/jobs/10552937/apply) |
| 2 | Amazon / AWS | SDE Intern, AWS Database – 2027 (US) | Summer 2027 | 96.0 | [apply](https://account.amazon.jobs/jobs/10565667/apply) |
| 3 | Amazon / AWS | SDE Intern (Embedded Systems) – Summer 2027 | Summer 2027 | 95.5 | [apply](https://account.amazon.jobs/jobs/10567914/apply) |
| 4 | Amazon / AWS | SDE Intern – Mobile (iOS/Android) – Summer 2027 | Summer 2027 | 95.5 | [apply](https://account.amazon.jobs/jobs/10571004/apply) |
| 5 | Amazon / AWS | SDE Intern, Amazon Leo – Summer 2027 | Summer 2027 | 92.0 | [apply](https://account.amazon.jobs/jobs/10559762/apply) |
| 6 | Amazon / AWS | SDE (Embedded Systems) Intern, Amazon Leo – Summer 2027 | Summer 2027 | 90.5 | [apply](https://account.amazon.jobs/jobs/10571374/apply) |
| 7 | Verkada | Backend Software Engineering Intern 2027 | Summer 2027 | 90.0 | [apply](https://job-boards.greenhouse.io/verkada/jobs/5210813007) |
| 8 | Verkada | Security Software Engineering Intern 2027 | Summer 2027 | 90.0 | [apply](https://job-boards.greenhouse.io/verkada/jobs/5213881007) |
| 9 | Rubrik | Software Engineering Winter Internship | Winter 2027 | 89.1 | [apply](https://www.rubrik.com/company/careers/departments/job.8171088?gh_jid=8171088) |
| 10 | Amazon / AWS | Robotics SDE Fall Intern/Co-op – 2026 | Fall 2026 | 88.2 | [apply](https://account.amazon.jobs/jobs/10517149/apply) |
| 11 | Cloudflare | People Team: Software Engineer Intern (Winter/Spring 2027) | Spring 2027 | 88.0 | [apply](https://boards.greenhouse.io/cloudflare/jobs/7774167?gh_jid=7774167) |
| 12 | Amazon / AWS | SDE Intern – Summer 2027, Amazon Dedicated Cloud | Summer 2027 | 88.0 | [apply](https://account.amazon.jobs/jobs/10559746/apply) |
| 13 | Affirm | Software Engineer (Machine Learning) Intern | Summer 2027 | 87.0 | [apply](https://job-boards.greenhouse.io/affirm/jobs/8008645003) |
| 14 | DV Trading | DevOps Engineer Intern – Summer 2027 | Summer 2027 | 87.0 | [apply](https://job-boards.greenhouse.io/dvtrading/jobs/4730886005) |
| 15 | Varda Space Industries | Site Reliability Internship – Spring 2027 | Spring 2027 | 87.0 | [apply](https://job-boards.greenhouse.io/vardaspace/jobs/7824814003) |

Amazon holds 8 of the 15 slots. #10 is a Fall 2026 co-op, and that term has already
started, so check its start date. Next by score:
Optiver Austin (85.5), Optiver Chicago (84.5), Together AI Winter (84.0), NVIDIA SWE 2027 (84.0).

## Skill gaps to act on

Shares are from `reports/skill-demand.md` (408 postings):

1. **Debugging: 19%** (46% of embedded, 29% of infrastructure). Very little effort if it's
   already true. Rewrite one production-software bullet around a real bug you tracked down
   (symptom → tools used → fix), and use the word "debugged".
2. **Linux: 17%** (31% of infrastructure, 46% of embedded). The profile lists Docker,
   Kubernetes, Jenkins and operating systems, so Linux is plausibly real experience. If it is,
   add "Linux" to the skills line. If not, spend a week on a small project: write a shell or a
   process monitor in C using `fork`/`exec`/`/proc`.
3. **LLMs/GenAI: 10%** (20% of data-infrastructure). ChromaDB and Tree-sitter on the profile
   suggest retrieval work. If that project actually called an LLM, name it in the bullet (e.g.
   "LLM-backed code search over a Tree-sitter-parsed repo with ChromaDB embeddings"). If it
   didn't, a 1–2 week RAG demo over a codebase would close this gap.

Rust (11%) and Embedded (15%) are in higher demand but take far more effort to learn, so they
come lower on this list.

## Trends

**First review:** there is no earlier `weekly-review.md` in git history to compare against.
Baseline snapshot:

- Of the 1,525 postings first seen within 21 days, 1,416 are baseline rows. 1,497 of the
  1,587 companies were added to the registry on 2026-10-07, so for most rows "first seen"
  means the date the company was onboarded, not the date the job was posted. Only **108**
  postings are genuinely new. The top new posters are Astranis (18), Optiver (9),
  Anduril (8), Pinterest (7), and Stripe, Ramp and Databricks (5 each).
- Seasons in the 21-day pool (before the US filter): Summer 2027 817, unspecified 275,
  Winter 2027 147, Fall 2026 145, Spring 2027 89. 536 companies are hiring. The largest
  posters are TikTok and NVIDIA (79 each) and Tesla (49).

## Roadmap

No phase changed status, so `docs/roadmap.md` is unchanged. Phase 2 is still waiting on the
resume. Phase 4 has no outcome data yet: the `applications` table is empty.
