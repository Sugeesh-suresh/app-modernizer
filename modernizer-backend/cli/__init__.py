"""
The Stella Modernizer, driven from Gemini CLI instead of the ADK pipeline.

The web app (main.py) runs every pattern as Google ADK agents behind FastAPI.
This package runs the same patterns from a Gemini CLI session, with no ADK and
no server:

- the **skills** are the same files (agents/skills/*/SKILL.md), loaded by Gemini
  CLI's own skill support;
- the **agents** are Gemini CLI subagents (gemini-cli/agents/*.md), one per role;
- the **deterministic tools** — inventories, dependency graph, scope fence,
  validators, change audit, plan checks, discovery's computed sections — are the
  same Python functions, served to Gemini CLI by an MCP server (mcp_server.py);
- the **pipeline** (which step runs next, with which skill and which inputs) is
  a state machine (pipeline.py) whose state lives in the repository's
  `.modernizer/` folder, so a run survives restarting the CLI.

The human review gates stay where they are: nothing is planned before the
analysis is confirmed (when it came from an agent), and nothing is changed
before the plan is approved.
"""
