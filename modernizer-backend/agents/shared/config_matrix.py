"""
Configuration matrix: every environment configuration key against every
profile, read from the files — no model involved.

Spring Boot environment files (`application.properties|yml|yaml`,
`application-<profile>.*`, `bootstrap*.*`) are parsed per configuration folder:
properties line by line, YAML with PyYAML (multi-document files with
`spring.config.activate.on-profile` / `spring.profiles` sections included) and
flattened to dotted keys. The table shows, per folder, the keys whose value
differs between profiles first, then keys present in only some profiles, then a
count of the keys identical everywhere.

Secrets never appear: a key that names a credential (password, secret, token,
key, credential, passphrase) or a value that is encrypted or a secret reference
(`ENC(...)`, `sm://`, `${vault:...}`) is shown as `[REDACTED]` / `[encrypted]`
/ `[secret reference]`.
"""
import hashlib
import re
from pathlib import Path, PurePosixPath

import yaml

from .dependency_graph import EXCLUDED_DIRS

_FILE = re.compile(r"^(application|bootstrap)(?:-([\w.-]+?))?\.(properties|ya?ml)$", re.I)
_SECRET_KEY = re.compile(r"pass(?:word|wd|phrase)?|pwd|secret|token|credential|private[-_.]?key|api[-_.]?key|"
                         r"access[-_.]?key|client[-_.]?secret|\bkey$", re.I)
_TEST = re.compile(r"(?:^|/)(?:src/test|test|tests)/", re.I)
_MAX_VALUE = 70


def _flatten(data, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    if isinstance(data, dict):
        for k, v in data.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            out.update(_flatten(v, key))
    elif isinstance(data, list):
        out[prefix] = ", ".join(str(x) for x in data) if all(not isinstance(x, (dict, list)) for x in data) \
            else f"[{len(data)} entries]"
    else:
        out[prefix] = "" if data is None else str(data)
    return out


def _properties(text: str) -> dict[str, str]:
    out, pending = {}, ""
    for raw in text.splitlines():
        line = pending + raw.strip()
        pending = ""
        if not line or line.startswith(("#", "!")):
            continue
        if line.endswith("\\"):
            pending = line[:-1]
            continue
        m = re.match(r"([^=:\s]+)\s*[=:]\s*(.*)$", line) or re.match(r"(\S+)\s+(.*)$", line)
        if m:
            out[m.group(1)] = m.group(2).strip()
    return out


def _yaml_documents(text: str, file_profile: str) -> list[tuple[str, dict[str, str]]]:
    """[(profile, flattened keys)] — a document naming its own profile overrides the file's."""
    try:
        docs = [d for d in yaml.safe_load_all(text) if isinstance(d, dict)]
    except yaml.YAMLError:
        return []
    out = []
    for doc in docs:
        flat = _flatten(doc)
        own = flat.get("spring.config.activate.on-profile") or flat.get("spring.profiles")
        out.append((own or file_profile, flat))
    return out


def display(key: str, value: str) -> str:
    """A value as it may appear in a document."""
    v = value.strip()
    if re.match(r"^ENC\(.*\)$", v):
        return "[encrypted]"
    if re.match(r"^\$\{?(?:sm://|vault:|secret:)|^sm://", v):
        return "[secret reference]"
    if _SECRET_KEY.search(key.rsplit(".", 1)[-1]) and v and not re.fullmatch(r"\$\{[^}]*\}", v):
        return "[REDACTED]"
    v = re.sub(r"(//[^:/@\s]+:)[^@/\s]+@", r"\1[REDACTED]@", v)       # user:password@host in URLs
    return v if len(v) <= _MAX_VALUE else v[:_MAX_VALUE - 1] + "…"


def scan(workspace_dir: str) -> list[dict]:
    """[{"folder", "profiles": [...], "values": {key: {profile: value}}}] per configuration folder."""
    root = Path(workspace_dir)
    if not root.is_dir():
        return []
    folders: dict[str, dict] = {}
    for path in sorted(root.rglob("*")):
        m = _FILE.match(path.name)
        if not m or not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if EXCLUDED_DIRS & set(PurePosixPath(rel).parts) or _TEST.search(rel):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        folder = str(PurePosixPath(rel).parent)
        profile = m.group(2) or ("default" if m.group(1).lower() == "application" else "bootstrap")
        entry = folders.setdefault(folder, {"folder": folder, "profiles": [], "values": {}, "raw": {}})
        documents = ([(profile, _properties(text))] if m.group(3).lower() == "properties"
                     else _yaml_documents(text, profile))
        for prof, keys in documents:
            if prof not in entry["profiles"]:
                entry["profiles"].append(prof)
            for key, value in keys.items():
                entry["values"].setdefault(key, {})[prof] = display(key, value)
                # Compared, never shown: two secrets that both display as
                # "[encrypted]" still differ between environments.
                entry["raw"].setdefault(key, {})[prof] = hashlib.sha256(value.strip().encode()).hexdigest()
    result = []
    for entry in folders.values():
        rest = sorted(p for p in entry["profiles"] if p not in ("default", "bootstrap"))
        entry["profiles"] = [p for p in ("bootstrap", "default") if p in entry["profiles"]] + rest
        result.append(entry)
    return result


def _cell(text: str) -> str:
    return (f"`{text}`" if text else "—").replace("|", "\\|")


def _shown(entry) -> str:
    if entry is None:
        return "—"
    value, inherited = entry
    return "(default)" if inherited else _cell(value)


def _inherit(matrix: dict, table: dict) -> dict[str, dict[str, tuple[str, bool]]]:
    out = {}
    for key, by_profile in table.items():
        row = {p: (v, False) for p, v in by_profile.items()}
        if "default" in by_profile:
            for p in matrix["profiles"]:
                if p not in row and p not in ("default", "bootstrap"):
                    row[p] = (by_profile["default"], True)
        out[key] = row
    return out


def effective(matrix: dict) -> dict[str, dict[str, tuple[str, bool]]]:
    """{key: {profile: (value, inherited)}} — a profile file inherits every key it
    does not set from the folder's default application file, as Spring does."""
    return _inherit(matrix, matrix["values"])


def to_markdown(matrices: list[dict], max_rows: int | None = 150) -> str:
    """`max_rows=None`: every key."""
    multi = [m for m in matrices if m["values"]]
    if not multi:
        return ""
    lines = ["## Configuration Matrix (computed)", "",
             "_Read from the environment configuration files by the pipeline. Secrets are never shown._", ""]
    for m in multi:
        profiles, values = m["profiles"], effective(m)
        raw = _inherit(m, m.get("raw") or m["values"])
        differs = [k for k, v in sorted(raw.items()) if len(v) == len(profiles) and len({x for x, _ in v.values()}) > 1]
        partial = [k for k, v in sorted(values.items()) if len(v) < len(profiles)]
        same = len(values) - len(differs) - len(partial)
        lines += [f"### `{m['folder']}` — {len(profiles)} profile{'s' if len(profiles) != 1 else ''}: "
                  + ", ".join(f"`{p}`" for p in profiles), ""]
        if len(profiles) == 1:
            lines += ["| Key | Value |", "|---|---|"]
            lines += [f"| `{k}` | {_cell(v[profiles[0]][0])} |" for k, v in list(sorted(values.items()))[:max_rows]]
        else:
            lines += ["| Key | " + " | ".join(profiles) + " |", "|---|" + "---|" * len(profiles)]
            rows = differs + partial
            for k in rows[:max_rows]:
                lines.append(f"| `{k}`{' (not in every profile)' if k in partial else ''} | "
                             + " | ".join(_shown(values[k].get(p)) for p in profiles) + " |")
            if max_rows is not None and len(rows) > max_rows:
                lines.append(f"| …and {len(rows) - max_rows} more differing keys | " + " | " * len(profiles))
            lines += ["", f"{len(differs)} keys differ between profiles, {len(partial)} are set in only some, "
                          f"{same} are identical everywhere. \"(default)\": not set in that profile's file, so the "
                          "default file's value applies."]
        lines.append("")
    return "\n".join(lines).rstrip()
