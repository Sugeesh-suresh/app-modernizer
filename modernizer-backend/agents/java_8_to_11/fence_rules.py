"""
The Java 8 -> 11 plan's stage title and the scope-fence rules every writing
agent is told. ADK-free, so the Gemini CLI path (cli/) gives its subagents the
same words as the web pipeline (agents/java_8_to_11/agents.py).
"""

#: The plan's one stage heading. main.py splits the plan into tasks under it, so
#: the planner skill must emit this title character for character.
STAGE_TITLE = "Java 8 → Java 11"

#: The rules every writing agent is held to, stated once so the modifier and the
#: fixer cannot drift apart. The tools enforce them regardless; stating them
#: saves the agent the refused call.
FENCE_RULES = (
    "Scope fence — enforced by your write tools, which refuse anything outside it:\n"
    "- Only `.java` sources and build files (pom.xml, build.gradle[.kts], settings.gradle, "
    "gradle.properties, Maven/Gradle wrapper properties) may change.\n"
    "- JSP (.jsp/.jspf/.tag/.tld), everything under src/main/webapp, WEB-INF and META-INF, web.xml, "
    "every WildFly/JBoss descriptor (jboss-*.xml, standalone*.xml, *-ds.xml, module.xml, *.cli) and "
    "container launch configuration (standalone.conf, Dockerfile) are FROZEN.\n"
    "- In build files: `<packaging>`, `<finalName>`, WildFly/JBoss deployment plugins and the "
    "maven-war-plugin configuration stay exactly as they are (the WAR plugin's version alone may "
    "move); the Java level is exactly 11, never higher; Spring Boot is never introduced.\n"
    "- The Java EE namespace stays `javax.*` — never add a `jakarta.*` import.\n"
    "- A dependency the WildFly container supplies (scope `provided`, or listed in "
    "jboss-deployment-structure.xml) keeps its version: WildFly supplies it at runtime, not the WAR.\n"
    "If the Java 11 upgrade genuinely cannot be completed inside the fence, stop and say exactly "
    "what and why in your summary — never work around a refusal."
)
