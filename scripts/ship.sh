#!/usr/bin/env bash
# Report the local Codex review to the pull request — the merge-readiness step
# (ADR-0015 §1).
#
# Review runs locally now, so the PR record depends on someone pasting it. This
# script is that paste, with the forgettable parts checked rather than trusted:
# it refuses unless a review artifact exists for the *exact* commit the PR head
# points at. The common failure under a paste-it-yourself norm is a review of a
# stale commit — that one is now mechanical.
#
# Deliberately not a pre-push hook: review is a pre-merge step, not a per-push
# one. Gating every push would force a full Codex run per WIP commit, which is
# the fix-per-finding cost pattern ADR-0015 exists to remove.
#
# Usage: scripts/ship.sh
set -euo pipefail

die() {
    echo "ship: $1" >&2
    exit 1
}

command -v gh >/dev/null 2>&1 || die "gh CLI not found on PATH"

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

branch="$(git rev-parse --abbrev-ref HEAD)"
[[ "$branch" == "HEAD" ]] && die "detached HEAD — check out the PR branch first"
[[ "$branch" == "main" ]] && die "on main; ship reports a PR branch's review"

# The review covers the committed diff, so uncommitted work is by definition
# unreviewed — shipping here would report a review of something else. Use
# `status --porcelain`, not `diff --quiet`: an untracked file is unreviewed work
# too, and a pair of diff checks silently passes it.
if [[ -n "$(git status --porcelain)" ]]; then
    die "working tree is dirty (tracked or untracked) — commit or stash first"
fi

sha="$(git rev-parse HEAD)"

# The PR must already show this commit, or the review would name a SHA a reader
# cannot find on the PR.
pr_sha="$(gh pr view --json headRefOid --jq .headRefOid 2>/dev/null || true)"
[[ -z "$pr_sha" ]] && die "no PR found for '${branch}' — open one first (gh pr create)"
if [[ "$pr_sha" != "$sha" ]]; then
    die "PR head is ${pr_sha:0:12} but HEAD is ${sha:0:12} — push first"
fi

# Adversarial is the required lens before merge; architecture is additionally
# required for a contract change, and is posted too whenever it was run.
shopt -s nullglob
artifacts=(".review/${sha}-"*.md)
shopt -u nullglob

if [[ ! -f ".review/${sha}-adversarial.md" ]]; then
    stale=""
    if compgen -G ".review/*.md" >/dev/null; then
        stale=" (reviews exist for other commits — they do not cover ${sha:0:12})"
    fi
    die "no adversarial review for ${sha:0:12}${stale}
     run: just review-codex adversarial"
fi

# A change to the shared contract surface needs the architecture lens too
# (CONTRIBUTING, "Contract ADRs land before their implementation"). That was
# documented but unenforced, which is precisely the prose-not-mechanism failure
# ADR-0015 exists to correct — so check it here rather than trusting recall.
base_ref="$(gh pr view --json baseRefName --jq .baseRefName 2>/dev/null || true)"
[[ -z "$base_ref" ]] && die "could not resolve the PR's base branch"
# Fetch the base so the comparison is against the real merge target, not a
# possibly-stale local ref; FETCH_HEAD is that ref as of this moment.
git fetch --no-tags --quiet origin "$base_ref" ||
    die "could not fetch base '${base_ref}' to check for contract changes"

# Capture the file list before matching, rather than piping git into `grep -q`.
# `grep -q` exits at the first match and closes the pipe; on a diff large enough
# to fill the pipe buffer, git then dies of SIGPIPE and — under `set -o
# pipefail` — the whole pipeline reports failure. The `if` would read that as
# "no core change" and skip the architecture requirement entirely: a fail-open
# on the one check that guards the shared contract surface.
changed_files="$(git diff --name-only "FETCH_HEAD...${sha}")"
if grep -qE '^src/ai_assistant/core/(protocols|types)\.py$' <<<"$changed_files"; then
    if [[ ! -f ".review/${sha}-architecture.md" ]]; then
        die "this change touches core/protocols.py or core/types.py, so it needs
     the architecture lens as well as the adversarial one
     run: just review-codex architecture"
    fi
fi

# Naming the right commit is not enough: a review run against a narrower base
# (`just review-codex adversarial HEAD~1`) covers only part of the PR yet
# produces a correctly-named artifact. Compare the range each review actually
# covered against the PR's own merge base.
expected_base="$(git merge-base FETCH_HEAD "$sha")"
for a in "${artifacts[@]}"; do
    recorded_base="$(sed -n '1s/.*base_sha=\([0-9a-f]*\).*/\1/p' "$a")"
    if [[ "$recorded_base" != "$expected_base" ]]; then
        die "$(basename "$a") reviewed a different range than this PR covers
     (recorded base ${recorded_base:-none}, PR base ${expected_base:0:12})
     re-run the review with its default base: just review-codex <persona>"
    fi
done

num="$(gh pr view --json number --jq .number)"
body="$(mktemp)"
trap 'rm -f "$body"' EXIT

{
    echo "🔍 **Local Codex review** — commit \`${sha:0:12}\`"
    echo
    for a in "${artifacts[@]}"; do
        persona="$(basename "$a" .md)"
        persona="${persona#"${sha}-"}"
        echo "<details><summary><strong>${persona}</strong></summary>"
        echo
        # Drop the provenance comment; it is metadata for this script, not for
        # a reader of the PR.
        tail -n +2 "$a"
        echo
        echo "</details>"
        echo
    done
} >"$body"

# One comment, posted once — the whole report is a single API call, so there is
# no partial-success state to reconcile. (Posting per persona would avoid the
# shared size budget below, but a transient failure on the second call would
# leave the first posted and make re-running `ship` duplicate it.)
#
# One call is not the same as idempotent: if GitHub creates the comment but the
# response is lost, `gh` reports failure and a re-run posts a duplicate. That
# window is narrow and its outcome is cosmetic — two identical reviews on a PR,
# not a false record — so it is tracked rather than solved here.
#
# GitHub rejects a body over 65536 characters, and nothing here is truncated:
# cutting at a byte boundary drops the tail, which is exactly where the ranked
# findings and the verdict sit. A silently-shortened review posted as a
# successful ship is worse than no comment, so an oversized report fails closed.
max_bytes=60000
if [[ "$(wc -c <"$body")" -gt "$max_bytes" ]]; then
    die "the review report is over ${max_bytes} bytes and cannot be posted intact
     truncating it would risk dropping the findings and the verdict
     post it by hand, or re-run the review to get a shorter one"
fi

# Re-read the PR head immediately before posting. Fetching the base and building
# the body takes seconds, and a push landing in that window would leave a review
# on the PR that reads as current but covers superseded code. This cannot be
# atomic with comment creation — hence the SHA in the comment header as well —
# but it closes the realistic window rather than the theoretical one.
if [[ "$(gh pr view --json headRefOid --jq .headRefOid)" != "$sha" ]]; then
    die "PR head moved while preparing the review — re-run ship"
fi

echo "ship: posting ${#artifacts[@]} review(s) for ${sha:0:12} to PR #${num}…" >&2
gh pr comment "$num" --body-file "$body"
echo "ship: done. Resolve or file issues for any blocker/major finding before merging." >&2
