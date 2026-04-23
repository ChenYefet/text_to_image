"""Pre-commit hook that requires CLAUDE.md to be read right before allowing
a commit.

This is a Claude Code PreToolUse hook for the Bash tool.  On every
Bash command that invokes a ``git`` subcommand authoring at least one
commit on successful execution — ``git commit``, ``git commit-tree``,
``git cherry-pick`` (initial invocation and its ``--continue`` /
``--skip`` completion forms), ``git revert`` (likewise), ``git rebase``
(likewise), ``git am`` (likewise), and ``git merge`` (initial and
``--continue``), excluding invocations carrying flags that suppress
commit authoring such as ``--abort``, ``--quit``, ``--no-commit``,
``--ff-only``, ``--show-current-patch``, ``--edit-todo``, or
``--dry-run`` — it checks for a session-scoped marker file created by
the PostToolUse hook ``track_reading_of_claude_md.py``, which fires
when the Read tool is used on CLAUDE.md.  If the marker exists, the
command is allowed.  The marker is not consumed here — it is consumed
by ``track_reading_of_claude_md.py`` after the command actually executes
(via a PostToolUse hook on Bash), ensuring that a command denied by
another PreToolUse hook does not invalidate the read marker.  If the
marker does not exist, the command is denied with a message instructing
the model to read CLAUDE.md before re-attempting.

Gating every commit-authoring subcommand rather than only the literal
``git commit`` is necessary because the hook's stated invariant — that
the next commit entering the repository's history requires a fresh
read of CLAUDE.md — applies to every path by which a commit can enter
history, not merely to the direct one.  Gating only ``git commit``
would let a ``git cherry-pick --continue`` or a ``git rebase
--continue`` after conflict resolution author a commit without any
pre-commit review, silently violating the invariant.

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
    is_command_for_git_rebase_with_abort_or_quit,
)
from helpers.parsing_of_hook_input_for_bash_commands import (
    is_git_subcommand_producing_a_new_commit,
    read_hook_input_from_standard_input,
)


def main() -> int:
    hook_input = read_hook_input_from_standard_input()
    tool_input = hook_input.get("tool_input", {})
    command = tool_input.get("command", "")
    session_id = hook_input.get("session_id", "")

    # Clean up read-marker when a rebase is abandoned — any markers
    # created during an abandoned rebase are stale.  ``--abort`` and
    # ``--quit`` both terminate the rebase without finalising its
    # authored commits: ``--abort`` resets HEAD to ORIG_HEAD, while
    # ``--quit`` leaves HEAD detached on the partially-applied state,
    # which the branch reference does not point at.  In either case
    # the commits that were in flight when the marker was created
    # are no longer on the branch, so the marker no longer describes
    # a live pre-commit review.
    if session_id and is_command_for_git_rebase_with_abort_or_quit(command):
        get_marker_file_path_for_session(
            PREFIX_OF_MARKER_FILE_FOR_COMMIT_PERMITTED_AFTER_READING_OF_CLAUDE_MD,
            session_id,
        ).unlink(missing_ok=True)
        return 0

    # Only gate commands whose git subcommand authors at least one new
    # commit on successful execution.  Covers direct ``git commit``, the
    # plumbing ``git commit-tree``, and the porcelain subcommands
    # (cherry-pick, revert, rebase, am, merge) in both their initial
    # form and their ``--continue`` / ``--skip`` completion forms.
    # Invocations carrying suppression flags (``--abort``, ``--quit``,
    # ``--no-commit``, ``--ff-only``, ``--show-current-patch``,
    # ``--edit-todo``, ``--dry-run``) author no commit and are passed
    # through.
    if not is_git_subcommand_producing_a_new_commit(command):
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
        # The marker is not consumed here.  Consumption is handled by
        # ``track_reading_of_claude_md.py`` (PostToolUse on Bash) after
        # the commit actually executes.  This prevents a denied commit
        # — blocked by another PreToolUse hook — from invalidating the
        # read marker.
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "permissionDecisionReason": "CLAUDE.md was read right before this commit-authoring command — command permitted.",
            },
        }
        print(json.dumps(output))
        return 0

    # CLAUDE.md has not been read right before this commit-authoring
    # command — deny.
    message = (
        "MANDATORY PRE-COMMIT REVIEW — COMMIT-AUTHORING COMMAND BLOCKED.\n"
        "\n"
        "This command has been blocked because CLAUDE.md has not been "
        "read right before it.  The command was detected as one that "
        "authors at least one new commit on successful execution "
        "(``git commit`` / ``git commit-tree``, or any of cherry-pick, "
        "revert, rebase, am, merge — including their ``--continue`` "
        "and ``--skip`` completion forms — without a suppression flag "
        "such as ``--abort``, ``--quit``, ``--no-commit``, "
        "``--ff-only``, ``--show-current-patch``, ``--edit-todo``, or "
        "``--dry-run``).\n"
        "\n"
        "Before re-attempting the command:\n"
        "\n"
        "1. Read CLAUDE.md in full using the Read tool.\n"
        "\n"
        "2. Review all changes that will be committed — including "
        "commit composition, version references, refactoring "
        "verification, and changelog updates — against each applicable "
        "directive.\n"
        "\n"
        "3. Review the commit message separately.\n"
        "\n"
        "If any directive is violated in either the changes or the "
        "commit message, fix the violation before re-attempting.  If "
        "all directives are satisfied, re-attempt the command — it "
        "will be allowed once CLAUDE.md has been read."
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
