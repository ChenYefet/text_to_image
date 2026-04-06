"""Pre-commit hook that verifies all prose references to markdown headings
are wrapped in hyperlinks.

This is a Claude Code PreToolUse hook for the Bash tool.  On the first
``git commit`` attempt within a session, it extracts added lines from
staged ``.md`` files and delegates semantic analysis to Claude Sonnet
via the ``claude`` command-line interface to detect prose text that references a heading
without a ``[...](#...)`` hyperlink.  If un-hyperlinked references are
found, the commit is denied and the violations are injected as a
``systemMessage``.  On the second attempt within the same session, the
hook allows the commit to proceed regardless — this ensures that false
positives from the non-deterministic analysis by the large language model never permanently
block a commit.

Session isolation is achieved via a marker file whose name includes the
``session_id`` from the hook input.  A marker created by a different
session is ignored and cleaned up, preventing stale markers from
allowing commits without review.

Graceful degradation: If the ``claude`` command-line interface is not found, times out,
returns an error, or produces unparseable output, the hook allows the
commit and logs a warning to stderr.

Exit code 0 — always (output JSON controls blocking via permissionDecision).
"""

import json
import subprocess
import sys

from helpers.deny_then_allow import run_deny_then_allow
from helpers.invoking_claude_cli_for_analysis import call_claude_cli_for_analysis
from helpers.parsing_of_hook_input_for_bash_commands import read_hook_input_from_standard_input
from helpers.validate_markdown_anchors import extract_anchors_from_headings

PREFIX_OF_MARKER_FILE = (
    ".marker_file_for_pending_review_of_hyperlinking_of_heading_references_for_session_"
)


def get_staged_markdown_files() -> list[str]:
    """Return file paths of staged ``.md`` files that were added or
    modified.
    """
    result = subprocess.run(
        [
            "git", "diff", "--cached", "--name-only",
            "--diff-filter=AM", "--", "*.md",
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
        encoding="utf-8",
    )
    return result.stdout


def get_added_lines_from_staged_diff(file_path: str) -> list[str]:
    """Return the text of lines added in the staged diff for a file.

    Each returned string is the raw line content without the leading
    ``+``. Heading lines (starting with ``#``) are excluded since they
    define headings rather than reference them.
    """
    result = subprocess.run(
        ["git", "diff", "--cached", "-U0", "--", file_path],
        capture_output=True,
        text=True,
    )
    added_lines = []
    for line in result.stdout.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            content = line[1:]
            # Skip heading lines — they define headings, not reference them.
            if not content.lstrip().startswith("#"):
                added_lines.append(content)
    return added_lines


def build_prompt_for_heading_reference_analysis(
    anchors_mapped_to_heading_texts: dict[str, list[str]],
    added_lines: list[str],
) -> str:
    """Build the analysis prompt listing headings and added lines."""
    heading_entries = []
    for anchor_identifier, heading_texts in anchors_mapped_to_heading_texts.items():
        for heading_text in heading_texts:
            heading_entries.append(
                f'- "{heading_text}" -> #{anchor_identifier}'
            )

    headings_section = "\n".join(heading_entries)
    added_lines_section = "\n".join(added_lines)

    return (
        "You are a markdown linting tool. Your task is to identify prose "
        "text in the ADDED LINES that references one of the HEADINGS "
        "listed below but is NOT wrapped in a markdown hyperlink "
        "`[...](#...)`.\n"
        "\n"
        "HEADINGS (with anchor identifiers):\n"
        f"{headings_section}\n"
        "\n"
        "ADDED LINES:\n"
        f"{added_lines_section}\n"
        "\n"
        "Rules:\n"
        "1. A reference is prose text that clearly refers to a heading by "
        "its full name or a close paraphrase -- for example, \"see the "
        "Configuration Requirements below\" referencing a heading called "
        "\"Configuration Requirements\".\n"
        "2. IGNORE text that is already inside a markdown hyperlink -- "
        "that is, text matching the pattern `[...](#...)`.\n"
        "3. IGNORE text inside fenced code blocks (delimited by ```) or "
        "inline code (delimited by single backticks).\n"
        "4. IGNORE coincidental word matches that are clearly not "
        "references to a heading -- for example, the word "
        "\"configuration\" appearing in a sentence about configuring "
        "something, when there happens to be a heading with "
        "\"Configuration\" in the name.\n"
        "5. Be conservative: Only flag text where the author clearly "
        "intended to refer the reader to a specific heading. When in "
        "doubt, do not flag it.\n"
        "\n"
        "Return ONLY a JSON array. Each element must be an object with "
        "these fields:\n"
        '- "reference_text": The exact prose text that references the '
        "heading.\n"
        '- "referenced_heading": The heading being referenced.\n'
        '- "anchor_id": The anchor identifier for that heading (from the '
        "list above).\n"
        '- "explanation": A brief explanation of why this is a heading '
        "reference.\n"
        "\n"
        "If there are no violations, return an empty array: []\n"
        "\n"
        "Return ONLY the JSON array, with no surrounding text, no markdown "
        "code fences, and no commentary."
    )


def call_claude_for_heading_reference_analysis(
    prompt: str,
) -> list[dict] | None:
    """Call the Claude command-line interface to analyse heading references."""
    return call_claude_cli_for_analysis(
        prompt,
        expected_type=list,
        timeout_in_seconds=60,
        description_of_analysis="heading reference validation",
    )


def build_blocking_message(
    violations_indexed_by_file_path: dict[str, list[dict]],
) -> str:
    """Build the blocking systemMessage listing all un-hyperlinked heading
    references.
    """
    lines = [
        "The following prose references to markdown headings are not wrapped",
        "in hyperlinks. All references to headings must use the format",
        "[reference text](#anchor-id):",
        "",
    ]
    for file_path, violations in violations_indexed_by_file_path.items():
        lines.append(f"  File: {file_path}")
        for violation in violations:
            reference_text = violation.get("reference_text", "unknown")
            referenced_heading = violation.get(
                "referenced_heading", "unknown"
            )
            anchor_identifier = violation.get("anchor_id", "unknown")
            explanation = violation.get("explanation", "")
            lines.append(
                f'    - "{reference_text}" references heading'
                f' "{referenced_heading}" (#{anchor_identifier})'
            )
            if explanation:
                lines.append(f"      {explanation}")
        lines.append("")

    lines.append(
        "Wrap each reference in a hyperlink, stage the changes, and"
    )
    lines.append("re-attempt the commit.  If these are false positives,")
    lines.append("re-attempt the commit unchanged — it will be allowed")
    lines.append("on the second attempt.")
    return "\n".join(lines)


def check_and_build_blocking_message() -> str | None:
    """Run the heading reference analysis on all staged markdown files.

    Returns a blocking message string if un-hyperlinked references are
    found, or None if no violations are detected.
    """
    staged_markdown_files = get_staged_markdown_files()
    if not staged_markdown_files:
        return None

    violations_indexed_by_file_path: dict[str, list[dict]] = {}

    for file_path in staged_markdown_files:
        staged_content = get_staged_file_content(file_path)
        anchors_mapped_to_heading_texts = extract_anchors_from_headings(
            staged_content
        )

        if not anchors_mapped_to_heading_texts:
            continue

        added_lines = get_added_lines_from_staged_diff(file_path)
        if not added_lines:
            continue

        prompt = build_prompt_for_heading_reference_analysis(
            anchors_mapped_to_heading_texts,
            added_lines,
        )
        violations = call_claude_for_heading_reference_analysis(prompt)

        if violations is None:
            # Graceful degradation: command-line interface unavailable or call failed.
            continue

        if violations:
            violations_indexed_by_file_path[file_path] = violations

    if not violations_indexed_by_file_path:
        return None

    return build_blocking_message(violations_indexed_by_file_path)


def main() -> int:
    hook_input = read_hook_input_from_standard_input()
    return run_deny_then_allow(
        hook_input,
        PREFIX_OF_MARKER_FILE,
        check_and_build_blocking_message,
    )


if __name__ == "__main__":
    sys.exit(main())
