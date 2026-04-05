"""Pre-commit hook that requires CLAUDE.md to be read right before allowing
a commit.

This is a Claude Code PreToolUse hook for the Bash tool.  On every
``git commit`` attempt, it checks for a session-scoped marker file
created by the PostToolUse hook ``track_reading_of_claude_md.py``,
which fires when the Read tool is used on CLAUDE.md.  If the marker
exists, the commit is allowed and the marker is consumed so that the
next commit requires a fresh read.  If the marker does not exist, the
commit is denied with a message instructing the model to read CLAUDE.md
before re-attempting.

Session isolation is achieved via a marker file whose name includes the
``session_id`` from the hook input.  A marker created by a different
session is ignored and cleaned up, preventing stale markers from
allowing commits without review.

Exit code 0 — always (output JSON controls blocking via permissionDecision).
"""

import json
import pathlib
import sys

from helpers.management_of_session_marker_files import (
    PREFIX_OF_MARKER_FILE_FOR_COMMIT_PERMITTED_AFTER_READING_OF_CLAUDE_MD,
    clean_up_stale_marker_files,
    get_marker_file_path_for_session,
    is_command_for_git_rebase_with_abort,
)
from helpers.parsing_of_hook_input_for_bash_commands import (
    is_git_subcommand,
    read_hook_input_from_standard_input,
)


def main() -> int:
    hook_input = read_hook_input_from_standard_input()
    tool_input = hook_input.get("tool_input", {})
    command = tool_input.get("command", "")
    session_id = hook_input.get("session_id", "")

    # Clean up read-marker when a rebase is aborted — any markers
    # created during the aborted rebase are stale.
    if session_id and is_command_for_git_rebase_with_abort(command):
        get_marker_file_path_for_session(
            PREFIX_OF_MARKER_FILE_FOR_COMMIT_PERMITTED_AFTER_READING_OF_CLAUDE_MD,
            session_id,
        ).unlink(missing_ok=True)
        return 0

    # Only gate git commit commands.
    if not is_git_subcommand(command, "commit"):
        return 0

    # Without a session ID, the marker mechanism cannot work — allow.
    if not session_id:
        return 0

    # If CLAUDE.md does not exist, no review is required.
    if not pathlib.Path("CLAUDE.md").is_file():
        return 0

    clean_up_stale_marker_files(
        PREFIX_OF_MARKER_FILE_FOR_COMMIT_PERMITTED_AFTER_READING_OF_CLAUDE_MD,
        session_id,
    )

    # Check for the read-marker created by track_reading_of_claude_md.py.
    read_marker_path = get_marker_file_path_for_session(
        PREFIX_OF_MARKER_FILE_FOR_COMMIT_PERMITTED_AFTER_READING_OF_CLAUDE_MD,
        session_id,
    )
    if read_marker_path.exists():
        read_marker_path.unlink(missing_ok=True)
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "permissionDecisionReason": "CLAUDE.md was read right before this commit — commit permitted.",
            },
        }
        print(json.dumps(output))
        return 0

    # CLAUDE.md has not been read right before this commit — deny.
    message = (
        "MANDATORY PRE-COMMIT REVIEW — COMMIT BLOCKED.\n"
        "\n"
        "This commit has been blocked because CLAUDE.md has not been "
        "read right before this commit.\n"
        "\n"
        "Before re-attempting the commit:\n"
        "\n"
        "1. Read CLAUDE.md in full using the Read tool.\n"
        "\n"
        "2. Review all staged code changes — including commit "
        "composition, version references, refactoring verification, "
        "and changelog updates — against each applicable directive.\n"
        "\n"
        "3. Review the commit message separately.\n"
        "\n"
        "If any directive is violated in either the staged changes or "
        "the commit message, fix the violation and restage before "
        "re-attempting the commit.  If all directives are satisfied, "
        "re-attempt the commit — it will be allowed once CLAUDE.md "
        "has been read."
    )

    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": message,
        },
    }
    print(json.dumps(output))
    return 0


if __name__ == "__main__":
    sys.exit(main())
