"""Shared utility functions for parsing of hook input for Bash commands.

Provides functions used at the entry point of every pre-commit hook:
one that reads and parses the JSON input provided by Claude Code on
standard input, a function that determines whether a Bash command
invokes a specific ``git`` subcommand, a function that determines
whether a Bash command invokes a specific ``git`` subcommand with a
specific flag attached to the same command segment (so that compound
command lines do not cause flags belonging to a different command to
be attributed to the ``git`` invocation), a function that determines
whether a Bash command invokes a specific ``git`` subcommand
without any flag from a given set attached to the same command
segment (complementing the with-flag predicate so that callers
whose semantic category is expressed by a set of mutually-
compatible flags — such as the rebase-abandonment category
expressed by either ``--abort`` or ``--quit`` — can detect
compound commands that carry both in-category and out-of-category
invocations of the same subcommand, neither of which follows from
the negation of the other),
a function that determines
whether a Bash command invokes any ``git`` subcommand that authors at
least one commit on successful execution (so that hooks whose
invariant is about new commits entering history — rather than about
the literal ``git commit`` command — gate every authoring path rather
than only the direct one), a function that extracts the commit message
from a git command string, a character-by-character shell scanner that
returns characters at the top level of the shell (outside quoted
strings, comments, and subshells), a function that replaces
parentheses outside quoted strings and comments with spaces so that
subshell-wrapped tokens are seen as structurally separate from their
surrounding ``git`` and flag tokens during tokenisation, and a
function that detects shell operators anywhere in a command after
stripping quoted strings and comments.
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


# Map from the name of a git subcommand that authors at least one commit
# on successful execution, to the set of flags whose presence as a token
# of the same command segment indicates that this particular invocation
# does not author a commit.  Suppression reasons include aborting or
# quitting a paused operation (``--abort``, ``--quit``), explicitly
# suppressing commit creation (``--no-commit`` and its short form
# ``-n`` on cherry-pick and revert; ``--no-commit`` on merge — note
# that ``-n`` on merge means ``--no-stat`` rather than ``--no-commit``
# and is therefore not a suppression flag for merge; ``--ff-only`` on
# merge, which fast-forwards or fails but never authors a new merge
# commit; ``--squash`` on merge, which stages the merged tree without
# recording a merge commit and requires a follow-up ``git commit``),
# running the subcommand in an informational mode
# (``--show-current-patch`` on rebase and am, ``--edit-todo`` on
# rebase), or running without side effects (``--dry-run`` on commit).
# ``--continue`` and ``--skip`` are not suppression flags because they
# advance a paused operation to the point of authoring a commit; their
# absence from this map means invocations carrying them remain gated.
# The map covers cherry-pick, revert, rebase, am, and merge — the set
# of porcelain subcommands that author commits beyond ``git commit``
# and ``git commit-tree``.  ``git pull`` is intentionally excluded: it
# wraps fetch with merge or rebase, and its most common outcome
# (fast-forward) authors no local commit, making broad gating of
# pull-style invocations disruptive relative to the residual miss (a
# pull that authors a merge commit without conflict), which remains
# observable in ``git log``.
_GIT_SUBCOMMANDS_PRODUCING_A_COMMIT_AND_FLAGS_SUPPRESSING_THE_COMMIT = {
    "commit": frozenset({"--dry-run"}),
    "commit-tree": frozenset(),
    "cherry-pick": frozenset({"--abort", "--quit", "--no-commit", "-n"}),
    "revert": frozenset({"--abort", "--quit", "--no-commit", "-n"}),
    "rebase": frozenset({
        "--abort",
        "--quit",
        "--edit-todo",
        "--show-current-patch",
    }),
    "am": frozenset({"--abort", "--quit", "--show-current-patch"}),
    "merge": frozenset({
        "--abort",
        "--quit",
        "--no-commit",
        "--ff-only",
        "--squash",
    }),
}


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


def flatten_subshell_parentheses_in_shell_command(command: str) -> str:
    """Return a copy of *command* with every ``(`` and ``)`` character
    that appears outside single-quoted strings, double-quoted strings,
    and ``#``-comments replaced by a single space.

    Replacing parentheses with spaces ensures that subshell-wrapped
    tokens — for example, ``(git`` in ``(git cherry-pick --abort)`` —
    are seen by ``shlex.split`` as structurally separate from their
    surrounding ``git`` and flag tokens.  This allows
    ``is_git_subcommand``, ``is_git_subcommand_with_flag``, and
    ``is_git_subcommand_producing_a_new_commit`` to detect
    subcommand-invocation patterns that would otherwise be fused into
    a single unparseable token.

    Parentheses inside single-quoted strings, double-quoted strings
    (with backslash-escape processing), and ``#``-comments are
    preserved verbatim, because they are not structural shell grouping
    characters in those contexts.

    This function does not attempt to parse command substitutions
    (``$(...)``), arithmetic expansions (``$((...))``) , or process
    substitutions (``<(...)``, ``>(...)``); those forms are
    pre-existing blind spots of this module and are out of scope.
    """
    result = []
    inside_single_quote = False
    inside_double_quote = False
    index = 0
    length = len(command)

    while index < length:
        character = command[index]

        if inside_single_quote:
            if character == "'":
                inside_single_quote = False
            result.append(character)
            index += 1
            continue

        if inside_double_quote:
            if character == "\\" and index + 1 < length:
                result.append(character)
                result.append(command[index + 1])
                index += 2
                continue
            if character == '"':
                inside_double_quote = False
            result.append(character)
            index += 1
            continue

        if character == "#":
            while index < length and command[index] != "\n":
                result.append(command[index])
                index += 1
            continue

        if character == "'":
            inside_single_quote = True
            result.append(character)
            index += 1
            continue

        if character == '"':
            inside_double_quote = True
            result.append(character)
            index += 1
            continue

        if character in ("(", ")"):
            result.append(" ")
            index += 1
            continue

        result.append(character)
        index += 1

    return "".join(result)


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


def split_command_into_segments_at_top_level_shell_operators(
    command: str,
) -> list[str]:
    """Split *command* into segments separated by top-level shell
    operators ``;``, ``&&``, ``||``, ``|``, and ``&``, and return the
    segments.

    Top-level means outside quoted strings, comments, and
    parenthesised subshells; the scanning logic for identifying
    top-level characters is reused from
    ``iterate_over_top_level_characters_in_shell_command``.
    Operators that appear inside quotes or subshells belong to those
    enclosed contexts and do not split the command.

    The returned segments are strings of the original command text
    with the separating operator characters removed.  Each segment may
    contain leading or trailing whitespace; callers that tokenise with
    ``shlex.split`` need not strip it.
    """
    indices_of_top_level_characters = {
        index
        for index, _ in iterate_over_top_level_characters_in_shell_command(
            command,
        )
    }
    segment_boundaries: list[tuple[int, int]] = []
    index = 0
    length_of_command = len(command)
    while index < length_of_command:
        if index not in indices_of_top_level_characters:
            index += 1
            continue
        character = command[index]
        if character in ("&", "|"):
            if (
                index + 1 < length_of_command
                and command[index + 1] == character
                and (index + 1) in indices_of_top_level_characters
            ):
                segment_boundaries.append((index, index + 2))
                index += 2
                continue
            segment_boundaries.append((index, index + 1))
            index += 1
            continue
        if character == ";":
            segment_boundaries.append((index, index + 1))
            index += 1
            continue
        index += 1
    if not segment_boundaries:
        return [command]
    segments: list[str] = []
    start_of_current_segment = 0
    for start_of_operator, end_of_operator in segment_boundaries:
        segments.append(command[start_of_current_segment:start_of_operator])
        start_of_current_segment = end_of_operator
    segments.append(command[start_of_current_segment:])
    return segments


def is_git_subcommand_with_flag(
    command: str, subcommand: str, flag: str,
) -> bool:
    """Return True if *command* contains a ``git <subcommand>`` invocation
    that also passes *flag* as a token of the same invocation — not as a
    token of a different command that appears before or after a shell
    operator within the same command line.

    This is the command-segment-scoped counterpart to
    ``is_git_subcommand``.  It answers not just whether *subcommand*
    appears after some ``git`` token, but whether *flag* is part of the
    same command segment, so compound command lines such as
    ``git rebase master && echo --abort`` or
    ``git rebase master; echo --abort`` do not cause *flag* to be
    attributed to the ``git rebase`` invocation when it was actually
    passed to ``echo``.
    """
    command = flatten_subshell_parentheses_in_shell_command(command)
    for segment in split_command_into_segments_at_top_level_shell_operators(
        command,
    ):
        try:
            tokens = shlex.split(segment)
        except ValueError:
            # Skip segments whose quoting is unparseable.  An
            # unparseable segment cannot be reliably analysed, and
            # skipping it is safer than treating its raw text as if
            # the flag were attached to the ``git`` invocation.
            continue
        for position, token in enumerate(tokens):
            if token != "git" and not token.endswith("/git"):
                continue
            tokens_after_git = tokens[position + 1 :]
            if (
                _extract_git_subcommand_from_tokens(tokens_after_git)
                == subcommand
                and flag in tokens_after_git
            ):
                return True
    return False


def is_git_subcommand_without_any_of_flags(
    command: str, subcommand: str, flags: tuple[str, ...],
) -> bool:
    """Return True if *command* contains at least one
    ``git <subcommand>`` invocation whose command segment carries none
    of *flags*.

    This is the counterpart to ``is_git_subcommand_with_flag``: that
    predicate answers whether *any* segment carries at least one of a
    set of flags, while this predicate answers whether *any* segment
    lacks every flag in a set.  The two are not logical negations of
    each other, because a compound command may contain both a segment
    that carries some in-category flag and a segment that lacks every
    in-category flag — for example,
    ``git rebase master && git rebase --abort``.  With
    ``flags=("--abort", "--quit")`` on that command,
    ``is_git_subcommand_with_flag(command, "rebase", "--abort")`` is
    True (the second segment carries ``--abort``) and
    ``is_git_subcommand_without_any_of_flags(command, "rebase",
    ("--abort", "--quit"))`` is also True (the first segment carries
    neither ``--abort`` nor ``--quit``).  Both predicates are needed
    because the presence of one form does not preclude the presence
    of the other.

    Callers use this predicate to determine whether a command's
    treatment should be conditioned on the presence of at least one
    invocation outside a semantic category — for example, to avoid
    routing a compound command to an abandonment-only handler when
    the command also contains a non-abandonment rebase whose output
    still requires validation.
    """
    command = flatten_subshell_parentheses_in_shell_command(command)
    for segment in split_command_into_segments_at_top_level_shell_operators(
        command,
    ):
        try:
            tokens = shlex.split(segment)
        except ValueError:
            # Skip segments whose quoting is unparseable.  An
            # unparseable segment cannot be reliably analysed, and
            # skipping it is safer than treating its raw text as if
            # every listed flag were absent from the ``git``
            # invocation.
            continue
        for position, token in enumerate(tokens):
            if token != "git" and not token.endswith("/git"):
                continue
            tokens_after_git = tokens[position + 1 :]
            if (
                _extract_git_subcommand_from_tokens(tokens_after_git)
                == subcommand
                and not any(flag in tokens_after_git for flag in flags)
            ):
                return True
    return False


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
    command = flatten_subshell_parentheses_in_shell_command(command)
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


def is_git_subcommand_producing_a_new_commit(command: str) -> bool:
    """Return True if *command* contains a ``git`` invocation whose
    subcommand authors at least one commit on successful execution, and
    whose command segment carries no flag that suppresses the authoring
    for this particular invocation.

    The set of commit-authoring subcommands and their per-subcommand
    suppression flags is declared in
    ``_GIT_SUBCOMMANDS_PRODUCING_A_COMMIT_AND_FLAGS_SUPPRESSING_THE_COMMIT``.
    The function scans each top-level command segment separately so that
    compound command lines such as
    ``git status && git cherry-pick --continue`` — where the
    commit-authoring invocation is not the first ``git`` token — are
    detected, and so that a suppression flag attached to a different
    command segment is not misattributed to the git invocation (for
    example, ``git cherry-pick master && echo --abort`` still reports
    True because ``--abort`` belongs to the ``echo`` segment).

    Callers use this predicate in place of
    ``is_git_subcommand(command, "commit")`` when the hook's
    invariant is about new commits entering the repository's history
    rather than about the literal ``git commit`` command.
    """
    command = flatten_subshell_parentheses_in_shell_command(command)
    for segment in split_command_into_segments_at_top_level_shell_operators(
        command,
    ):
        try:
            tokens = shlex.split(segment)
        except ValueError:
            continue
        for position, token in enumerate(tokens):
            if token != "git" and not token.endswith("/git"):
                continue
            tokens_after_git = tokens[position + 1 :]
            subcommand = _extract_git_subcommand_from_tokens(tokens_after_git)
            if (
                subcommand
                not in _GIT_SUBCOMMANDS_PRODUCING_A_COMMIT_AND_FLAGS_SUPPRESSING_THE_COMMIT
            ):
                continue
            suppression_flags = (
                _GIT_SUBCOMMANDS_PRODUCING_A_COMMIT_AND_FLAGS_SUPPRESSING_THE_COMMIT[
                    subcommand
                ]
            )
            if any(flag in tokens_after_git for flag in suppression_flags):
                continue
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
