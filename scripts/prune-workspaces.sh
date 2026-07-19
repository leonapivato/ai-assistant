#!/usr/bin/env bash
# Find (and optionally remove) claimed branches whose PR has already merged or
# closed — the point at which a workspace has done its job. Iterates every
# local branch tagged with a `refs/workspace-claimed/<branch>` ref by
# claim-workspace.sh (see its header) — not just branches with a live
# worktree, and not "every non-master branch". Both restrictions matter:
#
# - Branches, not worktrees: release-workspace.sh deliberately keeps the
#   branch after removing the worktree, so a branch-name is only ever freed
#   here, once `gh` confirms its PR is actually done. Scanning worktrees alone
#   would make that unreachable — the documented "release after merge, then
#   prune" flow would leave every released branch permanently un-prunable,
#   since by the time you release, there is no worktree left to find it by.
# - Tagged branches, not "every non-master branch": a branch created some
#   other way (a plain `git branch`, never claimed here) could coincidentally
#   share a commit with some old closed PR of an unrelated name. Without an
#   explicit "this is ours" marker, FORCE=1 could force-delete a branch this
#   tooling never created and has no business touching.
#
# Verdict comes from the GitHub PR's actual state via `gh`, not from local git
# history: this project merges via "rebase and merge" (CONTRIBUTING), which
# rewrites commit hashes, so a merged branch's tip is never an ancestor of
# master's tip in the local ref graph even though its content landed —
# `git merge-base --is-ancestor` would misreport it as unmerged. Asking GitHub
# directly also avoids mistaking an unpushed, in-progress branch (no remote
# ref, no PR yet) for a merged one, which a "does the remote branch still
# exist" heuristic would get wrong.
#
# Whether the branch has an OPEN PR is checked as its own query
# (`--state open --limit 1`), separately from the MERGED/CLOSED match below —
# not folded into one `--state all` call with a fixed page size. A branch can
# have more than one PR over its lifetime (e.g. closed for process reasons,
# then reopened as a fresh PR at the same commit); a single paginated query
# risks an OPEN PR sorting behind enough MERGED/CLOSED ones to fall off the
# page, which a fixed `--limit` could never fully rule out. An *existence*
# check does not have that problem: "at least one OPEN PR" needs at most one
# result to prove, so `--limit 1` there is exhaustive, not a cap. If any PR is
# OPEN, the branch is always kept, full stop — never pruned no matter what
# else is in its history. Only once that check comes back empty does a
# MERGED/CLOSED match get considered (a `--limit` there is no longer
# safety-critical — see below), and even then only if the branch's tip commit
# is *exactly* that PR's recorded head commit (`headRefOid`) — never on
# branch-name match alone, since a freed name is reusable and a later,
# unrelated claim of the same name must never be mistaken for the old PR.
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
# (worktree, if one still exists, plus the local branch always). A dirty
# worktree is always skipped, forced or not — this never discards uncommitted
# work. A branch with no worktree has nothing to lose, so it is never skipped
# for dirtiness — only for its PR/HEAD verdict, same as any other branch.
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

# Map branch -> worktree path, for the branches that currently have one.
declare -A wt_for_branch
current=""
while IFS= read -r line; do
    case "$line" in
        "worktree "*) current="${line#worktree }" ;;
        "branch refs/heads/"*) wt_for_branch["${line#branch refs/heads/}"]="$current" ;;
    esac
done < <(git worktree list --porcelain)

printf '%-30s %-14s %s\n' "BRANCH" "VERDICT" "PATH"

# Process substitution (not `| while`), so the loop runs in *this* shell, not
# a subshell — `had_error` set inside it must survive to the `exit` below.
while IFS= read -r branch; do
    [[ "$branch" == "master" ]] && continue  # never a prune target

    if ! git -C "$main_root" rev-parse --verify --quiet \
        "refs/workspace-claimed/${branch}" >/dev/null; then
        continue  # not ours — never listed, never touched
    fi

    path="${wt_for_branch[$branch]:-}"
    if [[ -n "$path" ]]; then
        if [[ -n "$(git -C "$path" status --porcelain)" ]]; then
            printf '%-30s %-14s %s\n' "$branch" "dirty-skip" "$path"
            continue
        fi
    else
        path="(released — branch only, no worktree)"
    fi

    # Existence check: does ANY PR for this branch have state OPEN? `--limit
    # 1` is exhaustive here, not a cap — one match is all that is needed to
    # prove "at least one exists". A non-zero exit is a genuine `gh` failure,
    # not "no open PR" — caught by `if !` so `set -e` does not abort the run
    # over one branch's lookup failing.
    if ! open_count="$(gh pr list --head "$branch" --state open --limit 1 \
        --json state --jq 'length' 2>/dev/null)"; then
        printf '%-30s %-14s %s\n' "$branch" "lookup-error" "$path"
        had_error=1
        continue
    fi

    if [[ "$open_count" != "0" ]]; then
        # An OPEN PR wins outright, regardless of what else is in the
        # branch's history — never prune something under active review.
        printf '%-30s %-14s %s\n' "$branch" "keep" "$path"
        continue
    fi

    # No OPEN PR exists (just established, exhaustively). Look for a
    # MERGED/CLOSED match to prune. `--limit 100` is not safety-critical the
    # way the check above is: at worst, an unmatched older PR past the page
    # just means a real prune candidate is conservatively reported as
    # `head-changed` instead of PRUNE — never the reverse.
    if ! resp="$(gh pr list --head "$branch" --state all --limit 100 \
        --json state,headRefOid \
        --jq '.[] | select(.state != "OPEN") | .state + "\t" + .headRefOid' 2>/dev/null)"; then
        printf '%-30s %-14s %s\n' "$branch" "lookup-error" "$path"
        had_error=1
        continue
    fi

    if [[ -z "$resp" ]]; then
        printf '%-30s %-14s %s\n' "$branch" "no-pr" "$path"
        continue
    fi

    local_head="$(git -C "$main_root" rev-parse "refs/heads/${branch}")"
    prune_state=""
    while IFS=$'\t' read -r pr_state pr_head_sha; do
        [[ "$pr_head_sha" == "$local_head" ]] && prune_state="$pr_state"
    done <<<"$resp"

    if [[ -n "$prune_state" ]]; then
        verdict="PRUNE(${prune_state,,})"
        printf '%-30s %-14s %s\n' "$branch" "$verdict" "$path"
        if (( force )); then
            # Order matters here, for two separate failure modes:
            #
            # worktree removal happens FIRST, before the marker is touched.
            # `git worktree remove` can fail on a clean worktree for reasons
            # unrelated to dirtiness (e.g. `git worktree lock`) — under `set
            # -e` that aborts the script immediately, so if the marker had
            # already been deleted at that point, this branch would come out
            # of a failed prune *unmarked but otherwise untouched*: still
            # claimed in every way that matters, but now invisible to both
            # this script's next run and release-workspace.sh (PR #17 review
            # finding). Trying worktree removal first means a failure there
            # aborts before anything is deleted at all — branch, worktree, and
            # marker all remain exactly as they were, a clean state to retry.
            #
            # The marker is deleted BEFORE `branch -D`, not after. If this
            # process is killed between the two, every remaining ordering is a
            # *safe* leak — a leftover branch this tooling will no longer
            # touch (no marker, so both claim's idempotent path and prune
            # itself skip it) — never a *dangerous* one. Deleting the branch
            # before the marker would risk the opposite: kill the process
            # between the two, and a manually recreated branch of the same
            # name later would inherit the stale marker and be silently
            # treated as tool-owned, with no relationship to the PR that
            # marker was originally about (an earlier PR #17 review finding).
            if [[ -n "${wt_for_branch[$branch]:-}" ]]; then
                git -C "$main_root" worktree remove "${wt_for_branch[$branch]}"
            fi
            git -C "$main_root" update-ref -d "refs/workspace-claimed/${branch}"
            git -C "$main_root" branch -D "$branch"
            echo "  removed." >&2
        fi
    else
        # Only CLOSED/MERGED entries exist, but none match this branch's
        # current tip (name reuse, or new commits since the recorded PR) —
        # never a prune target from name alone.
        printf '%-30s %-14s %s\n' "$branch" "head-changed" "$path"
    fi
done < <(git for-each-ref --format='%(refname:short)' refs/heads/)

(( force )) || echo "Dry run — set FORCE=1 to actually remove PRUNE candidates above." >&2
exit "$had_error"
