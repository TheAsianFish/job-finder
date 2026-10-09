"""Claude rewrites resume entries as technical stories, behind a guard.

What changed from the first version (which reworded bullets one at a time,
within +/-15% of the original, without seeing the posting, and produced
bland keyword sprinkles): the writer now gets each whole entry (every true
fact about that job/project, including bullets not currently shown), an
excerpt of the job description, the company, and explicit direction to
write technical, STAR/XYZ-style bullets that tell what was built, the hard
engineering decisions behind it, and the measurable result, in precise
engineering vocabulary, emphasising what this role values.

Truth is enforced by the guard, not by asking nicely. Per entry:
- every number must already appear in that entry's facts,
- every vocabulary skill (language, framework, tool) must be evidenced
  somewhere in the resume,
- every capitalised name or acronym must already appear in the resume
  (plus a short allow-list of generic engineering acronyms such as API),
- bullets must be 80-270 characters.
An entry whose rewrite fails any check keeps its original bullets (all or
nothing, so a story is never half rewritten); the reason is recorded.

The writer may drop an entry's weakest bullet (writing one fewer) and may
build a bullet from any fact of that entry, including reserve and verified
ones. When it believes a stronger bullet exists but needs a fact that is not
written down (a number, scale, tool), it returns that bullet as a
*proposal* instead; bullets rejected by the guard for the same reason become
proposals too. Proposals never reach a resume until Patrick approves them
(proposals.py -> pull request -> verified.yaml).

Claude Code runs headless (`claude -p --model opus`): the Max plan locally
or CLAUDE_CODE_OAUTH_TOKEN in CI; no API key.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field

from opportunity_radar.insights.skills import default_vocabulary
from opportunity_radar.resume.bank import Bank, Bullet, Entry
from opportunity_radar.resume.latex import escape

_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)*")
_PROPER_RE = re.compile(r"\b(?:[A-Z][a-zA-Z0-9+#.\-]*[A-Z0-9][a-zA-Z0-9+#.\-]*|[A-Z][a-z]{2,})\b")
_METRIC_RE = re.compile(r"~?\d[\d,.]*\s?(?:%|x|ms|s\b|K\+?|M\+?|\+)")
GENERIC_ACRONYMS = frozenset(
    [
        "API",
        "APIs",
        "SQL",
        "HTTP",
        "HTTPS",
        "JSON",
        "CRUD",
        "CI",
        "CD",
        "UI",
        "UX",
        "ETL",
        "ORM",
        "SDK",
        "CLI",
        "ID",
        "IDs",
        "CPU",
        "GPU",
        "RAM",
        "IO",
        "OS",
        "LRU",
        "TTL",
        "P95",
        "P99",
        "SLA",
        "SLO",
        "RPC",
        "REST",
        "AST",
        "DAG",
        "URL",
        "URLs",
        "CSV",
        "DB",
        "DBs",
        "ML",
        "AI",
        "LLM",
        "LLMs",
        "VM",
        "VMs",
        "RAG",
        "MVP",
        "QA",
        "PR",
        "PRs",
        "E2E",
        "OOP",
        "TCP",
        "UDP",
        "DNS",
        "JWT",
    ]
)
MIN_CHARS, MAX_CHARS = 80, 270
TOTAL_GROWTH = 1.03  # an entry's rewrite may not be longer overall: one page
DESCRIPTION_EXCERPT = 3500

Runner = Callable[[str], str]  # prompt -> model text


MAX_PROPOSALS = 4
_FACT_FAILURES = ("numbers not in", "skill not in resume", "name or term not in resume")


@dataclass
class Proposal:
    """A bullet Claude thinks is stronger but that needs Patrick's confirmation."""

    entry_id: str
    entry_name: str
    text: str
    confirm: list[str]  # the specific facts Patrick must confirm
    why: str = ""


@dataclass
class PolishOutcome:
    accepted: dict[str, list[str]] = field(default_factory=dict)  # entry id -> LaTeX bullets
    rejected: dict[str, str] = field(default_factory=dict)  # entry id -> reason
    proposals: list[Proposal] = field(default_factory=list)
    skipped_reason: str | None = None


def min_bullets(shown: int) -> int:
    """The writer may drop one weak bullet from an entry showing three or more."""
    return shown - 1 if shown >= 3 else shown


def entry_char_limit(entry: Entry) -> int:
    """Rewrites may not outgrow the entry's longest original bullet by >10%:
    the page budget is the master resume's, and longer bullets would force
    the one-page trimmer to drop real content."""
    longest = max((len(b.text) for b in entry.bullets), default=MAX_CHARS)
    return max(120, min(MAX_CHARS, int(longest * 1.1)))


def entry_min_chars(entry: Entry) -> int:
    """Short originals (e.g. a 45-character research bullet) may stay short."""
    shortest = min((len(b.text) for b in entry.bullets), default=MIN_CHARS)
    return max(40, min(MIN_CHARS, int(shortest * 0.8)))


def guard_bullet(
    text: str,
    entry_numbers: set[str],
    bank: Bank,
    corpus_lower: str,
    entry_text: str,
    max_chars: int = MAX_CHARS,
    min_chars: int = MIN_CHARS,
) -> str | None:
    """None if the bullet is safe, else why it was rejected."""
    stripped = text.strip()
    if not min_chars <= len(stripped) <= max_chars:
        return f"length {len(stripped)} outside {min_chars}-{max_chars}"
    new_numbers = set(_NUMBER_RE.findall(stripped)) - entry_numbers
    if new_numbers:
        return f"numbers not in this entry's facts: {sorted(new_numbers)}"
    bank_skills = bank.all_skills
    for skill in default_vocabulary():
        if (
            skill.found_in(stripped)
            and not skill.found_in(entry_text)
            and skill.name not in bank_skills
        ):
            return f"skill not in resume: {skill.name}"
    starts = {m.start(1) for m in re.finditer(r"(?:^|[.;:]\s+)(\S)", stripped)}
    for match in _PROPER_RE.finditer(stripped):
        word = match.group(0)
        if match.start() in starts and word[1:].islower():
            continue
        if word in GENERIC_ACRONYMS or word.rstrip("s") in GENERIC_ACRONYMS:
            continue
        if word.lower() not in corpus_lower:
            return f"name or term not in resume: {word}"
    return None


def headline_metrics(bullets: list[Bullet]) -> list[str]:
    """The first metric token of each originally-bold phrase ("90%", "100K+")."""
    metrics = []
    for bullet in bullets:
        for phrase in bullet.bold:
            found = _METRIC_RE.search(phrase)
            if found:
                metrics.append(found.group(0).strip())
    return metrics


def to_tex(text: str, metrics: list[str]) -> str:
    """Plain bullet -> LaTeX, bolding only the headline metric(s) the original
    bolded, as whole tokens (never fragments of a range like "2.5-3s")."""
    tex = escape(text.strip())
    for metric in sorted(set(metrics), key=len, reverse=True):
        escaped = escape(metric)
        pattern = re.compile(rf"(?<![\w.\-]){re.escape(escaped)}(?![\w])")
        match = pattern.search(tex)
        if match and "\\textbf{" + escaped not in tex:
            tex = tex[: match.start()] + f"\\textbf{{{escaped}}}" + tex[match.end() :]
    return tex


def build_prompt(
    entries: list[tuple[Entry, list[Bullet]]],
    *,
    title: str,
    company: str,
    description: str,
    skills_line: str,
    guidance: list[str] | None = None,
) -> str:
    payload = []
    for entry, shown in entries:
        payload.append(
            {
                "id": entry.id,
                "kind": entry.kind,
                "heading": entry.name if entry.kind == "project" else f"{entry.title}, {entry.org}",
                "dates": entry.dates,
                "tech": list(entry.tech),
                "bullets_to_write": len(shown),
                "min_bullets": min_bullets(len(shown)),
                "max_chars_per_bullet": entry_char_limit(entry),
                "max_total_chars": int(sum(len(b.text) for b in shown) * TOTAL_GROWTH),
                "facts": [b.text for b in entry.bullets],
            }
        )
    excerpt = (description or "")[:DESCRIPTION_EXCERPT]
    notes = ""
    if guidance:
        notes = (
            "\nA hiring panel (recruiter, hiring manager, interviewer, resume editor) reviewed "
            "the current resume for this role; its lead ranked these changes, most important "
            "first. Apply them wherever the facts allow:\n"
            + "\n".join(f"- {g}" for g in guidance)
            + "\n"
        )
    return f"""You are an expert technical resume writer for software engineering internships and
new-grad roles at top companies. Rewrite each entry below for a candidate applying to
"{title}" at {company}. The page must read as one strong engineer's record: a recruiter
skimming it for six seconds and an engineer reading it closely should come away with the
same clear story. ATS keyword coverage is guaranteed separately (the skills line names
every skill from the posting that the candidate has), so never bend a bullet to fit a
keyword.

What great looks like:
- Every bullet is a complete STAR story in one sentence (Google XYZ form): the Action with
  a strong verb and its technical substance, the Situation/Task compressed into the hard
  part (architecture, data structures, algorithms, concurrency, caching, indexing, query
  planning, API design, testing strategy, failure handling), and the Result: the measured
  outcome when the facts give a number, otherwise the concrete effect (what it enabled,
  replaced or prevented). A bullet with no result is unfinished.
- Use precise engineering vocabulary freely and confidently (e.g. memoized selectors,
  idempotent handlers, pagination pushed into the database, state-transition validation,
  incremental indexing, rank fusion, page-replacement policy). Specific beats generic.
- Lead with strong ownership verbs (Architected, Engineered, Owned, Diagnosed, Optimized,
  Shipped). No "helped", "worked on", "responsible for", no first person.
- Emphasise what THIS role and company value, judging from the job description below.
  Order each entry's bullets so the most relevant story comes first.
- Restructure, don't paraphrase. A rewrite that only swaps synonyms is a failure. Re-lead
  each bullet with the part of the story this role cares most about, cut jargon that
  doesn't serve the role, and replace a generic summary bullet with a more specific fact
  from the same entry when that fact exists.
  Illustration of the transformation (invented example, not this candidate):
    before: "Worked on the billing service and fixed several bugs in it."
    after:  "Diagnosed duplicate charges in the billing service to non-idempotent retries
             and added request-key deduplication, eliminating repeat charges."
- You have editorial control: you may drop an entry's weakest bullet (write min_bullets
  instead of bullets_to_write) and you may build a bullet from ANY fact listed for the entry,
  not only the ones currently shown. Prefer the strongest stories for this role.

Narrative (the page as a whole):
- One consistent story across all entries: who this engineer is for this role. Each entry
  adds different evidence; don't repeat the same claim, verb or keyword bullet after bullet.
- Lead each bullet with the action and its substance, never with a keyword. Where a fact
  truly is what the job description names, use the description's exact term in the natural
  place (if it says "distributed systems" and the fact is one, say so; "LLM orchestration",
  not "AI pipeline"). Spell out a key acronym once when the description uses the long form.
- Never stuff keywords; precision and a believable story beat density.

Truth rules (a strict automated check rejects any violation, and the original wording is
kept instead):
- Use only facts listed for that entry. Do not merge facts across entries.
- Every number must appear in that entry's facts. Never estimate or invent metrics.
- Never add a language, framework, tool, company, product, title or team size that is not
  in that entry's facts or in the candidate's skills: {skills_line}.
- Do not inflate scope (no "led a team", "company-wide", "millions of users" unless stated).

Proposals: if you are confident a clearly stronger bullet for this role exists for an entry
but it needs a fact that is not written down (a metric, scale, tool, or outcome the
candidate would know), do NOT put it in "entries". Put it in "proposals" (at most
{MAX_PROPOSALS} overall, only for high-value gaps), with "confirm" listing each specific fact
the candidate must confirm, phrased as a question. The candidate reviews these by hand.

Format: for each entry write between min_bullets and bullets_to_write bullets, each one
sentence, at most max_chars_per_bullet characters, and all of the entry's bullets together
at most max_total_chars characters (the page must stay one page: tighter wording, not more
of it). Plain text (no LaTeX, no markdown). Reply with only JSON:
{{"entries": [{{"id": "...", "bullets": ["...", "..."]}}],
 "proposals": [{{"id": "entry id", "bullet": "...", "confirm": ["...?"], "why": "..."}}]}}

Job description excerpt:
\"\"\"{excerpt}\"\"\"
{notes}
Entries:
{json.dumps(payload, ensure_ascii=False, indent=1)}
"""


def claude_runner(timeout: int = 420, model: str = "opus") -> Runner | None:
    """A runner backed by the Claude Code CLI, or None if it isn't installed."""
    exe = shutil.which("claude")
    if exe is None:
        return None

    def run(prompt: str) -> str:
        proc = subprocess.run(
            [exe, "-p", prompt, "--output-format", "json", "--max-turns", "1", "--model", model],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"claude exited {proc.returncode}: {proc.stderr.strip()[:200]}")
        envelope = json.loads(proc.stdout)
        if envelope.get("is_error"):
            raise RuntimeError(f"claude error: {str(envelope.get('result'))[:200]}")
        return str(envelope.get("result", ""))

    return run


def parse_json_object(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return {}
    try:
        value = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def rewrite_entries(
    bank: Bank,
    entries: list[tuple[Entry, list[Bullet]]],
    *,
    title: str,
    company: str,
    description: str,
    runner: Runner | None,
    guidance: list[str] | None = None,
) -> PolishOutcome:
    outcome = PolishOutcome()
    if runner is None:
        outcome.skipped_reason = "Claude Code CLI not available"
        return outcome
    if not entries:
        return outcome
    skills_line = "; ".join(f"{k}: {', '.join(v)}" for k, v in bank.skills.items())
    prompt = build_prompt(
        entries,
        title=title,
        company=company,
        description=description,
        skills_line=skills_line,
        guidance=guidance,
    )
    try:
        raw = runner(prompt)
    except Exception as exc:  # network, auth, timeout: never fail the resume
        outcome.skipped_reason = f"rewrite failed: {exc}"
        return outcome
    data = parse_json_object(raw)
    reply = data.get("entries")
    if not isinstance(reply, list):
        outcome.skipped_reason = "model reply was not the requested JSON"
        return outcome
    by_id = {str(item.get("id")): item.get("bullets") for item in reply if isinstance(item, dict)}
    names = {entry.id: entry.name for entry, _ in entries}
    derived: list[Proposal] = []
    corpus_lower = bank.plain_corpus().lower()
    for entry, shown in entries:
        bullets = by_id.get(entry.id)
        if not isinstance(bullets, list) or not bullets:
            continue
        if not min_bullets(len(shown)) <= len(bullets) <= len(shown):
            outcome.rejected[entry.id] = f"wrote {len(bullets)} bullets, expected {len(shown)}"
            continue
        entry_text = (
            " ".join(b.text for b in entry.bullets) + " " + entry.name + " " + " ".join(entry.tech)
        )
        numbers = set(_NUMBER_RE.findall(entry_text))
        metrics = headline_metrics(entry.bullets)
        limit = entry_char_limit(entry) + 15  # small tolerance over the requested cap
        reasons = [
            guard_bullet(
                str(text), numbers, bank, corpus_lower, entry_text, limit, entry_min_chars(entry)
            )
            for text in bullets
        ]
        failed = next((r for r in reasons if r), None)
        budget = int(sum(len(b.text) for b in shown) * TOTAL_GROWTH) + 20
        total = sum(len(str(t).strip()) for t in bullets)
        if failed is None and total > budget:
            failed = f"entry length {total} over budget {budget}"
        if failed:
            outcome.rejected[entry.id] = failed
            # A bullet that failed only for an unconfirmed fact is exactly what
            # Patrick can settle: ask him instead of silently dropping it.
            for text, reason in zip(bullets, reasons, strict=True):
                if reason and reason.startswith(_FACT_FAILURES):
                    derived.append(
                        Proposal(
                            entry_id=entry.id,
                            entry_name=entry.name,
                            text=" ".join(str(text).split()),
                            confirm=[f"Is this accurate? (the check flagged {reason})"],
                            why="rewrite for this role needed a fact not in your resume",
                        )
                    )
            continue
        outcome.accepted[entry.id] = [to_tex(str(text), metrics) for text in bullets]
    for item in data.get("proposals") or []:
        if not isinstance(item, dict) or str(item.get("id")) not in names:
            continue
        text = " ".join(str(item.get("bullet") or "").split())
        if not MIN_CHARS // 2 <= len(text) <= MAX_CHARS:
            continue
        confirm = item.get("confirm")
        outcome.proposals.append(
            Proposal(
                entry_id=str(item["id"]),
                entry_name=names[str(item["id"])],
                text=text,
                confirm=[str(c) for c in confirm] if isinstance(confirm, list) else [],
                why=str(item.get("why") or ""),
            )
        )
    seen: set[str] = set()
    unique = []
    # Deliberate (model-suggested) proposals first, guard-derived ones after.
    for proposal in outcome.proposals + derived:
        key = proposal.text.lower()
        if key not in seen:
            seen.add(key)
            unique.append(proposal)
    outcome.proposals = unique[:MAX_PROPOSALS]
    return outcome
