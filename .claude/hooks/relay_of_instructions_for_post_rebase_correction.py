"""PreToolUse hook that relays instructions for post-rebase correction.

This is a Claude Code PreToolUse hook for the Bash tool.  It is the
delivery companion to the PostToolUse hook
``validate_commit_messages_after_rebase.py``, which validates commit
messages after a git rebase and writes correction instructions to a
results file scoped to the session.

On every Bash tool invocation, this hook checks for the results file.
If found, it reads the correction instructions, deletes the file, and
denies the Bash command with the instructions as
``permissionDecisionReason``.  The model then sees the correction
instructions and can act on them.  On the next Bash tool invocation,
the results file no longer exists and the command proceeds normally.

``git rebase --abort`` is exempt from delivery: when the user signals
that the current rebase chain is being abandoned, the abort must
proceed unimpeded so that the companion PostToolUse hook can run and
clean up both the prior-attempt marker and any stale results file.
A relay denial of the abort would prevent that cleanup from running.

This relay is necessary because Claude Code does not inject
``systemMessage`` output from PostToolUse hooks into the model's
conversation context.  The PostToolUse hook
performs the expensive validation (calling the ``claude`` command-line
interface), and this hook performs the instant delivery (reading a
file and outputting a deny).

Exit code 0 — always (output JSON controls blocking via
permissionDecision).
"""

import json
import sys

from helpers.management_of_session_marker_files import (
    PREFIX_OF_RESULTS_FILE_FOR_INSTRUCTIONS_FOR_POST_REBASE_CORRECTION,
    clean_up_stale_marker_files,
    get_marker_file_path_for_session,
    is_command_for_git_rebase_with_abort,
)
from helpers.parsing_of_hook_input_for_bash_commands import (
    is_git_subcommand_without_flag,
    read_hook_input_from_standard_input,
)


def main() -> int:
    hook_input = read_hook_input_from_standard_input()
    session_id = hook_input.get("session_id", "")

    if not session_id:
        return 0

    tool_input = hook_input.get("tool_input", {})
    command = tool_input.get("command", "")

    # ``git rebase --abort`` must proceed unimpeded so that the
    # companion PostToolUse hook can clean up the prior-attempt
    # marker and the results file as part of abandoning the rebase
    # chain.  Delivering correction instructions here would deny the
    # abort before that cleanup could run.  The carve-out is scoped
    # to commands whose only rebase invocation is the abort: a
    # compound such as ``git rebase master && git rebase --abort``,
    # where the first rebase would run to completion, must remain
    # subject to delivery of any pending correction instructions,
    # because those corrections are the outcome of a previous rebase
    # whose resolution must not be bypassed by an unrelated
    # subsequent rebase pipeline that happens to end in an abort.
    if (
        is_command_for_git_rebase_with_abort(command)
        and not is_git_subcommand_without_flag(command, "rebase", "--abort")
    ):
        return 0

    clean_up_stale_marker_files(
        PREFIX_OF_RESULTS_FILE_FOR_INSTRUCTIONS_FOR_POST_REBASE_CORRECTION,
        session_id,
    )

    results_file_path = get_marker_file_path_for_session(
        PREFIX_OF_RESULTS_FILE_FOR_INSTRUCTIONS_FOR_POST_REBASE_CORRECTION,
        session_id,
    )

    if not results_file_path.exists():
        return 0

    correction_instructions = results_file_path.read_text(encoding="utf-8")
    results_file_path.unlink(missing_ok=True)

    if not correction_instructions.strip():
        return 0

    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": correction_instructions,
        },
    }
    print(json.dumps(output))
    return 0


if __name__ == "__main__":
    sys.exit(main())
