"""Shared utilities for managing session-scoped marker files.

Provides functions for creating, locating, and cleaning up marker files
used by hooks to coordinate state across tool invocations within a
session.  Three patterns use these utilities:

- The deny-then-allow pattern (``deny_then_allow.py``), which creates a
  marker file when a tool call is denied and consumes it on the next
  attempt.
- The read-before-commit pattern (``inject_claude_md_before_commit.py``
  and ``track_reading_of_claude_md.py``), which creates a marker file
  when CLAUDE.md is read and consumes it when a commit is allowed.
- The relay pattern for post-rebase correction
  (``validate_commit_messages_after_rebase.py`` and
  ``relay_of_instructions_for_post_rebase_correction.py``), which writes
  correction instructions to a results file after a rebase and relays
  them via a PreToolUse deny on the next Bash command.

All patterns share the same marker file lifecycle: session-scoped
creation, stale cleanup across sessions, and cleanup on
``git rebase --abort``.
"""

import glob
import pathlib
import re

from helpers.parsing_of_hook_input_for_bash_commands import is_git_subcommand

PREFIX_OF_MARKER_FILE_FOR_COMMIT_PERMITTED_AFTER_READING_OF_CLAUDE_MD = (
    ".marker_file_for_commit_permitted_after_reading_of_claude_md_for_session_"
)

PREFIX_OF_RESULTS_FILE_FOR_INSTRUCTIONS_FOR_POST_REBASE_CORRECTION = (
    ".results_file_for_instructions_for_post_rebase_correction_for_session_"
)


def is_command_for_git_rebase_with_abort(command: str) -> bool:
    """Return True if *command* contains a ``git rebase --abort``."""
    if not is_git_subcommand(command, "rebase"):
        return False
    return bool(re.search(r"--abort\b", command))


def clean_up_all_marker_files_for_current_session(
    session_id: str,
) -> None:
    """Remove all deny-then-allow marker files for the current session.

    This is called when a ``git rebase --abort`` is detected.  Aborting
    a rebase discards the in-progress rebase, invalidating any marker
    files that were created by denied commits during that rebase.
    Without this cleanup, those stale markers would cause the next
    commit to be allowed unconditionally without review.

    All marker files follow the naming convention
    ``.<hook_specific_prefix>session_<session_id>``.  This function
    globs for all files matching ``.*_session_{session_id}`` and
    deletes them.
    """
    for marker_path in glob.glob(f".*_session_{session_id}"):
        pathlib.Path(marker_path).unlink(missing_ok=True)


def clean_up_stale_marker_files(
    prefix_of_marker_file: str,
    current_session_id: str,
) -> None:
    """Remove marker files left behind by previous sessions."""
    for stale_marker_path in glob.glob(f"{prefix_of_marker_file}*"):
        if current_session_id not in stale_marker_path:
            pathlib.Path(stale_marker_path).unlink(missing_ok=True)


def get_marker_file_path_for_session(
    prefix_of_marker_file: str,
    session_id: str,
) -> pathlib.Path:
    """Return the path to the session-scoped marker file."""
    return pathlib.Path(f"{prefix_of_marker_file}{session_id}")
