#!/usr/bin/env bash
# Release a workspace claimed by scripts/claim-workspace.sh, once its PR merges
# (or is abandoned). Reverse of the claim:
#   - Main-checkout claim: return the main checkout to master and drop the lock.
#     Refuses if there is uncommitted work, unless FORCE=1 — which *deliberately
#     discards* it (a hard checkout), never carries it onto master.
#   - Worktree: remove the worktree that git reports is actually checked out to
#     <branch> (looked up from git, never guessed from a slugged path, so two
#     similar branch names cannot remove each other's worktree). Refuses on a
#     dirty worktree unless FORCE=1.
#
# Usage: scripts/release-workspace.sh <area>/<slug>
#   FORCE=1  discard uncommitted changes (any other value, or unset, does not).
set -euo pipefail

branch="${1:-}"
if [[ -z "$branch" ]]; then
    echo "usage: scripts/release-workspace.sh <area>/<slug>" >&2
    exit 2
fi
force=0
[[ "${FORCE:-}" == "1" ]] && force=1

common_dir="$(cd "$(git rev-parse --git-common-dir)" && pwd)"
main_root="$(git worktree list --porcelain | sed -n 's/^worktree //p' | head -1)"
lock="${common_dir}/main-workspace.lock"

# Path of the worktree actually checked out to this branch — asked of git, so it
# is collision-free regardless of how the branch name slugs to a directory.
wt_path="$(git worktree list --porcelain | awk -v ref="refs/heads/${branch}" '
    /^worktree /{path = substr($0, 10)}
    /^branch /{if ($2 == ref) print path}')"

if [[ -f "${lock}/branch" && "$(cat "${lock}/branch")" == "$branch" ]]; then
    if [[ -n "$(git -C "$main_root" status --porcelain)" ]]; then
        if (( force )); then
            # Deliberately discard tracked changes and untracked files — including
            # an untracked nested git repo (`-ff`) — so main returns to a genuinely
            # clean master. No `-x`, so ignored paths (.venv/.env) survive.
            git -C "$main_root" checkout -q -f master
            git -C "$main_root" clean -qffd
        else
            echo "Main checkout has uncommitted changes; commit/stash them or set FORCE=1." >&2
            exit 1
        fi
    else
        git -C "$main_root" checkout -q master
    fi
    # Never drop the lock while main is still dirty — that would silently push
    # future claims onto needless worktrees. Verify the postcondition first.
    if [[ -n "$(git -C "$main_root" status --porcelain)" ]]; then
        echo "Main checkout is still dirty after cleanup; NOT releasing the lock — clean it by hand." >&2
        exit 1
    fi
    rm -rf "$lock"
    echo "Released the main-checkout claim for '${branch}'; main is back on master." >&2
elif [[ -n "$wt_path" ]]; then
    if (( force )); then
        git -C "$main_root" worktree remove --force "$wt_path"
    else
        git -C "$main_root" worktree remove "$wt_path"
    fi
    echo "Removed the worktree for '${branch}' (${wt_path})." >&2
elif [[ -d "$lock" && ! -f "${lock}/branch" ]]; then
    # Stale-lock recovery: a claim hard-killed (SIGKILL) between acquiring the
    # lock and writing its metadata leaves an owner-less lock that would wedge the
    # main checkout for every future claim. It has no owner, so clear it.
    rm -rf "$lock"
    echo "Cleared an orphaned main-workspace lock (no owner metadata)." >&2
else
    echo "No workspace found for '${branch}' (already released?)." >&2
fi
