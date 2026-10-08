"""Bullet bank: the resume as structured, truthful building blocks.

Built from the user's LaTeX (Jake's template macros). Live entries are what
the master resume shows; commented-out entries and bullets are the *bank*:
true content the tailor may swap in when a posting needs it. Nothing in a
tailored resume can come from anywhere else.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from opportunity_radar.insights.skills import Skill, default_vocabulary
from opportunity_radar.resume.latex import (
    MacroCall,
    SectionText,
    bold_phrases,
    find_macros,
    split_sections,
    to_plain,
)

_MONTHS = {
    m: i
    for i, names in enumerate(
        [
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ],
        start=1,
    )
    for m in names
}
_DATE_RE = re.compile(r"([A-Za-z]{3,9})\.?\s+(20\d\d)")
_WORK_TITLE_RE = re.compile(
    r"intern|engineer|developer|worker|analyst|assistant|researcher|founder|scientist|lead",
    re.IGNORECASE,
)


@dataclass
class Bullet:
    id: str
    tex: str
    text: str
    skills: frozenset[str]
    bold: tuple[str, ...]
    has_metric: bool
    verified: bool = False  # approved via a proposal PR (verified.yaml), not in resume.tex


@dataclass
class Entry:
    id: str
    kind: str  # "experience" | "project"
    active: bool
    heading_tex: str  # the full heading macro call, re-emitted verbatim
    name: str  # project name, or "Title @ Org"
    title: str = ""
    org: str = ""
    dates: str = ""
    location: str = ""
    tech: tuple[str, ...] = ()
    bullets: list[Bullet] = field(default_factory=list)
    order: int = 0

    @property
    def start(self) -> date:
        match = _DATE_RE.search(self.dates)
        if not match:
            return date(1900, 1, 1)
        word = match.group(1).lower()
        month = _MONTHS.get(word) or _MONTHS.get(word[:3], 1)
        return date(int(match.group(2)), month, 1)

    @property
    def live_bullets(self) -> list[Bullet]:
        """The bullets resume.tex itself shows for this entry (not verified extras)."""
        return [b for b in self.bullets if not b.verified]

    @property
    def is_work(self) -> bool:
        return self.kind == "experience" and bool(_WORK_TITLE_RE.search(self.title))

    @property
    def skills(self) -> frozenset[str]:
        found: set[str] = set(_skills_in(", ".join(self.tech))) if self.tech else set()
        for bullet in self.bullets:
            found |= bullet.skills
        return frozenset(found)


@dataclass
class Bank:
    preamble: str  # documentclass ... \begin{document} + contact header
    education_tex: str  # the live Education section body, verbatim
    experiences: list[Entry]
    projects: list[Entry]
    skills: dict[str, list[str]]  # "Languages" -> [...], in resume order
    candidate_name: str
    section_names: dict[str, str]  # canonical -> heading as written

    @property
    def entries(self) -> list[Entry]:
        return self.experiences + self.projects

    @property
    def all_skills(self) -> frozenset[str]:
        """Vocabulary skills evidenced anywhere in the bank (live or reserve)."""
        found: set[str] = set()
        for entry in self.entries:
            found |= entry.skills
        line_text = " ".join(", ".join(items) for items in self.skills.values())
        found |= set(_skills_in(line_text))
        return frozenset(found)

    def plain_corpus(self) -> str:
        """All bank text: anything a rewrite says must already appear here."""
        parts = [to_plain(self.preamble), to_plain(self.education_tex)]
        for entry in self.entries:
            parts += [entry.name, entry.title, entry.org, entry.location, ", ".join(entry.tech)]
            parts += [b.text for b in entry.bullets]
        parts += [", ".join(items) for items in self.skills.values()]
        return "\n".join(parts)


def _skills_in(text: str, vocabulary: tuple[Skill, ...] | None = None) -> list[str]:
    vocab = vocabulary if vocabulary is not None else default_vocabulary()
    return [skill.name for skill in vocab if skill.found_in(text)]


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "entry"


def _bullets(calls: list[MacroCall], entry_id: str, extra_text: str) -> list[Bullet]:
    bullets = []
    for index, call in enumerate(calls):
        tex = call.args[0].strip()
        text = to_plain(tex)
        if not text:
            continue
        skills = frozenset(_skills_in(f"{text}\n{extra_text}"))
        bullets.append(
            Bullet(
                id=f"{entry_id}-{index}",
                tex=tex,
                text=text,
                skills=skills,
                bold=tuple(bold_phrases(tex)),
                has_metric=bool(re.search(r"\d", text)),
            )
        )
    return bullets


def _entries_from(text: str, kind: str, active: bool, order_offset: int) -> list[Entry]:
    heading_name = "resumeSubheading" if kind == "experience" else "resumeProjectHeading"
    nargs = 4 if kind == "experience" else 2
    headings = find_macros(text, heading_name, nargs)
    items = find_macros(text, "resumeItem", 1)
    entries: list[Entry] = []
    for index, heading in enumerate(headings):
        end = headings[index + 1].start if index + 1 < len(headings) else len(text)
        owned = [item for item in items if heading.end <= item.start < end]
        heading_tex = text[heading.start : heading.end]
        if kind == "experience":
            title, dates, org, location = (to_plain(a) for a in heading.args)
            name = f"{title} @ {org}"
            tech: tuple[str, ...] = ()
        else:
            first = heading.args[0]
            bold = find_macros(first, "textbf", 1)
            name = to_plain(bold[0].args[0]) if bold else to_plain(first).split("|")[0].strip()
            emph = find_macros(first, "emph", 1)
            tech = tuple(t.strip() for t in to_plain(emph[0].args[0]).split(",")) if emph else ()
            title, dates, org, location = "", to_plain(heading.args[1]), "", ""
        entry_id = _slug(name)
        entries.append(
            Entry(
                id=entry_id,
                kind=kind,
                active=active,
                heading_tex=heading_tex,
                name=name,
                title=title,
                org=org,
                dates=dates,
                location=location,
                tech=tech,
                # The entry name ("Toy OS Kernel") is evidence for every bullet;
                # the tech stack is credited once, at entry level (see skills).
                bullets=_bullets(owned, entry_id, name),
                order=order_offset + index,
            )
        )
    return [e for e in entries if e.bullets]


def _skill_lines(section: SectionText | None) -> dict[str, list[str]]:
    if section is None:
        return {}
    lines: dict[str, list[str]] = {}
    for call in find_macros(section.active, "textbf", 1):
        group_start = call.end
        rest = section.active[group_start:]
        match = re.match(r"\s*\{:\s*(.*?)\}", rest, re.DOTALL)
        if not match:
            continue
        items = [to_plain(i).strip().rstrip(".") for i in match.group(1).split(",")]
        lines[to_plain(call.args[0])] = [i for i in items if i]
    return lines


def _find(sections: list[SectionText], *names: str) -> SectionText | None:
    for section in sections:
        if any(n in section.name.lower() for n in names):
            return section
    return None


def build_bank(source: str) -> Bank:
    preamble, sections = split_sections(source)
    education = _find(sections, "education")
    experience = _find(sections, "experience")
    projects = _find(sections, "project")
    skills = _find(sections, "skill")
    exp_entries: list[Entry] = []
    proj_entries: list[Entry] = []
    if experience:
        exp_entries = _entries_from(experience.active, "experience", True, 0)
        exp_entries += _entries_from(experience.commented, "experience", False, 100)
    if projects:
        proj_entries = _entries_from(projects.active, "project", True, 0)
        proj_entries += _entries_from(projects.commented, "project", False, 100)
    _dedupe_ids(exp_entries + proj_entries)
    name_match = re.search(r"\\scshape\s+([^}]+)\}", preamble) or re.search(
        r"\\Huge[^{}]*?([A-Z][A-Za-z.\- ]+)", preamble
    )
    return Bank(
        preamble=preamble,
        education_tex=education.active if education else "",
        experiences=exp_entries,
        projects=proj_entries,
        skills=_skill_lines(skills),
        candidate_name=to_plain(name_match.group(1)).strip() if name_match else "Resume",
        section_names={
            key: section.name
            for key, section in (
                ("education", education),
                ("experience", experience),
                ("projects", projects),
                ("skills", skills),
            )
            if section is not None
        },
    )


def _dedupe_ids(entries: list[Entry]) -> None:
    seen: dict[str, int] = {}
    for entry in entries:
        count = seen.get(entry.id, 0)
        seen[entry.id] = count + 1
        if count:
            entry.id = f"{entry.id}-{count + 1}"
            for index, bullet in enumerate(entry.bullets):
                bullet.id = f"{entry.id}-{index}"
