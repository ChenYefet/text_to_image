"""Shared logic for the deny-then-allow pattern in pre-commit hooks.

Provides a reusable function that implements the session-scoped
deny-then-allow pattern: on the first ``git commit`` attempt within a
session, the hook runs a caller-provided check; if the check produces a
blocking message, the commit is denied and the message is injected as a
``systemMessage``.  On the second attempt within the same session, the
commit is allowed unconditionally — this ensures that false positives
from non-deterministic checks never permanently block a commit.

Session isolation is achieved via a marker file whose name includes the
``session_id`` from the hook input.  A marker created by a different
session is ignored and cleaned up, preventing stale markers from
allowing commits without review.
"""

import glob
import json
import pathlib
from collections.abc import Callable

from helpers.parsing_of_hook_input_for_bash_commands import is_git_commit_command


def _get_marker_file_path_for_session(
    marker_file_prefix: str,
    session_id: str,
) -> pathlib.Path:
    """Return the path to the session-scoped marker file."""
    return pathlib.Path(f"{marker_file_prefix}{session_id}")


def _clean_up_stale_marker_files(
    marker_file_prefix: str,
    current_session_id: str,
) -> None:
    """Remove marker files left behind by previous sessions."""
    for stale_marker_path in glob.glob(f"{marker_file_prefix}*"):
        if current_session_id not in stale_marker_path:
            pathlib.Path(stale_marker_path).unlink(missing_ok=True)


def run_deny_then_allow(
    hook_input: dict,
    marker_file_prefix: str,
    check_and_build_blocking_message: Callable[[], str | None],
) -> int:
    """Execute the deny-then-allow pattern for a pre-commit hook.

    On the first ``git commit`` attempt within a session, this function
    calls ``check_and_build_blocking_message``.  If the callable returns
    a message string, the commit is denied and the message is injected
    as a ``systemMessage``.  A session-scoped marker file is created so
    that the second attempt is allowed unconditionally.

    If no session ID is available in the hook input, the check is still
    run but any message is reported as an advisory ``systemMessage``
    without blocking — because without a session ID the marker file
    mechanism cannot guarantee the second attempt will be allowed.

    Parameters:
        hook_input: The JSON hook input from Claude Code stdin.
        marker_file_prefix: A unique prefix for this hook's marker
            files.  Must be different for each hook to avoid collisions.
        check_and_build_blocking_message: A callable that performs the
            hook-specific check and returns a blocking message string
            if the commit should be blocked, or None if it should be
            allowed.

    Returns 0 always (output JSON on stdout controls blocking via
    ``permissionDecision``).
    """
    tool_input = hook_input.get("tool_input", {})
    command = tool_input.get("command", "")

    # Fast path: not a git commit command.
    if not is_git_commit_command(command):
        return 0

    session_id = hook_input.get("session_id", "")
    if not session_id:
        # No session ID: run the check but report as advisory only,
        # to avoid permanently blocking commits.
        message = check_and_build_blocking_message()
        if message is not None:
            output = {"systemMessage": message}
            print(json.dumps(output))
        return 0

    _clean_up_stale_marker_files(marker_file_prefix, session_id)

    marker_file_path = _get_marker_file_path_for_session(
        marker_file_prefix, session_id
    )

    if marker_file_path.exists():
        # Second attempt within this session: allow the commit and
        # remove the marker so the next commit in this session is
        # also checked.
        marker_file_path.unlink(missing_ok=True)
        return 0

    # First attempt within this session: run the check.
    message = check_and_build_blocking_message()
    if message is None:
        return 0

    # Check produced a blocking message: create the marker so the
    # second attempt is allowed, then deny this attempt.
    marker_file_path.touch()

    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": message,
        },
    }
    print(json.dumps(output))

    return 0
