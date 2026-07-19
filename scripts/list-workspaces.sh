#!/usr/bin/env bash
# List active workspaces: every worktree claimed via claim-workspace.sh, plus
# the main checkout (always on master, integration-only — never claimed, see
# claim-workspace.sh). Shows branch, working-tree state, and how long ago the
# last commit landed, so tracking several parallel claims doesn't mean piecing
# it together from raw `git worktree list --porcelain` by hand.
#
# Branch names come entirely from the porcelain listing itself (not `git -C
# "$path" branch --show-current`), and `status`/`log` are only run when the
# worktree's directory still exists on disk. A worktree whose directory was
# manually deleted but whose administrative metadata git still tracks (`git
# worktree list` marks it "prunable") would otherwise make a bare `git -C
# "$path" ...` assignment fail under `set -e` and abort the whole listing
# before later entries are ever reached (PR #17 review finding) — reported
# here as `missing` instead, and every other entry still gets listed.
#
# Usage: scripts/list-workspaces.sh
set -euo pipefail

main_root="$(git worktree list --porcelain | sed -n 's/^worktree //p' | head -1)"

printf '%-30s %-7s %-15s %s\n' "BRANCH" "STATE" "LAST COMMIT" "PATH"

path=""
branch=""

print_row() {
    [[ -z "$path" ]] && return
    local label="${branch:-(detached)}"
    [[ "$path" == "$main_root" ]] && label="${label} (main, integration-only)"

    if [[ ! -d "$path" ]]; then
        printf '%-30s %-7s %-15s %s\n' "$label" "missing" "-" "${path} (worktree dir gone)"
        return
    fi

    local state last
    if [[ -n "$(git -C "$path" status --porcelain)" ]]; then
        state="dirty"
    else
        state="clean"
    fi
    last="$(git -C "$path" log -1 --format=%cr 2>/dev/null || echo "no commits")"
    printf '%-30s %-7s %-15s %s\n' "$label" "$state" "$last" "$path"
}

while IFS= read -r line; do
    case "$line" in
        "worktree "*)
            print_row
            path="${line#worktree }"
            branch=""
            ;;
        "branch refs/heads/"*)
            branch="${line#branch refs/heads/}"
            ;;
    esac
done < <(git worktree list --porcelain)
print_row
