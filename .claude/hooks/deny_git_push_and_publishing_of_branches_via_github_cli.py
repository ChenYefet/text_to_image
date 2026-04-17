"""PreToolUse hook that denies ``git push`` and publishing of branches via
the GitHub command-line interface.

This is a Claude Code PreToolUse hook for the Bash tool.  It intercepts
every Bash tool invocation and denies the command if it contains:

1. A ``git push`` invocation (any form, including ``git push --force``,
   ``git push --set-upstream``, and ``git push -u origin <branch>``), or
2. A ``gh pr create`` invocation, which publishes the current branch to
   GitHub and opens a pull request.

Both actions push branch content to a remote repository.  Pushing affects
shared state outside this session and requires the user to authorise it
explicitly in their own terminal.

Unlike hooks that use the deny-then-allow pattern for non-deterministic
checks, this hook blocks unconditionally.  The detection of ``git push``
and ``gh pr create`` is deterministic — token-based parsing produces no
false positives — so no escape hatch is provided.

Exit code 0 — always (output JSON controls blocking via permissionDecision).
"""

import json
import re
import shlex
import sys

from helpers.parsing_of_hook_input_for_bash_commands import (
    is_git_subcommand,
    read_hook_input_from_standard_input,
)


def command_contains_gh_pr_create(command: str) -> bool:
    """Return True if *command* contains a ``gh pr create`` invocation.

    Tokenises *command* with ``shlex.split`` and scans for ``gh`` (or
    an absolute-path token ending in ``/gh``) followed immediately by
    the subcommand path tokens ``pr`` and ``create``.  Falls back to a
    regular expression when ``shlex.split`` raises ``ValueError`` due to
    unterminated quoting.
    """
    try:
        tokens = shlex.split(command)
    except ValueError:
        return bool(re.search(r"\bgh\b\s+pr\s+create\b", command))

    for index, token in enumerate(tokens):
        if (
            (token == "gh" or token.endswith("/gh"))
            and index + 2 < len(tokens)
            and tokens[index + 1] == "pr"
            and tokens[index + 2] == "create"
        ):
            return True
    return False


def build_blocking_message(command: str) -> str:
    """Build the blocking systemMessage for a ``git push`` or
    ``gh pr create`` command detected in *command*.
    """
    return (
        "GIT PUSH AND PUBLISHING OF BRANCHES BLOCKED.\n"
        "\n"
        "The following Bash command would push or publish branches to a "
        "remote repository:\n"
        "\n"
        f"  {command}\n"
        "\n"
        "Pushing branches affects shared state outside this session and "
        "must therefore be authorised by the user in their own terminal.  "
        "The detection of ``git push`` and ``gh pr create`` is "
        "deterministic, so no escape hatch is provided — re-attempting "
        "the command will not allow it through.\n"
        "\n"
        "Ask the user to run the command themselves if a push or publish "
        "is genuinely intended."
    )


def main() -> int:
    hook_input = read_hook_input_from_standard_input()
    command = hook_input.get("tool_input", {}).get("command", "")

    if not is_git_subcommand(command, "push") and not command_contains_gh_pr_create(
        command
    ):
        return 0

    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": build_blocking_message(command),
        }
    }
    print(json.dumps(output))
    return 0


if __name__ == "__main__":
    sys.exit(main())
