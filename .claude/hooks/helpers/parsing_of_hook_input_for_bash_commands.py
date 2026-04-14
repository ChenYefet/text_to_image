"""Shared utility functions for parsing of hook input for Bash commands.

Provides functions used at the entry point of every pre-commit hook:
one that reads and parses the JSON input provided by Claude Code on
standard input, a function that determines whether a Bash command
invokes a specific ``git`` subcommand, a function that extracts the
commit message from a git command string, a character-by-character
shell scanner that returns characters at the top level of the shell
(outside quoted strings, comments, and subshells), and a function
that detects shell operators anywhere in a command after stripping
quoted strings and comments.
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


def iterate_over_top_level_characters_in_shell_command(
    command: str,
) -> list[tuple[int, str]]:
    """Return a list of ``(index, character)`` pairs for every character
    in *command* that appears at the top level of the shell — that is,
    outside single-quoted strings, double-quoted strings, comments, and
    subshells (parenthesised groups).

    This function encapsulates the character-by-character scanning logic
    that tracks quote state, parenthesis depth, escape sequences, and
    comment boundaries.  Callers can iterate over the returned list to
    inspect only the characters that are structurally significant in the
    outermost shell context, without duplicating the scanning logic.
    """
    top_level_characters = []
    depth = 0
    inside_single_quote = False
    inside_double_quote = False
    index = 0
    length = len(command)

    while index < length:
        character = command[index]

        if inside_single_quote:
            if character == "'":
                inside_single_quote = False
            index += 1
            continue

        if inside_double_quote:
            if character == "\\" and index + 1 < length:
                index += 2
                continue
            if character == '"':
                inside_double_quote = False
            index += 1
            continue

        if character == "#":
            while index < length and command[index] != "\n":
                index += 1
            continue

        if character == "'":
            inside_single_quote = True
            index += 1
            continue

        if character == '"':
            inside_double_quote = True
            index += 1
            continue

        if character == "(":
            depth += 1
            index += 1
            continue

        if character == ")":
            if depth > 0:
                depth -= 1
            index += 1
            continue

        if depth == 0:
            top_level_characters.append((index, character))

        index += 1

    return top_level_characters


def command_contains_shell_operator_at_any_depth(command: str) -> bool:
    """Return True if *command* contains a shell operator (``&&``,
    ``||``, ``;``, or ``|``) anywhere in the command.

    This function strips single-quoted strings, double-quoted strings
    (handling backslash escape sequences), and comments via a single
    regular expression pass, then searches the remainder for any shell
    operator.  Unlike the depth-aware scanner provided by
    ``iterate_over_top_level_characters_in_shell_command``, this
    function ignores parenthesis depth entirely, making it suitable for
    detecting compound commands in which operators may appear inside a
    subshell — for example, ``(cd /path && git commit -m "msg")`` — where
    a top-level-only scanner cannot see the ``&&`` at depth one.
    """
    command_without_quoted_strings_and_comments = re.sub(
        r"""'[^']*'|"(?:[^"\\]|\\.)*"|#[^\n]*""",
        "",
        command,
        flags=re.DOTALL,
    )
    return bool(re.search(
        r"&&|\|\||;|\|",
        command_without_quoted_strings_and_comments,
    ))


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

    # Scan all tokens for a 'git' invocation matching the requested
    # subcommand.  Scanning all tokens (rather than stopping at the
    # first 'git') ensures that compound commands such as
    # 'git add . && git commit' are handled correctly: the first 'git'
    # has subcommand 'add', so stopping there would cause 'commit' to
    # go undetected.
    for position, token in enumerate(tokens):
        if token == "git" or token.endswith("/git"):
            if (
                _extract_git_subcommand_from_tokens(tokens[position + 1 :])
                == subcommand
            ):
                return True

    return False


def extract_commit_message_from_command(command: str) -> str | None:
    """Extract the commit message from a git commit command string.

    Handles heredoc syntax, double-quoted ``-m`` arguments, and
    single-quoted ``-m`` arguments.  Returns ``None`` if no ``-m``
    flag is found (e.g. ``--amend`` without ``-m``, which reuses
    the existing message).
    """
    # Heredoc pattern: -m "$(cat <<'EOF' ... EOF )"
    heredoc_match = re.search(
        r"""-m\s+"\$\(cat\s+<<'EOF'\s*\n(.*?)\n\s*EOF\s*\)""",
        command,
        re.DOTALL,
    )
    if heredoc_match:
        return heredoc_match.group(1).strip()

    # Double-quoted: -m "message"
    double_quoted_match = re.search(
        r'-m\s+"((?:[^"\\]|\\.)*)"', command, re.DOTALL
    )
    if double_quoted_match:
        return double_quoted_match.group(1).strip()

    # Single-quoted: -m 'message'
    single_quoted_match = re.search(
        r"-m\s+'((?:[^'\\]|\\.)*)'", command, re.DOTALL
    )
    if single_quoted_match:
        return single_quoted_match.group(1).strip()

    return None
