"""Pre-commit hook that requires CLAUDE.md to be read before allowing
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

import glob
import json
import pathlib
import re
import sys

from helpers.parsing_of_hook_input_for_bash_commands import (
    is_git_subcommand,
    read_hook_input_from_standard_input,
)

PREFIX_OF_MARKER_FILE = ".marker_file_for_commit_permitted_after_reading_of_claude_md_for_session_"


def _is_command_for_git_rebase_with_abort(command: str) -> bool:
    """Return True if *command* contains a ``git rebase --abort``."""
    if not is_git_subcommand(command, "rebase"):
        return False
    return bool(re.search(r"--abort\b", command))


def _clean_up_stale_marker_files(current_session_id: str) -> None:
    """Remove read-marker files left behind by previous sessions."""
    for stale_marker_path in glob.glob(
        f"{PREFIX_OF_MARKER_FILE}*"
    ):
        if current_session_id not in stale_marker_path:
            pathlib.Path(stale_marker_path).unlink(missing_ok=True)


def main() -> int:
    hook_input = read_hook_input_from_standard_input()
    tool_input = hook_input.get("tool_input", {})
    command = tool_input.get("command", "")
    session_id = hook_input.get("session_id", "")

    # Clean up read-marker when a rebase is aborted — any markers
    # created during the aborted rebase are stale.
    if session_id and _is_command_for_git_rebase_with_abort(command):
        for marker_path in glob.glob(
            f"{PREFIX_OF_MARKER_FILE}{session_id}"
        ):
            pathlib.Path(marker_path).unlink(missing_ok=True)
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

    _clean_up_stale_marker_files(session_id)

    # Check for the read-marker created by track_reading_of_claude_md.py.
    read_marker_path = pathlib.Path(
        f"{PREFIX_OF_MARKER_FILE}{session_id}"
    )
    if read_marker_path.exists():
        read_marker_path.unlink(missing_ok=True)
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
        "3. Review the commit message separately.  The commit message "
        "is prose and is subject to the same naming, connector, and "
        "no-abbreviation rules as all other text.  Verify that every "
        "noun phrase in the commit message complies with the CLAUDE.md "
        "naming rules — including the requirement that modifiers "
        "attach to a named head noun rather than standing alone as "
        "shorthand.\n"
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
