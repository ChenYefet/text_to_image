"""Pre-commit hook that injects CLAUDE.md directives and blocks the first
commit attempt per session.

This is a Claude Code PreToolUse hook for the Bash tool.  On the first
``git commit`` attempt within a session, it denies the commit and injects
the full contents of CLAUDE.md as a ``systemMessage``, giving the model
the opportunity to review staged changes against the directives and fix
any violations before re-attempting.  On the second attempt within the
same session, the hook allows the commit to proceed.

Session isolation is achieved via a marker file whose name includes the
``session_id`` from the hook input.  A marker created by a different
session is ignored and cleaned up, preventing stale markers from
allowing commits without review.

Exit code 0 -- always (output JSON controls blocking via permissionDecision).
"""

import glob
import json
import pathlib
import re
import sys

MARKER_FILE_PREFIX = ".claude_md_review_pending_before_commit_session_"


def read_hook_input_from_stdin() -> dict:
    """Read the JSON hook input provided by Claude Code on stdin."""
    return json.loads(sys.stdin.read())


def is_git_commit_command(command: str) -> bool:
    """Return True if the command is a git commit invocation."""
    return bool(re.search(r"\bgit\s+commit\b", command))


def get_marker_file_path_for_session(session_id: str) -> pathlib.Path:
    """Return the path to the session-scoped marker file."""
    return pathlib.Path(f"{MARKER_FILE_PREFIX}{session_id}")


def clean_up_stale_marker_files(current_session_id: str) -> None:
    """Remove marker files left behind by previous sessions."""
    for stale_marker_path in glob.glob(f"{MARKER_FILE_PREFIX}*"):
        if current_session_id not in stale_marker_path:
            pathlib.Path(stale_marker_path).unlink(missing_ok=True)


def read_claude_md_content() -> str | None:
    """Read the CLAUDE.md file from the repository root.

    Returns the file content as a string, or None if the file does not
    exist or cannot be read.
    """
    claude_md_path = pathlib.Path("CLAUDE.md")
    if not claude_md_path.is_file():
        return None
    return claude_md_path.read_text(encoding="utf-8")


def build_blocking_message(claude_md_content: str) -> str:
    """Build the systemMessage that denies the commit and injects
    CLAUDE.md for review.
    """
    return (
        "MANDATORY PRE-COMMIT REVIEW — COMMIT BLOCKED.\n"
        "\n"
        "This commit has been blocked to give you the opportunity to "
        "review against the CLAUDE.md directives below.\n"
        "\n"
        "1. Review all staged code changes — including commit "
        "composition, version references, refactoring verification, "
        "and changelog updates — against each applicable directive.\n"
        "\n"
        "2. Review the commit message separately.  The commit message "
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
        "re-attempt the commit unchanged — it will be allowed on the "
        "second attempt.\n"
        "\n"
        "--- CLAUDE.md BEGIN ---\n"
        f"{claude_md_content}\n"
        "--- CLAUDE.md END ---"
    )


def main() -> int:
    hook_input = read_hook_input_from_stdin()

    tool_input = hook_input.get("tool_input", {})
    command = tool_input.get("command", "")

    # Fast path: Not a git commit command.
    if not is_git_commit_command(command):
        return 0

    session_id = hook_input.get("session_id", "")
    if not session_id:
        # If no session ID is available, fall back to non-blocking
        # injection to avoid permanently blocking commits.
        claude_md_content = read_claude_md_content()
        if claude_md_content is not None:
            output = {
                "hookSpecificOutput": {
                    "permissionDecision": "allow",
                },
                "systemMessage": build_blocking_message(claude_md_content),
            }
            print(json.dumps(output))
        return 0

    clean_up_stale_marker_files(session_id)

    marker_file_path = get_marker_file_path_for_session(session_id)

    if marker_file_path.exists():
        # Second attempt within this session: allow the commit and
        # remove the marker so the next commit in this session is
        # also reviewed.
        marker_file_path.unlink(missing_ok=True)
        return 0

    # First attempt within this session: block the commit, create
    # the marker, and inject CLAUDE.md for review.
    claude_md_content = read_claude_md_content()
    if claude_md_content is None:
        return 0

    marker_file_path.touch()

    message = build_blocking_message(claude_md_content)
    output = {
        "hookSpecificOutput": {
            "permissionDecision": "deny",
        },
        "systemMessage": message,
    }
    print(json.dumps(output))

    return 0


if __name__ == "__main__":
    sys.exit(main())
