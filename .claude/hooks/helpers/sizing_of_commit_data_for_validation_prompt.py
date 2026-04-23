"""Sizing of commit data sent to the validation prompt.

Bounds the size of the content that the post-rebase validation hook
supplies to the Claude command-line interface, through two
complementary primitives:

- ``truncate_diff_to_maximum_size_with_explicit_marker`` caps the
  per-commit diff at ``MAXIMUM_NUMBER_OF_CHARACTERS_OF_DIFF_PER_COMMIT``
  characters before the commit enters the batching step, so that no
  single commit can dominate the model's attention regardless of its
  actual size.
- ``split_commits_into_batches_under_character_budget`` groups the
  truncated per-commit entries into batches whose aggregated message-
  and diff size stays within
  ``MAXIMUM_NUMBER_OF_CHARACTERS_PER_VALIDATION_BATCH``, so that no
  single call to the validation model overflows the context window or
  runs out of time.

Both limits are sized against the 1 000 000-token context window
available to Claude Sonnet and Opus on this account; the
justifications for their specific values — including the "why not
half, why not double" analysis — are recorded beside each constant.
"""


# Maximum aggregated number of characters of commit message and diff
# content per call to the validation model.  The prompt concatenates
# each commit's message and diff; when this total would exceed the
# budget, the commits are split into multiple batches so that no
# single call to the validation model overflows the context window or
# runs out of time.  1 000 000 characters is roughly 250 000 tokens,
# which is approximately 25% of the 1 000 000-token context window
# available to Claude Sonnet and Opus on this account, leaving ample
# room for prompt scaffolding, the model's response, and safety
# margin against long tail-end reasoning.  A budget this large means
# most real rebases collapse into a single batch, amortising the
# prompt scaffolding across every commit in the rebase rather than
# repeating it per batch.  Why not 500 000 (half): Would split many
# routine multi-commit rebases into two batches for no accuracy
# benefit, doubling calls to the validation model without reducing
# per-call latency below what the model is already handling.  Why
# not 2 000 000 (double): Would require the model to process
# approximately 500 000 tokens per call, approaching half of the
# context window for input alone and leaving too little headroom for
# the 350 000-character per-commit diff cap to coexist with prompt
# scaffolding under worst-case rebases (several very large commits
# in the same batch).
MAXIMUM_NUMBER_OF_CHARACTERS_PER_VALIDATION_BATCH = 1_000_000


# Maximum number of characters of diff content kept per commit before
# truncation.  A diff longer than this is replaced with its prefix and
# an explicit truncation marker, so that no single commit can dominate
# the model's attention regardless of its actual size.  350 000
# characters is roughly 87 500 tokens, which is approximately 9% of
# the 1 000 000-token context window available to Claude Sonnet and
# Opus on this account, and covers diffs of roughly 7 000 to 11 000
# lines — large enough for substantial refactoring commits while
# bounding pathological inputs (vendored dependencies, generated
# files, large binary patches presented as text) to a single-digit
# fraction of the context.  Why not 175 000 (half): Would truncate
# legitimate large-refactor commits that the 1 000 000-token context
# window can easily accommodate, discarding accuracy signal that
# there is room to keep.  Why not 700 000 (double): Would allow a
# single commit to occupy close to 20% of the context window,
# crowding out prompt scaffolding and other commits sharing the same
# batch, and investing context in the unlikely tail of a commit
# whose message almost certainly does not depend on content beyond
# the first 350 000 characters of its diff.
MAXIMUM_NUMBER_OF_CHARACTERS_OF_DIFF_PER_COMMIT = 350_000


def truncate_diff_to_maximum_size_with_explicit_marker(
    diff: str, maximum_number_of_characters: int,
) -> str:
    """Return *diff* unchanged if it is at most
    *maximum_number_of_characters* long, otherwise return its prefix
    of *maximum_number_of_characters* followed by an explicit
    truncation marker that names the original size and the visible
    portion.

    The marker is written so that the validation model is aware that
    the diff has been truncated and can caveat its accuracy assessment
    accordingly, rather than silently treating the truncated content
    as the entire change.
    """
    if len(diff) <= maximum_number_of_characters:
        return diff

    truncated_prefix = diff[:maximum_number_of_characters]
    marker = (
        f"\n\n[DIFF TRUNCATED — ORIGINAL SIZE WAS {len(diff)} "
        f"CHARACTERS, FIRST {maximum_number_of_characters} CHARACTERS "
        "SHOWN; REMAINING CONTENT IS NOT VISIBLE TO THE VALIDATION "
        "MODEL]\n"
    )
    return truncated_prefix + marker


def split_commits_into_batches_under_character_budget(
    commits_data: list[dict],
    maximum_number_of_characters_per_batch: int,
) -> list[list[dict]]:
    """Split *commits_data* into batches whose aggregated message and
    diff size stays under the character budget.

    Batches are filled greedily in input order so that chronological
    order is preserved across batches.  A single commit whose own size
    exceeds the budget is emitted as a batch of one — the budget is
    an approximate target for normal batches, not a hard ceiling, and
    downstream handling may truncate or reject such an outsized commit.
    """
    batches: list[list[dict]] = []
    current_batch: list[dict] = []
    current_batch_size_in_characters = 0

    for commit_data in commits_data:
        size_of_this_commit = len(commit_data["message"]) + len(
            commit_data["diff"]
        )
        if (
            current_batch
            and current_batch_size_in_characters + size_of_this_commit
            > maximum_number_of_characters_per_batch
        ):
            batches.append(current_batch)
            current_batch = []
            current_batch_size_in_characters = 0
        current_batch.append(commit_data)
        current_batch_size_in_characters += size_of_this_commit

    if current_batch:
        batches.append(current_batch)

    return batches
