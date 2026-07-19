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
# Default is a dry-run report. FORCE=1 actually removes each MERGED/CLOSED
# candidate (worktree + local branch). A dirty worktree is always skipped,
# forced or not — this never discards uncommitted work. A branch with no PR,
# or an OPEN PR, is always kept.
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

printf '%-30s %-14s %s\n' "BRANCH" "VERDICT" "PATH"

git worktree list --porcelain | awk '/^worktree /{print substr($0, 10)}' |
while IFS= read -r path; do
    [[ "$path" == "$main_root" ]] && continue  # never a prune target

    branch="$(git -C "$path" branch --show-current)"

    if [[ -n "$(git -C "$path" status --porcelain)" ]]; then
        printf '%-30s %-14s %s\n' "$branch" "dirty-skip" "$path"
        continue
    fi

    state="$(gh pr list --head "$branch" --state all --json state --limit 1 \
        --jq '.[0].state' 2>/dev/null || true)"

    case "$state" in
        MERGED | CLOSED)
            verdict="PRUNE(${state,,})"
            printf '%-30s %-14s %s\n' "$branch" "$verdict" "$path"
            if (( force )); then
                git -C "$main_root" worktree remove "$path"
                git -C "$main_root" branch -D "$branch"
                echo "  removed." >&2
            fi
            ;;
        OPEN)
            printf '%-30s %-14s %s\n' "$branch" "keep" "$path"
            ;;
        *)
            printf '%-30s %-14s %s\n' "$branch" "no-pr" "$path"
            ;;
    esac
done

(( force )) || echo "Dry run — set FORCE=1 to actually remove PRUNE candidates above." >&2
