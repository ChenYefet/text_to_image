"""Shared utility functions for parsing of hook input for Bash commands.

Provides functions used at the entry point of every pre-commit hook:
one that reads and parses the JSON input provided by Claude Code on
standard input, and a function that determines whether a Bash command
invokes a specific ``git`` subcommand.
"""

import json
import re
import shlex
import sys

# Git top-level flags that consume a separate argument token.  When the
# tokeniser encounters one of these, the next token is consumed as its
# value and skipped.  Short flags (-C, -c) and their long equivalents
# are listed separately so that both forms are handled.
_GIT_FLAGS_THAT_CONSUME_AN_ARGUMENT = frozenset({
    "-C",
    "-c",
    "--git-dir",
    "--work-tree",
    "--namespace",
    "--super-prefix",
    "--config-env",
})


def read_hook_input_from_standard_input() -> dict:
    """Read the JSON hook input provided by Claude Code on standard input."""
    return json.loads(sys.stdin.read())


def _extract_git_subcommand_from_tokens(tokens: list[str]) -> str | None:
    """Walk *tokens* past any git-level flags and return the subcommand
    name, or ``None`` if the tokens are exhausted before a subcommand
    is found.

    *tokens* must begin at the token immediately after ``git``.
    """
    index = 0
    while index < len(tokens):
        token = tokens[index]

        # A token that does not start with '-' is the subcommand.
        if not token.startswith("-"):
            return token

        # Handle -C<path> / -c<key>=<value> written without a space
        # (e.g. ``git -C/tmp commit``).  The flag letter is at
        # position 1; if the token is longer than two characters the
        # value is glued onto the flag and no separate argument
        # follows.
        if len(token) > 2 and token[:2] in ("-C", "-c"):
            index += 1
            continue

        # Flags that consume a following argument token.
        if token in _GIT_FLAGS_THAT_CONSUME_AN_ARGUMENT:
            index += 2  # skip the flag and its argument
            continue

        # Long flags that use '=' to attach their value
        # (e.g. ``--git-dir=/repo``).
        if "=" in token:
            index += 1
            continue

        # Any other flag (e.g. ``--no-pager``, ``--bare``,
        # ``--no-replace-objects``) takes no argument.
        index += 1

    # Reached end of tokens without finding a subcommand.
    return None


def is_git_subcommand(command: str, subcommand: str) -> bool:
    """Return True if *command* is a ``git <subcommand>`` invocation.

    The function tokenises *command* with ``shlex.split`` so that
    git-level flags such as ``-C <path>`` and ``-c <key>=<value>``
    are consumed correctly before the subcommand is identified.  If
    ``shlex.split`` raises ``ValueError`` (e.g. due to unterminated
    quoting), the function falls back to a conservative regex that
    searches for *subcommand* as a standalone word after ``git``
    within the same command segment (no intervening pipe, semicolon,
    or ampersand).
    """
    try:
        tokens = shlex.split(command)
    except ValueError:
        # Fallback: search for the specific subcommand word after
        # 'git', within the same command segment.  Using the caller's
        # known subcommand is strictly safer than attempting generic
        # extraction, because a generic capture can match path
        # components or flag arguments.
        return bool(re.search(
            rf"\bgit\b(?:[^|;&]*)\b{re.escape(subcommand)}\b",
            command,
        ))

    # Locate the 'git' token.  It may not be the first token if the
    # command starts with environment variable assignments or a
    # preceding subshell wrapper.
    for position, token in enumerate(tokens):
        if token == "git" or token.endswith("/git"):
            return (
                _extract_git_subcommand_from_tokens(
                    tokens[position + 1 :]
                )
                == subcommand
            )

    return False
