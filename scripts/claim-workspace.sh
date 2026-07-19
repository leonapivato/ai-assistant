#!/usr/bin/env bash
# Allocate an isolated workspace for one unit of work — one branch, one PR — so
# parallel agents never share a working tree. Sharing one is how a stray
# `git add -A` once swept another agent's uncommitted files into the wrong
# commit; separate directories make that impossible.
#
# Allocation is deterministic:
#   - From the MAIN checkout: the first agent atomically claims it (only while it
#     is a clean master); agents that lose the lock get their own worktree.
#   - From inside a worktree: re-claiming the SAME branch just re-bootstraps; a
#     DIFFERENT branch gets its own new worktree (never silently reuses this one).
#
# The branch name is validated and must not already exist (a task gets a fresh
# branch). If anything fails after resources are acquired, a trap rolls back the
# lock, branch, and any partial worktree — a failed claim never wedges the repo.
# Prints the resolved workspace as the final `WORKSPACE=<path>` line.
#
# Usage: scripts/claim-workspace.sh <area>/<slug>   (e.g. memory/add-cache)
# Env:   WORKSPACE_BOOTSTRAP overrides the bootstrap command (default
#        `uv sync --quiet`); set to `true` to skip it (used by the tests).
# errtrace (-E) so the ERR-trap rollbacks below fire even for failures *inside*
# functions/subshells (e.g. a failing bootstrap) — without it the trap is not
# inherited and a failed claim would leave the lock/branch behind.
set -Eeuo pipefail

branch="${1:-}"
if [[ -z "$branch" || "$branch" != */* ]]; then
    echo "usage: scripts/claim-workspace.sh <area>/<slug>  (e.g. memory/add-cache)" >&2
    exit 2
fi
if ! git check-ref-format "refs/heads/${branch}"; then
    echo "invalid branch name: '${branch}'" >&2
    exit 2
fi

common_dir="$(cd "$(git rev-parse --git-common-dir)" && pwd)"
git_dir="$(cd "$(git rev-parse --git-dir)" && pwd)"
main_root="$(git worktree list --porcelain | sed -n 's/^worktree //p' | head -1)"
lock="${common_dir}/main-workspace.lock"
worktrees_root="${main_root}-worktrees"
# Word-split is intended, so `WORKSPACE_BOOTSTRAP="uv sync --quiet"` runs as argv.
bootstrap_cmd="${WORKSPACE_BOOTSTRAP:-uv sync --quiet}"

# New work branches from origin/master when present, so it starts at the latest
# integration point. This script does no network itself (it stays offline) — the
# caller runs `git fetch origin` first (per CONTRIBUTING) to refresh that ref.
# Falls back to the local master ref when there is no remote-tracking branch.
base=master
if git rev-parse --verify --quiet refs/remotes/origin/master >/dev/null 2>&1; then
    base=origin/master
fi

bootstrap() {
    # Recreate the untracked local state a fresh workspace needs: the venv (uv's
    # cache makes this cheap after the first sync) and git-ignored config the
    # gate/tools rely on. A shared venv is not an option — the editable install
    # is path-specific.
    ( cd "$1" && ${bootstrap_cmd} )
    local rel
    for rel in .env .claude/settings.local.json; do
        if [[ -f "${main_root}/${rel}" && ! -e "${1}/${rel}" ]]; then
            mkdir -p "${1}/$(dirname "${rel}")"
            cp "${main_root}/${rel}" "${1}/${rel}"
        fi
    done
}

create_worktree() {
    # Create a worktree for $branch at a path derived from the *full* branch name
    # (nested, so distinct branches never collide on one directory), rolling back
    # on any failure.
    local wt="${worktrees_root}/${branch}"
    mkdir -p "$(dirname "$wt")"
    # Branch from $base (origin/master when available), never the main checkout's
    # current HEAD — which may be another claimant's branch, whose commits would
    # otherwise leak into this workspace. Trap set immediately, and on INT/TERM
    # too, so an interrupt rolls back the worktree and its branch.
    git -C "$main_root" worktree add -q "$wt" -b "$branch" "$base"
    trap 'git -C "$main_root" worktree remove --force "$wt" 2>/dev/null || true
          git -C "$main_root" branch -D "$branch" 2>/dev/null || true' ERR INT TERM
    bootstrap "$wt"
    trap - ERR INT TERM
    echo "WORKSPACE=${wt}"
}

require_new_branch() {
    # A task gets a *fresh* branch; refuse to reuse an existing one. Checked only
    # on the paths that create a branch — never on an idempotent re-claim of the
    # worktree already on this branch.
    if git show-ref --verify --quiet "refs/heads/${branch}"; then
        echo "branch '${branch}' already exists; pick a new name (a task gets a fresh branch)" >&2
        exit 2
    fi
}

# Case 1: already inside a linked worktree.
if [[ "$git_dir" != "$common_dir" ]]; then
    current="$(git branch --show-current)"
    toplevel="$(git rev-parse --show-toplevel)"
    if [[ "$current" == "$branch" ]]; then
        bootstrap "$toplevel"
        echo "Already in the worktree for '${branch}'; bootstrapped." >&2
        echo "WORKSPACE=${toplevel}"
        exit 0
    fi
    require_new_branch
    echo "In worktree '${current}'; creating a separate worktree for '${branch}'." >&2
    create_worktree
    exit 0
fi

# Case 2: in the main checkout — claim it only if it is a clean master AND we win
# the atomic lock; otherwise fall through to a worktree.
main_is_free() {
    [[ "$(git -C "$main_root" symbolic-ref --quiet --short HEAD 2>/dev/null)" == "master" ]] &&
        [[ -z "$(git -C "$main_root" status --porcelain)" ]]
}

require_new_branch
# Acquire the lock atomically *with* its owner metadata: `noclobber` makes `>`
# an exclusive create (fails if the file exists), and the branch name is written
# in that same step. So the lock never exists in a metadata-less state that a
# concurrent release could mistake for orphaned. Rollback trap installed right
# after, on INT/TERM too.
if main_is_free && (set -o noclobber; printf '%s\n' "$branch" >"$lock") 2>/dev/null; then
    trap 'git -C "$main_root" checkout -q master 2>/dev/null || true
          git -C "$main_root" branch -D "$branch" 2>/dev/null || true
          rm -f "$lock"' ERR INT TERM
    git -C "$main_root" checkout -q -b "$branch" "$base"
    bootstrap "$main_root"
    trap - ERR INT TERM
    echo "Claimed the MAIN checkout for '${branch}'." >&2
    echo "WORKSPACE=${main_root}"
else
    main_is_free || echo "(main checkout is not a clean master)" >&2
    echo "Main checkout unavailable; creating a worktree for '${branch}'." >&2
    create_worktree
fi
