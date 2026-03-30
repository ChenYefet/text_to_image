"""Pre-commit hook that prompts for evaluation of the specification
changelog when the specification file is modified without changes to
the changelog section.

This is a Claude Code PreToolUse hook for the Bash tool.  On the first
``git commit`` attempt within a session where the specification file is
modified but the changelog section (Appendix B: Document Revision
History and the detailed changelogs that follow it) is untouched, the
hook denies the commit and prompts for changelog evaluation.  On the
second attempt within the same session, the hook allows the commit to
proceed regardless — this ensures that specification changes which
genuinely do not warrant a changelog entry never permanently block a
commit.

The hook compares the changelog section of the staged specification
file against the HEAD version (or the pre-rename version for file
renames) to determine whether the changelog was modified.

Exit code 0 — always (output JSON controls blocking via permissionDecision).
"""

import re
import subprocess
import sys

from helpers.deny_then_allow import run_deny_then_allow
from helpers.parsing_of_hook_input_for_bash_commands import (
    read_hook_input_from_standard_input,
)

PREFIX_OF_MARKER_FILE = (
    ".marker_file_for_pending_evaluation_of_specification_changelog_for_session_"
)

SPECIFICATION_FILE_PATTERNS = [
    re.compile(r"text-to-image-spec-v\d+_\d+_\d+\.md"),
    re.compile(r"text_to_image_specification_version_\d+_\d+_\d+\.md"),
]

CHANGELOG_SECTION_HEADING = "### Appendix B: Document Revision History"


def is_specification_file(file_path: str) -> bool:
    """Return True if the file path matches a known specification file
    pattern.
    """
    basename = file_path.rsplit("/", 1)[-1] if "/" in file_path else file_path
    return any(
        pattern.fullmatch(basename) for pattern in SPECIFICATION_FILE_PATTERNS
    )


def get_paths_of_specification_file_from_staged_changes() -> (
    tuple[str, str] | None
):
    """Return (staged_path, head_path) for the specification file if it
    is staged for commit, or None if no specification file is staged.

    For modifications (same filename), both paths are identical.  For
    renames, the staged_path is the new name and head_path is the
    previous name.  For additions (no HEAD version), returns None
    because there is no previous changelog to compare against.
    """
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-status", "-M"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None

    for line in result.stdout.strip().splitlines():
        parts = line.split("\t")
        status = parts[0]

        if status == "M" and len(parts) >= 2:
            file_path = parts[1]
            if is_specification_file(file_path):
                return (file_path, file_path)

        elif status.startswith("R") and len(parts) >= 3:
            old_path = parts[1]
            new_path = parts[2]
            if is_specification_file(new_path):
                return (new_path, old_path)

    return None


def get_content_of_file_from_git_object(object_reference: str) -> str | None:
    """Return the content of a file from a git object reference.

    The object_reference can be ``:<path>`` for the staging area or
    ``HEAD:<path>`` for the HEAD commit.
    """
    result = subprocess.run(
        ["git", "show", object_reference],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        return None
    return result.stdout


def extract_changelog_section(content: str) -> str | None:
    """Extract the changelog section from specification content.

    Returns everything from the changelog heading to the end of the
    file, or None if the heading is not found.
    """
    index = content.find(CHANGELOG_SECTION_HEADING)
    if index == -1:
        return None
    return content[index:]


def check_and_build_blocking_message() -> str | None:
    """Check whether the specification changelog was modified alongside
    specification changes.

    Returns a blocking message if the specification is modified but the
    changelog section is untouched, or None if no action is needed.
    """
    paths_of_specification_file = (
        get_paths_of_specification_file_from_staged_changes()
    )
    if paths_of_specification_file is None:
        return None

    staged_path, head_path = paths_of_specification_file

    staged_content = get_content_of_file_from_git_object(f":{staged_path}")
    head_content = get_content_of_file_from_git_object(f"HEAD:{head_path}")

    if staged_content is None or head_content is None:
        # Cannot compare — allow the commit.
        return None

    staged_changelog = extract_changelog_section(staged_content)
    head_changelog = extract_changelog_section(head_content)

    if staged_changelog is None or head_changelog is None:
        # Changelog section not found — cannot verify.
        return None

    if staged_changelog != head_changelog:
        # Changelog section was modified — no action needed.
        return None

    return (
        "SPECIFICATION CHANGELOG EVALUATION — COMMIT BLOCKED.\n"
        "\n"
        f"The specification file '{staged_path}' has been modified but\n"
        "the changelog section (Appendix B: Document Revision History\n"
        "and the detailed changelogs that follow it) has not been\n"
        "updated.\n"
        "\n"
        "Every commit that modifies the specification must include an\n"
        "explicit evaluation of whether the changelog should be updated.\n"
        "If the change warrants a changelog entry — for example, a new\n"
        "requirement, a changed configuration value, a corrected\n"
        "normative statement, or a restructured section — the changelog\n"
        "entry must be included in the same commit.\n"
        "\n"
        "Evaluate whether a changelog entry is needed and either add\n"
        "one or re-attempt the commit unchanged — it will be allowed\n"
        "on the second attempt."
    )


def main() -> int:
    hook_input = read_hook_input_from_standard_input()
    return run_deny_then_allow(
        hook_input,
        PREFIX_OF_MARKER_FILE,
        check_and_build_blocking_message,
    )


if __name__ == "__main__":
    sys.exit(main())
