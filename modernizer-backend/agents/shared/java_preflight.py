"""
The Java patterns' environment checks (preflights), chosen by pattern, and
their report at the top of the Technical Specification the planner reads.

  java-8-to-11  agents/java_8_to_11/preflight.py — one JDK (11), baseline build on it
  java-8-to-25  agents/java_8_to_25/preflight.py — one JDK per stage release, baseline on the first
"""
import json

_HEADINGS = {"java-8-to-11": "## Baseline Build on JDK 11",
             "java-8-to-25": "## Build Environment and Baseline Build"}


def module_for(pattern: str):
    """The preflight module of `pattern`, or None when it has none."""
    if pattern == "java-8-to-11":
        from ..java_8_to_11 import preflight
        return preflight
    if pattern == "java-8-to-25":
        from ..java_8_to_25 import preflight
        return preflight
    return None


def run(pattern: str, workspace_dir: str, strategy: str = "bigbang", springboot_upgrade: bool = False):
    module = module_for(pattern)
    if pattern == "java-8-to-25":
        return module.run(workspace_dir, strategy or "bigbang", springboot_upgrade)
    return module.run(workspace_dir)


def with_preflight(tech_spec: str, pattern: str, preflight_json: str) -> str:
    """The preflight's report prepended to `pattern`'s Technical Specification (once)."""
    module = module_for(pattern)
    if not module or not preflight_json or _HEADINGS[pattern] in tech_spec:
        return tech_spec
    try:
        pf = module.Preflight(**json.loads(preflight_json))
    except (TypeError, json.JSONDecodeError):
        return tech_spec
    return module.to_markdown(pf) + "\n\n" + tech_spec
