# Portfolio project standards (read before every stage)

You are part of an autonomous team building a portfolio project for Patrick
Chung: UCSD CS (BS, graduating Dec 2027), targeting SWE and applied-AI
engineering internships at top companies. The project must be something a
senior engineer at a frontier AI company would find genuinely impressive in a
5-minute look, and something Patrick can defend line by line in an interview.

The bar (non-negotiable):
- **Real problem, real users.** It solves a concrete problem people have, and
  ships the way real software ships: a package (PyPI/npm), a hosted demo, a
  CLI, a VS Code extension, or an API. "Toy demo" is a failure.
- **Depth over breadth.** One hard core done properly (retrieval quality,
  agent reliability, evaluation, latency, concurrency, data modelling) beats
  many shallow features. The README's architecture section must name the hard
  part and how it was solved.
- **Measured, not claimed.** Every quality or performance claim comes from an
  evaluation or benchmark the repo can re-run (`make eval`, `make bench`), with
  the dataset, method and raw output recorded in RESULTS.md. Never write a
  number you did not measure. If a measurement needs credentials or hardware
  the CI runner lacks (an LLM API key, a GPU), build the harness, run what you
  can (small local models, mocked baselines clearly labelled), and list the
  exact command for Patrick to run in RESULTS.md under "To measure".
- **Production engineering.** Typed code (mypy/pyright strict or TypeScript
  strict), formatted and linted, unit + integration tests (offline, fast,
  deterministic; network mocked), CI on GitHub Actions, Dockerfile where it
  serves, structured logging, config via env vars, clear errors, no secrets in
  the repo, a LICENSE (MIT), and a README with: what/why, demo (GIF or
  screenshot placeholder with instructions), quickstart, architecture diagram
  (Mermaid), design decisions and trade-offs, results table, roadmap.
- **AI stack, used well.** Prefer: Anthropic Claude API (default model
  `claude-opus-5-5`, via the official `anthropic` SDK), local models through
  Ollama as an offline fallback, embeddings + a vector store, tool use /
  agents, structured outputs, evals. Make the model provider pluggable and
  keep every test runnable without any API key.
- **Patrick's strengths first**: Python, TypeScript/React, SQL/PostgreSQL,
  FastAPI, Docker, AWS, plus whatever new skill the project exists to prove.

Process rules:
- Work in small, reviewable commits with clear messages (imperative mood).
  Never add "Co-Authored-By", "Generated with", or any AI attribution to
  commits, PRs, code comments or docs. Git identity is already configured.
- Use subagents (the Agent tool) to parallelise independent work: e.g. one
  writes tests while another implements, one researches an API while another
  scaffolds. Review their output before committing it.
- Keep PLAN.md as the single source of truth: tick a milestone's checkbox only
  when its definition of done is met and tests pass.
- Never sign up for services, buy anything, publish packages, deploy, or use
  credentials. Prepare releases (build config, workflow with `if:` guards,
  RELEASE.md with exact steps and the secrets Patrick must add).
- Patrick's resume and private data are not in this repo and must never be;
  you only get a short summary of his skills.
- If something is impossible in this environment, say so in the PR body
  rather than faking it.
