"""Optional Claude rewording of selected bullets, behind a fabrication guard.

Claude Code runs headless (`claude -p`), so it uses whatever the user's
Claude login provides: the Max plan locally, or CLAUDE_CODE_OAUTH_TOKEN in
CI. No API key is involved. If the CLI or a login is missing, polishing is
skipped and the deterministic tailoring stands on its own.

The guard is the point: a rewrite is accepted only if every number in it
appears in the original bullet, every vocabulary skill in it is evidenced
somewhere in the bank, every capitalised word or acronym already appears in
the bank, and its length stays close to the original. Anything else falls
back to the original wording, with the reason recorded.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field

from opportunity_radar.insights.skills import default_vocabulary
from opportunity_radar.resume.bank import Bank, Bullet
from opportunity_radar.resume.latex import escape

_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)*")
_PROPER_RE = re.compile(r"\b(?:[A-Z][a-zA-Z0-9+#.\-]*[A-Z0-9][a-zA-Z0-9+#.\-]*|[A-Z][a-z]{2,})\b")
MAX_GROWTH = 1.20
MIN_SHRINK = 0.60

Runner = Callable[[str], str]  # prompt -> model text


@dataclass
class PolishOutcome:
    accepted: dict[str, str] = field(default_factory=dict)  # bullet id -> new LaTeX
    rejected: dict[str, str] = field(default_factory=dict)  # bullet id -> reason
    skipped_reason: str | None = None


def guard(original: Bullet, rewrite: str, bank: Bank, corpus_lower: str) -> str | None:
    """Return None if the rewrite is safe, else the reason it was rejected."""
    text = rewrite.strip()
    if not text:
        return "empty rewrite"
    if not MIN_SHRINK * len(original.text) <= len(text) <= MAX_GROWTH * len(original.text) + 10:
        return f"length {len(text)} vs original {len(original.text)}"
    original_numbers = set(_NUMBER_RE.findall(original.text))
    new_numbers = set(_NUMBER_RE.findall(text)) - original_numbers
    if new_numbers:
        return f"new numbers {sorted(new_numbers)}"
    bank_skills = bank.all_skills
    for skill in default_vocabulary():
        if (
            skill.found_in(text)
            and not skill.found_in(original.text)
            and skill.name not in bank_skills
        ):
            return f"skill not in resume: {skill.name}"
    sentence_start = {m.start() for m in re.finditer(r"(?:^|[.;:]\s+)(\S)", text)}
    for match in _PROPER_RE.finditer(text):
        word = match.group(0)
        if match.start() in sentence_start and word[1:].islower():
            continue  # ordinary capitalised first word ("Built", "Designed")
        if word.lower() not in corpus_lower:
            return f"name or term not in resume: {word}"
    return None


def to_tex(rewrite: str, original: Bullet) -> str:
    """Plain rewrite -> LaTeX, re-bolding phrases that were bold originally."""
    tex = escape(rewrite.strip())
    for phrase in original.bold:
        escaped = escape(phrase)
        if escaped in tex:
            tex = tex.replace(escaped, f"\\textbf{{{escaped}}}", 1)
    return tex


def build_prompt(bullets: list[Bullet], keywords: list[str], title: str) -> str:
    payload = [{"id": b.id, "text": b.text} for b in bullets]
    return (
        "You edit resume bullets for an internship application. Rewrite each bullet so a "
        f"recruiter and an ATS screening for '{title}' see the relevant skills, using these "
        f"keywords only where the bullet's own facts support them: {', '.join(keywords) or 'none'}.\n"
        "Hard rules: keep every fact and number exactly; add no new numbers, tools, "
        "employers, metrics or claims; strong past-tense verb first; one sentence; length "
        "within 15% of the original. If a bullet cannot honestly use a keyword, keep its "
        "meaning and wording close to the original.\n"
        'Reply with only a JSON array: [{"id": "...", "text": "..."}].\n\n'
        f"Bullets:\n{json.dumps(payload, ensure_ascii=False)}"
    )


def claude_runner(timeout: int = 240) -> Runner | None:
    """A runner backed by the Claude Code CLI, or None if it isn't installed."""
    exe = shutil.which("claude")
    if exe is None:
        return None

    def run(prompt: str) -> str:
        proc = subprocess.run(
            [exe, "-p", prompt, "--output-format", "json", "--max-turns", "1"],
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


def _parse(text: str) -> dict[str, str]:
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        return {}
    try:
        items = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
    return {
        str(item["id"]): str(item["text"])
        for item in items
        if isinstance(item, dict) and "id" in item and "text" in item
    }


def polish(
    bank: Bank,
    bullets: list[Bullet],
    keywords: list[str],
    title: str,
    runner: Runner | None,
) -> PolishOutcome:
    outcome = PolishOutcome()
    if runner is None:
        outcome.skipped_reason = "Claude Code CLI not available"
        return outcome
    if not bullets:
        return outcome
    try:
        raw = runner(build_prompt(bullets, keywords, title))
    except Exception as exc:  # network, auth, timeout: never fail the resume
        outcome.skipped_reason = f"polish failed: {exc}"
        return outcome
    rewrites = _parse(raw)
    if not rewrites:
        outcome.skipped_reason = "model reply was not the requested JSON"
        return outcome
    corpus_lower = bank.plain_corpus().lower()
    for bullet in bullets:
        rewrite = rewrites.get(bullet.id)
        if rewrite is None:
            continue
        if rewrite.strip() == bullet.text.strip():
            continue
        reason = guard(bullet, rewrite, bank, corpus_lower)
        if reason:
            outcome.rejected[bullet.id] = reason
        else:
            outcome.accepted[bullet.id] = to_tex(rewrite, bullet)
    return outcome
