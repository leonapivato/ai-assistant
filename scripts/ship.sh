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
# unreviewed — shipping here would report a review of something else.
if ! git diff --quiet || ! git diff --cached --quiet; then
    die "working tree is dirty — commit (or stash) before shipping"
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

echo "ship: posting ${#artifacts[@]} review(s) for ${sha:0:12} to PR #${num}…" >&2
gh pr comment "$num" --body-file "$body"
echo "ship: done. Resolve or file issues for any blocker/major finding before merging." >&2
