#!/usr/bin/env bash
# Release a workspace claimed by scripts/claim-workspace.sh, once its PR merges
# (or is abandoned). Every claim is a linked worktree (the main checkout is
# never claimed — see claim-workspace.sh), so release always removes the
# worktree that git reports is actually checked out to <branch>, looked up
# from git rather than guessed from a slugged path, so two similar branch
# names cannot remove each other's worktree. Refuses on a dirty worktree
# unless FORCE=1, which *deliberately discards* the uncommitted work.
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

main_root="$(git worktree list --porcelain | sed -n 's/^worktree //p' | head -1)"

# Path of the worktree actually checked out to this branch — asked of git, so it
# is collision-free regardless of how the branch name slugs to a directory.
wt_path="$(git worktree list --porcelain | awk -v ref="refs/heads/${branch}" '
    /^worktree /{path = substr($0, 10)}
    /^branch /{if ($2 == ref) print path}')"

if [[ -n "$wt_path" ]]; then
    if (( force )); then
        git -C "$main_root" worktree remove --force "$wt_path"
    else
        git -C "$main_root" worktree remove "$wt_path"
    fi
    echo "Removed the worktree for '${branch}' (${wt_path})." >&2
else
    echo "No workspace found for '${branch}' (already released?)." >&2
fi
