#!/usr/bin/env bash
# Find (and optionally remove) workspaces whose PR has already merged or
# closed — the point at which a claimed worktree has done its job and is just
# taking up disk. Verdict comes from the GitHub PR's actual state via `gh`,
# not from local git history: this project merges via "rebase and merge"
# (CONTRIBUTING), which rewrites commit hashes, so a merged branch's tip is
# never an ancestor of master's tip in the local ref graph even though its
# content landed — `git merge-base --is-ancestor` would misreport it as
# unmerged. Asking GitHub directly also avoids mistaking an unpushed,
# in-progress branch (no remote ref, no PR yet) for a merged one, which a
# "does the remote branch still exist" heuristic would get wrong.
#
# A MERGED/CLOSED PR is only trusted as a prune signal if the worktree's HEAD
# commit is *exactly* that PR's recorded head commit (`headRefOid`) — never on
# branch-name match alone. Branch names are reused (claim-workspace.sh's
# `require_new_branch` only blocks reuse while a branch still exists locally;
# once its old PR is pruned, git branch -D frees the name). Matching by name
# alone would let a brand-new, unrelated, still-in-progress claim that happens
# to reuse an old merged PR's branch name get force-deleted — including any
# unpushed commits — the moment someone runs this with FORCE=1. An exact HEAD
# match makes that impossible: any local commit made since the claim (the
# normal case for real work) moves HEAD away from the old PR's snapshot, so it
# reports `head-changed` instead of a prune candidate.
#
# `gh` failures (auth, network, rate limit, malformed response) are reported
# as `lookup-error`, distinct from a genuine `no-pr` (the call succeeded and
# found nothing) — silently folding the two together would let a transient
# `gh` failure masquerade as "definitely nothing to prune here" instead of
# "unknown, go check". A lookup-error is never a prune candidate, and the
# script exits non-zero if any occurred so a caller notices coverage was
# incomplete.
#
# Default is a dry-run report. FORCE=1 actually removes each PRUNE candidate
# (worktree + local branch). A dirty worktree is always skipped, forced or
# not — this never discards uncommitted work.
#
# Requires the `gh` CLI, authenticated against this repo. Unlike
# claim-workspace.sh, this DOES touch the network — it needs fresh PR state,
# and it is an occasional, explicitly user-invoked cleanup step, not part of
# the hot claim path.
#
# Usage: scripts/prune-workspaces.sh   (FORCE=1 to actually remove)
set -euo pipefail

if ! command -v gh >/dev/null 2>&1; then
    echo "gh CLI not found; cannot determine PR state, so nothing can be pruned safely." >&2
    exit 1
fi

force=0
[[ "${FORCE:-}" == "1" ]] && force=1

main_root="$(git worktree list --porcelain | sed -n 's/^worktree //p' | head -1)"
had_error=0

printf '%-30s %-14s %s\n' "BRANCH" "VERDICT" "PATH"

# Process substitution (not `| while`), so the loop runs in *this* shell, not
# a subshell — `had_error` set inside it must survive to the `exit` below.
while IFS= read -r path; do
    [[ "$path" == "$main_root" ]] && continue  # never a prune target

    branch="$(git -C "$path" branch --show-current)"

    if [[ -n "$(git -C "$path" status --porcelain)" ]]; then
        printf '%-30s %-14s %s\n' "$branch" "dirty-skip" "$path"
        continue
    fi

    # One call returns both the PR's state and its head commit, tab-separated;
    # `// ""` guards the no-match case ([0] is null) so the jq concat never
    # errors. A non-zero exit here is a genuine `gh` failure, not "no PR" —
    # caught by the `if !` so `set -e` does not abort the whole run over one
    # branch's lookup failing.
    if ! resp="$(gh pr list --head "$branch" --state all --limit 1 \
        --json state,headRefOid \
        --jq '(.[0].state // "") + "\t" + (.[0].headRefOid // "")' 2>/dev/null)"; then
        printf '%-30s %-14s %s\n' "$branch" "lookup-error" "$path"
        had_error=1
        continue
    fi
    IFS=$'\t' read -r pr_state pr_head_sha <<<"$resp"

    case "$pr_state" in
        MERGED | CLOSED)
            local_head="$(git -C "$path" rev-parse HEAD)"
            if [[ -n "$pr_head_sha" && "$local_head" == "$pr_head_sha" ]]; then
                verdict="PRUNE(${pr_state,,})"
                printf '%-30s %-14s %s\n' "$branch" "$verdict" "$path"
                if (( force )); then
                    git -C "$main_root" worktree remove "$path"
                    git -C "$main_root" branch -D "$branch"
                    echo "  removed." >&2
                fi
            else
                # Branch name matches an old PR, but this worktree has moved on
                # (new commits since claim, or since that PR's tip) — never a
                # prune target from name alone.
                printf '%-30s %-14s %s\n' "$branch" "head-changed" "$path"
            fi
            ;;
        OPEN)
            printf '%-30s %-14s %s\n' "$branch" "keep" "$path"
            ;;
        *)
            printf '%-30s %-14s %s\n' "$branch" "no-pr" "$path"
            ;;
    esac
done < <(git worktree list --porcelain | awk '/^worktree /{print substr($0, 10)}')

(( force )) || echo "Dry run — set FORCE=1 to actually remove PRUNE candidates above." >&2
exit "$had_error"
