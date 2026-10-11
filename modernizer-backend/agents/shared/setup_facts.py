"""
What it takes to build, run and deploy the application — the facts the
repository states, computed without a model, for the Setup & Deployment guide.

- **Build** — every build file (Maven, Gradle, npm/yarn, pip/poetry, Go, .NET),
  its modules and packaging, the wrapper scripts, and the commands its own
  configuration defines (npm scripts, the Spring Boot plugin, …).
- **Runtimes** — the language levels the build declares (Java release, Node
  `engines` / `.nvmrc`, Python), and the base images of every Dockerfile.
- **Configuration needed at start-up** — profiles, ports, the environment
  variables and placeholders the code and configuration read that the
  repository does not set, and the configuration files themselves.
- **Services it needs** — data sources, message brokers, mail, directories and
  remote APIs, from the System Inventory.
- **Database setup** — schema/data scripts and change-script tooling.
- **Containers and deployment** — Dockerfiles, docker-compose services,
  Kubernetes/Helm/Terraform/Cloud Foundry/App Engine descriptors, application
  server descriptors, start scripts and CI/CD pipelines.

Each item names the file (and line) that states it.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .config_matrix import display as _display
from .dependency_graph import EXCLUDED_DIRS
from .system_inventory import _config_entries, _safe_url

HEADING = "## Setup & Deployment Facts (computed)"
_SKIP = re.compile(r"(?:^|/)(?:node_modules|vendor|vendors|third[-_]?party)/")
_ENV_CODE = [re.compile(r"System\s*\.\s*getenv\s*\(\s*\"([A-Za-z_][\w.]*)\""),
             re.compile(r"process\s*\.\s*env\s*\.\s*([A-Za-z_]\w*)"),
             re.compile(r"process\s*\.\s*env\s*\[\s*['\"]([A-Za-z_]\w*)['\"]"),
             re.compile(r"os\s*\.\s*(?:environ\s*(?:\.get\s*\(|\[)|getenv\s*\()\s*['\"]([A-Za-z_]\w*)['\"]"),
             re.compile(r"System\s*\.\s*getProperty\s*\(\s*\"([\w.\-]+)\""),
             re.compile(r"@Value\s*\(\s*\"\$\{([\w.\-]+)\}\"\s*\)")]
_PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][\w.\-]*)(:[^}]*)?\}")


def _files(root: Path):
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if EXCLUDED_DIRS & set(Path(rel).parts) or _SKIP.search(rel):
            continue
        yield rel, path


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace") if path.stat().st_size < 2_000_000 else ""
    except OSError:
        return ""


def _line(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def scan(workspace_dir: str) -> dict:
    root = Path(workspace_dir)
    out = {"build": [], "commands": [], "runtimes": [], "profiles": [], "ports": [], "env": [], "config_files": [],
           "db_setup": [], "containers": [], "compose": [], "deploy": [], "app_server": [], "scripts": [],
           "ci": [], "docs": []}
    if not root.is_dir():
        return out
    defined_keys: set[str] = set()
    placeholders: list[tuple[str, str, str]] = []
    env_uses: list[tuple[str, str, str]] = []
    for rel, path in _files(root):
        name = path.name
        low = name.lower()
        suffix = path.suffix.lower()
        text = ""
        if low == "pom.xml":
            text = _read(path)
            packaging = re.search(r"<packaging>\s*(\w+)\s*</packaging>", text)
            modules = re.findall(r"<module>\s*([^<\s]+)\s*</module>", text)
            release = re.search(r"<(?:maven\.compiler\.release|maven\.compiler\.source|release|java\.version|"
                                r"source)>\s*([\d.]+)\s*</", text)
            boot = "spring-boot-maven-plugin" in text
            out["build"].append({"tool": "Maven", "file": rel, "detail": "; ".join(filter(None, [
                f"packaging {packaging.group(1)}" if packaging else "packaging jar (default)",
                f"modules: {', '.join(modules)}" if modules else "",
                "Spring Boot plugin" if boot else "",
                "WAR plugin" if "maven-war-plugin" in text else ""]))})
            if release:
                out["runtimes"].append({"runtime": "Java", "version": release.group(1),
                                        "where": f"{rel}:{_line(text, release.start())}"})
            if rel.count("/") == 0 or not modules:
                wrapper = (root / rel).parent / "mvnw"
                mvn = "./mvnw" if wrapper.exists() else "mvn"
                d = rel.rsplit("/", 1)[0] if "/" in rel else "."
                out["commands"].append({"purpose": "build", "command": f"{mvn} clean package", "dir": d,
                                        "source": rel})
                if boot:
                    out["commands"].append({"purpose": "run locally", "command": f"{mvn} spring-boot:run", "dir": d,
                                            "source": rel})
        elif low in ("build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts"):
            text = _read(path)
            if low.startswith("build"):
                level = re.search(r"(?:sourceCompatibility|targetCompatibility|languageVersion\.set\(\s*"
                                  r"JavaLanguageVersion\.of\()\s*=?\s*['\"]?(?:JavaVersion\.VERSION_)?([\d._]+)", text)
                out["build"].append({"tool": "Gradle", "file": rel, "detail": "; ".join(filter(None, [
                    "war plugin" if re.search(r"['\"]war['\"]|\bwar\b", text) else "",
                    "Spring Boot plugin" if "org.springframework.boot" in text else ""]))})
                if level:
                    out["runtimes"].append({"runtime": "Java", "version": level.group(1).replace("_", "."),
                                            "where": f"{rel}:{_line(text, level.start())}"})
                gw = "./gradlew" if ((root / rel).parent / "gradlew").exists() else "gradle"
                d = rel.rsplit("/", 1)[0] if "/" in rel else "."
                out["commands"].append({"purpose": "build", "command": f"{gw} build", "dir": d, "source": rel})
                if "org.springframework.boot" in text:
                    out["commands"].append({"purpose": "run locally", "command": f"{gw} bootRun", "dir": d,
                                            "source": rel})
        elif low == "package.json":
            text = _read(path)
            try:
                pkg = json.loads(text)
            except json.JSONDecodeError:
                pkg = {}
            d = rel.rsplit("/", 1)[0] if "/" in rel else "."
            manager = "yarn" if (path.parent / "yarn.lock").exists() else \
                "pnpm" if (path.parent / "pnpm-lock.yaml").exists() else "npm"
            out["build"].append({"tool": f"Node.js ({manager})", "file": rel,
                                 "detail": f"package `{pkg.get('name', '')}`"})
            out["commands"].append({"purpose": "install dependencies",
                                    "command": f"{manager} install" if manager != "npm" else
                                    ("npm ci" if (path.parent / "package-lock.json").exists() else "npm install"),
                                    "dir": d, "source": rel})
            for script, cmd in (pkg.get("scripts") or {}).items():
                out["commands"].append({"purpose": f"script `{script}`",
                                        "command": f"{manager} run {script}  # {cmd}", "dir": d, "source": rel})
            if (pkg.get("engines") or {}).get("node"):
                out["runtimes"].append({"runtime": "Node.js", "version": pkg["engines"]["node"], "where": rel})
        elif low in (".nvmrc", ".node-version", ".python-version", ".java-version", ".tool-versions",
                     ".sdkmanrc", "runtime.txt"):
            out["runtimes"].append({"runtime": {".nvmrc": "Node.js", ".node-version": "Node.js",
                                                ".python-version": "Python", ".java-version": "Java"}.get(low, low),
                                    "version": _read(path).strip().splitlines()[0] if _read(path).strip() else "",
                                    "where": rel})
        elif low in ("requirements.txt", "pyproject.toml", "pipfile", "setup.py", "go.mod") or suffix == ".csproj":
            text = _read(path)
            tool = {"requirements.txt": "pip", "pyproject.toml": "Python (pyproject)", "pipfile": "pipenv",
                    "setup.py": "setuptools", "go.mod": "Go modules"}.get(low, ".NET")
            out["build"].append({"tool": tool, "file": rel, "detail": ""})
            m = re.search(r"requires-python\s*=\s*\"([^\"]+)\"|^go\s+([\d.]+)|<TargetFramework>([^<]+)<", text, re.M)
            if m:
                out["runtimes"].append({"runtime": {"go.mod": "Go"}.get(low, ".NET" if suffix == ".csproj" else
                                                                       "Python"),
                                        "version": next(g for g in m.groups() if g), "where": rel})
        if low == "dockerfile" or low.startswith("dockerfile.") or low.endswith(".dockerfile"):
            text = text or _read(path)
            items = [f"{m.group(1).upper()} {m.group(2).strip()}" for m in
                     re.finditer(r"^\s*(FROM|EXPOSE|ENTRYPOINT|CMD|ENV|ARG|WORKDIR|HEALTHCHECK)\s+(.+)$", text,
                                 re.M | re.I)]
            out["containers"].append({"file": rel, "detail": "; ".join(_safe_url(i) for i in items)[:1200]})
            for m in re.finditer(r"^\s*EXPOSE\s+(.+)$", text, re.M | re.I):
                out["ports"].append({"port": m.group(1).strip(), "where": f"{rel}:{_line(text, m.start())}"})
        elif re.match(r"(?:docker-)?compose[\w.-]*\.ya?ml$", low):
            text = _read(path)
            try:
                import yaml
                data = yaml.safe_load(text) or {}
            except Exception:
                data = {}
            for svc, spec in ((data.get("services") or {}) if isinstance(data, dict) else {}).items():
                if isinstance(spec, dict):
                    env = spec.get("environment") or {}
                    env_keys = list(env) if isinstance(env, dict) else [str(e).split("=")[0] for e in env]
                    out["compose"].append({"file": rel, "service": svc,
                                           "image": spec.get("image") or ("build: " + str(spec.get("build"))),
                                           "ports": ", ".join(map(str, spec.get("ports") or [])),
                                           "depends_on": ", ".join(spec.get("depends_on") or [])
                                           if isinstance(spec.get("depends_on"), list) else
                                           ", ".join(spec.get("depends_on") or {}),
                                           "environment": ", ".join(env_keys)})
        elif low in ("jenkinsfile",) or rel.startswith(".github/workflows/") or low in (
                ".gitlab-ci.yml", "azure-pipelines.yml", "bitbucket-pipelines.yml", "cloudbuild.yaml",
                "cloudbuild.yml", ".travis.yml", "buildspec.yml") or rel.startswith(".circleci/"):
            text = _read(path)
            stages = re.findall(r"stage\s*\(\s*['\"]([^'\"]+)['\"]", text) or \
                re.findall(r"^\s{2}([\w-]+):\s*$", text, re.M) or re.findall(r"-\s*name:\s*(.+)$", text, re.M)
            out["ci"].append({"file": rel, "detail": "; ".join(dict.fromkeys(s.strip() for s in stages))[:600]})
        elif suffix in (".yaml", ".yml") and re.search(r"^\s*kind:\s*(Deployment|StatefulSet|Service|Ingress|"
                                                       r"ConfigMap|Secret|CronJob|Job|DaemonSet|Route)\b",
                                                       text := _read(path), re.M) and "apiVersion" in text:
            kinds = re.findall(r"^\s*kind:\s*(\w+)", text, re.M)
            images = re.findall(r"^\s*image:\s*(\S+)", text, re.M)
            out["deploy"].append({"kind": "Kubernetes", "file": rel,
                                  "detail": f"{', '.join(kinds)}" + (f"; images: {', '.join(images)}" if images else "")})
        elif low in ("chart.yaml",):
            out["deploy"].append({"kind": "Helm chart", "file": rel, "detail": ""})
        elif suffix == ".tf":
            res = re.findall(r"^\s*resource\s+\"([\w-]+)\"\s+\"([\w-]+)\"", _read(path), re.M)
            out["deploy"].append({"kind": "Terraform", "file": rel,
                                  "detail": ", ".join(f"{a}.{b}" for a, b in res)[:600]})
        elif low in ("app.yaml", "manifest.yml", "manifest.yaml", "procfile", "serverless.yml", "appspec.yml",
                     "skaffold.yaml", "fly.toml", "vercel.json", "netlify.toml"):
            out["deploy"].append({"kind": {"app.yaml": "Google App Engine", "procfile": "Procfile (Heroku-style)",
                                           "serverless.yml": "Serverless Framework", "appspec.yml": "AWS CodeDeploy"}
                                  .get(low, "Cloud Foundry" if low.startswith("manifest") else low),
                                  "file": rel, "detail": _read(path).strip().replace("\n", "; ")[:300]})
        if low in ("web.xml", "jboss-web.xml", "jboss-deployment-structure.xml", "context.xml", "server.xml",
                   "weblogic.xml", "ibm-web-bnd.xml", "standalone.xml", "standalone-full.xml") or \
                low.endswith("-ds.xml") or low.endswith(".cli"):
            out["app_server"].append({"file": rel})
        if suffix in (".sh", ".bat", ".cmd", ".ps1") and (rel.count("/") <= 1 or re.search(r"(?:^|/)(?:bin|scripts?|"
                                                                                           r"deploy)/", rel)):
            out["scripts"].append({"file": rel, "detail": next((l.strip() for l in _read(path).splitlines()
                                                                if l.strip() and not l.startswith(("#", "@echo",
                                                                                                   "REM", "rem"))),
                                                               "")[:160]})
        if re.match(r"(?:readme|install|setup|contributing|deploy(?:ment)?|running)[\w.-]*\.(?:md|txt|adoc|rst)$",
                    low):
            out["docs"].append({"file": rel})
        if (suffix in (".sql",) and re.search(r"(?:^|/)(?:schema|data|init|import|seed)[\w-]*\.sql$", low)) or \
                re.search(r"(?:^|/)(?:db/migration|db/changelog|flyway|liquibase)/", rel):
            out["db_setup"].append({"file": rel})
        if suffix in (".properties", ".yml", ".yaml") and re.match(
                r"(?:application|bootstrap)(?:-([\w-]+))?\.(?:properties|ya?ml)$", low):
            text = text or _read(path)
            m = re.match(r"(?:application|bootstrap)-([\w-]+)\.", low)
            if m:
                out["profiles"].append({"profile": m.group(1), "file": rel})
            out["config_files"].append({"file": rel})
            for key, value, n in _config_entries(rel, text):
                defined_keys.add(key)
                if key in ("server.port", "management.server.port", "server.http.port"):
                    out["ports"].append({"port": f"{value} ({key})", "where": f"{rel}:{n}"})
                if key in ("spring.profiles.active", "spring.profiles.include", "spring.config.import"):
                    out["profiles"].append({"profile": f"{key} = {value}", "file": f"{rel}:{n}"})
                for m2 in _PLACEHOLDER.finditer(value):
                    placeholders.append((m2.group(1), m2.group(2) or "", f"{rel}:{n}"))
        elif suffix in (".properties", ".env", ".conf", ".cfg", ".ini") and not _SKIP.search(rel):
            text = text or _read(path)
            if suffix == ".env" or low.endswith(".env.example") or low == ".env.example":
                for key, _, n in _config_entries(rel, text):
                    env_uses.append((key, "declared in an env file", f"{rel}:{n}"))
            else:
                for key, value, n in _config_entries(rel, text):
                    defined_keys.add(key)
                    for m2 in _PLACEHOLDER.finditer(value):
                        placeholders.append((m2.group(1), m2.group(2) or "", f"{rel}:{n}"))
        if suffix in (".java", ".kt", ".groovy", ".js", ".ts", ".mjs", ".cjs", ".py", ".jsx", ".tsx") \
                and not re.search(r"(?:^|/)(?:src/test|test|tests|__tests__)/", rel):
            text = text or _read(path)
            for pattern in _ENV_CODE:
                for m in pattern.finditer(text):
                    kind = "Java system property" if "getProperty" in pattern.pattern else \
                        "@Value placeholder" if "@Value" in pattern.pattern else "environment variable"
                    env_uses.append((m.group(1), kind, f"{rel}:{_line(text, m.start())}"))
    seen = set()
    for key, default, where in placeholders:
        if key in defined_keys or (key, where) in seen:
            continue
        seen.add((key, where))
        out["env"].append({"name": key, "kind": "configuration placeholder" + (
            f" (default `{_display(key, default[1:])}`)" if default else " — no default, must be supplied"),
                           "where": where})
    for key, kind, where in env_uses:
        if kind == "@Value placeholder" and key in defined_keys:
            continue
        if (key, where) not in seen:
            seen.add((key, where))
            out["env"].append({"name": key, "kind": kind, "where": where})
    return out


def _table(headers: list[str], rows: list[list], empty: str = "None found in the repository.") -> list[str]:
    if not rows:
        return [f"_{empty}_", ""]
    cell = lambda v: str(v).replace("|", "\\|").replace("\n", " ") if v not in (None, "") else "—"  # noqa: E731
    return ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)] + \
        ["| " + " | ".join(cell(c) for c in r) + " |" for r in rows] + [""]


def to_markdown(facts: dict) -> str:
    f = facts
    lines = [HEADING, "",
             "_Computed by the pipeline from the repository's build, configuration, container, deployment and "
             "pipeline files (no model). Each row names the file that states it; values are as written, credentials "
             "never shown._", ""]
    sections = [
        ("Build files", ["Tool", "File", "Detail"], [[b["tool"], f"`{b['file']}`", b["detail"]] for b in f["build"]]),
        ("Build and run commands defined by the repository", ["Purpose", "Command", "Run in", "From"],
         [[c["purpose"], f"`{c['command']}`", f"`{c['dir']}`", f"`{c['source']}`"] for c in f["commands"]]),
        ("Runtime versions declared", ["Runtime", "Version", "Where"],
         [[r["runtime"], f"`{r['version']}`", f"`{r['where']}`"] for r in f["runtimes"]]),
        ("Configuration files and profiles", ["Profile / setting", "File"],
         [[p["profile"], f"`{p['file']}`"] for p in f["profiles"]]
         + [["(configuration file)", f"`{c['file']}`"] for c in f["config_files"]]),
        ("Ports", ["Port", "Where"], [[p["port"], f"`{p['where']}`"] for p in f["ports"]]),
        ("Environment variables, system properties and unresolved placeholders", ["Name", "Kind", "Where"],
         [[f"`{e['name']}`", e["kind"], f"`{e['where']}`"] for e in f["env"]]),
        ("Database setup scripts", ["File"], [[f"`{d['file']}`"] for d in f["db_setup"]]),
        ("Dockerfiles", ["File", "Instructions"], [[f"`{c['file']}`", f"`{c['detail']}`"] for c in f["containers"]]),
        ("docker-compose services", ["File", "Service", "Image / build", "Ports", "Depends on", "Environment keys"],
         [[f"`{c['file']}`", c["service"], f"`{c['image']}`", c["ports"], c["depends_on"], c["environment"]]
          for c in f["compose"]]),
        ("Deployment descriptors", ["Kind", "File", "Detail"],
         [[d["kind"], f"`{d['file']}`", d["detail"]] for d in f["deploy"]]),
        ("Application server descriptors", ["File"], [[f"`{a['file']}`"] for a in f["app_server"]]),
        ("Start and deployment scripts", ["File", "First command"],
         [[f"`{s['file']}`", f"`{s['detail']}`" if s["detail"] else ""] for s in f["scripts"]]),
        ("CI/CD pipelines", ["File", "Stages / jobs"], [[f"`{c['file']}`", c["detail"]] for c in f["ci"]]),
        ("Existing setup documentation", ["File"], [[f"`{d['file']}`"] for d in f["docs"]]),
    ]
    for title, headers, rows in sections:
        lines += [f"### {title}", ""] + _table(headers, rows)
    return "\n".join(lines).rstrip() + "\n"
