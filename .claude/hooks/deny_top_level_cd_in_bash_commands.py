"""PreToolUse hook that denies top-level ``cd`` (change-to-directory) commands
in Bash invocations.

This is a Claude Code PreToolUse hook for the Bash tool.  It intercepts
every Bash tool invocation, scans the command for ``cd`` commands not
wrapped in a subshell, and denies the command if any are found.

A ``cd /path && command`` not wrapped in a subshell permanently shifts the
persistent shell session's working directory, silently corrupting the
execution context for every subsequent Bash command issued in the
conversation.  The correct form is ``(cd /path && command)``, which confines
the directory change to a subshell.

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
    iterate_over_top_level_characters_in_shell_command,
    read_hook_input_from_standard_input,
)

PREFIX_OF_MARKER_FILE = ".marker_file_for_pending_review_of_use_of_cd_at_top_level_for_session_"


def command_contains_top_level_cd(command: str) -> bool:
    """Return True if *command* contains a ``cd`` (change-to-directory)
    command at the top level of the shell (parenthesis depth zero, outside
    quoted strings and comments) — that is, a ``cd`` not wrapped in a
    subshell.

    For example, ``cd /path && command`` is at the top level, whereas
    ``(cd /path && command)`` is wrapped in a subshell and therefore not
    at the top level.

    The detection is heuristic: it uses the shared top-level character
    scanner to inspect only characters at depth zero, then checks for
    ``cd`` at command boundaries.  False positives (for example, ``cd``
    appearing as an argument to another command) are handled by the
    deny-then-allow pattern at the call site.
    """
    top_level_characters = (
        iterate_over_top_level_characters_in_shell_command(command)
    )
    for position, (index, character) in enumerate(top_level_characters):
        if character != "c" or command[index : index + 2] != "cd":
            continue

        character_after_cd = (
            command[index + 2] if index + 2 < len(command) else None
        )
        character_before_cd = command[index - 1] if index > 0 else None
        # 'cd' is at a command boundary if it appears at the very start
        # of the command or immediately after a command separator.
        is_at_command_boundary = character_before_cd is None or (
            character_before_cd in ("\n", ";", "&", "|", " ", "\t")
        )
        # 'cd' is the command itself (not a prefix of a longer identifier
        # such as 'cdrom') if it is followed by whitespace, a separator,
        # or the end of the string.
        is_not_prefix_of_longer_identifier = (
            character_after_cd is None
            or character_after_cd in (" ", "\t", "\n", ";", "&", "|")
        )
        if is_at_command_boundary and is_not_prefix_of_longer_identifier:
            return True

    return False


def build_blocking_message(command: str) -> str:
    """Build the blocking systemMessage for a top-level ``cd``
    (change-to-directory) command found in *command*.
    """
    return (
        "TOP-LEVEL cd (CHANGE-TO-DIRECTORY) COMMAND BLOCKED.\n"
        "\n"
        "The following Bash command contains a ``cd`` "
        "(change-to-directory) command not wrapped in a subshell:\n"
        "\n"
        f"  {command}\n"
        "\n"
        "The Bash tool runs all commands in a single persistent shell. "
        "A ``cd /path && command`` not wrapped in a subshell permanently "
        "shifts the working directory for every subsequent Bash command "
        "issued in this session, which can silently corrupt the execution "
        "context.\n"
        "\n"
        "Wrap the directory change in a subshell instead:\n"
        "\n"
        "  (cd /path && command)\n"
        "\n"
        "The parentheses confine the ``cd`` to the subshell; the "
        "persistent shell's working directory is not affected. "
        "Re-attempt the command using the subshell form. If this is a "
        "false positive, re-attempt the command unchanged — it will be "
        "allowed on the second attempt."
    )


def main() -> int:
    hook_input = read_hook_input_from_standard_input()
    command = hook_input.get("tool_input", {}).get("command", "")

    def check_and_build_blocking_message() -> str | None:
        if not command_contains_top_level_cd(command):
            return None
        return build_blocking_message(command)

    return run_deny_then_allow_on_bash_command(
        hook_input,
        PREFIX_OF_MARKER_FILE,
        check_and_build_blocking_message,
    )


if __name__ == "__main__":
    sys.exit(main())
