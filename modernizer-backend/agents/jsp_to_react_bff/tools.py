"""
Workspace tools for the JSP -> React + BFF pattern.

Unlike the other 3 real-toolchain patterns, this pipeline doesn't modify
the source JSP files in place — it reads them as reference material and
writes an entirely new decoupled architecture into two fresh subtrees of
the same workspace: `backend/` (the Spring Boot 4 BFF, packaged as a
standalone JAR) and `frontend/` (the React app). `run_command`'s `subdir`
parameter (see agents/shared/workspace_tools.py) is what lets the
validator build each tree independently — `mvn compile` in `backend/`,
`npm run build` in `frontend/`.
"""
from ..shared.workspace_tools import (
    list_files,
    make_run_command,
    read_file,
    replace_in_file,
    signal_build_success,
    write_file,
)

run_command = make_run_command({
    # Backend (Spring Boot 4 BFF, JAR)
    "mvn", "mvnw", "./mvnw", "gradle", "gradlew", "./gradlew", "javac", "java",
    # Frontend (React)
    "npm", "npx", "node", "tsc",
})

__all__ = ["list_files", "read_file", "replace_in_file", "write_file", "run_command", "signal_build_success"]
