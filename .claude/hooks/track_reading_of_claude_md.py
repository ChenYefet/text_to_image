"""PostToolUse hook that records when CLAUDE.md is read.

This is a Claude Code PostToolUse hook for the Read tool.  When the
Read tool is used on a file named ``CLAUDE.md``, this hook creates a
session-scoped marker file.  The pre-commit hook
``inject_claude_md_before_commit.py`` checks for this marker right before
allowing a ``git commit`` command, ensuring that the CLAUDE.md
directives have been freshly read into the model's context before the
commit review.

The marker is consumed (deleted) by the pre-commit hook when a commit
is allowed, so each commit requires a fresh read of CLAUDE.md.

Exit code 0 — always.
"""

import json
import pathlib
import sys

from helpers.management_of_session_marker_files import (
    PREFIX_OF_MARKER_FILE_FOR_COMMIT_PERMITTED_AFTER_READING_OF_CLAUDE_MD,
    get_marker_file_path_for_session,
)


def main() -> int:
    hook_input = json.loads(sys.stdin.read())
    session_id = hook_input.get("session_id", "")
    if not session_id:
        return 0

    tool_input = hook_input.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    if not file_path or pathlib.Path(file_path).name != "CLAUDE.md":
        return 0

    marker_file_path = get_marker_file_path_for_session(
        PREFIX_OF_MARKER_FILE_FOR_COMMIT_PERMITTED_AFTER_READING_OF_CLAUDE_MD,
        session_id,
    )
    marker_file_path.touch()

    return 0


if __name__ == "__main__":
    sys.exit(main())
