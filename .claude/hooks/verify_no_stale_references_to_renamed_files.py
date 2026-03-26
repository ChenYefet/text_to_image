"""Pre-commit hook that searches the repository for stale references to
files renamed in the staged commit.

This is a Claude Code PreToolUse hook for the Bash tool. It intercepts
``git commit`` commands, detects renamed files, and searches the entire
repository for references to the old file path. If stale references are
found, the commit is denied with a systemMessage listing each reference.

Exit code 0 — always (output JSON controls blocking via permissionDecision).
"""

import json
import os
import subprocess
import sys

from helpers.parsing_of_hook_input_for_bash_commands import (
    is_git_subcommand,
    read_hook_input_from_standard_input,
)
from helpers.searching_for_references_to_file_paths_in_repository import (
    convert_file_path_to_path_of_python_module,
    search_repository_for_references,
)


def get_renamed_files_from_staged_changes() -> list[tuple[str, str]]:
    """Return a list of (old_path, new_path) tuples for renamed files."""
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-status", "--diff-filter=R"],
        capture_output=True,
        text=True,
    )
    renamed_files = []
    for line in result.stdout.strip().splitlines():
        parts = line.split("\t")
        if len(parts) >= 3:
            # Format: R100\told_path\tnew_path (or R0xx for partial matches)
            old_path = parts[1]
            new_path = parts[2]
            renamed_files.append((old_path, new_path))
    return renamed_files


def collect_stale_references_for_renamed_file(
    old_path: str,
    new_path: str,
) -> list[tuple[str, int, str]]:
    """Search the repository for all references to the old path of a
    renamed file.

    Searches for:
    1. The full old relative path.
    2. The old Python dotted module path (if applicable).
    3. The old basename (if unambiguous — i.e. no other tracked file
       shares the same basename).
    """
    all_references: list[tuple[str, int, str]] = []
    seen_locations: set[tuple[str, int]] = set()
    excluded_files = [old_path, new_path]

    def add_unique_references(
        references: list[tuple[str, int, str]],
    ) -> None:
        for file_path, line_number, line_content in references:
            location = (file_path, line_number)
            if location not in seen_locations:
                seen_locations.add(location)
                all_references.append((file_path, line_number, line_content))

    # Search for the full old path.
    add_unique_references(
        search_repository_for_references(old_path, excluded_files)
    )

    # Search for the Python dotted module path.
    old_module_path = convert_file_path_to_path_of_python_module(old_path)
    if old_module_path:
        add_unique_references(
            search_repository_for_references(old_module_path, excluded_files)
        )

    # Search for the basename if unambiguous.
    old_basename = os.path.basename(old_path)
    if old_basename and old_basename != old_path:
        # Check if the basename is unique among tracked files.
        basename_check = subprocess.run(
            ["git", "ls-files"],
            capture_output=True,
            text=True,
        )
        tracked_files_with_same_basename = [
            tracked_file
            for tracked_file in basename_check.stdout.strip().splitlines()
            if os.path.basename(tracked_file) == old_basename
            and tracked_file != old_path
        ]
        if not tracked_files_with_same_basename:
            add_unique_references(
                search_repository_for_references(old_basename, excluded_files)
            )

    return all_references


def build_blocking_message(
    renamed_files_with_references: list[
        tuple[str, str, list[tuple[str, int, str]]]
    ],
) -> str:
    """Build the blocking systemMessage for renamed files with stale
    references.
    """
    lines = [
        "The following files were renamed in this commit, but stale references",
        "to the old names were found:",
        "",
    ]
    for old_path, new_path, references in renamed_files_with_references:
        lines.append(f"  Renamed: {old_path} → {new_path}")
        lines.append("")
        lines.append(f'  Stale references to "{old_path}":')
        for file_path, line_number, line_content in references:
            truncated_content = (
                line_content[:80] + "…" if len(line_content) > 80 else line_content
            )
            lines.append(f"    - {file_path}:{line_number}  — {truncated_content}")
        lines.append("")

    lines.append(
        "Update all stale references to use the new name, stage the changes,"
    )
    lines.append("and re-attempt the commit.")
    return "\n".join(lines)


def build_advisory_message(
    renamed_files_without_references: list[tuple[str, str]],
) -> str:
    """Build the advisory systemMessage for renamed files with no stale
    references found by automated search.
    """
    file_list = "\n".join(
        f"  - {old_path} → {new_path}"
        for old_path, new_path in renamed_files_without_references
    )
    return (
        "The following files were renamed in this commit. No stale references\n"
        "were found by automated search, but verify that the README Project\n"
        "Structure, run instructions, and prose references are updated:\n"
        "\n"
        f"{file_list}"
    )


def main() -> int:
    hook_input = read_hook_input_from_standard_input()

    tool_input = hook_input.get("tool_input", {})
    command = tool_input.get("command", "")

    # Fast path: not a git commit command.
    if not is_git_subcommand(command, "commit"):
        return 0

    renamed_files = get_renamed_files_from_staged_changes()
    if not renamed_files:
        return 0

    renamed_files_with_references: list[
        tuple[str, str, list[tuple[str, int, str]]]
    ] = []
    renamed_files_without_references: list[tuple[str, str]] = []

    for old_path, new_path in renamed_files:
        references = collect_stale_references_for_renamed_file(old_path, new_path)
        if references:
            renamed_files_with_references.append((old_path, new_path, references))
        else:
            renamed_files_without_references.append((old_path, new_path))

    if renamed_files_with_references:
        # Blocking: deny the commit.
        message = build_blocking_message(renamed_files_with_references)
        if renamed_files_without_references:
            message += "\n\n" + build_advisory_message(
                renamed_files_without_references
            )
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": message,
            },
        }
        print(json.dumps(output))
    elif renamed_files_without_references:
        # Advisory: allow but notify.
        output = {
            "systemMessage": build_advisory_message(
                renamed_files_without_references
            ),
        }
        print(json.dumps(output))

    return 0


if __name__ == "__main__":
    sys.exit(main())
