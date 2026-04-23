"""Detection of git-rebase completion and enumeration of the commits the
rebase has changed.

Provides the two families of primitives on which the post-rebase
validation hook depends:

- **Rebase-completion detection**: functions that determine whether a
  ``git rebase`` invocation has finished and whether the HEAD movement
  it produced belongs to the just-returned Bash invocation, including
  ``resolve_path_inside_git_directory`` for worktree-aware rebase-state
  path resolution, ``is_rebase_still_in_progress`` for the in-progress
  gate, and ``was_head_last_modified_by_a_recent_rebase_completion``
  for the freshness check against the HEAD reflog.
- **Enumeration of changed commits**: functions that list the commits
  created by the rebase (``get_new_commits_after_rebase``), retrieve
  per-commit metadata (``get_commit_message``,
  ``get_first_parent_hash``, ``get_number_of_parents``,
  ``get_diff_between_parent_and_commit``), compute patch-id mappings
  between pre-rebase and post-rebase revision ranges
  (``get_merge_base``,
  ``get_mapping_from_patch_id_to_commit_hash_for_revision_range``),
  and narrow the commit list to those whose content or message
  actually changed (``select_commits_changed_by_rebase``).

All primitives invoke ``git`` as a subprocess and return parsed
results, returning ``None`` or an empty container on any subprocess
failure so that callers can fall back to a safe default.
"""

import pathlib
import subprocess
import time


# Maximum age, in seconds, of the most recent HEAD reflog entry for
# it to be attributed to the Bash invocation that just returned.  The
# post-rebase hook fires immediately after ``git rebase`` returns, so
# a successful rebase completion produces a HEAD reflog entry whose
# timestamp is effectively ``now``.  Anything older than this
# threshold indicates that HEAD was last modified by a prior operation
# — most commonly a rebase completed several commands ago whose
# ORIG_HEAD has not been overwritten since — and the current
# invocation therefore did not produce a new HEAD movement to
# validate.  Why not 60 seconds (roughly the per-batch validation
# timeout): A single rebase that applies many commits, each of which
# involves content-aware merging, can legitimately take longer than a
# minute on slower machines, and the reflog timestamp records the
# final HEAD movement (at the end of the rebase), not the command's
# start.  A 60-second ceiling would reject legitimate slow rebases as
# stale.  Why not 3 600 seconds (one hour): Would allow an hour-old
# HEAD movement to be treated as current, defeating the purpose of
# the freshness check entirely.  300 seconds (five minutes) is long
# enough to cover the tail of realistic rebases plus a generous
# allowance for machine clock skew, and short enough that no unrelated
# operation from a prior command can be mistaken for the current one.
_MAXIMUM_AGE_IN_SECONDS_OF_HEAD_REFLOG_ENTRY_FOR_ATTRIBUTION_TO_CURRENT_INVOCATION = (
    300
)


def resolve_path_inside_git_directory(
    name_inside_git_directory: str,
) -> pathlib.Path | None:
    """Return the filesystem path that git uses for a given name inside
    its effective git directory.

    Delegates to ``git rev-parse --git-path`` so that the correct path
    is produced regardless of the repository layout: in a linked
    worktree the rebase state lives under
    ``.git/worktrees/<name>/rebase-merge`` rather than under
    ``.git/rebase-merge``, and in a bare repository there is no
    ``.git/`` directory at all.  The returned path is emitted by git
    relative to the current working directory and may be used directly
    with ``pathlib.Path`` operations.

    Returns None if git is unavailable or returns an error.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-path", name_inside_git_directory],
            capture_output=True,
            encoding="utf-8",
            timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None

    if result.returncode != 0:
        return None

    resolved_path_text = result.stdout.strip()
    if not resolved_path_text:
        return None

    return pathlib.Path(resolved_path_text)


def is_rebase_still_in_progress() -> bool:
    """Return True if a rebase is currently in progress (not yet completed).

    Git stores rebase state under ``rebase-merge/`` during
    ``git rebase -i`` and ``git rebase``, and under ``rebase-apply/``
    during ``git am`` and older-style rebases.  The presence of either
    directory inside the effective git directory indicates that the
    rebase stopped (for conflicts or editing) and has not yet
    completed.

    Paths are resolved via ``git rev-parse --git-path`` so that the
    check remains correct in linked worktrees (where the rebase state
    lives under ``.git/worktrees/<name>/``) and in bare repositories
    (where the git directory is not named ``.git``).
    """
    for name_inside_git_directory in ("rebase-merge", "rebase-apply"):
        resolved_path = resolve_path_inside_git_directory(
            name_inside_git_directory
        )
        if resolved_path is not None and resolved_path.is_dir():
            return True
    return False


def was_head_last_modified_by_a_recent_rebase_completion() -> bool:
    """Return True if the most recent reflog entry on HEAD was produced
    by a rebase and is recent enough to be attributed to the Bash
    invocation that just returned.

    Uses ``git reflog HEAD -1 --format=%ct %gs`` to retrieve both the
    timestamp (``%ct``, committer date as Unix seconds) and the subject
    (``%gs``, the reflog message) of the most recent HEAD reflog entry.
    The entry is attributed to the current invocation when both of the
    following hold:

    - Its subject begins with ``rebase`` — the reflog subjects that git
      emits for rebase-produced HEAD movements include
      ``rebase (start)``, ``rebase (pick)``, ``rebase (reword)``,
      ``rebase (continue)``, and ``rebase (finish)``, and all of them
      share the ``rebase`` prefix.  Any other prefix indicates that
      HEAD was last moved by a non-rebase operation (commit, merge,
      reset, checkout), which means ``ORIG_HEAD..HEAD`` cannot be
      interpreted as the output of a just-completed rebase.
    - Its timestamp is within the attribution window defined by
      ``_MAXIMUM_AGE_IN_SECONDS_OF_HEAD_REFLOG_ENTRY_FOR_ATTRIBUTION_TO_CURRENT_INVOCATION``.
      A rebase reflog entry from a command several interactions ago
      would still match the subject check, but its ORIG_HEAD and HEAD
      pointers have long been validated; re-running the model against
      them is wasted cost.

    Returns False — the safe default — whenever the reflog cannot be
    read, is empty, or fails either check.  A False return skips the
    current invocation's validation, which is preferable to
    revalidating commits whose state does not belong to this
    invocation.
    """
    try:
        result = subprocess.run(
            ["git", "reflog", "HEAD", "-1", "--format=%ct %gs"],
            capture_output=True,
            encoding="utf-8",
            timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False

    if result.returncode != 0:
        return False

    output = result.stdout.strip()
    if not output:
        return False

    timestamp_and_subject = output.split(" ", 1)
    if len(timestamp_and_subject) != 2:
        return False

    timestamp_text, subject = timestamp_and_subject
    try:
        timestamp_of_entry_in_seconds = int(timestamp_text)
    except ValueError:
        return False

    if not subject.startswith("rebase"):
        return False

    current_time_in_seconds = int(time.time())
    age_of_entry_in_seconds = (
        current_time_in_seconds - timestamp_of_entry_in_seconds
    )
    return (
        0
        <= age_of_entry_in_seconds
        <= _MAXIMUM_AGE_IN_SECONDS_OF_HEAD_REFLOG_ENTRY_FOR_ATTRIBUTION_TO_CURRENT_INVOCATION
    )


def get_new_commits_after_rebase() -> list[str]:
    """Return the commit hashes created by the most recent rebase.

    Uses ``ORIG_HEAD..HEAD`` to identify commits that are reachable
    from HEAD but were not reachable from the pre-rebase HEAD.
    Returns commits in chronological order (oldest first) as full
    40-character SHA-1 hashes.  Returns an empty list if ORIG_HEAD is
    not set or no new commits exist.
    """
    try:
        result = subprocess.run(
            ["git", "log", "--format=%H", "--reverse", "ORIG_HEAD..HEAD"],
            capture_output=True,
            encoding="utf-8",
            timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []

    if result.returncode != 0:
        return []

    return [h.strip() for h in result.stdout.strip().split("\n") if h.strip()]


def get_commit_message(commit_hash: str) -> str | None:
    """Return the commit message of the given commit."""
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%B", commit_hash],
            capture_output=True,
            encoding="utf-8",
            timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None

    if result.returncode != 0:
        return None

    output = result.stdout.strip()
    return output if output else None


def get_first_parent_hash(commit_hash: str) -> str | None:
    """Return the hash of the first parent of *commit_hash*.

    Uses ``git rev-parse --verify <commit>^1`` to resolve the parent.
    Returns None for root commits (no first parent) and on any
    subprocess failure.  The two cases share a return value because
    they cannot be distinguished from the exit code of
    ``git rev-parse --verify`` alone; in the post-rebase context the
    overwhelmingly common cause is a root commit produced by
    ``git rebase --root``.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", f"{commit_hash}^1"],
            capture_output=True,
            encoding="utf-8",
            timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None

    if result.returncode != 0:
        return None

    first_parent_hash = result.stdout.strip()
    return first_parent_hash if first_parent_hash else None


def get_number_of_parents(commit_hash: str) -> int | None:
    """Return the number of parents of *commit_hash*.

    Uses ``git show --no-patch --format=%P`` so that every parent is
    listed in a single line of output regardless of how many parents
    the commit has.  The returned integer has the following meaning:

    - ``0``: a root commit, typically produced by
      ``git rebase --root``.
    - ``1``: a standard commit whose history is linear at this point.
    - ``2`` or more: a merge commit, typically preserved by
      ``git rebase --rebase-merges``.

    Returns ``None`` on any subprocess failure so that callers can
    fall back to a safe default — treating the commit as non-merge —
    rather than assume a false exemption when the parent count cannot
    be determined.
    """
    try:
        result = subprocess.run(
            ["git", "show", "--no-patch", "--format=%P", commit_hash],
            capture_output=True,
            encoding="utf-8",
            timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None

    if result.returncode != 0:
        return None

    parent_hashes_field = result.stdout.strip()
    if not parent_hashes_field:
        return 0
    return len(parent_hashes_field.split())


def get_diff_between_parent_and_commit(
    parent_hash: str, commit_hash: str,
) -> str | None:
    """Return the diff between *parent_hash* and *commit_hash*.

    Uses ``git diff-tree -p <parent_hash> <commit_hash>`` to produce a
    normal (non-combined) diff.  For merge commits, the default
    ``git diff-tree -p <commit>`` form produces a combined diff that
    is empty for clean merges; with explicit two-tree arguments the
    first-parent diff is emitted regardless of whether the commit is
    a merge, so merge commits produced by ``git rebase --rebase-merges``
    are included in validation rather than silently dropped.

    Returns None for empty diffs (e.g. an empty commit created with
    ``git commit --allow-empty``) and on any subprocess failure.
    """
    try:
        result = subprocess.run(
            ["git", "diff-tree", "-p", parent_hash, commit_hash],
            capture_output=True,
            encoding="utf-8",
            timeout=30,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None

    if result.returncode != 0:
        return None

    diff_output = result.stdout.strip()
    return diff_output if diff_output else None


def get_merge_base(revision_1: str, revision_2: str) -> str | None:
    """Return the merge base of two revisions, or None if none exists
    or the command fails."""
    try:
        result = subprocess.run(
            ["git", "merge-base", revision_1, revision_2],
            capture_output=True,
            encoding="utf-8",
            timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None

    if result.returncode != 0:
        return None

    merge_base_text = result.stdout.strip()
    return merge_base_text if merge_base_text else None


def get_mapping_from_patch_id_to_commit_hash_for_revision_range(
    revision_range: str,
) -> dict[str, str]:
    """Return a mapping from patch-id to commit hash for every commit
    in the given revision range.

    Pipes the output of ``git log -p <revision_range>`` into
    ``git patch-id --stable``.  Patch-ids are computed to be invariant
    to whitespace changes, line-number shifts, and context differences
    introduced by rebasing onto a new parent, so two commits with the
    same patch-id record the same conceptual change even if their
    diffs against their respective parents differ textually.

    Returns an empty dict if either subprocess fails, so that callers
    fall back to full validation rather than silently skipping commits
    on a transient failure.
    """
    try:
        log_process = subprocess.run(
            ["git", "log", "-p", "--reverse", revision_range],
            capture_output=True,
            encoding="utf-8",
            timeout=30,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return {}

    if log_process.returncode != 0 or not log_process.stdout:
        return {}

    try:
        patch_id_process = subprocess.run(
            ["git", "patch-id", "--stable"],
            input=log_process.stdout,
            capture_output=True,
            encoding="utf-8",
            timeout=30,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return {}

    if patch_id_process.returncode != 0:
        return {}

    patch_id_to_commit_hash: dict[str, str] = {}
    for line in patch_id_process.stdout.splitlines():
        fields = line.split()
        if len(fields) >= 2:
            patch_id_value, commit_hash_value = fields[0], fields[1]
            patch_id_to_commit_hash[patch_id_value] = commit_hash_value

    return patch_id_to_commit_hash


def select_commits_changed_by_rebase(
    commit_hashes_in_new_range: list[str],
) -> list[str]:
    """Return the subset of post-rebase commits that actually require
    revalidation.

    Matches each commit in ``ORIG_HEAD..HEAD`` to a pre-rebase commit
    in ``merge-base(ORIG_HEAD, HEAD)..ORIG_HEAD`` by patch-id.  A
    commit is retained for validation if any of the following holds:

    - Its patch-id has no match in the pre-rebase range (the commit
      introduces genuinely new content).
    - Its patch-id matches a pre-rebase commit whose message differs
      (the rebase reworded the commit).
    - Patch-id matching cannot be performed for any reason (the
      function falls back to returning the full input list so that
      validation proceeds over every commit rather than silently
      skipping any).

    A commit is dropped from validation only when its patch-id matches
    a pre-rebase commit whose message is byte-identical.  In that case
    the rebase has produced an exact content-and-message replica, so
    there is nothing new for the validation model to assess, and
    issuing a call would risk flagging the message as inaccurate
    merely because the diff against the new parent differs in context
    or conflict resolution.
    """
    merge_base_commit = get_merge_base("ORIG_HEAD", "HEAD")
    if merge_base_commit is None:
        return commit_hashes_in_new_range

    patch_id_to_pre_rebase_hash = (
        get_mapping_from_patch_id_to_commit_hash_for_revision_range(
            f"{merge_base_commit}..ORIG_HEAD"
        )
    )
    if not patch_id_to_pre_rebase_hash:
        return commit_hashes_in_new_range

    patch_id_to_post_rebase_hash = (
        get_mapping_from_patch_id_to_commit_hash_for_revision_range(
            "ORIG_HEAD..HEAD"
        )
    )
    if not patch_id_to_post_rebase_hash:
        return commit_hashes_in_new_range

    post_rebase_hash_to_patch_id = {
        commit_hash_value: patch_id_value
        for patch_id_value, commit_hash_value
        in patch_id_to_post_rebase_hash.items()
    }

    commit_hashes_to_validate: list[str] = []
    for commit_hash in commit_hashes_in_new_range:
        patch_id_of_this_commit = post_rebase_hash_to_patch_id.get(commit_hash)
        if patch_id_of_this_commit is None:
            commit_hashes_to_validate.append(commit_hash)
            continue
        pre_rebase_counterpart = patch_id_to_pre_rebase_hash.get(
            patch_id_of_this_commit
        )
        if pre_rebase_counterpart is None:
            commit_hashes_to_validate.append(commit_hash)
            continue
        message_of_pre_rebase_counterpart = get_commit_message(
            pre_rebase_counterpart
        )
        message_of_post_rebase_commit = get_commit_message(commit_hash)
        if (
            message_of_pre_rebase_counterpart is None
            or message_of_post_rebase_commit is None
        ):
            commit_hashes_to_validate.append(commit_hash)
            continue
        if message_of_pre_rebase_counterpart != message_of_post_rebase_commit:
            commit_hashes_to_validate.append(commit_hash)

    return commit_hashes_to_validate
