"""Minimal, dependable LaTeX reading for resume templates.

Not a TeX engine: just enough to find macro calls with balanced brace
arguments, separate live lines from commented-out ones (the bullet bank),
and turn LaTeX snippets into plain text for keyword matching.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_INLINE_COMMENT_RE = re.compile(r"(?<!\\)%.*$")
_SECTION_RE = re.compile(r"\\section\*?\{([^}]*)\}")


@dataclass(frozen=True)
class MacroCall:
    name: str
    start: int
    end: int
    args: tuple[str, ...]


def read_group(text: str, pos: int) -> tuple[str, int] | None:
    """Read a balanced {...} group starting at/after pos (skipping whitespace)."""
    i = pos
    while i < len(text) and text[i] in " \t\r\n":
        i += 1
    if i >= len(text) or text[i] != "{":
        return None
    depth = 0
    j = i
    while j < len(text):
        ch = text[j]
        if ch == "\\":
            j += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[i + 1 : j], j + 1
        j += 1
    return None


def find_macros(text: str, name: str, nargs: int) -> list[MacroCall]:
    """All calls of \\name with exactly nargs brace arguments."""
    calls: list[MacroCall] = []
    pattern = re.compile(rf"\\{re.escape(name)}(?![A-Za-z])")
    for match in pattern.finditer(text):
        pos = match.end()
        args: list[str] = []
        for _ in range(nargs):
            group = read_group(text, pos)
            if group is None:
                break
            arg, pos = group
            args.append(arg)
        if len(args) == nargs:
            calls.append(MacroCall(name, match.start(), pos, tuple(args)))
    return calls


@dataclass
class SectionText:
    name: str
    active: str  # live LaTeX (inline comments removed)
    commented: str  # commented-out LaTeX with the leading '%' removed


def split_sections(source: str) -> tuple[str, list[SectionText]]:
    """Return (preamble+header up to the first live \\section, sections).

    Commented lines are attributed to the section they appear in; a
    commented-out \\section (e.g. "%\\section{Relevant Coursework}") opens a
    section of its own whose content is entirely commented. Lines commented
    twice ("%%" or "% %") are wordings the author deliberately superseded
    inside an already-commented block, so they are dropped entirely.
    """
    lines = source.splitlines()
    preamble: list[str] = []
    sections: list[SectionText] = []
    current: SectionText | None = None
    for line in lines:
        stripped = line.lstrip()
        is_comment = stripped.startswith("%")
        if is_comment:
            content = stripped[1:]
            if content.lstrip().startswith("%"):
                continue  # commented twice: a superseded alternative
            content = content[1:] if content.startswith(" ") else content
            section = _SECTION_RE.search(content)
            if section and current is not None:
                current = SectionText(section.group(1).strip(), "", "")
                sections.append(current)
                continue
            if current is None:
                preamble.append(line)
            else:
                current.commented += content + "\n"
            continue
        live = _INLINE_COMMENT_RE.sub("", line)
        section = _SECTION_RE.search(live)
        if section:
            current = SectionText(section.group(1).strip(), "", "")
            sections.append(current)
            remainder = live[section.end() :]
            if remainder.strip():
                current.active += remainder + "\n"
            continue
        if current is None:
            preamble.append(line)
        else:
            current.active += live + "\n"
    return "\n".join(preamble) + "\n", sections


_UNWRAP_RE = re.compile(
    r"\\(?:textbf|emph|textit|underline|small|large|Large|scshape|texttt)\{([^{}]*)\}"
)
_HREF_RE = re.compile(r"\\href\{[^{}]*\}\{([^{}]*)\}")
_COLOR_RE = re.compile(r"\\textcolor\{[^{}]*\}\{([^{}]*)\}")
_CMD_RE = re.compile(r"\\[A-Za-z]+\*?(?:\[[^\]]*\])?")

_REPLACEMENTS = [
    ("${\\sim}$", "~"),
    ("$\\sim$", "~"),
    ("$|$", "|"),
    ("\\%", "%"),
    ("\\&", "&"),
    ("\\$", "$"),
    ("\\#", "#"),
    ("\\_", "_"),
    ("{,}", ","),
    ("---", "\u2014"),
    ("--", "\u2013"),
    ("\\,", " "),
    ("~", " "),
]


def to_plain(tex: str) -> str:
    """LaTeX snippet -> readable plain text (for matching and reports)."""
    text = tex
    for _ in range(8):  # innermost-first; repeat until nothing changes
        before = text
        text = _COLOR_RE.sub(r"\1", text)
        text = _UNWRAP_RE.sub(r"\1", text)
        text = _HREF_RE.sub(r"\1", text)
        if text == before:
            break
    for old, new_value in _REPLACEMENTS[:-1]:
        text = text.replace(old, new_value)
    text = _CMD_RE.sub("", text)
    text = text.replace("{", "").replace("}", "").replace("$", "")
    return re.sub(r"\s+", " ", text).strip()


def bold_phrases(tex: str) -> list[str]:
    """Plain-text versions of every \\textbf{...} phrase in a snippet."""
    phrases = []
    for call in find_macros(tex, "textbf", 1):
        phrase = to_plain(call.args[0])
        if phrase:
            phrases.append(phrase)
    return phrases


_ESCAPE_MAP = {
    "\\": "\\textbackslash{}",
    "&": "\\&",
    "%": "\\%",
    "$": "\\$",
    "#": "\\#",
    "_": "\\_",
    "{": "\\{",
    "}": "\\}",
    "~": "${\\sim}$",
    "\u2014": "---",
    "\u2013": "--",
}


def escape(text: str) -> str:
    """Plain text -> safe LaTeX, one character at a time (no double escaping)."""
    return "".join(_ESCAPE_MAP.get(ch, ch) for ch in text)
