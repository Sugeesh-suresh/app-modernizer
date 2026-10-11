"""
Word (.docx) copies of a run's documents, converted from the same Markdown by
shared/docx_export.py (no model) — the CLI counterpart of the web app's
`?format=docx` downloads.
"""
from __future__ import annotations

from pathlib import Path

from agents.shared import docx_export

from . import patterns as P
from .runstate import Run

_DOCS = (("brd", "Business Requirements"), ("technical_spec", "Technical Specification"),
         ("test_inventory", "Existing Test Inventory"), ("plan", "Migration Plan"),
         ("setup", "Setup & Deployment Guide"), ("tech_debt", "Tech Debt & Dead Code"),
         ("ui_screens", "UI Screens"), ("evidence", "Evidence"))
_RESULTS = (("final_report.md", "Migration Report"), ("code_review.md", "Independent Code Review"))


def _images(run: Run, text: str) -> dict[str, Path]:
    """Every local image the document names, by the exact reference it uses."""
    out = {}
    for folder in ("diagrams", "screens"):
        base = run.dir / "discovery" / folder
        if base.is_dir():
            for path in base.glob("*.png"):
                ref = f"../../discovery/{folder}/{path.name}"
                if ref in text:
                    out[ref] = path
    return out


def export(run: Run) -> str:
    out_dir = run.dir / "export"
    out_dir.mkdir(parents=True, exist_ok=True)
    patterns = run.state.get("bundle") or [run.state["pattern"]]
    written = []
    for pattern in patterns:
        label = "Technology Stack Discovery" if pattern == P.STACK_DISCOVERY else P.get(pattern).label
        for name, title in _DOCS:
            text = run.read_doc(name, pattern)
            if not text.strip():
                continue
            target = out_dir / f"{pattern}-{name}.docx"
            target.write_bytes(docx_export.to_docx(f"{title} — {label}", [(None, text)], _images(run, text)))
            written.append(target)
        for name, title in _RESULTS:
            path = run.dir / "results" / pattern / name
            if path.is_file():
                target = out_dir / f"{pattern}-{name.removesuffix('.md')}.docx"
                target.write_bytes(docx_export.to_docx(f"{title} — {label}", [(None, path.read_text(encoding='utf-8'))]))
                written.append(target)
    if not written:
        return "Nothing to export yet — no document has been written."
    return "Wrote:\n" + "\n".join(f"- `{run.rel(p)}`" for p in written)
