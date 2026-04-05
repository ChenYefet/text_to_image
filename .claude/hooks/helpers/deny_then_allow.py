"""Shared logic for the deny-then-allow pattern in PreToolUse hooks.

Provides reusable functions that implement the session-scoped
deny-then-allow pattern: on the first triggering invocation within a
session, the hook runs a caller-provided check; if the check produces a
blocking message, the tool call is denied and the message is injected as
a ``systemMessage``.  On the second attempt within the same session, the
call is allowed unconditionally — this ensures that false positives from
non-deterministic checks never permanently block a tool call.

Two public entry points are provided:

- ``run_deny_then_allow`` — gates on ``git commit`` commands (and
  optionally on additional commit-affecting git commands supplied by the
  caller).  Use this for pre-commit hooks.
- ``run_deny_then_allow_on_bash_command`` — applies the deny-then-allow
  check to every Bash tool invocation without filtering by subcommand.
  Use this for hooks that must check arbitrary shell commands rather
  than only git commits.

Both entry points also detect ``git rebase --abort`` commands and clean
up all marker files for the current session before allowing the command.
A ``git rebase --abort`` discards the in-progress rebase, invalidating
any marker files that were created by denied commits during that rebase;
without cleanup, those stale markers would cause the next commit to be
allowed unconditionally without review.

Session isolation is achieved via a marker file whose name includes the
``session_id`` from the hook input.  A marker created by a different
session is ignored and cleaned up, preventing stale markers from
allowing calls without review.
"""

import json
from collections.abc import Callable

from helpers.management_of_session_marker_files import (
    clean_up_all_marker_files_for_current_session,
    clean_up_stale_marker_files,
    get_marker_file_path_for_session,
    is_command_for_git_rebase_with_abort,
)
from helpers.parsing_of_hook_input_for_bash_commands import is_git_subcommand


def _run_core_logic_of_deny_then_allow(
    hook_input: dict,
    prefix_of_marker_file: str,
    check_and_build_blocking_message: Callable[[], str | None],
) -> int:
    """Execute the session-scoped marker-file deny-then-allow logic.

    This is the shared core invoked by all public entry points after they
    have decided the current tool call is subject to the check.

    On the first invocation within a session, calls
    ``check_and_build_blocking_message``.  If it returns a message string,
    creates a marker file and denies the tool call.  On the second
    invocation within the same session, deletes the marker file and allows
    the tool call unconditionally.

    If no session ID is available in the hook input, the check is still
    run but any message is reported as an advisory ``systemMessage``
    without blocking — because without a session ID the marker file
    mechanism cannot guarantee the second attempt will be allowed.

    Returns 0 always (output JSON on stdout controls blocking via
    ``permissionDecision``).
    """
    session_id = hook_input.get("session_id", "")
    if not session_id:
        message = check_and_build_blocking_message()
        if message is not None:
            output = {"systemMessage": message}
            print(json.dumps(output))
        return 0

    clean_up_stale_marker_files(prefix_of_marker_file, session_id)

    marker_file_path = get_marker_file_path_for_session(
        prefix_of_marker_file, session_id
    )

    if marker_file_path.exists():
        marker_file_path.unlink(missing_ok=True)
        return 0

    message = check_and_build_blocking_message()
    if message is None:
        return 0

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


def run_deny_then_allow(
    hook_input: dict,
    prefix_of_marker_file: str,
    check_and_build_blocking_message: Callable[[], str | None],
    predicate_for_other_git_commands_that_affect_commits: (
        Callable[[str], bool] | None
    ) = None,
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
        prefix_of_marker_file: A unique prefix for this hook's marker
            files.  Must be different for each hook to avoid collisions.
        check_and_build_blocking_message: A callable that performs the
            hook-specific check and returns a blocking message string
            if the commit should be blocked, or None if it should be
            allowed.
        predicate_for_other_git_commands_that_affect_commits: An
            optional callable that returns True for git commands — other
            than ``git commit`` — that also produce or modify commits
            and should therefore trigger the deny-then-allow check.
            When provided, commands for which either
            ``is_git_subcommand`` or this callable returns True will
            proceed to the check.  When not provided, only
            ``git commit`` commands are checked.  This parameter exists
            because some hooks need to verify properties of commits
            produced by commands such as ``git rebase --continue``, not
            only those produced by ``git commit``.

    Returns 0 always (output JSON on stdout controls blocking via
    ``permissionDecision``).
    """
    tool_input = hook_input.get("tool_input", {})
    command = tool_input.get("command", "")

    # Clean up all marker files when a rebase is aborted, because any
    # markers created by denied commits during the rebase are now stale.
    session_id = hook_input.get("session_id", "")
    if session_id and is_command_for_git_rebase_with_abort(command):
        clean_up_all_marker_files_for_current_session(session_id)
        return 0

    # Fast path: command is neither a git commit nor another
    # commit-affecting git command detected by the caller's predicate.
    other_predicate = predicate_for_other_git_commands_that_affect_commits
    if not is_git_subcommand(command, "commit") and (
        other_predicate is None
        or not other_predicate(command)
    ):
        return 0

    return _run_core_logic_of_deny_then_allow(
        hook_input, prefix_of_marker_file, check_and_build_blocking_message
    )


def run_deny_then_allow_on_bash_command(
    hook_input: dict,
    prefix_of_marker_file: str,
    check_and_build_blocking_message: Callable[[], str | None],
) -> int:
    """Execute the deny-then-allow pattern on every Bash tool invocation.

    Unlike ``run_deny_then_allow``, which gates on ``git commit`` commands,
    this function applies the deny-then-allow check to every Bash tool call
    without filtering by subcommand.  Use this for hooks that must check
    arbitrary shell commands rather than only git commits.

    On the first invocation within a session, calls
    ``check_and_build_blocking_message``.  If the callable returns a
    message string, the Bash command is denied and the message is injected
    as a ``systemMessage``.  A session-scoped marker file is created so
    that the second attempt is allowed unconditionally, ensuring that false
    positives never permanently block a command.

    Parameters:
        hook_input: The JSON hook input from Claude Code stdin.
        prefix_of_marker_file: A unique prefix for this hook's marker
            files.  Must be different for each hook to avoid collisions.
        check_and_build_blocking_message: A callable that performs the
            hook-specific check and returns a blocking message string
            if the command should be blocked, or None if it should be
            allowed.

    Returns 0 always (output JSON on stdout controls blocking via
    ``permissionDecision``).
    """
    # Clean up all marker files when a rebase is aborted, because any
    # markers created by denied commits during the rebase are now stale.
    tool_input = hook_input.get("tool_input", {})
    command = tool_input.get("command", "")
    session_id = hook_input.get("session_id", "")
    if session_id and is_command_for_git_rebase_with_abort(command):
        clean_up_all_marker_files_for_current_session(session_id)
        return 0

    return _run_core_logic_of_deny_then_allow(
        hook_input, prefix_of_marker_file, check_and_build_blocking_message
    )
