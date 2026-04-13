"""PostToolUse hook that creates and consumes the marker for reading of
CLAUDE.md.

This is a Claude Code PostToolUse hook registered for both the Read
tool and the Bash tool.  It performs two lifecycle operations on the
marker file used by ``inject_claude_md_before_commit.py`` to gate
commits on a fresh read of CLAUDE.md:

1. **Creation** (PostToolUse on Read): When the Read tool is used on a
   file named ``CLAUDE.md``, this hook creates the marker file.

2. **Consumption** (PostToolUse on Bash): When the Bash tool executes
   a ``git commit`` command, this hook deletes the marker file so that
   the next commit requires a fresh read.

Consumption happens in PostToolUse (after the commit executes) rather
than in the PreToolUse check in ``inject_claude_md_before_commit.py``
(before the commit executes) to prevent a denied commit — one blocked
by another PreToolUse hook — from invalidating the marker.  If any
PreToolUse hook denies the commit, the Bash tool never executes,
PostToolUse does not fire, and the marker persists for the next
attempt.

The marker file is scoped to the session via the ``session_id`` from
the hook input.

Exit code 0 — always.
"""

import json
import pathlib
import sys

from helpers.management_of_session_marker_files import (
    PREFIX_OF_MARKER_FILE_FOR_COMMIT_PERMITTED_AFTER_READING_OF_CLAUDE_MD,
    get_marker_file_path_for_session,
)
from helpers.parsing_of_hook_input_for_bash_commands import is_git_subcommand


def main() -> int:
    hook_input = json.loads(sys.stdin.read())
    session_id = hook_input.get("session_id", "")
    if not session_id:
        return 0

    tool_input = hook_input.get("tool_input", {})

    # PostToolUse on Read: create marker when CLAUDE.md is read.
    file_path = tool_input.get("file_path", "")
    if file_path and pathlib.Path(file_path).name == "CLAUDE.md":
        marker_file_path = get_marker_file_path_for_session(
            PREFIX_OF_MARKER_FILE_FOR_COMMIT_PERMITTED_AFTER_READING_OF_CLAUDE_MD,
            session_id,
        )
        marker_file_path.touch()
        return 0

    # PostToolUse on Bash: consume marker when git commit executes.
    command = tool_input.get("command", "")
    if command and is_git_subcommand(command, "commit"):
        marker_file_path = get_marker_file_path_for_session(
            PREFIX_OF_MARKER_FILE_FOR_COMMIT_PERMITTED_AFTER_READING_OF_CLAUDE_MD,
            session_id,
        )
        marker_file_path.unlink(missing_ok=True)
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
