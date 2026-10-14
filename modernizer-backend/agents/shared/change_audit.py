"""
Deterministic (non-LLM) audit of what a migration run actually changed, run
as the first step of the independent code review.

The build loop proves the code compiles and the reviewer reads the files, but
neither answers the two questions a human reviewer asks first:

  1. Did anything really change, and is every change explained by the
     migration? A file that was rewritten without any legacy marker
     disappearing or any modern one appearing is scope creep (or a
     gratuitous reformat) until someone justifies it — and a *legacy*
     marker that appears in an added line is an outright regression
     (re-adding Jackson 2 on a Boot 4 target, silencing a JDK 17
     `InaccessibleObjectException` with `--add-opens`).

  2. Are the untouched files really irrelevant? An unchanged file that
     still matches a legacy marker is a coverage gap candidate: either the
     modifier missed it, or it belongs to a stage/toggle that was out of
     scope. Only the plan can say which, so this module reports the
     evidence and the reviewer adjudicates.

Philosophy is `companion_detector.py`'s: cheap regex static analysis over
real files, with the matched line quoted as evidence so the finding is
auditable rather than an opaque AI guess. The markers are deliberately
recall-biased — a false positive costs the reviewer one sentence of
adjudication, a false negative hides a missed file.

`audit_migration_changes` is the ADK tool wrapper; every pattern's code
reviewer gets it automatically via `make_code_reviewer_agent`.
"""
from . import fswalk
import difflib
import functools
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypedDict

from .adk_compat import ToolContext

from . import scope_fence
from .dependency_graph import EXCLUDED_DIRS

# File types worth grepping for library/API signatures — sources, build files
# and config, across every pattern this app supports.
_SCAN_SUFFIXES = {
    ".java", ".xml", ".properties", ".yml", ".yaml", ".gradle", ".kts",
    ".jsp", ".jspf", ".tag", ".tld", ".sql", ".pks", ".pkb", ".plsql",
    ".js", ".jsx", ".ts", ".tsx", ".json", ".conf", ".cfg",
    # Templates and views. A JSP scriptlet or taglib surviving into a Thymeleaf
    # or React template is precisely the defect worth catching, and these were
    # invisible to the scan.
    ".html", ".htm", ".vue", ".svelte",
}

# Evidence caps — a review prompt has a budget, and 200 residual-legacy files
# all saying the same thing helps nobody.
_MAX_FILES_PER_BUCKET = 40
_MAX_HITS_PER_FILE = 4
_MAX_LINE_CHARS = 200


@dataclass(frozen=True)
class Marker:
    """One regex signature, with the note the reviewer needs to adjudicate it. `requires`, when set,
    must also match somewhere in the file: a line that only means something in a context (HQL `?`
    parameters, which are JDBC's own syntax outside Hibernate) is not judged without it."""
    name: str
    pattern: re.Pattern
    note: str = ""
    requires: re.Pattern | None = None

    def applies_to(self, text: str | None) -> bool:
        """Whether the marker applies to a file with this text (None: the file is not known — it applies)."""
        return self.requires is None or text is None or bool(self.requires.search(text))


def _m(name: str, regex: str, note: str = "", flags: int = 0, requires: str = "") -> Marker:
    return Marker(name, re.compile(regex, flags), note, re.compile(requires) if requires else None)


SQL_SUFFIXES = frozenset({".sql", ".pks", ".pkb", ".ddl", ".plsql", ".prc", ".fnc", ".trg"})


def sql_code(text: str) -> str:
    """`text` with SQL comments (`--`, `/* */`, SQL*Plus `REM`) blanked out, line breaks kept: keyword
    checks then see only code, so a migration script's comment ("NOTES LONG -> CLOB") is never read as a
    LONG column. String literals are kept — `EXECUTE IMMEDIATE '...'` is code — but a `--` inside one
    does not start a comment."""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if text.startswith("--", i) or (c in "Rr" and (i == 0 or text[i - 1] == "\n")
                                         and re.match(r"rem(?:ark)?\b", text[i:i + 6], re.IGNORECASE)):
            j = text.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append(re.sub(r"[^\n]", " ", text[i:j]))
            i = j
        elif c == "'":
            j = i + 1
            while j < n and not (text[j] == "'" and not text.startswith("''", j)):
                j += 2 if text.startswith("''", j) else 1
            j = min(j + 1, n)
            out.append(text[i:j])
            i = j
        else:
            out.append(c)
            i += 1
    return "".join(out)


_DOC_SUFFIXES = {".md", ".markdown", ".txt", ".adoc", ".rst"}
_C_COMMENT_SUFFIXES = {".java", ".groovy", ".kt", ".kts", ".gradle", ".js", ".ts"}
_XML_SUFFIXES = {".xml", ".xsd", ".xsl", ".html", ".htm", ".jsp", ".jspx", ".tld"}


def c_code(text: str) -> str:
    """`text` with `//` and `/* */` comments blanked out (line breaks kept); string and char literals are kept, and
    a `//` inside one (`"http://..."`) does not start a comment."""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if text.startswith("//", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append(re.sub(r"[^\n]", " ", text[i:j]))
            i = j
        elif c in "\"'":
            j = i + 1
            while j < n and text[j] != c and text[j] != "\n":
                j += 2 if text[j] == "\\" else 1
            j = min(j + 1, n)
            out.append(text[i:j])
            i = j
        else:
            out.append(c)
            i += 1
    return "".join(out)


def code_text(path: str, text: str) -> str:
    """What the markers read: code only. SQL without comments; Java and other C-style sources without comments;
    XML and JSP without `<!-- -->`; properties without comment lines; prose documents (a README, a deploy
    note) not at all — a legacy name in a comment or a document is not legacy code."""
    suffix = Path(path).suffix.lower()
    if suffix in SQL_SUFFIXES:
        return sql_code(text)
    if suffix in _DOC_SUFFIXES:
        return ""
    if suffix in _C_COMMENT_SUFFIXES:
        return c_code(text)
    if suffix in _XML_SUFFIXES:
        return re.sub(r"<!--.*?-->", lambda m: re.sub(r"[^\n]", " ", m.group(0)), text, flags=re.S)
    if suffix == ".properties":
        return re.sub(r"(?m)^[ \t]*[#!].*$", "", text)
    return text


# ---------------------------------------------------------------------------
# Marker sets, per pattern.
#
#   legacy    — must NOT survive the migration. Removed in a diff = the change
#               is migration work; still present in an untouched file = a
#               coverage-gap candidate; ADDED in a diff = a regression.
#   modern    — the migration's target APIs. Added in a diff = migration work.
#   forbidden — never a legitimate fix, whatever the plan says (see the
#               java-8-to-25 skill's fix step's "never by adding --add-opens" rule).
# ---------------------------------------------------------------------------

_JAVA_LEGACY = [
    # Jakarta EE namespaces only — Java SE javax.sql / javax.naming / javax.crypto /
    # JAXP and JSR-107 javax.cache legitimately keep their javax names forever.
    _m("javax EE namespace",
       r"\bjavax\.(?:servlet|persistence|validation|annotation|transaction|ws\.rs|ejb|jms|mail|xml\.bind|xml\.ws|enterprise|inject|faces|batch)\b",
       "Jakarta EE package — becomes jakarta.* in the Spring Boot 3 / Spring 6 stage. Java SE javax.sql/naming/crypto/JAXP and javax.cache (JSR-107) are NOT part of that rename."),
    _m("Spring 3/4 hibernate3 support", r"org\.springframework\.orm\.hibernate[34]\b",
       "Removed in Spring 5 — rewrite onto org.springframework.orm.hibernate5 (Java 17 stage)."),
    _m("Spring Framework 3/4", r"<spring(?:\.framework)?\.version>\s*[34]\.|<groupId>org\.springframework</groupId>\s*<artifactId>spring-[\w-]+</artifactId>\s*<version>\s*[34]\.|"
       r"springframework\.org/schema/[\w/-]+-[34]\.\d\.xsd",
       "Spring 3/4 is long EOL and does not run on modern JDKs — Spring 6/7 through the Spring Boot stages "
       "(versioned XSD locations become versionless)."),
    _m("Hibernate 3/4", r"<hibernate\.version>\s*[34]\.|<artifactId>hibernate-(?:core|entitymanager|annotations)</artifactId>\s*<version>\s*[34]\.",
       "Hibernate 3/4 → Hibernate 6/7 (with Spring Boot 3/4): Criteria, HibernateTemplate and positional HQL are gone."),
    # `?` is JDBC's own placeholder (JdbcTemplate, PreparedStatement): only a file that builds Hibernate /
    # JPA queries can hold HQL.
    _m("HQL positional parameter", r"\"(?:from|select|update|delete)\b[^\"\n]*\?(?!\d)[^\"\n]*\"",
       "JDBC-style `?` parameters in HQL were removed in Hibernate 5.3 — use `?1` ordinals or `:named` parameters.",
       re.IGNORECASE,
       requires=r"\b(?:createQuery|createFilter|HibernateTemplate|getHibernateTemplate|org\.hibernate\.(?:Session|Query)\b|"
                r"Restrictions\.sqlRestriction|@(?:Named)?Query\s*\((?![^)]*nativeQuery\s*=\s*true))"),
    _m("commons-lang 2", r"\borg\.apache\.commons\.lang\.(?!3\b)|<artifactId>commons-lang</artifactId>",
       "commons-lang 2 is EOL — org.apache.commons.lang3 (commons-lang3)."),
    # Only the 2.x artifact is javax-era: RI 4 (Jakarta) keeps the WSServlet class names and the
    # sun-jaxws.xml namespace, so matching those would flag the migrated code as legacy.
    _m("JAX-WS RI 2.x (javax)", r"<artifactId>jaxws-rt</artifactId>\s*<version>\s*2\.",
       "The javax JAX-WS RI — jaxws-rt 4.x (Jakarta XML Web Services, same WSServlet wiring) or CXF 4 "
       "at the Jakarta stage."),
    _m("Jackson 1", r"org\.codehaus\.jackson",
       "Jackson 1 is EOL — an API rewrite to com.fasterxml.jackson, not a version bump (Java 17 stage)."),
    _m("Jackson afterburner", r"jackson-module-afterburner|jackson\.module\.afterburner",
       "Breaks under JDK 17 strong encapsulation — replace with jackson-module-blackbird."),
    _m("Jackson unsafe default typing", r"\benableDefaultTyping\s*\(",
       "Removed/unsafe — activateDefaultTyping(PolymorphicTypeValidator) with an allow-list."),
    _m("Ehcache 2", r"\bnet\.sf\.ehcache\b",
       "Ehcache 2 → Ehcache 3 (org.ehcache) — an API rewrite; getKeys()/getQuiet() have no equivalent."),
    _m("Spring Ehcache 2 support", r"org\.springframework\.cache\.ehcache|EhCacheCacheManager|EhCacheManagerFactoryBean",
       "Removed in Spring 6 — JCacheCacheManager over Ehcache 3's JSR-107 provider."),
    _m("Hibernate Ehcache 2 support", r"\bhibernate-ehcache\b|org\.hibernate\.cache\.ehcache",
       "Removed in Hibernate 6 — hibernate-jcache with the jcache region factory."),
    _m("ehcache-web", r"\behcache-web\b",
       "No modern equivalent — the filters are removed and flagged."),
    _m("log4j 1.2", r"\borg\.apache\.log4j\b|<artifactId>log4j</artifactId>",
       "log4j 1.2 is EOL — SLF4J + Logback."),
    _m("cglib / javassist", r"\bcglib(?:-nodep)?\b|\bjavassist\b",
       "Bundles an ASM that cannot read modern class files — remove it; Spring 5+ repackages cglib and Hibernate 5.3+ uses ByteBuddy."),
    _m("Oracle versioned dialect", r"Oracle(?:8i|9i|10g|12c)Dialect",
       "Versioned dialects were removed in Hibernate 6 — drop hibernate.dialect and let it auto-detect."),
    _m("C3P0 / DBCP pool", r"C3P0ConnectionProvider|\bcom\.mchange\.v2\b|\bcommons-dbcp\b",
       "Superseded by HikariCP once Spring Boot manages the datasource."),
    _m("legacy Oracle JDBC driver", r"\bojdbc(?:6|14)\b",
       "ojdbc6/ojdbc14 do not run on a modern JDK — ojdbc11."),
    _m("google-collections", r"\bgoogle-collections\b|com\.google\.collections",
       "Same packages as Guava — remove it and keep the newest Guava."),
    _m("removed Guava API", r"Objects\.toStringHelper|\bnew\s+Stopwatch\s*\(|\.elapsedMillis\s*\(|makeComputingMap|sameThreadExecutor",
       "Removed from modern Guava — MoreObjects, Stopwatch.createStarted(), CacheBuilder, directExecutor()."),
    _m("spring-mock", r"\bspring-mock\b",
       "A test library used at runtime scope — replace with real HttpServletRequestWrapper / ServletOutputStream."),
    _m("Mockito 1.x", r"\bmockito-all\b",
       "Mocks via cglib and breaks on JDK 9+ — mockito-core (4.11.0 in readiness, 5.x from the Java 17 stage)."),
    _m("JUnit 3", r"\bjunit\.framework\.TestCase\b|\bjunit\.framework\.Assert\b",
       "JUnit 3 is deprecated — report it even when the JUnit toggle is off."),
    _m("JUnit 4", r"\borg\.junit\.Test\b|\borg\.junit\.runner\b|SpringJUnit4ClassRunner|\bSpringRunner\b",
       "JUnit 4 is maintenance-only and deprecated by Spring Framework 7 — report it even when the JUnit toggle is off."),
    _m("Java 8 compiler level", r"<(?:source|target)>1\.8</(?:source|target)>|<maven\.compiler\.(?:source|target)>1\.8<|(?:source|target)Compatibility\s*=\s*['\"]?1\.8",
       "The compiler level never left Java 8 — expected only if the run stopped before the Java 17 stage."),
    _m("dead build plugin", r"maven-svn-revision-number-plugin|cargo-maven2-plugin",
       "Dead build cruft removed in the readiness stage."),
    _m("Spring MVC adapter class", r"\b(?:WebMvcConfigurerAdapter|HandlerInterceptorAdapter|WebSecurityConfigurerAdapter)\b",
       "Removed in Spring 6 / Spring Security 6 — implement WebMvcConfigurer / HandlerInterceptor directly; a "
       "SecurityFilterChain bean replaces WebSecurityConfigurerAdapter (Java 25 / Spring 6 stage)."),
    _m("Java EE descriptor namespace", r"\bxmlns(?::\w+)?=\"https?://(?:xmlns\.jcp\.org|java\.sun\.com)/xml/ns/(?:javaee|j2ee)\"",
       "A Java EE web.xml / descriptor header — the jakartaee namespace (web-app 6.0) at the Jakarta stage."),
    _m("JSTL 1.2 (javax)", r"<groupId>javax\.servlet(?:\.jsp\.jstl)?</groupId>\s*<artifactId>(?:jstl|javax\.servlet\.jsp\.jstl-api)</artifactId>|"
                          r"<groupId>taglibs</groupId>\s*<artifactId>standard</artifactId>",
       "The javax JSTL — jakarta.servlet.jsp.jstl-api 3.x plus an implementation (org.glassfish.web:"
       "jakarta.servlet.jsp.jstl) at the Jakarta stage; JSP taglib URIs keep working."),
    # Thymeleaf 2.1 (Spring Boot 1.5) → 3.x (Boot 2+); 3.1 with Boot 3/4 — references/thymeleaf-2-to-3.md.
    _m("Thymeleaf 2 template mode", r"\bspring\.thymeleaf\.mode\s*[=:]\s*(?:LEGACY)?HTML5\b|"
                                   r"setTemplateMode\s*\(\s*\"(?:LEGACY)?HTML5\"|TemplateMode\.(?:LEGACY)?HTML5\b",
       "HTML5 / LEGACYHTML5 do not exist in Thymeleaf 3 — mode HTML (the default: drop the property)."),
    _m("layout dialect decorator", r"\blayout:decorator\s*=",
       "Removed from the Thymeleaf Layout Dialect 3 — layout:decorate=\"~{layout}\"."),
    _m("Thymeleaf th:include", r"\bth:include\s*=",
       "Deprecated since Thymeleaf 3.0 — th:replace (or th:insert, which keeps the host element) with a "
       "~{...} fragment expression. Fragment inclusion runs BEFORE th:each on the same element."),
    _m("Thymeleaf 3.1 removed expression object", r"#(?:request|response|session|servletContext|httpServletRequest|httpSession)\b",
       "Removed in Thymeleaf 3.1 (Spring Boot 3+) — put what the template needs in the model."),
    _m("old Thymeleaf Spring Security extras", r"thymeleaf-extras-springsecurity[345]\b",
       "→ thymeleaf-extras-springsecurity6 with Spring Security 6+."),
]

_JAVA_MODERN = [
    _m("jakarta namespace", r"\bjakarta\.(?:servlet|persistence|validation|annotation|transaction|ws\.rs|ejb|jms|mail|xml\.bind)\b"),
    _m("modern compiler release", r"<release>(?:1[1-9]|2[0-9])</release>|<maven\.compiler\.release>|(?:source|target)Compatibility\s*=\s*['\"]?(?:1[1-9]|2[0-9])"),
    _m("Spring Boot starter", r"spring-boot-starter|spring-boot-maven-plugin|org\.springframework\.boot"),
    _m("Spring 5+ hibernate5 support", r"org\.springframework\.orm\.hibernate5"),
    _m("Jackson 2", r"\bcom\.fasterxml\.jackson\b|\bjackson-bom\b"),
    _m("Jackson 3", r"\btools\.jackson\b|JsonMapper\.builder"),
    _m("jackson blackbird", r"jackson-module-blackbird"),
    _m("Ehcache 3", r"\borg\.ehcache\b|JCacheCacheManager|\bhibernate-jcache\b"),
    _m("SLF4J", r"\borg\.slf4j\b|\blogback\b"),
    _m("JUnit Jupiter", r"org\.junit\.jupiter|\bjunit-jupiter\b|\bjunit-bom\b"),
    _m("mockito-core", r"\bmockito-core\b"),
    _m("modern surefire/failsafe", r"maven-(?:surefire|failsafe)-plugin"),
    _m("modern Guava", r"\bguava-bom\b|MoreObjects|Stopwatch\.create|directExecutor\s*\("),
    _m("ojdbc11", r"\bojdbc11\b"),
    _m("Spring Data JPA", r"spring-boot-starter-data-jpa|org\.springframework\.data\.jpa"),
    _m("Spring MVC interfaces", r"\bimplements\s+(?:[\w.]+\s*,\s*)*WebMvcConfigurer\b|\bSecurityFilterChain\b"),
    _m("Jakarta EE descriptor namespace", r"jakarta\.ee/xml/ns/jakartaee"),
    _m("Jakarta JSTL", r"jakarta\.servlet\.jsp\.jstl"),
    _m("Thymeleaf 3 fragment expression", r"~\{|\blayout:decorate\s*="),
]

_JAVA_FORBIDDEN = [
    _m("--add-opens / --add-exports escape hatch", r"--add-(?:opens|exports)\b",
       "The java-8-to-25 skill's fix step is explicit: this silences InaccessibleObjectException instead of removing the stale library. Never the fix."),
    _m("dependency pinned backwards", r"<!--\s*(?:downgrade|pin back|revert)\b",
       "A deliberate downgrade to make a build pass is a migration failure, not a fix."),
]

# Java 8 -> 11 is scoped to what Java 11 itself breaks, so its legacy set is the
# removed JDK APIs and the Java 8 compiler level -- NOT the EOL libraries the
# 8 -> 25 set lists, which run on Java 11 and are deliberately out of scope here.
_JAVA11_LEGACY = [
    # Spring 5 dropped orm.hibernate3/4 (hibernate5 is the Spring 5 module); Hibernate 5.3+ rejects JDBC-style `?`
    # in HQL. Present in a file that still has them = work the Spring/Hibernate move leaves to do.
    _m("Spring ORM hibernate3/4 support", r"org\.springframework\.orm\.hibernate[34]\b",
       "Removed in Spring 5 — org.springframework.orm.hibernate5 (same class names)."),
    _m("HQL positional parameter", r"\"(?:from|select|update|delete)\b[^\"\n]*\?(?!\d)[^\"\n]*\"",
       "JDBC-style `?` parameters in HQL were removed in Hibernate 5.3 — use `?0` ordinals (0-based in the "
       "setParameter(0, …) / HibernateTemplate.find(…) calls) or `:named` parameters.",
       re.IGNORECASE,
       requires=r"\b(?:createQuery|createFilter|HibernateTemplate|getHibernateTemplate|org\.hibernate\.(?:Session|Query)\b|"
                r"@(?:Named)?Query\s*\((?![^)]*nativeQuery\s*=\s*true))"),
    _m("removed JDK internal API", r"\bsun\.misc\.BASE64(?:En|De)coder\b|\bsun\.reflect\.Reflection\b|\bsun\.misc\.Cleaner\b",
       "Removed/encapsulated since Java 9 — java.util.Base64, StackWalker, java.lang.ref.Cleaner."),
    _m("method removed in Java 11", r"\.runFinalizersOnExit\s*\(|\bThread\.currentThread\(\)\.destroy\s*\(|\bcheckAwtEventQueueAccess\b|\bcheckTopLevelWindow\b|\bcheckSystemClipboardAccess\b|\bcheckMemberAccess\b|\bjavax\.security\.auth\.Policy\b",
       "Removed from the JDK in Java 11 — the code does not compile on 11."),
    _m("system class loader cast", r"\(\s*URLClassLoader\s*\)\s*(?:ClassLoader\.getSystemClassLoader|Thread\.currentThread\(\)\.getContextClassLoader)",
       "ClassCastException on Java 9+ — the system loader is no longer a URLClassLoader."),
    _m("Java 8 compiler level", r"<(?:source|target)>1\.[5-8]</(?:source|target)>|<maven\.compiler\.(?:source|target)>1\.[5-8]<|<java\.version>1\.[5-8]<|(?:source|target)Compatibility\s*=\s*['\"]?1\.[5-8]|VERSION_1_[5-8]",
       "The compiler level never reached 11 — every module must target release 11."),
    _m("Mockito 1.x", r"\bmockito-all\b|org\.mockito\.runners\.",
       "Mockito 1.x cannot mock on Java 11 — mockito-core 2.x (org.mockito.junit runner)."),
    _m("Java 11-incapable build plugin", r"findbugs-maven-plugin|<requireJavaVersion>\s*<version>\s*\[?1\.8",
       "Cannot run on / rejects JDK 11."),
]

_JAVA11_MODERN = [
    _m("release 11", r"<release>11</release>|<maven\.compiler\.release>11<|<java\.version>11<|(?:source|target)Compatibility\s*=\s*['\"]?11|VERSION_11|JavaLanguageVersion\.of\(\s*11\s*\)|release\s*=\s*11"),
    _m("removed Java EE module as a dependency", r"\bjaxb-api\b|\bjaxws-api\b|javax\.annotation-api|javax\.activation-api|javax\.transaction-api|javax\.xml\.soap-api|jaxb-runtime|jaxws-rt"),
    _m("JDK 9+ replacement API", r"\bjava\.util\.Base64\b|\bBase64\.get(?:Mime)?(?:En|De)coder\b|\bStackWalker\b|\bjava\.lang\.ref\.Cleaner\b|Runtime\.version\(\)"),
    _m("Java 11-capable build plugin", r"maven-(?:compiler|surefire|failsafe|war|jar|javadoc|shade|enforcer)-plugin|jacoco-maven-plugin|spotbugs-maven-plugin|aspectj-maven-plugin|jaxb2-maven-plugin|jaxws-maven-plugin"),
    _m("mockito-core / Mockito 2 runner", r"\bmockito-core\b|org\.mockito\.junit\.|powermock-api-mockito2|\bnullable\s*\("),
]

_JAVA11_FORBIDDEN = [
    _m("Jakarta namespace", r"^\s*import\s+(?:static\s+)?jakarta\.",
       "Java 11 keeps javax.* — the WildFly container provides Java EE, not Jakarta EE 9+.", re.MULTILINE),
    _m("Java level past 11", r"<release>(?:1[2-9]|[2-9]\d)</release>|<maven\.compiler\.(?:release|source|target)>(?:1[2-9]|[2-9]\d)<|(?:source|target)Compatibility\s*=\s*['\"]?(?:1[2-9]|[2-9]\d)\b|VERSION_(?:1[2-9]|[2-9]\d)\b|JavaLanguageVersion\.of\(\s*(?:1[2-9]|[2-9]\d)\s*\)",
       "The target is exactly Java 11."),
    _m("Spring Boot introduced", r"spring-boot|org\.springframework\.boot",
       "Out of scope — this migration changes the JDK only, never the framework or deployment model."),
    _m("--add-opens / --add-exports escape hatch", r"--add-(?:opens|exports)\b|--illegal-access",
       "Illegal reflective access is only a warning on Java 11 — an error here has another cause."),
]

_SOLR_LEGACY = [
    _m("SolrJ 4 server classes", r"\b(?:Http|Cloud|Concurrent|LBHttp)Solr(?:Server)\b|\bSolrServer\b",
       "Renamed to *SolrClient with builder construction in SolrJ 5+ (the SolrServer base type is SolrClient; "
       "EmbeddedSolrServer keeps its name). SolrClient is Closeable and query() also throws IOException."),
    _m("Trie field types", r"solr\.Trie\w*Field",
       "Removed in Solr 9 — Point field types with docValues."),
    _m("legacy solrconfig", r"<luceneMatchVersion>\s*4\.|\bsolr\.clustering\b",
       "luceneMatchVersion still on 4.x, or a contrib removed in Solr 9."),
    _m("schema defaults removed in Solr 7", r"<defaultSearchField>|<solrQueryParser\b",
       "Removed in Solr 7 — the df and q.op request parameters (in the handler defaults; note edismax's sow default "
       "also changed to false in Solr 7)."),
    _m("removed analysis option", r"\benablePositionIncrements\s*=|solr\.StandardFilterFactory",
       "enablePositionIncrements and StandardFilterFactory are gone from Lucene 5+/8 — drop them."),
    _m("removed Solr cache / handler class", r"solr\.(?:Fast)?LRUCache|solr\.LFUCache|solr\.admin\.AdminHandlers|<mergePolicy\b",
       "LRUCache/FastLRUCache/LFUCache were removed in Solr 9 (solr.CaffeineCache); AdminHandlers in Solr 6 (implicit "
       "handlers); <mergePolicy> in Solr 7 (<mergePolicyFactory>)."),
    _m("Solr 9 contrib / remote streaming", r"<lib\s+dir=\"[^\"]*contrib/|\benableRemoteStreaming\s*=",
       "contrib/ became modules/ in Solr 9 (enable with solr.modules, not <lib>); remote streaming is a system "
       "property, not a solrconfig attribute."),
    _m("graph-unaware synonyms", r"solr\.SynonymFilterFactory",
       "Deprecated — SynonymGraphFilterFactory (+ FlattenGraphFilterFactory at index time) for multi-word synonyms."),
]

_SOLR_MODERN = [
    _m("SolrJ client classes", r"\b(?:Http2?|Cloud|LBHttp2?)Solr(?:Client)\b"),
    _m("Point field types", r"solr\.\w*PointField"),
    _m("modern luceneMatchVersion", r"<luceneMatchVersion>\s*9\."),
]

_ORACLE_LEGACY = [
    # A column definition: a name, then LONG [RAW], then what may follow a column type. A Java `(Long)`
    # cast or `Long id;` field is not one.
    _m("LONG / LONG RAW column", r"(?<=\w)\s+LONG(?:\s+RAW)?\b(?=\s*(?:,|\)|$|NOT\b|NULL\b|DEFAULT\b))",
       "Deprecated since Oracle 8 — CLOB / BLOB.", re.IGNORECASE | re.MULTILINE),
    _m("deprecated Oracle driver class", r"\boracle\.jdbc\.driver\.OracleDriver\b",
       "The oracle.jdbc.driver package is deprecated — oracle.jdbc.OracleDriver."),
    _m("SID connect string", r"jdbc:oracle:thin:@(?!//)[\w.-]+:\d+:\w+",
       "SID syntax — Oracle 23ai is multitenant-only: connect to the PDB by service name (@//host:port/service)."),
    _m("optimizer feature pin", r"optimizer_features_enable", "Pins the optimizer to an old release."),
    _m("legacy Oracle JDBC driver", r"\bojdbc(?:6|8|14)\b", "→ ojdbc11 for 23ai."),
]

_ORACLE_MODERN = [
    _m("LOB column", r"\bCLOB\b|\bBLOB\b"),
    _m("ojdbc11", r"\bojdbc11\b"),
    _m("23ai feature", r"\bJSON\s+DUALITY\b|\bVECTOR\b|IF\s+NOT\s+EXISTS", "", re.IGNORECASE),
]

_TIBCO_LEGACY = [
    _m("TIBCO EMS client", r"\bcom\.tibco\.tibjms\b|\btibjms\b|\btibjmsnaming\b",
       "The EMS transport is what this migration removes."),
    _m("JMS API", r"\bjavax\.jms\b|\bjakarta\.jms\b|\bQueueConnectionFactory\b|\bTopicConnectionFactory\b",
       "JMS client code becomes Pub/Sub Publisher/Subscriber."),
]

_TIBCO_MODERN = [
    _m("Pub/Sub client", r"com\.google\.cloud\.pubsub|\bPubsubMessage\b|\bPublisher\b|\bSubscriber\b"),
    _m("Pub/Sub dependency", r"google-cloud-pubsub|spring-cloud-gcp-pubsub"),
]

_JSP_LEGACY = [
    _m("JSP view", r"<%@|<%=|\bjsp:useBean\b|\bstruts\b", "Server-rendered JSP is what this migration replaces."),
    _m("JSTL / scriptlet tags", r"http://java\.sun\.com/jsp/jstl"),
]

_JSP_MODERN = [
    _m("React component", r"\bfrom\s+['\"]react['\"]|useState|useEffect|export\s+default\s+function"),
    _m("BFF REST controller", r"@RestController|@GetMapping|@PostMapping"),
]

LEGACY_MARKERS: dict[str, list[Marker]] = {
    "java-8-to-25": _JAVA_LEGACY,
    "java-8-to-11": _JAVA11_LEGACY,
    "solr-4-to-9": _SOLR_LEGACY,
    "oracle-19c-to-23ai": _ORACLE_LEGACY,
    "tibco-ems-to-pubsub": _TIBCO_LEGACY,
    "jsp-to-react-bff": _JSP_LEGACY,
}

MODERN_MARKERS: dict[str, list[Marker]] = {
    "java-8-to-25": _JAVA_MODERN,
    "java-8-to-11": _JAVA11_MODERN,
    "solr-4-to-9": _SOLR_MODERN,
    "oracle-19c-to-23ai": _ORACLE_MODERN,
    "tibco-ems-to-pubsub": _TIBCO_MODERN,
    "jsp-to-react-bff": _JSP_MODERN,
}

FORBIDDEN_MARKERS: dict[str, list[Marker]] = {
    "java-8-to-25": _JAVA_FORBIDDEN,
    "java-8-to-11": _JAVA11_FORBIDDEN,
}


#: Patterns that GENERATE new trees beside the original application instead of
#: transforming it in place. For these, the legacy source is meant to survive --
#: the plan's own rollback section promises the old app stays deployable until
#: the replacement is verified -- so scanning it for legacy markers reports the
#: entire source repository as a coverage gap, one finding per file. The residual
#: scan is limited to the generated trees, where a legacy marker IS a real defect
#: (a scriptlet copied into a template, a JSP taglib in the BFF).
GENERATED_SUBTREES: dict[str, tuple[str, ...]] = {
    "jsp-to-react-bff": ("backend/", "frontend/"),
}


class MarkerHit(TypedDict):
    marker: str
    line: str
    note: str


class ChangedFileAudit(TypedDict):
    path: str
    status: str
    legacy_removed: list[MarkerHit]
    modern_added: list[MarkerHit]
    legacy_added: list[MarkerHit]
    forbidden_added: list[MarkerHit]


class UnchangedFileAudit(TypedDict):
    path: str
    legacy_present: list[MarkerHit]


@dataclass
class ChangeAudit:
    pattern: str
    markers_configured: bool
    changed_total: int = 0
    unchanged_total: int = 0
    unchanged_scanned: int = 0
    unchanged_out_of_scope: int = 0
    generated_subtrees: tuple[str, ...] = ()
    #: Untouched files inside the pattern's scope fence (agents/shared/scope_fence.py):
    #: frozen by design, so never scanned as coverage gaps.
    unchanged_frozen: int = 0
    has_fence: bool = False
    explained: list[ChangedFileAudit] = field(default_factory=list)
    unexplained: list[ChangedFileAudit] = field(default_factory=list)
    regressions: list[ChangedFileAudit] = field(default_factory=list)
    residual_legacy: list[UnchangedFileAudit] = field(default_factory=list)
    #: Changed only by another migration of the same bundle run: {path: pattern}. Not reviewed here.
    others: dict[str, str] = field(default_factory=dict)
    error: str = ""


def _clip(line: str) -> str:
    line = line.strip()
    return line if len(line) <= _MAX_LINE_CHARS else line[:_MAX_LINE_CHARS] + " …"


@functools.lru_cache(maxsize=None)
def _anchored_source(pattern: str, flags: int) -> bool:
    return bool(re.search(r"(?<!\\)(?:\^|\$)|\\[AZz]", pattern))


def _anchored(compiled: re.Pattern) -> bool:
    return _anchored_source(compiled.pattern, compiled.flags)


def _scan(lines: list[str], markers: list[Marker], context: str | None = None) -> list[MarkerHit]:
    """First `_MAX_HITS_PER_FILE` distinct markers matched anywhere in *lines* (of a file whose text
    is `context`: a marker whose `requires` it does not meet is skipped)."""
    markers = [m for m in markers if m.applies_to(context)]
    # A marker that matches no line cannot match the text as a whole: one search per marker over the joined
    # lines drops the markers a file never triggers before any per-line work. Anchored patterns (`^`, `$`) mean
    # something different per line than over the whole text, so they always go through the lines.
    if len(lines) > 3:
        joined = "\n".join(lines)
        markers = [m for m in markers if _anchored(m.pattern) or m.pattern.search(joined)]
        if not markers:
            return []
    hits: list[MarkerHit] = []
    seen: set[str] = set()
    for line in lines:
        for marker in markers:
            if marker.name in seen:
                continue
            if marker.pattern.search(line):
                seen.add(marker.name)
                hits.append({"marker": marker.name, "line": _clip(line), "note": marker.note})
                if len(hits) >= _MAX_HITS_PER_FILE:
                    return hits
    return hits


def relevant_files(root: Path) -> dict[str, Path]:
    """`{relative path: absolute path}` for every file that is really part of the
    repository — build output, VCS metadata and IDE folders excluded."""
    out: dict[str, Path] = {}
    for path in fswalk.files(root):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if EXCLUDED_DIRS & set(rel.parts):
            continue
        out[rel.as_posix()] = path
    return out


def snapshot(root: str | Path) -> dict[str, str]:
    """`{relative path: sha256}` of every relevant file — taken when a migration
    pass starts, so the files that pass changed can be told apart afterwards."""
    import hashlib
    base = Path(root).resolve()
    if not base.exists():
        return {}
    return {rel: hashlib.sha256(path.read_bytes()).hexdigest() for rel, path in relevant_files(base).items()}


def changed_since(root: str | Path, before: dict[str, str]) -> list[str]:
    """Files added, modified or deleted since `before` (a snapshot)."""
    after = snapshot(root)
    return sorted(rel for rel in set(before) | set(after) if before.get(rel) != after.get(rel))


def other_migrations_files(state: dict) -> dict[str, str]:
    """`{path: pattern}` for files that, in a bundle run, only ANOTHER migration
    changed (`state["pass_changes"]`: pattern -> files its finished passes
    changed; `state["pass_start_file"]`: the running pass's start snapshot). A
    review compares the shared workspace with the upload, so without this a
    companion's edits read as this pattern's scope creep."""
    raw = state.get("pass_changes") or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or "{}")
        except ValueError:
            raw = {}
    mine = state.get("pattern", "")
    own = set(raw.get(mine, []))
    start = state.get("pass_start_file") or ""
    if start and Path(start).is_file() and state.get("workspace_dir"):
        # The running pass's own changes so far: it is reviewed before they are recorded.
        try:
            own |= set(changed_since(state["workspace_dir"], json.loads(Path(start).read_text(encoding="utf-8"))))
        except ValueError:
            pass
    out: dict[str, str] = {}
    for pattern, files in raw.items():
        if pattern != mine:
            for rel in files:
                if rel not in own:
                    out.setdefault(rel, pattern)
    return out


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def changed_file_statuses(baseline_dir: str, workspace_dir: str) -> dict[str, str]:
    """`{relative path: "added" | "modified" | "deleted"}` for every file that
    differs between the pristine baseline and the migrated workspace.

    Shared with plan_coverage.py, so the marker audit and the plan-conformance
    check can never disagree about which files this run actually touched.
    """
    baseline_root = Path(baseline_dir).resolve() if baseline_dir else None
    workspace_root = Path(workspace_dir).resolve() if workspace_dir else None
    if not baseline_root or not baseline_root.exists() or not workspace_root or not workspace_root.exists():
        return {}

    before = relevant_files(baseline_root)
    after = relevant_files(workspace_root)
    statuses: dict[str, str] = {}
    for rel in sorted(set(before) | set(after)):
        if rel not in after:
            statuses[rel] = "deleted"
        elif rel not in before:
            statuses[rel] = "added"
        elif _read(before[rel]) != _read(after[rel]):
            statuses[rel] = "modified"
    return statuses


def audit_changes(baseline_dir: str, workspace_dir: str, pattern: str,
                  others: dict[str, str] | None = None) -> ChangeAudit:
    """Compare the pristine baseline against the migrated workspace and classify
    every file as explained / unexplained / regressed / residually legacy.
    `others` (other_migrations_files) are set aside, not classified."""
    legacy = LEGACY_MARKERS.get(pattern, [])
    modern = MODERN_MARKERS.get(pattern, [])
    forbidden = FORBIDDEN_MARKERS.get(pattern, [])
    subtrees = GENERATED_SUBTREES.get(pattern, ())
    audit = ChangeAudit(pattern=pattern, markers_configured=bool(legacy or modern),
                        generated_subtrees=subtrees,
                        has_fence=scope_fence.fence_for(pattern) is not None)

    baseline_root = Path(baseline_dir).resolve() if baseline_dir else None
    workspace_root = Path(workspace_dir).resolve() if workspace_dir else None
    if not baseline_root or not baseline_root.exists() or not workspace_root or not workspace_root.exists():
        audit.error = "baseline or workspace directory is unavailable — change audit could not run"
        return audit

    before = relevant_files(baseline_root)
    after = relevant_files(workspace_root)

    for rel in sorted(set(before) | set(after)):
        before_text = _read(before[rel]) if rel in before else ""
        after_text = _read(after[rel]) if rel in after else ""
        before_code, after_code = code_text(rel, before_text), code_text(rel, after_text)

        if rel in before and rel in after and before_text == after_text:
            audit.unchanged_total += 1
            if subtrees and not rel.startswith(subtrees):
                # The original application, which this pattern leaves in place by design.
                audit.unchanged_out_of_scope += 1
                continue
            if scope_fence.frozen_reason(pattern, rel):
                # Frozen by the pattern's scope fence: untouched is the only correct state.
                audit.unchanged_frozen += 1
                continue
            if Path(rel).suffix.lower() in _SCAN_SUFFIXES and legacy:
                audit.unchanged_scanned += 1
                present = _scan(after_code.splitlines(), legacy, after_code)
                if present:
                    audit.residual_legacy.append({"path": rel, "legacy_present": present})
            continue

        if others and rel in others:
            audit.others[rel] = others[rel]
            continue
        audit.changed_total += 1
        if rel not in after:
            status = "deleted"
        elif rel not in before:
            status = "added"
        else:
            status = "modified"

        removed_lines: list[str] = []
        added_lines: list[str] = []
        for line in difflib.unified_diff(          # code only: a reworded SQL comment is not a change
            before_code.splitlines(), after_code.splitlines(), lineterm="", n=0
        ):
            if line.startswith("+++") or line.startswith("---") or line.startswith("@@"):
                continue
            if line.startswith("-"):
                removed_lines.append(line[1:])
            elif line.startswith("+"):
                added_lines.append(line[1:])

        entry: ChangedFileAudit = {
            "path": rel,
            "status": status,
            "legacy_removed": _scan(removed_lines, legacy, before_code),
            "modern_added": _scan(added_lines, modern, after_code),
            "legacy_added": _scan(added_lines, legacy, after_code),
            "forbidden_added": _scan(added_lines, forbidden, after_code),
        }
        frozen = scope_fence.frozen_reason(pattern, rel)
        if frozen:
            # Any change inside the fence is a regression on its own, whatever
            # the lines say -- the pattern promised this file would not move.
            entry["forbidden_added"].insert(0, {
                "marker": "frozen file changed", "line": f"{status}: {rel}", "note": frozen,
            })

        if entry["forbidden_added"] or entry["legacy_added"]:
            audit.regressions.append(entry)
        if entry["legacy_removed"] or entry["modern_added"]:
            audit.explained.append(entry)
        elif not entry["forbidden_added"] and not entry["legacy_added"]:
            audit.unexplained.append(entry)

    return audit


# ---------------------------------------------------------------------------
# Rendering — the tool returns markdown, since its only consumer is an LLM
# reviewer that has to quote this evidence back in its report.
# ---------------------------------------------------------------------------

def _render_hits(hits: list[MarkerHit], label: str) -> list[str]:
    out: list[str] = []
    for hit in hits:
        note = f" — {hit['note']}" if hit["note"] else ""
        out.append(f"    - {label} `{hit['marker']}`: `{_clip(hit['line'])}`{note}")
    return out


def _truncate_note(shown: int, total: int) -> list[str]:
    if total > shown:
        return [f"  _(… and {total - shown} more — the same adjudication applies)_"]
    return []


def to_markdown(audit: ChangeAudit) -> str:
    if audit.error:
        return f"# Change Audit\n\nERROR: {audit.error}"

    lines = [
        "# Change Audit (deterministic — baseline vs. migrated workspace)",
        "",
        f"- Pattern: `{audit.pattern}`",
        f"- Files changed: **{audit.changed_total}**",
        f"- Files unchanged: **{audit.unchanged_total}** ({audit.unchanged_scanned} of them scannable source/config)",
    ]
    if audit.others:
        lines.append(f"- Changed only by the run's other migrations, so not reviewed here: {len(audit.others)} — "
                     + ", ".join(f"`{p}` ({pat})" for p, pat in sorted(audit.others.items())[:_MAX_FILES_PER_BUCKET]))
    if audit.generated_subtrees:
        trees = ", ".join(f"`{t}`" for t in audit.generated_subtrees)
        lines += [
            f"- This pattern GENERATES {trees} beside the original application, which it leaves in "
            f"place on purpose. {audit.unchanged_out_of_scope} untouched file(s) outside those trees "
            "are the original app and are **not** coverage gaps — do not report them as such. The "
            "residual-legacy check below covers the generated trees only, where a legacy marker "
            "would be a real defect.",
        ]
    if audit.has_fence:
        lines += [
            f"- This pattern has a SCOPE FENCE: {audit.unchanged_frozen} untouched file(s) are frozen "
            "(JSP, web roots, WildFly descriptors, launch configuration) and are correct untouched — "
            "never report them as coverage gaps. Any CHANGED frozen file appears under Regressions as "
            "`frozen file changed` and is a CRITICAL finding.",
        ]
    if not audit.markers_configured:
        lines += [
            "",
            f"No relevance markers are configured for `{audit.pattern}`, so the two relevance "
            "questions below are yours to answer from the plan and the files alone — this audit "
            "only supplies the changed/unchanged split.",
        ]

    if audit.changed_total == 0:
        lines += [
            "",
            "## ⚠ Nothing changed",
            "",
            "The migrated workspace is byte-identical to the uploaded baseline. No migration work "
            "landed at all. This is a CRITICAL finding regardless of what the modify results or the "
            "build result claim — report it as the headline finding and do not describe the run as "
            "successful.",
        ]
        return "\n".join(lines)

    # 1 — changes that carry no migration signal.
    lines += ["", "## 1. Changed files with no migration signal", ""]
    if not audit.unexplained:
        lines.append("None — every changed file removed a legacy marker or added a modern one.")
    else:
        lines.append(
            "These files were rewritten, but the diff neither removed a known legacy marker nor "
            "added a known target-stack one. Read each one and decide: legitimate collateral work "
            "the plan called for (a call site updated because its dependency moved, a rename that "
            "propagated), or unrequested scope creep / a gratuitous reformat? Report the second kind."
        )
        lines.append("")
        for entry in audit.unexplained[:_MAX_FILES_PER_BUCKET]:
            lines.append(f"- `{entry['path']}` ({entry['status']})")
        lines += _truncate_note(_MAX_FILES_PER_BUCKET, len(audit.unexplained))

    # 2 — regressions.
    lines += ["", "## 2. Regressions introduced by the migration", ""]
    if not audit.regressions:
        lines.append("None — no legacy or forbidden marker appears in any added line.")
    else:
        lines.append(
            "An added line re-introduces a legacy marker, or uses a fix the skills forbid. Each of "
            "these is a HIGH or CRITICAL finding unless the plan explicitly authorised it."
        )
        lines.append("")
        for entry in audit.regressions[:_MAX_FILES_PER_BUCKET]:
            lines.append(f"- `{entry['path']}` ({entry['status']})")
            lines += _render_hits(entry["forbidden_added"], "FORBIDDEN")
            lines += _render_hits(entry["legacy_added"], "legacy re-added")
        lines += _truncate_note(_MAX_FILES_PER_BUCKET, len(audit.regressions))

    # 3 — untouched files that still look legacy.
    lines += ["", "## 3. Unchanged files that still match a legacy marker", ""]
    if not audit.residual_legacy:
        scope = " in the generated trees" if audit.generated_subtrees else ""
        lines.append(
            f"None — no untouched source or config file{scope} still matches a legacy marker for "
            "this pattern. The unchanged files are, on this evidence, genuinely out of scope."
        )
    else:
        lines.append(
            "These files were never touched, yet still contain legacy markers. Each is either a **file "
            "the migration missed** (a real coverage gap — report it, naming the plan task that should "
            "have covered it) or **legitimately out of scope** (owned by a later stage, or excluded by "
            "a toggle the user left off, e.g. JUnit 3/4 when the JUnit upgrade was declined, or "
            "`javax.*` when no Spring Boot upgrade was requested). Check each against the confirmed "
            "plan and say which — do not report them as a list without adjudicating."
        )
        lines.append("")
        for entry in audit.residual_legacy[:_MAX_FILES_PER_BUCKET]:
            lines.append(f"- `{entry['path']}`")
            lines += _render_hits(entry["legacy_present"], "still present")
        lines += _truncate_note(_MAX_FILES_PER_BUCKET, len(audit.residual_legacy))

    # 4 — the explained majority, as a count only.
    lines += [
        "",
        "## 4. Changed files carrying a clear migration signal",
        "",
        f"{len(audit.explained)} file(s) removed a legacy marker and/or added a target-stack one. "
        "These need no relevance justification — review them for correctness as usual.",
    ]
    for entry in audit.explained[:_MAX_FILES_PER_BUCKET]:
        signals = [h["marker"] for h in entry["legacy_removed"]] + [h["marker"] for h in entry["modern_added"]]
        lines.append(f"- `{entry['path']}` ({entry['status']}): {', '.join(signals)}")
    lines += _truncate_note(_MAX_FILES_PER_BUCKET, len(audit.explained))

    lines += [
        "",
        "---",
        "",
        "Markers are regex heuristics, biased towards recall: they flag candidates, they do not "
        "return verdicts. Adjudicate every entry against the confirmed plan before writing a finding, "
        "and never report a marker hit you could not confirm by reading the file. In a companion-"
        "bundle run all patterns share one workspace: files only another migration changed are set "
        "aside above, while a file two migrations both changed appears here with both diffs — "
        "judge only this pattern's part of it.",
    ]
    return "\n".join(lines)


def audit_migration_changes(tool_context: ToolContext) -> str:
    """Audit what this migration run actually changed, before reviewing any file.

    Compares the pristine uploaded repository against the migrated workspace and
    reports, with the matched line as evidence: files changed with no migration
    signal (possible scope creep), legacy APIs re-introduced or forbidden fixes
    applied (regressions), and untouched files that still match a legacy marker
    (possible coverage gaps). Call this FIRST — it tells you which files are
    worth reading and is the only way to see what was left untouched.

    Returns:
        A markdown change-audit report, or a report whose body says the audit
        could not run if the baseline snapshot is unavailable.
    """
    state = tool_context.state or {}
    return to_markdown(audit_changes(
        state.get("baseline_dir", ""),
        state.get("workspace_dir", ""),
        state.get("pattern", ""),
        other_migrations_files(state),
    ))
