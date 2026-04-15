"""Shared utilities for invoking the Claude command-line interface and
parsing its JSON output.

Provides two functions used by hooks that delegate analysis to the
Claude command-line interface:

- ``parse_json_from_claude_cli_output`` — unwraps the envelope
  produced by ``--output-format json`` (either a legacy
  ``{"result": ...}`` object or the current array-of-events
  format), strips markdown code fences if present, parses the
  JSON, and validates the result type.
- ``call_claude_cli_for_analysis`` — invokes the Claude command-line
  interface as a subprocess with the standard flags, retries on
  transient failures, handles errors gracefully, and returns the
  parsed result.
"""

import json
import os
import subprocess
import sys
import time


def parse_json_from_claude_cli_output(
    standard_output: str,
    expected_type: type = dict,
) -> dict | list | None:
    """Parse JSON from the Claude command-line interface output.

    The ``--output-format json`` flag produces either a JSON object
    with a ``result`` field (legacy format) or a JSON array of event
    objects where the result is in the event whose ``type`` field is
    ``"result"`` (current format).  This function unwraps either
    envelope, strips markdown code fences if present, parses the
    inner JSON, and validates the result type.

    When the model self-corrects mid-response, the ``result`` field may
    contain multiple markdown code blocks (e.g. an initial answer
    followed by prose like "Wait, let me re-evaluate" and a corrected
    answer in a second code block).  In that case, this function
    extracts each code block individually and returns the last one
    that parses as valid JSON of the expected type — the last block
    is the model's final answer.

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
        elif isinstance(parsed_output, list):
            for event in parsed_output:
                if (
                    isinstance(event, dict)
                    and event.get("type") == "result"
                    and "result" in event
                ):
                    response_text = event["result"]
                    break
    except (json.JSONDecodeError, TypeError):
        pass

    if isinstance(response_text, expected_type):
        return response_text

    if not isinstance(response_text, str):
        return None

    # Strip markdown code fences if Claude wrapped the JSON in them.
    # When the model self-corrects, it may produce multiple code blocks
    # (e.g. an initial answer followed by "Wait, let me re-evaluate"
    # and a corrected answer).  Extract each code block individually
    # and return the last one that parses as valid JSON of the
    # expected type — the last block is the model's final answer.
    # If no code blocks are found, try parsing the entire text as
    # JSON.
    cleaned = response_text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        block_start = None
        last_valid_result = None
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("```"):
                if block_start is None:
                    # Opening fence — content starts on the next line.
                    block_start = i + 1
                else:
                    # Closing fence — extract the block and try to parse.
                    block_text = "\n".join(
                        lines[block_start:i]
                    ).strip()
                    try:
                        result = json.loads(block_text)
                        if isinstance(result, expected_type):
                            last_valid_result = result
                    except (json.JSONDecodeError, TypeError):
                        pass
                    # Reset for the next code block, if any.
                    block_start = None
        # If a code block was opened but never closed, try parsing
        # everything after the opening fence.
        if block_start is not None:
            block_text = "\n".join(
                lines[block_start:]
            ).strip()
            try:
                result = json.loads(block_text)
                if isinstance(result, expected_type):
                    last_valid_result = result
            except (json.JSONDecodeError, TypeError):
                pass
        return last_valid_result

    try:
        result = json.loads(cleaned)
        if isinstance(result, expected_type):
            return result
    except (json.JSONDecodeError, TypeError):
        pass

    return None


description_of_last_failure: str | None = None
"""Module-level variable that stores the description of the most recent
failure from ``call_claude_cli_for_analysis``.  Set to None when the
call succeeds or before each invocation.  Callers that hard-block on
failure can import this variable to include diagnostic detail in
blocking messages.
"""


def call_claude_cli_for_analysis(
    prompt: str,
    *,
    expected_type: type = dict,
    timeout_in_seconds: int = 60,
    maximum_number_of_attempts: int = 2,
    number_of_seconds_between_attempts: int = 3,
    description_of_analysis: str,
    severity: str = "WARNING",
) -> dict | list | None:
    """Call the Claude command-line interface to perform an analysis.

    Invokes ``claude -p --model sonnet --output-format json`` with the
    given prompt on stdin, parses the JSON response, and returns the
    result.  Retries on transient failures (timeout, non-zero exit
    code, unparseable output) up to ``maximum_number_of_attempts``
    times with a delay of ``number_of_seconds_between_attempts``
    seconds between retries.  Does not retry when the command-line
    interface binary is not found (a non-transient failure).

    On failure, sets the module-level ``description_of_last_failure``
    variable with a diagnostic message that callers can include in
    blocking output.

    Parameters:
        prompt: The prompt text to send to the Claude command-line
            interface via stdin.
        expected_type: The expected Python type of the parsed result
            (``dict`` or ``list``).  Defaults to ``dict``.
        timeout_in_seconds: Subprocess timeout in seconds.  Defaults
            to 60.
        maximum_number_of_attempts: The maximum number of attempts
            before giving up.  Defaults to 2 (one original attempt
            plus one retry).
        number_of_seconds_between_attempts: The number of seconds to
            wait between retry attempts.  Defaults to 3.
        description_of_analysis: A short description of the analysis
            being performed, used in error/warning messages (e.g.
            ``"commit message format analysis"``).
        severity: The prefix for log messages — ``"ERROR"`` or
            ``"WARNING"``.  Use ``"ERROR"`` when the hook hard-blocks
            on failure; use ``"WARNING"`` when the hook degrades
            gracefully.  Defaults to ``"WARNING"``.

    Returns the parsed result if successful, or None on any failure.
    """
    global description_of_last_failure
    description_of_last_failure = None

    environment_without_nesting_guard = os.environ.copy()
    environment_without_nesting_guard.pop("CLAUDECODE", None)

    last_failure = None

    for attempt_index in range(maximum_number_of_attempts):
        if attempt_index > 0:
            print(
                f"{severity}: Attempt {attempt_index} of"
                f" {maximum_number_of_attempts} for"
                f" {description_of_analysis} failed ({last_failure});"
                f" retrying in {number_of_seconds_between_attempts}"
                f" seconds.",
                file=sys.stderr,
            )
            time.sleep(number_of_seconds_between_attempts)

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
            last_failure = (
                "command-line interface not found in PATH"
            )
            print(
                f"{severity}: Claude {last_failure};"
                f" skipping {description_of_analysis}.",
                file=sys.stderr,
            )
            description_of_last_failure = last_failure
            return None
        except subprocess.TimeoutExpired:
            last_failure = (
                f"command-line interface timed out after"
                f" {timeout_in_seconds} seconds"
            )
            continue

        if result.returncode != 0:
            stderr_excerpt = result.stderr.strip()[:200]
            last_failure = (
                f"command-line interface exited with code"
                f" {result.returncode}"
                + (
                    f" (stderr: {stderr_excerpt})"
                    if stderr_excerpt
                    else ""
                )
            )
            continue

        analysis = parse_json_from_claude_cli_output(
            result.stdout, expected_type
        )
        if analysis is None:
            stdout_excerpt = result.stdout.strip()[:200]
            last_failure = (
                f"could not parse command-line interface response"
                f" as JSON (stdout excerpt: {stdout_excerpt})"
            )
            continue

        return analysis

    description_of_last_failure = last_failure
    print(
        f"{severity}: All {maximum_number_of_attempts} attempt(s) failed"
        f" for {description_of_analysis}"
        + (f" — last failure: {last_failure}" if last_failure else "")
        + ".",
        file=sys.stderr,
    )
    return None
