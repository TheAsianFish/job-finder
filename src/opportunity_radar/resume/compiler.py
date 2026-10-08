"""pdfLaTeX compilation (TinyTeX locally and in CI) plus PDF inspection.

pdfLaTeX, not XeTeX/Tectonic: Jake's template relies on pdfTeX primitives
(\\pdfgentounicode, glyphtounicode) and the master PDF is pdfTeX output, so
the same engine guarantees identical metrics and a one-page result that
matches what the user sees in Overleaf.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

_CANDIDATES = [
    Path.home() / "Library/TinyTeX/bin/universal-darwin/pdflatex",
    Path.home() / ".TinyTeX/bin/x86_64-linux/pdflatex",
    Path.home() / ".TinyTeX/bin/aarch64-linux/pdflatex",
]
TEX_PACKAGES = ["titlesec", "marvosym", "enumitem", "fancyhdr", "babel-english", "preprint"]


class CompileError(RuntimeError):
    pass


def find_pdflatex() -> str | None:
    env = os.environ.get("OPPORTUNITY_RADAR_PDFLATEX")
    if env and Path(env).exists():
        return env
    found = shutil.which("pdflatex")
    if found:
        return found
    for candidate in _CANDIDATES:
        if candidate.exists():
            return str(candidate)
    return None


@dataclass
class CompiledPdf:
    path: Path
    pages: int
    text: str


def compile_tex(tex: str, output: Path, timeout: int = 120) -> CompiledPdf:
    """Compile LaTeX source to `output` (a .pdf path)."""
    engine = find_pdflatex()
    if engine is None:
        raise CompileError(
            "pdflatex not found: install TinyTeX "
            "(curl -sL https://yihui.org/tinytex/install-bin-unix.sh | sh) and run "
            f"`tlmgr install {' '.join(TEX_PACKAGES)}`"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "resume.tex"
        src.write_text(tex, encoding="utf-8")
        proc = subprocess.run(
            [engine, "-interaction=nonstopmode", "-halt-on-error", "resume.tex"],
            cwd=tmp,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        pdf = Path(tmp) / "resume.pdf"
        if proc.returncode != 0 or not pdf.exists():
            errors = [ln for ln in proc.stdout.splitlines() if ln.startswith("!")]
            raise CompileError("; ".join(errors[:3]) or f"pdflatex exited {proc.returncode}")
        shutil.copyfile(pdf, output)
    return inspect_pdf(output)


def inspect_pdf(path: Path) -> CompiledPdf:
    reader = PdfReader(str(path))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    return CompiledPdf(path=path, pages=len(reader.pages), text=text)
