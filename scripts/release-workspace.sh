#!/usr/bin/env bash
# Release a workspace claimed by scripts/claim-workspace.sh, once its PR merges
# (or is abandoned). Every claim is a linked worktree (the main checkout is
# never claimed — see claim-workspace.sh), so release always removes the
# worktree that git reports is actually checked out to <branch>, looked up
# from git rather than guessed from a slugged path, so two similar branch
# names cannot remove each other's worktree. Refuses on a dirty worktree
# unless FORCE=1, which *deliberately discards* the uncommitted work — "dirty"
# includes a valuable git-ignored file (.env, or anything else ignored that
# isn't a known-regenerable tooling artifact), which git's own `worktree
# remove` dirty-check cannot see on its own (see the check further down).
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
    # untracked-but-not-ignored files — but git-ignored files (.env, and any
    # other ignored path a user creates in a claimed workspace: .env.local,
    # .env.production, scratch notes, anything) are invisible to that check
    # entirely, edited or freshly created. A first version of this check only
    # covered the two specific paths claim-workspace.sh's bootstrap() seeds
    # (.env, .claude/settings.local.json), which review correctly flagged as
    # incomplete: the same blind spot applies to *any* ignored file, not just
    # those two (PR #17 review, blocker; the narrower version was itself
    # verified empirically before being generalised here).
    #
    # Every ignored path is inspected (`--ignored=matching`, not the default
    # `--ignored`, so a directory with its own nested .gitignore — e.g. this
    # project's .import_linter_cache/ — is reported file-by-file rather than
    # collapsed to one line, which the pattern matching below relies on).
    # Known-regenerable tooling artifacts (venvs, __pycache__, build output,
    # test/type-check caches — the categories this project's own .gitignore
    # itself groups together) are skipped: those get silently recreated by
    # `uv sync`/pytest/mypy/ruff on every worktree as a matter of routine
    # use, and flagging them would make FORCE=1 mandatory for every release,
    # defeating the point of asking at all. Everything else ignored is
    # treated as potentially valuable: blocked unless it is a file whose
    # content exactly matches the main checkout's copy (an unedited
    # bootstrap-seeded file, the common case).
    if (( ! force )); then
        diverged=()
        while IFS= read -r entry; do
            case "$entry" in
                .venv | .venv/* | venv | venv/* | \
                __pycache__ | __pycache__/* | */__pycache__ | */__pycache__/* | \
                .pytest_cache | .pytest_cache/* | .ruff_cache | .ruff_cache/* | \
                .mypy_cache | .mypy_cache/* | \
                .import_linter_cache | .import_linter_cache/* | \
                build | build/* | dist | dist/* | wheels | wheels/* | \
                htmlcov | htmlcov/* | *.egg-info | *.egg-info/* | \
                *.pyc | *.pyo | .coverage | .coverage.* | coverage.xml)
                    continue
                    ;;
            esac
            if [[ -f "${wt_path}/${entry}" && -f "${main_root}/${entry}" ]] \
                && cmp -s "${wt_path}/${entry}" "${main_root}/${entry}"; then
                continue
            fi
            diverged+=("$entry")
        done < <(git -C "$wt_path" status --porcelain --ignored=matching | sed -n 's/^!! //p')
        if (( ${#diverged[@]} > 0 )); then
            echo "Worktree has ignored file(s) git's dirty-check cannot see: ${diverged[*]}." >&2
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
