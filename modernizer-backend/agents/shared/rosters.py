"""
Each migration pattern's skill roster: the skills that govern a run, in the order
they run, with the role each plays. The planner reproduces it verbatim as the
plan's Skill Composition table (shared/skill_manifest.py).

One definition for both front ends: the ADK agents (agents/<pattern>/agents.py)
and the Gemini CLI path (cli/) read it from here, so the two cannot drift.
"""

PLAN_SKILL_ROSTERS: dict[str, list[tuple[str, str]]] = {
    "java-8-to-11": [
        ("java-8-to-11-re-module", "Analysed the repository unit by unit (module, or part of one) into Module Findings"),
        ("java-8-to-11-re", "Combined the Module Findings into the confirmed BRD, Technical Specification and Test Inventory"),
        ("java-8-to-11-plan", "Produces this plan"),
        ("java-8-to-11-modify", "Applies each task's `.java` and build-file changes, inside the scope fence"),
        ("java-8-to-11-validate", "Packages the WAR at release 11 and checks the scope-fence invariants"),
        ("java-8-to-11-fix", "Repairs build and invariant failures inside the loop, inside the scope fence"),
        ("code-review", "Independent review of the result against this plan's manifest"),
        ("java-8-to-11-report", "Produces the final migration report"),
    ],
    "java-8-to-25": [
        ("java-8-to-25-re", "Reverse-engineered this repository into the confirmed BRD, Technical Specification and Test Inventory"),
        ("java-8-to-25-plan", "Produces this plan"),
        ("java-migration-readiness", "Incremental only — Stages 1-2: build modernisation, the test-stack safety net and OpenRewrite setup"),
        ("springboot-incremental-upgrade", "Incremental only, and only when a Spring Boot upgrade was requested — Stages 4-5: Spring Boot 2.7, then 3.x with the Jakarta rename"),
        ("springboot-war-to-boot4", "Only when a Spring Boot upgrade was requested — the Spring Boot 4.x target and the WAR to executable-JAR conversion"),
        ("java-8-to-25-modify", "Applies each task's file changes to the workspace"),
        ("java-8-to-25-validate", "Compiles (and packages) the workspace after each stage"),
        ("java-8-to-25-fix", "Repairs build errors inside the build loop"),
        ("code-review", "Independent review of the result against this plan's manifest"),
        ("java-8-to-25-report", "Produces the final migration report"),
    ],
    "jsp-to-react-bff": [
        ("jsp-re", "Extracted the verifiable facts of the JSP application that the Analysis, BRD, Technical Specification and Test Inventory were built from"),
        ("jsp-logic-classifier", "Classified each JSP's logic as client-side or server-side"),
        ("jsp-to-react-bff-plan", "Produces this plan"),
        ("spring-boot-bff-generate", "Generates the Spring Boot 4 BFF tree"),
        ("react-frontend-generate", "Generates the React frontend tree"),
        ("jsp-to-react-bff-validate", "Builds both generated trees after each pass"),
        ("jsp-to-react-bff-fix", "Repairs build errors inside the loop"),
        ("code-review", "Independent review of the result against this plan's manifests"),
        ("jsp-to-react-bff-report", "Produces the final migration report"),
    ],
    "oracle-19c-to-23ai": [
        ("oracle-19c-to-23ai-re", "Reverse-engineered this repository into the confirmed BRD, Technical Specification and Test Inventory"),
        ("oracle-19c-to-23ai-plan", "Produces this plan"),
        ("oracle-19c-to-23ai-modify", "Applies the plan's file changes to the workspace"),
        ("oracle-19c-to-23ai-validate", "Validates the migrated SQL/PLSQL after each pass"),
        ("oracle-19c-to-23ai-fix", "Repairs validation errors inside the loop"),
        ("code-review", "Independent review of the result against this plan's manifest"),
        ("oracle-19c-to-23ai-report", "Produces the final migration report"),
    ],
    "solr-4-to-9": [
        ("solr-4-to-9-re", "Reverse-engineered this repository into the confirmed BRD, Technical Specification and Test Inventory"),
        ("solr-4-to-9-plan", "Produces this plan"),
        ("solr-4-to-9-modify", "Applies the plan's file changes to the workspace"),
        ("solr-4-to-9-validate", "Validates the migrated schema and config after each pass"),
        ("solr-4-to-9-fix", "Repairs validation errors inside the loop"),
        ("code-review", "Independent review of the result against this plan's manifest"),
        ("solr-4-to-9-report", "Produces the final migration report"),
    ],
    "tibco-ems-to-pubsub": [
        ("tibco-ems-to-pubsub-re", "Reverse-engineered this repository into the confirmed BRD, Technical Specification and Test Inventory"),
        ("tibco-ems-to-pubsub-plan", "Produces this plan"),
        ("tibco-ems-to-pubsub-modify", "Applies the plan's file changes to the workspace"),
        ("tibco-ems-to-pubsub-validate", "Validates the migrated client code and config after each pass"),
        ("tibco-ems-to-pubsub-fix", "Repairs validation errors inside the loop"),
        ("code-review", "Independent review of the result against this plan's manifest"),
        ("tibco-ems-to-pubsub-report", "Produces the final migration report"),
    ],
}
