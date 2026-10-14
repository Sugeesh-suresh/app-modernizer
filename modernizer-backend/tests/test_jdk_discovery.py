"""JDKs already on the machine are found in the standard install folders (agents/shared/jdk_discovery.py), so a
pipeline names them instead of downloading one."""
import os
from pathlib import Path

import pytest

from agents import config
from agents.java_8_to_25 import preflight as pf25
from agents.shared import java_env, jdk_discovery


def _jdk(home: Path, version: str, windows: bool = False, javac: bool = True, release: bool = True) -> Path:
    (home / "bin").mkdir(parents=True)
    ext = ".exe" if windows else ""
    (home / "bin" / f"java{ext}").write_text("")
    if javac:
        (home / "bin" / f"javac{ext}").write_text("")
    if release:
        (home / "release").write_text(f'IMPLEMENTOR="x"\nJAVA_VERSION="{version}"\n')
    return home


def _majors(found):
    return sorted((j.major, Path(j.home).name) for j in found)


def test_windows_install_folders_are_found(tmp_path):
    pf, pfx86, local, user = tmp_path / "PF", tmp_path / "PF86", tmp_path / "Local", tmp_path / "user"
    _jdk(pf / "Java" / "jdk1.8.0_392", "1.8.0_392", windows=True)
    _jdk(pf / "Eclipse Adoptium" / "jdk-17.0.9.9-hotspot", "17.0.9", windows=True)
    _jdk(pf / "Microsoft" / "jdk-11.0.21.9-hotspot", "11.0.21", windows=True)
    _jdk(pfx86 / "Java" / "jdk-21", "21.0.1", windows=True)
    _jdk(local / "Programs" / "Eclipse Adoptium" / "jdk-25", "25", windows=True)
    _jdk(pf / "Java" / "jre1.8.0_392", "1.8.0_392", windows=True, javac=False)          # a JRE is not a JDK
    _jdk(user / ".jdks" / "corretto-19", "19.0.2", windows=True)
    _jdk(user / "scoop" / "apps" / "temurin23-jdk" / "current", "23.0.1", windows=True)
    env = {"ProgramFiles": str(pf), "ProgramFiles(x86)": str(pfx86), "LocalAppData": str(local), "USERPROFILE": str(user)}
    found = jdk_discovery.discover("Windows", env, user, registry=False)
    assert sorted(j.major for j in found) == [8, 11, 17, 19, 21, 23, 25]
    assert not any("jre1.8" in j.home for j in found)
    assert jdk_discovery.find(17, system="Windows", environ=env, user_home=user, registry=False).endswith("jdk-17.0.9.9-hotspot")


def test_mac_homes_are_found_inside_their_bundles(tmp_path):
    user = tmp_path / "user"
    base = user / "Library" / "Java" / "JavaVirtualMachines"
    _jdk(base / "temurin-17.jdk" / "Contents" / "Home", "17.0.9")
    _jdk(base / "zulu-11.jdk" / "Contents" / "Home", "11.0.21")
    found = jdk_discovery.discover("Darwin", {"HOME": str(user)}, user, mac_tool=False, system_folders=False)
    assert _majors(found) == [(11, "Home"), (17, "Home")]
    assert {Path(j.home).parent.parent.name for j in found} == {"temurin-17.jdk", "zulu-11.jdk"}


def test_what_java_home_v_lists_is_read():
    text = ('Matching Java Virtual Machines (2):\n'
            '    17.0.9 (arm64) "Eclipse Adoptium" - "OpenJDK 17.0.9" /Library/Java/JavaVirtualMachines/temurin-17.jdk/Contents/Home\n'
            '    1.8.0_392 (x86_64) "Oracle" - "Java SE 8" /Library/Java/JavaVirtualMachines/jdk1.8.0_392.jdk/Contents/Home\n'
            '/Library/Java/JavaVirtualMachines/temurin-17.jdk/Contents/Home\n')
    assert [p.parent.parent.name for p in jdk_discovery.parse_java_home_listing(text)] == ["temurin-17.jdk", "jdk1.8.0_392.jdk"]


def test_version_managers_and_environment_variables_are_found_and_links_do_not_duplicate(tmp_path):
    user = tmp_path / "user"
    real = _jdk(user / ".sdkman" / "candidates" / "java" / "17.0.9-tem", "17.0.9")
    (user / ".sdkman" / "candidates" / "java" / "current").symlink_to(real)
    _jdk(user / ".jenv" / "versions" / "11.0", "11.0.21")
    _jdk(user / ".asdf" / "installs" / "java" / "temurin-21.0.1+12", "21.0.1")
    _jdk(user / ".gradle" / "jdks" / "jdk-8", "1.8.0_402")
    elsewhere = _jdk(tmp_path / "somewhere" / "my-jdk-25", "25.0.1")
    found = jdk_discovery.discover("Linux", {"HOME": str(user), "JAVA_HOME_25_X64": str(elsewhere), "PATH": "/x"}, user,
                                  system_folders=False)
    assert sorted(j.major for j in found) == [8, 11, 17, 21, 25]
    assert len([j for j in found if j.major == 17]) == 1


def test_a_jdk_without_a_release_file_is_asked_for_its_version(tmp_path):
    home = tmp_path / "jvm" / "weird"
    _jdk(home, "", release=False)
    (home / "bin" / "java").write_text('#!/bin/sh\necho \'openjdk version "11.0.7" 2020-04-14\' >&2\n')
    (home / "bin" / "java").chmod(0o755)
    assert jdk_discovery.major_of(home, "Linux") == 11
    assert jdk_discovery.major_of(tmp_path / "nowhere", "Linux") is None


def test_the_preflight_lists_found_jdks_after_what_the_user_configured_and_before_the_downloaded(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "MIGRATION_JAVA_HOMES", "17=/opt/mine")
    monkeypatch.setattr(config, "MIGRATION_JAVA_HOME", "")
    monkeypatch.setattr(config, "BASELINE_JAVA_HOME", "")
    monkeypatch.setattr(pf25.jdk_discovery, "discover", lambda: [jdk_discovery.Jdk("/usr/lib/jvm/java-11", 11)])
    monkeypatch.setattr(pf25.toolchain, "managed_jdks", lambda: {25: "/tools/jdks/temurin-25"})
    labels = [label for label, _ in pf25.configured_homes()]
    assert labels.index("MIGRATION_JAVA_HOMES[17]") < labels.index("PATH") < labels.index("found in /usr/lib/jvm") \
        < labels.index("installed JDK 25")


def test_java11_and_the_baseline_use_a_jdk_found_on_the_machine_before_installing_one(monkeypatch):
    monkeypatch.setattr(config, "MIGRATION_JAVA_HOME", "")
    monkeypatch.setattr(config, "BASELINE_JAVA_HOME", "")
    monkeypatch.setattr(java_env.jdk_discovery, "find", lambda major, **k: {11: "/opt/jdk-11", 8: "/opt/jdk-8"}.get(major, ""))
    assert java_env.migration_home() == "/opt/jdk-11" and java_env.baseline_home() == "/opt/jdk-8"
    monkeypatch.setattr(config, "MIGRATION_JAVA_HOME", "/pinned/jdk-11")
    assert java_env.migration_home() == "/pinned/jdk-11"                  # what the user pinned always wins


def test_nothing_is_downloaded_for_a_jdk_the_scan_found(monkeypatch):
    monkeypatch.setattr(config, "AUTO_INSTALL_TOOLS", True)
    monkeypatch.setattr(pf25, "available_jdks", lambda: [{"major": 17, "home": "/usr/lib/jvm/java-17", "source": "found"}])

    def no_download(major):
        raise AssertionError("a JDK that is on the machine was downloaded")
    monkeypatch.setattr(pf25.toolchain, "install_jdk", no_download)
    pf = pf25.Preflight()
    pf25.provision_jdks([17], pf)
    assert pf.notes == []
