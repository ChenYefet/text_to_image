"""PostToolUse hook that validates commit messages after a git rebase
completes.

This hook closes the gap where ``reword`` actions during
``git rebase -i`` cannot be intercepted by PreToolUse hooks.  The
PreToolUse hooks that validate commit message format and accuracy fire
before a Bash command executes, but ``git rebase -i`` handles reword
steps internally within a single command invocation — no separate
``git commit`` is issued for each reword, so no PreToolUse hook can
intercept the individual message changes.

After the rebase command finishes, this hook identifies the newly
created commits via ``ORIG_HEAD..HEAD``, retrieves each commit's
message and diff from its parent, and delegates validation to Claude
Sonnet via the ``claude`` command-line interface in a single batched call.

Validation covers both format (header + bullet points, past-tense
verbs) and accuracy (message accurately describes the diff from
parent).

The hook only fires when all of the following are true:

1. The command is ``git rebase`` (not ``--continue``, ``--abort``, or
   ``--skip`` — ``--continue`` is handled by the PreToolUse hooks,
   and ``--abort``/``--skip`` do not create commits).
2. The rebase has completed (no ``.git/rebase-merge/`` or
   ``.git/rebase-apply/`` directory exists).
3. New commits were created (``ORIG_HEAD..HEAD`` is non-empty).

If issues are found, the hook injects a ``systemMessage`` instructing
Claude to correct the problematic commit messages.  The validation
model also produces corrected commit messages, which are included in
the ``systemMessage`` so that Claude's correction task is purely
mechanical — applying pre-written messages rather than interpreting
issues and composing fixes.  Since this is a PostToolUse hook, it
cannot block the command — it can only report.

Graceful degradation: If the ``claude`` command-line interface is not found, times out,
returns an error, or produces unparseable output, the hook exits
silently without injecting any message.

Exit code 0 — always (output JSON controls behaviour via systemMessage).
"""

import glob
import json
import pathlib
import re
import subprocess
import sys

from helpers.invoking_claude_cli_for_analysis import call_claude_cli_for_analysis
from helpers.parsing_of_hook_input_for_bash_commands import (
    is_git_subcommand,
    read_hook_input_from_standard_input,
)


PREFIX_OF_MARKER_FILE = (
    ".marker_file_for_pending_post_rebase_validation_for_session_"
)


def is_rebase_still_in_progress() -> bool:
    """Return True if a rebase is currently in progress (not yet completed).

    Git creates ``.git/rebase-merge/`` during ``git rebase -i`` and
    ``git rebase``, and ``.git/rebase-apply/`` during ``git am`` and
    older-style rebases.  The presence of either directory indicates
    that the rebase stopped (for conflicts or editing) and has not yet
    completed.
    """
    return (
        pathlib.Path(".git/rebase-merge").is_dir()
        or pathlib.Path(".git/rebase-apply").is_dir()
    )


def get_new_commits_after_rebase() -> list[str]:
    """Return the commit hashes created by the most recent rebase.

    Uses ``ORIG_HEAD..HEAD`` to identify commits that are reachable
    from HEAD but were not reachable from the pre-rebase HEAD.
    Returns commits in chronological order (oldest first).  Returns
    an empty list if ORIG_HEAD is not set or no new commits exist.
    """
    try:
        result = subprocess.run(
            ["git", "log", "--format=%H", "--reverse", "ORIG_HEAD..HEAD"],
            capture_output=True,
            encoding="utf-8",
            timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []

    if result.returncode != 0:
        return []

    return [h.strip() for h in result.stdout.strip().split("\n") if h.strip()]


def get_commit_message(commit_hash: str) -> str | None:
    """Return the commit message of the given commit."""
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%B", commit_hash],
            capture_output=True,
            encoding="utf-8",
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        return None

    if result.returncode != 0:
        return None

    output = result.stdout.strip()
    return output if output else None


def get_diff_from_parent(commit_hash: str) -> str | None:
    """Return the diff between the commit and its first parent.

    Uses ``git diff-tree -p`` which shows the changes introduced by
    the commit relative to its first parent.

    Note: For root commits (commits with no parent), ``git diff-tree``
    with a single argument produces no output.  This causes the function
    to return None, which means root commits are silently skipped by the
    validation in ``main()`` (which requires both message and diff).

    Returns None if the diff cannot be computed or is empty.
    """
    try:
        result = subprocess.run(
            ["git", "diff-tree", "-p", commit_hash],
            capture_output=True,
            encoding="utf-8",
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return None

    if result.returncode != 0:
        return None

    output = result.stdout.strip()
    if not output:
        return None

    return output


def build_validation_prompt(commits_data: list[dict]) -> str:
    """Build a single prompt that validates all commits' messages for
    format and accuracy."""
    commits_text = ""
    for i, data in enumerate(commits_data, 1):
        commits_text += (
            f"\n--- COMMIT {i} ({data['hash']}) ---\n"
            f"MESSAGE:\n{data['message']}\n\n"
            f"DIFF FROM PARENT:\n{data['diff']}\n"
        )

    return (
        "You are validating commit messages after a git rebase.  For "
        "each commit below, check two things:\n"
        "\n"
        "1. **Format**: The message must have a single subject line "
        "(header).  If a body is present (text after a blank line "
        "following the header), it must use bullet points (lines "
        "beginning with `- `), never prose paragraphs.  Each bullet "
        "point that begins with a verb must use past tense (e.g. "
        "'Added', 'Removed', 'Updated', 'Fixed').  A bullet point "
        "that begins with a present-tense verb (e.g. 'Add', 'Remove') "
        "is a violation.  A commit message with only a subject line "
        "and no body is acceptable.\n"
        "\n"
        "2. **Accuracy**: The message must accurately describe the "
        "changes shown in the diff from the parent commit.  Check for "
        "false claims (changes described but not present in the diff), "
        "significant omissions (distinct purposes not covered by the "
        "message), and inaccurate characterisations (e.g. 'add' for "
        "something that was modified, 'remove' for something "
        "restructured).\n"
        f"{commits_text}\n"
        "\n"
        "Return ONLY a JSON object (no markdown fences, no surrounding "
        "text):\n"
        "{\n"
        '  "commits": [\n'
        "    {\n"
        '      "hash": "...",\n'
        '      "format_valid": true/false,\n'
        '      "accuracy_valid": true/false,\n'
        '      "issues": ["description of issue 1", ...],\n'
        '      "corrected_message": "full corrected commit message"\n'
        "    }\n"
        "  ]\n"
        "}\n"
        "\n"
        'The "issues" array must be empty if both checks pass.  When '
        '"issues" is non-empty, "corrected_message" must contain the '
        "full corrected commit message — header line, blank line, and "
        "bullet-point body — that resolves every listed issue while "
        "accurately describing the diff from the parent commit.  When "
        '"issues" is empty, omit "corrected_message".'
    )


def call_claude_for_validation(prompt: str) -> dict | None:
    """Call the ``claude`` command-line interface to validate commit messages."""
    return call_claude_cli_for_analysis(
        prompt,
        timeout_in_seconds=120,
        description_of_analysis="post-rebase commit message validation",
    )


def build_system_message_for_automatic_correction(
    problematic_commits: list[dict],
) -> str:
    """Build the systemMessage that instructs Claude to correct commit
    messages automatically via a non-interactive rebase.

    When corrected messages are available (provided by the validation
    model), the instruction includes the exact replacement text so that
    Claude's task is purely mechanical.  When a corrected message is
    not available for a commit, Claude is asked to compose one.

    This is used on the first firing within a session.
    """
    all_have_corrections = all(
        "corrected_message" in commit for commit in problematic_commits
    )

    lines = [
        "POST-REBASE COMMIT MESSAGE VALIDATION — ISSUES FOUND.",
        "",
        "The following commits created by the rebase have commit message",
        "issues that must be corrected:",
        "",
    ]

    for commit in problematic_commits:
        lines.append(f"  {commit['hash']}:")
        lines.append("    Current message:")
        for message_line in commit["message"].splitlines():
            lines.append(f"      {message_line}")
        lines.append("    Issues:")
        for issue in commit["issues"]:
            lines.append(f"    - {issue}")
        if "corrected_message" in commit:
            lines.append("    Corrected message (apply exactly as shown):")
            for message_line in commit["corrected_message"].splitlines():
                lines.append(f"      {message_line}")
        lines.append("")

    if all_have_corrections:
        lines.extend([
            "Apply the corrected messages above exactly as shown using a",
            "non-interactive ``git rebase -i`` by setting",
            "``GIT_SEQUENCE_EDITOR`` to a ``sed`` command that marks the",
            "affected commits as ``reword``, and ``GIT_EDITOR`` to a",
            "script that writes the corrected message.  Do not modify",
            "the corrected messages — apply them verbatim.",
        ])
    else:
        lines.extend([
            "Correct the commit messages using a non-interactive",
            "``git rebase -i`` by setting ``GIT_SEQUENCE_EDITOR`` to a",
            "``sed`` command that marks the affected commits as ``reword``,",
            "and ``GIT_EDITOR`` to a script that writes the corrected",
            "message.  Where a corrected message is provided above, apply",
            "it exactly as shown.  Where no corrected message is provided,",
            "compose one that follows the header + bullet point format and",
            "accurately describes the diff from the parent commit.",
        ])

    return "\n".join(lines)


def build_system_message_for_manual_resolution(
    problematic_commits: list[dict],
) -> str:
    """Build the systemMessage that asks Claude to present remaining
    issues to the user for manual resolution.

    This is used on the second firing within a session, after an
    automatic correction attempt has already been made.
    """
    lines = [
        "POST-REBASE COMMIT MESSAGE VALIDATION — ISSUES PERSIST AFTER",
        "AUTOMATIC CORRECTION.",
        "",
        "The following commits still have commit message issues after a",
        "previous correction attempt:",
        "",
    ]

    for commit in problematic_commits:
        lines.append(f"  {commit['hash']}:")
        lines.append("    Message:")
        for message_line in commit["message"].splitlines():
            lines.append(f"      {message_line}")
        lines.append("    Issues:")
        for issue in commit["issues"]:
            lines.append(f"    - {issue}")
        lines.append("")

    lines.extend([
        "Do not attempt another automated correction.  Present the",
        "issues above to the user and ask how they would like to",
        "proceed.",
    ])

    return "\n".join(lines)


def _clean_up_stale_marker_files(current_session_id: str) -> None:
    """Remove marker files left behind by previous sessions."""
    for stale_marker_path in glob.glob(f"{PREFIX_OF_MARKER_FILE}*"):
        if current_session_id not in stale_marker_path:
            pathlib.Path(stale_marker_path).unlink(missing_ok=True)


def main() -> int:
    hook_input = read_hook_input_from_standard_input()

    tool_input = hook_input.get("tool_input", {})
    command = tool_input.get("command", "")

    if not is_git_subcommand(command, "rebase"):
        return 0

    # Skip --continue, --abort, --skip.  --continue is handled by
    # PreToolUse hooks (which validate the commit being created).
    # --abort and --skip do not create commits.
    # Strip heredoc content before checking for flags to avoid false
    # positives from flag names appearing in commit messages.
    command_without_heredoc = re.sub(
        r"<<'EOF'\s*\n.*?\n\s*EOF", "", command, flags=re.DOTALL
    )
    if re.search(r"--(continue|abort|skip)\b", command_without_heredoc):
        return 0

    # If the rebase is still in progress (stopped for conflicts or
    # editing), there are no finalised commits to validate yet.
    if is_rebase_still_in_progress():
        return 0

    commits = get_new_commits_after_rebase()
    if not commits:
        return 0

    # Session tracking: cap automatic correction at one attempt.
    session_id = hook_input.get("session_id", "")
    is_second_attempt = False
    marker_file_path = None

    if session_id:
        _clean_up_stale_marker_files(session_id)
        marker_file_path = pathlib.Path(
            f"{PREFIX_OF_MARKER_FILE}{session_id}"
        )
        if marker_file_path.exists():
            is_second_attempt = True
            marker_file_path.unlink(missing_ok=True)

    # Collect message + diff for each commit.
    commits_data = []
    for commit_hash in commits:
        message = get_commit_message(commit_hash)
        diff = get_diff_from_parent(commit_hash)
        if message and diff:
            commits_data.append({
                "hash": commit_hash[:8],
                "message": message,
                "diff": diff,
            })

    if not commits_data:
        return 0

    prompt = build_validation_prompt(commits_data)
    analysis = call_claude_for_validation(prompt)

    if analysis is None:
        return 0

    # Build a lookup from short hash to commit message.
    commit_message_indexed_by_short_hash = {
        data["hash"]: data["message"] for data in commits_data
    }

    # Extract commits with issues.
    problematic = []
    for commit_result in analysis.get("commits", []):
        issues = commit_result.get("issues", [])
        if issues:
            short_hash = commit_result.get("hash", "unknown")
            entry = {
                "hash": short_hash,
                "message": commit_message_indexed_by_short_hash.get(short_hash, "(unknown)"),
                "issues": issues,
            }
            corrected = commit_result.get("corrected_message")
            if corrected:
                entry["corrected_message"] = corrected
            problematic.append(entry)

    if not problematic:
        return 0

    if is_second_attempt:
        system_message = build_system_message_for_manual_resolution(
            problematic
        )
    else:
        system_message = build_system_message_for_automatic_correction(
            problematic
        )
        # Create marker so the next firing uses manual resolution.
        if marker_file_path is not None:
            marker_file_path.touch()

    output = {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "systemMessage": system_message,
        },
    }
    print(json.dumps(output))
    return 0


if __name__ == "__main__":
    sys.exit(main())
