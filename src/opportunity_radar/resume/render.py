"""Selection -> LaTeX in the user's own template.

The preamble, contact header and Education section are re-emitted verbatim;
Experience, Projects and Skills are rebuilt from the selection with the same
macros, so the output is indistinguishable in style from the master resume.
"""

from __future__ import annotations

from opportunity_radar.resume.bank import Bank, Bullet, Entry
from opportunity_radar.resume.latex import escape
from opportunity_radar.resume.selector import Selection


def _entries_tex(entries: list[tuple[Entry, list[Bullet]]], overrides: dict[str, str]) -> list[str]:
    lines: list[str] = []
    for entry, bullets in entries:
        lines.append(f"    {entry.heading_tex.strip()}")
        lines.append("      \\resumeItemListStart")
        for bullet in bullets:
            lines.append(f"        \\resumeItem{{{overrides.get(bullet.id, bullet.tex)}}}")
        lines.append("      \\resumeItemListEnd")
    return lines


def render(bank: Bank, selection: Selection, overrides: dict[str, str] | None = None) -> str:
    overrides = overrides or {}
    names = bank.section_names
    out = [bank.preamble.rstrip(), ""]
    if bank.education_tex.strip():
        out += [
            f"\\section{{{names.get('education', 'Education')}}}",
            bank.education_tex.rstrip(),
            "",
        ]
    if selection.experiences:
        out += [
            f"\\section{{{names.get('experience', 'Experience')}}}",
            "  \\resumeSubHeadingListStart",
        ]
        out += _entries_tex(selection.experiences, overrides)
        out += ["  \\resumeSubHeadingListEnd", ""]
    if selection.projects:
        out += [
            f"\\section{{{names.get('projects', 'Projects')}}}",
            "  \\resumeSubHeadingListStart",
        ]
        out += _entries_tex(selection.projects, overrides)
        out += ["  \\resumeSubHeadingListEnd", ""]
    if selection.skills:
        out += [
            f"\\section{{{names.get('skills', 'Technical Skills')}}}",
            " \\begin{itemize}[leftmargin=0.15in, label={}]",
            "    \\small{\\item{",
        ]
        rows = [
            f"     \\textbf{{{escape(label)}}}{{: {', '.join(escape(i) for i in items)}.}}"
            for label, items in selection.skills.items()
        ]
        out.append(" \\\\\n".join(rows))
        out += ["    }}", " \\end{itemize}", ""]
    out.append("\\end{document}")
    return "\n".join(out) + "\n"
