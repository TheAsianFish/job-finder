"""Tailor the resume to one posting, end to end.

select (deterministic) -> optional guarded polish -> render in the user's
template -> compile with pdfLaTeX -> trim until one page -> ATS report ->
write .tex / .pdf / ats.md / meta.json. Never raises for a missing compiler
or Claude login: the .tex and report are still produced and the reason is
recorded.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

import yaml

from opportunity_radar.resume.ats import AtsReport, analyse, render_markdown
from opportunity_radar.resume.bank import Bank, build_bank
from opportunity_radar.resume.compiler import CompileError, compile_tex, inspect_pdf
from opportunity_radar.resume.latex import to_plain
from opportunity_radar.resume.paths import private_dir, resume_source
from opportunity_radar.resume.polish import PolishOutcome, Runner, rewrite_entries
from opportunity_radar.resume.render import render
from opportunity_radar.resume.selector import Posting, Selection, bullet_score, select

MAX_TRIM_ROUNDS = 4

# Role-family versions: a synthetic posting per family. Skills are refreshed
# from live demand when the job database is available (see variant_postings).
FAMILY_POSTINGS: dict[str, tuple[str, str]] = {
    "backend": (
        "Backend Software Engineer Intern",
        "Python Java SQL PostgreSQL REST APIs microservices distributed systems AWS Docker "
        "Kubernetes CI/CD databases",
    ),
    "ai-ml": (
        "Machine Learning / AI Engineer Intern",
        "Python machine learning deep learning LLMs PyTorch data pipelines AWS Docker Kubernetes",
    ),
    "fullstack": (
        "Full Stack Software Engineer Intern",
        "React TypeScript JavaScript HTML/CSS REST APIs Node.js PostgreSQL SQL AWS CI/CD",
    ),
    "infrastructure": (
        "Infrastructure / Platform Engineer Intern",
        "Kubernetes Docker AWS Linux CI/CD Terraform distributed systems Python Go monitoring",
    ),
    "general": (
        "Software Engineer Intern",
        "Python Java C++ data structures algorithms object-oriented programming Git SQL",
    ),
}


@dataclass
class TailorResult:
    out_dir: Path
    tex_path: Path
    pdf_path: Path | None
    report: AtsReport
    selection: Selection
    polish: PolishOutcome | None
    compile_error: str | None = None
    trimmed: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        parts = [f"keyword coverage {self.report.coverage:.0%}"]
        if self.report.baseline_coverage is not None:
            parts[-1] += f" (master {self.report.baseline_coverage:.0%})"
        if self.selection.ats_added:
            parts.append("skills line now names " + ", ".join(self.selection.ats_added))
        if self.report.true_gaps:
            parts.append("not on your resume: " + ", ".join(self.report.true_gaps[:4]))
        if self.selection.swapped_in:
            parts.append("swapped in " + ", ".join(self.selection.swapped_in))
        if self.polish and self.polish.accepted:
            parts.append(f"{len(self.polish.accepted)} entries rewritten")
        if self.polish and self.polish.proposals:
            parts.append(f"{len(self.polish.proposals)} bullet proposal(s) for your review")
        return "; ".join(parts)


def slug(text: str, limit: int = 40) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:limit] or "x"


def load_bank(path: Path | None = None) -> Bank:
    """resume.tex plus the bullets Patrick verified (verified.yaml beside it)."""
    from opportunity_radar.resume.verified import apply_verified, load_verified

    source = path or resume_source()
    if not source.exists():
        raise FileNotFoundError(
            f"resume source not found at {source} (clone the private career repo there)"
        )
    bank = build_bank(source.read_text(encoding="utf-8"))
    apply_verified(bank, load_verified(source.parent / "verified.yaml"))
    bank.pinned_projects = load_pinned(source.parent / RULES_FILE)
    return bank


RULES_FILE = "resume_rules.yaml"


def load_pinned(path: Path) -> list[str]:
    """Project names Patrick always wants shown (private resume_rules.yaml)."""
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [str(name) for name in raw.get("pinned_projects") or [] if str(name).strip()]


def master_text(bank: Bank) -> str:
    """Plain text of the master resume: its PDF if present, else its live LaTeX."""
    for pdf in sorted(private_dir().glob("*.pdf")):
        try:
            return inspect_pdf(pdf).text
        except Exception:  # unreadable PDF: fall back to the source text
            break
    live = [e for e in bank.entries if e.active]
    return "\n".join(
        [to_plain(bank.preamble), to_plain(bank.education_tex)]
        + [f"{e.name} {' '.join(e.tech)} " + " ".join(b.text for b in e.live_bullets) for e in live]
        + [", ".join(v) for v in bank.skills.values()]
    )


def _trim(selection: Selection, posting: Posting) -> str | None:
    """Remove the least relevant bullet from an entry with more than two."""
    candidates = [
        (bullet_score(b, posting), entry, b)
        for entry, bullets in selection.experiences + selection.projects
        if len(bullets) > 2
        for b in bullets
    ]
    if not candidates:
        if len(selection.projects) > 2:
            entry, _ = selection.projects.pop()
            return f"dropped project {entry.name}"
        return None
    _, entry, worst = min(candidates, key=lambda c: c[0])
    for owner, bullets in selection.experiences + selection.projects:
        if owner is entry:
            bullets.remove(worst)
            break
    return f"trimmed a bullet from {entry.name}"


def tailor(
    bank: Bank,
    *,
    title: str,
    company: str,
    description: str,
    out_dir: Path,
    runner: Runner | None = None,
    compile_pdf: bool = True,
    baseline_text: str | None = None,
    meta: dict | None = None,
    guidance: list[str] | None = None,
    prefer: list[str] | None = None,
) -> TailorResult:
    posting = Posting.from_text(title, description)
    selection = select(bank, posting, prefer=prefer)
    outcome: PolishOutcome | None = None
    overrides: dict[str, list[str]] = {}
    if runner is not None:
        outcome = rewrite_entries(
            bank,
            selection.experiences + selection.projects,
            title=title,
            company=company,
            description=description,
            runner=runner,
            guidance=guidance,
        )
        overrides = dict(outcome.accepted)

    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_name = (
        f"{slug(bank.candidate_name).replace('-', '_').title()}_Resume_{slug(company, 24)}.pdf"
    )
    pdf_path: Path | None = out_dir / pdf_name
    compile_error = None
    trimmed: list[str] = []
    reverted: list[str] = []
    tex = render(bank, selection, overrides)
    text_for_report = to_plain(tex)
    pages: int | None = None
    if compile_pdf:
        try:
            for _ in range(MAX_TRIM_ROUNDS + len(overrides) + 1):
                compiled = compile_tex(tex, pdf_path)  # type: ignore[arg-type]
                pages, text_for_report = compiled.pages, compiled.text
                if compiled.pages <= 1:
                    break
                # Overflow: undo the longest rewrite before cutting real content.
                if overrides:
                    longest = max(overrides, key=lambda k: sum(len(t) for t in overrides[k]))
                    overrides.pop(longest)
                    reverted.append(longest)
                else:
                    note = _trim(selection, posting)
                    if note is None:
                        break
                    trimmed.append(note)
                tex = render(bank, selection, overrides)
            # Rewrites must never lose keywords that the same selection shows
            # unrewritten (selection-level trade-offs, e.g. a reviewer-advised
            # swap, are judged by the reviewer, not undone here).
            if overrides:
                rewritten_cov = analyse(text_for_report, posting, bank).coverage
                plain_cov = analyse(to_plain(render(bank, selection, {})), posting, bank).coverage
                if rewritten_cov + 1e-9 < plain_cov:
                    reverted.extend(overrides)
                    overrides = {}
                    tex = render(bank, selection, overrides)
                    compiled = compile_tex(tex, pdf_path)  # type: ignore[arg-type]
                    pages, text_for_report = compiled.pages, compiled.text
        except CompileError as exc:
            compile_error = str(exc)
            pdf_path = None
    else:
        pdf_path = None

    tex_path = out_dir / "resume.tex"
    tex_path.write_text(tex, encoding="utf-8")
    report = analyse(text_for_report, posting, bank, pages=pages, baseline_text=baseline_text)
    (out_dir / "ats.md").write_text(render_markdown(report, title, company), encoding="utf-8")
    record = {
        "title": title,
        "company": company,
        "generated": date.today().isoformat(),
        "experiences": [e.name for e, _ in selection.experiences],
        "projects": [e.name for e, _ in selection.projects],
        "swapped_in": selection.swapped_in,
        "swapped_out": selection.swapped_out,
        "matched_skills": selection.matched_skills,
        "ats_added": selection.ats_added,
        "pinned_projects": bank.pinned_projects,
        "polish_accepted": sorted(outcome.accepted) if outcome else [],
        "polish_rejected": outcome.rejected if outcome else {},
        "polish_skipped": outcome.skipped_reason if outcome else "not requested",
        "proposals": [asdict(p) for p in outcome.proposals] if outcome else [],
        "trimmed": trimmed,
        "rewrites_reverted": reverted,
        "rewrites_kept": sorted(overrides),
        "compile_error": compile_error,
        "ats": asdict(report),
        **(meta or {}),
    }
    (out_dir / "meta.json").write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
    return TailorResult(
        out_dir=out_dir,
        tex_path=tex_path,
        pdf_path=pdf_path,
        report=report,
        selection=selection,
        polish=outcome,
        compile_error=compile_error,
        trimmed=trimmed,
    )


def variant_postings(demand: dict[str, list[str]] | None = None) -> dict[str, tuple[str, str]]:
    """Family postings, with live top skills appended when demand data exists."""
    postings = dict(FAMILY_POSTINGS)
    family_map = {
        "backend": "backend",
        "ai-ml": "ml_systems",
        "fullstack": "fullstack",
        "infrastructure": "infrastructure",
        "general": "general_swe",
    }
    for key, family in family_map.items():
        skills = (demand or {}).get(family)
        if skills:
            title, base = postings[key]
            postings[key] = (title, base + " " + " ".join(skills))
    return postings
