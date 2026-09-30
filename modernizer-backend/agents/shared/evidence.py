"""
Quoting code as evidence without quoting secrets.

The deterministic inventories show the first matching line of each finding so a
planner can write a real "before" snippet. That line can hold a credential
(a password property, a connection string with user:password@), and the
document is shown in the UI and sent to the planning model, so it is scrubbed
here. The path and line number still identify the line.
"""
import re

_SECRET_LINE = re.compile(r"passw(?:or)?d|pwd|secret|token|api[_-]?key|credential", re.IGNORECASE)


def redact(value: str) -> str:
    """Remove credentials from connection strings: jdbc:oracle:thin:user/pass@host
    and scheme://user:pass@host."""
    value = re.sub(r"(jdbc:oracle:\w+:)[^@\s]*@", r"\1<redacted>@", value)
    return re.sub(r"(//)[^@/\s]*@", r"\1<redacted>@", value)


def sample(line: str, limit: int = 160) -> str:
    """A matching line fit for a markdown table cell — never a secret."""
    if _SECRET_LINE.search(line):
        return "(line names a credential — not reproduced)"
    return redact(line.strip())[:limit].replace("|", "/")
