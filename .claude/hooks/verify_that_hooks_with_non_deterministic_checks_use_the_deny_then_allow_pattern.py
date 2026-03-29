"""Pre-commit hook that verifies hooks with non-deterministic checks use
the deny-then-allow pattern.

This is a Claude Code PreToolUse hook for the Bash tool.  On the first
``git commit`` attempt within a session, it inspects staged
``.claude/hooks/*.py`` files and delegates analysis to Claude Sonnet
via the ``claude`` CLI to determine whether each hook uses a
non-deterministic check (such as an LLM call).  If a hook uses a
non-deterministic check but does not import and use
``helpers.deny_then_allow``, the commit is denied.  On the second attempt
within the same session, the hook allows the commit to proceed
regardless — because the analysis is itself non-deterministic.

This hook is self-referentially consistent: It enforces the rule that
LLM-based hooks must use the deny-then-allow pattern, and it is itself
an LLM-based hook that uses the deny-then-allow pattern.

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
from helpers.parsing_of_hook_input_for_bash_commands import read_hook_input_from_standard_input

PREFIX_OF_MARKER_FILE = (
    ".marker_file_for_pending_review_of_deny_then_allow_compliance_by_hooks_with_non_deterministic_checks_for_session_"
)

def get_staged_hook_files() -> list[str]:
    """Return file paths of staged ``.claude/hooks/*.py`` files that were
    added or modified.

    The glob ``.claude/hooks/*.py`` does not recurse into subdirectories,
    so helper modules in ``.claude/hooks/helpers/`` are automatically
    excluded.
    """
    result = subprocess.run(
        [
            "git", "diff", "--cached", "--name-only",
            "--diff-filter=AM", "--", ".claude/hooks/*.py",
        ],
        capture_output=True,
        text=True,
    )
    return [
        line.strip()
        for line in result.stdout.strip().splitlines()
        if line.strip()
    ]


def get_staged_file_content(file_path: str) -> str:
    """Return the staged content of a file via ``git show :file_path``."""
    result = subprocess.run(
        ["git", "show", f":{file_path}"],
        capture_output=True,
        text=True,
    )
    return result.stdout


def build_prompt_for_non_deterministic_check_analysis(
    file_path: str,
    file_content: str,
) -> str:
    """Build the analysis prompt for a single hook file."""
    return (
        "You are a code analysis tool. Your task is to determine whether "
        "the following Python hook file uses a non-deterministic check — "
        "that is, a check whose result may vary across invocations given "
        "identical input. The most common example is delegating analysis "
        "to a large language model (such as calling the `claude` CLI, "
        "calling an LLM API, or invoking any generative AI service).\n"
        "\n"
        "If the hook uses a non-deterministic check, determine whether "
        "it imports and uses the `helpers.deny_then_allow` module "
        "(specifically the `run_deny_then_allow` function) to ensure that false "
        "positives do not permanently block commits.\n"
        "\n"
        f"File: {file_path}\n"
        "\n"
        "```python\n"
        f"{file_content}\n"
        "```\n"
        "\n"
        "Return ONLY a JSON object with these fields:\n"
        '- "uses_non_deterministic_check": boolean — true if the hook '
        "uses a non-deterministic check (LLM call, generative AI "
        "service, etc.), false otherwise.\n"
        '- "uses_deny_then_allow": boolean — true if the hook imports '
        "and uses `run_deny_then_allow` from `helpers.deny_then_allow`, false "
        "otherwise.\n"
        '- "explanation": string — a brief explanation of your '
        "reasoning.\n"
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
        cli_output = json.loads(standard_output)
        if isinstance(cli_output, dict) and "result" in cli_output:
            response_text = cli_output["result"]
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
    """Call the claude CLI to analyse a hook file.

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
            " non-deterministic hook analysis.",
            file=sys.stderr,
        )
        return None
    except subprocess.TimeoutExpired:
        print(
            "WARNING: claude CLI timed out; skipping non-deterministic"
            " hook analysis.",
            file=sys.stderr,
        )
        return None

    if result.returncode != 0:
        print(
            f"WARNING: claude CLI exited with code {result.returncode};"
            " skipping non-deterministic hook analysis.",
            file=sys.stderr,
        )
        return None

    analysis = parse_analysis_from_claude_response(result.stdout)
    if analysis is None:
        print(
            "WARNING: Could not parse claude CLI response as JSON;"
            " skipping non-deterministic hook analysis.",
            file=sys.stderr,
        )
        return None

    return analysis


def build_blocking_message(
    violations: list[tuple[str, str]],
) -> str:
    """Build the blocking systemMessage listing hooks that use
    non-deterministic checks without the deny-then-allow pattern.
    """
    lines = [
        "The following hook files use non-deterministic checks (such as LLM",
        "calls) but do not use the `helpers.deny_then_allow` module.  Hooks",
        "with non-deterministic checks must import and use",
        "`run_deny_then_allow` from `helpers.deny_then_allow` to ensure that",
        "false positives do not",
        "permanently block commits:",
        "",
    ]
    for file_path, explanation in violations:
        lines.append(f"  File: {file_path}")
        lines.append(f"    {explanation}")
        lines.append("")

    lines.append(
        "Update each hook to import and use `run_deny_then_allow` from"
    )
    lines.append("`helpers.deny_then_allow`, stage the changes, and re-attempt")
    lines.append("the commit.  If these are false positives, re-attempt")
    lines.append("the commit unchanged — it will be allowed on the")
    lines.append("second attempt.")
    return "\n".join(lines)


def check_and_build_blocking_message() -> str | None:
    """Analyse staged hook files for non-deterministic checks without
    the deny-then-allow pattern.

    Returns a blocking message string if violations are found, or None
    if no violations are detected.
    """
    staged_hook_files = get_staged_hook_files()
    if not staged_hook_files:
        return None

    violations: list[tuple[str, str]] = []

    for file_path in staged_hook_files:
        file_content = get_staged_file_content(file_path)

        prompt = build_prompt_for_non_deterministic_check_analysis(
            file_path, file_content
        )
        analysis = call_claude_for_analysis(prompt)

        if analysis is None:
            # Graceful degradation: CLI unavailable or call failed.
            continue

        uses_non_deterministic_check = analysis.get(
            "uses_non_deterministic_check", False
        )
        uses_deny_then_allow = analysis.get(
            "uses_deny_then_allow", False
        )
        explanation = analysis.get("explanation", "")

        if uses_non_deterministic_check and not uses_deny_then_allow:
            violations.append((file_path, explanation))

    if not violations:
        return None

    return build_blocking_message(violations)


def main() -> int:
    hook_input = read_hook_input_from_standard_input()
    return run_deny_then_allow(
        hook_input,
        PREFIX_OF_MARKER_FILE,
        check_and_build_blocking_message,
    )


if __name__ == "__main__":
    sys.exit(main())
