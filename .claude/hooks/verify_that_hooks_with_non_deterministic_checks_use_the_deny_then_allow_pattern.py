"""Pre-commit hook that verifies hooks with non-deterministic checks use
the deny-then-allow pattern.

This is a Claude Code PreToolUse hook for the Bash tool.  On the first
``git commit`` attempt within a session, it inspects staged
``.claude/hooks/*.py`` files and delegates analysis to Claude Sonnet
via the ``claude`` command-line interface to determine whether each hook uses a
non-deterministic check (such as a call to a large language model).  If a
PreToolUse hook uses a non-deterministic check but does not import and
use ``helpers.deny_then_allow``, the commit is denied.  PostToolUse hooks
are exempt from this requirement because they run after tool execution
and cannot deny or block tool calls.  On the second attempt within the
same session, the hook allows the commit to proceed regardless — because
the analysis is itself non-deterministic.

This hook is self-referentially consistent: It enforces the rule that
hooks based on large language models must use the deny-then-allow
pattern, and it is itself a hook based on a large language model that
uses the deny-then-allow pattern.

Graceful degradation: If the ``claude`` command-line interface is not found, times out,
returns an error, or produces unparseable output, the hook allows the
commit and logs a warning to stderr.

Exit code 0 — always (output JSON controls blocking via permissionDecision).
"""

import sys

from helpers.deny_then_allow import run_deny_then_allow
from helpers.invoking_claude_cli_for_analysis import call_claude_cli_for_analysis
from helpers.parsing_of_hook_input_for_bash_commands import read_hook_input_from_standard_input
from helpers.retrieval_from_git_staging_area import (
    get_paths_of_staged_files_matching_pathspec,
    get_staged_content_of_file,
)

PREFIX_OF_MARKER_FILE = (
    ".marker_file_for_pending_review_of_deny_then_allow_compliance_by_hooks_with_non_deterministic_checks_for_session_"
)

def get_staged_hook_files_at_top_level_of_hooks_directory() -> list[str]:
    """Return paths of staged top-level ``.claude/hooks/*.py`` files.

    Helper modules in ``.claude/hooks/helpers/`` are excluded by an
    explicit path-depth filter because git's pathspec glob ``*.py``
    recurses into subdirectories on some platforms (observed on Windows
    with Git for Windows).
    """
    return [
        file_path
        for file_path in get_paths_of_staged_files_matching_pathspec(
            ".claude/hooks/*.py"
        )
        if file_path.count("/") == 2  # .claude/hooks/file.py
    ]


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
        "calling an API of a large language model, or invoking any generative AI service).\n"
        "\n"
        "If the hook uses a non-deterministic check, determine whether "
        "it imports and uses the `helpers.deny_then_allow` module "
        "(specifically the `run_deny_then_allow` function) to ensure that false "
        "positives do not permanently block commits.\n"
        "\n"
        "Also determine whether the hook is a PreToolUse hook or a "
        "PostToolUse hook.  PreToolUse hooks run before a tool executes "
        "and can deny (block) tool calls via permissionDecision.  "
        "PostToolUse hooks run after a tool has already executed and "
        "cannot deny or block tool calls.  Look for docstring "
        "declarations (such as 'PreToolUse hook' or 'PostToolUse hook') "
        "and code patterns (such as outputting a permissionDecision of "
        "'deny') to determine the hook type.\n"
        "\n"
        f"File: {file_path}\n"
        "\n"
        "```python\n"
        f"{file_content}\n"
        "```\n"
        "\n"
        "Return ONLY a JSON object with these fields:\n"
        '- "uses_non_deterministic_check": boolean — true if the hook '
        "uses a non-deterministic check (call to a large language model, generative AI "
        "service, etc.), false otherwise.\n"
        '- "uses_deny_then_allow": boolean — true if the hook imports '
        "and uses `run_deny_then_allow` from `helpers.deny_then_allow`, false "
        "otherwise.\n"
        '- "is_pre_tool_use_hook": boolean — true if the hook is a '
        "PreToolUse hook that can deny tool calls, false if it is a "
        "PostToolUse hook that cannot deny.\n"
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
        "The following hook files use non-deterministic checks (such as calls",
        "to large language models) but do not use the `helpers.deny_then_allow` module.  Hooks",
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
    staged_hook_files = get_staged_hook_files_at_top_level_of_hooks_directory()
    if not staged_hook_files:
        return None

    violations: list[tuple[str, str]] = []

    for file_path in staged_hook_files:
        file_content = get_staged_content_of_file(file_path)

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
        is_pre_tool_use_hook = analysis.get(
            "is_pre_tool_use_hook", True
        )
        explanation = analysis.get("explanation", "")

        if (
            uses_non_deterministic_check
            and is_pre_tool_use_hook
            and not uses_deny_then_allow
        ):
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
