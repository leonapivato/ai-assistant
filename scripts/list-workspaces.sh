#!/usr/bin/env bash
# List active workspaces: every worktree claimed via claim-workspace.sh, plus
# the main checkout (always on master, integration-only — never claimed, see
# claim-workspace.sh). Shows branch, working-tree state, and how long ago the
# last commit landed, so tracking several parallel claims doesn't mean piecing
# it together from raw `git worktree list --porcelain` by hand.
#
# Usage: scripts/list-workspaces.sh
set -euo pipefail

main_root="$(git worktree list --porcelain | sed -n 's/^worktree //p' | head -1)"

printf '%-30s %-7s %-15s %s\n' "BRANCH" "STATE" "LAST COMMIT" "PATH"

git worktree list --porcelain | awk '/^worktree /{print substr($0, 10)}' |
while IFS= read -r path; do
    branch="$(git -C "$path" branch --show-current)"
    [[ -z "$branch" ]] && branch="(detached)"
    [[ "$path" == "$main_root" ]] && branch="${branch} (main, integration-only)"

    if [[ -n "$(git -C "$path" status --porcelain)" ]]; then
        state="dirty"
    else
        state="clean"
    fi
    last="$(git -C "$path" log -1 --format=%cr 2>/dev/null || echo "no commits")"

    printf '%-30s %-7s %-15s %s\n' "$branch" "$state" "$last" "$path"
done
