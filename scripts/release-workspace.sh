#!/usr/bin/env bash
# Release a workspace claimed by scripts/claim-workspace.sh, once its PR is
# merged (or abandoned). Reverse of the claim:
#   - If the branch held the MAIN checkout, drop the lock and return main to
#     master (refusing if there is still uncommitted work to lose).
#   - If the branch had a linked worktree, remove it.
#
# Usage: scripts/release-workspace.sh <area>/<slug>
#   FORCE=1 to remove a worktree that still has uncommitted changes.
set -euo pipefail

branch="${1:-}"
if [[ -z "$branch" ]]; then
    echo "usage: scripts/release-workspace.sh <area>/<slug>" >&2
    exit 2
fi

common_dir="$(cd "$(git rev-parse --git-common-dir)" && pwd)"
main_root="$(git worktree list --porcelain | sed -n 's/^worktree //p' | head -1)"
lock="${common_dir}/main-workspace.lock"
slug="${branch//\//-}"
wt="${main_root}-worktrees/${slug}"

if [[ -f "${lock}/branch" && "$(cat "${lock}/branch")" == "$branch" ]]; then
    if [[ -n "$(git -C "$main_root" status --porcelain)" && "${FORCE:-}" != "1" ]]; then
        echo "Main checkout has uncommitted changes; commit/stash them or set FORCE=1." >&2
        exit 1
    fi
    git -C "$main_root" checkout -q master
    rm -rf "$lock"
    echo "Released the main-checkout claim for '$branch'; main is back on master." >&2
elif [[ -d "$wt" ]]; then
    git -C "$main_root" worktree remove ${FORCE:+--force} "$wt"
    echo "Removed the worktree for '$branch'." >&2
else
    echo "No workspace found for '$branch' (already released?)." >&2
fi
