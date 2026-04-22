"""PostToolUse hook that creates and consumes the marker for reading of
CLAUDE.md.

This is a Claude Code PostToolUse hook registered for both the Read
tool and the Bash tool.  It performs two lifecycle operations on the
marker file used by ``inject_claude_md_before_commit.py`` to gate
commits on a fresh read of CLAUDE.md:

1. **Creation** (PostToolUse on Read): When the Read tool is used on a
   file named ``CLAUDE.md``, this hook creates the marker file.

2. **Consumption** (PostToolUse on Bash): When the Bash tool executes
   a command that invokes a ``git`` subcommand authoring at least one
   commit on successful execution — ``git commit``, ``git commit-tree``,
   ``git cherry-pick`` (initial invocation and its ``--continue`` /
   ``--skip`` completion forms), ``git revert`` (likewise), ``git
   rebase`` (likewise), ``git am`` (likewise), and ``git merge``
   (initial and ``--continue``), excluding invocations carrying flags
   that suppress commit authoring such as ``--abort``, ``--quit``,
   ``--no-commit``, ``--ff-only``, ``--show-current-patch``,
   ``--edit-todo``, or ``--dry-run`` — this hook deletes the marker
   file so that the next commit-authoring command requires a fresh
   read.

Gating and consumption are kept symmetric: every subcommand covered by
``inject_claude_md_before_commit.py``'s gate must also consume the
marker here, otherwise the marker would persist after a commit-authoring
command and silently satisfy a subsequent gate without a fresh read.

Consumption happens in PostToolUse (after the command executes) rather
than in the PreToolUse check in ``inject_claude_md_before_commit.py``
(before the command executes) to prevent a denied command — one blocked
by another PreToolUse hook — from invalidating the marker.  If any
PreToolUse hook denies the command, the Bash tool never executes,
PostToolUse does not fire, and the marker persists for the next
attempt.

The marker file is scoped to the session via the ``session_id`` from
the hook input.

Exit code 0 — always.
"""

import json
import pathlib
import sys

from helpers.management_of_session_marker_files import (
    PREFIX_OF_MARKER_FILE_FOR_COMMIT_PERMITTED_AFTER_READING_OF_CLAUDE_MD,
    get_marker_file_path_for_session,
)
from helpers.parsing_of_hook_input_for_bash_commands import (
    is_git_subcommand_producing_a_new_commit,
)


def main() -> int:
    hook_input = json.loads(sys.stdin.read())
    session_id = hook_input.get("session_id", "")
    if not session_id:
        return 0

    tool_input = hook_input.get("tool_input", {})

    # PostToolUse on Read: create marker when CLAUDE.md is read.
    file_path = tool_input.get("file_path", "")
    if file_path and pathlib.Path(file_path).name == "CLAUDE.md":
        marker_file_path = get_marker_file_path_for_session(
            PREFIX_OF_MARKER_FILE_FOR_COMMIT_PERMITTED_AFTER_READING_OF_CLAUDE_MD,
            session_id,
        )
        marker_file_path.touch()
        return 0

    # PostToolUse on Bash: consume marker when any command that invokes
    # a commit-authoring git subcommand executes.  The set covered here
    # mirrors the set gated by ``inject_claude_md_before_commit.py``,
    # so that every command that passes through the gate also consumes
    # the marker and the next commit-authoring command requires a fresh
    # read.
    command = tool_input.get("command", "")
    if command and is_git_subcommand_producing_a_new_commit(command):
        marker_file_path = get_marker_file_path_for_session(
            PREFIX_OF_MARKER_FILE_FOR_COMMIT_PERMITTED_AFTER_READING_OF_CLAUDE_MD,
            session_id,
        )
        marker_file_path.unlink(missing_ok=True)
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
