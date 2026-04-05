"""Pre-commit hook that verifies the commit message accurately describes the
diff from the parent commit when creating, amending, or continuing a rebase.

This catches a common error where the commit message does not accurately
describe the staged changes — whether because the message was written for an
intermediate editing state and no longer accurately describes the total
changes from the parent commit after amendment, or because the message was
simply inaccurate when the commit was first created.

Covered scenarios:

- ``git commit`` (without ``--amend``): Covers new commits.  The diff is
  computed between the staging area and HEAD (the parent of the new commit).
- ``git commit --amend``: Covers direct amends and ``edit`` stops during
  interactive rebase (which use ``git commit --amend`` under the hood).
  The diff is computed between the staging area and HEAD~1 (the parent of
  the commit being amended).
- ``git rebase --continue``: Covers conflict resolution and rebase steps
  where ``--continue`` creates or finalises a commit.  The diff is computed
  between the staging area and HEAD (the parent of the commit about to be
  created).
- ``git merge -m``: Covers merge commits with a custom message.  The diff
  is computed using the three-dot diff (``HEAD...target``) which shows
  changes on the merge target since the merge base.  Only merges with an
  explicit ``-m`` flag are validated; merges that use the auto-generated
  message are skipped.
- ``git commit-tree``: Covers low-level commit creation (plumbing command).
  The diff is computed between the parent commit (``-p``) and the tree
  object using ``git diff-tree``.  Only single-parent commits are
  supported; merge commits with multiple ``-p`` flags are not validated.

Known limitation — ``reword`` during interactive rebase: When
``git rebase -i`` includes ``reword`` actions, git handles the message
change internally within the single ``git rebase -i`` invocation.  No
separate ``git commit --amend`` or ``git rebase --continue`` command is
issued for the reword step, so no PreToolUse hook can intercept it.
This hook therefore cannot verify commit message accuracy for pure
``reword`` actions.  The PostToolUse hook
``validate_commit_messages_after_rebase.py`` closes this gap by
validating all commit messages in the ``ORIG_HEAD..HEAD`` range after
the rebase completes.

This is a Claude Code PreToolUse hook for the Bash tool.  On the first
``git commit``, ``git commit --amend``, ``git rebase --continue``,
``git merge -m``, or ``git commit-tree`` attempt within a session, it
computes the diff between the staging area (or tree object) and the
parent commit, then delegates accuracy analysis to Claude Sonnet via
the ``claude`` command-line interface.  If the message contains inaccuracies — false claims,
references to intermediate states, significant omissions, or
mischaracterisations — the commit is denied.  On the second attempt
within the same session, the hook allows the commit to proceed
regardless, because the analysis is itself non-deterministic.

Graceful degradation: If the ``claude`` command-line interface is not found, times out,
returns an error, or produces unparseable output, the hook allows the
commit and logs a warning to stderr.

Exit code 0 — always (output JSON controls blocking via permissionDecision).
"""

import json
import os
import pathlib
import re
import shlex
import subprocess
import sys

from helpers.deny_then_allow import run_deny_then_allow
from helpers.parsing_of_hook_input_for_bash_commands import (
    extract_commit_message_from_command,
    is_git_subcommand,
    read_hook_input_from_standard_input,
)

PREFIX_OF_MARKER_FILE = (
    ".marker_file_for_pending_review_of_accuracy_of_commit_message_against_diff_from_parent_for_session_"
)

# Store the command from hook input so the closure can access it.
_captured_command = ""


def is_command_for_git_commit_with_amend(command: str) -> bool:
    """Return True if the command is a ``git commit --amend`` invocation.

    Uses the shared ``is_git_subcommand`` to determine whether the
    command is a ``git commit`` invocation (correctly handling git-level
    flags such as ``-C <path>``), then strips heredoc content (between
    ``<<'EOF'`` and ``EOF``) before checking for ``--amend``, to avoid
    false positives when the commit message itself mentions ``--amend``
    as descriptive text.
    """
    if not is_git_subcommand(command, "commit"):
        return False
    command_without_heredoc_content = re.sub(
        r"<<'EOF'\s*\n.*?\n\s*EOF", "", command, flags=re.DOTALL
    )
    return bool(re.search(r"--amend\b", command_without_heredoc_content))


def is_command_for_git_commit_without_amend(command: str) -> bool:
    """Return True if the command is a ``git commit`` invocation without
    ``--amend``.

    Uses the shared ``is_git_subcommand`` to determine whether the
    command is a ``git commit`` invocation (correctly handling git-level
    flags such as ``-C <path>``), then strips heredoc content (between
    ``<<'EOF'`` and ``EOF``) before checking for the absence of
    ``--amend``, to avoid false positives when the commit message itself
    mentions ``--amend`` as descriptive text.
    """
    if not is_git_subcommand(command, "commit"):
        return False
    command_without_heredoc_content = re.sub(
        r"<<'EOF'\s*\n.*?\n\s*EOF", "", command, flags=re.DOTALL
    )
    return not bool(re.search(r"--amend\b", command_without_heredoc_content))


def is_command_for_git_merge(command: str) -> bool:
    """Return True if the command is a ``git merge`` invocation with a
    ``-m`` flag (a custom commit message).

    Merges without ``-m`` use an auto-generated message and do not need
    validation.
    """
    if not is_git_subcommand(command, "merge"):
        return False
    command_without_heredoc_content = re.sub(
        r"<<'EOF'\s*\n.*?\n\s*EOF", "", command, flags=re.DOTALL
    )
    return bool(
        re.search(r"\b-m\b|--message\b", command_without_heredoc_content)
    )


# Merge options that consume a following argument token.
_MERGE_FLAGS_THAT_CONSUME_AN_ARGUMENT = frozenset({
    "-m", "--message", "-s", "-X", "--into-name", "--cleanup",
})


def extract_merge_target_from_command(command: str) -> str | None:
    """Extract the branch or ref being merged from a ``git merge`` command.

    Parses the tokens after ``merge``, skipping known flags and their
    arguments, and returns the first positional argument (the merge
    target).  Returns None if no target can be determined.
    """
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None

    merge_index = None
    for i, token in enumerate(tokens):
        if token == "merge":
            merge_index = i
            break

    if merge_index is None:
        return None

    remaining = tokens[merge_index + 1 :]
    skip_next = False

    for token in remaining:
        if skip_next:
            skip_next = False
            continue
        if token in _MERGE_FLAGS_THAT_CONSUME_AN_ARGUMENT:
            skip_next = True
            continue
        if token.startswith("-"):
            continue
        return token

    return None


def get_diff_for_merge_target(target: str) -> str | None:
    """Return the diff that merging *target* into HEAD would introduce.

    Uses the three-dot diff (``HEAD...target``) which shows changes on
    *target* since the merge base with HEAD — this is what the merge
    commit message should describe.

    Returns None if the diff cannot be computed.
    """
    try:
        result = subprocess.run(
            ["git", "diff", f"HEAD...{target}"],
            capture_output=True,
            encoding="utf-8",
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return None

    if result.returncode != 0:
        return None

    output = result.stdout.strip()
    return output if output else None


def is_command_for_git_rebase_with_continue(command: str) -> bool:
    """Return True if the command is a ``git rebase --continue`` invocation.

    Uses the shared ``is_git_subcommand`` to correctly handle
    git-level flags such as ``-C <path>`` before identifying the
    subcommand, then checks for the ``--continue`` flag.
    """
    if not is_git_subcommand(command, "rebase"):
        return False
    return bool(re.search(r"--continue\b", command))


def get_diff_of_staged_changes_from_parent_for_amend() -> str | None:
    """Return the diff between the staging area and HEAD~1.

    During ``git commit --amend``, the amended commit's parent is HEAD~1.
    The staging area contains the content that will form the amended
    commit.  This diff therefore represents the full content of the
    amended commit relative to its parent.

    Returns None if the diff cannot be computed (for example, an initial
    commit with no parent).
    """
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "HEAD~1"],
            capture_output=True,
            encoding="utf-8",
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return None

    if result.returncode != 0:
        return None

    output = result.stdout.strip()
    return output if output else None


def get_diff_of_staged_changes_from_head() -> str | None:
    """Return the diff between the staging area and HEAD.

    For ``git commit`` (without ``--amend``), HEAD is the parent of the
    new commit.  For ``git rebase --continue``, HEAD is the parent of the
    commit about to be created.  In both cases this diff represents the
    full content of the new commit relative to its parent.

    Returns None if there are no staged changes (which means
    ``--continue`` is merely advancing the rebase without creating a
    new commit, or the new commit has nothing staged).
    """
    try:
        result = subprocess.run(
            ["git", "diff", "--cached"],
            capture_output=True,
            encoding="utf-8",
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return None

    if result.returncode != 0:
        return None

    output = result.stdout.strip()
    return output if output else None


def get_commit_message_of_head() -> str | None:
    """Return the commit message of the current HEAD commit."""
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%B", "HEAD"],
            capture_output=True,
            encoding="utf-8",
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        return None

    if result.returncode != 0:
        return None

    output = result.stdout.strip()
    return output if output else None


def get_pending_commit_message_from_rebase() -> str | None:
    """Return the pending commit message during an active rebase.

    During ``git rebase --continue``, the commit message for the next
    commit is stored in ``.git/rebase-merge/message``.  This function
    reads that file if it exists.

    Returns None if no active rebase is detected or no message file
    exists.
    """
    message_path = pathlib.Path(".git/rebase-merge/message")
    if not message_path.exists():
        return None

    try:
        content = message_path.read_text(encoding="utf-8").strip()
        return content if content else None
    except OSError:
        return None


def is_command_for_git_commit_tree(command: str) -> bool:
    """Return True if the command is a ``git commit-tree`` invocation."""
    return is_git_subcommand(command, "commit-tree")


def extract_tree_and_parent_from_commit_tree_command(
    command: str,
) -> tuple[str, str] | None:
    """Extract the tree SHA and parent SHA from a ``git commit-tree`` command.

    Parses the command to find the positional tree argument and the
    ``-p <parent>`` flag.  Returns ``(tree_sha, parent_sha)`` or None
    if either cannot be determined.  Only the first ``-p`` flag is used;
    merge commits with multiple parents are not supported.
    """
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None

    # Find the tokens after 'commit-tree'.
    commit_tree_index = None
    for i, token in enumerate(tokens):
        if token == "commit-tree":
            commit_tree_index = i
            break

    if commit_tree_index is None:
        return None

    remaining = tokens[commit_tree_index + 1 :]

    tree_sha = None
    parent_sha = None
    skip_next = False

    for i, token in enumerate(remaining):
        if skip_next:
            skip_next = False
            continue
        if token == "-p" and i + 1 < len(remaining):
            parent_sha = remaining[i + 1]
            skip_next = True
        elif token == "-m" and i + 1 < len(remaining):
            skip_next = True
        elif not token.startswith("-") and tree_sha is None:
            tree_sha = token

    if not tree_sha or not parent_sha:
        return None

    return (tree_sha, parent_sha)


def get_diff_between_tree_and_parent(
    tree_sha: str, parent_sha: str,
) -> str | None:
    """Return the diff between a parent commit and a tree object.

    Uses ``git diff-tree -p`` to compute the diff, which is the same
    diff that ``git commit-tree`` would record for the new commit.

    Returns None if the diff cannot be computed.
    """
    try:
        result = subprocess.run(
            ["git", "diff-tree", "-p", parent_sha, tree_sha],
            capture_output=True,
            encoding="utf-8",
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return None

    if result.returncode != 0:
        return None

    output = result.stdout.strip()
    return output if output else None


def build_prompt_for_analysis_of_commit_message_accuracy(
    commit_message: str,
    diff_from_parent: str,
) -> str:
    """Build the prompt for Claude to analyse whether the commit message
    accurately describes the diff from the parent commit."""
    return (
        "You are a commit message accuracy reviewer.  You are given a "
        "commit message and the full diff that the commit will introduce "
        "relative to its parent commit.\n"
        "\n"
        "Determine whether the commit message accurately describes the "
        "changes shown in the diff.  Check for:\n"
        "\n"
        "1. **False claims**: The message describes changes NOT present "
        "in the diff — for example, claiming to 'replace X with Y' when "
        "X does not appear in the removed lines, or claiming to 'remove "
        "Z' when Z is not removed in the diff.\n"
        "\n"
        "2. **Intermediate state references**: The message describes "
        "changes relative to an intermediate editing state rather than "
        "relative to the parent commit.  This happens when a commit is "
        "amended multiple times and the message still describes a delta "
        "between edits rather than the delta from the parent.\n"
        "\n"
        "3. **Significant omissions**: The diff contains changes that "
        "represent a distinct purpose or intent not covered by any part "
        "of the message.  Supporting implementation details that serve a "
        "described change do not need to be mentioned separately.\n"
        "\n"
        "4. **Inaccurate characterisation**: The message mischaracterises "
        "a change — for example, saying 'add' for something that already "
        "existed in the parent and was modified, or saying 'remove' for "
        "something that was restructured.\n"
        "\n"
        "Respond with ONLY a JSON object (no markdown fences, no "
        "explanation outside the JSON):\n"
        "{\n"
        '  "is_accurate": true/false,\n'
        '  "issues": ["description of issue 1", "description of issue 2"]\n'
        "}\n"
        "\n"
        'The "issues" array must be empty if "is_accurate" is true.\n'
        "\n"
        "COMMIT MESSAGE:\n"
        f"{commit_message}\n"
        "\n"
        "DIFF FROM PARENT COMMIT:\n"
        f"{diff_from_parent}"
    )


def parse_analysis_from_claude_response(
    standard_output: str,
) -> dict | None:
    """Parse the analysis result from the Claude command-line interface JSON output.

    Returns the analysis dictionary on success, or None if the response
    cannot be parsed.
    """
    response_text = standard_output
    try:
        parsed_output = json.loads(standard_output)
        if isinstance(parsed_output, dict) and "result" in parsed_output:
            response_text = parsed_output["result"]
    except (json.JSONDecodeError, TypeError):
        pass

    if isinstance(response_text, dict):
        return response_text

    if not isinstance(response_text, str):
        return None

    # Strip markdown code fences if Claude wrapped the JSON in them.
    cleaned = response_text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        end_index = len(lines)
        for i in range(len(lines) - 1, 0, -1):
            if lines[i].strip().startswith("```"):
                end_index = i
                break
        cleaned = "\n".join(lines[1:end_index]).strip()

    try:
        result = json.loads(cleaned)
        if isinstance(result, dict) and "is_accurate" in result:
            return result
    except (json.JSONDecodeError, TypeError):
        pass

    return None


def call_claude_for_analysis(prompt: str) -> dict | None:
    """Call the Claude command-line interface to analyse commit message accuracy.

    Returns the analysis dictionary on success, or None if the command-line interface is
    unavailable, the call fails, or the response is unparseable.
    """
    environment_without_nesting_guard = os.environ.copy()
    environment_without_nesting_guard.pop("CLAUDECODE", None)

    try:
        result = subprocess.run(
            [
                "claude", "-p",
                "--model", "sonnet",
                "--output-format", "json",
            ],
            input=prompt,
            capture_output=True,
            encoding="utf-8",
            timeout=120,
            env=environment_without_nesting_guard,
        )
    except FileNotFoundError:
        print(
            "WARNING: Claude command-line interface not found in PATH; skipping"
            " analysis of commit message accuracy against diff"
            " from parent.",
            file=sys.stderr,
        )
        return None
    except subprocess.TimeoutExpired:
        print(
            "WARNING: Claude command-line interface timed out; skipping"
            " analysis of commit message accuracy against diff"
            " from parent.",
            file=sys.stderr,
        )
        return None

    if result.returncode != 0:
        print(
            f"WARNING: Claude command-line interface exited with code {result.returncode};"
            " skipping analysis of commit message accuracy against diff"
            " from parent.",
            file=sys.stderr,
        )
        return None

    analysis = parse_analysis_from_claude_response(result.stdout)
    if analysis is None:
        print(
            "WARNING: Could not parse Claude command-line interface response as JSON;"
            " skipping analysis of commit message accuracy against diff"
            " from parent.",
            file=sys.stderr,
        )
        return None

    return analysis


def resolve_commit_message_and_diff_from_parent() -> tuple[str, str] | None:
    """Determine the commit message and diff from parent for the current
    command.

    For ``git commit`` (without ``--amend``): The message comes from the
    -m flag.  The diff is computed between the staging area and HEAD (the
    parent of the new commit).

    For ``git commit --amend``: The message comes from the -m flag (or
    from HEAD if no -m flag is present).  The diff is computed between
    the staging area and HEAD~1 (the parent of the commit being amended).

    For ``git rebase --continue``: The message comes from the rebase
    message file (``.git/rebase-merge/message``).  The diff is computed
    between the staging area and HEAD (the parent of the commit about to
    be created).

    Returns a (commit_message, diff_from_parent) tuple, or None if
    the message or diff cannot be determined.
    """
    if is_command_for_git_commit_without_amend(_captured_command):
        commit_message = extract_commit_message_from_command(_captured_command)
        diff_from_parent = get_diff_of_staged_changes_from_head()

    elif is_command_for_git_commit_with_amend(_captured_command):
        commit_message = extract_commit_message_from_command(
            _captured_command
        )
        if commit_message is None:
            commit_message = get_commit_message_of_head()
        diff_from_parent = get_diff_of_staged_changes_from_parent_for_amend()

    elif is_command_for_git_rebase_with_continue(_captured_command):
        commit_message = get_pending_commit_message_from_rebase()
        diff_from_parent = get_diff_of_staged_changes_from_head()

    elif is_command_for_git_merge(_captured_command):
        commit_message = extract_commit_message_from_command(_captured_command)
        merge_target = extract_merge_target_from_command(_captured_command)
        if merge_target is not None:
            diff_from_parent = get_diff_for_merge_target(merge_target)
        else:
            diff_from_parent = None

    elif is_command_for_git_commit_tree(_captured_command):
        commit_message = extract_commit_message_from_command(_captured_command)
        tree_and_parent = extract_tree_and_parent_from_commit_tree_command(
            _captured_command
        )
        if tree_and_parent is not None:
            diff_from_parent = get_diff_between_tree_and_parent(*tree_and_parent)
        else:
            diff_from_parent = None

    else:
        return None

    if not commit_message or not diff_from_parent:
        return None

    return (commit_message, diff_from_parent)


def check_and_build_blocking_message() -> str | None:
    """Run the accuracy check and return a blocking message if the commit
    message does not accurately describe the diff from the parent commit.

    Returns None if the message is accurate or the check cannot be
    performed.
    """
    resolved = resolve_commit_message_and_diff_from_parent()
    if resolved is None:
        return None

    commit_message, diff_from_parent = resolved

    prompt = build_prompt_for_analysis_of_commit_message_accuracy(
        commit_message, diff_from_parent
    )
    analysis = call_claude_for_analysis(prompt)

    if analysis is None:
        return None

    if analysis.get("is_accurate", True):
        return None

    issues = analysis.get("issues", [])
    if not issues:
        return None

    formatted_issues = "\n".join(f"  - {issue}" for issue in issues)

    return (
        "COMMIT MESSAGE ACCURACY REVIEW — COMMIT BLOCKED.\n"
        "\n"
        f"Commit message:\n\n{commit_message}\n"
        "\n"
        "The commit message does not accurately describe the diff from\n"
        "the parent commit.\n"
        "\n"
        f"Issues found:\n{formatted_issues}\n"
        "\n"
        "The commit message must accurately describe the changes relative\n"
        "to the parent commit, not relative to an intermediate editing state.\n"
        "\n"
        "Review the issues above, correct the commit message, and\n"
        "re-attempt the commit.  If this is a false positive, re-attempt\n"
        "the commit unchanged — it will be allowed on the second attempt."
    )


def main() -> int:
    global _captured_command
    hook_input = read_hook_input_from_standard_input()

    tool_input = hook_input.get("tool_input", {})
    command = tool_input.get("command", "")

    if (
        not is_command_for_git_commit_without_amend(command)
        and not is_command_for_git_commit_with_amend(command)
        and not is_command_for_git_rebase_with_continue(command)
        and not is_command_for_git_merge(command)
        and not is_command_for_git_commit_tree(command)
    ):
        return 0

    _captured_command = command

    return run_deny_then_allow(
        hook_input,
        PREFIX_OF_MARKER_FILE,
        check_and_build_blocking_message,
        predicate_for_other_git_commands_that_affect_commits=(
            is_command_for_git_rebase_with_continue
        ),
    )


if __name__ == "__main__":
    sys.exit(main())
