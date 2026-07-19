#!/usr/bin/env bash
# Claim several workspaces at once, one worktree per branch, running the claims
# concurrently. This is safe because claim-workspace.sh no longer serialises on
# a shared main-checkout lock (see its header): each branch gets its own `git
# worktree add`, and git's own worktree-administration locking makes
# concurrent adds for distinct branches safe with no coordination needed here.
#
# This does not make claiming linearly faster with N — each claim still runs
# `uv sync` (or WORKSPACE_BOOTSTRAP) in its own directory, and those may
# serialise on uv's own package-cache lock. It does mean N workspaces from one
# command instead of N sequential invocations, with per-branch errors reported
# instead of the whole batch aborting on the first failure.
#
# Usage: scripts/claim-workspaces.sh <area>/<slug> [<area>/<slug> ...]
# Exit:  0 if every branch claimed successfully, 1 if any failed (successful
#        claims are kept — one branch failing never rolls back its siblings).
set -uo pipefail

if [[ $# -eq 0 ]]; then
    echo "usage: scripts/claim-workspaces.sh <area>/<slug> [<area>/<slug> ...]" >&2
    exit 2
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

pids=()
branches=()
for branch in "$@"; do
    out="${tmp_dir}/${#pids[@]}.out"
    "$script_dir/claim-workspace.sh" "$branch" >"$out" 2>&1 &
    pids+=("$!")
    branches+=("$branch")
done

failed=0
for i in "${!pids[@]}"; do
    if wait "${pids[$i]}"; then
        grep '^WORKSPACE=' "${tmp_dir}/${i}.out"
    else
        failed=1
        echo "--- claim failed for '${branches[$i]}' ---" >&2
        cat "${tmp_dir}/${i}.out" >&2
    fi
done

exit "$failed"
