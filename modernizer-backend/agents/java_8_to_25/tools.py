"""
Thin wrapper around the shared workspace tools, configured for the Java
toolchain (mvn/gradle/javac allowed).
"""
from ..shared.workspace_tools import (
    list_files,
    make_run_command,
    read_file,
    replace_in_file,
    signal_build_success,
    write_file,
)

run_command = make_run_command({"mvn", "mvnw", "./mvnw", "gradle", "gradlew", "./gradlew", "javac", "java"})

__all__ = ["list_files", "read_file", "replace_in_file", "write_file", "run_command", "signal_build_success"]
