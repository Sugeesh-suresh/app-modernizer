"""
Installing what a migration needs and the machine lacks: a JDK for each Java release it builds on, and Maven.

Nothing here touches the system. Everything goes under TOOLS_DIR (default `~/.modernizer/tools`) as the current
user — no admin rights, no package manager, no PATH or registry change — so it behaves the same on Windows, macOS
and Linux, and removing the folder removes it all. Sources are the vendors' own:

- JDKs: Eclipse Temurin, from the Adoptium API (`/v3/assets/latest/<major>/hotspot`), which publishes the
  archive's SHA-256;
- Maven: the binary distribution on Maven Central, with its published SHA-512.

A download that does not match its checksum is deleted and never extracted; archives are unpacked with path
checks (no `..`, no absolute paths, no links out of the folder); a JDK is accepted only when it runs and reports
the major version asked for. Every install is logged to `installed.json` beside the tools, reported by the
preflight, and shown as progress while it runs (agents/shared/progress.py).

What is NOT installed: Gradle (projects bring a wrapper), Node, and Maven *plugins* — Maven fetches those itself from
the configured repository on first use; one it cannot fetch is a repository / network / credential problem, reported
as an ENVIRONMENT error, which no installation fixes.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

from .. import config
from . import progress

_WINDOWS = os.name == "nt"
_CHUNK = 1 << 20


class ToolchainError(RuntimeError):
    """A tool could not be installed; the message says why and what to do instead."""


def enabled() -> bool:
    return config.AUTO_INSTALL_TOOLS


def tools_dir() -> Path:
    base = config.TOOLS_DIR or str(Path(os.getenv("MODERNIZER_HOME") or Path.home() / ".modernizer") / "tools")
    return Path(base).expanduser()


def _java_name() -> str:
    return "java.exe" if _WINDOWS else "java"


def _mvn_name() -> str:
    return "mvn.cmd" if _WINDOWS else "mvn"


# ── what is already installed ────────────────────────────────────────────────────────────────────────

def _home_in(root: Path, max_depth: int = 4) -> str | None:
    """The JAVA_HOME inside an unpacked JDK (the folder holding bin/java; `Contents/Home` on macOS)."""
    root = Path(root)
    for dirpath, dirnames, _files in os.walk(root):
        depth = len(Path(dirpath).relative_to(root).parts)
        if (Path(dirpath) / "bin" / _java_name()).is_file():
            return dirpath
        if depth >= max_depth:
            dirnames[:] = []
    return None


def managed_jdks() -> dict[int, str]:
    """{major: JAVA_HOME} of the JDKs this tool installed."""
    out: dict[int, str] = {}
    base = tools_dir() / "jdks"
    if base.is_dir():
        for entry in sorted(base.iterdir()):
            m = re.fullmatch(r"temurin-(\d+)", entry.name)
            home = _home_in(entry) if m and entry.is_dir() else None
            if home:
                out[int(m.group(1))] = home
    return out


def managed_home(major: int) -> str:
    return managed_jdks().get(major, "")


def managed_maven() -> str:
    """The `mvn` of the Maven this tool installed, or ""."""
    base = tools_dir() / "maven"
    if base.is_dir():
        for entry in sorted(base.iterdir(), reverse=True):
            mvn = entry / "bin" / _mvn_name()
            if mvn.is_file():
                return str(mvn)
    return ""


def _prefer_file() -> Path:
    return tools_dir() / "maven" / "PREFERRED"


def prefer_managed_maven() -> None:
    """The Maven on PATH is unusable (too old): builds use the installed one."""
    _prefer_file().parent.mkdir(parents=True, exist_ok=True)
    _prefer_file().write_text("1")


def maven_preferred() -> str:
    return managed_maven() if _prefer_file().is_file() else ""


# ── downloading ──────────────────────────────────────────────────────────────────────────────────────

def _check_url(url: str) -> None:
    parts = urllib.parse.urlsplit(url)
    local = parts.hostname in ("localhost", "127.0.0.1", "::1")
    if parts.scheme != "https" and not (parts.scheme == "http" and local):
        raise ToolchainError(f"Refusing to download over {parts.scheme or 'an unknown scheme'}: {url} (https only).")


_TRANSIENT = {408, 425, 429, 500, 502, 503, 504}
_RETRIES = 4                                   # attempts; waits of 2, 5, 12 s (or the server's Retry-After, capped)


def _open(url: str, timeout: int = 60):
    _check_url(url)
    request = urllib.request.Request(url, headers={"User-Agent": "stella-modernizer-toolchain"})
    for attempt in range(1, _RETRIES + 1):
        try:
            return urllib.request.urlopen(request, timeout=timeout)   # honours HTTPS_PROXY / system certificates
        except urllib.error.HTTPError as exc:
            if exc.code not in _TRANSIENT or attempt == _RETRIES:
                return _fail(url, exc)
            wait = _wait(attempt, exc.headers.get("Retry-After") if exc.headers else None)
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            if attempt == _RETRIES:
                return _fail(url, exc)
            wait = _wait(attempt, None)
        progress.detail(f"{urllib.parse.urlsplit(url).hostname} is busy or unreachable — retrying in {wait:.0f}s "
                        f"(attempt {attempt} of {_RETRIES})")
        time.sleep(wait)


def _wait(attempt: int, retry_after: str | None) -> float:
    if retry_after and retry_after.strip().isdigit():
        return min(float(retry_after), 30.0)
    return (2.0, 5.0, 12.0)[min(attempt, 3) - 1]


def _fail(url: str, exc: Exception):
    try:
        raise exc
    except urllib.error.HTTPError as exc:
        raise ToolchainError(f"{url} answered HTTP {exc.code}"
                             + (" — the network or proxy may block this host; allow it, or install the tool yourself "
                                "and name it in MIGRATION_JAVA_HOMES." if exc.code in (401, 403, 407) else ".")) from None
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise ToolchainError(f"Could not reach {url} ({getattr(exc, 'reason', exc)}). Check the network / proxy "
                             "(HTTPS_PROXY), or install the tool yourself.") from None


def _get_json(url: str):
    with _open(url) as response:
        return json.loads(response.read().decode("utf-8"))


def _get_text(url: str) -> str:
    with _open(url) as response:
        return response.read().decode("utf-8", errors="replace")


def _download(url: str, dest: Path, algorithm: str, expected: str, label: str, size_hint: int = 0) -> None:
    """Stream `url` to `dest`, verifying the checksum; progress is reported while it runs."""
    expected = expected.strip().lower()
    digest = hashlib.new(algorithm)
    done, last = 0, 0.0
    with _open(url, timeout=120) as response, open(dest, "wb") as out:
        total = int(response.headers.get("Content-Length") or size_hint or 0)
        if total:
            free = shutil.disk_usage(dest.parent).free
            if free < total * 3:
                raise ToolchainError(f"Not enough disk space in {dest.parent} for {label}: {free // 2**20} MB free, "
                                     f"about {total * 3 // 2**20} MB needed (download + unpacked copy).")
        while True:
            chunk = response.read(_CHUNK)
            if not chunk:
                break
            out.write(chunk)
            digest.update(chunk)
            done += len(chunk)
            if time.monotonic() - last > 2:
                last = time.monotonic()
                progress.detail(f"downloading {label}: {done // 2**20} MB" + (f" of {total // 2**20} MB" if total else ""))
    if digest.hexdigest().lower() != expected:
        dest.unlink(missing_ok=True)
        raise ToolchainError(f"The {label} download does not match its published {algorithm.upper()} checksum "
                             f"(got {digest.hexdigest()[:16]}…, expected {expected[:16]}…) — discarded, nothing "
                             "was installed. A proxy rewriting the download is the usual cause.")


def _safe_target(root: Path, name: str) -> Path:
    target = (root / name).resolve()
    if not str(target).startswith(str(root.resolve()) + os.sep) and target != root.resolve():
        raise ToolchainError(f"The archive holds a path that escapes its folder ({name}) — refusing to unpack it.")
    return target


def _extract(archive: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                _safe_target(dest, info.filename)
            zf.extractall(dest)
    else:
        with tarfile.open(archive) as tf:
            for member in tf.getmembers():
                _safe_target(dest, member.name)
                if member.issym():            # relative to the link's own folder
                    _safe_target(dest, os.path.relpath((dest / member.name).parent / member.linkname, dest))
                elif member.islnk():          # relative to the archive root
                    _safe_target(dest, member.linkname)
                if member.isdev():
                    raise ToolchainError(f"The archive holds a device file ({member.name}) — refusing to unpack it.")
            tf.extractall(dest)


def _log(entry: dict) -> None:
    path = tools_dir() / "installed.json"
    try:
        items = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []
    except (OSError, ValueError):
        items = []
    items.append({**entry, "when": time.strftime("%Y-%m-%d %H:%M:%S")})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items, indent=2), encoding="utf-8")


def _publish(staging: Path, final: Path) -> None:
    """Move the unpacked tree into place; if another run got there first, keep theirs."""
    final.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(staging, final)
    except OSError:
        shutil.rmtree(staging, ignore_errors=True)
        if not final.exists():
            raise


# ── JDKs ─────────────────────────────────────────────────────────────────────────────────────────────

def _platform() -> tuple[str, str]:
    """(os, architecture) in the Adoptium API's words."""
    system = platform.system().lower()
    os_name = "windows" if system == "windows" else "mac" if system == "darwin" else "linux"
    machine = platform.machine().lower()
    arch = "aarch64" if machine in ("arm64", "aarch64") else "x64"
    return os_name, arch


def _java_reports_major(home: str, major: int) -> bool:
    try:
        r = subprocess.run([str(Path(home) / "bin" / _java_name()), "-version"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return False
    m = re.search(r'version "(?:1\.)?(\d+)', (r.stderr or "") + (r.stdout or ""))
    return bool(m) and int(m.group(1)) == major


def install_jdk(major: int) -> str:
    """Install Eclipse Temurin JDK `major` for this user; returns its JAVA_HOME. Idempotent."""
    existing = managed_home(major)
    if existing:
        return existing
    os_name, arch = _platform()
    label = f"JDK {major} (Eclipse Temurin, {os_name}/{arch})"
    progress.stage(f"Installing {label} — it is not on this machine (into {tools_dir() / 'jdks'}, this user only)")
    query = urllib.parse.urlencode({"architecture": arch, "image_type": "jdk", "os": os_name, "vendor": "eclipse"})
    assets = _get_json(f"{config.ADOPTIUM_API}/v3/assets/latest/{major}/hotspot?{query}")
    package = next(((a.get("binary") or {}).get("package") for a in assets or [] if (a.get("binary") or {}).get("package")), None)
    if not package or not package.get("link") or not package.get("checksum"):
        raise ToolchainError(f"Adoptium publishes no {label} (the API returned no downloadable package). Install a "
                             f"JDK {major} yourself and name it in MIGRATION_JAVA_HOMES (e.g. `{major}=/path/to/jdk`).")
    tools_dir().mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=f"jdk{major}-", dir=tools_dir()))
    try:
        archive = work / (package.get("name") or ("jdk.zip" if os_name == "windows" else "jdk.tar.gz"))
        _download(package["link"], archive, "sha256", package["checksum"], label, int(package.get("size") or 0))
        progress.detail(f"unpacking {label}")
        staging = work / "unpacked"
        _extract(archive, staging)
        home = _home_in(staging)
        if not home:
            raise ToolchainError(f"The {label} archive holds no bin/{_java_name()} — discarded.")
        if not _java_reports_major(home, major):
            raise ToolchainError(f"The unpacked {label} does not run as Java {major} — discarded.")
        final = tools_dir() / "jdks" / f"temurin-{major}"
        _publish(staging, final)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    home = managed_home(major)
    if not home:
        raise ToolchainError(f"{label} was unpacked but not found afterwards in {tools_dir() / 'jdks'}.")
    _log({"tool": "jdk", "major": major, "vendor": "Eclipse Temurin", "source": package["link"],
          "sha256": package["checksum"], "home": home})
    return home


# ── Maven ────────────────────────────────────────────────────────────────────────────────────────────

def install_maven(version: str = "") -> str:
    """Install Apache Maven for this user; returns the path of its `mvn`. Idempotent."""
    version = version or config.MAVEN_INSTALL_VERSION
    final = tools_dir() / "maven" / f"apache-maven-{version}"
    if (final / "bin" / _mvn_name()).is_file():
        return str(final / "bin" / _mvn_name())
    base = f"{config.MAVEN_DOWNLOAD_BASE}/{version}/apache-maven-{version}-bin.zip"
    label = f"Apache Maven {version}"
    progress.stage(f"Installing {label} — Maven is missing or too old on this machine (into {tools_dir() / 'maven'})")
    published = _get_text(base + ".sha512").split()
    expected = published[0] if published else ""
    if not expected:
        raise ToolchainError(f"{label} has no published checksum at {base}.sha512 — not installed.")
    tools_dir().mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="maven-", dir=tools_dir()))
    try:
        archive = work / f"apache-maven-{version}-bin.zip"
        _download(base, archive, "sha512", expected, label)
        staging = work / "unpacked"
        _extract(archive, staging)
        inner = next((p for p in staging.iterdir() if (p / "bin" / _mvn_name()).is_file()), None)
        if inner is None:
            raise ToolchainError(f"The {label} archive holds no bin/{_mvn_name()} — discarded.")
        if not _WINDOWS:
            for exe in (inner / "bin").iterdir():
                exe.chmod(exe.stat().st_mode | 0o111)
        _publish(inner, final)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    mvn = final / "bin" / _mvn_name()
    if not mvn.is_file():
        raise ToolchainError(f"{label} was unpacked but {mvn} is missing.")
    _log({"tool": "maven", "version": version, "source": base, "sha512": expected, "home": str(final)})
    return str(mvn)
