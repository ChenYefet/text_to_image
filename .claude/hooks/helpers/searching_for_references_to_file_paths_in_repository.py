"""Shared utility functions for searching for references to file paths
in a repository.

Provides functions shared by pre-commit hooks that detect stale
references to renamed or deleted files: one that converts a ``.py``
file path to the dot-separated path of its Python module, and one that
searches the repository for all occurrences of a search term using
``git grep``.
"""

import re
import subprocess
import sys


def convert_file_path_to_path_of_python_module(file_path: str) -> str | None:
    """Convert a .py file path to the dot-separated path of its Python module.

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
    try:
        result = subprocess.run(
            ["git", "grep", "-n", "--fixed-strings", search_term],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        print(
            "WARNING: git grep timed out while searching for"
            f" references to {search_term!r}.",
            file=sys.stderr,
        )
        return []
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
