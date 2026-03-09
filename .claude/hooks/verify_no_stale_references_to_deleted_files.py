"""Pre-commit hook that searches the repository for stale references to
files deleted in the staged commit.

This is a Claude Code PreToolUse hook for the Bash tool. It intercepts
``git commit`` commands, detects deleted files, and searches the entire
repository for references to the deleted file path. If stale references
are found, the commit is denied with a systemMessage listing each
reference.

Exit code 0 — always (output JSON controls blocking via permissionDecision).
"""

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


def get_deleted_files_from_staged_changes() -> list[str]:
    """Return a list of file paths that are staged as Deleted (D)."""
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-status", "--diff-filter=D"],
        capture_output=True,
        text=True,
    )
    deleted_files = []
    for line in result.stdout.strip().splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            deleted_files.append(parts[1])
    return deleted_files


def convert_file_path_to_python_module_path(file_path: str) -> str | None:
    """Convert a .py file path to its dotted Python module path.

    Returns None if the file is not a Python file.
    For example, ``application/main.py`` becomes ``application.main``.
    """
    if not file_path.endswith(".py"):
        return None
    module_path = file_path[:-3].replace("/", ".").replace("\\", ".")
    # Strip trailing .__init__ since that module is typically imported
    # via the package name alone.
    if module_path.endswith(".__init__"):
        module_path = module_path[: -len(".__init__")]
    return module_path


def search_repository_for_references(
    search_term: str,
    excluded_file_paths: list[str] | None = None,
) -> list[tuple[str, int, str]]:
    """Search the repository for occurrences of search_term using git grep.

    Returns a list of (file_path, line_number, line_content) tuples.
    Excludes any files listed in excluded_file_paths.
    """
    result = subprocess.run(
        ["git", "grep", "-n", "--fixed-strings", search_term],
        capture_output=True,
        text=True,
    )
    references = []
    excluded = set(excluded_file_paths or [])
    for line in result.stdout.strip().splitlines():
        # Format: file_path:line_number:line_content
        match = re.match(r"^(.+?):(\d+):(.*)$", line)
        if match:
            file_path = match.group(1)
            line_number = int(match.group(2))
            line_content = match.group(3).strip()
            if file_path not in excluded:
                references.append((file_path, line_number, line_content))
    return references


def collect_stale_references_for_deleted_file(
    deleted_path: str,
) -> list[tuple[str, int, str]]:
    """Search the repository for all references to a deleted file.

    Searches for:
    1. The full relative path.
    2. The Python dotted module path (if applicable).
    3. The basename (if unambiguous — i.e. no other tracked file
       shares the same basename).
    """
    all_references: list[tuple[str, int, str]] = []
    seen_locations: set[tuple[str, int]] = set()
    excluded_files = [deleted_path]

    def add_unique_references(
        references: list[tuple[str, int, str]],
    ) -> None:
        for file_path, line_number, line_content in references:
            location = (file_path, line_number)
            if location not in seen_locations:
                seen_locations.add(location)
                all_references.append((file_path, line_number, line_content))

    # Search for the full path.
    add_unique_references(
        search_repository_for_references(deleted_path, excluded_files)
    )

    # Search for the Python dotted module path.
    module_path = convert_file_path_to_python_module_path(deleted_path)
    if module_path:
        add_unique_references(
            search_repository_for_references(module_path, excluded_files)
        )

    # Search for the basename if unambiguous.
    basename = os.path.basename(deleted_path)
    if basename and basename != deleted_path:
        # Check if the basename is unique among tracked files (excluding
        # the file being deleted).
        basename_check = subprocess.run(
            ["git", "ls-files"],
            capture_output=True,
            text=True,
        )
        tracked_files_with_same_basename = [
            tracked_file
            for tracked_file in basename_check.stdout.strip().splitlines()
            if os.path.basename(tracked_file) == basename
            and tracked_file != deleted_path
        ]
        if not tracked_files_with_same_basename:
            add_unique_references(
                search_repository_for_references(basename, excluded_files)
            )

    return all_references


def build_blocking_message(
    deleted_files_with_references: list[
        tuple[str, list[tuple[str, int, str]]]
    ],
) -> str:
    """Build the blocking systemMessage for deleted files with stale
    references.
    """
    lines = [
        "The following files were deleted in this commit, but references to",
        "them were found elsewhere in the repository:",
        "",
    ]
    for deleted_path, references in deleted_files_with_references:
        lines.append(f"  Deleted: {deleted_path}")
        lines.append("")
        lines.append(f'  References to "{deleted_path}":')
        for file_path, line_number, line_content in references:
            truncated_content = (
                line_content[:80] + "…" if len(line_content) > 80 else line_content
            )
            lines.append(f"    - {file_path}:{line_number}  — {truncated_content}")
        lines.append("")

    lines.append(
        "Remove or replace all references to the deleted file, stage the"
    )
    lines.append("changes, and re-attempt the commit.")
    return "\n".join(lines)


def build_advisory_message(
    deleted_files_without_references: list[str],
) -> str:
    """Build the advisory systemMessage for deleted files with no stale
    references found by automated search.
    """
    file_list = "\n".join(
        f"  - {deleted_path}"
        for deleted_path in deleted_files_without_references
    )
    return (
        "The following files were deleted in this commit. No stale references\n"
        "were found by automated search, but verify that the README Project\n"
        "Structure and any prose references are updated:\n"
        "\n"
        f"{file_list}"
    )


def main() -> int:
    hook_input = read_hook_input_from_stdin()

    tool_input = hook_input.get("tool_input", {})
    command = tool_input.get("command", "")

    # Fast path: not a git commit command.
    if not is_git_commit_command(command):
        return 0

    deleted_files = get_deleted_files_from_staged_changes()
    if not deleted_files:
        return 0

    deleted_files_with_references: list[
        tuple[str, list[tuple[str, int, str]]]
    ] = []
    deleted_files_without_references: list[str] = []

    for deleted_path in deleted_files:
        references = collect_stale_references_for_deleted_file(deleted_path)
        if references:
            deleted_files_with_references.append((deleted_path, references))
        else:
            deleted_files_without_references.append(deleted_path)

    if deleted_files_with_references:
        # Blocking: deny the commit.
        message = build_blocking_message(deleted_files_with_references)
        if deleted_files_without_references:
            message += "\n\n" + build_advisory_message(
                deleted_files_without_references
            )
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": message,
            },
        }
        print(json.dumps(output))
    elif deleted_files_without_references:
        # Advisory: allow but notify.
        output = {
            "systemMessage": build_advisory_message(
                deleted_files_without_references
            ),
        }
        print(json.dumps(output))

    return 0


if __name__ == "__main__":
    sys.exit(main())
