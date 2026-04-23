"""PreToolUse hook that denies any commit-authoring ``git`` invocation
when chained with other commands in the same Bash tool call.

This is a Claude Code PreToolUse hook for the Bash tool.  It intercepts
every Bash tool invocation and denies the command if both conditions are
met simultaneously:

1. The command contains a commit-authoring ``git`` invocation — that is,
   one of ``git commit``, ``git commit-tree``, ``git cherry-pick``,
   ``git revert``, ``git rebase``, ``git am``, or ``git merge``
   (including ``--continue`` and ``--skip`` completion forms), excluding
   invocations carrying a flag that suppresses commit authoring for the
   specific invocation (such as ``--abort``, ``--quit``, ``--no-commit``,
   ``-n``, ``--ff-only``, ``--squash``, ``--dry-run``,
   ``--show-current-patch``, or ``--edit-todo``).
2. The command contains a shell operator (``&&``, ``||``, ``;``, or
   ``|``) anywhere in the command after stripping quoted strings and
   comments.

PreToolUse hooks evaluate the state of the repository at the moment the
Bash tool call begins — before any commands in the compound expression
have run.  When ``git add`` and a commit-authoring invocation are
chained in the same Bash tool call, the commit-message verification
hooks observe the staging area before ``git add`` has modified it.  The
hooks therefore verify the commit message against a stale diff and may
allow a commit whose message does not accurately describe the content
being staged.  Issuing each commit-authoring invocation as its own
standalone Bash tool call ensures that the hooks observe the correct
staging area.

This rationale applies equally to every commit-authoring subcommand —
not only ``git commit``: ``git cherry-pick --continue``,
``git rebase --continue``, ``git revert --continue``,
``git am --continue``, and ``git merge`` can all author commits, and
each must observe the correct staging area before the pre-commit
verification hooks run.

The hook uses the deny-then-allow pattern: on the first invocation that
triggers the check within a session, the command is denied and a
``systemMessage`` is injected explaining the violation.  On the second
attempt within the same session, the command is allowed unconditionally,
so that false positives from the heuristic check never permanently block
a command.

Exit code 0 — always (output JSON controls blocking via permissionDecision).
"""

import sys

from helpers.deny_then_allow import run_deny_then_allow_on_bash_command
from helpers.parsing_of_hook_input_for_bash_commands import (
    command_contains_shell_operator_at_any_depth,
    is_git_subcommand_producing_a_new_commit,
    read_hook_input_from_standard_input,
)

PREFIX_OF_MARKER_FILE = (
    ".marker_file_for_pending_review_of_commit_authoring_git_invocation_in_compound_command_for_session_"
)


def command_contains_commit_authoring_git_invocation_in_compound_command(
    command: str,
) -> bool:
    """Return True if *command* contains a commit-authoring ``git``
    invocation chained with other commands via a shell operator.

    The check requires both conditions to be true simultaneously: the
    command must contain a commit-authoring ``git`` invocation —
    ``git commit``, ``git commit-tree``, ``git cherry-pick``,
    ``git revert``, ``git rebase``, ``git am``, or ``git merge``
    (including ``--continue`` and ``--skip`` completion forms), excluding
    invocations carrying a flag that suppresses commit authoring (such as
    ``--abort``, ``--quit``, ``--no-commit``, ``-n``, ``--ff-only``,
    ``--squash``, ``--dry-run``, ``--show-current-patch``, or
    ``--edit-todo``) — detected via
    ``is_git_subcommand_producing_a_new_commit``; and the command must
    contain a shell operator anywhere after stripping quoted strings and
    comments — detected via
    ``command_contains_shell_operator_at_any_depth``.  When a
    commit-authoring invocation is issued as a standalone command, the
    check passes without blocking.
    """
    if not is_git_subcommand_producing_a_new_commit(command):
        return False
    return command_contains_shell_operator_at_any_depth(command)


def build_blocking_message(command: str) -> str:
    """Build the blocking systemMessage for a commit-authoring ``git``
    invocation found in a compound command.
    """
    return (
        "COMMIT-AUTHORING GIT INVOCATION IN COMPOUND COMMAND BLOCKED.\n"
        "\n"
        "The following Bash command chains a commit-authoring ``git`` "
        "invocation with other commands in a single tool call:\n"
        "\n"
        f"  {command}\n"
        "\n"
        "PreToolUse hooks evaluate the state of the repository before "
        "any commands in the compound expression have run.  When "
        "``git add`` and a commit-authoring invocation are chained in "
        "the same Bash tool call, the commit-message verification hooks "
        "observe the staging area before ``git add`` has modified it — "
        "they therefore verify the commit message against a stale diff "
        "and may allow a commit whose message does not accurately "
        "describe the content being staged.\n"
        "\n"
        "Commit-authoring subcommands include: ``git commit``, "
        "``git commit-tree``, ``git cherry-pick``, ``git revert``, "
        "``git rebase``, ``git am``, and ``git merge`` (including "
        "``--continue`` and ``--skip`` completion forms), excluding "
        "invocations that carry a flag suppressing commit authoring "
        "(such as ``--abort``, ``--quit``, ``--no-commit``, ``-n``, "
        "``--ff-only``, ``--squash``, ``--dry-run``, "
        "``--show-current-patch``, or ``--edit-todo``).\n"
        "\n"
        "Issue each commit-authoring invocation as its own standalone "
        "Bash tool call instead.  For example, instead of:\n"
        "\n"
        "  git add file.py && git commit -m \"message\"\n"
        "\n"
        "Use two separate Bash tool calls:\n"
        "\n"
        "  1. git add file.py\n"
        "  2. git commit -m \"message\"\n"
        "\n"
        "Re-attempt the command as separate Bash tool calls. If this "
        "is a false positive, re-attempt the command unchanged — it "
        "will be allowed on the second attempt."
    )


def main() -> int:
    hook_input = read_hook_input_from_standard_input()
    command = hook_input.get("tool_input", {}).get("command", "")

    def check_and_build_blocking_message() -> str | None:
        if not command_contains_commit_authoring_git_invocation_in_compound_command(
            command
        ):
            return None
        return build_blocking_message(command)

    return run_deny_then_allow_on_bash_command(
        hook_input,
        PREFIX_OF_MARKER_FILE,
        check_and_build_blocking_message,
    )


if __name__ == "__main__":
    sys.exit(main())
