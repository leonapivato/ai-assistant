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
    # `created` gates the trap's cleanup on whether THIS invocation's own
    # `git worktree add` actually succeeded — not merely on the trap having
    # fired. Two agents racing to claim the *same* branch name can both pass
    # require_new_branch's pre-check and both reach `git worktree add` below;
    # git's own ref-locking guarantees only one of the two actually creates
    # the branch, but the loser's `git worktree add` then fails at the exact
    # same path/branch the winner just created. An unconditional trap here
    # would force-remove that shared path and delete that branch regardless
    # of which process's resource it actually is — destroying the winner's
    # worktree, and any work already started in it, out from under it (a
    # blocker-severity PR #17 review finding). Gating on `created` (set only
    # once `git worktree add` itself has returned success) means the loser's
    # trap fires with `created` still 0 and does nothing: nothing to clean up
    # is exactly correct, since this process created nothing.
    #
    # The trap is still installed BEFORE `git worktree add` runs, not after —
    # every command in its body already no-ops safely (`2>/dev/null || true`)
    # when `created` is unset, so arming it early costs nothing and closes a
    # separate gap: a SIGINT/SIGTERM landing between worktree creation and
    # installing the trap would otherwise abort with no rollback at all (an
    # earlier PR #17 review finding). ERR too, so a synchronous failure
    # anywhere below is covered the same way.
    # The trap ends with an explicit `exit 1`, not just cleanup. For ERR,
    # `set -e` would exit afterward anyway — but INT/TERM don't work that
    # way: bash runs the trap and then resumes execution right where the
    # signal landed, unless the handler itself exits. Without this, a signal
    # arriving after `bootstrap` succeeds but before `trap - ERR INT TERM`
    # clears the trap would still fire the rollback (deleting the worktree,
    # marker, and branch), then fall through to printing `WORKSPACE=<the now
    # -deleted path>` and exiting 0 — reporting success for a claim that had
    # just been torn down (a PR #17 review finding).
    local created=0
    trap '(( created )) && {
              git -C "$main_root" worktree remove --force "$wt" 2>/dev/null || true
              git -C "$main_root" update-ref -d "refs/workspace-claimed/${branch}" 2>/dev/null || true
              git -C "$main_root" branch -D "$branch" 2>/dev/null || true
          }
          exit 1' ERR INT TERM
    mkdir -p "$(dirname "$wt")"
    # Branch from $base (origin/master when available), never the main checkout's
    # current HEAD — which stays on master, but this also keeps a second worktree
    # from ever branching off a sibling worktree's HEAD. `git worktree add` for a
    # fresh branch name is itself safe under concurrency (git serialises its own
    # worktree-administration writes), so many agents can call this at once for
    # distinct branches with no lock here — and for the *same* branch name, the
    # `created` gate above means the loser backs off cleanly instead of
    # clobbering the winner.
    git -C "$main_root" worktree add -q "$wt" -b "$branch" "$base"
    created=1
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
    # git's ref storage cannot have a branch that is both a leaf and a
    # path-prefix of another at the same time — 'area/task' and
    # 'area/task/subtask' can never coexist, with or without this tooling
    # (confirmed: plain `git branch area/task/subtask` fails identically once
    # `area/task` exists, no worktrees involved). `git worktree add -b`
    # already refuses this safely on its own — nothing destructive happens,
    # verified directly (PR #17 review) — but its raw error doesn't name the
    # conflicting branch. This does, so the failure is clear up front rather
    # than surfacing as a generic git ref-locking message.
    local prefix="$branch"
    while [[ "$prefix" == */* ]]; do
        prefix="${prefix%/*}"
        if git show-ref --verify --quiet "refs/heads/${prefix}"; then
            echo "branch '${branch}' conflicts with existing branch '${prefix}' (git cannot have one as a path-prefix of the other); pick a different name" >&2
            exit 2
        fi
    done
    local nested
    nested="$(git for-each-ref --format='%(refname:short)' "refs/heads/${branch}/*" | head -1)"
    if [[ -n "$nested" ]]; then
        echo "branch '${branch}' conflicts with existing branch '${nested}' (git cannot have one as a path-prefix of the other); pick a different name" >&2
        exit 2
    fi
    # A stale marker can only exist here if a branch of this name was deleted
    # outside this tooling (release-workspace.sh keeps the branch; a
    # successful prune-workspaces.sh deletes the marker before the branch —
    # see its header — so neither leaves one behind on its own; only a raw
    # `git branch -D` bypassing both does). Drop it before create_worktree
    # sets a fresh one for the branch actually being created here, so it can
    # never attach itself to unrelated new work by name alone (PR #17
    # review). This does not close the case where the *recreation* also
    # bypasses this tooling — a branch conjured by raw git commands to
    # deliberately match an old marker is outside what any check here can
    # distinguish from a real claim; treat manual branch deletion as always
    # pairable with `git update-ref -d refs/workspace-claimed/<branch>`, or
    # simply prefer release-workspace.sh / prune-workspaces.sh over raw git.
    git -C "$main_root" update-ref -d "refs/workspace-claimed/${branch}" 2>/dev/null || true
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
        #
        # If this call is the one newly setting the marker (the worktree
        # was not already tool-owned) and bootstrap then fails, roll the
        # marker back — a claim that never completed must not confer
        # ownership (a separate PR #17 review finding: a failed claim was
        # still leaving the worktree tagged as tool-owned). If the marker
        # was already there from a genuine prior claim, a transient failure
        # on this re-bootstrap must NOT strip that pre-existing ownership,
        # so the rollback only triggers for a marker this call itself set.
        was_already_tagged="$(git -C "$main_root" rev-parse --verify --quiet \
            "refs/workspace-claimed/${branch}" 2>/dev/null || true)"
        # Trap installed BEFORE update-ref, not after — same reasoning as
        # create_worktree's trap: a signal landing in the gap between setting
        # the marker and arming its rollback would otherwise leave it
        # untracked by the rollback entirely. Ends with an explicit `exit 1`
        # for the same reason as create_worktree's trap: INT/TERM don't exit
        # on their own after a trap runs, so without it a signal landing
        # after bootstrap succeeds but before `trap - ERR INT TERM` clears
        # this would roll the marker back and then still fall through to
        # printing WORKSPACE= and exiting 0 (a PR #17 review finding).
        if [[ -z "$was_already_tagged" ]]; then
            trap 'git -C "$main_root" update-ref -d "refs/workspace-claimed/${branch}" 2>/dev/null || true
                  exit 1' ERR INT TERM
        fi
        git -C "$main_root" update-ref "refs/workspace-claimed/${branch}" "refs/heads/${branch}"
        bootstrap "$toplevel"
        trap - ERR INT TERM
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
