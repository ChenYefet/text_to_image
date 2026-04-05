"""Shared utilities for invoking the Claude command-line interface and
parsing its JSON output.

Provides two functions used by hooks that delegate analysis to the
Claude command-line interface:

- ``parse_json_from_claude_cli_output`` — unwraps the
  ``{"result": ...}`` envelope produced by ``--output-format json``,
  strips markdown code fences if present, parses the JSON, and
  validates the result type.
- ``call_claude_cli_for_analysis`` — invokes the Claude command-line
  interface as a subprocess with the standard flags, handles errors
  gracefully, and returns the parsed result.
"""

import json
import os
import subprocess
import sys


def parse_json_from_claude_cli_output(
    standard_output: str,
    expected_type: type = dict,
) -> dict | list | None:
    """Parse JSON from the Claude command-line interface output.

    The ``--output-format json`` flag wraps the response in a JSON
    object with a ``result`` field containing the text Claude generated.
    This function unwraps that envelope, strips markdown code fences if
    present, parses the inner JSON, and validates the result type.

    Parameters:
        standard_output: The raw stdout from the Claude command-line
            interface subprocess.
        expected_type: The expected Python type of the parsed result
            (``dict`` or ``list``).  Defaults to ``dict``.

    Returns the parsed result if it matches ``expected_type``, or None
    if the output cannot be parsed or does not match.
    """
    response_text = standard_output
    try:
        parsed_output = json.loads(standard_output)
        if isinstance(parsed_output, dict) and "result" in parsed_output:
            response_text = parsed_output["result"]
    except (json.JSONDecodeError, TypeError):
        pass

    if isinstance(response_text, expected_type):
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
        if isinstance(result, expected_type):
            return result
    except (json.JSONDecodeError, TypeError):
        pass

    return None


def call_claude_cli_for_analysis(
    prompt: str,
    *,
    expected_type: type = dict,
    timeout_in_seconds: int = 60,
    description_of_analysis: str,
    severity: str = "WARNING",
) -> dict | list | None:
    """Call the Claude command-line interface to perform an analysis.

    Invokes ``claude -p --model sonnet --output-format json`` with the
    given prompt on stdin, parses the JSON response, and returns the
    result.  Handles common failure modes (command-line interface not
    found, timeout, non-zero exit, unparseable output) by logging a
    message to stderr and returning None.

    Parameters:
        prompt: The prompt text to send to the Claude command-line
            interface via stdin.
        expected_type: The expected Python type of the parsed result
            (``dict`` or ``list``).  Defaults to ``dict``.
        timeout_in_seconds: Subprocess timeout in seconds.  Defaults
            to 60.
        description_of_analysis: A short description of the analysis
            being performed, used in error/warning messages (e.g.
            ``"commit message format analysis"``).
        severity: The prefix for log messages — ``"ERROR"`` or
            ``"WARNING"``.  Use ``"ERROR"`` when the hook hard-blocks
            on failure; use ``"WARNING"`` when the hook degrades
            gracefully.  Defaults to ``"WARNING"``.

    Returns the parsed result if successful, or None on any failure.
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
            timeout=timeout_in_seconds,
            env=environment_without_nesting_guard,
        )
    except FileNotFoundError:
        print(
            f"{severity}: Claude command-line interface not found in PATH;"
            f" skipping {description_of_analysis}.",
            file=sys.stderr,
        )
        return None
    except subprocess.TimeoutExpired:
        print(
            f"{severity}: Claude command-line interface timed out;"
            f" skipping {description_of_analysis}.",
            file=sys.stderr,
        )
        return None

    if result.returncode != 0:
        print(
            f"{severity}: Claude command-line interface exited with code"
            f" {result.returncode}; skipping {description_of_analysis}.",
            file=sys.stderr,
        )
        return None

    analysis = parse_json_from_claude_cli_output(
        result.stdout, expected_type
    )
    if analysis is None:
        print(
            f"{severity}: Could not parse Claude command-line interface"
            f" response as JSON; skipping {description_of_analysis}.",
            file=sys.stderr,
        )
        return None

    return analysis
