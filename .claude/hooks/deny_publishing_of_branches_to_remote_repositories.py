"""PreToolUse hook that denies pushing or publishing of branches to
remote repositories.

This is a Claude Code PreToolUse hook for the Bash tool.  It intercepts
every Bash tool invocation and denies the command if it contains any
invocation that publishes branch content to a remote repository,
covering the following commands:

git subcommands that publish:
- ``git push`` (in any form, including ``git push --force``,
  ``git push --set-upstream``, and ``git push -u origin <branch>``)
- ``git send-email`` (transmits patches via the Simple Mail Transfer
  Protocol)
- ``git svn dcommit`` (pushes commits to a Subversion remote)
- ``git subtree push`` (pushes a subtree to a remote)

Invocations of third-party command-line interfaces that publish:
- ``gh pr create`` (publishes the current branch to GitHub and opens
  a pull request)
- ``gh release create`` (publishes a release with associated tags to
  GitHub)
- ``gh repo create --push`` (creates a remote repository on GitHub and
  pushes the current branch into it)
- ``glab mr create`` (publishes the current branch to GitLab and opens
  a merge request)
- ``hub push`` (legacy hub command for pushing)
- ``hub pull-request`` (legacy hub command for opening a pull request)

All of these actions push branch content to a remote repository.
Pushing affects shared state outside this session and requires the
user to authorise it explicitly in their own terminal.

Unlike hooks that use the deny-then-allow pattern for non-deterministic
checks, this hook blocks unconditionally.  Detection is performed by
``shlex`` token parsing of literal command names — no false positives
are expected — so no escape hatch is provided.

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


# Each entry pairs a binary name with the consecutive subcommand path
# tokens that publish, and (when not None) a flag that must additionally
# appear anywhere in the command for the invocation to count as a
# publishing one.  ``gh repo create`` only publishes when the ``--push``
# flag is present, since the bare invocation creates an empty remote
# repository without pushing any branch into it.
PUBLISHING_INVOCATIONS_OF_THIRD_PARTY_COMMAND_LINE_INTERFACES = [
    ("gh", ["pr", "create"], None),
    ("gh", ["release", "create"], None),
    ("gh", ["repo", "create"], "--push"),
    ("glab", ["mr", "create"], None),
    ("hub", ["push"], None),
    ("hub", ["pull-request"], None),
]


# Top-level git subcommands that themselves publish to a remote.
GIT_SUBCOMMANDS_THAT_PUBLISH = ["push", "send-email"]


# Pairs of (git subcommand, first positional argument) where the
# combination publishes to a remote.  These cannot be detected by
# ``is_git_subcommand`` alone because that function only inspects the
# git subcommand itself, not its first positional argument.
GIT_SUBCOMMANDS_WITH_PUBLISHING_FIRST_POSITIONAL_ARGUMENT = [
    ("svn", "dcommit"),
    ("subtree", "push"),
]


def tokenise_command_via_shlex(command: str) -> list[str] | None:
    """Tokenise *command* with ``shlex.split``.  Return ``None`` if the
    tokeniser raises ``ValueError`` due to unterminated quoting.
    """
    try:
        return shlex.split(command)
    except ValueError:
        return None


def tokens_contain_binary_followed_by_subcommand_path(
    tokens: list[str],
    binary_name: str,
    subcommand_path: list[str],
) -> bool:
    """Return True if *tokens* contains *binary_name* (or a path token
    ending in ``/<binary_name>``) followed immediately by the
    *subcommand_path* tokens.
    """
    path_length = len(subcommand_path)
    for index, token in enumerate(tokens):
        if not (token == binary_name or token.endswith(f"/{binary_name}")):
            continue
        if index + path_length >= len(tokens):
            continue
        if tokens[index + 1 : index + 1 + path_length] == subcommand_path:
            return True
    return False


def command_contains_publishing_invocation_of_third_party_command_line_interface(
    command: str,
) -> bool:
    """Detect publishing invocations of ``gh``, ``glab``, and ``hub``.

    The set of invocations covered is enumerated in the module-level
    constant
    ``PUBLISHING_INVOCATIONS_OF_THIRD_PARTY_COMMAND_LINE_INTERFACES``.
    """
    tokens = tokenise_command_via_shlex(command)
    for binary_name, subcommand_path, required_flag in (
        PUBLISHING_INVOCATIONS_OF_THIRD_PARTY_COMMAND_LINE_INTERFACES
    ):
        if tokens is None:
            path_pattern = r"\s+".join(re.escape(t) for t in subcommand_path)
            pattern = rf"\b{re.escape(binary_name)}\b\s+{path_pattern}\b"
            if required_flag is not None:
                pattern = (
                    pattern + rf".*(?<![A-Za-z0-9_]){re.escape(required_flag)}\b"
                )
            if re.search(pattern, command):
                return True
            continue
        if not tokens_contain_binary_followed_by_subcommand_path(
            tokens, binary_name, subcommand_path
        ):
            continue
        if required_flag is None or required_flag in tokens:
            return True
    return False


def command_invokes_git_subcommand_with_first_positional_argument(
    command: str,
    subcommand: str,
    first_positional_argument: str,
) -> bool:
    """Return True if *command* invokes ``git <subcommand>`` such that
    the first positional argument that follows *subcommand* equals
    *first_positional_argument*.

    Multiple occurrences of the same subcommand token are checked
    independently — for example, in ``git log subtree && git subtree
    push --prefix=foo`` the second occurrence of ``subtree`` has
    ``push`` as its first positional argument and therefore matches.
    """
    if not is_git_subcommand(command, subcommand):
        return False
    tokens = tokenise_command_via_shlex(command)
    if tokens is None:
        return bool(re.search(
            rf"\b{re.escape(subcommand)}\b\s+{re.escape(first_positional_argument)}\b",
            command,
        ))
    for position, token in enumerate(tokens):
        if token != subcommand:
            continue
        for next_token in tokens[position + 1 :]:
            if next_token.startswith("-"):
                continue
            if next_token == first_positional_argument:
                return True
            break
    return False


def command_contains_publishing_invocation_of_git(command: str) -> bool:
    """Detect git subcommands that publish to a remote.

    Covers the top-level subcommands enumerated in
    ``GIT_SUBCOMMANDS_THAT_PUBLISH`` and the nested-subcommand pairs
    enumerated in
    ``GIT_SUBCOMMANDS_WITH_PUBLISHING_FIRST_POSITIONAL_ARGUMENT``.
    """
    for subcommand in GIT_SUBCOMMANDS_THAT_PUBLISH:
        if is_git_subcommand(command, subcommand):
            return True
    for subcommand, first_positional_argument in (
        GIT_SUBCOMMANDS_WITH_PUBLISHING_FIRST_POSITIONAL_ARGUMENT
    ):
        if command_invokes_git_subcommand_with_first_positional_argument(
            command, subcommand, first_positional_argument
        ):
            return True
    return False


def build_blocking_message(command: str) -> str:
    """Build the blocking systemMessage for a publishing command
    detected in *command*.
    """
    return (
        "PUSHING OR PUBLISHING OF BRANCHES TO REMOTE REPOSITORIES BLOCKED.\n"
        "\n"
        "The following Bash command would push or publish branches to a "
        "remote repository:\n"
        "\n"
        f"  {command}\n"
        "\n"
        "Pushing branches affects shared state outside this session and "
        "must therefore be authorised by the user in their own terminal.  "
        "Detection covers ``git push``, ``git send-email``, "
        "``git svn dcommit``, ``git subtree push``, ``gh pr create``, "
        "``gh release create``, ``gh repo create --push``, "
        "``glab mr create``, ``hub push``, and ``hub pull-request``; "
        "each detection is deterministic with no escape hatch provided "
        "— re-attempting the command will not allow it through.\n"
        "\n"
        "Ask the user to run the command themselves if a push or publish "
        "is genuinely intended."
    )


def main() -> int:
    hook_input = read_hook_input_from_standard_input()
    command = hook_input.get("tool_input", {}).get("command", "")

    if not (
        command_contains_publishing_invocation_of_git(command)
        or command_contains_publishing_invocation_of_third_party_command_line_interface(
            command
        )
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
