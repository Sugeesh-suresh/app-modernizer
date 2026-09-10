"""
Scoped read/write tools for the skill-curator agent — the one agent in this
app with write access to the skill library itself (`agents/skills/`), so
that what a pipeline learns on a real run can improve future runs.

This is a materially more sensitive capability than the workspace tools
(which are sandboxed to one session's throwaway temp directory): these
tools touch the actual prompt files that drive every future session. The
safety rails are:

  1. Every call is scoped to an explicit `allowed_skills` allowlist fixed
     at agent-construction time in Python (one per pattern, in each
     pattern's agents.py) — never decided by the LLM itself, and never
     spanning skills outside the pattern that actually ran.
  2. `write_skill_file` only accepts `.md` files, resolved strictly within
     one allowed skill's own directory (the same resolve-and-check-parents
     pattern used by agents/shared/workspace_tools.py) — it cannot reach
     `__init__.py`, `agents.py`, or any other skill's directory.
  3. It only ever *overwrites the content of* an existing markdown file
     inside an allowed skill directory — it cannot create new skill
     directories, rename/delete files, or write anywhere outside
     `agents/skills/<allowed-skill>/`.
"""
from pathlib import Path

_SKILLS_DIR = Path(__file__).parent.parent / "skills"


def _resolve_within_skill(skill_name: str, relative_path: str, allowed: set[str]) -> Path:
    if skill_name not in allowed:
        raise ValueError(f"'{skill_name}' is not one of this run's allowed skills: {sorted(allowed)}")
    skill_root = (_SKILLS_DIR / skill_name).resolve()
    if _SKILLS_DIR not in skill_root.parents or not skill_root.is_dir():
        raise ValueError(f"'{skill_name}' is not a real skill directory")
    candidate = (skill_root / relative_path).resolve()
    if candidate != skill_root and skill_root not in candidate.parents:
        raise ValueError(f"path '{relative_path}' escapes the '{skill_name}' skill directory")
    return candidate


def make_skill_curator_tools(allowed_skills: list[str]):
    """Build a (list_skill_files, read_skill_file, write_skill_file) tool
    triple restricted to exactly *allowed_skills* — the skills actually
    used by the pattern that just ran."""
    allowed = set(allowed_skills)
    allowed_list = ", ".join(sorted(allowed))

    def list_skill_files(skill_name: str) -> str:
        try:
            root = _resolve_within_skill(skill_name, ".", allowed)
        except ValueError as exc:
            return f"ERROR: {exc}"
        paths = [str(p.relative_to(root)) for p in sorted(root.rglob("*")) if p.is_file()]
        return "\n".join(paths) if paths else "(no files found)"

    def read_skill_file(skill_name: str, relative_path: str) -> str:
        try:
            target = _resolve_within_skill(skill_name, relative_path, allowed)
        except ValueError as exc:
            return f"ERROR: {exc}"
        if not target.is_file():
            return f"ERROR: '{relative_path}' is not a file in '{skill_name}'."
        try:
            return target.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            return f"ERROR: could not read '{relative_path}': {exc}"

    def write_skill_file(skill_name: str, relative_path: str, content: str) -> str:
        try:
            target = _resolve_within_skill(skill_name, relative_path, allowed)
        except ValueError as exc:
            return f"ERROR: {exc}"
        if target.suffix.lower() != ".md":
            return f"ERROR: only .md files may be written, got '{relative_path}'."
        if not target.exists():
            return (
                f"ERROR: '{relative_path}' does not exist in '{skill_name}' — this tool refines "
                "existing skill docs, it does not create new ones. Call list_skill_files first "
                "to see what's actually there."
            )
        try:
            target.write_text(content, encoding="utf-8")
        except Exception as exc:
            return f"ERROR: could not write '{relative_path}': {exc}"
        return f"Wrote {len(content)} chars to {skill_name}/{relative_path}."

    list_skill_files.__doc__ = (
        "List every file in one of this run's skills.\n\n"
        f"Args:\n    skill_name: One of this run's allowed skills: {allowed_list}.\n\n"
        "Returns:\n    Newline-separated relative file paths (e.g. 'SKILL.md', "
        "'references/foo.md'), or a string starting with \"ERROR:\"."
    )
    read_skill_file.__doc__ = (
        "Read the current content of one file within one of this run's skills.\n\n"
        f"Args:\n    skill_name: One of this run's allowed skills: {allowed_list}.\n"
        "    relative_path: File path relative to that skill's own directory, exactly as "
        "returned by list_skill_files.\n\n"
        "Returns:\n    The file's text content, or a string starting with \"ERROR:\"."
    )
    write_skill_file.__doc__ = (
        "Overwrite one EXISTING markdown file within one of this run's skills with refined "
        "content. Cannot create new files, cannot touch non-.md files, cannot write outside "
        "the given skill's own directory.\n\n"
        f"Args:\n    skill_name: One of this run's allowed skills: {allowed_list}.\n"
        "    relative_path: File path relative to that skill's own directory, exactly as "
        "returned by list_skill_files.\n    content: The COMPLETE new content of the file "
        "(full overwrite, not a patch/diff) — preserve everything you are not deliberately "
        "changing, including the YAML frontmatter and any existing '## Learned Patterns' section.\n\n"
        "Returns:\n    A short confirmation message, or a string starting with \"ERROR:\"."
    )

    return list_skill_files, read_skill_file, write_skill_file
