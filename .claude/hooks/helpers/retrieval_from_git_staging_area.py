"""Retrieval of staged file paths and staged file content from git.

Provides the two primitives used by pre-commit hooks that inspect the
staging area: listing the paths of files that are currently staged
(optionally filtered by a git pathspec and by the class of change), and
retrieving the staged content of a given file via ``git show
:<file_path>``.

Both primitives invoke ``git`` as a subprocess, rely on UTF-8 encoding
of file content, and return parsed results.
"""

import subprocess


def get_paths_of_staged_files_matching_pathspec(
    pathspec: str | None = None,
    diff_filter: str = "AM",
) -> list[str]:
    """Return paths of staged files that match *pathspec*.

    When *pathspec* is None, all staged files are returned regardless of
    path.  When *pathspec* is a git pathspec pattern such as ``"*.py"``
    or ``".claude/hooks/*.py"``, only files matching that pathspec are
    returned.

    *diff_filter* selects which classes of changes are included, using
    the letters recognised by ``git diff --diff-filter``.  The default
    ``"AM"`` returns files that were added or modified; pass ``"ACMR"``
    to also include copied and renamed files.

    Callers that need a stricter filter than a git pathspec can provide
    are expected to apply it to the returned list themselves — for
    example, ``.claude/hooks/*.py`` may match files in subdirectories of
    ``.claude/hooks/`` on some platforms, so a caller that wants to
    restrict the result to the top level of ``.claude/hooks/`` must
    filter the list further by path depth.
    """
    arguments_to_git = [
        "git", "diff", "--cached", "--name-only",
        f"--diff-filter={diff_filter}",
    ]
    if pathspec is not None:
        arguments_to_git.extend(["--", pathspec])
    result = subprocess.run(
        arguments_to_git,
        capture_output=True,
        text=True,
    )
    return [
        line.strip()
        for line in result.stdout.strip().splitlines()
        if line.strip()
    ]


def get_staged_content_of_file(file_path: str) -> str:
    """Return the staged content of *file_path* via ``git show :<file_path>``.

    The content is decoded as UTF-8 regardless of the platform's default
    encoding, so that binary replacement artefacts (such as the
    mojibake produced on Windows when the system encoding is ``cp1252``)
    cannot silently slip into downstream analysis.
    """
    result = subprocess.run(
        ["git", "show", f":{file_path}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout
