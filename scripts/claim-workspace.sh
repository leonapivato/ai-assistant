#!/usr/bin/env bash
# Allocate an isolated workspace for one unit of work — one branch, one PR — so
# that parallel agents never share a working tree. Sharing one is what let a
# `git add -A` once sweep another agent's uncommitted files into the wrong
# commit; separate directories make that impossible.
#
# Allocation is deterministic, not guessed:
#   - The FIRST agent claims the MAIN checkout (no worktree, no extra `uv sync`)
#     — but only while it is a clean `master`. The claim is an atomic lock, so
#     two agents racing cannot both win it.
#   - Every ADDITIONAL concurrent agent gets its own linked worktree beside the
#     repo. Git already enforces one-branch-per-worktree, so this maps cleanly.
# Either way the branch is created and the environment bootstrapped, and the
# resolved workspace path is printed as the final `WORKSPACE=<path>` line.
#
# Usage: scripts/claim-workspace.sh <area>/<slug>   (e.g. memory/add-cache)
# Then work ONLY in the printed workspace. Release with scripts/release-workspace.sh.
set -euo pipefail

branch="${1:-}"
if [[ -z "$branch" || "$branch" != */* ]]; then
    echo "usage: scripts/claim-workspace.sh <area>/<slug>  (e.g. memory/add-cache)" >&2
    exit 2
fi

# The shared git dir, this workspace's git dir, and the main checkout (the first
# worktree git lists). A linked worktree's git dir differs from the common one.
common_dir="$(cd "$(git rev-parse --git-common-dir)" && pwd)"
git_dir="$(cd "$(git rev-parse --git-dir)" && pwd)"
main_root="$(git worktree list --porcelain | sed -n 's/^worktree //p' | head -1)"
lock="${common_dir}/main-workspace.lock"
worktrees_root="${main_root}-worktrees"
slug="${branch//\//-}"

bootstrap() {
    # Recreate the untracked local state a fresh workspace needs: the venv (uv's
    # cache makes this cheap after the first sync) and git-ignored config the
    # gate/tools rely on. A shared venv is not an option — the editable install
    # is path-specific.
    ( cd "$1" && uv sync --quiet )
    for rel in .env .claude/settings.local.json; do
        if [[ -f "${main_root}/${rel}" && ! -e "${1}/${rel}" ]]; then
            mkdir -p "${1}/$(dirname "$rel")"
            cp "${main_root}/${rel}" "${1}/${rel}"
        fi
    done
}

# Case 1: already inside a linked worktree — we are already allocated.
if [[ "$git_dir" != "$common_dir" ]]; then
    bootstrap "$PWD"
    echo "Already in a worktree on '$(git branch --show-current)'; bootstrapped." >&2
    echo "WORKSPACE=$(git rev-parse --show-toplevel)"
    exit 0
fi

# Case 2: in the main checkout. Claim it only if it is a clean master AND we win
# the atomic lock; otherwise fall through to a worktree.
main_is_free() {
    [[ "$(git -C "$main_root" symbolic-ref --quiet --short HEAD 2>/dev/null)" == "master" ]] &&
        [[ -z "$(git -C "$main_root" status --porcelain)" ]]
}

if main_is_free && mkdir "$lock" 2>/dev/null; then
    printf '%s\n' "$branch" >"${lock}/branch"
    git -C "$main_root" checkout -q -b "$branch"
    bootstrap "$main_root"
    echo "Claimed the MAIN checkout for '$branch'." >&2
    echo "WORKSPACE=$main_root"
else
    mkdir -p "$worktrees_root"
    wt="${worktrees_root}/${slug}"
    git -C "$main_root" worktree add -q "$wt" -b "$branch"
    bootstrap "$wt"
    main_is_free || echo "(main checkout is not a clean master)" >&2
    echo "Main checkout unavailable; created a worktree for '$branch'." >&2
    echo "WORKSPACE=$wt"
fi
