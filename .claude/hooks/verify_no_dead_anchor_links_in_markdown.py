"""Pre-commit hook that verifies no dead anchor links exist in staged
markdown files.

This is a Claude Code PreToolUse hook for the Bash tool. It intercepts
``git commit`` commands, extracts staged ``.md`` files, and validates
that every same-file anchor reference (``](#anchor)``) points to an
existing heading. If dead anchors are found, the commit is denied.

Exit code 0 — always (output JSON controls blocking via permissionDecision).
"""

import importlib.util
import json
import os
import re
import subprocess
import sys


def read_hook_input_from_stdin() -> dict:
    """Read the JSON hook input provided by Claude Code on stdin."""
    return json.loads(sys.stdin.read())


def is_git_commit_command(command: str) -> bool:
    """Return True if the command is a git commit invocation."""
    return bool(re.search(r"\bgit\s+commit\b", command))


def load_anchor_validation_functions() -> tuple:
    """Load ``extract_anchors_from_headings`` and
    ``extract_same_file_anchor_references`` from
    ``helpers/validate_markdown_anchors.py``.

    Returns a tuple of (extract_anchors_from_headings,
    extract_same_file_anchor_references).
    """
    directory_of_this_hook = os.path.dirname(os.path.abspath(__file__))
    path_to_validation_module = os.path.join(
        directory_of_this_hook, "helpers", "validate_markdown_anchors.py"
    )
    specification = importlib.util.spec_from_file_location(
        "validate_markdown_anchors", path_to_validation_module
    )
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return (
        module.extract_anchors_from_headings,
        module.extract_same_file_anchor_references,
    )


def get_staged_markdown_files() -> list[str]:
    """Return file paths of staged ``.md`` files that were added or
    modified.
    """
    result = subprocess.run(
        [
            "git", "diff", "--cached", "--name-only",
            "--diff-filter=AM", "--", "*.md",
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


def build_blocking_message(
    dead_anchor_links_indexed_by_file_path: dict[str, list[tuple[str, str, int]]],
) -> str:
    """Build the blocking systemMessage listing all dead anchor links."""
    lines = [
        "The following anchor links in staged markdown files point to",
        "headings that do not exist. Every same-file anchor reference",
        "must correspond to a valid heading:",
        "",
    ]
    for file_path, dead_links in dead_anchor_links_indexed_by_file_path.items():
        lines.append(f"  File: {file_path}")
        for link_text, anchor, line_number in dead_links:
            lines.append(
                f"    line {line_number}: [{link_text}](#{anchor})"
            )
        lines.append("")

    lines.append(
        "Fix or remove the dead anchor links, stage the changes, and"
    )
    lines.append("re-attempt the commit.")
    return "\n".join(lines)


def main() -> int:
    hook_input = read_hook_input_from_stdin()

    tool_input = hook_input.get("tool_input", {})
    command = tool_input.get("command", "")

    # Fast path: not a git commit command.
    if not is_git_commit_command(command):
        return 0

    staged_markdown_files = get_staged_markdown_files()
    if not staged_markdown_files:
        return 0

    extract_anchors_from_headings, extract_same_file_anchor_references = (
        load_anchor_validation_functions()
    )
    dead_anchor_links_indexed_by_file_path: dict[
        str, list[tuple[str, str, int]]
    ] = {}

    for file_path in staged_markdown_files:
        staged_content = get_staged_file_content(file_path)
        anchors = extract_anchors_from_headings(staged_content)
        references = extract_same_file_anchor_references(staged_content)

        dead_links = []
        for link_text, anchor, line_number in references:
            if anchor not in anchors:
                dead_links.append((link_text, anchor, line_number))

        if dead_links:
            dead_anchor_links_indexed_by_file_path[file_path] = dead_links

    if dead_anchor_links_indexed_by_file_path:
        message = build_blocking_message(
            dead_anchor_links_indexed_by_file_path
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
