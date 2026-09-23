"""
Deterministic (non-LLM) detection of every technology stack present in an
uploaded repository — the first pass of the `stack-discovery` pattern's
dependency mapper.

Different question from companion_detector.py's. That module answers "the user
picked Java 8 -> 25; what else must move for the app to keep working?", so it
needs a primary pattern and only ever looks for that primary's companions.
This one answers "what is in here at all?" with no primary chosen, and so it
also has to detect the stacks that are somebody's primary elsewhere — Java
itself, and JSP.

Both passes stay evidence-first: every stack reported carries the file paths and
the matched text that put it there, so a reviewer can check the finding instead
of trusting it. The LLM mapper that runs afterwards (skills/dependency-mapper)
may ADD stacks this pass missed, but it is held to the same standard — a stack
with no citation is dropped.

Two deliberate omissions:

- No version detection. `ojdbc8` in a pom tells you an Oracle driver is on the
  classpath, not which database version answers the connection string, and a
  guessed version reads as a fact once it is in a document. Versions are left
  to the RE skills, which read the files and can cite them.
- No confidence scores. A number nobody can derive would be decoration; the
  evidence list is the confidence signal, and it is auditable.
"""
import re
from dataclasses import dataclass, field
from pathlib import Path

from .companion_detector import (
    COMPANION_LABELS,
    ORACLE_PATTERNS,
    SOLR_PATTERNS,
    TIBCO_EMS_PATTERNS,
    scannable_files,
)

#: Wider than companion_detector's: stack detection also has to see JSP views
#: and tag files, which no companion pattern ever needs to grep.
_SCAN_SUFFIXES = {
    ".xml", ".properties", ".yml", ".yaml", ".java", ".gradle", ".kts",
    ".jsp", ".jspx", ".jspf", ".tag", ".tagx", ".tld", ".mf",
}

_MAX_EVIDENCE_PER_STACK = 5


@dataclass(frozen=True)
class StackSpec:
    """One detectable stack, and the RE pattern whose `re` runner extracts it.

    `pattern` is a key into PATTERN_RUNNERS, not a migration the user asked
    for — `stack-discovery` only ever invokes that pattern's RE stage. That is
    why `wildfly` can appear here with no plan or code pipeline behind it.
    """
    pattern: str
    label: str
    #: Exact lowercased basenames that are evidence on their own — a file that
    #: only exists because the stack does.
    filenames: tuple[str, ...] = ()
    #: Extensions that are evidence on their own, for the same reason.
    suffixes: tuple[str, ...] = ()
    content: tuple[re.Pattern, ...] = field(default_factory=tuple)


_JAVA_PATTERNS = (
    re.compile(r"maven\.compiler\.(?:source|target|release)"),
    re.compile(r"<source>\s*1\.[45678]\s*</source>"),
    re.compile(r"sourceCompatibility\s*=?\s*['\"]?1\.[45678]"),
    re.compile(r"\borg\.springframework\b"),
)

_JSP_PATTERNS = (
    re.compile(r"<%@\s*(?:page|taglib|include)\b"),
    re.compile(r"\b(?:javax|jakarta)\.servlet\.jsp\b"),
    re.compile(r"<jsp:(?:include|forward|useBean)\b"),
    re.compile(r"InternalResourceViewResolver"),
)

# `urn:jboss:domain` and `java:jboss/` are the load-bearing ones: they appear in
# WildFly/JBoss server config and JNDI names and essentially nowhere else. The
# plugin coordinates are equally specific. Deliberately NOT matching a bare
# "jboss" or "org.jboss.logging", which turn up as transitive dependencies of
# libraries in applications that never run on WildFly at all.
_WILDFLY_PATTERNS = (
    re.compile(r"urn:jboss:domain"),
    re.compile(r"urn:jboss:deployment-structure"),
    re.compile(r"java:(?:jboss|global)/"),
    re.compile(r"\b(?:wildfly|jboss-as)-maven-plugin\b"),
    re.compile(r"\borg\.jboss\.as\b"),
    re.compile(r"\bjboss-eap\b|\bwildfly-dist\b"),
)

#: Display/execution order. Infrastructure stacks first and the application
#: language last, so the combined document reads outside-in and the reviewer
#: sees what the app sits on before what it is written in.
STACK_SPECS: tuple[StackSpec, ...] = (
    StackSpec(
        pattern="wildfly",
        label="WildFly / JBoss (app server)",
        filenames=(
            "jboss-deployment-structure.xml", "jboss-web.xml", "jboss-ejb3.xml",
            "standalone.xml", "standalone-full.xml", "domain.xml", "jboss-app.xml",
        ),
        content=_WILDFLY_PATTERNS,
    ),
    StackSpec(
        pattern="oracle-19c-to-23ai",
        label=COMPANION_LABELS["oracle-19c-to-23ai"],
        content=tuple(ORACLE_PATTERNS),
    ),
    StackSpec(
        pattern="solr-4-to-9",
        label=COMPANION_LABELS["solr-4-to-9"],
        filenames=("solrconfig.xml", "managed-schema"),
        content=tuple(SOLR_PATTERNS),
    ),
    StackSpec(
        pattern="tibco-ems-to-pubsub",
        label=COMPANION_LABELS["tibco-ems-to-pubsub"],
        content=tuple(TIBCO_EMS_PATTERNS),
    ),
    StackSpec(
        pattern="jsp-to-react-bff",
        label="JSP / Servlet web tier",
        suffixes=(".jsp", ".jspx", ".jspf", ".tag", ".tagx"),
        content=_JSP_PATTERNS,
    ),
    StackSpec(
        pattern="java-8-to-25",
        label=COMPANION_LABELS["java-8-to-25"],
        suffixes=(".java",),
        content=_JAVA_PATTERNS,
    ),
)

STACK_ORDER: list[str] = [spec.pattern for spec in STACK_SPECS]

#: Stacks with an RE skill but no migration pipeline. Detected and reverse
#: engineered; never planned or generated. Kept explicit so a caller can say so
#: in the UI rather than silently offering a migration that does not exist.
EXTRACTION_ONLY_PATTERNS: frozenset[str] = frozenset({"wildfly"})

STACK_LABELS: dict[str, str] = {spec.pattern: spec.label for spec in STACK_SPECS}


def detect_stacks(workspace_dir: str) -> list[dict]:
    """Every stack found in the workspace, in STACK_ORDER.

    Returns `[{"pattern", "label", "evidence": [str, ...], "extraction_only": bool}, ...]`,
    each with at least one evidence line. One pass over the repo, testing every
    spec against each file, because this runs inline in the upload request.
    """
    root = Path(workspace_dir).resolve()
    if not root.exists():
        return []

    evidence: dict[str, list[str]] = {spec.pattern: [] for spec in STACK_SPECS}

    for path in scannable_files(root, _SCAN_SUFFIXES):
        if all(len(hits) >= _MAX_EVIDENCE_PER_STACK for hits in evidence.values()):
            break
        rel = str(path.relative_to(root))
        name = path.name.lower()
        suffix = path.suffix.lower()

        # Read lazily: a file is only opened if some spec still wants content
        # evidence from it, which keeps a repo of nothing but .java files from
        # being read end to end once the Java spec is already satisfied.
        text: str | None = None
        for spec in STACK_SPECS:
            hits = evidence[spec.pattern]
            if len(hits) >= _MAX_EVIDENCE_PER_STACK:
                continue

            if name in spec.filenames:
                hits.append(f"{rel}: present")
                continue
            if suffix and suffix in spec.suffixes:
                hits.append(f"{rel}: present")
                continue
            if not spec.content:
                continue

            if text is None:
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    text = ""
            if not text:
                continue
            for pattern in spec.content:
                match = pattern.search(text)
                if match:
                    hits.append(f"{rel}: matched `{match.group(0).strip()}`")
                    break

    return [
        {
            "pattern": spec.pattern,
            "label": spec.label,
            "evidence": evidence[spec.pattern],
            "extraction_only": spec.pattern in EXTRACTION_ONLY_PATTERNS,
        }
        for spec in STACK_SPECS
        if evidence[spec.pattern]
    ]


def to_markdown(stacks: list[dict], source: str = "deterministic scan") -> str:
    """The stack inventory, as the section that opens the combined RE document.

    The evidence travels with the finding into the document the reviewer signs
    off on — a stack inventory with the evidence stripped out asks them to take
    the detection on faith.
    """
    if not stacks:
        return (
            "## Detected Technology Stacks\n\n"
            "No known stack was detected. The repository may use a technology this pipeline "
            "has no detector for; nothing below should be read as a statement that the "
            "repository is empty."
        )

    lines = ["## Detected Technology Stacks", ""]
    lines.append(f"Detected by {source}. Every row carries the evidence that produced it.")
    lines.append("")
    lines.append("| Stack | Reverse engineered by | Evidence |")
    lines.append("|---|---|---|")
    for stack in stacks:
        cited = "<br>".join(
            _format_evidence(e) for e in stack["evidence"][:_MAX_EVIDENCE_PER_STACK]
        )
        skill = f"`{stack['pattern']}` RE stage"
        if stack.get("extraction_only"):
            skill += " (extraction only — no migration target)"
        lines.append(f"| {stack['label']} | {skill} | {cited or '—'} |")
    return "\n".join(lines)


def _format_evidence(line: str) -> str:
    """One `path: finding` evidence line, as a table cell.

    Only the path is wrapped in backticks. The finding half already carries its
    own backticks around the matched text (`matched \\`ojdbc8\\``), and wrapping
    the whole line would nest them and break the code span in both the rendered
    document and the UI.
    """
    path, _, rest = line.partition(": ")
    cell = f"`{path}` — {rest}" if rest else f"`{line}`"
    # A pipe anywhere in a cell ends the column early, so escape it.
    return cell.replace("|", "\\|")
