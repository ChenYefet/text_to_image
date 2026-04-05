"""Pre-commit hook that verifies hooks with non-deterministic checks use
the deny-then-allow pattern.

This is a Claude Code PreToolUse hook for the Bash tool.  On the first
``git commit`` attempt within a session, it inspects staged
``.claude/hooks/*.py`` files and delegates analysis to Claude Sonnet
via the ``claude`` command-line interface to determine whether each hook uses a
non-deterministic check (such as an LLM call).  If a hook uses a
non-deterministic check but does not import and use
``helpers.deny_then_allow``, the commit is denied.  On the second attempt
within the same session, the hook allows the commit to proceed
regardless — because the analysis is itself non-deterministic.

This hook is self-referentially consistent: It enforces the rule that
LLM-based hooks must use the deny-then-allow pattern, and it is itself
an LLM-based hook that uses the deny-then-allow pattern.

Graceful degradation: If the ``claude`` command-line interface is not found, times out,
returns an error, or produces unparseable output, the hook allows the
commit and logs a warning to stderr.

Exit code 0 — always (output JSON controls blocking via permissionDecision).
"""

import subprocess
import sys

from helpers.deny_then_allow import run_deny_then_allow
from helpers.invoking_claude_cli_for_analysis import call_claude_cli_for_analysis
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
        "to a large language model (such as calling the `claude` command-line interface, "
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


def call_claude_for_analysis(prompt: str) -> dict | None:
    """Call the Claude command-line interface to analyse a hook file."""
    return call_claude_cli_for_analysis(
        prompt,
        timeout_in_seconds=60,
        description_of_analysis="non-deterministic hook analysis",
    )


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
            # Graceful degradation: command-line interface unavailable or call failed.
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
