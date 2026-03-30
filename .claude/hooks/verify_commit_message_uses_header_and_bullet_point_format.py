"""Pre-commit hook that verifies commit messages use the header-and-bullet-point
format.

This is a Claude Code PreToolUse hook for the Bash tool.  On the first
``git commit`` attempt within a session, it extracts the commit message
from the command and delegates format analysis to Claude Sonnet via the
``claude`` CLI.  If the message body uses prose paragraphs instead of
bullet points, the commit is denied.  On the second attempt within the
same session, the hook allows the commit to proceed regardless — because
the analysis is itself non-deterministic.

Graceful degradation: If the ``claude`` CLI is not found, times out,
returns an error, or produces unparseable output, the hook allows the
commit and logs a warning to stderr.

Exit code 0 — always (output JSON controls blocking via permissionDecision).
"""

import json
import os
import subprocess
import sys

from helpers.deny_then_allow import run_deny_then_allow
from helpers.parsing_of_hook_input_for_bash_commands import (
    is_git_subcommand,
    read_hook_input_from_standard_input,
)

PREFIX_OF_MARKER_FILE = (
    ".marker_file_for_pending_review_of_format_of_commit_message_for_session_"
)


def extract_commit_message_from_command(command: str) -> str | None:
    """Extract the commit message from a git commit command string.

    Supports both ``-m "message"`` and heredoc forms.  Returns the
    message text, or None if it cannot be extracted.
    """
    # Pass the entire command to a simple heuristic: everything between
    # the commit message delimiters.  Since the command may use heredoc
    # or quoted strings, we return the full command and let the LLM
    # extract the message — this is more robust than fragile parsing.
    return command


def build_prompt_for_analysis_of_commit_message_format(
    command: str,
) -> str:
    """Build the analysis prompt for a check of commit message format."""
    return (
        "You are a commit message format validator. Your task is to "
        "determine whether the commit message in the following git "
        "commit command follows the required format:\n"
        "\n"
        "1. The message must have a single subject line (the header).\n"
        "2. If a body is present (text after a blank line following the "
        "header), it must use bullet points (lines beginning with "
        "`- `) — never prose paragraphs.\n"
        "3. If a bullet point begins with a verb, that verb must be in "
        "the past tense (e.g. 'Added', 'Removed', 'Updated', 'Fixed', "
        "'Replaced', 'Renamed'). A bullet point that begins with a "
        "present-tense verb (e.g. 'Add', 'Remove', 'Update', 'Fix') "
        "is a violation. A bullet point that begins with a non-verb "
        "word is acceptable regardless of tense.\n"
        "4. The Co-Authored-By trailer line at the end is not part of "
        "the body and should be ignored.\n"
        "5. A commit message with only a subject line and no body is "
        "acceptable.\n"
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
        '- "body_uses_bullet_points": boolean — true if the body '
        "(when present) uses bullet points, or if there is no body. "
        "false if the body uses prose paragraphs.\n"
        '- "bullet_points_use_past_tense": boolean — true if every '
        "bullet point that begins with a verb uses a past-tense verb, "
        "or if there is no body. false if any bullet point begins with "
        "a present-tense verb.\n"
        '- "is_valid": boolean — true if the format is correct '
        "(has header, body if present uses bullet points, and no bullet "
        "point begins with a present-tense verb).\n"
        '- "explanation": string — a brief explanation of any format '
        "violations found, or a confirmation that the format is correct.\n"
        "\n"
        "Return ONLY the JSON object, with no surrounding text, no "
        "markdown code fences, and no commentary."
    )


def parse_analysis_from_claude_response(
    standard_output: str,
) -> dict | None:
    """Parse the analysis result from the claude CLI JSON output.

    Returns the analysis dictionary on success, or None if the response
    cannot be parsed.
    """
    response_text = standard_output
    try:
        parsed_output = json.loads(standard_output)
        if isinstance(parsed_output, dict) and "result" in parsed_output:
            response_text = parsed_output["result"]
    except (json.JSONDecodeError, TypeError):
        pass

    if isinstance(response_text, dict):
        return response_text

    if not isinstance(response_text, str):
        return None

    # Strip markdown code fences if Claude wrapped the JSON in them.
    cleaned = response_text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        end_index = len(lines)
        for i in range(len(lines) - 1, 0, -1):
            if lines[i].strip().startswith("```"):
                end_index = i
                break
        cleaned = "\n".join(lines[1:end_index]).strip()

    try:
        result = json.loads(cleaned)
        if isinstance(result, dict):
            return result
    except (json.JSONDecodeError, TypeError):
        pass

    return None


def call_claude_for_analysis(prompt: str) -> dict | None:
    """Call the claude CLI to analyse the commit message format.

    Returns the analysis dictionary on success, or None if the CLI is
    unavailable, the call fails, or the response is unparseable.
    """
    environment_without_nesting_guard = os.environ.copy()
    environment_without_nesting_guard.pop("CLAUDECODE", None)

    try:
        result = subprocess.run(
            [
                "claude", "-p",
                "--model", "sonnet",
                "--output-format", "json",
            ],
            input=prompt,
            capture_output=True,
            encoding="utf-8",
            timeout=60,
            env=environment_without_nesting_guard,
        )
    except FileNotFoundError:
        print(
            "WARNING: claude CLI not found in PATH; skipping"
            " analysis of commit message format.",
            file=sys.stderr,
        )
        return None
    except subprocess.TimeoutExpired:
        print(
            "WARNING: claude CLI timed out; skipping"
            " analysis of commit message format.",
            file=sys.stderr,
        )
        return None

    if result.returncode != 0:
        print(
            f"WARNING: claude CLI exited with code {result.returncode};"
            " skipping analysis of commit message format.",
            file=sys.stderr,
        )
        return None

    analysis = parse_analysis_from_claude_response(result.stdout)
    if analysis is None:
        print(
            "WARNING: Could not parse claude CLI response as JSON;"
            " skipping analysis of commit message format.",
            file=sys.stderr,
        )
        return None

    return analysis


def check_and_build_blocking_message_from_command(
    command: str,
) -> str | None:
    """Analyse the commit message format and return a blocking message
    if it violates the header-and-bullet-point format.

    Returns a blocking message string if violations are found, or None
    if the format is correct.
    """
    prompt = build_prompt_for_analysis_of_commit_message_format(command)
    analysis = call_claude_for_analysis(prompt)

    if analysis is None:
        # Graceful degradation: CLI unavailable or call failed.
        return None

    is_valid = analysis.get("is_valid", True)
    explanation = analysis.get("explanation", "")

    if is_valid:
        return None

    return (
        "COMMIT MESSAGE FORMAT VIOLATION — COMMIT BLOCKED.\n"
        "\n"
        "The commit message does not follow the required format.\n"
        "\n"
        f"Issue: {explanation}\n"
        "\n"
        "Required format:\n"
        "- A single subject line (the header).\n"
        "- If a body is needed, a blank line followed by bullet points\n"
        "  (each line beginning with `- `). Never use prose paragraphs.\n"
        "- Each bullet point that begins with a verb must use the past\n"
        "  tense (e.g. 'Added', 'Removed', 'Updated', 'Fixed').\n"
        "- The Co-Authored-By trailer is not part of the body.\n"
        "\n"
        "Fix the commit message and re-attempt the commit.  If this is\n"
        "a false positive, re-attempt the commit unchanged — it will be\n"
        "allowed on the second attempt."
    )


# Store the command from hook input so the closure can access it.
_captured_command = ""


def check_and_build_blocking_message() -> str | None:
    """Wrapper that satisfies the deny-then-allow callable signature."""
    return check_and_build_blocking_message_from_command(_captured_command)


def main() -> int:
    global _captured_command
    hook_input = read_hook_input_from_standard_input()

    tool_input = hook_input.get("tool_input", {})
    command = tool_input.get("command", "")

    if not is_git_subcommand(command, "commit"):
        return 0

    _captured_command = command

    return run_deny_then_allow(
        hook_input,
        PREFIX_OF_MARKER_FILE,
        check_and_build_blocking_message,
    )


if __name__ == "__main__":
    sys.exit(main())
