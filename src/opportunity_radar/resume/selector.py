"""Pick and order true resume content for one posting (no model calls).

Rules, in order of priority (Patrick's call, AD-31):
1. Experience is fixed: every live entry in resume.tex appears, in date
   order; commented-out experience never swaps in. Only its bullets vary.
2. Projects are reshuffled per posting: every project slot goes to the live
   or reserve (commented-out) project that best matches. A reserve must beat
   a live one by a margin to displace it, so curated choices win ties.
3. Bullets inside an entry are reordered by relevance (a live entry's
   opening summary bullet stays first); verified extras (verified.yaml) may
   replace weaker live bullets; near-duplicate wordings never both appear.
4. Skills lines keep every item but put the posting's skills first.
5. The total bullet count never exceeds the master resume's (one page).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from opportunity_radar.insights.skills import Skill, default_vocabulary
from opportunity_radar.resume.bank import Bank, Bullet, Entry

RESERVE_MARGIN = 3.0  # score a reserve entry needs above a live one to replace it
_WORD_RE = re.compile(r"[a-z][a-z0-9+#.\-]{3,}")
_STOP = frozenset(
    [
        "with",
        "that",
        "this",
        "from",
        "your",
        "will",
        "have",
        "years",
        "work",
        "team",
        "teams",
        "build",
        "building",
        "using",
        "about",
        "their",
        "they",
        "such",
        "into",
        "also",
        "more",
        "than",
        "other",
        "within",
        "across",
        "each",
        "what",
        "where",
        "when",
        "which",
        "while",
        "including",
        "strong",
        "ability",
        "experience",
        "skills",
        "role",
        "candidates",
        "candidate",
        "preferred",
        "required",
        "requirements",
        "responsibilities",
        "opportunity",
        "company",
        "please",
        "equal",
        "employment",
    ]
)


@dataclass
class Posting:
    title: str
    text: str
    skills: dict[str, float]  # vocabulary skill -> weight (title mentions count more)
    words: frozenset[str]

    @classmethod
    def from_text(
        cls, title: str, description: str, vocabulary: tuple[Skill, ...] | None = None
    ) -> Posting:
        vocab = vocabulary if vocabulary is not None else default_vocabulary()
        full = f"{title}\n{description}"
        skills: dict[str, float] = {}
        for skill in vocab:
            if skill.category == "soft":
                continue
            if skill.found_in(title):
                skills[skill.name] = 3.0
            elif skill.found_in(description):
                skills[skill.name] = 2.0
        words = frozenset(w for w in _WORD_RE.findall(full.lower()) if w not in _STOP)
        return cls(title=title, text=full, skills=skills, words=words)


@dataclass
class Selection:
    experiences: list[tuple[Entry, list[Bullet]]]
    projects: list[tuple[Entry, list[Bullet]]]
    skills: dict[str, list[str]]
    matched_skills: list[str] = field(default_factory=list)
    swapped_in: list[str] = field(default_factory=list)
    swapped_out: list[str] = field(default_factory=list)

    @property
    def bullets(self) -> list[Bullet]:
        return [b for _, bullets in self.experiences + self.projects for b in bullets]


def bullet_score(bullet: Bullet, posting: Posting) -> float:
    skill_points = sum(posting.skills.get(s, 0.0) for s in bullet.skills)
    words = frozenset(w for w in _WORD_RE.findall(bullet.text.lower()) if w not in _STOP)
    lexical = min(len(words & posting.words) * 0.15, 3.0)
    impact = 0.5 if bullet.has_metric else 0.0
    return skill_points + lexical + impact


def entry_score(entry: Entry, posting: Posting) -> float:
    scores = sorted((bullet_score(b, posting) for b in entry.bullets), reverse=True)
    tech_hits = sum(
        posting.skills.get(name, 0.0)
        for name in posting.skills
        if any(name.lower() == t.lower() for t in entry.tech)
    )
    return sum(scores[:2]) + tech_hits


def _similar(a: Bullet, b: Bullet) -> bool:
    wa = set(_WORD_RE.findall(a.text.lower()))
    wb = set(_WORD_RE.findall(b.text.lower()))
    if not wa or not wb:
        return False
    return len(wa & wb) / len(wa | wb) >= 0.5


def _pick_bullets(entry: Entry, posting: Posting, limit: int) -> list[Bullet]:
    """Most relevant bullets first, except that a live entry's opening bullet
    (usually the one-line summary of what it is) keeps its place."""
    ranked = sorted(entry.bullets, key=lambda b: bullet_score(b, posting), reverse=True)
    if entry.active and entry.bullets:
        ranked.remove(entry.bullets[0])
        ranked.insert(0, entry.bullets[0])
    chosen: list[Bullet] = []
    for bullet in ranked:
        if any(_similar(bullet, other) for other in chosen):
            continue
        chosen.append(bullet)
        if len(chosen) >= limit:
            break
    return chosen


def _entity(entry: Entry) -> str:
    """The thing an entry is about ("neuranote"), so one venture never appears
    twice (e.g. as both an experience and a project)."""
    source = entry.org if entry.kind == "experience" and entry.org else entry.name
    words = [w for w in re.findall(r"[a-z0-9]+", source.lower()) if len(w) > 2]
    return words[0] if words else entry.id


def _fill_slots(
    live: list[Entry],
    reserves: list[Entry],
    slots: int,
    posting: Posting,
    exclude_entities: frozenset[str] = frozenset(),
) -> tuple[list[Entry], list[str], list[str]]:
    """Choose `slots` entries, preferring live ones unless a reserve clearly wins."""
    pool = [e for e in live + reserves if _entity(e) not in exclude_entities]
    scored = [(entry_score(e, posting) + (RESERVE_MARGIN if e.active else 0.0), e) for e in pool]
    scored.sort(key=lambda pair: (pair[0], pair[1].active, -pair[1].order), reverse=True)
    chosen = [e for _, e in scored[:slots]]
    swapped_in = [e.name for e in chosen if not e.active]
    swapped_out = [e.name for e in live if e not in chosen]
    return chosen, swapped_in, swapped_out


def _matches_name(entry: Entry, wanted: str) -> bool:
    """Loose match of a reviewer's free-text suggestion to a bank entry."""
    target = re.sub(r"[^a-z0-9]+", " ", wanted.lower())
    for candidate in (entry.name, entry.org, entry.title):
        words = [
            w for w in re.sub(r"[^a-z0-9]+", " ", (candidate or "").lower()).split() if len(w) > 3
        ]
        if words and sum(w in target for w in words) >= min(2, len(words)):
            return True
    return False


def _apply_preferences(
    chosen: list[Entry],
    reserves: list[Entry],
    prefer: list[str],
    protected: list[Entry],
    posting: Posting,
) -> list[str]:
    """Swap reviewer-recommended reserve entries in for the weakest unprotected
    chosen entries (in place). Returns the names swapped in."""
    swapped: list[str] = []
    for wanted in prefer:
        entry = next((e for e in reserves if e not in chosen and _matches_name(e, wanted)), None)
        if entry is None:
            continue
        candidates = [e for e in chosen if e not in protected and e.active]
        if not candidates:
            break
        weakest = min(candidates, key=lambda e: entry_score(e, posting))
        chosen[chosen.index(weakest)] = entry
        swapped.append(entry.name)
    return swapped


def select(bank: Bank, posting: Posting, prefer: list[str] | None = None) -> Selection:
    """prefer: reserve projects a reviewer recommended (free text, loosely
    matched); they replace the weakest live projects."""
    experiences = sorted(
        (e for e in bank.experiences if e.active), key=lambda e: e.start, reverse=True
    )
    live_proj = [e for e in bank.projects if e.active]
    reserves_proj = [e for e in bank.projects if not e.active]
    taken = frozenset(_entity(e) for e in experiences)
    proj_chosen, proj_in, proj_out = _fill_slots(
        live_proj, reserves_proj, len(live_proj), posting, exclude_entities=taken
    )
    if prefer:
        proj_in += _apply_preferences(proj_chosen, reserves_proj, prefer, [], posting)
        proj_out = [e.name for e in live_proj if e not in proj_chosen]

    budget = sum(len(e.live_bullets) for e in experiences + live_proj)

    def limit_for(entry: Entry) -> int:
        if entry.active:
            return len(entry.live_bullets)
        displaced = [e for e in live_proj if e not in proj_chosen]
        return max((len(e.live_bullets) for e in displaced), default=2)

    exp_sel = [(e, _pick_bullets(e, posting, limit_for(e))) for e in experiences]
    proj_order = sorted(proj_chosen, key=lambda e: entry_score(e, posting), reverse=True)
    proj_sel = [(e, _pick_bullets(e, posting, limit_for(e))) for e in proj_order]
    _enforce_budget(exp_sel, proj_sel, budget, posting)

    skills = {
        label: sorted(items, key=lambda item: (not _item_matches(item, posting), items.index(item)))
        for label, items in bank.skills.items()
    }
    shown_text = (
        " ".join(b.text for _, bs in exp_sel + proj_sel for b in bs)
        + " "
        + " ".join(", ".join(v) for v in skills.values())
        + " "
        + " ".join(", ".join(e.tech) for e, _ in proj_sel)
    )
    vocab = {s.name: s for s in default_vocabulary()}
    matched = [
        name for name in posting.skills if name in vocab and vocab[name].found_in(shown_text)
    ]
    return Selection(
        experiences=exp_sel,
        projects=proj_sel,
        skills=skills,
        matched_skills=matched,
        swapped_in=proj_in,
        swapped_out=proj_out,
    )


def _item_matches(item: str, posting: Posting) -> bool:
    vocab = default_vocabulary()
    return any(skill.name in posting.skills and skill.found_in(item) for skill in vocab)


def _enforce_budget(
    exp_sel: list[tuple[Entry, list[Bullet]]],
    proj_sel: list[tuple[Entry, list[Bullet]]],
    budget: int,
    posting: Posting,
) -> None:
    """Drop the least relevant bullets (never an entry's last two) until within budget."""
    while sum(len(bs) for _, bs in exp_sel + proj_sel) > budget:
        candidates = [
            (bullet_score(b, posting), i, b)
            for i, (_, bs) in enumerate(exp_sel + proj_sel)
            if len(bs) > 2
            for b in bs
        ]
        if not candidates:
            return
        _, index, worst = min(candidates, key=lambda c: c[0])
        target = (exp_sel + proj_sel)[index][1]
        target.remove(worst)
