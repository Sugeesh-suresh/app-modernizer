"""
Is this repository a Spring Boot application on embedded Tomcat, and nothing left of the Spring Framework way?

The `java-8-to-25-boot` pipeline ends in one shape: Spring Boot 4.x, packaged as an executable JAR with the
embedded Tomcat, every Spring library brought in as its starter, configuration in `application.yml`, no XML bean
files, no web.xml, no WAR, no JSP, no `javax.*` Java EE imports. Agents are told this; `scan()` checks it, in code,
so that "converted" means the repository says so — the pipeline fails the final validation on any error finding.

Findings are coded (B001–B013, W101) so a fixer can act on one; the codes are documented for the agents in
`agents/skills/java-8-to-25-boot/references/boot-conformance-rules.md`.

A finding that is deliberate can be kept with a `boot:keep <reason>` comment on its line or just above it
(in Java), or in a comment just before its `<dependency>` (in a pom). The reason is reported, never silently dropped.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import fswalk

ERROR, WARN = "error", "warn"

TITLES = {
    "B001": "Packaged as a WAR", "B002": "Servlet-container bootstrap (web.xml / initializer)",
    "B003": "No @SpringBootApplication class", "B004": "JSP / webapp still present",
    "B005": "Spring XML bean files remain", "B006": "Spring library not brought in as a Boot starter",
    "B007": "Not a Boot build (parent/BOM, plugin)", "B008": "javax.* Java EE API left (Jakarta required)",
    "B009": "Configuration that fights Boot's auto-configuration", "B010": "Not on the embedded Tomcat",
    "B011": "No application.properties / application.yml", "B012": "Old Spring test runner",
    "B013": "Legacy logging configuration", "W101": "Hand-set version of a managed dependency",
}

# (groupId prefix, artifactId regex) -> the Boot starter that replaces it
_STARTERS: list[tuple[str, str, str]] = [
    ("org.springframework", r"spring-(webmvc|web)$", "spring-boot-starter-webmvc (Boot 4's name for the web starter; spring-boot-starter-web if the chosen release does not publish it)"),
    ("org.springframework", r"spring-webflux$", "spring-boot-starter-webflux"),
    ("org.springframework", r"spring-(jdbc|tx)$", "spring-boot-starter-jdbc"),
    ("org.springframework", r"spring-orm$", "spring-boot-starter-data-jpa"),
    ("org.springframework", r"spring-(aop|aspects)$", "spring-boot-starter-aop"),
    ("org.springframework", r"spring-jms$", "spring-boot-starter-activemq (or -artemis)"),
    ("org.springframework", r"spring-test$", "spring-boot-starter-test"),
    ("org.springframework", r"spring-context-support$", "spring-boot-starter-mail / -cache (whichever it served)"),
    ("org.springframework", r"spring-(messaging|websocket)$", "spring-boot-starter-websocket"),
    ("org.springframework", r"spring-(core|beans|context|expression|jcl)$", "nothing — every starter brings it; remove it"),
    ("org.springframework.security", r"spring-security-test$", "spring-boot-starter-security-test"),
    ("org.springframework.security", r"spring-security-.+", "spring-boot-starter-security (oauth2: -oauth2-client / -oauth2-resource-server)"),
    ("org.springframework.data", r"spring-data-jpa$", "spring-boot-starter-data-jpa"),
    ("org.springframework.data", r"spring-data-redis$", "spring-boot-starter-data-redis"),
    ("org.springframework.data", r"spring-data-mongodb$", "spring-boot-starter-data-mongodb"),
    ("org.springframework.data", r"spring-data-.+", "the matching spring-boot-starter-data-*"),
    ("org.springframework.batch", r".+", "spring-boot-starter-batch"),
    ("org.springframework.integration", r".+", "spring-boot-starter-integration"),
    ("org.springframework.amqp", r".+", "spring-boot-starter-amqp"),
    ("org.springframework.kafka", r".+", "spring-boot-starter-kafka"),
    ("org.springframework.session", r".+", "the matching spring-boot-starter-session-*"),
    ("org.springframework.ws", r".+", "spring-boot-starter-web-services"),
    ("org.springframework.retry", r".+", "no starter — drop the version, the Boot BOM manages it"),
    ("org.hibernate", r"hibernate-(core|entitymanager)$", "spring-boot-starter-data-jpa"),
    ("org.hibernate.orm", r"hibernate-core$", "spring-boot-starter-data-jpa"),
    ("org.aspectj", r"aspectjweaver$", "spring-boot-starter-aop"),
    ("org.hibernate.validator", r"hibernate-validator$", "spring-boot-starter-validation"),
]
_JSP_DEPS = re.compile(r"^(?:jstl|standard|taglibs-standard-\w+|tomcat-embed-jasper|jasper|javax\.servlet\.jsp-api|jakarta\.servlet\.jsp(?:\.jstl)?-api|jsp-api)$")
_JAVAX_DEPS = ("javax.servlet", "javax.persistence", "javax.validation", "javax.annotation", "javax.xml.bind", "javax.jms",
               "javax.mail", "javax.transaction", "javax.ws.rs", "javax.inject", "javax.ejb")
_MANAGED_GROUPS = ("org.springframework", "com.fasterxml.jackson", "org.hibernate", "org.slf4j", "ch.qos.logback", "org.junit",
                   "org.mockito", "org.apache.tomcat", "org.assertj")
_EE_IMPORT = re.compile(r"^\s*import\s+(?:static\s+)?javax\.(?:servlet|persistence|validation|jms|mail|transaction|ws\.rs|"
                        r"xml\.bind|inject|ejb|faces|json|websocket|el|enterprise|interceptor|security\.enterprise|"
                        r"annotation\.(?:PostConstruct|PreDestroy|Resource|Resources|Priority|Generated|security))\b", re.M)
_BOOT_BEAN_TYPES = ("DataSource|LocalContainerEntityManagerFactoryBean|LocalSessionFactoryBean|SessionFactory|EntityManagerFactory|"
                    "PlatformTransactionManager|DataSourceTransactionManager|JpaTransactionManager|HibernateTransactionManager|"
                    "JdbcTemplate|NamedParameterJdbcTemplate|PropertyPlaceholderConfigurer|PropertySourcesPlaceholderConfigurer|"
                    "CommonsMultipartResolver|MultipartResolver|InternalResourceViewResolver|UrlBasedViewResolver|ViewResolver")
_JAVA_RULES: list[tuple[str, str, str, str]] = [
    ("B002", r"\bextends\s+SpringBootServletInitializer\b|\bimplements\s+WebApplicationInitializer\b|"
             r"\bextends\s+Abstract(?:Annotation(?:Config)?)?(?:Context\w*|DispatcherServlet)Initializer\b",
     "a servlet-container initializer", "delete it — the embedded Tomcat is started by the @SpringBootApplication main class"),
    ("B009", r"@EnableWebMvc\b", "@EnableWebMvc switches Boot's MVC auto-configuration off",
     "remove it; keep only a WebMvcConfigurer for customisations"),
    ("B009", r"\bextends\s+WebMvcConfigurerAdapter\b", "WebMvcConfigurerAdapter was removed",
     "implement WebMvcConfigurer instead"),
    ("B009", r"\bextends\s+WebSecurityConfigurerAdapter\b", "WebSecurityConfigurerAdapter was removed in Spring Security 6",
     "declare a SecurityFilterChain bean with the lambda DSL"),
    ("B009", r"\bInternalResourceViewResolver\b|\bContextLoaderListener\b|\bnew\s+DispatcherServlet\s*\(",
     "container wiring Boot does itself", "delete it; configure views with Thymeleaf and server.* properties"),
    ("B009", r"\b(?:ClassPathXml|FileSystemXml)ApplicationContext\b|\bXmlWebApplicationContext\b|\bAnnotationConfigWebApplicationContext\b",
     "a manually created application context", "let SpringApplication create the context"),
    ("B009", r"@ImportResource\b", "@ImportResource keeps XML bean definitions alive",
     "convert the XML to @Configuration / properties and delete @ImportResource"),
]
_RETURN_BEAN = re.compile(r"@Bean\b[^{;]*?\b(?:public|protected|static|\s)+\s*(" + _BOOT_BEAN_TYPES + r")(?:<[^>]*>)?\s+\w+\s*\(")
_KEEP = re.compile(r"boot:keep(?:\s+(.*))?", re.I)


@dataclass
class Finding:
    code: str
    level: str
    path: str
    line: int
    message: str
    fix: str = ""

    def text(self) -> str:
        where = f"{self.path}:{self.line}" if self.line else self.path
        return f"{self.code} {where} — {self.message}" + (f" → {self.fix}" if self.fix else "")


@dataclass
class Conformance:
    findings: list[Finding] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)          # "path:line — reason" of every boot:keep

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.level == ERROR]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.level == WARN]

    @property
    def ok(self) -> bool:
        return not self.errors

    def add(self, code: str, level: str, path: str, line: int, message: str, fix: str = "") -> None:
        self.findings.append(Finding(code, level, path, line, message, fix))

    def error_lines(self, limit: int = 40) -> list[str]:
        return [f.text() for f in self.errors[:limit]] + ([f"… {len(self.errors) - limit} more error finding(s)"]
                                                          if len(self.errors) > limit else [])

    def markdown(self, limit_per_code: int = 12) -> str:
        head = (f"Spring Boot conformance: {len(self.errors)} error(s), {len(self.warnings)} warning(s)"
                + (" — the repository meets the end state." if self.ok and not self.warnings else "."))
        if not self.findings and not self.kept:
            return head
        out = [head, ""]
        for code in sorted({f.code for f in self.findings}):
            rows = [f for f in self.findings if f.code == code]
            out.append(f"### {code} — {TITLES[code]} ({rows[0].level}, {len(rows)})")
            out += [f"- `{f.path}{':' + str(f.line) if f.line else ''}` — {f.message}" + (f" → {f.fix}" if f.fix else "")
                    for f in rows[:limit_per_code]]
            if len(rows) > limit_per_code:
                out.append(f"- … {len(rows) - limit_per_code} more")
            out.append("")
        if self.kept:
            out += ["### Kept on purpose (`boot:keep`)"] + [f"- {k}" for k in self.kept[:20]] + [""]
        return "\n".join(out).rstrip() + "\n"


def _strip_tags_ns(xml: str) -> str:
    return re.sub(r"<!--.*?-->", lambda m: m.group(0) if "boot:keep" in m.group(0) else "", xml, flags=re.S)


def _blocks(text: str, tag: str) -> list[tuple[int, str]]:
    """(start offset, inner text) of every `<tag>…</tag>`."""
    return [(m.start(), m.group(1)) for m in re.finditer(rf"<{tag}\b[^>]*>(.*?)</{tag}>", text, re.S)]


def _tag(block: str, name: str) -> str:
    m = re.search(rf"<{name}>\s*([^<]*?)\s*</{name}>", block)
    return m.group(1).strip() if m else ""


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _kept_before(text: str, offset: int) -> str | None:
    window = text[max(0, offset - 300):offset]
    m = re.search(r"<!--\s*boot:keep\b(.*?)-->\s*$", window, re.S)
    return (m.group(1).strip() or "no reason given") if m else None


def _scan_pom(pom: Path, rel: str, out: Conformance, facts: dict) -> None:
    raw = pom.read_text(encoding="utf-8", errors="replace")
    text = _strip_tags_ns(raw)
    head = re.sub(r"<(?:dependencyManagement|build|dependencies|profiles|parent)\b.*", "", text, count=1, flags=re.S)
    packaging = _tag(head, "packaging") or "jar"
    if packaging == "war":
        out.add("B001", ERROR, rel, _line_of(raw, raw.find("<packaging>")), "`<packaging>war</packaging>`", "`jar`")
    if "maven-war-plugin" in text:
        out.add("B001", ERROR, rel, _line_of(raw, raw.find("maven-war-plugin")), "maven-war-plugin", "remove it; spring-boot-maven-plugin repackages the JAR")
    parent = re.search(r"<parent>(.*?)</parent>", text, re.S)
    if parent and _tag(parent.group(1), "artifactId") in ("spring-boot-starter-parent", "spring-boot-dependencies"):
        facts["boot_parent"] = True
    if "spring-boot-dependencies" in text and "<scope>import</scope>" in text:
        facts["boot_parent"] = True
    if "spring-boot-maven-plugin" in text:
        facts["boot_plugin"] = True
        if packaging != "pom" and "<goal>repackage</goal>" not in text and "<executions>" in text.split("spring-boot-maven-plugin", 1)[1][:900]:
            out.add("B007", ERROR, rel, _line_of(raw, raw.find("spring-boot-maven-plugin")), "spring-boot-maven-plugin without the repackage goal", "add the repackage execution (or drop <executions>: the parent binds it)")
    if packaging != "pom":
        facts["jar_modules"] = facts.get("jar_modules", 0) + 1
    deps_xml = re.sub(r"<dependencyManagement>.*?</dependencyManagement>", "", text, flags=re.S)
    for start, block in _blocks(deps_xml, "dependency"):
        group, art, scope, version = _tag(block, "groupId"), _tag(block, "artifactId"), _tag(block, "scope"), _tag(block, "version")
        line = _line_of(raw, raw.find(f"<artifactId>{art}</artifactId>")) if art else 0
        kept = _kept_before(deps_xml, start)
        if kept is not None:
            out.kept.append(f"{rel}:{line} — {group}:{art}: {kept}")
            continue
        if group == "org.springframework.boot":
            if art == "spring-boot-starter-tomcat" and scope == "provided":
                out.add("B010", ERROR, rel, line, "spring-boot-starter-tomcat in `provided` scope (an external container)", "remove the scope — the embedded Tomcat is the server")
            if art in ("spring-boot-starter-jetty", "spring-boot-starter-undertow"):
                out.add("B010", ERROR, rel, line, f"{art} replaces Tomcat", "use spring-boot-starter-web's Tomcat")
            if art in ("spring-boot-starter-web", "spring-boot-starter-webmvc") and "spring-boot-starter-tomcat" in block:
                out.add("B010", ERROR, rel, line, "spring-boot-starter-tomcat excluded from the web starter", "keep the embedded Tomcat")
            if version and not version.startswith("${"):
                out.add("W101", WARN, rel, line, f"`{art}` pinned to {version}", "drop the version: the parent/BOM manages it")
            continue
        if _JSP_DEPS.match(art):
            out.add("B004", ERROR, rel, line, f"JSP dependency `{group}:{art}`", "remove it; views are Thymeleaf")
            continue
        if group in _JAVAX_DEPS or group.startswith("javax.") and group.split(".")[1] in ("servlet", "persistence", "validation", "xml", "jms", "mail", "transaction", "ws", "inject", "ejb", "annotation"):
            out.add("B008", ERROR, rel, line, f"`{group}:{art}` is a javax Java EE API", "drop it (the starter brings the Jakarta API) or use the jakarta.* artifact")
            continue
        replaced = next((s for g, a, s in _STARTERS if group.startswith(g) and re.match(a, art)), None)
        if replaced is not None:
            out.add("B006", ERROR, rel, line, f"`{group}:{art}`" + (f" ({version})" if version else ""), replaced)
            continue
        if group.startswith("org.springframework") and not art.startswith("spring-boot"):
            out.add("B006", ERROR, rel, line, f"`{group}:{art}`", "the matching spring-boot-starter-*, or drop it if a starter brings it")
        elif (group in ("log4j", "commons-logging") or art in ("slf4j-log4j12", "log4j-slf4j-impl", "commons-logging")) and group != "org.springframework":
            out.add("B013", WARN, rel, line, f"explicit logging dependency `{group}:{art}`", "use Boot's logging (spring-boot-starter-logging)")
        elif version and not version.startswith("${") and any(group.startswith(g) for g in _MANAGED_GROUPS):
            out.add("W101", WARN, rel, line, f"`{group}:{art}` pinned to {version}", "drop the version if the Boot BOM manages it")


def _code_only(src: str) -> str:
    return re.sub(r"/\*.*?\*/|//[^\n]*", lambda m: " " * len(m.group(0)) if m.group(0).startswith("/*") else "", src, flags=re.S)


def _kept_line(lines: list[str], idx: int) -> str | None:
    for i in (idx, idx - 1):                       # the line itself, or the comment line directly above it
        if 0 <= i < len(lines):
            m = _KEEP.search(lines[i])
            if m and ("//" in lines[i] or "/*" in lines[i]):
                return (m.group(1) or "no reason given").strip().rstrip("*/").strip()
    return None


def _scan_java(path: Path, rel: str, out: Conformance, facts: dict, is_test: bool) -> None:
    src = path.read_text(encoding="utf-8", errors="replace")
    lines = src.splitlines()
    code = _code_only(src)

    def report(code_id: str, level: str, offset: int, message: str, fix: str) -> None:
        line = code.count("\n", 0, offset) + 1
        kept = _kept_line(lines, line - 1)
        if kept is not None:
            out.kept.append(f"{rel}:{line} — {kept}")
        else:
            out.add(code_id, level, rel, line, message, fix)

    if is_test:
        for m in re.finditer(r"@RunWith\s*\(\s*(?:SpringJUnit4ClassRunner|SpringRunner)\.class\s*\)|SpringJUnit4ClassRunner", code):
            report("B012", WARN, m.start(), "an old Spring test runner", "@SpringBootTest (or a slice) with JUnit 5")
            break
        return
    if "@SpringBootApplication" in code:
        facts["app_class"] = True
    imports = list(_EE_IMPORT.finditer(code))
    if imports:
        first = code[imports[0].start():code.find("\n", imports[0].start())].strip()
        report("B008", ERROR, imports[0].start(), f"{len(imports)} javax.* Java EE import(s), first `{first}`",
               "the jakarta.* equivalents (only Java SE javax.* — sql, naming, crypto, net — stays)")
    for code_id, pattern, message, fix in _JAVA_RULES:
        for m in re.finditer(pattern, code):
            report(code_id, ERROR, m.start(), message, fix)
    for m in _RETURN_BEAN.finditer(code):
        report("B009", ERROR, m.start(), f"a hand-declared `{m.group(1)}` bean that Boot auto-configures",
               "configure it with spring.* properties or a customizer; remove the bean")


def _scan_files(root: Path, out: Conformance, facts: dict) -> None:
    has_main_resources_config = False
    webapp_files: list[str] = []
    for f in fswalk.files(root):
        rel = f.relative_to(root).as_posix()
        if rel.startswith(".modernizer/"):
            continue
        name = f.name
        in_main = "/src/main/" in "/" + rel
        in_test = "/src/test/" in "/" + rel
        if name == "web.xml" and "WEB-INF" in rel:
            out.add("B002", ERROR, rel, 0, "web.xml", "delete it; servlets, filters and listeners become beans / @WebServlet registrations")
        if name.endswith((".jsp", ".jspf", ".tag", ".tagx")):
            out.add("B004", ERROR, rel, 0, "a JSP view", "convert it to a Thymeleaf template under src/main/resources/templates")
        elif "src/main/webapp/" in rel and not rel.endswith("web.xml"):
            webapp_files.append(rel)
        if name in ("application.properties", "application.yml", "application.yaml") and in_main:
            has_main_resources_config = True
        if name in ("log4j.properties", "log4j.xml", "log4j2.xml", "log4j2.properties") and in_main:
            out.add("B013", WARN, rel, 0, "a log4j configuration", "use logging.* properties / logback-spring.xml")
        if name.endswith(".xml") and (in_main or in_test) and name != "pom.xml":
            try:
                head = f.read_text(encoding="utf-8", errors="replace")[:3000]
            except OSError:
                continue
            if re.search(r"<beans[\s>]", head) or "springframework.org/schema/beans" in head:
                out.add("B005", ERROR if in_main else WARN, rel, 0, "a Spring XML bean file", "convert its beans to @Configuration / @Component / properties and delete it")
        if name.endswith(".java") and in_main:
            _scan_java(f, rel, out, facts, False)
        elif name.endswith(".java") and in_test:
            _scan_java(f, rel, out, facts, True)
        elif name in ("pom.xml",):
            _scan_pom(f, rel, out, facts)
        elif name in ("build.gradle", "build.gradle.kts"):
            text = f.read_text(encoding="utf-8", errors="replace")
            if re.search(r"id\s*\(?['\"]war['\"]|apply plugin:\s*['\"]war['\"]", text):
                out.add("B001", ERROR, rel, 0, "the Gradle `war` plugin", "remove it; use the Spring Boot plugin's bootJar")
    if webapp_files:
        out.add("B004", ERROR, "src/main/webapp", 0, f"{len(webapp_files)} file(s) under src/main/webapp (e.g. {webapp_files[0]})",
                "move static assets to src/main/resources/static and delete src/main/webapp")
    facts["has_config"] = has_main_resources_config


def scan(root: Path | str) -> Conformance:
    """Every way `root` still differs from a Spring Boot 4 / embedded Tomcat executable-JAR application."""
    root = Path(root)
    out, facts = Conformance(), {}
    _scan_files(root, out, facts)
    if facts.get("jar_modules") and not facts.get("app_class"):
        out.add("B003", ERROR, "", 0, "no class is annotated @SpringBootApplication", "add the application class with `main` (SpringApplication.run)")
    if facts.get("jar_modules"):
        if not facts.get("boot_parent"):
            out.add("B007", ERROR, "pom.xml", 0, "no spring-boot-starter-parent / spring-boot-dependencies BOM", "make the Boot parent (or BOM import) the source of every managed version")
        if not facts.get("boot_plugin"):
            out.add("B007", ERROR, "pom.xml", 0, "no spring-boot-maven-plugin", "add it so `package` produces the executable JAR")
        if not facts.get("has_config"):
            out.add("B011", ERROR, "src/main/resources", 0, "no application.properties / application.yml", "add one: server.*, spring.datasource.*, logging.* … replace what the XML and web.xml configured")
    out.findings.sort(key=lambda f: (f.level != ERROR, f.code, f.path, f.line))
    return out
