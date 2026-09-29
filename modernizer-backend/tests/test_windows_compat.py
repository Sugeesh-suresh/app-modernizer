"""
The backend on Windows.

These run on any OS by simulating the Windows side: `callbacks.py` is loaded
the way Windows sees it (no `fcntl`, an `msvcrt`), and the command helpers are
exercised with their Windows switch on. The guards they pin are the three
things that broke there -- the backend would not start (`import fcntl`),
builds reported "not installed" (`mvn` is really `mvn.cmd`), and relative
paths came back with backslashes that nothing downstream matches.
"""
import importlib.util
import os
import pathlib
import re
import sys
import types

import pytest

from agents.shared import workspace_tools as wt

BACKEND = pathlib.Path(__file__).parent.parent
CALLBACKS = BACKEND / "agents" / "shared" / "callbacks.py"


class _FakeMsvcrt(types.ModuleType):
    LK_LOCK, LK_UNLCK = 1, 0

    def __init__(self, fail: bool = False):
        super().__init__("msvcrt")
        self.calls: list[int] = []
        self.fail = fail

    def locking(self, fd, mode, nbytes):
        if self.fail and mode == self.LK_LOCK:
            raise OSError("lock timed out")
        self.calls.append(mode)


def _load_callbacks_as_windows(monkeypatch, msvcrt: _FakeMsvcrt):
    monkeypatch.setitem(sys.modules, "msvcrt", msvcrt)
    monkeypatch.setitem(sys.modules, "fcntl", None)  # `import fcntl` raises, as on Windows
    spec = importlib.util.spec_from_file_location("callbacks_as_windows", CALLBACKS)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setattr(os, "name", "nt")
    try:
        spec.loader.exec_module(module)
    finally:
        monkeypatch.setattr(os, "name", "posix")
    return module


class TestSkillFileLock:
    def test_callbacks_imports_without_fcntl_and_locks_with_msvcrt(self, monkeypatch, tmp_path):
        msvcrt = _FakeMsvcrt()
        callbacks = _load_callbacks_as_windows(monkeypatch, msvcrt)
        target = tmp_path / "SKILL.md"

        with callbacks._locked(target):
            target.write_text("written under the lock")

        assert msvcrt.calls == [msvcrt.LK_LOCK, msvcrt.LK_UNLCK]
        assert target.read_text() == "written under the lock"

    def test_a_lock_that_cannot_be_taken_does_not_stop_the_write(self, monkeypatch, tmp_path):
        msvcrt = _FakeMsvcrt(fail=True)
        callbacks = _load_callbacks_as_windows(monkeypatch, msvcrt)
        target = tmp_path / "SKILL.md"

        with callbacks._locked(target):
            target.write_text("still written")

        assert msvcrt.calls == []  # nothing to unlock
        assert target.read_text() == "still written"

    def test_an_error_inside_the_locked_block_propagates_as_itself(self, tmp_path):
        # The old version caught OSError around its `yield` and yielded again,
        # turning the caller's own error into "generator didn't stop".
        from agents.shared import callbacks

        with pytest.raises(OSError, match="disk full"):
            with callbacks._locked(tmp_path / "SKILL.md"):
                raise OSError("disk full")


@pytest.fixture
def windows(monkeypatch):
    monkeypatch.setattr(wt, "_WINDOWS", True)


class TestCommandsOnWindows:
    def test_backslash_paths_and_quotes_survive_splitting(self, windows):
        assert wt._split_command(r'mvn -f C:\repo\pom.xml "-Dname=a b" -q') == [
            "mvn", "-f", r"C:\repo\pom.xml", "-Dname=a b", "-q",
        ]

    @pytest.mark.parametrize("arg0, name", [
        ("mvn.cmd", "mvn"), (r".\mvnw.cmd", "mvnw"), ("./gradlew.bat", "gradlew"),
        ("npm.cmd", "npm"), ("java.exe", "java"), ("mvn", "mvn"),
    ])
    def test_launcher_suffixes_are_checked_against_the_allow_list_by_bare_name(self, arg0, name):
        assert wt._command_name(arg0) == name

    def test_the_repository_wrapper_resolves_to_its_windows_twin(self, windows, tmp_path):
        (tmp_path / "mvnw").write_text("#!/bin/sh")
        (tmp_path / "mvnw.cmd").write_text("@echo off")
        (tmp_path / "gradlew.bat").write_text("@echo off")
        assert wt._resolve_executable("./mvnw", tmp_path) == str(tmp_path / "mvnw.cmd")
        assert wt._resolve_executable("mvnw", tmp_path) == str(tmp_path / "mvnw.cmd")
        assert wt._resolve_executable(r".\gradlew", tmp_path) == str(tmp_path / "gradlew.bat")

    def test_path_tools_are_found_through_pathext(self, windows, monkeypatch, tmp_path):
        monkeypatch.setattr(wt.shutil, "which", lambda name: rf"C:\maven\bin\{name}.cmd")
        assert wt._resolve_executable("mvn", tmp_path) == r"C:\maven\bin\mvn.cmd"

    def test_run_command_launches_the_resolved_program(self, windows, monkeypatch, tmp_path):
        monkeypatch.setattr(wt.shutil, "which", lambda name: rf"C:\maven\bin\{name}.cmd")
        seen: list[list[str]] = []

        def fake_run(argv, **kwargs):
            seen.append(argv)
            return types.SimpleNamespace(returncode=0, stdout="BUILD SUCCESS", stderr="")

        monkeypatch.setattr(wt.subprocess, "run", fake_run)
        run = wt.make_run_command({"mvn"})
        ctx = types.SimpleNamespace(state={"workspace_dir": str(tmp_path)})

        assert run(ctx, "mvn -q -DskipTests package").startswith("exit_code=0")
        assert seen == [[r"C:\maven\bin\mvn.cmd", "-q", "-DskipTests", "package"]]
        assert "not permitted" in run(ctx, "cmd.exe /c del *")

    def test_nothing_changes_off_windows(self, tmp_path):
        assert wt._WINDOWS is (os.name == "nt")
        if not wt._WINDOWS:
            assert wt._resolve_executable("./mvnw", tmp_path) == "./mvnw"
            assert wt._split_command(r"echo a\ b") == ["echo", "a b"]


def test_workspace_relative_paths_are_never_built_with_str():
    """`str(path.relative_to(root))` gives `src\\main\\...` on Windows, which the
    plan manifest, the diff, the frozen-file rules and every `backend/`-style
    prefix check fail to match. `.as_posix()` is the same on Linux/macOS."""
    offenders = []
    for path in [BACKEND / "main.py", *(BACKEND / "agents").rglob("*.py")]:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"str\([^()]*\.relative_to\(", line) or re.search(r"\bstr\(rel\)", line):
                offenders.append(f"{path.relative_to(BACKEND).as_posix()}:{number}: {line.strip()}")
    assert not offenders, "\n".join(offenders)
