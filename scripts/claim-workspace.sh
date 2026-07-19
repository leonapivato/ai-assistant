#!/usr/bin/env bash
# Allocate an isolated workspace for one unit of work — one branch, one PR — so
# parallel agents never share a working tree. Sharing one is how a stray
# `git add -A` once swept another agent's uncommitted files into the wrong
# commit; separate directories make that impossible.
#
# Every claim gets its own linked worktree, always — there is no shared "first
# agent gets the bare checkout" slot to contend over. That used to exist as an
# optimisation (skip one `uv sync` for the common solo case) but it needed a
# lock file, exclusive-create, and ERR/INT/TERM rollback traps to be race-safe,
# and it only ever protected a single resource that N-agent parallelism doesn't
# actually need. Dropping it removes that whole class of bugs: worktree
# creation for distinct branches is already safe under concurrency (git takes
# care of its own worktree-administration locking), so claiming many
# workspaces at once needs no coordination here at all. The main checkout stays
# on `master` permanently, as a read-only integration copy nobody claims (the
# `no-commit-to-branch` pre-commit hook backs this up).
#
# The branch name is validated and must not already exist (a task gets a fresh
# branch). If anything fails after the worktree is created, a trap rolls back
# the branch and any partial worktree — a failed claim never leaves debris.
# Prints the resolved workspace as the final `WORKSPACE=<path>` line.
#
# Usage: scripts/claim-workspace.sh <area>/<slug>   (e.g. memory/add-cache)
# Env:   WORKSPACE_BOOTSTRAP, if set, overrides the bootstrap step with a single
#        command/executable run without word-splitting (e.g. `true` to skip); the
#        default is `uv sync --quiet`. Used by the tests.
# errtrace (-E) so the ERR-trap rollback below fires even for failures *inside*
# functions/subshells (e.g. a failing bootstrap) — without it the trap is not
# inherited and a failed claim would leave the branch/worktree behind.
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

git_dir="$(cd "$(git rev-parse --git-dir)" && pwd)"
common_dir="$(cd "$(git rev-parse --git-common-dir)" && pwd)"
main_root="$(git worktree list --porcelain | sed -n 's/^worktree //p' | head -1)"
worktrees_root="${main_root}-worktrees"

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
    #
    # WORKSPACE_BOOTSTRAP, if set, overrides the sync with a *single* command or
    # executable, run quoted (no word-splitting, so a spaced path works); tests
    # pass `true`/`false`. Unset uses the real multi-word default.
    if [[ -n "${WORKSPACE_BOOTSTRAP:-}" ]]; then
        ( cd "$1" && "$WORKSPACE_BOOTSTRAP" )
    else
        ( cd "$1" && uv sync --quiet )
    fi
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
    # current HEAD — which stays on master, but this also keeps a second worktree
    # from ever branching off a sibling worktree's HEAD. Trap set immediately,
    # and on INT/TERM too, so an interrupt rolls back the worktree and its
    # branch. `git worktree add` for a fresh branch name is itself safe under
    # concurrency (git serialises its own worktree-administration writes), so
    # many agents can call this at once for distinct branches with no lock here.
    git -C "$main_root" worktree add -q "$wt" -b "$branch" "$base"
    trap 'git -C "$main_root" worktree remove --force "$wt" 2>/dev/null || true
          git -C "$main_root" update-ref -d "refs/workspace-claimed/${branch}" 2>/dev/null || true
          git -C "$main_root" branch -D "$branch" 2>/dev/null || true' ERR INT TERM
    # Tag the branch as ours, in its own ref (never pushed — no `push` default
    # refspec covers refs/workspace-claimed/*, and it is not under
    # refs/heads/, so nothing here is a checkout target). This is what lets
    # prune-workspaces.sh trust "this branch's PR is done" at all: a branch
    # created some other way (a plain `git branch`, never claimed here) might
    # coincidentally share a commit with some old closed PR, and without this
    # marker prune-workspaces.sh could not tell the two apart. Deliberately
    # NOT `git config branch.<name>.*`: that writes the single shared
    # .git/config file, so concurrent claims of distinct branches would
    # serialise on its lock — exactly the contention the always-worktree
    # model exists to avoid. A dedicated ref is its own file with its own
    # lock, the same mechanism that already makes concurrent
    # `git worktree add -b <branch>` calls for distinct branches safe.
    git -C "$main_root" update-ref "refs/workspace-claimed/${branch}" "refs/heads/${branch}"
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
        # (Re-)tag on every idempotent re-claim, not just on first creation.
        # Without this, calling claim-workspace.sh from inside a worktree that
        # was never claimed through this tooling (a plain `git worktree add`)
        # reported success and a usable WORKSPACE= path, but
        # release-workspace.sh / prune-workspaces.sh would then refuse to
        # touch it — claim said "claimed", release said "not ours" (PR #17
        # review). update-ref is idempotent, so re-tagging an already-tagged
        # branch is a no-op.
        git -C "$main_root" update-ref "refs/workspace-claimed/${branch}" "refs/heads/${branch}"
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

# Case 2: in the main checkout. The main checkout is never claimed — it stays on
# master as a read-only integration copy — so every claim from here creates its
# own worktree, same as from inside another worktree.
require_new_branch
create_worktree
