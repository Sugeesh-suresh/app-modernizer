"""
Thin wrapper around the shared workspace tools, configured for the Java
toolchain (mvn/gradle/javac allowed). Builds run on the JDK assigned to the
current stage's Java release, with MAVEN_SETTINGS (preflight.stage_env).
"""
from ..shared import java_env
from ..shared.workspace_tools import (
    delete_file,
    list_files,
    make_run_command,
    read_file,
    replace_in_file,
    signal_build_success,
    write_file,
)

from .preflight import stage_env

run_command = make_run_command({"mvn", "mvnw", "./mvnw", "gradle", "gradlew", "./gradlew", "javac", "java"},
                               env_factory=stage_env, extra_args=java_env.maven_settings_args)

__all__ = ["delete_file", "list_files", "read_file", "replace_in_file", "write_file", "run_command", "signal_build_success"]
