"""
Keeps a stack-discovery document a description of the repository as it is.

The discovery agents are instructed never to discuss migration, upgrades or
recommendations (skills/stack-discovery-re), but an instruction is not a
guarantee. This is the deterministic backstop applied to every discovery
section before it is stored or shown:

- a heading about migration / recommendations / next steps / target state is
  removed together with its whole body;
- a list item or table row that contains such language is removed;
- in a paragraph, only the offending sentences are removed;
- a table whose header row is about migration is removed whole;
- fenced code blocks and `inline code` are never inspected or changed, so file
  paths, coordinates and identifiers (`db/migration/V1__init.sql`,
  `UpgradeService`) are kept.

Schema-change tooling is a repository artifact, not a migration proposal, so
"Flyway migration", "Liquibase changeset" and the like are not matched.

`neutral_ids` replaces the detector's pattern ids (java-8-to-25, …), which name
migrations, with plain stack ids in the final document.
"""
import re

# Advisory or migration language. Matched against prose with code spans removed.
_TERMS = re.compile(
    r"""
      \bmigrat(?:e|es|ed|ing|ion|ions|able|ability)\b
    | \bupgrad\w*
    | \bmoderni[sz]\w*
    | \bre-?platform\w*
    | \bre-?host\w*
    | \bre-?architect\w*
    | \bport(?:ed|ing)?\s+(?:to|onto)\b
    | \bend[\s-]of[\s-](?:life|support)\b
    | \bEOL\b
    | \bout\s+of\s+(?:support|maintenance)\b
    | \bdeprecat\w*
    | \bno\s+longer\s+(?:supported|available|maintained)\b
    | \bremoved\s+in\s+(?:java|jdk|jakarta|solr|oracle|version|release)\b
    | \bremediat\w*
    | \bincompatib\w*
    | \bbackport\w*
    | \breadiness\b
    | \bblockers?\b
    | \bnext\s+steps?\b
    | \broadmap\b
    | \bfuture[\s-]state\b
    | \bto-be\b
    | \btarget\s+(?:version|platform|state|runtime|jdk|java|release|architecture|environment|stack|database)\b
    | \b(?:is|are|we|strongly|highly|it\s+is)\s+recommended\b
    | \brecommend(?:s|ed)?\s+(?:to|that|using|replacing|moving|adopting|upgrading|switching)\b
    | \brecommendations?\s*:
    | \bshould\s+(?:be\s+)?(?:replac|upgrad|migrat|mov|refactor|consider|adopt|remov|rewrit|introduc|switch|convert|modern|retir|decommission)\w*
    | \bconsider\s+(?:replacing|moving|adopting|upgrading|migrating|switching|using|introducing|retiring)\b
    | \b(?:java|jdk)\s*(?:8|1\.8|11|17|21)\s*(?:→|->|=>|to)\s*(?:java|jdk)?\s*\d+
    | \bjava\s*25\b|\bjdk\s*25\b
    | \b23ai\b
    | \bsolr\s*9(?:\.\w+)?\b
    | \bpub/?sub\b
    | \bgoogle\s+cloud\b|\bGCP\b
    | \beffort\s+(?:estimate|sizing)\b|\bstory\s+points\b|\bt-shirt\s+siz\w*
    | \d[\w.]*\s*(?:→|->|=>)\s*\d
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Headings that introduce advice even without one of the terms above.
_HEADING_ONLY = re.compile(
    r"\brecommendations?\b|\bimprovements?\b|\bsuggest\w*|\bopportunit\w*|\bproposed\b|\bgap\s+analysis\b",
    re.IGNORECASE,
)

# Schema-change tooling: artifacts the repository contains, not proposals.
_ARTIFACT_PHRASES = re.compile(
    r"\b(?:flyway|liquibase|schema|database|db|sql|data(?:base)?\s+change)\s+migrations?\b"
    r"|\bmigrations?\s+(?:scripts?|files?|folder|director(?:y|ies)|changesets?|versions?)\b",
    re.IGNORECASE,
)

_FENCE = re.compile(r"^\s*(```|~~~)")
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_LIST_ITEM = re.compile(r"^(\s*)(?:[-*+]|\d+[.)])\s+")
_TABLE_ROW = re.compile(r"^\s*\|")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}")
_CODE_SPAN = re.compile(r"`[^`\n]*`")
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z*_`(\[])")
_HTML_COMMENT = re.compile(r"^\s*<!--.*-->\s*$")


def _prose(text: str) -> str:
    return _ARTIFACT_PHRASES.sub(" ", _CODE_SPAN.sub(" ", text))


def is_migration_language(text: str) -> bool:
    return bool(_TERMS.search(_prose(text)))


def _heading_is_advice(title: str) -> bool:
    prose = _prose(title)
    return bool(_TERMS.search(prose) or _HEADING_ONLY.search(prose))


def scrub(markdown: str) -> tuple[str, list[str]]:
    """(cleaned markdown, removed fragments). Idempotent."""
    if not markdown:
        return markdown, []
    lines = markdown.split("\n")
    out: list[str] = []
    removed: list[str] = []
    in_fence = False
    skip_level = 0            # >0: inside a removed heading's body
    i = 0
    while i < len(lines):
        line = lines[i]
        if _FENCE.match(line):
            in_fence = not in_fence
            if not skip_level:
                out.append(line)
            i += 1
            continue
        if in_fence:
            if not skip_level:
                out.append(line)
            i += 1
            continue

        heading = _HEADING.match(line)
        if heading:
            level = len(heading.group(1))
            if skip_level and level > skip_level:
                i += 1
                continue
            skip_level = 0
            if _heading_is_advice(heading.group(2)):
                skip_level = level
                removed.append(line.strip())
                i += 1
                continue
            out.append(line)
            i += 1
            continue
        if skip_level:
            # Section markers belong to the parser, never to a heading's body.
            if _HTML_COMMENT.match(line) and "SECTION:" in line:
                skip_level = 0
                out.append(line)
            i += 1
            continue

        if _TABLE_ROW.match(line):
            j = i
            while j < len(lines) and _TABLE_ROW.match(lines[j]):
                j += 1
            table = lines[i:j]
            has_header = len(table) > 1 and _TABLE_SEP.match(table[1])
            if has_header and is_migration_language(table[0]):
                removed.append(table[0].strip())
                i = j
                continue
            kept = []
            for k, row in enumerate(table):
                if (has_header and k < 2) or not is_migration_language(row):
                    kept.append(row)
                else:
                    removed.append(row.strip())
            # A table left with only its header said nothing but the removed rows.
            if not (has_header and len(kept) == 2 and len(table) > 2):
                out.extend(kept)
            i = j
            continue

        item = _LIST_ITEM.match(line)
        if item:
            indent = len(item.group(1))
            j = i + 1
            while (j < len(lines) and lines[j].strip()
                   and not _LIST_ITEM.match(lines[j]) and not _HEADING.match(lines[j])
                   and not _TABLE_ROW.match(lines[j])
                   and len(lines[j]) - len(lines[j].lstrip()) > indent):
                j += 1
            block = lines[i:j]
            if is_migration_language(" ".join(block)):
                removed.append(" ".join(s.strip() for s in block))
                # Nested items belong to the removed one.
                while (j < len(lines) and _LIST_ITEM.match(lines[j])
                       and len(_LIST_ITEM.match(lines[j]).group(1)) > indent):
                    j += 1
            else:
                out.extend(block)
            i = j
            continue

        if not line.strip() or _HTML_COMMENT.match(line):
            out.append(line)
            i += 1
            continue

        # A paragraph: consecutive plain lines. Drop only the offending sentences.
        j = i
        while (j < len(lines) and lines[j].strip() and not _HEADING.match(lines[j])
               and not _LIST_ITEM.match(lines[j]) and not _TABLE_ROW.match(lines[j])
               and not _FENCE.match(lines[j]) and not _HTML_COMMENT.match(lines[j])):
            j += 1
        paragraph = lines[i:j]
        if is_migration_language(" ".join(paragraph)):
            sentences = _SENTENCE.split(" ".join(s.strip() for s in paragraph))
            kept = [s for s in sentences if not is_migration_language(s)]
            removed.extend(s for s in sentences if is_migration_language(s))
            if kept:
                out.append(" ".join(kept))
        else:
            out.extend(paragraph)
        i = j

    text = re.sub(r"\n{3,}", "\n\n", "\n".join(out))
    return text, removed


#: The detector's pattern ids name migrations; the document names stacks.
NEUTRAL_IDS: dict[str, str] = {
    "java-8-to-25": "java",
    "java-8-to-11": "java",
    "jsp-to-react-bff": "jsp",
    "oracle-19c-to-23ai": "oracle",
    "solr-4-to-9": "solr",
    "tibco-ems-to-pubsub": "tibco-ems",
}


def neutral_ids(text: str) -> str:
    for pattern, stack in NEUTRAL_IDS.items():
        text = re.sub(rf"(?<![\w-]){re.escape(pattern)}(?![\w-])", stack, text)
    return text
