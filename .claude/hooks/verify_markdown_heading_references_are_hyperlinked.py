"""Pre-commit hook that verifies all prose references to markdown headings
are wrapped in hyperlinks.

This is a Claude Code PreToolUse hook for the Bash tool.  On the first
``git commit`` attempt within a session, it extracts added lines from
staged ``.md`` files and delegates semantic analysis to Claude Sonnet
via the ``claude`` CLI to detect prose text that references a heading
without a ``[...](#...)`` hyperlink.  If un-hyperlinked references are
found, the commit is denied and the violations are injected as a
``systemMessage``.  On the second attempt within the same session, the
hook allows the commit to proceed regardless — this ensures that false
positives from the non-deterministic LLM analysis never permanently
block a commit.

Session isolation is achieved via a marker file whose name includes the
``session_id`` from the hook input.  A marker created by a different
session is ignored and cleaned up, preventing stale markers from
allowing commits without review.

Graceful degradation: If the ``claude`` CLI is not found, times out,
returns an error, or produces unparseable output, the hook allows the
commit and logs a warning to stderr.

Exit code 0 — always (output JSON controls blocking via permissionDecision).
"""

import glob
import importlib.util
import json
import os
import pathlib
import re
import subprocess
import sys


MARKER_FILE_PREFIX = (
    ".heading_reference_hyperlink_review_pending_before_commit_session_"
)


def read_hook_input_from_stdin() -> dict:
    """Read the JSON hook input provided by Claude Code on stdin."""
    return json.loads(sys.stdin.read())


def is_git_commit_command(command: str) -> bool:
    """Return True if the command is a git commit invocation."""
    return bool(re.search(r"\bgit\s+commit\b", command))


def get_marker_file_path_for_session(session_id: str) -> pathlib.Path:
    """Return the path to the session-scoped marker file."""
    return pathlib.Path(f"{MARKER_FILE_PREFIX}{session_id}")


def clean_up_stale_marker_files(current_session_id: str) -> None:
    """Remove marker files left behind by previous sessions."""
    for stale_marker_path in glob.glob(f"{MARKER_FILE_PREFIX}*"):
        if current_session_id not in stale_marker_path:
            pathlib.Path(stale_marker_path).unlink(missing_ok=True)


def load_function_to_extract_anchors_from_headings():
    """Load ``extract_anchors_from_headings`` from
    ``validate_markdown_anchors.py`` in the same directory as this hook.

    Returns the function object.
    """
    directory_of_this_hook = os.path.dirname(os.path.abspath(__file__))
    path_to_validation_module = os.path.join(
        directory_of_this_hook, "validate_markdown_anchors.py"
    )
    specification = importlib.util.spec_from_file_location(
        "validate_markdown_anchors", path_to_validation_module
    )
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module.extract_anchors_from_headings


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


def parse_violations_from_claude_response(
    standard_output: str,
) -> list[dict] | None:
    """Parse the violations array from the claude CLI JSON output.

    The ``--output-format json`` flag wraps the response in a JSON object
    with a ``result`` field containing the text Claude generated.

    Returns the list of violation dictionaries on success, or None if
    the response cannot be parsed.
    """
    response_text = standard_output
    try:
        cli_output = json.loads(standard_output)
        if isinstance(cli_output, dict) and "result" in cli_output:
            response_text = cli_output["result"]
    except (json.JSONDecodeError, TypeError):
        pass

    # If the result is already a list (parsed directly), return it.
    if isinstance(response_text, list):
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
        violations = json.loads(cleaned)
        if isinstance(violations, list):
            return violations
    except (json.JSONDecodeError, TypeError):
        pass

    return None


def call_claude_for_heading_reference_analysis(
    prompt: str,
) -> list[dict] | None:
    """Call the claude CLI to analyse heading references.

    Returns a list of violation dictionaries on success, or None if the
    CLI is unavailable, the call fails, or the response is unparseable.
    """
    # Unset CLAUDECODE to allow the CLI to run from within a Claude
    # Code session (hooks execute inside the parent session's
    # environment).
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
            "WARNING: claude CLI not found in PATH; skipping heading"
            " reference validation.",
            file=sys.stderr,
        )
        return None
    except subprocess.TimeoutExpired:
        print(
            "WARNING: claude CLI timed out; skipping heading reference"
            " validation.",
            file=sys.stderr,
        )
        return None

    if result.returncode != 0:
        print(
            f"WARNING: claude CLI exited with code {result.returncode};"
            " skipping heading reference validation.",
            file=sys.stderr,
        )
        return None

    violations = parse_violations_from_claude_response(result.stdout)
    if violations is None:
        print(
            "WARNING: Could not parse claude CLI response as JSON;"
            " skipping heading reference validation.",
            file=sys.stderr,
        )
        return None

    return violations


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


def collect_violations() -> dict[str, list[dict]]:
    """Run the heading reference analysis on all staged markdown files.

    Returns a dictionary mapping file paths to their violation lists.
    Empty if no staged markdown files exist, no headings are found, or
    no violations are detected.
    """
    staged_markdown_files = get_staged_markdown_files()
    if not staged_markdown_files:
        return {}

    extract_anchors_from_headings = (
        load_function_to_extract_anchors_from_headings()
    )
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
            # Graceful degradation: CLI unavailable or call failed.
            continue

        if violations:
            violations_indexed_by_file_path[file_path] = violations

    return violations_indexed_by_file_path


def run_analysis_and_report() -> int:
    """Run the analysis and report violations without blocking.

    This is the fallback path when no session ID is available.  Without
    a session ID, the marker file mechanism cannot guarantee that a
    second attempt will be allowed, so violations are reported as an
    advisory systemMessage rather than a blocking deny.
    """
    violations_indexed_by_file_path = collect_violations()

    if violations_indexed_by_file_path:
        message = build_blocking_message(violations_indexed_by_file_path)
        output = {
            "systemMessage": message,
        }
        print(json.dumps(output))

    return 0


def main() -> int:
    hook_input = read_hook_input_from_stdin()

    tool_input = hook_input.get("tool_input", {})
    command = tool_input.get("command", "")

    # Fast path: not a git commit command.
    if not is_git_commit_command(command):
        return 0

    session_id = hook_input.get("session_id", "")
    if not session_id:
        # If no session ID is available, fall back to running the
        # analysis without marker file logic to avoid permanently
        # blocking commits.
        return run_analysis_and_report()

    clean_up_stale_marker_files(session_id)

    marker_file_path = get_marker_file_path_for_session(session_id)

    if marker_file_path.exists():
        # Second attempt within this session: allow the commit and
        # remove the marker so the next commit in this session is
        # also checked.
        marker_file_path.unlink(missing_ok=True)
        return 0

    # First attempt within this session: run the analysis.
    violations_indexed_by_file_path = collect_violations()

    if not violations_indexed_by_file_path:
        return 0

    # Violations found: create the marker so the second attempt is
    # allowed, then deny this attempt with the violations message.
    marker_file_path.touch()

    message = build_blocking_message(violations_indexed_by_file_path)
    output = {
        "hookSpecificOutput": {
            "permissionDecision": "deny",
        },
        "systemMessage": message,
    }
    print(json.dumps(output))

    return 0


if __name__ == "__main__":
    sys.exit(main())
