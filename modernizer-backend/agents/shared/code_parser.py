import re
from typing import List
from models.schemas import GeneratedFile


def parse_generated_files(raw: str, target_lang: str = "java") -> List[GeneratedFile]:
    """Parse ```lang:path/to/file ... ``` fenced blocks from model output."""
    pattern = re.compile(
        r"```(?P<lang>\w+)?(?::(?P<path>[^\n]+))?\n(?P<code>.*?)```",
        re.DOTALL,
    )
    files: List[GeneratedFile] = []
    for m in pattern.finditer(raw):
        lang = (m.group("lang") or target_lang).strip()
        path = (m.group("path") or f"output.{lang}").strip()
        code = m.group("code").strip()
        files.append(GeneratedFile(path=path, content=code, language=lang))

    if not files:
        ext = {"go": "go", "java": "java", "kotlin": "kt"}.get(target_lang.lower(), "txt")
        files.append(GeneratedFile(
            path=f"output.{ext}",
            content=raw.strip(),
            language=target_lang.lower(),
        ))
    return files


def is_test_file(path: str, lang: str) -> bool:
    """Return True when *path* looks like a test file for the given language."""
    p = path.lower()
    if lang == "go":
        return p.endswith("_test.go")
    # Java (java25 and quarkus): canonical Maven layout or Test suffix
    return "src/test/" in p or p.endswith("test.java")


def merge_files_by_path(original: List[dict], fixes: List[dict]) -> List[dict]:
    """Merge *fixes* into *original* by path, overwriting matching entries.

    Files in *fixes* that are not in *original* are appended.
    Order of *original* is preserved; new files go at the end.
    """
    by_path: dict = {f["path"]: f for f in original}
    for fix in fixes:
        by_path[fix["path"]] = fix
    return list(by_path.values())
