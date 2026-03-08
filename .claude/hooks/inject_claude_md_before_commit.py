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

import pathlib
import sys

from helpers.deny_then_allow import read_hook_input_from_stdin
from helpers.deny_then_allow import run_deny_then_allow

MARKER_FILE_PREFIX = ".claude_md_review_pending_before_commit_session_"


def check_and_build_blocking_message() -> str | None:
    """Read CLAUDE.md and build the blocking message.

    Returns the blocking message string, or None if CLAUDE.md does not
    exist or cannot be read.
    """
    claude_md_path = pathlib.Path("CLAUDE.md")
    if not claude_md_path.is_file():
        return None
    claude_md_content = claude_md_path.read_text(encoding="utf-8")
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
    return run_deny_then_allow(
        hook_input,
        MARKER_FILE_PREFIX,
        check_and_build_blocking_message,
    )


if __name__ == "__main__":
    sys.exit(main())
