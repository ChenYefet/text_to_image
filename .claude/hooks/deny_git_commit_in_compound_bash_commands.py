"""PreToolUse hook that denies ``git commit`` when chained with other
commands in the same Bash tool call.

This is a Claude Code PreToolUse hook for the Bash tool.  It intercepts
every Bash tool invocation and denies the command if both conditions are
met simultaneously:

1. The command contains a ``git commit`` or ``git commit-tree`` invocation.
2. The command contains a shell operator (``&&``, ``||``, ``;``, or
   ``|``) anywhere in the command after stripping quoted strings and
   comments.

PreToolUse hooks evaluate the state of the repository at the moment the
Bash tool call begins — before any commands in the compound expression
have run.  When ``git add`` and ``git commit`` are chained in the same
Bash tool call, the commit-message verification hooks observe the
staging area before ``git add`` has modified it.  The hooks therefore
verify the commit message against a stale diff and may allow a commit
whose message does not accurately describe the content being staged.
Issuing ``git commit`` as its own standalone Bash tool call ensures that
the hooks observe the correct staging area.

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
    is_git_subcommand,
    read_hook_input_from_standard_input,
)

PREFIX_OF_MARKER_FILE = (
    ".marker_file_for_pending_review_of_git_commit_in_compound_command_for_session_"
)


def command_contains_git_commit_in_compound_command(command: str) -> bool:
    """Return True if *command* contains a ``git commit`` invocation
    chained with other commands via a shell operator.

    The check requires both conditions to be true simultaneously: the
    command must contain ``git commit`` or ``git commit-tree`` (detected
    via ``is_git_subcommand``), and the command must contain a shell
    operator anywhere after stripping quoted strings and comments
    (detected via ``command_contains_shell_operator_at_any_depth``).
    When ``git commit`` is issued as a standalone command, the check
    passes without blocking.
    """
    if not is_git_subcommand(command, "commit") and not is_git_subcommand(
        command, "commit-tree"
    ):
        return False
    return command_contains_shell_operator_at_any_depth(command)


def build_blocking_message(command: str) -> str:
    """Build the blocking systemMessage for a ``git commit`` found in
    a compound command.
    """
    return (
        "GIT COMMIT IN COMPOUND COMMAND BLOCKED.\n"
        "\n"
        "The following Bash command chains ``git commit`` with other "
        "commands in a single tool call:\n"
        "\n"
        f"  {command}\n"
        "\n"
        "PreToolUse hooks evaluate the state of the repository before "
        "any commands in the compound expression have run.  When "
        "``git add`` and ``git commit`` are chained in the same Bash "
        "tool call, the commit-message verification hooks observe the "
        "staging area before ``git add`` has modified it — they "
        "therefore verify the commit message against a stale diff and "
        "may allow a commit whose message does not accurately describe "
        "the content being staged.\n"
        "\n"
        "Issue ``git add`` and ``git commit`` as separate Bash tool "
        "calls instead.  For example, instead of:\n"
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
        if not command_contains_git_commit_in_compound_command(command):
            return None
        return build_blocking_message(command)

    return run_deny_then_allow_on_bash_command(
        hook_input,
        PREFIX_OF_MARKER_FILE,
        check_and_build_blocking_message,
    )


if __name__ == "__main__":
    sys.exit(main())
