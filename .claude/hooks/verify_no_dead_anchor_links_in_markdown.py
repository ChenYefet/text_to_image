"""Pre-commit hook that verifies no dead anchor links exist in staged
markdown files.

This is a Claude Code PreToolUse hook for the Bash tool. It intercepts
``git commit`` commands, extracts staged ``.md`` files, and validates
that every same-file anchor reference (``](#anchor)``) points to an
existing heading. If dead anchors are found, the commit is denied.

Exit code 0 — always (output JSON controls blocking via permissionDecision).
"""

import json
import sys

from helpers.parsing_of_hook_input_for_bash_commands import (
    is_git_subcommand,
    read_hook_input_from_standard_input,
)
from helpers.retrieval_from_git_staging_area import (
    get_paths_of_staged_files_matching_pathspec,
    get_staged_content_of_file,
)
from helpers.validate_markdown_anchors import (
    extract_anchors_from_headings,
    extract_same_file_anchor_references,
)


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
    hook_input = read_hook_input_from_standard_input()

    tool_input = hook_input.get("tool_input", {})
    command = tool_input.get("command", "")

    # Fast path: not a git commit command.
    if not is_git_subcommand(command, "commit"):
        return 0

    staged_markdown_files = get_paths_of_staged_files_matching_pathspec("*.md")
    if not staged_markdown_files:
        return 0

    dead_anchor_links_indexed_by_file_path: dict[
        str, list[tuple[str, str, int]]
    ] = {}

    for file_path in staged_markdown_files:
        staged_content = get_staged_content_of_file(file_path)
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
