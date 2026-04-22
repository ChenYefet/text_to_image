"""Pre-commit hook that verifies commit messages use the header-and-bullet-point
format.

This is a Claude Code PreToolUse hook for the Bash tool.  On the first
``git commit``, ``git commit-tree``, or ``git merge`` attempt within a
session, it extracts the commit message from the command and delegates
format analysis to Claude Sonnet via the ``claude`` command-line interface.  If the
message body uses prose paragraphs instead of
bullet points, the commit is denied.  On the second attempt within the
same session, the hook allows the commit to proceed regardless — because
the analysis is itself non-deterministic.

If the ``claude`` command-line interface is not found, times out, returns an
error, or produces unparseable output, the commit is blocked unconditionally.
Unlike format violations, a failure of the command-line interface does not
create a marker file and does not benefit from the deny-then-allow escape
hatch — every attempt is blocked until the command-line interface issue is
resolved.

Exit code 0 — always (output JSON controls blocking via permissionDecision).
"""

import json
import pathlib
import sys

from helpers.deny_then_allow import run_deny_then_allow
from helpers.description_of_rules_for_validation_of_commit_messages import (
    build_text_describing_format_rules,
)
from helpers import invoking_claude_cli_for_analysis
from helpers.invoking_claude_cli_for_analysis import call_claude_cli_for_analysis
from helpers.parsing_of_hook_input_for_bash_commands import (
    extract_commit_message_from_command,
    is_git_subcommand,
    read_hook_input_from_standard_input,
)

PREFIX_OF_MARKER_FILE = (
    ".marker_file_for_pending_review_of_format_of_commit_message_for_session_"
)


def build_prompt_for_analysis_of_commit_message_format(
    command: str,
) -> str:
    """Build the analysis prompt for a check of commit message format."""
    return (
        "You are a commit message format validator.  Your task is to "
        "determine whether the commit message in the following git "
        "commit command satisfies every rule below:\n"
        "\n"
        f"{build_text_describing_format_rules()}\n"
        "\n"
        "Here is the git commit command:\n"
        "\n"
        "```\n"
        f"{command}\n"
        "```\n"
        "\n"
        "Return ONLY a JSON object with these fields:\n"
        '- "has_header": boolean — true if the message has a clear '
        "single-line subject header.\n"
        '- "header_uses_present_tense": boolean — true if the header '
        "begins with a present-tense imperative verb or a non-verb "
        "word. false if the header begins with a past-tense verb.\n"
        '- "subject_separated_from_body_by_blank_line": boolean — true '
        "if the message either has no body, or has an empty line "
        "immediately after the subject line separating it from the "
        "body. false if a non-empty second line directly follows the "
        "subject line with no empty line between them.\n"
        '- "body_uses_bullet_points": boolean — true if the body '
        "(when present) uses bullet points, or if there is no body. "
        "false if the body uses prose paragraphs.\n"
        '- "bullet_points_use_past_tense": boolean — true if every '
        "bullet point that begins with a verb uses a past-tense verb, "
        "or if there is no body. false if any bullet point begins with "
        "a present-tense verb.\n"
        '- "is_valid": boolean — true if every rule above is '
        "satisfied. false if any rule is violated.\n"
        '- "explanation": string — a brief explanation of any format '
        "violations found, or a confirmation that the format is correct.\n"
        "\n"
        "Return ONLY the JSON object, with no surrounding text, no "
        "markdown code fences, and no commentary."
    )


def call_claude_for_analysis(prompt: str) -> dict | None:
    """Call the Claude command-line interface to analyse the commit message format."""
    return call_claude_cli_for_analysis(
        prompt,
        timeout_in_seconds=60,
        description_of_analysis="commit message format analysis",
        severity="ERROR",
    )


def build_blocking_message_for_format_violation(
    explanation: str, commit_message: str | None,
) -> str:
    """Build the blocking message for a commit message format violation."""
    if commit_message is not None:
        message_section = (
            f"Commit message:\n\n{commit_message}\n\n"
        )
    else:
        message_section = ""

    return (
        "COMMIT MESSAGE FORMAT VIOLATION — COMMIT BLOCKED.\n"
        "\n"
        f"{message_section}"
        "The commit message does not follow the required format.\n"
        "\n"
        f"Issue: {explanation}\n"
        "\n"
        "Required format:\n"
        "\n"
        f"{build_text_describing_format_rules()}\n"
        "\n"
        "Fix the commit message and re-attempt the commit.  If this is\n"
        "a false positive, re-attempt the commit unchanged — it will be\n"
        "allowed on the second attempt."
    )


def build_blocking_message_for_failure_of_claude_cli() -> str:
    """Build the blocking message when the Claude command-line interface is unavailable.

    Includes the specific failure reason from the most recent attempt,
    if available, to aid diagnosis.
    """
    failure_detail = (
        invoking_claude_cli_for_analysis.description_of_last_failure
    )
    detail_section = (
        f"\nFailure detail: {failure_detail}\n"
        if failure_detail
        else ""
    )
    return (
        "COMMIT MESSAGE FORMAT CHECK FAILED — COMMIT BLOCKED.\n"
        "\n"
        "The commit message format could not be verified because the\n"
        "Claude command-line interface was unavailable or returned an"
        " unexpected error.\n"
        f"{detail_section}"
        "\n"
        "Resolve the issue with the Claude command-line interface before"
        " re-attempting\n"
        "the commit.  Unlike format violations, this block does not\n"
        "benefit from the deny-then-allow escape hatch — every attempt\n"
        "is blocked until the command-line interface issue is resolved."
    )


# Store the analysis result from main() so check_and_build_blocking_message
# can access it without re-calling the Claude command-line interface.
_analysis_result_cached: dict | None = None
_commit_message_cached: str | None = None


def check_and_build_blocking_message() -> str | None:
    """Build a blocking message from the cached analysis result.

    This wrapper satisfies the deny-then-allow callable signature.  It
    uses the analysis result cached by main() rather than re-calling the
    Claude command-line interface.
    """
    if _analysis_result_cached is None:
        return None

    is_valid = _analysis_result_cached.get("is_valid", True)
    explanation = _analysis_result_cached.get("explanation", "")

    if is_valid:
        return None

    return build_blocking_message_for_format_violation(
        explanation, _commit_message_cached,
    )


def main() -> int:
    global _analysis_result_cached, _commit_message_cached
    hook_input = read_hook_input_from_standard_input()

    tool_input = hook_input.get("tool_input", {})
    command = tool_input.get("command", "")

    if (
        not is_git_subcommand(command, "commit")
        and not is_git_subcommand(command, "commit-tree")
        and not is_git_subcommand(command, "merge")
    ):
        return 0

    _commit_message_cached = extract_commit_message_from_command(command)

    # If a marker file for this session already exists, the
    # deny-then-allow mechanism is in the allow-on-second-attempt state
    # (a format violation was blocked on the first attempt).  Delegate
    # directly to run_deny_then_allow without calling the Claude command-line interface —
    # it will clean up the marker file and allow the commit through.
    # Note: the marker file path formula must stay in sync with the
    # formula in helpers/deny_then_allow.py.
    session_id = hook_input.get("session_id", "")
    if session_id and pathlib.Path(
        f"{PREFIX_OF_MARKER_FILE}{session_id}"
    ).exists():
        return run_deny_then_allow(
            hook_input,
            PREFIX_OF_MARKER_FILE,
            check_and_build_blocking_message,
        )

    prompt = build_prompt_for_analysis_of_commit_message_format(command)
    analysis = call_claude_for_analysis(prompt)

    if analysis is None:
        # The Claude command-line interface was unavailable or returned an error.  Output a
        # hard block directly — no marker file is created, so every
        # subsequent attempt is also blocked until the command-line interface issue is resolved.
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    build_blocking_message_for_failure_of_claude_cli()
                ),
            },
        }
        print(json.dumps(output))
        return 0

    _analysis_result_cached = analysis

    return run_deny_then_allow(
        hook_input,
        PREFIX_OF_MARKER_FILE,
        check_and_build_blocking_message,
    )


if __name__ == "__main__":
    sys.exit(main())
