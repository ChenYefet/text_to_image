"""Shared natural-language descriptions of the rules used to validate
commit messages.

Provides text suitable for embedding in prompts that delegate commit
message validation to a large language model.  The rules are expressed
once in this module so that the pre-commit format hook
(``verify_commit_message_uses_header_and_bullet_point_format.py``),
the pre-commit accuracy hook
(``verify_commit_message_against_diff_from_parent.py``), and the
post-rebase validation hook
(``validate_commit_messages_after_rebase.py``) stay in sync when a
rule is tightened, added, or removed.

Two functions are exposed:

- ``build_text_describing_format_rules`` — returns the numbered list of
  format requirements (subject line, blank-line separator, bullet-point
  body, past-tense verbs, Co-Authored-By trailer handling).
- ``build_text_describing_categories_of_accuracy_checks`` — returns the
  numbered list of accuracy-check categories (false claims, references
  to intermediate state, significant omissions, inaccurate
  characterisation).

Each function returns the rule text alone, without surrounding
scaffolding, so that callers can embed it under the introductory
phrasing appropriate to their own prompt.
"""


def build_text_describing_format_rules() -> str:
    """Return the natural-language description of the format rules for
    commit messages.

    The text is a numbered list with one rule per item.  Callers embed
    it in a validation prompt by prefixing their own introduction
    (e.g. ``"Check that the message satisfies every rule below:"``).
    """
    return (
        "1. The message must have a single subject line (the "
        "header).\n"
        "2. The header must use present-tense imperative mood "
        "(e.g. 'Add', 'Remove', 'Update', 'Fix', 'Rename', "
        "'Replace').  A header that begins with a past-tense verb "
        "(e.g. 'Added', 'Removed', 'Updated', 'Fixed') is a "
        "violation.\n"
        "3. A message that contains any line beyond the subject "
        "line must have an empty line immediately following the "
        "subject line, separating the subject from the body.  A "
        "second non-empty line that directly follows the subject "
        "line, with no empty line between them, is a violation.\n"
        "4. If a body is present (text after the empty line "
        "following the subject line), it must use bullet points "
        "(lines beginning with ``- ``) — never prose paragraphs.\n"
        "5. If a bullet point begins with a verb, that verb must "
        "be in the past tense (e.g. 'Added', 'Removed', 'Updated', "
        "'Fixed', 'Replaced', 'Renamed').  A bullet point that "
        "begins with a present-tense verb (e.g. 'Add', 'Remove', "
        "'Update', 'Fix') is a violation.  A bullet point that "
        "begins with a non-verb word is acceptable regardless of "
        "tense.\n"
        "6. A Co-Authored-By trailer line at the end of the "
        "message is not part of the body and shall be ignored "
        "during format analysis.\n"
        "7. A commit message that consists of only a subject "
        "line, with no body, is acceptable."
    )


def build_text_describing_categories_of_accuracy_checks() -> str:
    """Return the natural-language description of the accuracy-check
    categories for commit messages.

    The text is a numbered list with one category per item.  Callers
    embed it in a validation prompt by prefixing their own introduction
    (e.g. ``"Check that the message accurately describes the diff "
    "from the parent commit.  Check for:"``).
    """
    return (
        "1. **False claims**: the message describes changes that "
        "are NOT present in the diff — for example, claiming to "
        "'replace X with Y' when X does not appear in the removed "
        "lines, or claiming to 'remove Z' when Z is not removed in "
        "the diff.\n"
        "2. **References to intermediate state**: the message "
        "describes changes relative to an intermediate editing "
        "state rather than relative to the parent commit.  This "
        "happens when a commit is amended multiple times and the "
        "message still describes a delta between edits rather than "
        "the delta from the parent.\n"
        "3. **Significant omissions**: the diff contains changes "
        "that represent a distinct purpose or intent not covered "
        "by any part of the message.  Supporting implementation "
        "details that serve a described change do not need to be "
        "mentioned separately.\n"
        "4. **Inaccurate characterisation**: the message "
        "mischaracterises a change — for example, saying 'add' "
        "for something that already existed in the parent and was "
        "modified, or saying 'remove' for something that was "
        "restructured."
    )
