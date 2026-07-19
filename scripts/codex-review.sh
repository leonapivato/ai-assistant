#!/usr/bin/env bash
# Run an adversarial review with Codex — a different model, for a perspective
# independent of the one that wrote the code.
#
# Uses the same rubric as documented in docs/review/, feeding it plus the branch
# diff to `codex exec`, read-only. `codex exec review --base` cannot take custom
# instructions on stdin, so we drive `codex exec` directly with an explicit diff.
#
# NOTE: this sends the diff and repository context to OpenAI. It is a deliberate
# pre-merge step, not something to run on every change.
#
# Usage: scripts/codex-review.sh <architecture|adversarial> [base-ref]
#   base-ref defaults to origin/main when known (else local main); the
#   review covers HEAD's *committed* changes vs base-ref — commit a fix (even
#   a small follow-up you'll squash later) before re-running, or the diff
#   Codex sees will not reflect it.
set -euo pipefail

persona="${1:-}"
base="${2:-}"

if [[ -z "$persona" ]]; then
    echo "usage: scripts/codex-review.sh <architecture|adversarial> [base-ref]" >&2
    exit 2
fi

if [[ -z "$base" ]]; then
    # Prefer origin/main, same as claim-workspace.sh's own base resolution
    # (see its header) — the local `main` branch ref is not kept current by
    # anything in this workflow (worktrees branch from origin/main, never
    # touching local main at all) and can sit stale indefinitely, silently
    # reviewing a different diff than CI's merge-relative one. This script
    # still does no network itself; run `git fetch origin` first for a fresh
    # origin/main, same as before claiming a workspace.
    base=main
    if git rev-parse --verify --quiet refs/remotes/origin/main >/dev/null 2>&1; then
        base=origin/main
    fi
fi

repo_root="$(git rev-parse --show-toplevel)"
rubric="${repo_root}/docs/review/${persona}.md"

if [[ ! -f "$rubric" ]]; then
    echo "unknown persona '${persona}': no ${rubric}" >&2
    exit 2
fi

if ! command -v codex >/dev/null 2>&1; then
    echo "codex CLI not found on PATH; install it to run reviews" >&2
    exit 127
fi

diff="$(git diff "${base}...HEAD")"
if [[ -z "$diff" ]]; then
    echo "no changes between ${base} and HEAD to review" >&2
    exit 0
fi

prompt="$(mktemp -t "codex-prompt-${persona}.XXXXXX.md")"
out="$(mktemp -t "codex-review-${persona}.XXXXXX.md")"
trap 'rm -f "$prompt"' EXIT

{
    cat "$rubric"
    echo
    echo "## Change under review"
    echo
    echo "Review ONLY the committed diff below (HEAD vs ${base}). You may read full"
    echo "files in the repo for context, but do not modify anything. Output exactly the"
    echo "ranked findings and verdict from docs/review/guide.md."
    echo
    echo '```diff'
    printf '%s\n' "$diff"
    echo '```'
} >"$prompt"

# Codex sandboxes the shell commands the model runs (file reads, git) with
# bubblewrap. In CI the runner is already an ephemeral, externally-sandboxed
# environment where bwrap cannot set up its network namespace
# ("bwrap: loopback: Failed RTM_NEWADDR"); that failure breaks every file read
# and degrades the review to an apology. There, skip Codex's own sandbox — the
# exact case --dangerously-bypass-approvals-and-sandbox documents. Locally the
# read-only sandbox works and is a real safety layer, so keep it. GITHUB_ACTIONS
# is "true" on the runner — matched exactly, so an inherited GITHUB_ACTIONS=false
# cannot silently disable the local sandbox; CODEX_REVIEW_NO_SANDBOX=1 forces the
# bypass either way. The prompt still instructs a read-only review regardless.
sandbox_args=(-s read-only)
if [[ "${CODEX_REVIEW_NO_SANDBOX:-}" == "1" || "${GITHUB_ACTIONS:-}" == "true" ]]; then
    sandbox_args=(--dangerously-bypass-approvals-and-sandbox)
fi

# Unset by default, so local runs keep using the Codex CLI's own default model.
# CI pins this (CODEX_REVIEW_MODEL in codex-review.yml) so the reviewer model is
# an explicit, deliberate choice there rather than whatever the pinned CLI
# version happens to default to.
model_args=()
if [[ -n "${CODEX_REVIEW_MODEL:-}" ]]; then
    model_args=(-m "$CODEX_REVIEW_MODEL")
fi

echo "Running Codex '${persona}' review of HEAD vs '${base}' (read-only)…" >&2
# -o captures just the final review; progress streams to stderr.
codex exec "${sandbox_args[@]}" "${model_args[@]}" -o "$out" - <"$prompt" >&2

echo >&2
echo "===== ${persona} review (HEAD vs ${base}) =====" >&2
cat "$out"
