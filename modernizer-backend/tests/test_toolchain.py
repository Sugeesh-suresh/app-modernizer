"""Installing a missing JDK / Maven for the migration (agents/shared/toolchain.py), against a local stand-in of the
Adoptium API and Maven Central: download, checksum, unpacking, the layout of each platform, refusals."""
import hashlib
import http.server
import io
import json
import stat
import tarfile
import threading
import zipfile
from pathlib import Path

import pytest

from agents import config
from agents.shared import toolchain

JAVA = """#!/bin/sh
echo '    java.home = '"$(cd "$(dirname "$0")/.." && pwd)" >&2
echo 'openjdk version "{v}" 2024-01-16' >&2
"""
MVN = "#!/bin/sh\necho 'Apache Maven 3.9.11'\n"


def _tar(entries: dict[str, tuple[bytes, int]]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, (data, mode) in entries.items():
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(data), mode
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _zip(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


class Site:
    """The stand-in services; `files` maps a path to its bytes, `assets` a major to its API answer."""
    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.assets: dict[int, list] = {}
        self.hits: list[str] = []
        self.busy: dict[str, list[int]] = {}          # path -> statuses to answer before the real answer
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a): pass

            def do_GET(self):
                outer.hits.append(self.path)
                path = self.path.split("?")[0]
                if outer.busy.get(path):
                    self.send_response(outer.busy[path].pop(0))
                    self.send_header("Retry-After", "1")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                body = None
                if path.startswith("/v3/assets/latest/"):
                    body = json.dumps(outer.assets.get(int(path.split("/")[4]), [])).encode()
                elif path in outer.files:
                    body = outer.files[path]
                if body is None:
                    self.send_error(404); return
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def add_jdk(self, major: int, archive: bytes, name="jdk.tar.gz", checksum: str | None = None):
        self.files[f"/dl/{name}"] = archive
        self.assets[major] = [{"binary": {"package": {
            "link": f"{self.url}/dl/{name}", "name": name, "size": len(archive),
            "checksum": checksum or hashlib.sha256(archive).hexdigest()}}}]

    def add_maven(self, version="3.9.11", archive: bytes | None = None, checksum: str | None = None):
        archive = archive or _zip({f"apache-maven-{version}/bin/mvn": MVN.encode(),
                                   f"apache-maven-{version}/bin/mvn.cmd": b"@echo off"})
        base = f"/maven/{version}/apache-maven-{version}-bin.zip"
        self.files[base] = archive
        self.files[base + ".sha512"] = ((checksum or hashlib.sha512(archive).hexdigest()) + "  x.zip\n").encode()


@pytest.fixture
def site(tmp_path, monkeypatch):
    s = Site()
    monkeypatch.setattr(config, "ADOPTIUM_API", s.url)
    monkeypatch.setattr(config, "MAVEN_DOWNLOAD_BASE", s.url + "/maven")
    monkeypatch.setattr(config, "TOOLS_DIR", str(tmp_path / "tools"))
    monkeypatch.setattr(config, "AUTO_INSTALL_TOOLS", True)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    monkeypatch.setattr(toolchain, "_WINDOWS", False)
    monkeypatch.setattr(toolchain, "_platform", lambda: ("linux", "x64"))
    s.sleeps = []
    monkeypatch.setattr(toolchain.time, "sleep", s.sleeps.append)         # retries wait without slowing the tests
    yield s
    s.server.shutdown()


def _jdk_archive(major: int, layout="jdk-{v}+9") -> bytes:
    top = layout.format(v=f"{major}.0.9")
    return _tar({f"{top}/bin/java": (JAVA.format(v=f"{major}.0.9").encode(), 0o755), f"{top}/release": (b"x", 0o644)})


def test_a_missing_jdk_is_downloaded_verified_unpacked_and_found(site):
    site.add_jdk(17, _jdk_archive(17))
    home = toolchain.install_jdk(17)
    assert (Path(home) / "bin" / "java").is_file() and toolchain.managed_jdks() == {17: home}
    assert toolchain.managed_home(17) == home and toolchain.managed_home(8) == ""
    assert "architecture=x64" in site.hits[0] and "os=linux" in site.hits[0] and "vendor=eclipse" in site.hits[0]
    log = json.loads((toolchain.tools_dir() / "installed.json").read_text())
    assert log[0]["tool"] == "jdk" and log[0]["major"] == 17 and log[0]["sha256"]
    n = len(site.hits)
    assert toolchain.install_jdk(17) == home and len(site.hits) == n          # installed once, never again


def test_the_macos_layout_is_found_too(site):
    site.add_jdk(21, _tar({"jdk-21.0.9+9/Contents/Home/bin/java": (JAVA.format(v="21.0.9").encode(), 0o755)}))
    assert toolchain.install_jdk(21).endswith("Contents/Home")


def test_a_windows_zip_is_unpacked_with_its_exe(site, monkeypatch):
    monkeypatch.setattr(toolchain, "_WINDOWS", True)
    monkeypatch.setattr(toolchain, "_platform", lambda: ("windows", "x64"))
    exe = JAVA.format(v="17.0.9").encode()
    archive = _zip({"jdk-17.0.9+9/bin/java.exe": exe})
    site.add_jdk(17, archive, name="jdk.zip")
    monkeypatch.setattr(toolchain, "_java_reports_major", lambda home, major: True)   # an .exe cannot run on this host
    home = toolchain.install_jdk(17)
    assert (Path(home) / "bin" / "java.exe").is_file()
    assert "os=windows" in site.hits[0]


def test_a_download_that_fails_its_checksum_is_discarded_and_nothing_is_installed(site):
    site.add_jdk(17, _jdk_archive(17), checksum="0" * 64)
    with pytest.raises(toolchain.ToolchainError, match="does not match its published SHA256 checksum"):
        toolchain.install_jdk(17)
    assert toolchain.managed_jdks() == {} and not list(toolchain.tools_dir().glob("jdk17-*"))


def test_a_jdk_that_is_not_the_version_asked_for_is_refused(site):
    site.add_jdk(17, _tar({"jdk/bin/java": (JAVA.format(v="11.0.9").encode(), 0o755)}))
    with pytest.raises(toolchain.ToolchainError, match="does not run as Java 17"):
        toolchain.install_jdk(17)
    assert toolchain.managed_jdks() == {}


@pytest.mark.parametrize("bad", ["../evil", "/etc/evil", "a/../../evil"])
def test_archives_cannot_write_outside_their_folder(site, bad):
    site.add_jdk(17, _tar({bad: (b"x", 0o644), "jdk/bin/java": (JAVA.format(v="17.0.9").encode(), 0o755)}))
    with pytest.raises(toolchain.ToolchainError, match="escapes"):
        toolchain.install_jdk(17)


def test_a_symlink_out_of_the_folder_is_refused(site):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        link = tarfile.TarInfo("jdk/link"); link.type = tarfile.SYMTYPE; link.linkname = "../../../etc/passwd"
        tf.addfile(link)
    site.add_jdk(17, buf.getvalue())
    with pytest.raises(toolchain.ToolchainError, match="escapes"):
        toolchain.install_jdk(17)


def test_no_published_package_or_no_network_is_a_message_that_says_what_to_do(site, monkeypatch):
    with pytest.raises(toolchain.ToolchainError, match="MIGRATION_JAVA_HOMES"):
        toolchain.install_jdk(99)                                             # the API knows no such JDK
    monkeypatch.setattr(config, "ADOPTIUM_API", "http://127.0.0.1:9")
    with pytest.raises(toolchain.ToolchainError, match="Could not reach .* proxy"):
        toolchain.install_jdk(17)
    monkeypatch.setattr(config, "ADOPTIUM_API", "http://example.com")
    with pytest.raises(toolchain.ToolchainError, match="https only"):
        toolchain.install_jdk(17)                                             # never plain http to a real host


def test_maven_is_installed_verified_and_executable(site):
    site.add_maven()
    mvn = toolchain.install_maven()
    assert Path(mvn).is_file() and Path(mvn).stat().st_mode & stat.S_IXUSR
    assert toolchain.managed_maven() == mvn and toolchain.maven_preferred() == ""
    toolchain.prefer_managed_maven()
    assert toolchain.maven_preferred() == mvn
    assert toolchain.install_maven() == mvn


def test_maven_with_a_wrong_checksum_is_not_installed(site):
    site.add_maven(checksum="f" * 128)
    with pytest.raises(toolchain.ToolchainError, match="SHA512"):
        toolchain.install_maven()
    assert toolchain.managed_maven() == ""


def test_the_switch_and_the_default():
    assert config.AUTO_INSTALL_TOOLS is True                                # the user asked for installing by default
    assert toolchain.tools_dir().name == "tools"


# ── how the preflights use it ────────────────────────────────────────────────────────────────────────

from agents.java_8_to_11 import preflight as pf11          # noqa: E402
from agents.java_8_to_25 import preflight as pf25          # noqa: E402
from agents.shared import java_env                          # noqa: E402


def _no_install(monkeypatch):
    calls = []
    monkeypatch.setattr(toolchain, "install_jdk", lambda major: calls.append(("jdk", major)) or f"/tools/jdk{major}")
    monkeypatch.setattr(toolchain, "install_maven", lambda version="": calls.append(("maven",)) or "/tools/maven/apache-maven-3.9.11/bin/mvn")
    return calls


def test_java25_installs_exactly_the_releases_it_lacks(monkeypatch):
    calls = _no_install(monkeypatch)
    monkeypatch.setattr(pf25, "available_jdks", lambda: [{"major": 25, "home": "/x", "source": "PATH"}])
    pf = pf25.Preflight()
    pf25.provision_jdks([8, 17, 25], pf)
    assert calls == [("jdk", 8), ("jdk", 17)]                       # 25 is there; an approximate JDK 21 would not do
    assert [n for n in pf.notes if n.startswith("Installed JDK")] and "AUTO_INSTALL_TOOLS" in pf.notes[0]


def test_nothing_is_installed_when_the_switch_is_off_or_nothing_is_missing(monkeypatch):
    calls = _no_install(monkeypatch)
    monkeypatch.setattr(pf25, "available_jdks", lambda: [{"major": m, "home": "/x", "source": "PATH"} for m in (8, 17, 25)])
    pf25.provision_jdks([8, 17, 25], pf25.Preflight())
    monkeypatch.setattr(pf25, "available_jdks", lambda: [])
    monkeypatch.setattr(config, "AUTO_INSTALL_TOOLS", False)
    pf25.provision_jdks([8, 17], pf25.Preflight())
    assert pf25.provision_maven(None, Path("."), pf25.Preflight()) is None
    assert calls == []


def test_a_failed_install_is_a_note_and_the_run_carries_on_as_before(monkeypatch):
    def boom(major):
        raise toolchain.ToolchainError("the proxy blocks api.adoptium.net")
    monkeypatch.setattr(toolchain, "install_jdk", boom)
    monkeypatch.setattr(pf25, "available_jdks", lambda: [])
    pf = pf25.Preflight()
    pf25.provision_jdks([8, 17], pf)
    assert len(pf.notes) == 2 and all("could not be installed: the proxy blocks" in n for n in pf.notes)
    assert pf.ok                                                   # the existing "no JDK" stop decides, not the installer


def test_maven_is_installed_when_missing_or_too_old_but_a_project_wrapper_is_left_alone(monkeypatch, tmp_path):
    calls = _no_install(monkeypatch)
    pf = pf25.Preflight()
    assert pf25.provision_maven(None, tmp_path, pf).endswith("bin/mvn") and calls == [("maven",)]
    monkeypatch.setattr(java_env, "_run", lambda cmd, cwd, env, t: (0, "Apache Maven 3.2.5\n"))
    monkeypatch.setattr(toolchain, "prefer_managed_maven", lambda: calls.append(("prefer",)))
    assert pf25.provision_maven("/usr/bin/mvn", tmp_path, pf25.Preflight())
    assert ("prefer",) in calls                                    # builds use the new one from now on
    calls.clear()
    monkeypatch.setattr(java_env, "_run", lambda cmd, cwd, env, t: (0, "Apache Maven 3.9.9\n"))
    assert pf25.provision_maven("/usr/bin/mvn", tmp_path, pf25.Preflight()) is None
    assert pf25.provision_maven("/repo/mvnw", tmp_path, pf25.Preflight()) is None
    assert calls == []


def _tc(**kw):
    return java_env.Toolchain(**{"java_major": 17, "maven_version": "3.9.9", "problems": ["x"], **kw})


def test_java11_installs_its_jdk_unless_the_user_pinned_one(monkeypatch, tmp_path):
    calls = _no_install(monkeypatch)
    probes = []
    monkeypatch.setattr(java_env, "probe", lambda cwd, java_home=None, target=11: probes.append(1) or _tc(java_major=11, problems=[]))
    monkeypatch.setattr(config, "MIGRATION_JAVA_HOME", "")
    tc = pf11.provision(_tc(), tmp_path, pf11.Preflight())
    assert calls == [("jdk", 11)] and tc.java_major == 11 and probes == [1]          # installed, then probed again
    calls.clear(); probes.clear()
    monkeypatch.setattr(config, "MIGRATION_JAVA_HOME", "/opt/jdk17-the-user-chose")
    pf11.provision(_tc(), tmp_path, pf11.Preflight())
    assert calls == [] and probes == []                              # their choice: reported by the probe, not overridden


def test_java11_installs_maven_when_missing_and_the_baseline_jdk_when_the_code_has_tests(monkeypatch, tmp_path):
    calls = _no_install(monkeypatch)
    monkeypatch.setattr(java_env, "probe", lambda cwd, java_home=None, target=11: _tc(java_major=11, problems=[]))
    monkeypatch.setattr(config, "MIGRATION_JAVA_HOME", "")
    monkeypatch.setattr(java_env, "maven_executable", lambda cwd=None: None)
    pf11.provision(_tc(java_major=11, maven_version=""), tmp_path, pf11.Preflight())
    assert calls == [("maven",)]


def test_an_installed_jdk_and_maven_are_what_the_builds_use(site, monkeypatch, tmp_path):
    site.add_jdk(11, _jdk_archive(11))
    site.add_maven()
    monkeypatch.setattr(config, "MIGRATION_JAVA_HOME", "")
    monkeypatch.setattr(config, "BASELINE_JAVA_HOME", "")
    monkeypatch.setattr(java_env.jdk_discovery, "find", lambda major, **k: "")       # this machine's own JDKs stay out
    monkeypatch.setattr(java_env.jdk_discovery, "discover", lambda *a, **k: [])
    assert java_env.migration_home() == ""
    home = toolchain.install_jdk(11)
    assert java_env.migration_home() == home
    assert java_env.build_env()["JAVA_HOME"] == home and java_env.build_env("").get("JAVA_HOME") != home
    mvn = toolchain.install_maven()
    monkeypatch.setattr(java_env.shutil, "which", lambda name: None)
    assert java_env.maven_executable(tmp_path) == mvn              # nothing on PATH: the installed one
    monkeypatch.setattr(java_env.shutil, "which", lambda name: "/usr/bin/mvn")
    assert java_env.maven_executable(tmp_path) == "/usr/bin/mvn"
    toolchain.prefer_managed_maven()
    assert java_env.maven_executable(tmp_path) == mvn              # PATH's was too old: the installed one wins
    (tmp_path / "mvnw").write_text("#!/bin/sh\n"); (tmp_path / "mvnw").chmod(0o755)
    assert java_env.maven_executable(tmp_path).endswith("mvnw")    # the project's wrapper always wins
    assert (11, home, "installed JDK 11") in [(j["major"], j["home"], j["source"]) for j in pf25.available_jdks()] \
        or any(j["major"] == 11 and j["home"] == home for j in pf25.available_jdks())


def test_the_whole_java25_provisioning_through_the_stand_in_site(site, monkeypatch):
    for major in (8, 17):
        site.add_jdk(major, _jdk_archive(major), name=f"jdk{major}.tar.gz")
    monkeypatch.setattr(pf25, "configured_homes", lambda: [("installed JDK %d" % m, h) for m, h in toolchain.managed_jdks().items()])
    pf = pf25.Preflight()
    pf25.provision_jdks([8, 17], pf)
    majors = {j["major"] for j in pf25.available_jdks()}
    assert {8, 17} <= majors and len([n for n in pf.notes if n.startswith("Installed JDK")]) == 2


def test_a_busy_server_is_retried_but_a_refusal_is_not(site):
    site.add_maven()
    path = "/maven/3.9.11/apache-maven-3.9.11-bin.zip.sha512"
    site.busy[path] = [429, 503]                                              # rate limited twice, then fine
    toolchain.install_maven()
    assert site.hits.count(path) == 3 and len(site.sleeps) == 2 and site.sleeps[0] == 1.0   # Retry-After honoured
    site.busy["/v3/assets/latest/17/hotspot"] = [403]
    before = len(site.hits)
    with pytest.raises(toolchain.ToolchainError, match="HTTP 403"):
        toolchain.install_jdk(17)
    assert len(site.hits) == before + 1                                       # a refusal is final: asked once


def test_a_server_that_stays_busy_gives_up_with_its_status(site):
    site.busy["/v3/assets/latest/17/hotspot"] = [429] * 10
    with pytest.raises(toolchain.ToolchainError, match="HTTP 429"):
        toolchain.install_jdk(17)
    assert len(site.sleeps) == toolchain._RETRIES - 1


def test_the_tools_command_installs_and_reports(site, capsys):
    from cli import __main__ as cli_main
    site.add_jdk(17, _jdk_archive(17))
    site.add_maven()
    assert cli_main.main(["tools", "--install-jdk", "17", "--install-maven"]) == 0
    out = capsys.readouterr().out
    assert "Tools folder:" in out and "Installed JDKs:" in out and "17" in out and "Installed Maven:" in out
    assert cli_main.main(["tools", "--install-jdk", "99"]) == 1
    assert "ERROR:" in capsys.readouterr().err
