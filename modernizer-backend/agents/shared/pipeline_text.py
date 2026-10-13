"""
Model-free helpers of the migration and discovery pipelines: parsing an
analysis into its sections, reconciling the dependency mapper's answer with the
deterministic scan, the discovery writers' budgets and backstops, and the
per-task bookkeeping of the modifier.

They used to live in main.py, which imports FastAPI and Google ADK. Here they
are shared by the web pipeline (main.py imports them under their old names) and
the Gemini CLI path (cli/), which runs without either.
"""
from . import fswalk
import json
import os
import re
from pathlib import Path, PurePosixPath

from . import (arch_diagrams, current_state, dependency_graph, plan_coverage, repo_fingerprint,
               stack_detector, ui_contracts)

_re = re

DISCOVERY_GRAPHS = {"java": "java-8-to-25", "jsp": "jsp-to-react-bff", "oracle": "oracle-19c-to-23ai",
                     "solr": "solr-4-to-9", "tibco-ems": "tibco-ems-to-pubsub"}


def workspace_paths(workspace_dir: str) -> list[str]:
    root = Path(workspace_dir)
    if not workspace_dir or not root.exists():
        return []
    return sorted(p.relative_to(root).as_posix() for p in fswalk.files(root)
                  if p.is_file() and not (dependency_graph.EXCLUDED_DIRS & set(p.relative_to(root).parts)))


def task_paths(listed: list[str], workspace_paths: list[str]) -> list[str]:
    """Workspace files a task's `Files:` line names (exact, glob, directory or
    unique suffix — the same resolution plan conformance uses)."""
    out: list[str] = []
    for entry in listed:
        for path in plan_coverage._resolve(entry, workspace_paths):
            if path not in out:
                out.append(path)
    return out


def file_digests(workspace_dir: str, paths: list[str]) -> dict[str, str]:
    import hashlib
    out = {}
    for rel in paths:
        try:
            out[rel] = hashlib.sha256((Path(workspace_dir) / rel).read_bytes()).hexdigest()
        except OSError:
            out[rel] = ""
    return out


def unexplained_unchanged(workspace_dir: str, before: dict[str, str], modify_result: str) -> list[str]:
    """Files the task listed that are byte-identical after it and that the
    modifier did not list under "Files skipped" (by path or file name)."""
    skipped = ""
    m = _re.search(r"Files skipped[^\n]*(?:\n(?!\s*-\s*(?:Refused|Anything|Task|Files changed)).*)*",
                   modify_result, flags=_re.IGNORECASE)
    if m:
        skipped = m.group(0)
    after = file_digests(workspace_dir, list(before))
    return [rel for rel, digest in before.items()
            if digest and after.get(rel) == digest
            and rel not in skipped and PurePosixPath(rel).name not in skipped]


def parse_re_sections(combined: str) -> tuple[str, str, str, str]:
    """Return (analysis, brd, technical_spec, test_inventory) parsed from
    the combined RE output."""
    _A = _re.search(r'<!--\s*SECTION:\s*ANALYSIS\s*-->', combined, _re.IGNORECASE)
    _B = _re.search(r'<!--\s*SECTION:\s*BRD\s*-->', combined, _re.IGNORECASE)
    _T = _re.search(r'<!--\s*SECTION:\s*TECHNICAL_SPECIFICATION\s*-->', combined, _re.IGNORECASE)
    _X = _re.search(r'<!--\s*SECTION:\s*TEST_INVENTORY\s*-->', combined, _re.IGNORECASE)
    _E = _re.search(r'<!--\s*SECTION:\s*END\s*-->', combined, _re.IGNORECASE)

    analysis = combined[_A.end():_B.start()].strip() if _A and _B else combined
    brd       = combined[_B.end():_T.start()].strip() if _B and _T else (combined[_B.end():].strip() if _B else combined)

    tech_end  = _X.start() if _X else (_E.start() if _E else len(combined))
    tech_spec = combined[_T.end():tech_end].strip() if _T else ""

    test_end       = _E.start() if _E else len(combined)
    test_inventory = combined[_X.end():test_end].strip() if _X else ""

    # A dropped marker used to fail silently, and the damage is asymmetric: the
    # plan's Evidence Plan and Coverage Gaps are answered from test_inventory,
    # so losing it produces a plan that quietly claims full coverage. Fall back
    # to the section's own heading, and say so where a human will read it.
    if not test_inventory:
        heading = _re.search(
            r'^#{1,4}\s*(?:SECTION\s*4\s*[—:-]*\s*)?(?:EXISTING\s+)?TEST\s+INVENTORY\b.*$',
            tech_spec, _re.IGNORECASE | _re.MULTILINE,
        )
        if heading:
            test_inventory = tech_spec[heading.start():].strip()
            tech_spec = tech_spec[:heading.start()].strip()

    missing = [name for name, found in (
        ("ANALYSIS", _A), ("BRD", _B), ("TECHNICAL_SPECIFICATION", _T), ("TEST_INVENTORY", _X),
    ) if not found]
    # A marker in the wrong place is as damaging as a missing one and far quieter:
    # emit all five consecutively and every section parses EMPTY while the
    # missing-marker check above stays silent, because the markers are all there.
    empty = [name for name, found, body in (
        ("ANALYSIS", _A, analysis), ("BRD", _B, brd),
        ("TECHNICAL_SPECIFICATION", _T, tech_spec), ("TEST_INVENTORY", _X, test_inventory),
    ) if found and not body.strip()]

    if missing or empty:
        detail = []
        if missing:
            detail.append(f"missing marker(s): {', '.join(missing)}")
        if empty:
            detail.append(f"empty section(s): {', '.join(empty)}")
        print(f"[re] WARNING: RE output {'; '.join(detail)}", flush=True)

        reasons = []
        if missing:
            reasons.append(
                f"did not emit the {', '.join('`' + m + '`' for m in missing)} section marker(s)"
            )
        if empty:
            reasons.append(
                f"left {', '.join('`' + e + '`' for e in empty)} empty — usually because the "
                "markers were emitted together instead of as separators, with the content after "
                "them"
            )
        warning = (
            "> **Automated warning — incomplete reverse-engineering output.** The analysis "
            + " and ".join(reasons)
            + ". Check this document before confirming: the plan is built from these sections, and "
            "an empty Technical Specification or Test Inventory makes the plan's Coverage Gaps look "
            "clean when they are simply unknown.\n"
        )
        brd = warning + "\n" + (brd or combined)
        if not test_inventory.strip():
            test_inventory = warning

    return analysis, brd or combined, tech_spec, test_inventory


def inject_dependency_graph(tech_spec: str, graph_json: str, pattern: str, discovery: bool = False) -> str:
    """Prepend the deterministically-computed dependency graph + migration
    groups (rendered as a plain-text tree) to the top of the Technical
    Specification, so the MarkdownWithDiagrams renderer in BRDReview.tsx
    displays it with zero dedicated frontend graph code."""
    try:
        graph = json.loads(graph_json) if graph_json else {}
    except json.JSONDecodeError:
        graph = {}
    # Valid JSON of the wrong shape was not guarded, and `"[]"` is a real value
    # here -- _create_pattern_session seeds it for a bundled code-generation
    # session. Nothing calls this with that session today, so this was latent
    # rather than live, but an AttributeError mid-run is a poor way to find out.
    if not isinstance(graph, dict):
        graph = {}
    if not graph.get("nodes"):
        return tech_spec
    section = dependency_graph.to_markdown_section(graph, pattern, discovery=discovery)
    return f"{section}\n\n{tech_spec}"


def parse_mapper_json(raw: str) -> dict:
    """Extract the dependency mapper's trailing ```json block.

    Deliberately not _parse_validation_json: that one falls back to scanning from
    the first `{` to the last `}`, which here would start inside the prose
    inventory (a JNDI name, a `${...}` property, a code excerpt) and capture
    nothing valid. The mapper's contract puts the block last, so the last fenced
    block wins, and a bare object anywhere is only the final fallback.
    """
    text = (raw or "").strip()
    if not text:
        return {}

    blocks = _re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, _re.DOTALL)
    for block in reversed(blocks):
        try:
            return json.loads(block)
        except Exception:
            continue

    # Unfenced: take the widest object that parses, searching from the end since
    # that is where the contract puts it.
    for start in sorted((m.start() for m in _re.finditer(r"\{", text)), reverse=True):
        candidate = text[start : text.rfind("}") + 1]
        if '"stacks"' not in candidate:
            continue
        try:
            return json.loads(candidate)
        except Exception:
            continue
    return {}


def cited_paths_exist(evidence: list[str], workspace_dir: str) -> bool:
    """Whether at least one evidence line cites a file that is in the workspace.
    Without a workspace to check against (unit tests), the citation is taken as given."""
    if not workspace_dir or not Path(workspace_dir).is_dir():
        return True
    root = Path(workspace_dir).resolve()
    for line in evidence:
        path = _re.split(r":(?:\d+)?\s|:\d+$|\s—\s|\s-\s|\s\(", line.strip().strip("`"), maxsplit=1)[0]
        path = path.strip().strip("`").lstrip("./")
        if path and ".." not in Path(path).parts and (root / path).exists():
            return True
    return False


def without_result_block(raw: str) -> str:
    """The mapper's prose without its trailing machine-readable block (and that
    block's heading). Only a block that ends the reply is cut."""
    text = (raw or "").strip()
    start = max(text.rfind("```json"), -1)
    if start < 0 or not text.endswith("```") or start >= len(text) - 3:
        return text
    head = text[:start].rstrip()
    head = _re.sub(r"\n#+\s*Machine-Readable Result\s*$", "", head).rstrip()
    return head


def dedupe_evidence(lines: list[str]) -> list[str]:
    """Evidence lines without restatements: the mapper often repeats a pre-scan
    finding without its backticks or with "—" for ":". The first wording is kept."""
    seen, out = set(), []
    for line in lines:
        key = " ".join(_re.sub(r"[`*]|\s[—–-]\s|:\s", " ", line).lower().split())
        if key not in seen:
            seen.add(key)
            out.append(line)
    return out


def merge_mapper_result(prescan: list[dict], raw: str, workspace_dir: str = "") -> tuple[list[dict], list[str]]:
    """Reconcile the LLM mapper's JSON block against the deterministic pre-scan.

    Returns `(stacks, notes)` — the stacks to reverse-engineer, and any notes to
    surface to the reviewer about what was dropped and why.

    The pre-scan is the floor. The mapper may enrich a stack's evidence, reject
    one with a stated reason, or add one it found, but three things are enforced
    here rather than trusted to the prompt:

    - **A stack with no evidence is dropped.** Uncited is indistinguishable from
      invented, and this document is downloaded and relied on.
    - **An added stack must cite a file that exists.** Any identifier is
      accepted — every stack is documented by the same discovery agent — but a
      stack none of whose cited paths is in the workspace is dropped with a note.
    - **A rejection needs a reason.** Rejecting a deterministic finding is the one
      move here that removes evidence from the document, so it has to be argued;
      a bare rejection leaves the pre-scan's finding standing.
    """
    by_pattern: dict[str, dict] = {}
    for s in prescan:
        stack = dict(s)
        # Ids and labels are the stack's, never a migration's (an older pre-scan
        # used the migration pattern ids, e.g. `java-8-to-25`).
        stack["pattern"] = current_state.neutral_ids(stack["pattern"])
        stack["label"] = stack_detector.STACK_LABELS.get(stack["pattern"]) or stack.get("label") or stack["pattern"]
        stack.setdefault("kind", next((c.kind for c in stack_detector.CATALOG if c.pattern == stack["pattern"]),
                                      "other"))
        stack.setdefault("reference", stack_detector.reference_for(stack["pattern"], stack["kind"]))
        stack.pop("extraction_only", None)
        by_pattern[stack["pattern"]] = stack
    notes: list[str] = []

    parsed = parse_mapper_json(raw)
    # An unparseable reply must not read as "no stacks found" — that would
    # silently discard the deterministic findings and produce an empty document.
    if not isinstance(parsed, dict) or "stacks" not in parsed:
        notes.append(
            "The dependency mapper's machine-readable block could not be parsed, so the "
            "deterministic scan's findings are used as-is. Its written inventory is still in the "
            "document."
        )
        return stack_detector.order(list(by_pattern.values())), notes

    for entry in parsed.get("stacks") or []:
        if not isinstance(entry, dict):
            continue
        pattern = str(entry.get("pattern") or "").strip()
        evidence = dedupe_evidence([str(e).strip() for e in (entry.get("evidence") or []) if str(e).strip()])
        if not pattern or not evidence:
            notes.append(
                f"Dropped a stack the mapper reported without evidence: `{pattern or 'unnamed'}`."
            )
            continue
        pattern = current_state.neutral_ids(pattern)
        if pattern not in by_pattern:
            pattern = stack_detector.slug(pattern)
        if pattern not in by_pattern and not cited_paths_exist(evidence, workspace_dir):
            notes.append(
                f"Dropped `{pattern}`: none of the files the mapper cited for it exist in the "
                f"repository ({'; '.join(evidence[:3])})."
            )
            continue
        if pattern in by_pattern:
            # Confirmed. The mapper read the files, so prefer its citations and
            # keep the pre-scan's underneath as corroboration.
            existing = by_pattern[pattern]["evidence"]
            by_pattern[pattern]["evidence"] = dedupe_evidence(evidence + existing)[:6]
        else:
            kind = str(entry.get("kind") or "").strip().lower()
            spec_kind = next((s.kind for s in stack_detector.CATALOG if s.pattern == pattern), "")
            kind = spec_kind or (kind if kind in stack_detector.KIND_ORDER else "other")
            by_pattern[pattern] = {
                "pattern": pattern,
                "label": str(stack_detector.STACK_LABELS.get(pattern) or entry.get("label") or pattern)[:80],
                "kind": kind,
                "reference": stack_detector.reference_for(pattern, kind),
                "evidence": evidence[:6],
            }

    for entry in parsed.get("rejected") or []:
        if not isinstance(entry, dict):
            continue
        pattern = current_state.neutral_ids(str(entry.get("pattern") or "").strip())
        reason = str(entry.get("reason") or "").strip()
        if pattern not in by_pattern:
            continue
        if not reason:
            notes.append(
                f"The mapper rejected `{pattern}` without a reason, so the deterministic scan's "
                "finding stands."
            )
            continue
        del by_pattern[pattern]
        notes.append(f"`{pattern}` was detected by the scan but rejected by the mapper: {reason}")

    return stack_detector.order(list(by_pattern.values())), notes


def clip_findings(text: str, limit: int, label: str) -> str:
    """Findings cut to *limit* characters, with the cut stated where the
    document's reader and the combining agent will see it — never silently."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return (
        text[:limit].rstrip()
        + f"\n\n> ⚠ **Findings for {label} were cut at {limit:,} characters.** Rows after this point are "
        "missing from this document; raise RE_FINDINGS_MAX_CHARS / RE_SYNTHESIS_MAX_CHARS to keep them."
    )


def batch_by_size(items: list[str], budget: int) -> list[list[str]]:
    """Consecutive batches whose joined size stays within *budget*.

    Used by merge loops, which must shrink the list every round: when no two
    items fit together (each is over half the budget), items are paired anyway —
    a merge request somewhat over budget beats a loop that never ends."""
    batches: list[list[str]] = []
    size = 0
    for item in items:
        if batches and size + len(item) <= budget:
            batches[-1].append(item)
            size += len(item)
        else:
            batches.append([item])
            size = len(item)
    if len(items) > 1 and all(len(b) == 1 for b in batches):
        batches = [items[i:i + 2] for i in range(0, len(items), 2)]
    return batches


def with_reviewer_notes(document: str, feedback: str | None) -> str:
    """An inventory is a function of the code, so "Refine with AI" cannot reword
    it: the reviewer's feedback is kept as Reviewer Notes at the top of the
    scope (BRD) section, which the planner reads."""
    if not feedback:
        return document
    return document.replace(
        "<!-- SECTION: BRD -->\n",
        "<!-- SECTION: BRD -->\n\n## Reviewer Notes\n\n" + feedback.strip() + "\n\n"
        "_Carried to the planner as written. The inventory itself is regenerated from the code; "
        "to change its content, edit the document before confirming._\n",
        1,
    )


def current_state_only(text: str, where: str, keep: frozenset = frozenset()) -> str:
    """A discovery section with any migration or advisory language removed and
    the detector's migration-named pattern ids replaced by stack ids — the
    deterministic backstop to the stack-discovery-re skill's instructions.
    `keep`: target technologies the repository itself uses (current_state.targets_in_repo)."""
    cleaned, removed = current_state.scrub(current_state.neutral_ids(text or ""), keep)
    if removed:
        print(f"[discovery] {where}: removed {len(removed)} migration/advisory fragment(s): "
              + " | ".join(r[:80] for r in removed[:5]), flush=True)
    return cleaned


def with_ingestion_warning(state: dict, brd: str, tech_spec: str) -> tuple[str, str]:
    ingestion_warning = state.get("ingestion_warning", "")
    if not ingestion_warning:
        return brd, tech_spec
    banner = f"> ⚠️ **Incomplete repository.** {ingestion_warning}\n"
    return (f"{banner}\n{brd}" if brd else banner), (f"{banner}\n{tech_spec}" if tech_spec else banner)


WRITER_RULES_INDEX_CHARS = 40_000


ELIDED_SPEC = ("(the complete list is in the computed sections of this specification: Interface & Job "
                "Inventory, Endpoint Contracts, UI-to-Backend Contracts)")


ELIDED_UI = "(every control is listed in the computed UI-to-Backend Contracts)"


ELIDED_TESTS = "(every test file and test is listed in the computed Test Files table)"


def for_writer(markdown: str, limit: int) -> str:
    """A computed section for a writer's request, cut at `limit` with a note that the
    specification prints it in full (the writer describes it; it does not re-list it)."""
    if not markdown:
        return ""
    if len(markdown) <= limit:
        return markdown + "\n\n"
    cut = markdown[:limit].rsplit("\n", 1)[0]
    return cut + "\n\n(cut here for length — the specification prints this section in full)\n\n"


EVIDENCE_FILE = "evidence.md"


BUILD_FILES = ("pom.xml", "build.gradle", "build.gradle.kts", "package.json", "setup.py", "pyproject.toml")


def module_names(workspace_dir: str) -> list[str]:
    """The repository's modules: every folder with a build file (the root by the repository's name)."""
    root = Path(workspace_dir)
    names: set[str] = set()
    if root.is_dir():
        for name in BUILD_FILES:
            for path in root.rglob(name):
                rel = path.relative_to(root)
                if dependency_graph.EXCLUDED_DIRS & set(rel.parts):
                    continue
                names.add(rel.parent.name if rel.parent.parts else root.name)
    return sorted(names)


def diagram_facts(stacks: list[str], endpoints: list[dict], modules: list[str], config_md: str,
                   ui_result: dict, computed: str) -> arch_diagrams.Facts:
    keys = _re.findall(r"^\|\s*`([^`]+)`", config_md or "", _re.M)
    return arch_diagrams.Facts.build(stacks, endpoints, modules, keys, ui_contracts.ids(ui_result), computed)


def diagram_refs(facts: arch_diagrams.Facts) -> str:
    """The computed-fact references the diagrams agent may cite, grouped."""
    groups: dict[str, list[str]] = {}
    for ref in sorted(facts.refs):
        kind = "ui" if ref.startswith("UI-") else ref.split(":", 1)[0]
        groups.setdefault(kind, []).append(ref)
    lines = ["## Computed facts you may cite", ""]
    for kind in ("stack", "module", "endpoint", "handler", "config", "ui"):
        if groups.get(kind):
            lines.append(f"**{kind}:** " + ", ".join(f"`{r}`" for r in groups[kind]))
            lines.append("")
    return "\n".join(lines)


def rule_languages(stacks: list[dict]) -> set[str]:
    """Languages whose rule candidates belong to a confirmed stack. Code of a stack
    the reviewer unchecked is not analysed (and the coverage report says so)."""
    languages: set[str] = set()
    for s in stacks:
        stack, kind = s.get("pattern", ""), s.get("kind", "")
        if stack == "java":
            languages |= {"Java", "Drools"}
        elif stack == "jsp":
            languages.add("JSP")
        elif stack == "thymeleaf":
            # Templates, and the page scripts the templates load.
            languages |= {"Thymeleaf", "JavaScript", "TypeScript"}
        elif kind in ("frontend", "service") or stack in ("javascript", "typescript"):
            languages |= {"JavaScript", "TypeScript"}
        elif stack == "python":
            languages.add("Python")
        elif kind == "database" or stack in ("sql", "pl-sql"):
            languages |= {"SQL", "PL/SQL"}
    if languages:
        # Template / rule / reference-data files belong to the application, whatever its stacks.
        languages |= {"JSON", "YAML", "XML", "Properties", "CSV", "MyBatis XML"}
    return languages


STACK_SUFFIXES = {
    "java": {".java"},
    "jsp": {".jsp", ".jspx", ".jspf", ".tag", ".tagx"},
    "thymeleaf": {".html", ".htm", ".js"},
    "nodejs": {".js", ".mjs", ".cjs", ".ts"},
}


FRONTEND_SUFFIXES = {".js", ".jsx", ".ts", ".tsx", ".vue", ".hbs", ".handlebars", ".mustache", ".html", ".htm"}


def stack_files(workspace_dir: str, stack: dict) -> list[str] | None:
    """The stack's own source files, or None for a stack whose artifacts are not
    a body of source (a database, broker, server) — those are documented in one run."""
    stack_id, kind = stack.get("pattern", ""), stack.get("kind", "")
    suffixes = STACK_SUFFIXES.get(stack_id)
    if suffixes is None and kind == "frontend":
        suffixes = FRONTEND_SUFFIXES
    if suffixes is None and kind == "language":
        suffixes = {ext for ext, lang in repo_fingerprint.LANGUAGES.items()
                    if stack_detector.slug(stack_detector._LANGUAGE_FAMILY.get(lang, lang)) == stack_id}
    if not suffixes:
        return None
    root = Path(workspace_dir)
    if not root.is_dir():
        return None
    files = []
    for path in sorted(fswalk.files(root)):
        if not path.is_file() or path.suffix.lower() not in suffixes:
            continue
        rel = path.relative_to(root).as_posix()
        parts = set(Path(rel).parts)
        if (dependency_graph.EXCLUDED_DIRS & parts or "node_modules" in parts or path.name.endswith(".min.js")
                or (kind in ("frontend", "web-tier")
                    and _re.search(r"(?:^|/)(?:lib|libs|vendor|vendors|third[-_]?party)/", rel))):
            continue
        files.append(rel)
    return files


def file_units(files: list[str], max_files: int) -> list[list[str]]:
    """Files packed into units of at most `max_files`, keeping a directory's
    files together where they fit. Every file is in exactly one unit."""
    by_dir: dict[str, list[str]] = {}
    for f in files:
        by_dir.setdefault(str(PurePosixPath(f).parent), []).append(f)
    units: list[list[str]] = []
    for directory in sorted(by_dir):
        group = by_dir[directory]
        for i in range(0, len(group), max_files):
            part = group[i:i + max_files]
            if units and len(units[-1]) + len(part) <= max_files:
                units[-1].extend(part)
            else:
                units.append(list(part))
    return units


def unit_label(files: list[str]) -> str:
    dirs = sorted({str(PurePosixPath(f).parent) for f in files})
    common = os.path.commonpath(dirs) if dirs else ""
    return f"{common or '(root)'} ({len(files)} files)"


#: Where the pipeline places its own sections in the Enterprise Architect's
#: specification (plain_language.place_section: before the first of these present).
#: The current headings of the current-state-architecture skill first, then the ones
#: earlier versions of it wrote, so a stored specification still places correctly.
SPEC_UI_CONTRACTS_BEFORE = ("## Third-Party Integrations", "## Internal System Integrations", "## Database Details",
                            "## Security Mechanisms", "## Logging, Monitoring", "## Configuration & Environments",
                            "## Data Architecture", "## Integrations", "## Security", "## Runtime",
                            "## Per-Stack Detail", "## Discovery Limitations")
SPEC_DIAGRAMS_BEFORE = ("## System Components", "## Component Communication", "## Interface Overview",
                        ui_contracts.SECTION_HEADING) + SPEC_UI_CONTRACTS_BEFORE
