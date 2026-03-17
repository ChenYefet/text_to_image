"""Shared utility functions for parsing of hook input for Bash commands.

Provides functions used at the entry point of every pre-commit hook:
one that reads and parses the JSON input provided by Claude Code on
standard input, and one that determines whether a Bash command is a
``git commit`` invocation.
"""

import json
import re
import sys


def read_hook_input_from_standard_input() -> dict:
    """Read the JSON hook input provided by Claude Code on standard input."""
    return json.loads(sys.stdin.read())


def is_git_commit_command(command: str) -> bool:
    """Return True if the command is a git commit invocation."""
    return bool(re.search(r"\bgit\s+commit\b", command))
