#!/usr/bin/env bash
# Run an adversarial review with Codex — a different model, for a perspective
# independent of the one that wrote the code.
#
# Uses the same rubric as the in-session Claude reviewers (docs/review/<persona>.md),
# so only the model differs. Runs read-only: Codex may not modify the repo.
#
# NOTE: this sends the diff and repository context to OpenAI. It is a deliberate
# pre-merge step, not something to run on every change.
#
# Usage: scripts/codex-review.sh <architecture|adversarial> [base-branch]
#   base-branch defaults to "main".
set -euo pipefail

persona="${1:-}"
base="${2:-main}"

if [[ -z "$persona" ]]; then
    echo "usage: scripts/codex-review.sh <architecture|adversarial> [base-branch]" >&2
    exit 2
fi

repo_root="$(git rev-parse --show-toplevel)"
rubric="${repo_root}/docs/review/${persona}.md"

if [[ ! -f "$rubric" ]]; then
    echo "unknown persona '${persona}': no ${rubric}" >&2
    exit 2
fi

if ! command -v codex >/dev/null 2>&1; then
    echo "codex CLI not found on PATH; install it or run the in-session Claude reviewers instead" >&2
    exit 127
fi

out="$(mktemp -t "codex-review-${persona}.XXXXXX.md")"

echo "Running Codex '${persona}' review against '${base}' (read-only)…" >&2
# `codex exec review` diffs against --base and takes custom instructions on
# stdin; -s read-only forbids any repo mutation. -o captures just the final
# review (progress is streamed to stderr), which we then print cleanly.
codex exec -s read-only -o "$out" review --base "$base" - < "$rubric" >&2

echo >&2
echo "===== ${persona} review (${base}) =====" >&2
cat "$out"
