"""
Deterministic (non-LLM) detection of "companion" migration patterns — cross-cutting
library/dependency signals inside an uploaded repo that suggest additional migrations
are needed for the app to keep working, beyond the primary pattern the user selected.

Example: a Java 8 repo that pulls in an Oracle JDBC driver and a SolrJ client should
be offered the Oracle 19c->23ai and Solr 4x->9x migrations alongside the Java 8->25
one, instead of requiring three separate manual uploads.

This intentionally mirrors `dependency_graph.py`'s philosophy: cheap regex-based
static analysis over real files, run once at upload time, before any agent sees the
code. Evidence strings are returned alongside each recommendation so the decision is
auditable, not an opaque AI guess.

v1 scope: only `java-8-to-25` has companion candidates wired up (see
COMPANION_CANDIDATES). The dict shape is deliberately generic so more primaries can
be added later without restructuring.
"""
import re
from collections.abc import Iterator
from pathlib import Path

from .dependency_graph import EXCLUDED_DIRS

COMPANION_CANDIDATES: dict[str, list[str]] = {
    "java-8-to-25": ["oracle-19c-to-23ai", "solr-4-to-9", "tibco-ems-to-pubsub"],
}

COMPANION_LABELS: dict[str, str] = {
    "oracle-19c-to-23ai": "Oracle 19c → 23ai",
    "solr-4-to-9": "Solr 4x → Solr 9x",
    "tibco-ems-to-pubsub": "TIBCO EMS → Google Cloud Pub/Sub",
    "java-8-to-25": "Java 8 → Java 25",
}

_SCAN_SUFFIXES = {".xml", ".properties", ".yml", ".yaml", ".java", ".gradle", ".kts"}

_ORACLE_PATTERNS = [
    re.compile(r"com\.oracle\.database\.jdbc", re.IGNORECASE),
    re.compile(r"\bojdbc\d*\b", re.IGNORECASE),
    re.compile(r"oracle\.jdbc\.(?:driver\.)?OracleDriver"),
    re.compile(r"jdbc:oracle:thin:"),
]

_SOLR_PATTERNS = [
    re.compile(r"org\.apache\.solr"),
    re.compile(r"\bsolr-solrj\b"),
    re.compile(r"\b(?:Http|Cloud)Solr(?:Client|Server)\b"),
    re.compile(r"org\.apache\.solr\.client\.solrj"),
]

_TIBCO_EMS_PATTERNS = [
    re.compile(r"\btibjms\b", re.IGNORECASE),
    re.compile(r"com\.tibco\.tibjms\.Tibjms(?:ConnectionFactory|Queue|Topic)"),
    re.compile(r"tibjmsnaming", re.IGNORECASE),
]

_EVIDENCE_PATTERNS: dict[str, list[re.Pattern]] = {
    "oracle-19c-to-23ai": _ORACLE_PATTERNS,
    "solr-4-to-9": _SOLR_PATTERNS,
    "tibco-ems-to-pubsub": _TIBCO_EMS_PATTERNS,
}

_MAX_EVIDENCE_PER_PATTERN = 5


def _scannable_files(root: Path) -> Iterator[Path]:
    """Repository files worth grepping for library signatures — build files
    (pom.xml/*.gradle/*.kts), sources and config, minus VCS/build output."""
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if EXCLUDED_DIRS & set(path.relative_to(root).parts):
            continue
        if path.suffix.lower() in _SCAN_SUFFIXES:
            yield path


def detect_companions(workspace_dir: str, primary_pattern: str) -> list[dict]:
    """Returns [{"pattern": str, "label": str, "evidence": [str, ...]}, ...] for
    each candidate companion pattern with at least one evidence hit. Empty list if
    the primary pattern has no candidates or nothing was found.

    Walks the workspace once and tests every candidate against each file's
    content, rather than re-walking and re-reading per candidate: this runs
    inline in the upload request, so it stays a single pass over the repo.
    """
    candidates = COMPANION_CANDIDATES.get(primary_pattern, [])
    if not candidates:
        return []

    root = Path(workspace_dir).resolve()
    if not root.exists():
        return []

    evidence: dict[str, list[str]] = {c: [] for c in candidates}
    for path in _scannable_files(root):
        if all(len(hits) >= _MAX_EVIDENCE_PER_PATTERN for hits in evidence.values()):
            break
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        rel = str(path.relative_to(root))
        for candidate in candidates:
            hits = evidence[candidate]
            if len(hits) >= _MAX_EVIDENCE_PER_PATTERN:
                continue
            for pattern in _EVIDENCE_PATTERNS.get(candidate, []):
                match = pattern.search(text)
                if match:
                    hits.append(f"{rel}: matched `{match.group(0).strip()}`")
                    break

    return [
        {
            "pattern": candidate,
            "label": COMPANION_LABELS.get(candidate, candidate),
            "evidence": evidence[candidate],
        }
        for candidate in candidates if evidence[candidate]
    ]
