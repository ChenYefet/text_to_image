"""Pre-commit hook that checks whether files added in the staged commit
appear in the README Project Structure.

This is a Claude Code PreToolUse hook for the Bash tool. It intercepts
``git commit`` commands, parses the README.md Project Structure code
block, and outputs an advisory systemMessage when added files are inside
directories that the structure documents but are not themselves listed.

Exit code 0 — always (advisory only, never blocks).
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


def get_added_files_from_staged_changes() -> list[str]:
    """Return a list of file paths that are staged as Added (A)."""
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-status", "--diff-filter=A"],
        capture_output=True,
        text=True,
    )
    added_files = []
    for line in result.stdout.strip().splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            added_files.append(parts[1])
    return added_files


def parse_readme_project_structure() -> tuple[set[str], set[str]]:
    """Parse the README.md Project Structure code block.

    Returns a tuple of (documented_file_paths,
    parent_directories_of_documented_files).

    documented_file_paths contains full relative paths of files listed in
    the structure (e.g. ``application/main.py``).

    parent_directories_of_documented_files contains the parent directory
    of each documented file (e.g. ``application``, ``tests/unit``, and
    ``""`` for root-level files). This is used to determine whether a
    newly added file is in a location where existing files are already
    documented.
    """
    readme_path = os.path.join(os.getcwd(), "README.md")
    if not os.path.isfile(readme_path):
        return set(), set()

    with open(readme_path, "r", encoding="utf-8") as readme_file:
        content = readme_file.read()

    # Find the Project Structure code block.
    structure_match = re.search(
        r"## Project Structure\s*\n\s*```\s*\n(.*?)```",
        content,
        re.DOTALL,
    )
    if not structure_match:
        return set(), set()

    structure_block = structure_match.group(1)
    documented_file_paths: set[str] = set()
    parent_directories_of_documented_files: set[str] = set()
    directory_stack: list[str] = []

    for line in structure_block.splitlines():
        # Skip empty lines.
        if not line.strip():
            continue

        # Calculate depth by counting tree-drawing prefix groups.
        # Each depth level is represented by 4 characters:
        #   "│   " or "    " or "├── " or "└── "
        stripped_line = line
        depth = 0

        while stripped_line:
            if stripped_line.startswith("│   "):
                stripped_line = stripped_line[4:]
                depth += 1
            elif stripped_line.startswith("    "):
                stripped_line = stripped_line[4:]
                depth += 1
            elif stripped_line.startswith("├── "):
                stripped_line = stripped_line[4:]
                depth += 1
                break
            elif stripped_line.startswith("└── "):
                stripped_line = stripped_line[4:]
                depth += 1
                break
            else:
                break

        # Extract the name (strip inline comments after #).
        name = stripped_line.strip()
        comment_index = name.find("#")
        if comment_index > 0:
            name = name[:comment_index].strip()

        if not name:
            continue

        # Detect whether this entry is a directory.
        is_directory = name.endswith("/")
        if is_directory:
            name = name.rstrip("/")

        # Adjust the directory stack to the current depth.
        # depth is 1-indexed because the root line (text_to_image/)
        # is at depth 0 and the first children are at depth 1.
        # The directory_stack stores parent directories excluding root.
        parent_depth = depth - 1
        directory_stack = directory_stack[:parent_depth]

        if is_directory:
            directory_stack.append(name)
        else:
            full_path = "/".join(directory_stack + [name]) if directory_stack else name
            documented_file_paths.add(full_path)
            # Track the parent directory so we can detect new files
            # added alongside existing documented files.
            parent_directory = "/".join(directory_stack) if directory_stack else ""
            parent_directories_of_documented_files.add(parent_directory)

    return documented_file_paths, parent_directories_of_documented_files


def find_added_files_absent_from_structure(
    added_files: list[str],
    documented_file_paths: set[str],
    parent_directories_of_documented_files: set[str],
) -> list[str]:
    """Return added files whose parent directory already has documented
    entries but the file itself is absent from the structure.
    """
    absent_files = []
    for file_path in added_files:
        # Determine the parent directory of the added file.
        # For root-level files this is ""; for nested files it is
        # the directory portion (e.g. "application" for
        # "application/new_module.py").
        separator_index = file_path.rfind("/")
        if separator_index >= 0:
            parent_directory = file_path[:separator_index]
        else:
            parent_directory = ""

        if (
            parent_directory in parent_directories_of_documented_files
            and file_path not in documented_file_paths
        ):
            absent_files.append(file_path)
    return absent_files


def build_advisory_message(absent_files: list[str]) -> str:
    """Build the advisory systemMessage for added files absent from the
    README Project Structure.
    """
    file_list = "\n".join(f"  - {file_path}" for file_path in absent_files)
    return (
        "The following files are being added in this commit within directories\n"
        "documented in the README Project Structure, but do not appear in the\n"
        "structure themselves:\n"
        "\n"
        f"{file_list}\n"
        "\n"
        "Verify whether these files should be added to the README Project\n"
        "Structure section. If so, update README.md and stage it before\n"
        "committing."
    )


def main() -> int:
    hook_input = read_hook_input_from_stdin()

    tool_input = hook_input.get("tool_input", {})
    command = tool_input.get("command", "")

    # Fast path: not a git commit command.
    if not is_git_commit_command(command):
        return 0

    added_files = get_added_files_from_staged_changes()
    if not added_files:
        return 0

    documented_file_paths, parent_directories_of_documented_files = (
        parse_readme_project_structure()
    )
    if not parent_directories_of_documented_files:
        # No structure found or no documented files — nothing to check.
        return 0

    absent_files = find_added_files_absent_from_structure(
        added_files,
        documented_file_paths,
        parent_directories_of_documented_files,
    )
    if not absent_files:
        return 0

    # Advisory: output a systemMessage but do not block.
    output = {
        "systemMessage": build_advisory_message(absent_files),
    }
    print(json.dumps(output))
    return 0


if __name__ == "__main__":
    sys.exit(main())
