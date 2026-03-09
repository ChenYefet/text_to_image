"""Pre-commit hook that ensures CLAUDE.md is always committed by itself.

This is a Claude Code PreToolUse hook for the Bash tool. It intercepts
``git commit`` commands and denies the commit if CLAUDE.md is staged
alongside any other files.

Exit code 0 -- always (output JSON controls blocking via permissionDecision).
"""

import json
import re
import subprocess
import sys


def read_hook_input_from_stdin() -> dict:
    """Read the JSON hook input provided by Claude Code on stdin."""
    return json.loads(sys.stdin.read())


def is_git_commit_command(command: str) -> bool:
    """Return True if the command is a git commit invocation."""
    return bool(re.search(r"\bgit\s+commit\b", command))


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


def main() -> int:
    hook_input = read_hook_input_from_stdin()

    tool_input = hook_input.get("tool_input", {})
    command = tool_input.get("command", "")

    # Fast path: not a git commit command.
    if not is_git_commit_command(command):
        return 0

    staged_files = get_staged_files()
    if not staged_files:
        return 0

    claude_md_is_staged = any(
        file_path == "CLAUDE.md" for file_path in staged_files
    )

    if not claude_md_is_staged:
        return 0

    number_of_other_staged_files = len(staged_files) - 1

    if number_of_other_staged_files == 0:
        return 0

    other_staged_files = [
        file_path for file_path in staged_files if file_path != "CLAUDE.md"
    ]
    file_list = "\n".join(f"  - {file_path}" for file_path in other_staged_files)

    message = (
        "CLAUDE.md must be committed in isolation — it cannot be staged\n"
        "alongside other files. The following files are also staged:\n"
        "\n"
        f"{file_list}\n"
        "\n"
        "Either commit CLAUDE.md by itself first and then commit the other\n"
        "files separately, or unstage CLAUDE.md and commit the other files\n"
        "first."
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
