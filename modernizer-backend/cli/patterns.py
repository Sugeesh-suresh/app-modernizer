"""
What each pattern runs, step by step — the Gemini CLI counterpart of the ADK
agent definitions in agents/<pattern>/agents.py.

Each entry names the skills of every role and the pattern's tools. The skill
names, the plan's skill roster (shared/rosters.py), the Java 11 fence rules and
the Java 8 -> 25 stages are imported from the same modules the ADK agents use,
so the two front ends run the same instructions.
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass, field

from agents.shared.rosters import PLAN_SKILL_ROSTERS

JAVA_8_TO_11 = "java-8-to-11"
JAVA_8_TO_25 = "java-8-to-25"
JSP_TO_REACT = "jsp-to-react-bff"
STACK_DISCOVERY = "stack-discovery"


@dataclass(frozen=True)
class Pattern:
    id: str
    label: str
    tools_module: str                       # agents.<pkg>.tools
    re_skills: tuple[str, ...]              # analysis by agent (in order)
    plan_skill: str
    modify_skills: tuple[str, ...]          # one modifier pass per skill (JSP: backend, then frontend)
    validate_skill: str
    fix_skill: str
    report_skill: str
    validator: str = ""                     # deterministic validator in tools_module ("" = build only)
    fenced: bool = False                    # writes go through the scope fence (Java 11)
    curator_skills: tuple[str, ...] = field(default=())
    validator_note: str = ""

    @property
    def roster(self) -> list[tuple[str, str]]:
        return PLAN_SKILL_ROSTERS.get(self.id, [])

    def tools(self):
        return importlib.import_module(self.tools_module)


PATTERNS: dict[str, Pattern] = {
    JAVA_8_TO_25: Pattern(
        JAVA_8_TO_25, "Java 8 → Java 25", "agents.java_8_to_25.tools",
        ("java-8-to-25-re",), "java-8-to-25-plan", ("java-8-to-25-modify",),
        "java-8-to-25-validate", "java-8-to-25-fix", "java-8-to-25-report",
        curator_skills=("java-8-to-25-re", "java-8-to-25-plan", "java-8-to-25-modify", "java-8-to-25-validate",
                        "java-8-to-25-fix", "java-8-to-25-report", "java-migration-readiness",
                        "springboot-incremental-upgrade", "springboot-war-to-boot4"),
        validator_note="Build with ws_run_command (`mvn -q -DskipTests compile`, or the Gradle equivalent).",
    ),
    JAVA_8_TO_11: Pattern(
        JAVA_8_TO_11, "Java 8 → Java 11 (JSP & WildFly preserved)", "agents.java_8_to_11.tools",
        ("java-8-to-11-re",), "java-8-to-11-plan", ("java-8-to-11-modify",),
        "java-8-to-11-validate", "java-8-to-11-fix", "java-8-to-11-report",
        validator="run_java11_build", fenced=True,
        curator_skills=("java-8-to-11-re", "java-8-to-11-re-module", "java-8-to-11-plan", "java-8-to-11-modify",
                        "java-8-to-11-validate", "java-8-to-11-fix", "java-8-to-11-report"),
        validator_note=("Call ws_validate (runs `mvn clean package` on the migration JDK and classifies every "
                        "problem) and ws_check_invariants (the scope fence) — both must pass."),
    ),
    "solr-4-to-9": Pattern(
        "solr-4-to-9", "Solr 4.x → Solr 9.x", "agents.solr_4_to_9.tools",
        ("solr-4-to-9-re",), "solr-4-to-9-plan", ("solr-4-to-9-modify",),
        "solr-4-to-9-validate", "solr-4-to-9-fix", "solr-4-to-9-report",
        validator="validate_solr_config",
        curator_skills=("solr-4-to-9-re", "solr-4-to-9-plan", "solr-4-to-9-modify", "solr-4-to-9-validate",
                        "solr-4-to-9-fix", "solr-4-to-9-report"),
        validator_note="Call ws_validate (static Solr config check: well-formedness and removed elements/classes).",
    ),
    "oracle-19c-to-23ai": Pattern(
        "oracle-19c-to-23ai", "Oracle 19c → 23ai", "agents.oracle_19c_to_23ai.tools",
        ("oracle-19c-to-23ai-re",), "oracle-19c-to-23ai-plan", ("oracle-19c-to-23ai-modify",),
        "oracle-19c-to-23ai-validate", "oracle-19c-to-23ai-fix", "oracle-19c-to-23ai-report",
        validator="validate_sql_syntax",
        curator_skills=("oracle-19c-to-23ai-re", "oracle-19c-to-23ai-plan", "oracle-19c-to-23ai-modify",
                        "oracle-19c-to-23ai-validate", "oracle-19c-to-23ai-fix", "oracle-19c-to-23ai-report"),
        validator_note="Call ws_validate (static SQL / PL/SQL check).",
    ),
    "tibco-ems-to-pubsub": Pattern(
        "tibco-ems-to-pubsub", "TIBCO EMS → Cloud Pub/Sub", "agents.tibco_ems_to_pubsub.tools",
        ("tibco-ems-to-pubsub-re",), "tibco-ems-to-pubsub-plan", ("tibco-ems-to-pubsub-modify",),
        "tibco-ems-to-pubsub-validate", "tibco-ems-to-pubsub-fix", "tibco-ems-to-pubsub-report",
        validator="validate_pubsub_mapping",
        curator_skills=("tibco-ems-to-pubsub-re", "tibco-ems-to-pubsub-plan", "tibco-ems-to-pubsub-modify",
                        "tibco-ems-to-pubsub-validate", "tibco-ems-to-pubsub-fix", "tibco-ems-to-pubsub-report"),
        validator_note=("Build with ws_run_command when there is a pom.xml/build.gradle; otherwise call "
                        "ws_validate (static Pub/Sub mapping check)."),
    ),
    JSP_TO_REACT: Pattern(
        JSP_TO_REACT, "JSP → React + BFF", "agents.jsp_to_react_bff.tools",
        ("jsp-re", "jsp-logic-classifier"), "jsp-to-react-bff-plan",
        ("spring-boot-bff-generate", "react-frontend-generate"),
        "jsp-to-react-bff-validate", "jsp-to-react-bff-fix", "jsp-to-react-bff-report",
        curator_skills=("jsp-re", "jsp-logic-classifier", "jsp-to-react-bff-plan", "spring-boot-bff-generate",
                        "react-frontend-generate", "jsp-to-react-bff-validate", "jsp-to-react-bff-fix",
                        "jsp-to-react-bff-report"),
        validator_note=("Build both trees with ws_run_command: `mvn -q -DskipTests compile` with subdir "
                        "`backend`, then `npm install` and `npm run build` with subdir `frontend`."),
    ),
}

ALL_PATTERNS = (*PATTERNS, STACK_DISCOVERY)


def get(pattern: str) -> Pattern:
    try:
        return PATTERNS[pattern]
    except KeyError:
        raise KeyError(f"Unknown migration pattern '{pattern}'. Choose one of: {', '.join(ALL_PATTERNS)}.")
