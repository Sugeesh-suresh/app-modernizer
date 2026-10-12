"""
What a long deterministic step is doing right now, for whoever is waiting on it.

The Gemini CLI path runs every deterministic step (the Java preflight's Maven
builds, the migration inventory, discovery's computed sections) inside one
`next_step` call. Without this, the person sees only "Thinking…" for as long as
a first Maven build downloads its dependencies. The MCP server
(cli/mcp_server.py) runs `next_step` in a background worker with a Tracker
active and, while it runs, answers with `Tracker.report()`; the command-line
CLI echoes each stage to stderr instead.

Code that does slow work only calls the module functions: `stage("Baseline
build of `rest` (2 of 3) on JDK 8")` when it starts something new, `detail(...)`
for progress inside a stage, and `wants_output()` / `output(line)` to stream a
command's output (agents/shared/java_env.py does that for Maven). With no
tracker active — the web pipeline, the tests — they do nothing.
"""
from __future__ import annotations

import re
import sys
import threading
import time
from dataclasses import dataclass, field

_HISTORY = 12

_MODULE = re.compile(r"^\[INFO\] Building (.+?)(?:\s+\[(\d+)/(\d+)\])?\s*$")
_GOAL = re.compile(r"^\[INFO\] --- (\S+) .*?---\s*$|^\[INFO\] --- ([\w.:-]+)")
_DOWNLOAD = re.compile(r"^(?:\[INFO\] )?Downloaded from \S+: (\S+)")
_ERROR = re.compile(r"^\[ERROR\]")
# JVM banners (JAVA_TOOL_OPTIONS carries proxy settings, sometimes a password) are never shown.
_SKIP = re.compile(r"^(?:Picked up (?:JAVA_TOOL_OPTIONS|_JAVA_OPTIONS|JDK_JAVA_OPTIONS))")
# Credentials never reach a report: user:password@ in URLs, and -D...password=... style settings.
_SECRETS = (
    (re.compile(r"(://)[^/@\s:]+:[^/@\s]+@"), r"\1***@"),
    (re.compile(r"(?i)((?:password|passwd|pwd|secret|token|api[-_]?key)\w*\s*[=:]\s*)\S+"), r"\1***"),
)


def _redact(line: str) -> str:
    for pattern, repl in _SECRETS:
        line = pattern.sub(repl, line)
    return line


def _clock(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 60}m{seconds % 60:02d}s" if seconds >= 60 else f"{seconds}s"


@dataclass
class _Command:
    """What the output of the running command (a Maven build) says so far."""
    started: float
    lines: int = 0
    module: str = ""
    goal: str = ""
    downloads: int = 0
    last_download: str = ""
    errors: int = 0
    last_line: str = ""


@dataclass
class Tracker:
    title: str = ""
    echo: bool = False                         # the command-line CLI: print each stage to stderr
    started: float = field(default_factory=time.monotonic)
    current: str = ""
    current_since: float = 0.0
    note: str = ""
    history: list[tuple[str, float]] = field(default_factory=list)   # finished stages and their duration
    command: _Command | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    # ── updates ────────────────────────────────────────────────────────────
    def stage(self, text: str) -> None:
        now = time.monotonic()
        with self._lock:
            if self.current and now - self.current_since >= 1:      # instant stages are not news
                self.history.append((self.current, now - self.current_since))
                del self.history[:-_HISTORY]
            self.current, self.current_since, self.note, self.command = text, now, "", None
        if self.echo:
            print(f"[modernizer] {text}", file=sys.stderr, flush=True)

    def detail(self, text: str) -> None:
        with self._lock:
            self.note = text

    def output(self, line: str) -> None:
        line = _redact(line.rstrip())
        if not line or _SKIP.match(line):
            return
        with self._lock:
            cmd = self.command
            if cmd is None:
                cmd = self.command = _Command(time.monotonic())
            cmd.lines += 1
            cmd.last_line = line[:200]
            if m := _MODULE.match(line):
                cmd.module = m.group(1).strip() + (f" [{m.group(2)}/{m.group(3)}]" if m.group(2) else "")
            elif m := _GOAL.match(line):
                cmd.goal = (m.group(1) or m.group(2) or "").split("@")[0]
            elif m := _DOWNLOAD.match(line):
                cmd.downloads += 1
                cmd.last_download = m.group(1).rsplit("/", 1)[-1]
            elif _ERROR.match(line):
                cmd.errors += 1

    # ── reading ────────────────────────────────────────────────────────────
    def report(self) -> str:
        """Markdown: the stage running now, what its command reports, and what already finished."""
        now = time.monotonic()
        with self._lock:
            lines = [f"**{self.title or 'Working'}** — running for {_clock(now - self.started)} (no model involved)."]
            if self.current:
                lines += ["", f"- **Now:** {self.current} — {_clock(now - self.current_since)}"]
                if self.note:
                    lines.append(f"  - {self.note}")
                cmd = self.command
                if cmd:
                    facts = []
                    if cmd.module:
                        facts.append(f"building `{cmd.module}`")
                    if cmd.goal:
                        facts.append(f"step `{cmd.goal}`")
                    if cmd.downloads:
                        facts.append(f"{cmd.downloads} artifact(s) downloaded"
                                     + (f", last `{cmd.last_download}`" if cmd.last_download else ""))
                    if cmd.errors:
                        facts.append(f"{cmd.errors} `[ERROR]` line(s) so far")
                    if facts:
                        lines.append("  - Maven: " + "; ".join(facts))
                    lines.append(f"  - Last output ({_clock(now - cmd.started)} in, {cmd.lines} lines): "
                                 f"`{cmd.last_line.replace('`', chr(39))}`")
            if self.history:
                lines += ["", "Finished so far:"]
                lines += [f"- {text} ({_clock(took)})" for text, took in self.history]
            return "\n".join(lines)


_active: Tracker | None = None
_active_lock = threading.Lock()


def activate(tracker: Tracker | None) -> Tracker | None:
    """Make `tracker` the one updates go to (None: none); returns the previous one. One run at a time
    per process — the MCP server serialises next_step — so a process-wide tracker is enough, and it
    also receives updates from helper threads (parallel Maven downloads)."""
    global _active
    with _active_lock:
        previous, _active = _active, tracker
    return previous


def active() -> Tracker | None:
    return _active


def stage(text: str) -> None:
    if (t := _active) is not None:
        t.stage(text)


def detail(text: str) -> None:
    if (t := _active) is not None:
        t.detail(text)


def wants_output() -> bool:
    return _active is not None


def output(line: str) -> None:
    if (t := _active) is not None:
        t.output(line)
