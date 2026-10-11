"""
The reverse-engineering deliverables: one file per document, with an index.

    README.md                    index: what each file is, the strategy, the stacks
    SETUP.md                     local setup and deployment to other environments
    BRD.md                       the Product Owner's Business Requirements Document
    TECHNICAL_SPECIFICATION.md   the Enterprise Architect's technical documentation,
                                 with the computed inventories and the test inventory
    openapi.yaml / openapi.json  OpenAPI 3.0.3 of every HTTP endpoint (Swagger-ready)
    TECH_DEBT_AND_DEAD_CODE.md   tech debt and dead-code candidates for human review
    UI_PAGES.md                  every UI page: its HTML elements, interactive elements and
                                 their traces to the backend (when the repository has a UI)
    UI_SCREENS.md                a screenshot of each page, in the same page order
    STRATEGY.md                  the strategy options offered and the one chosen
    EVIDENCE.md                  traceability of every statement to the code

Used by both front ends: the Gemini CLI path writes them to `.modernizer/deliverables/`,
the web app serves them as one zip (`/download/deliverables`).
"""
from __future__ import annotations

from . import openapi_spec

FILES: tuple[tuple[str, str, str], ...] = (
    ("SETUP.md", "setup", "Setting the application up locally and deploying it to other environments"),
    ("BRD.md", "brd", "Business Requirements Document (Product Owner)"),
    ("TECHNICAL_SPECIFICATION.md", "technical_spec",
     "Technical documentation (Enterprise Architect): architecture, components, communication, integrations, "
     "database, security, logging/monitoring/auditing, configuration, runtime, the computed inventories and the "
     "existing test inventory"),
    ("TECH_DEBT_AND_DEAD_CODE.md", "tech_debt", "Tech debt and dead-code candidates for human review"),
    ("UI_PAGES.md", "ui_pages", "Every UI page, page by page: all its HTML elements, its interactive elements, the "
     "action and purpose of each, and the trace of each to the backend (Ajax / HTTP endpoint URL, handler, "
     "request and response)"),
    ("UI_SCREENS.md", "ui_screens", "A screenshot of each UI page, in the same page order as UI_PAGES.md"),
    ("EVIDENCE.md", "evidence", "Traceability: each statement's evidence, the business-rules catalog, grounding checks"),
)


def build(docs: dict[str, str], openapi: dict | None, strategy_md: str, title: str, strategy_name: str,
          stacks: list[str]) -> dict[str, str]:
    """{file name: content}. `docs` maps document ids (brd, technical_spec, test_inventory,
    setup, tech_debt, ui_pages, ui_screens, evidence) to Markdown; empty documents are left out."""
    out: dict[str, str] = {}
    rows = []
    for fname, doc, what in FILES:
        text = docs.get(doc, "") or ""
        if doc == "technical_spec" and (docs.get("test_inventory") or "").strip():
            tests = docs["test_inventory"]
            text = (text.rstrip() + "\n\n---\n\n# Existing Test Inventory\n\n" + tests) if text.strip() else tests
        if text.strip():
            out[fname] = text if text.endswith("\n") else text + "\n"
            rows.append(f"| [{fname}]({fname}) | {what} |")
    if openapi and openapi.get("paths") is not None:
        out["openapi.yaml"] = openapi_spec.to_yaml(openapi)
        out["openapi.json"] = openapi_spec.to_json(openapi)
        n = sum(len(v) for v in openapi["paths"].values())
        rows.append(f"| [openapi.yaml](openapi.yaml) / [openapi.json](openapi.json) | OpenAPI 3.0.3 specification of "
                    f"every HTTP endpoint ({n} operation(s)) — import into Swagger UI / Editor, Postman or a code "
                    "generator |")
    if strategy_md.strip():
        out["STRATEGY.md"] = strategy_md
        rows.append("| [STRATEGY.md](STRATEGY.md) | The reverse-engineering strategy options and the one chosen |")
    index = [f"# Reverse-Engineering Deliverables — {title}", "",
             f"Strategy: **{strategy_name}**." + (f" Stacks: {', '.join(stacks)}." if stacks else ""), "",
             "| File | Contents |", "|---|---|", *rows, ""]
    return {"README.md": "\n".join(index), **out}
