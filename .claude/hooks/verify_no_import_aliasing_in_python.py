"""Pre-commit hook that verifies no Python import statements use aliasing.

This is a Claude Code PreToolUse hook for the Bash tool. It intercepts
``git commit`` commands, scans staged ``.py`` files for ``import X as Y``
or ``from X import Y as Z`` patterns, and denies the commit if any are
found.

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


def get_staged_python_files() -> list[str]:
    """Return file paths of staged ``.py`` files that were added or
    modified.
    """
    result = subprocess.run(
        [
            "git", "diff", "--cached", "--name-only",
            "--diff-filter=AM", "--", "*.py",
        ],
        capture_output=True,
        text=True,
    )
    return [
        line.strip()
        for line in result.stdout.strip().splitlines()
        if line.strip()
    ]


def get_staged_file_content(file_path: str) -> str:
    """Return the staged content of a file via ``git show :file_path``."""
    result = subprocess.run(
        ["git", "show", f":{file_path}"],
        capture_output=True,
        text=True,
    )
    return result.stdout


# Matches "import X as Y" but not "from X import Y"
IMPORT_AS_PATTERN = re.compile(
    r"^\s*import\s+.+\s+as\s+\w+",
)

# Matches "from X import Y as Z"
FROM_IMPORT_AS_PATTERN = re.compile(
    r"^\s*from\s+.+\s+import\s+.+\s+as\s+\w+",
)


def find_import_aliases_in_file_content(
    file_content: str,
) -> list[tuple[int, str]]:
    """Return a list of (line_number, line_text) tuples for lines that
    contain import aliasing.

    Ignores lines inside triple-quoted strings and comments.
    """
    violations = []
    inside_multiline_string = False
    multiline_string_delimiter = None

    for line_number, line in enumerate(file_content.splitlines(), start=1):
        stripped = line.strip()

        # Track triple-quoted string boundaries.
        if not inside_multiline_string:
            for delimiter in ('"""', "'''"):
                # Count occurrences to handle open and close on same line.
                number_of_occurrences = stripped.count(delimiter)
                if number_of_occurrences % 2 == 1:
                    inside_multiline_string = True
                    multiline_string_delimiter = delimiter
                    break
            if inside_multiline_string:
                continue
        else:
            if multiline_string_delimiter in stripped:
                number_of_occurrences = stripped.count(
                    multiline_string_delimiter
                )
                if number_of_occurrences % 2 == 1:
                    inside_multiline_string = False
                    multiline_string_delimiter = None
            continue

        # Skip comment-only lines.
        if stripped.startswith("#"):
            continue

        if IMPORT_AS_PATTERN.match(line) or FROM_IMPORT_AS_PATTERN.match(line):
            violations.append((line_number, stripped))

    return violations


def build_blocking_message(
    violations_indexed_by_file_path: dict[str, list[tuple[int, str]]],
) -> str:
    """Build the blocking systemMessage listing all import aliasing
    violations.
    """
    lines = [
        "The following import statements use aliasing, which is prohibited",
        "by CLAUDE.md (\"Imported libraries must not be aliased\"):",
        "",
    ]
    for file_path, violations in violations_indexed_by_file_path.items():
        lines.append(f"  File: {file_path}")
        for line_number, line_text in violations:
            lines.append(f"    line {line_number}: {line_text}")
        lines.append("")

    lines.append(
        "Replace each aliased import with the full module name, stage the"
    )
    lines.append("changes, and re-attempt the commit.")
    return "\n".join(lines)


def main() -> int:
    hook_input = read_hook_input_from_stdin()

    tool_input = hook_input.get("tool_input", {})
    command = tool_input.get("command", "")

    # Fast path: not a git commit command.
    if not is_git_commit_command(command):
        return 0

    staged_python_files = get_staged_python_files()
    if not staged_python_files:
        return 0

    violations_indexed_by_file_path: dict[
        str, list[tuple[int, str]]
    ] = {}

    for file_path in staged_python_files:
        file_content = get_staged_file_content(file_path)
        violations = find_import_aliases_in_file_content(file_content)

        if violations:
            violations_indexed_by_file_path[file_path] = violations

    if violations_indexed_by_file_path:
        message = build_blocking_message(violations_indexed_by_file_path)
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
