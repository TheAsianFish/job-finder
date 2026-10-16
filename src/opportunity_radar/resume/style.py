"""Patrick's resume voice, for every agent that writes bullets (AD-47).

The guide (`agents/prompts/resume-style.md`) is public and describes the
voice in patterns only. `voice_block` adds his own live experience bullets as
examples of that voice; it reads the private resume, so it is only used
where the private repo is available (the tailor, and the voice pass on
project bullets), never in a project build session.
"""

from __future__ import annotations

from pathlib import Path

from opportunity_radar.resume.bank import Bank

GUIDE = Path(__file__).resolve().parents[3] / "agents" / "prompts" / "resume-style.md"
MAX_EXAMPLES = 6


def guide() -> str:
    return GUIDE.read_text(encoding="utf-8") if GUIDE.exists() else ""


def exemplars(bank: Bank, limit: int = MAX_EXAMPLES) -> list[str]:
    """His own shown experience bullets, most recent role first."""
    out: list[str] = []
    entries = sorted(
        (e for e in bank.entries if e.kind == "experience" and e.active and e.is_work),
        key=lambda e: e.start,
        reverse=True,
    )
    for entry in entries:
        for bullet in entry.live_bullets:
            if len(out) < limit:
                out.append(bullet.text)
    return out


def voice_block(bank: Bank) -> str:
    """The guide plus his own bullets as voice examples, for a prompt."""
    text = guide().strip()
    examples = exemplars(bank)
    if examples:
        text += (
            "\n\n## His own bullets (match this voice; never reuse their facts)\n\n"
            + "\n".join(f"- {b}" for b in examples)
        )
    return text
