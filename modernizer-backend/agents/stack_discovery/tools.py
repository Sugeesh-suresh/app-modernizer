"""
Workspace tools for the stack-discovery pattern.

Read-only by design. This pattern never modifies the repository: it maps the
stacks present and reverse-engineers each one into a document. There is no
modifier, no build loop and therefore no `run_command`, `write_file` or
`replace_in_file` — the uploaded workspace is reference material from the first
agent to the last.
"""
from ..shared.workspace_tools import list_files, read_file, search_files

__all__ = ["list_files", "read_file", "search_files"]
