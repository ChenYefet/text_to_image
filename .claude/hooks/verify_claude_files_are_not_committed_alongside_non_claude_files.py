"""Pre-commit hook that prevents Claude files from being committed
alongside non-Claude files.

A Claude file is any file whose path is ``CLAUDE.md`` or starts with
``.claude/``.  This hook intercepts ``git commit`` and
``git commit --amend`` commands and denies the commit if any Claude file
would appear alongside any non-Claude file in the resulting commit.
Claude files may be committed by themselves or together with other Claude
files, but not with any other files.

For plain commits, the check inspects the staging area
(``git diff --cached``).  For amends, the check inspects the full diff
between the staging area and HEAD~1 (the parent of the commit being
amended), because files from the original commit that were not re-staged
do not appear in ``git diff --cached`` but will still be part of the
amended commit.

Exit code 0 -- always (output JSON controls blocking via permissionDecision).
"""

import json
import re
import subprocess
import sys

from helpers.parsing_of_hook_input_for_bash_commands import (
    is_git_subcommand,
    read_hook_input_from_standard_input,
)


def _is_claude_file(file_path: str) -> bool:
    """Return True if the file is a Claude file."""
    return file_path == "CLAUDE.md" or file_path.startswith(".claude/")


def _is_amend_command(command: str) -> bool:
    """Return True if the command contains ``--amend`` outside heredoc content."""
    command_without_heredoc_content = re.sub(
        r"<<'EOF'\s*\n.*?\n\s*EOF", "", command, flags=re.DOTALL
    )
    return bool(re.search(r"--amend\b", command_without_heredoc_content))


def get_staged_files() -> list[str]:
    """Return file paths of all staged files."""
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        capture_output=True,
        text=True,
    )
    return [
        line.strip()
        for line in result.stdout.strip().splitlines()
        if line.strip()
    ]


def get_files_in_amended_commit() -> list[str]:
    """Return file paths that will differ between the amended commit and
    its parent.

    During ``git commit --amend``, the parent of the amended commit is
    HEAD~1.  Comparing the staging area against HEAD~1 captures both
    files that were in the original commit and files that were newly
    staged for the amend.
    """
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "HEAD~1"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    return [
        line.strip()
        for line in result.stdout.strip().splitlines()
        if line.strip()
    ]


def main() -> int:
    hook_input = read_hook_input_from_standard_input()

    tool_input = hook_input.get("tool_input", {})
    command = tool_input.get("command", "")

    # Fast path: not a git commit command.
    if not is_git_subcommand(command, "commit"):
        return 0

    if _is_amend_command(command):
        staged_files = get_files_in_amended_commit()
    else:
        staged_files = get_staged_files()
    if not staged_files:
        return 0

    staged_claude_files = [
        file_path for file_path in staged_files if _is_claude_file(file_path)
    ]

    if not staged_claude_files:
        return 0

    staged_non_claude_files = [
        file_path for file_path in staged_files if not _is_claude_file(file_path)
    ]

    if not staged_non_claude_files:
        return 0

    claude_file_list = "\n".join(
        f"  - {file_path}" for file_path in staged_claude_files
    )
    non_claude_file_list = "\n".join(
        f"  - {file_path}" for file_path in staged_non_claude_files
    )

    message = (
        "Claude files (CLAUDE.md and .claude/*) cannot be committed\n"
        "alongside non-Claude files.\n"
        "\n"
        "Staged Claude files:\n"
        f"{claude_file_list}\n"
        "\n"
        "Staged non-Claude files:\n"
        f"{non_claude_file_list}\n"
        "\n"
        "Either commit the Claude files by themselves first and then\n"
        "commit the other files separately, or unstage the Claude files\n"
        "and commit the other files first."
    )

    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": message,
        },
    }
    print(json.dumps(output))
    return 0


if __name__ == "__main__":
    sys.exit(main())
