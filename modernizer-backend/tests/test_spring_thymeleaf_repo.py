"""
A Spring Boot 2.7 / Java 11 multi-module repository with a Thymeleaf UI,
Spring Security + LDAP, a reactive module and vendored front-end libraries —
the shape of a typical internal Java service. Everything here is deterministic
(parsers and patterns, no model): the same repository always gives the same
stacks, fingerprint and rule candidates.
"""
import json
from pathlib import Path

import main
from agents.shared import repo_fingerprint as rf
from agents.shared import rule_candidates as rc
from agents.shared import stack_detector as sd

T = "pds-service/src/main/resources/templates"
REPO = {
    "pom.xml": """<project><groupId>com.acme</groupId><artifactId>pds</artifactId><packaging>pom</packaging>
<parent><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-parent</artifactId><version>2.7.0</version></parent>
<properties><java.version>11</java.version><project.build.sourceEncoding>UTF-8</project.build.sourceEncoding><app.name>pds</app.name></properties>
<modules><module>pds-dao</module><module>pds-javaflux</module><module>pds-service</module></modules></project>""",
    "pds-service/pom.xml": """<project><artifactId>pds-service</artifactId><dependencies>
<dependency><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-thymeleaf</artifactId></dependency>
<dependency><groupId>org.springframework.security</groupId><artifactId>spring-security-ldap</artifactId></dependency>
<dependency><groupId>org.apache.poi</groupId><artifactId>poi-ooxml</artifactId><version>5.2.2</version></dependency>
</dependencies></project>""",
    "pds-dao/pom.xml": "<project><artifactId>pds-dao</artifactId></project>",
    "pds-javaflux/src/main/java/com/acme/pds/flux/ProductStandardizer.java": """package com.acme.pds.flux;
import reactor.core.publisher.Flux;
public class ProductStandardizer {
    public Flux<Product> standardize(Flux<Product> in) {
        return in.filter(p -> p.getPrice() > 0 && !p.isDiscontinued())
                 .map(p -> p.getUpc().length() == 12 ? p : p.withUpc("0" + p.getUpc()));
    }
    public Flux<Product> clean(Flux<Product> in) {
        return in.filter(p -> p != null);
    }
}
""",
    "pds-service/src/main/java/com/acme/pds/web/SecurityConfig.java": """package com.acme.pds.web;
public class SecurityConfig {
    protected void configure(HttpSecurity http) throws Exception {
        http.authorizeRequests().antMatchers("/admin/**").hasRole("PDS_ADMIN")
            .antMatchers("/selfservicetool/**").hasAnyRole("PDS_ADMIN", "PDS_USER").anyRequest().authenticated();
    }
}
""",
    "pds-service/src/main/java/com/acme/pds/web/JobController.java": """package com.acme.pds.web;
@PreAuthorize("hasRole('PDS_USER')")
public class JobController {
    @PreAuthorize("hasRole('PDS_ADMIN')")
    public String deleteJob(String id) { service.delete(id); return "redirect:/jobfinder"; }
    @Scheduled(cron = "0 0 2 * * *")
    public void nightlyStandardization() { service.runAll(); }
    public String list() { return "jobfinder/search"; }
}
""",
    f"{T}/dashboard/index.html": """<html xmlns:th="http://www.thymeleaf.org">
<script th:src="@{/vendor/jquery/jquery-3.6.0.min.js}"></script>
<div th:if="${job.failedCount > 0}">Some products failed standardization</div>
<a sec:authorize="hasRole('PDS_ADMIN')" th:href="@{/admin}">Admin</a>
<span th:text="${job.ok} ? 'OK' : 'Check'"></span>
</html>""",
    f"{T}/jobfinder/search.html": '<html xmlns:th="http://www.thymeleaf.org"><div th:each="j : ${jobs}" th:text="${j.name}"></div></html>',
    "pds-service/src/main/resources/static/js/dashboard.js":
        "function validateUpload(f) { if (f.size > 5000000) { return false; } return true; }\n",
    "pds-service/src/main/resources/static/vendor/jquery/jquery-3.6.0.min.js": "/*! jQuery v3.6.0 */ function x(a){if(a>1)return 1}",
    "pds-service/src/main/resources/static/plain.html": "<html><body>About</body></html>",
    "pds-service/src/main/resources/application.properties":
        "spring.ldap.urls=ldap://ldap.acme.net:389\npds.db.password=ENC(abc123==)\n",
}


def _write(root: Path) -> Path:
    for rel, text in REPO.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return root


def test_the_ui_and_the_directory_are_stacks_of_their_own(tmp_path):
    stacks = {s["pattern"]: s for s in sd.detect_stacks(str(_write(tmp_path)))}
    assert list(stacks) == ["ldap", "thymeleaf", "java"]                    # identity → web tier → application
    assert stacks["thymeleaf"]["reference"] == "thymeleaf.md" and stacks["ldap"]["reference"] == "identity.md"
    assert "jquery" not in stacks and "javascript" not in stacks            # the Thymeleaf UI owns its scripts


def test_the_fingerprint_shows_the_parent_pom_key_properties_and_th_src_scripts(tmp_path):
    fp = rf.fingerprint(str(_write(tmp_path)))
    root = next(m for m in fp["manifests"] if m["path"] == "pom.xml")
    assert root["dependencies"] == [{"name": "org.springframework.boot:spring-boot-starter-parent",
                                     "version": "2.7.0", "scope": "parent"}]
    assert root["properties"] == {"java.version": "11", "project.build.sourceEncoding": "UTF-8"}
    assert fp["scripts"]["jquery"] == [f"{T}/dashboard/index.html"]
    md = rf.to_markdown(fp)
    assert "Key properties: `java.version` = 11" in md and "| `org.springframework.boot:spring-boot-starter-parent` | 2.7.0 | parent |" in md


def test_rules_in_lambdas_access_rules_schedules_and_templates_are_candidates(tmp_path):
    scan = rc.scan(str(_write(tmp_path)))
    by = {(c.kind, c.symbol.rsplit(".", 1)[-1] if c.language == "Java" else c.symbol): c for c in scan.candidates}
    standardize = by[("method", "standardize")]
    assert standardize.status == "pending" and "comparison ×2" in standardize.signals and "ternary ×1" in standardize.signals
    assert ("method", "clean") not in by                                    # a null filter decides nothing
    assert "authorization-rule ×3" in by[("method", "configure")].signals    # hasRole, hasAnyRole, authenticated
    assert by[("authorization", "deleteJob")].signals == ["@PreAuthorize(\"hasRole('PDS_ADMIN')\")"]
    assert by[("authorization", "JobController")].status == "pending"        # class-level access rule
    assert by[("scheduled", "nightlyStandardization")].signals == ['@Scheduled(cron = "0 0 2 * * *")']
    assert ("method", "list") not in by                                     # no decision, no annotation
    view = by[("view-logic", "index.html")]
    assert view.language == "Thymeleaf" and view.signals == ["conditional rendering ×3"]
    assert ("view-logic", "search.html") not in by                          # a template with no conditions
    assert ("method", "validateUpload") in by and not any("vendor/" in c.path for c in scan.candidates)
    assert scan.files_by_language["Thymeleaf"] == {"files": 2, "parser": "pattern"}   # plain.html is not a template


def test_extraction_and_chunking_cover_the_ui_stacks_files(tmp_path):
    root = str(_write(tmp_path))
    assert main._rule_languages([{"pattern": "thymeleaf", "kind": "web-tier"}]) >= {"Thymeleaf", "JavaScript"}
    files = main._stack_files(root, {"pattern": "thymeleaf", "kind": "web-tier"})
    assert files == sorted([f"{T}/dashboard/index.html", f"{T}/jobfinder/search.html",
                            "pds-service/src/main/resources/static/js/dashboard.js",
                            "pds-service/src/main/resources/static/plain.html"])   # vendor/ excluded


def test_everything_is_deterministic(tmp_path):
    root = str(_write(tmp_path))
    first = (json.dumps(sd.detect(root), sort_keys=True), [c.to_dict() | {"source": c.source} for c in rc.scan(root).candidates])
    second = (json.dumps(sd.detect(root), sort_keys=True), [c.to_dict() | {"source": c.source} for c in rc.scan(root).candidates])
    assert first == second


def test_db2_is_detected_from_every_driver_coordinate(tmp_path):
    for i, dep in enumerate(("<groupId>com.ibm.db2</groupId><artifactId>jcc</artifactId>",
                             "<groupId>com.ibm.db2.jcc</groupId><artifactId>db2jcc4</artifactId>")):
        root = tmp_path / str(i)
        root.mkdir()
        (root / "pom.xml").write_text(f"<project><dependencies><dependency>{dep}</dependency></dependencies></project>")
        assert "db2" in {s["pattern"] for s in sd.detect_stacks(str(root))}, dep
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "ds.properties").write_text("driver=com.ibm.db2.jcc.DB2Driver\n")
    assert "db2" in {s["pattern"] for s in sd.detect_stacks(str(cfg))}
