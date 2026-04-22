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
creation, age-based cleanup of orphaned markers left behind by
sessions that crashed or exited without consuming their own markers,
and cleanup on ``git rebase --abort``.
"""

import glob
import pathlib
import time

from helpers.parsing_of_hook_input_for_bash_commands import (
    is_git_subcommand_with_flag,
)

PREFIX_OF_MARKER_FILE_FOR_COMMIT_PERMITTED_AFTER_READING_OF_CLAUDE_MD = (
    ".marker_file_for_commit_permitted_after_reading_of_claude_md_for_session_"
)

PREFIX_OF_RESULTS_FILE_FOR_INSTRUCTIONS_FOR_POST_REBASE_CORRECTION = (
    ".results_file_for_instructions_for_post_rebase_correction_for_session_"
)


# Threshold beyond which an unconsumed marker file is treated as
# orphaned and eligible for cleanup by ``clean_up_stale_marker_files``.
# Marker files created by the post-rebase validator and the
# deny-then-allow pattern are ordinarily consumed on the next tool call
# (for results files) or on the next rebase finalising within the same
# session (for the second-attempt marker); both lifetimes are measured
# in seconds to minutes.  A marker that has not been consumed after
# this threshold reflects an abandoned workflow — a session crash, a
# user disengagement, or an abort whose cleanup path did not run.
# 86 400 seconds (24 hours) is long enough to survive any realistic
# pause in an active correction workflow (including an overnight break
# between recognising an issue and returning to correct it) and short
# enough that orphaned markers do not accumulate across days of usage.
# Why not 43 200 seconds (12 hours, half): Would risk deleting markers
# from an ongoing multi-stage correction that the user returned to
# after a longer pause (for example, after a full working day spent
# on unrelated work).  Why not 172 800 seconds (48 hours, double):
# Would allow markers from crashed sessions to survive two days before
# cleanup, widening the window during which they could be mistaken for
# live state by another concurrent session operating under the same
# working directory.
_NUMBER_OF_SECONDS_AFTER_WHICH_A_MARKER_FILE_IS_TREATED_AS_ORPHANED = 86_400


def is_command_for_git_rebase_with_abort(command: str) -> bool:
    """Return True if *command* contains a ``git rebase --abort``
    invocation — that is, ``--abort`` appears as a token of the same
    ``git rebase`` command segment, not elsewhere in a compound command
    line such as ``git rebase master && echo --abort``.
    """
    return is_git_subcommand_with_flag(command, "rebase", "--abort")


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
    """Remove marker files that are overwhelmingly likely to be
    orphaned.

    A marker file is treated as orphaned when its modification time is
    older than
    ``_NUMBER_OF_SECONDS_AFTER_WHICH_A_MARKER_FILE_IS_TREATED_AS_ORPHANED``.
    Marker files for the current session are exempt from the age
    threshold and never removed by this function — they are managed by
    the explicit consume-on-use logic in the hooks that created them.

    The previous implementation unlinked every marker file whose path
    did not contain the current session ID, which meant that when two
    Claude Code sessions ran in the same working directory
    concurrently, each would treat the other's live markers as stale
    and delete them, masking correction instructions and
    second-attempt state.  Filtering by age instead of by session
    membership preserves the live markers of other active sessions
    while still removing markers left behind by sessions that have
    crashed or exited without cleanup.
    """
    current_time_in_seconds = time.time()
    for candidate_marker_path in glob.glob(f"{prefix_of_marker_file}*"):
        if current_session_id in candidate_marker_path:
            continue
        candidate_marker = pathlib.Path(candidate_marker_path)
        try:
            modification_time_in_seconds = (
                candidate_marker.stat().st_mtime
            )
        except FileNotFoundError:
            continue
        age_in_seconds = (
            current_time_in_seconds - modification_time_in_seconds
        )
        if age_in_seconds > (
            _NUMBER_OF_SECONDS_AFTER_WHICH_A_MARKER_FILE_IS_TREATED_AS_ORPHANED
        ):
            candidate_marker.unlink(missing_ok=True)


def get_marker_file_path_for_session(
    prefix_of_marker_file: str,
    session_id: str,
) -> pathlib.Path:
    """Return the path to the session-scoped marker file."""
    return pathlib.Path(f"{prefix_of_marker_file}{session_id}")
