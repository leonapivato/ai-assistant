#!/usr/bin/env bash
# Release a workspace claimed by scripts/claim-workspace.sh, once its PR merges
# (or is abandoned). Every claim is a linked worktree (the main checkout is
# never claimed — see claim-workspace.sh), so release always removes the
# worktree that git reports is actually checked out to <branch>, looked up
# from git rather than guessed from a slugged path, so two similar branch
# names cannot remove each other's worktree. Refuses on a dirty worktree
# unless FORCE=1, which *deliberately discards* the uncommitted work — "dirty"
# includes a locally-edited copy of a git-ignored seeded file (.env,
# .claude/settings.local.json), which git's own `worktree remove` dirty-check
# cannot see on its own (see the check further down).
#
# Only ever touches a branch carrying the `refs/workspace-claimed/<branch>`
# marker claim-workspace.sh sets (see its header) — a worktree for some other,
# unclaimed branch (created directly with `git worktree add`, never through
# this tooling) is refused, not removed, even with FORCE=1. `master` is
# refused outright: it is the permanent main-checkout branch, never a claimed
# workspace, so it is rejected before even looking for a worktree to match.
#
# Usage: scripts/release-workspace.sh <area>/<slug>
#   FORCE=1  discard uncommitted changes (any other value, or unset, does not).
set -euo pipefail

branch="${1:-}"
if [[ -z "$branch" ]]; then
    echo "usage: scripts/release-workspace.sh <area>/<slug>" >&2
    exit 2
fi
if [[ "$branch" == "master" ]]; then
    echo "refusing to release 'master' — it is the permanent main checkout, never a claimed workspace." >&2
    exit 2
fi
force=0
[[ "${FORCE:-}" == "1" ]] && force=1

main_root="$(git worktree list --porcelain | sed -n 's/^worktree //p' | head -1)"

# Deliberately does NOT delete the local branch — only the worktree. That
# leaves the branch name permanently claimed (claim-workspace.sh's
# require_new_branch refuses to reuse it), which is intentional: it is what
# lets prune-workspaces.sh trust a branch-name-to-PR match at all. If release
# freed the name for reuse, a brand-new claim could reuse an old, merged PR's
# branch name before that PR's branch is pruned, and prune-workspaces.sh's
# `gh pr list --head <branch>` would find the *old* PR under the *new* claim.
# (It still cannot be force-deleted in that case — prune-workspaces.sh guards
# on an exact HEAD match, not name alone — but avoiding the ambiguity here is
# simpler than relying on that second guard to catch it.) Branch names freed
# by prune-workspaces.sh (after it confirms via `gh` the PR actually merged or
# closed) are the only ones safe to reuse.

# Path of the worktree actually checked out to this branch — asked of git, so it
# is collision-free regardless of how the branch name slugs to a directory.
#
# `awk -v` processes backslash escapes in its value (POSIX-mandated, not a
# gawk quirk), which could in principle corrupt `ref` for a branch name
# containing a literal backslash (a PR #17 review finding). Verified this is
# not reachable: `git check-ref-format` rejects any ref name containing a
# backslash outright (confirmed empirically — every position tried), and
# claim-workspace.sh already runs that same check before a branch is ever
# created, so no branch this tooling could have claimed can reach this line
# with one.
wt_path="$(git worktree list --porcelain | awk -v ref="refs/heads/${branch}" '
    /^worktree /{path = substr($0, 10)}
    /^branch /{if ($2 == ref) print path}')"

if [[ -n "$wt_path" ]]; then
    if ! git -C "$main_root" rev-parse --verify --quiet \
        "refs/workspace-claimed/${branch}" >/dev/null; then
        echo "'${branch}' was not claimed by this tooling (no refs/workspace-claimed/${branch} marker) — refusing to remove its worktree." >&2
        exit 1
    fi

    # `git worktree remove` (no --force) refuses on tracked changes or
    # untracked-but-not-ignored files — but .env / .claude/settings.local.json
    # (the same paths claim-workspace.sh's bootstrap() seeds from the main
    # checkout; keep this list in sync with that function) are git-ignored,
    # so git's own dirty-check cannot see them at all, edited or not: a
    # locally-edited .env (e.g. real secrets set up for this workspace) is
    # invisible to it and gets silently deleted along with everything else
    # (verified empirically; PR #17 review, blocker). Checked here instead:
    # refuse, without FORCE, if a seeded file's content has diverged from the
    # main checkout's copy it started from — an unedited copy is expected and
    # safe to discard; a diverged one is exactly what FORCE exists to gate.
    if (( ! force )); then
        diverged=()
        for rel in .env .claude/settings.local.json; do
            if [[ -f "${wt_path}/${rel}" ]]; then
                if [[ ! -f "${main_root}/${rel}" ]] || ! cmp -s "${wt_path}/${rel}" "${main_root}/${rel}"; then
                    diverged+=("$rel")
                fi
            fi
        done
        if (( ${#diverged[@]} > 0 )); then
            echo "Worktree has modified git-ignored file(s) git cannot see as dirty: ${diverged[*]}." >&2
            echo "Removing would silently discard them. Set FORCE=1 to discard anyway." >&2
            exit 1
        fi
    fi

    if (( force )); then
        git -C "$main_root" worktree remove --force "$wt_path"
    else
        git -C "$main_root" worktree remove "$wt_path"
    fi
    echo "Removed the worktree for '${branch}' (${wt_path})." >&2
else
    echo "No workspace found for '${branch}' (already released?)." >&2
fi
