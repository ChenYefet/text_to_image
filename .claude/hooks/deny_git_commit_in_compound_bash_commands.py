"""PreToolUse hook that denies ``git commit`` when chained with other
commands during an interactive rebase.

This is a Claude Code PreToolUse hook for the Bash tool.  It intercepts
every Bash tool invocation and denies the command if all three conditions
are met simultaneously:

1. The command contains a ``git commit`` invocation.
2. The command contains a shell operator (``&&``, ``||``, ``;``, or
   ``|``) at the top level of the shell.
3. An interactive rebase is currently in progress (detected by the
   presence of ``.git/rebase-merge/`` or ``.git/rebase-apply/``).

During an interactive rebase, git checks out older commits into the
working tree.  If the ``.claude/hooks/`` files were different in those
older commits, an older version of the hook code for parsing commands
might not correctly detect ``git commit`` within compound commands.
Issuing ``git commit`` as its own standalone Bash tool call during
rebases ensures that every pre-commit hook fires reliably.

Outside of an interactive rebase, the current hooks correctly detect
``git commit`` in compound commands, so no restriction is needed.

The hook uses the deny-then-allow pattern: on the first invocation that
triggers the check within a session, the command is denied and a
``systemMessage`` is injected explaining the violation.  On the second
attempt within the same session, the command is allowed unconditionally,
so that false positives from the heuristic check never permanently block
a command.

Exit code 0 — always (output JSON controls blocking via permissionDecision).
"""

import pathlib
import sys

from helpers.deny_then_allow import run_deny_then_allow_on_bash_command
from helpers.parsing_of_hook_input_for_bash_commands import (
    command_contains_shell_operator_at_top_level,
    is_git_subcommand,
    read_hook_input_from_standard_input,
)

MARKER_FILE_PREFIX = (
    ".git_commit_in_compound_command_deny_then_allow_session_"
)


def _is_interactive_rebase_in_progress() -> bool:
    """Return True if an interactive rebase is currently in progress.

    Git creates ``.git/rebase-merge/`` during ``git rebase -i`` and
    ``git rebase``, and ``.git/rebase-apply/`` during ``git am`` and
    older-style rebases.  The presence of either directory indicates
    that a rebase is in progress and the working tree may contain
    files from an older commit.
    """
    return (
        pathlib.Path(".git/rebase-merge").is_dir()
        or pathlib.Path(".git/rebase-apply").is_dir()
    )


def command_contains_git_commit_in_compound_command(command: str) -> bool:
    """Return True if *command* contains a ``git commit`` invocation
    chained with other commands via a shell operator at the top level
    while an interactive rebase is in progress.

    The check requires all three conditions to be true simultaneously:
    the command must contain ``git commit`` (detected via
    ``is_git_subcommand``), the command must contain a top-level shell
    operator (detected via
    ``command_contains_shell_operator_at_top_level``), and an
    interactive rebase must be in progress.  Outside of a rebase, or
    when ``git commit`` is issued as a standalone command, the check
    passes without blocking.
    """
    if not _is_interactive_rebase_in_progress():
        return False
    if not is_git_subcommand(command, "commit"):
        return False
    return command_contains_shell_operator_at_top_level(command)


def build_blocking_message(command: str) -> str:
    """Build the blocking systemMessage for a ``git commit`` found in
    a compound command.
    """
    return (
        "GIT COMMIT IN COMPOUND COMMAND BLOCKED (INTERACTIVE REBASE "
        "IN PROGRESS).\n"
        "\n"
        "The following Bash command chains ``git commit`` with other "
        "commands in a single tool call:\n"
        "\n"
        f"  {command}\n"
        "\n"
        "An interactive rebase is currently in progress.  During a "
        "rebase, the working tree may contain an older version of the "
        "hook code that does not correctly detect ``git commit`` "
        "within compound commands.  Issuing ``git commit`` as its "
        "own standalone Bash tool call ensures that every pre-commit "
        "hook fires reliably.\n"
        "\n"
        "Issue ``git commit`` as its own standalone Bash tool call "
        "instead.  For example, instead of:\n"
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
        MARKER_FILE_PREFIX,
        check_and_build_blocking_message,
    )


if __name__ == "__main__":
    sys.exit(main())
