"""
Workspace tools for the Solr 4 -> 9 pattern.

There is no real Solr server to build/deploy against in this environment,
so validation is a deterministic static check of the Solr XML config
(`solrconfig.xml`, `schema.xml`, `solr.xml`, `core.properties`) instead of
a real `run_command` build — well-formedness plus a scan for elements and
classes that were removed or renamed between Solr 4 and Solr 9. The
validator agent still does the judgment (reading the report and deciding
pass/fail as JSON) — only the fact-gathering is deterministic.
"""
from ..shared import fswalk
import re
import xml.etree.ElementTree as ET

from ..shared.adk_compat import ToolContext

from ..shared.workspace_tools import (  # noqa: F401 (re-exported)
    EXCLUDED_DIRS,
    list_files,
    read_file,
    replace_in_file,
    signal_build_success,
    workspace_root,
    write_file,
)

_CONFIG_FILENAMES = {"solrconfig.xml", "schema.xml", "solr.xml", "managed-schema"}

# (regex over the raw file text, message) -- deprecated/removed Solr 4-era config.
_DEPRECATED_PATTERNS: list[tuple[str, str]] = [
    (r"solr\.TrieIntField|solr\.TrieLongField|solr\.TrieFloatField|solr\.TrieDoubleField|solr\.TrieDateField",
     "Trie*Field types were removed in Solr 8 — use the Point field types (solr.IntPointField, solr.LongPointField, solr.FloatPointField, solr.DoublePointField, solr.DatePointField)."),
    (r"<requestHandler\s+name=\"/update/extract\"", "The /update/extract (Solr Cell) handler is no longer registered by default in modern Solr — register it explicitly via the extraction contrib if still needed."),
    (r"class=\"solr\.spelling\.SpellingQueryConverter\"", "SpellingQueryConverter was removed in Solr 7 — use WordBreakSolrSpellChecker or a modern spellcheck component."),
    (r"<updateRequestProcessorChain\b[^>]*>\s*</updateRequestProcessorChain>", "Empty updateRequestProcessorChain — verify it wasn't accidentally emptied during migration."),
    (r"solr\.DirectSolrSpellChecker", None),  # informational only, not necessarily an error
    (r"<field\s+name=\"_version_\"[^>]*indexed=\"false\"", "_version_ field must be indexed for optimistic concurrency / real-time get since Solr 4.x — do not set indexed=\"false\"."),
    (r"class=\"solr\.LatLonType\"", "solr.LatLonType is deprecated — use solr.LatLonPointSpatialField."),
    (r"<luceneMatchVersion>\s*[4-7]\.", "luceneMatchVersion is older than 8 — set it to the Solr 9 release (e.g. 9.x) and reindex."),
    (r"<defaultSearchField>", "<defaultSearchField> was removed in Solr 7 — set df in the request handler defaults."),
    (r"<solrQueryParser\b", "<solrQueryParser defaultOperator> was removed in Solr 7 — set q.op in the request handler defaults."),
    (r"\benablePositionIncrements\s*=", "enablePositionIncrements is no longer accepted by the filter factories — remove it."),
    (r"solr\.StandardFilterFactory", "StandardFilterFactory was removed in Solr 8 — remove it from the analyzer chain."),
    (r"solr\.(?:Fast)?LRUCache|solr\.LFUCache", "LRUCache/FastLRUCache/LFUCache were removed in Solr 9 — use solr.CaffeineCache."),
    (r"solr\.admin\.AdminHandlers", "solr.admin.AdminHandlers was removed in Solr 6 — the admin handlers are implicit; delete it."),
    (r"<mergePolicy\b", "<mergePolicy> was removed in Solr 7 — use <mergePolicyFactory>."),
    (r"<lib\s+dir=\"[^\"]*contrib/", "contrib/ became modules/ in Solr 9 — enable modules (solr.modules) instead of <lib> paths into contrib/."),
    (r"\benableRemoteStreaming\s*=", "Remote streaming is no longer configured in solrconfig.xml in Solr 9 — use the system property if still needed."),
]


def validate_solr_config(tool_context: ToolContext) -> str:
    """Statically validate every Solr config file in the workspace.

    Checks XML well-formedness for solrconfig.xml/schema.xml/solr.xml/
    managed-schema, and scans their raw text for elements, field types, and
    classes known to be deprecated or removed between Solr 4 and Solr 9.

    Returns a plain-text report — one line per file checked, and one line
    per issue found (or "No issues found." if the file is clean). Read
    this report and decide pass/fail yourself; this tool does not decide
    anything.
    """
    root = workspace_root(tool_context)
    checked: list[str] = []
    lines: list[str] = []
    any_issue = False

    for path in sorted(fswalk.files(root)):
        if not path.is_file() or path.name not in _CONFIG_FILENAMES:
            continue
        rel_parts = path.relative_to(root).parts
        if EXCLUDED_DIRS & set(rel_parts):
            continue
        rel = path.relative_to(root).as_posix()
        checked.append(rel)

        file_issues: list[str] = []
        if path.suffix.lower() == ".xml":
            try:
                ET.parse(path)
            except ET.ParseError as exc:
                file_issues.append(f"XML parse error — {exc}")

        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            file_issues.append(f"could not read file — {exc}")
            text = ""

        for pattern, message in _DEPRECATED_PATTERNS:
            if message and re.search(pattern, text):
                file_issues.append(message)

        if file_issues:
            any_issue = True
            lines.append(f"{rel}: ISSUES FOUND")
            for issue in file_issues:
                lines.append(f"  - {issue}")
        else:
            lines.append(f"{rel}: No issues found.")

    if not checked:
        return "No Solr config files (solrconfig.xml/schema.xml/solr.xml/managed-schema) found in the workspace."

    header = f"Checked {len(checked)} Solr config file(s)."
    footer = "OVERALL: issues found." if any_issue else "OVERALL: no issues found."
    return "\n".join([header, *lines, footer])
