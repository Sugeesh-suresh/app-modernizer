"""
Pins the Java 8-era legacy-stack rules.

A Java 8 repo rarely fails to reach Java 25 because of the language — it fails
because Spring 3.x/4.x, Hibernate 3/4, cglib and javassist bundle an ASM that
refuses newer class files, so they die at context startup rather than at
compile time. Two consequences are easy to regress and are pinned here:

  * the test stack is modernised FIRST (readiness), because it is what proves
    the later stages preserved behaviour, and Mockito 1.x / surefire 2.x cannot
    even start on the JDK those stages run on;
  * each JDK stage owns its framework floor. The Java 17 stage must be allowed
    to raise plain Spring to 5.3.x and the Java 25 stage to 6.x — a guardrail
    that flatly forbids framework changes there would strand an old Spring app
    on a JDK it cannot run on.
"""
import pathlib
import re

from google.adk.skills import load_skill_from_dir

from agents.java_8_to_25.agents import INCREMENTAL_STAGES

SKILLS_DIR = pathlib.Path(__file__).parent.parent / "agents" / "skills"

BUILD_SYSTEMS = "Modernize Build Systems (Maven/Gradle)"
JAVA_17 = "Java 8 → Java 17 LTS"
JAVA_25 = "Java 17 → Java 25 LTS"


def _read(relative: str) -> str:
    return (SKILLS_DIR / relative).read_text()


def _guardrail(title: str) -> str:
    return next(s.guardrail for s in INCREMENTAL_STAGES if s.title == title)


def test_the_modifier_ships_the_legacy_library_reference():
    # Stages 3 and 6 load no extra skill, so this reference has to travel with the base
    # modify skill or those stages never see the legacy rules at all.
    references = load_skill_from_dir(SKILLS_DIR / "java-8-to-25-modify").resources.references
    assert "legacy-library-modernization.md" in references
    assert "legacy-library-modernization.md" in _read("java-8-to-25-modify/SKILL.md")


def test_every_legacy_stack_is_covered_by_the_reference():
    text = _read("java-8-to-25-modify/references/legacy-library-modernization.md")
    for token in (
        "org.springframework.orm.hibernate3", "org.hibernate.Interceptor", "Oracle10gDialect",
        "C3P0ConnectionProvider", "org.codehaus.jackson", "JsonMethod", "net.sf.ehcache",
        "getQuiet", "org.apache.log4j", "cglib", "javassist", "aspectj", "ojdbc6",
        "google-collections", "spring-mock", "javax.xml.bind", "maven-svn-revision-number-plugin",
        "cargo-maven2-plugin", "mockito", "surefire",
    ):
        assert token in text, token


def test_the_test_stack_is_modernised_in_readiness_before_production_code():
    skill = _read("java-migration-readiness/SKILL.md")
    assert "Baseline safety net" in skill
    # Mockito 1.x mocks via cglib and breaks on JDK 9+; 4.11.0 is the last line that still
    # runs on a Java 8 runtime, which is what the readiness stage still targets.
    assert "4.11.0" in skill and "JDK 9+" in skill
    assert "3.2.5" in skill  # surefire/failsafe 2.x cannot fork a test JVM on JDK 9+
    # ...and the stage's "no version changes" rule has to admit that exception, or the
    # modifier will refuse the bump it was just told to make.
    assert "outside the test stack" in _read("java-migration-readiness/references/build-modernization.md")


def test_readiness_guardrail_allows_the_test_stack_bump():
    guardrail = _guardrail(BUILD_SYSTEMS)
    assert "mockito-core" in guardrail
    assert "Test-scoped" in guardrail


def test_the_java_17_stage_owns_the_spring_5_3_floor():
    guardrail = _guardrail(JAVA_17)
    assert "5.3" in guardrail
    assert "hibernate3" in guardrail and "hibernate5" in guardrail
    # It must still not do the Spring Boot stages' work.
    assert "do not rename Jakarta EE" in guardrail
    assert "Spring Boot version" in guardrail


def test_the_java_25_stage_carries_a_plain_spring_app_to_spring_6():
    guardrail = _guardrail(JAVA_25)
    assert "Spring 6.x" in guardrail
    # Spring 6 is jakarta-only, so this stage has to do the rename when there is no Boot upgrade.
    assert "jakarta." in guardrail
    # But never the Java SE packages — the recurring build break this repo has already hit.
    assert "javax.sql" in guardrail


def test_the_fixer_knows_the_legacy_failure_signatures():
    fixes = _read("java-8-to-25-fix/references/common-build-fixes.md")
    for token in (
        "InaccessibleObjectException", "Unsupported class file major version",
        "org.springframework.orm.hibernate3", "org.codehaus.jackson", "getQuiet",
        "org.apache.log4j", "google-collections", "forked VM terminated",
    ):
        assert token in fixes, token
    # --add-opens hides the cglib/javassist problem instead of fixing it.
    assert "not the fix" in fixes
    assert "--add-opens" in _read("java-8-to-25-fix/SKILL.md")


def test_the_planner_plans_the_legacy_work_into_the_java_17_stage():
    plan = _read("java-8-to-25-plan/SKILL.md")
    # The title also appears backticked in the "renumber without Spring Boot" paragraph, so take
    # the last occurrence — the real stage heading in the template.
    stage_17 = plan.split(f"## Stage 3: {JAVA_17}")[-1].split("## Stage 4:")[0]
    for token in ("5.3.x", "hibernate3", "org.codehaus.jackson", "net.sf.ehcache", "log4j",
                  "cglib", "ojdbc"):
        assert token in stage_17, token
    # Required even without the Spring Boot toggle — an old Spring app cannot run on Java 17.
    assert "`{springboot_upgrade}` is false" in stage_17


def test_junit_3_and_4_are_called_out_as_deprecated_even_without_the_junit_toggle():
    reference = _read("java-8-to-25-modify/references/legacy-library-modernization.md")
    for token in ("junit.framework.TestCase", "junit-vintage-engine", "SpringRunner",
                  "JUnit 3 and JUnit 4 are deprecated", "When it was not requested"):
        assert token in reference, token
    # Only the migration is gated by the toggle — the call-out is not.
    checklist = _read("java-8-to-25-plan/references/java8-to-java25-checklist.md")
    assert "Only the migration is gated by `{junit_upgrade}`" in checklist
    assert "Deprecated" in _read("java-8-to-25-re/SKILL.md")
    assert "deprecated" in _read("java-migration-readiness/SKILL.md")
    plan = _read("java-8-to-25-plan/SKILL.md")
    # Count real headings, not inline mentions of the section name.
    assert len(re.findall(r"^#+ Deprecated Libraries\s*$", plan, re.MULTILINE)) == 2  # bigbang and incremental shapes
    assert "## Deprecated Libraries Remaining" in _read("java-8-to-25-report/SKILL.md")


def test_jackson_is_covered_from_jackson_1_through_jackson_3():
    reference = _read("java-8-to-25-modify/references/legacy-library-modernization.md")
    for token in ("jackson-bom", "enableDefaultTyping", "jackson-module-blackbird", "jackson-datatype-jsr310"):
        assert token in reference, token
    boot4 = _read("springboot-war-to-boot4/references/boot4-dependency-cleanup.md")
    for token in ("tools.jackson", "JacksonException", "JsonMapper.builder()", "jackson-datatype-jsr310"):
        assert token in boot4, token
    fixes = _read("java-8-to-25-fix/references/common-build-fixes.md")
    assert "tools.jackson" in fixes and "afterburner" in fixes


def test_ehcache_integrations_are_covered_not_just_the_core_api():
    reference = _read("java-8-to-25-modify/references/legacy-library-modernization.md")
    for token in ("EhCacheCacheManager", "JCacheCacheManager", "hibernate-jcache", "ehcache-web", "jakarta.cache"):
        assert token in reference, token
    fixes = _read("java-8-to-25-fix/references/common-build-fixes.md")
    assert "EhCacheRegionFactory" in fixes and "EhCacheCacheManager" in fixes
    assert "hibernate-jcache" in _read("springboot-incremental-upgrade/references/boot3-jakarta-transition.md")


def test_google_collections_moves_to_the_newest_guava():
    reference = _read("java-8-to-25-modify/references/legacy-library-modernization.md")
    for token in ("newest `-jre` release", "guava-bom", "MoreObjects.toStringHelper",
                  "Stopwatch.createStarted()", "directExecutor", "Spring Boot does not manage Guava"):
        assert token in reference, token
    assert "newest" in _read("java-8-to-25-plan/references/java8-to-java25-checklist.md").split("| Guava |")[1]
    stage_17 = _read("java-8-to-25-plan/SKILL.md").split(f"## Stage 3: {JAVA_17}")[-1].split("## Stage 4:")[0]
    assert "newest `com.google.guava:guava`" in stage_17
    assert "toStringHelper" in _read("java-8-to-25-fix/references/common-build-fixes.md")
    # Boot's "strip managed versions" cleanup must not strip Guava's.
    assert "does **not** manage Guava" in _read("springboot-war-to-boot4/references/boot4-dependency-cleanup.md")
