"""
The JDKs a machine already has, found where installers and version managers put them.

`JAVA_HOME` and `PATH` name one JDK, but a developer machine usually has several side by side; the pipelines
need a JDK per Java release and must not download one that is already there. The standard places, per system:

  Windows  %ProgramFiles%\\Java, Eclipse Adoptium, Microsoft, Zulu, Amazon Corretto, BellSoft, Semeru, ...
           (also Program Files (x86), %LocalAppData%\\Programs), the registry's JavaSoft / Adoptium keys,
           %USERPROFILE%\\.jdks, scoop
  macOS    /Library/Java/JavaVirtualMachines/*/Contents/Home, ~/Library/Java/JavaVirtualMachines, Homebrew,
           what `/usr/libexec/java_home -V` lists
  Linux    /usr/lib/jvm, /usr/java, /opt/java, /opt/jdk*, /opt/openjdk*
  all      SDKMAN, jenv, asdf, jabba, IntelliJ's ~/.jdks, Gradle's ~/.gradle/jdks, JAVA*_HOME / JDK*_HOME variables

Only a JDK counts (a folder with both `java` and `javac`). A JDK's version is read from its `release` file,
so finding them starts no process. What the user configured (MIGRATION_JAVA_HOMES, MIGRATION_JAVA_HOME,
JAVA_HOME, PATH) always wins over what is found here (agents/java_8_to_25/preflight.py:configured_homes).
"""
from __future__ import annotations

import os
import platform
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

_WINDOWS_VENDORS = (
    "Java", "Eclipse Adoptium", "Eclipse Foundation", "AdoptOpenJDK", "Microsoft", "Zulu", "Azul", "Amazon Corretto",
    "BellSoft", "Semeru", "IBM", "OpenJDK", "RedHat", "Red Hat", "SapMachine", "GraalVM", "Oracle", "Temurin",
)
_LINUX_PARENTS = ("/usr/lib/jvm", "/usr/lib64/jvm", "/usr/java", "/opt/java", "/usr/local/java")
_OPT_PREFIXES = ("jdk", "openjdk", "java", "temurin", "zulu", "corretto", "graalvm", "semeru", "liberica")
_MANAGER_PARENTS = (  # relative to the user's home
    ".sdkman/candidates/java", ".jenv/versions", ".asdf/installs/java", ".jabba/jdk", ".jdks", ".gradle/jdks",
    ".m2/jdks", "scoop/apps",
)
_ENV_NAME = re.compile(r"^(?:JAVA|JDK)(?:_?\d+)?_HOME(?:_[A-Z0-9]+)*$|^JAVA_HOME_\d+_\w+$", re.I)


@dataclass(frozen=True)
class Jdk:
    home: str
    major: int


def _exe(system: str, name: str) -> str:
    return name + (".exe" if system == "Windows" else "")


def _is_jdk(home: Path, system: str) -> bool:
    return (home / "bin" / _exe(system, "java")).is_file() and (home / "bin" / _exe(system, "javac")).is_file()


def _resolve(path: Path, system: str) -> Path | None:
    """The JDK home a folder stands for: itself, a macOS bundle's Contents/Home, or a `current` link's target."""
    for candidate in (path, path / "Contents" / "Home", path / "libexec" / "openjdk.jdk" / "Contents" / "Home"):
        if _is_jdk(candidate, system):
            try:
                return candidate.resolve()
            except OSError:
                return candidate
    return None


def major_of(home: Path | str, system: str | None = None) -> int | None:
    """The JDK's major version: from its `release` file (`JAVA_VERSION="1.8.0_392"` -> 8, `"17.0.9"` -> 17), else —
    some builds ship none — from `java -version`."""
    home = Path(home)
    try:
        text = (home / "release").read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    m = re.search(r'JAVA_VERSION\s*=\s*"?(\d+)(?:\.(\d+))?', text)
    if m:
        major = int(m.group(1))
        return int(m.group(2)) if major == 1 and m.group(2) else major
    try:
        r = subprocess.run([str(home / "bin" / _exe(system or platform.system(), "java")), "-version"],
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r'version "(\d+)(?:\.(\d+))?', (r.stdout or "") + (r.stderr or ""))
    if not m:
        return None
    major = int(m.group(1))
    return int(m.group(2)) if major == 1 and m.group(2) else major


def _children(parent: Path) -> list[Path]:
    try:
        return sorted((p for p in parent.iterdir() if p.is_dir()), key=lambda p: p.name, reverse=True)
    except OSError:
        return []


def _windows_bases(environ: dict[str, str]) -> list[Path]:
    bases = []
    for var in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
        if environ.get(var):
            bases.append(Path(environ[var]))
    if environ.get("LocalAppData"):
        bases.append(Path(environ["LocalAppData"]) / "Programs")
    return list(dict.fromkeys(bases))


def _windows_registry_homes() -> list[Path]:
    """JavaHome / Path values the JDK installers write (best effort; nothing off Windows)."""
    try:
        import winreg                                   # type: ignore[import-not-found]
    except ImportError:
        return []
    out: list[Path] = []
    roots = [r"SOFTWARE\JavaSoft\JDK", r"SOFTWARE\JavaSoft\Java Development Kit", r"SOFTWARE\Eclipse Adoptium\JDK",
             r"SOFTWARE\Eclipse Foundation\JDK", r"SOFTWARE\AdoptOpenJDK\JDK", r"SOFTWARE\Microsoft\JDK",
             r"SOFTWARE\Azul Systems\Zulu", r"SOFTWARE\Amazon Corretto"]

    def values(key, depth: int) -> None:
        try:
            for name in ("JavaHome", "Path", "InstallationPath"):
                try:
                    out.append(Path(winreg.QueryValueEx(key, name)[0]))
                except OSError:
                    pass
            if depth:
                for i in range(64):
                    try:
                        sub = winreg.EnumKey(key, i)
                    except OSError:
                        break
                    with winreg.OpenKey(key, sub) as sk:
                        values(sk, depth - 1)
        except OSError:
            pass

    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for root in roots:
            for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
                try:
                    with winreg.OpenKey(hive, root, 0, winreg.KEY_READ | view) as key:
                        values(key, 3)
                except OSError:
                    continue
    return out


def parse_java_home_listing(text: str) -> list[Path]:
    """The paths in `/usr/libexec/java_home -V` output: each JDK's line ends with its home."""
    out = []
    for line in text.splitlines():
        m = re.search(r"(/\S.*?)\s*$", line)
        if m and line.strip()[:1].isdigit():
            out.append(Path(m.group(1)))
    return out


def _mac_java_home_tool() -> list[Path]:
    tool = Path("/usr/libexec/java_home")
    if not tool.is_file():
        return []
    try:
        r = subprocess.run([str(tool), "-V"], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return []
    return parse_java_home_listing((r.stdout or "") + (r.stderr or ""))


def candidate_homes(system: str | None = None, environ: dict[str, str] | None = None, user_home: Path | None = None,
                    registry: bool = True, mac_tool: bool = True, system_folders: bool = True) -> list[Path]:
    """Every folder that might be a JDK home on this machine, most specific first (not yet checked)."""
    system = system or platform.system()
    environ = dict(os.environ if environ is None else environ)
    home = user_home or Path(environ.get("USERPROFILE") or environ.get("HOME") or Path.home())
    out: list[Path] = []

    for name, value in environ.items():
        if _ENV_NAME.match(name) and value.strip():
            out.append(Path(value.strip()))
    if system == "Windows":
        for base in _windows_bases(environ):
            for vendor in _WINDOWS_VENDORS:
                folder = base / vendor
                out.extend(_children(folder))
                out.append(folder)
        if registry:
            out.extend(_windows_registry_homes())
    elif system == "Darwin":
        out.extend(_children(home / "Library" / "Java" / "JavaVirtualMachines"))
        if system_folders:
            out.extend(_children(Path("/Library/Java/JavaVirtualMachines")))
            for brew in (Path("/opt/homebrew/opt"), Path("/usr/local/opt"), Path("/opt/homebrew/Cellar"), Path("/usr/local/Cellar")):
                for formula in _children(brew):
                    if any(k in formula.name for k in ("jdk", "temurin", "zulu", "corretto", "liberica", "semeru")):
                        out.append(formula)
                        out.extend(_children(formula))
        if mac_tool:
            out.extend(_mac_java_home_tool())
    elif system_folders:
        for parent in _LINUX_PARENTS:
            out.extend(_children(Path(parent)))
        out.extend(c for c in _children(Path("/opt")) if c.name.lower().startswith(_OPT_PREFIXES))
    for rel in _MANAGER_PARENTS:
        parent = home / rel
        for child in _children(parent):
            out.append(child)
            if rel == "scoop/apps":
                out.append(child / "current")
    return out


def discover(system: str | None = None, environ: dict[str, str] | None = None, user_home: Path | None = None,
             registry: bool = True, mac_tool: bool = True, system_folders: bool = True) -> list[Jdk]:
    """The JDKs found in the standard places, one per distinct folder, newest folder name first within a major."""
    system = system or platform.system()
    seen: set[str] = set()
    found: list[Jdk] = []
    for candidate in candidate_homes(system, environ, user_home, registry, mac_tool, system_folders):
        home = _resolve(candidate, system)
        if home is None or str(home) in seen:
            continue
        major = major_of(home, system)
        if major is None:
            continue
        seen.add(str(home))
        found.append(Jdk(str(home), major))
    return sorted(found, key=lambda j: (-j.major, "".join(reversed(j.home))))


def find(major: int, **kwargs) -> str:
    """The home of a JDK of this major version found on the machine, or ""."""
    return next((j.home for j in discover(**kwargs) if j.major == major), "")
