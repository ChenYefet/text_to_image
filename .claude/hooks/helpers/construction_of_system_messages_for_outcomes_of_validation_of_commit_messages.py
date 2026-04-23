"""Construction of system messages that describe outcomes of post-rebase
validation of commit messages.

The post-rebase validation hook produces one of four classes of outcome
once the validation model has run over a batch of commits.  This module
builds the system-message text that the companion relay hook delivers
to the model for each class:

- ``build_system_message_for_automatic_correction`` — issues found on
  the first attempt within the correction lifecycle; the model is
  instructed to apply the corrected messages via a non-interactive
  ``git rebase -i``.
- ``build_system_message_for_manual_resolution`` — issues still present
  on a subsequent attempt; the model is instructed to stop attempting
  automatic corrections and to surface the remaining issues to the
  user.
- ``build_system_message_for_validation_infrastructure_failure`` — no
  genuine issues were detected but one or more batches could not be
  validated; manual inspection of the unvalidated commits is
  requested.
- ``build_text_describing_commits_that_could_not_be_validated`` —
  trailing section appended to an automatic-correction or manual-
  resolution message when real issues and infrastructure failures
  coexist.

The two ``_build_text_listing_*`` helpers are reused internally between
the outcome messages so that batch-failure reasons and unvalidated-
commit listings share a single formatting source.
"""


# Length of the abbreviated commit hash used in user-facing output.
# Twelve characters provide ample collision resistance even in large
# repositories, while remaining compact enough to fit inline in
# instructions and terminal output.  The full hash is retained as the
# internal identifier when correlating the validation model's
# per-commit responses with the commits they describe.
NUMBER_OF_CHARACTERS_IN_ABBREVIATED_COMMIT_HASH = 12


def build_system_message_for_automatic_correction(
    problematic_commits: list[dict],
) -> str:
    """Build the systemMessage that instructs Claude to correct commit
    messages automatically via a non-interactive rebase.

    When corrected messages are available (provided by the validation
    model), the instruction includes the exact replacement text so that
    Claude's task is purely mechanical.  When a corrected message is
    not available for a commit, Claude is asked to compose one.

    This is used on the first firing of a correction lifecycle —
    that is, the first rebase completion whose validation finds
    issues while no prior-attempt marker is in place.  The firing
    creates the prior-attempt marker, so any subsequent firing whose
    validation still finds issues will instead produce the manual-
    resolution escalation.
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
        lines.append(f"  {commit['abbreviated_hash']}:")
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
            "compose one that follows the header + bullet-point format and",
            "accurately describes the diff from the parent commit.",
        ])

    return "\n".join(lines)


def build_system_message_for_manual_resolution(
    problematic_commits: list[dict],
) -> str:
    """Build the systemMessage that asks Claude to present remaining
    issues to the user for manual resolution.

    This is used on every firing after the first within the same
    correction lifecycle — that is, any rebase completion whose
    validation still finds issues while the prior-attempt marker
    from an earlier firing is still in place.  The escalation
    remains in effect until the issues are actually resolved (a
    subsequent rebase whose validation finds no issues) or the
    lifecycle is abandoned via ``git rebase --abort`` or
    ``git rebase --quit``.
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
        lines.append(f"  {commit['abbreviated_hash']}:")
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


def _build_text_listing_failed_batches(
    failed_batches: list[dict],
) -> list[str]:
    """Return the lines that enumerate why each failed batch failed.

    Separated from the message-builder functions so that both the
    standalone infrastructure-failure message and the appended section
    that accompanies real issues share the same formatting for the
    per-batch failure reasons.
    """
    if not failed_batches:
        return []
    lines = ["Failure reasons by batch:"]
    for batch in failed_batches:
        number_of_commits_in_batch = len(batch["commits_in_batch"])
        commit_or_commits = (
            "commit"
            if number_of_commits_in_batch == 1
            else "commits"
        )
        lines.append(
            f"  Batch {batch['batch_index']} of"
            f" {batch['number_of_batches']}"
            f" ({number_of_commits_in_batch} {commit_or_commits}):"
            f" {batch['failure_description'] or 'unknown'}"
        )
    lines.append("")
    return lines


def _build_text_listing_unvalidated_commits(
    unvalidated_commits: list[dict],
) -> list[str]:
    """Return the lines that enumerate each commit whose validation did
    not complete, showing the commit's abbreviated hash and message.
    """
    lines: list[str] = []
    for commit_data in unvalidated_commits:
        abbreviated_hash = commit_data["hash"][
            :NUMBER_OF_CHARACTERS_IN_ABBREVIATED_COMMIT_HASH
        ]
        lines.append(f"  {abbreviated_hash}:")
        lines.append("    Message:")
        for message_line in commit_data["message"].splitlines():
            lines.append(f"      {message_line}")
        lines.append("")
    return lines


def build_system_message_for_validation_infrastructure_failure(
    unvalidated_commits: list[dict],
    failed_batches: list[dict],
) -> str:
    """Build the systemMessage that reports an infrastructure failure
    blocking post-rebase commit message validation.

    Used when validation did not complete for any commit because every
    batch failed, or when the only remaining concern after successful
    batches is the set of commits whose batches did not complete.  The
    message does not instruct Claude to perform an automatic
    correction — the failure is not with the commit messages
    themselves but with the validation infrastructure, so the correct
    next action is manual inspection of each listed commit against
    its diff from the parent.
    """
    lines = [
        "POST-REBASE COMMIT MESSAGE VALIDATION — COULD NOT COMPLETE.",
        "",
        "The following commits produced by the rebase could not be",
        "validated because the Claude command-line interface failed",
        "for their batch:",
        "",
    ]
    lines.extend(_build_text_listing_unvalidated_commits(unvalidated_commits))
    lines.extend(_build_text_listing_failed_batches(failed_batches))
    lines.extend([
        "Inspect each listed commit message manually against its diff",
        "from the parent commit (``git show <hash>``).  If any need",
        "correction, apply the corrected messages using a",
        "non-interactive ``git rebase -i`` by setting",
        "``GIT_SEQUENCE_EDITOR`` to a ``sed`` command that marks the",
        "affected commits as ``reword``, and ``GIT_EDITOR`` to a",
        "script that writes the corrected message.",
        "",
        "If the command-line-interface failure was transient (for",
        "example, a timeout), a subsequent rebase that changes any of",
        "these commits will trigger validation again.",
    ])
    return "\n".join(lines)


def build_text_describing_commits_that_could_not_be_validated(
    unvalidated_commits: list[dict],
    failed_batches: list[dict],
) -> str:
    """Build the trailing section that reports commits whose
    validation did not complete, intended to be appended to one of
    the existing correction messages when real issues and
    infrastructure failures coexist.

    The section is clearly separated from the primary correction
    instructions so that Claude applies the corrected messages for
    the commits with real issues and treats the unvalidated commits
    as a distinct manual-inspection task.
    """
    lines = [
        "ADDITIONAL COMMITS COULD NOT BE VALIDATED — MANUAL INSPECTION",
        "REQUIRED.",
        "",
        "Validation did not complete for the following commits because",
        "the Claude command-line interface failed for their batch:",
        "",
    ]
    lines.extend(_build_text_listing_unvalidated_commits(unvalidated_commits))
    lines.extend(_build_text_listing_failed_batches(failed_batches))
    lines.extend([
        "Inspect each listed commit message manually against its diff",
        "from the parent commit.  If any need correction, include them",
        "in the same non-interactive ``git rebase -i`` used to apply",
        "the corrections above.",
    ])
    return "\n".join(lines)
