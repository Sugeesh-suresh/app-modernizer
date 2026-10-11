"""
The Java 8 -> 25 "incremental" strategy's stages, in strict order.

Kept free of ADK imports so the Gemini CLI path (cli/) runs the same stages,
with the same guardrails, as the web pipeline (agents/java_8_to_25/agents.py).
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class IncrementalStage:
    """One staged modifier+build_loop pass of the "incremental" strategy."""
    # Stable id (runner key, agent names, state keys). The step number users and the
    # plan see is the stage's position in the run, which differs when Spring Boot
    # stages are skipped -- so the plan section is matched by `title`, not by number.
    idx: int
    phase: int
    phase_title: str
    title: str
    # Compiler release level the build must target once this stage is applied.
    java_release: str
    # Framework stage: only runs when the user requested a Spring Boot upgrade.
    springboot: bool
    # Stage guides (steps of the java-8-to-25 skill) this stage's modifier follows alongside its modify step.
    extra_skills: tuple[str, ...]
    # What this stage must NOT do yet -- later stages own those changes.
    guardrail: str
    # Build goal the validator runs ("compile", or "package" when the artifact itself changes).
    build_goal: str = "compile"


_KEEP_FRAMEWORK = (
    "Do not change the Spring / Spring Boot version, the `javax`/`jakarta` namespace, or the "
    "packaging — those belong to the Spring Boot stages (when requested)."
)

# Same rule for the JDK stages, minus the Spring Framework version: see _SPRING_FLOOR_* below.
# Stage 3 can forbid the Jakarta rename outright, because Spring 5.3 is still `javax` and nothing
# at that stage needs it. Stage 6 cannot: when no Spring Boot upgrade was requested, Spring 6 is
# the only way onto Java 25 and Spring 6 IS `jakarta`, so the rename has to happen there. Stating
# both the blanket prohibition and the requirement in one prompt made the stage unactionable.
_KEEP_BOOT_17 = (
    "Do not change the Spring Boot version or the packaging, and do not rename Jakarta EE `javax.*` "
    "packages — those belong to the Spring Boot stages (when requested)."
)
_KEEP_BOOT_25 = (
    "Do not change the Spring Boot version or the packaging."
)

# A JDK stage cannot leave the framework behind: old Spring/Hibernate lines bundle an ASM that
# refuses newer class files, so they fail at context startup on the JDK this stage targets rather
# than at compile time. Each JDK stage therefore owns the framework floor its release requires.
_SPRING_FLOOR_17 = (
    "The one framework change this stage owns: if the app is on plain Spring Framework 3.x/4.x, "
    "raise every `org.springframework:spring-*` artifact to the newest 5.3.x (still `javax`, "
    "supports Java 8-21) — older Spring cannot read Java 17 class files — and rewrite "
    "`org.springframework.orm.hibernate3.*` (removed in Spring 5) onto `hibernate5` alongside a "
    "Hibernate 5.6.x bump. Never go past Spring 5.3 here."
)
_SPRING_FLOOR_25 = (
    "The Jakarta EE namespace is decided by which of these two cases the app is in, and exactly one "
    "of them applies:\n"
    "  (a) The app is Spring Boot-managed (a Spring Boot upgrade was requested, so the Spring Boot "
    "3.x stage already ran). Leave the framework version alone and do NOT rename anything — that "
    "stage already moved `javax.*` to `jakarta.*`.\n"
    "  (b) The app is on plain Spring Framework 5.3 because no Spring Boot upgrade was requested. "
    "Raise it to Spring 6.x — 5.3 does not support Java 25 — and because Spring 6 is built on "
    "Jakarta EE, the `javax.*` → `jakarta.*` rename MUST happen in this stage. It is this stage's "
    "work, not a later one's; there is no later one. Rename every Jakarta EE package and never the "
    "Java SE `javax.sql`, `javax.naming`, `javax.crypto` or JAXP packages.\n"
    "Never leave a Spring 5.3 application compiled at release 25, and never revert Spring to 5.3 to "
    "make the build pass."
)

# The "incremental" strategy, in strict order. JDK and Spring Boot stages interleave so
# every stage lands on a supported combination: Spring Boot 2.7 (Java 8-21) and 3.x
# (Java 17+) are done on Java 17, before the Java 25 jump; Spring Boot 4 comes after it.
INCREMENTAL_STAGES: list[IncrementalStage] = [
    IncrementalStage(
        1, 1, "Readiness", "Modernize Build Systems (Maven/Gradle)", "8", False,
        ("java-8-to-25:readiness",),
        "Keep the compiler release at 8 and do not touch application source code. Test-scoped "
        "dependencies and the test plugins are the one exception: the test stack (Mockito 1.x → "
        "`mockito-core` 4.11.0, JUnit 4.13.2, surefire/failsafe 3.2.5+) is modernised here as the "
        "migration's safety net. " + _KEEP_FRAMEWORK,
    ),
    IncrementalStage(
        2, 1, "Readiness", "Automate Code Analysis (OpenRewrite)", "8", False,
        ("java-8-to-25:readiness",),
        "Only add OpenRewrite configuration — never wire it to run during the normal build, and do not "
        "apply recipe changes to source files, change the compiler release, or touch application code.",
    ),
    IncrementalStage(
        3, 2, "Java 17 Baseline", "Java 8 → Java 17 LTS", "17", False, (),
        "Set the compiler release to exactly 17, not further. " + _KEEP_BOOT_17 + " " + _SPRING_FLOOR_17,
    ),
    IncrementalStage(
        4, 2, "Java 17 Baseline", "Upgrade to Spring Boot 2.7 (WAR intact)", "17", True,
        ("java-8-to-25:springboot-incremental",),
        "Keep the compiler release at 17, keep `<packaging>war</packaging>`, and keep every `javax.*` "
        "import (Spring Boot 2.7 is still Java EE 8 / javax based) — the jakarta transition is the "
        "next Spring Boot stage.",
    ),
    IncrementalStage(
        5, 3, "Java 25 Baseline", "Upgrade to Spring Boot 3.x (Jakarta namespace transition)", "17", True,
        ("java-8-to-25:springboot-incremental",),
        "Keep the compiler release at 17 (the Java 25 upgrade is the next stage), keep "
        "`<packaging>war</packaging>`, and stay on Spring Boot 3.x — Spring Boot 4 is a later stage. "
        "Never rename Java SE `javax.*` packages (`javax.sql`, `javax.naming`, `javax.crypto`, ...).",
    ),
    IncrementalStage(
        6, 3, "Java 25 Baseline", "Java 17 → Java 25 LTS", "25", False, (),
        "Set the compiler release to exactly 25. " + _KEEP_BOOT_25 + " " + _SPRING_FLOOR_25,
    ),
    IncrementalStage(
        7, 4, "Spring Boot 4 & Cloud Native", "Upgrade to Spring Boot 4.x", "25", True,
        ("java-8-to-25:springboot-boot4", "java-8-to-25:springboot-incremental"),
        "Keep `<packaging>war</packaging>` and the JSP views (with their JSP libraries) in this stage — "
        "the executable JAR conversion and JSP → Thymeleaf are the next stage.",
    ),
    IncrementalStage(
        8, 4, "Spring Boot 4 & Cloud Native", "Convert WAR → Executable JAR (Embedded Container)", "25", True,
        ("java-8-to-25:springboot-boot4", "java-8-to-25:springboot-incremental"),
        "Do not change the Java or Spring Boot versions — this stage only changes the packaging and "
        "deployment model and converts JSP views to Thymeleaf. The result must be an executable JAR, "
        "never a WAR.",
        build_goal="package",
    ),
]


def incremental_stages(springboot_upgrade: bool) -> list[IncrementalStage]:
    """The stages an incremental run actually executes for this session's options, in
    order. A stage's displayed step number is its 1-based position in this list."""
    return [s for s in INCREMENTAL_STAGES if springboot_upgrade or not s.springboot]
