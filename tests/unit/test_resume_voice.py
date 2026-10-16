"""Patrick's voice (AD-47): the guide, his examples, and the guarded voice pass."""

from __future__ import annotations

import json

from opportunity_radar.resume.bank import build_bank
from opportunity_radar.resume.latex import to_plain
from opportunity_radar.resume.polish import build_prompt, revoice_project, voice_problems
from opportunity_radar.resume.style import exemplars, guide, voice_block
from tests.conftest import load_fixture

TEX = load_fixture("resume_sample.tex")
BANK = build_bank(TEX)
CORPUS = to_plain(TEX)
ENTRY = r"""\resumeProjectHeading
  {\textbf{Replay --- Regression Testing for LLM Agents} $|$ \emph{Python, FastAPI} $|$ \href{https://github.com/TheAsianFish/agent-replay}{\textcolor{blue}{GitHub}}}{}
  \resumeItemListStart
    \resumeItem{Built a Python recorder for agent runs replayed at chosen cut points; cut-point replay caught \textbf{12/12} seeded model regressions}
    \resumeItem{Built a flakiness gate over 150 live runs that surfaced a 1-in-120 policy breach a single CI run would miss}
    \resumeItem{Built a FastAPI service with a replay suite taking 222 ms vs 51 s live}
  \resumeItemListEnd
"""


def runner_returning(bullets):
    return lambda prompt: json.dumps({"bullets": bullets})


GOOD = [
    "Engineered record-and-replay testing for LLM agents with replay from chosen cut points, "
    "catching 12 of 12 seeded model regressions",
    "Surfaced a 1-in-120 policy breach a single CI run would miss by gating agents on a "
    "flakiness test over 150 live runs",
    "Accelerated regression checks from 51 s live to 222 ms by replaying recorded runs behind "
    "a FastAPI service",
]


def test_guide_is_public_patterns_and_examples_are_his_own_bullets():
    text = guide()
    assert "Weak (never as the lead verb)" in text and "Made, Kept, Cut" in text
    examples = exemplars(BANK)
    assert examples and all(b in CORPUS or b[:30] in CORPUS for b in examples)
    assert "His own bullets" in voice_block(BANK)


def test_tailor_prompt_carries_the_voice_not_generic_verbs():
    entry = next(e for e in BANK.entries if e.kind == "experience")
    prompt = build_prompt(
        [(entry, entry.live_bullets)],
        title="Intern",
        company="Acme",
        description="Python",
        skills_line="Python",
        voice=voice_block(BANK),
    )
    assert "The candidate's voice" in prompt and "Made, Kept, Cut" in prompt
    assert "Lead with strong ownership verbs (Architected" not in prompt


def test_voice_pass_applies_a_guarded_rewrite_and_keeps_the_heading():
    new, note = revoice_project(ENTRY, BANK, runner_returning(GOOD), corpus=CORPUS)
    assert note.startswith("applied"), note
    assert new.startswith(ENTRY.split("\\resumeItemListStart")[0].rstrip())
    assert new.count("\\resumeItem{") == 3 and "\\textbf{12}" not in new
    assert "Built" not in new


def test_voice_pass_rejects_invented_numbers_weak_and_repeated_verbs():
    invented = [GOOD[0].replace("12 of 12", "15 of 15"), *GOOD[1:]]
    new, note = revoice_project(ENTRY, BANK, runner_returning(invented), corpus=CORPUS)
    assert new == ENTRY and "guard rejected" in note and "15" in note

    weak = ["Made " + GOOD[0].split(" ", 1)[1], *GOOD[1:]]
    new, note = revoice_project(ENTRY, BANK, runner_returning(weak), corpus=CORPUS)
    assert new == ENTRY and "weak lead verb: made" in note

    assert voice_problems(["Built a b c", "Built d e f"]) == ["repeated lead verb: built"]
    assert voice_problems(["Kept x", "Cut y"]) == ["weak lead verb: kept", "weak lead verb: cut"]


def test_voice_pass_never_fails_the_pr():
    def broken(prompt):
        raise RuntimeError("usage limit")

    assert revoice_project(ENTRY, BANK, broken, corpus=CORPUS)[0] == ENTRY
    assert revoice_project(ENTRY, BANK, None, corpus=CORPUS)[1].startswith("skipped")
    too_few = runner_returning(GOOD[:1])
    assert "1 bullets returned" in revoice_project(ENTRY, BANK, too_few, corpus=CORPUS)[1]


def test_voice_pass_bolds_only_a_numbered_phrase_from_the_bullet_itself():
    items = [
        {"text": GOOD[0], "bold": "12 of 12 seeded model regressions"},
        {"text": GOOD[1], "bold": "a phrase that is not in the bullet 1"},
        {"text": GOOD[2], "bold": "regression checks"},  # no number: not bolded
    ]
    new, note = revoice_project(
        ENTRY, BANK, lambda prompt: json.dumps({"bullets": items}), corpus=CORPUS
    )
    assert note.startswith("applied"), note
    items_tex = new.split("\\resumeItemListStart")[1]
    assert items_tex.count("\\textbf{") == 1
    assert "\\textbf{12 of 12 seeded model regressions}" in items_tex
