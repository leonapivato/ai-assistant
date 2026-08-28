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
#
#        scripts/codex-review.sh --start <persona> [base-ref]
#        scripts/codex-review.sh --wait  <persona> [base-ref] [--timeout N]
#   The same round, launched detached and then polled in bounded calls, for a
#   caller that cannot hold one process open for the minutes a round takes
#   (issue #1594). `--start` runs the round below in a detached copy of THIS
#   script — same locks, same artifact, same acceptance — and returns as soon as
#   that round has claimed its loop; `--wait` blocks on the in-flight lock for
#   HEAD's tree and then reports the artifact and its verdict. Neither changes
#   what a round is or what it records: the foreground form is the round, and
#   these two are how it is started and observed.
set -euo pipefail

# --- Modes (issue #1594) -----------------------------------------------------
#
# The mode is a leading flag rather than a subcommand word, so the positional
# grammar every existing caller uses — `<persona> [base-ref]`, and an EMPTY
# second positional standing for "resolve the base yourself", which the
# `review-codex` recipe passes literally — keeps its exact meaning in all three
# modes. A subcommand word would have made `codex-review.sh adversarial` and
# `codex-review.sh run adversarial` two grammars to keep in step.
mode=run
timeout_arg=""
positional=()
while [[ $# -gt 0 ]]; do
    case "$1" in
    --start | --wait)
        if [[ "$mode" != "run" ]]; then
            echo "scripts/codex-review.sh: --start and --wait are alternatives;" \
                "pass at most one" >&2
            exit 2
        fi
        mode="${1#--}"
        shift
        ;;
    --timeout)
        if [[ $# -lt 2 ]]; then
            echo "scripts/codex-review.sh: --timeout needs a value in seconds" >&2
            exit 2
        fi
        timeout_arg="$2"
        shift 2
        ;;
    --timeout=*)
        timeout_arg="${1#--timeout=}"
        shift
        ;;
    --)
        shift
        while [[ $# -gt 0 ]]; do
            positional+=("$1")
            shift
        done
        ;;
    -*)
        echo "scripts/codex-review.sh: unknown option '$1'" >&2
        exit 2
        ;;
    *)
        positional+=("$1")
        shift
        ;;
    esac
done

_usage() {
    echo "usage: scripts/codex-review.sh <architecture|adversarial> [base-ref]" >&2
    echo "       scripts/codex-review.sh --start <persona> [base-ref]" >&2
    echo "       scripts/codex-review.sh --wait <persona> [base-ref] [--timeout N]" >&2
}

persona="${positional[0]:-}"
base="${positional[1]:-}"

if [[ -z "$persona" || ${#positional[@]} -gt 2 ]]; then
    _usage
    exit 2
fi

if [[ -n "$timeout_arg" && "$mode" != "wait" ]]; then
    echo "scripts/codex-review.sh: --timeout applies to --wait only" >&2
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

# `--wait` reads `.review/` and a lock file and calls nothing; requiring the CLI
# it never invokes would make the one mode whose job is to REPORT on a round fail
# on a host that cannot start one — including the case where the round it is
# reporting on was started elsewhere.
if [[ "$mode" != "wait" ]] && ! command -v codex >/dev/null 2>&1; then
    echo "codex CLI not found on PATH; install it to run reviews" >&2
    exit 127
fi

# Codex reads files from the working tree for context, not just the diff we hand
# it. Reviewing with uncommitted changes present therefore reasons about a tree
# that is not the commit the artifact will name — and once those changes are
# stashed, ship.sh still accepts it. Same rule as ship: clean tree or nothing.
#
# `status --porcelain` does not report *ignored* files, and deliberately so.
# Codex can read an ignored file, so in principle one could influence a review
# and then vanish. Closing that would mean refusing to run whenever any ignored
# file exists — which is always: .venv/, .env, and every tool cache are ignored
# by design. There is no reliable way to tell "an ignored fixture that swayed
# the review" from "the virtualenv", so the check would either never pass or
# depend on a hand-maintained exemption list that silently rots. Waived
# deliberately; the tracked+untracked check is what is enforceable here.
#
# `--wait` WARNS where the other two modes refuse, because its answer is about a
# round that is already running and its inputs are HEAD's tree and a lock file,
# neither of which a dirty working tree changes. Refusing there would withhold
# the diagnosis in the one case it is most wanted — a round in flight while the
# tree has drifted under it — and that round is going to refuse to record itself
# anyway (the settled-tree check at the end of a round), which is precisely what
# the operator needs to be told rather than shielded from.
_dirty="$(git status --porcelain)"
if [[ "$mode" == "wait" ]]; then
    if [[ -n "$_dirty" ]]; then
        echo "warning: the working tree is dirty (tracked or untracked), so HEAD's" >&2
        echo "  tree is not what is on disk, and a round in flight will refuse to" >&2
        echo "  record itself when it finishes. Reporting on HEAD's tree anyway." >&2
    fi
elif [[ -n "$_dirty" ]]; then
    echo "working tree is dirty (tracked or untracked); commit or stash first" >&2
    echo "the review would reason about files that are not in the reviewed commit" >&2
    exit 1
fi

# Resolve HEAD to an immutable SHA *before* diffing, and review that SHA rather
# than the moving ref. A review can run for minutes; if HEAD advances meanwhile,
# re-resolving afterwards would file this diff under a commit Codex never saw,
# and ship.sh would accept it as evidence for that commit. Pinning here means
# the artifact always names exactly the code that was reviewed.
sha="$(git rev-parse HEAD)"

# Pin the *base* for the same reason, and at the same time. `base` is a ref
# ("origin/main"), and a concurrent fetch can move it mid-review: the diff would
# be computed from the old merge base while the recorded one is re-resolved
# afterwards to the new commit — an artifact certifying a range Codex never saw,
# which ship.sh would then accept. Both edges of the reviewed range are immutable
# from here on.
base_sha="$(git merge-base "$base" "$sha")"

# --- A ratification flip is reviewed as its parent (ADR-0165 §3) -------------
#
# `ship` does not compare an artifact against HEAD when HEAD is a ratification
# flip. ADR-0165 §3 is normative that "ADR-0027 §2's acceptance loop is evaluated
# against `HEAD`'s parent — its tree and its patch identity — and paths (a) and
# (b) then run exactly as written". A round run on such a HEAD therefore has to
# record the PARENT's content, or it records evidence the rule is required to
# look past: the paid round covers strictly more than `ship` asks for, and `ship`
# refuses it all the same (issue #1672, PR #1660).
#
# That order is reachable rather than exotic. `just adr-ratify` runs before
# `ship`, so HEAD is already the flip when the base moves; any `docs/adr/**`
# merge landing on the base breaches ADR-0027 §3's floor and genuinely owes a
# round; and every ADR lane that is not first in its merge order meets both.
#
# So the RECOGNISER's re-anchoring is mirrored here in the PRODUCER, by calling
# the same `scripts/adr_ratify.py check-shape` that `ship` calls — one
# implementation of the shape, for the reason ship.sh gives at length. What moves
# is exactly what `ship` compares: the reviewed range's right edge, the recorded
# tree and the recorded patch identity. `sha` does NOT move. It stays HEAD,
# because it is what the settled-checkout guard re-reads when the round finishes
# and what `ship` ranks a matching artifact by.
#
# Nothing is relaxed and no acceptance path is added. The single line the
# reviewer no longer sees is the line ADR-0165 §2 defines as carrying no
# reviewable content; the decision text it ratifies is in the range either way.
# The alternative — teaching `ship` to accept an artifact recorded against HEAD's
# own tree as well — would be the "third acceptance path" ADR-0165 §3 says this
# is not, and it is not this script's to grant.
#
# Fails CLOSED in every direction, exactly as ship.sh's copy does: no python, a
# missing script or a non-zero exit leaves `content_sha` at `$sha`, which is the
# behaviour that predates this block.
content_sha="$sha"
ratify_adr=""
_ratify_python="$(command -v python3 || command -v python || true)"
if [[ -n "$_ratify_python" && -f "${repo_root}/scripts/adr_ratify.py" ]]; then
    ratify_adr="$("$_ratify_python" "${repo_root}/scripts/adr_ratify.py" \
        check-shape "$sha" 2>/dev/null || true)"
fi
if [[ -n "$ratify_adr" ]]; then
    content_sha="$(git rev-parse "${sha}^")"
    echo "HEAD ${sha:0:12} is the one-line ratification flip of ${ratify_adr};" >&2
    echo "  reviewing and recording its parent ${content_sha:0:12}, which is the" >&2
    echo "  content 'just ship' judges coverage over (ADR-0165 §3)." >&2
fi

# The tree is the anchor ship.sh checks (ADR-0020 §3): it identifies the content
# reviewed, where the SHA identifies only the commit that happened to carry it.
# Pinned here with the other two edges, and for the same reason — everything the
# artifact certifies is resolved before the review starts, never after it. Taken
# from `content_sha`, so it is the tree of what was actually reviewed on a
# ratification flip as much as anywhere else.
tree="$(git rev-parse "${content_sha}^{tree}")"

# The branch is what scopes the round count below to *this* review loop, and it
# is recorded in the artifact for that reason. Unlike the SHA or the base, it
# survives a squash, an amend and a rebase — which is exactly the property the
# count needs (issue #97).
branch="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$branch" == "HEAD" ]]; then
    # Detached: "HEAD" is a placeholder, not an identity, so using it as the
    # scope key would make every detached checkout share one review loop and
    # contaminate the others' counts. Key on the commit instead — each detached
    # review is then its own loop, starting at round 1. Nothing is lost: such a
    # review cannot be shipped at all, since ship refuses a detached HEAD.
    branch="detached-${sha}"
fi

# --- Where this loop's state lives -------------------------------------------
#
# Hoisted above the mode dispatch below so `--start` and `--wait` resolve the
# loop's paths from the same four inputs a round does — the branch, the pinned
# base, the persona and the tree — rather than re-deriving them. A second
# spelling of the loop key is the failure this avoids: it would not fail loudly,
# it would wait on a lock no round holds and report "no round in flight" while
# one runs, which is the very confusion issue #1594 is about.
review_dir="${repo_root}/.review"
codex_home="${CODEX_HOME:-$HOME/.codex}"
session_dir="${review_dir}/session"
disposition_dir="${review_dir}/dispositions"
branch_key="$(printf '%s' "$branch" | sha1sum | awk '{print $1}')"
base_key="$(printf '%s' "$base_sha" | sha1sum | awk '{print $1}')"
loop_key="${branch_key}-${base_key}"
meta_file="${session_dir}/${loop_key}.meta"
thread_file="${session_dir}/${loop_key}.${persona}.thread"
lock_file="${session_dir}/${loop_key}.lock"
inflight_file="${session_dir}/${loop_key}.${persona}.inflight"

# The in-flight lock is keyed by (loop, persona) and says only THAT a round of
# this persona is running — never WHICH CONTENT it is reviewing, because the tree
# is not in its key and cannot be: the lock is claimed before the round has done
# anything, and one branch reviews many trees under one key. `--wait` is asked
# about a tree, so the running round publishes the one it pinned. `round_file` is
# that marker, and `log_file` is where a detached round's output goes. Both sit
# beside the lock under `.review/`, which is already git-ignored.
round_file="${session_dir}/${loop_key}.${persona}.round"
log_file="${session_dir}/${loop_key}.${persona}.log"
start_lock_file="${session_dir}/${loop_key}.${persona}.start"

# An opaque random id. Mints the durable per-loop identity below (ADR-0025 §4)
# and the per-attempt token `--start` uses to recognise its own child.
_mint_id() {
    if [[ -r /proc/sys/kernel/random/uuid ]]; then
        cat /proc/sys/kernel/random/uuid
    else
        od -An -N16 -tx1 /dev/urandom | tr -d ' \n'
    fi
}

# The bypass path (no sandbox, or CI) keeps no Codex session (see the invocation
# far below). Resolved here rather than there because all three modes need it:
# `--start` and `--wait` both reason about the in-flight lock, which the bypass
# path does not take. GITHUB_ACTIONS is matched exactly against "true", so an
# inherited GITHUB_ACTIONS=false cannot enable it; CODEX_REVIEW_NO_SANDBOX=1
# forces it.
bypass=0
if [[ "${CODEX_REVIEW_NO_SANDBOX:-}" == "1" || "${GITHUB_ACTIONS:-}" == "true" ]]; then
    bypass=1
fi

# Whether the loop phases can be serialized at all. `flock` is util-linux, so it
# is present wherever `sha1sum` (already required above, for the loop key) is.
# Where it is somehow absent, the loop degrades to the unserialized behaviour it
# had before #142 and says so, rather than refusing to review: the race needs two
# concurrent invocations, which the one-agent-per-clone workflow (ADR-0015) does
# not produce, so bricking the tool would be the worse failure.
serialized=1
if ! command -v flock >/dev/null 2>&1; then
    serialized=0
    if [[ "$bypass" -eq 0 && "$mode" != "wait" ]]; then
        echo "warning: flock not found; the review loop's init/update cannot be" >&2
        echo "  serialized. Run one codex-review at a time (issue #142)." >&2
    fi
fi

# One field of a recorded provenance LINE (the artifact's first line). The
# greedy prefix means the last occurrence wins, which is what the recorded format
# guarantees is the only one: every field name appears once per line.
_provenance_field() {
    sed -n "s/.*[[:space:]]${2}=\([^[:space:]]*\).*/\1/p" <<<"$1"
}

# The review's closing verdict line, normalised: last non-blank line, markdown
# emphasis stripped, trimmed. Used by the round below to VALIDATE that Codex
# produced a verdict at all (the guard documented at length at its call site) and
# by `--wait` to REPORT the verdict of an artifact that already passed it. One
# spelling, because two would let `--wait` report a verdict line the round would
# not have accepted.
_last_verdict_line() {
    grep -v '^[[:space:]]*$' "$1" | tail -n 1 |
        tr -d '*#`' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//'
}

# One field of a round marker (`key=value` per line), first occurrence.
_marker_field() {
    [[ -n "$1" && -f "$1" ]] || return 0
    sed -n "s/^${2}=//p" "$1" | head -n 1
}

# The same, for THIS invocation's own loop key. `--start` uses it because the key
# it watches is by definition its own; `--wait` cannot assume that (see
# `_live_marker`).
_round_field() {
    _marker_field "$round_file" "$1"
}

# Whether a round of this (loop, persona) holds the in-flight lock right now.
#
# Probed by trying to take it, which is the only way to ask: an flock lives on an
# open descriptor and leaves nothing on disk to inspect, which is exactly the
# property that makes a crashed round unable to wedge the loop. The file is not
# CREATED to ask the question — a probe that had to create the lock file would
# answer "free" by construction on the first call — so a missing file is "no
# round", which it is.
#
# Any other failure of `flock` (an unreadable file, a descriptor limit) answers
# "held", the safe direction: a false "held" costs `--wait` one more call, where a
# false "free" reports no round in flight while one runs.
_lock_held() {
    [[ "$serialized" -eq 1 && -e "$inflight_file" ]] || return 1
    ! flock -n "$inflight_file" true 2>/dev/null
}

# Whether the round described by marker $1, whose loop key is $2, is running.
# The lock is the signal wherever there is one to read; the marker's own pid is
# the fallback only where there is not, for the reason `--wait` states below.
_marker_live() {
    local inflight="${session_dir}/${2}.${persona}.inflight" pid
    if [[ "$serialized" -eq 1 && -e "$inflight" ]]; then
        ! flock -n "$inflight" true 2>/dev/null
        return
    fi
    pid="$(_marker_field "$1" pid)"
    [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

# The marker of a live round of this persona on this branch, whatever loop key it
# was filed under. A round covering HEAD'S TREE wins outright; failing that, the
# newest live one, so the different-tree report below still has something to name.
#
# The preference is not a tie-break, it is the whole point: two rounds of one
# persona CAN be live at once under different base keys, and picking by recency
# alone would let a newer round on some other tree hide an older one that covers
# HEAD exactly — answering exit 4, "stop polling", about a round that is about to
# record the artifact being waited for.
#
# Scanned rather than read from this invocation's own path, because the loop key
# folds in the BASE (ADR-0025 §1, deliberately: a moved base is a different diff
# and must not inherit a session). So a base that moves while a round runs files
# that round under a key this invocation no longer computes, and reading one path
# would answer "nothing is in flight" about a round plainly visible on disk —
# after which the caller, told never to poll an exit 4, would start a replacement
# round it did not need. `--wait` already declines to pretend about a round on a
# different TREE; declining to pretend about one on a different base is the same
# courtesy, and its absence was an inconsistency rather than a policy.
#
# Scoped by branch, which is what identifies "this review loop" across exactly
# the rewrites the workflow relies on — the same key the aggregate counts by.
_live_marker() {
    local m key started candidate="" newest=-1 covering="" covering_newest=-1
    shopt -s nullglob
    for m in "${session_dir}"/*."${persona}".round; do
        [[ "$(_marker_field "$m" branch)" == "$branch" ]] || continue
        key="${m##*/}"
        key="${key%".${persona}.round"}"
        _marker_live "$m" "$key" || continue
        started="$(_marker_field "$m" started_at)"
        [[ "$started" =~ ^[0-9]+$ ]] || started=0
        if [[ "$(_marker_field "$m" tree)" == "$tree" && "$started" -ge "$covering_newest" ]]; then
            covering_newest="$started"
            covering="$m"
        fi
        if [[ "$started" -ge "$newest" ]]; then
            newest="$started"
            candidate="$m"
        fi
    done
    shopt -u nullglob
    printf '%s' "${covering:-$candidate}"
    return 0
}

# The artifact recorded for (this persona, HEAD's tree), or nothing.
#
# Selected by the RECORDED PROVENANCE, never by parsing the filename — the same
# discipline `ship` follows and for the same reason (ADR-0027 §6): the name is an
# identity, and the fields are what selection is defined over. Where two
# artifacts match one persona and one tree — issue #149's shape, two runs against
# different bases — the one recorded against the base THIS invocation resolved
# wins, because that is the one `ship` can use; failing that, the most recently
# written, so the answer is never silently the older of two.
# A detached round's output, indented and clipped to its tail. The tail is what
# carries the failure; the head is the aggregate, which is long, always present,
# and never the reason a round stopped.
#
# Takes the path explicitly, and distinguishes THREE states, because collapsing
# two of them is how a message stops being true. The single fallback line this
# replaces — `(no log: this round was not started with --start)` — was printed on
# an EMPTY file exactly as on an absent one, and the one caller that reaches it
# with an empty file is `--start`'s own grace expiry, which truncated that file
# and launched a child into it moments earlier. So it told a lane its round had
# not been started, by the very mode that had just started it, three lines under
# a sentence beginning "It failed at startup" (issues #1670, #1674). Both
# reporters read the pair as evidence of a dead round; in all three recorded
# instances the round was alive and went on to record its artifact.
_echo_log() {
    local path="$1"
    if [[ -n "$path" && -s "$path" ]]; then
        tail -n 25 "$path" | sed 's/^/  | /' >&2
    elif [[ -n "$path" ]]; then
        echo "  | (${path#"${repo_root}/"} is empty: the round has written nothing" >&2
        echo "  |  to it yet. That is what a round still starting looks like, and" >&2
        echo "  |  it is not evidence in either direction.)" >&2
    else
        echo "  | (no log: this round was not started with --start, so its output" >&2
        echo "  |  went to the terminal that ran it.)" >&2
    fi
}

_artifact_for_tree() {
    local f line best=""
    shopt -s nullglob
    for f in "${review_dir}"/*.md; do
        line="$(head -n 1 "$f")"
        [[ "$(_provenance_field "$line" persona)" == "$persona" ]] || continue
        [[ "$(_provenance_field "$line" tree)" == "$tree" ]] || continue
        if [[ "$(_provenance_field "$line" base_sha)" == "$base_sha" ]]; then
            shopt -u nullglob
            printf '%s' "$f"
            return 0
        fi
        if [[ -z "$best" || "$f" -nt "$best" ]]; then
            best="$f"
        fi
    done
    shopt -u nullglob
    if [[ -n "$best" ]]; then
        printf '%s' "$best"
    fi
    return 0
}

# --- `--start`: this same round, detached (issue #1594) ----------------------
#
# The round is not reimplemented here. `--start` re-executes THIS script in its
# ordinary foreground form, so the detached round takes the same locks, resolves
# the same loop, writes the same artifact and is subject to every check above and
# below — there is no second code path whose behaviour could drift from the
# reviewed one. What `--start` adds is detachment and a bounded confirmation that
# the round is really running before it hands the terminal back.
#
# The child is handed the RESOLVED BASE COMMIT, not the ref this invocation was
# given. A ref is mutable, and re-resolving it in the child is not the same
# computation: a fetch landing in the window between the parent's `git merge-base`
# and the child's would give the child a different base, hence a different loop
# key, hence a different lock, marker and artifact path from the ones the parent
# is watching. The parent would poll its own key until the grace expired and
# report a failure, while the paid round ran on to completion and recorded a
# perfectly good artifact somewhere the parent never looked.
#
# Passing the commit closes that window by construction — `git merge-base <commit>
# HEAD` is that commit, since it is already an ancestor — so the child's range is
# the parent's range and not merely one resolved the same way a moment later.
# Nothing reads the artifact's `base=` field (`ship` selects on `base_sha`), so
# recording the commit there rather than the ref costs nothing and is the more
# precise provenance for a round whose base was pinned before it was launched.
_mode_start() {
    # Zero is refused rather than accepted as "do not wait". `--start`'s whole
    # contract is that it returns once the round has claimed its loop, so a
    # zero-second budget for that is a contradiction, and it does not fail
    # harmlessly: the deadline is already past on the first pass, so every start
    # would report a round that "is not running" while its child ran on to
    # completion behind the message. Refused at the point it is read, like every
    # other numeric knob here.
    #
    # The default is 120s rather than 30s (issue #1670). A round does not claim
    # the loop the instant it starts: it resolves the base, renders the whole
    # `base...HEAD` diff and computes the patch identity FIRST, and only then
    # takes the persona lock and publishes the marker this poll is watching for.
    # On a large branch, on a machine where two or three other clones are running
    # their own rounds — which is the ordinary state of this project, not an
    # unusual one — that is comfortably more than thirty seconds. The old default
    # made the timeout the common path rather than the exceptional one, and every
    # second of the grace is spent only on a start that has not yet confirmed:
    # nothing waits longer for a round that claims normally.
    local start_grace="${CODEX_REVIEW_START_GRACE:-120}"
    if [[ ! "$start_grace" =~ ^[1-9][0-9]{0,3}$ ]]; then
        echo "CODEX_REVIEW_START_GRACE must be a decimal integer from 1 to 9999 with" \
            "no leading zero (a shell reads a leading zero as octal), not" \
            "'${start_grace}' — it bounds the seconds --start waits for the detached" \
            "round to claim its loop, and zero would declare every round failed" \
            "before any could answer" >&2
        exit 2
    fi

    # The bypass path keeps no state under `.review/session` — no in-flight lock
    # and no round marker (ADR-0025 §1) — so a round started there could be
    # neither observed nor attributed to a tree, and `--start` would be handing
    # back a handle to nothing. Refused rather than degraded, because the only
    # caller of this path is CI, which runs one round in the foreground and has
    # nothing to poll with.
    if [[ "$bypass" -eq 1 ]]; then
        echo "--start is unavailable on the bypass path (CODEX_REVIEW_NO_SANDBOX=1," >&2
        echo "  or GITHUB_ACTIONS=true): it keeps no in-flight state, so a detached" >&2
        echo "  round there could not be waited on. Run the round in the foreground:" >&2
        echo "  scripts/codex-review.sh ${persona} ${base}" >&2
        exit 2
    fi

    # And refused for the same reason where there is no `flock` to take. Without
    # it `_claim_persona` claims nothing (the pre-#142 degradation this script
    # keeps deliberately), so two `--start`s would each launch a round, each
    # observe its own token in the marker they take turns overwriting, and both
    # report success — two concurrent rounds of one persona writing one artifact,
    # one thread and one snapshot. The foreground form carries the same
    # degradation and is left alone, because it is bounded by the operator running
    # one command at a time; `--start` returns immediately and is precisely the
    # affordance that makes two easy to launch by accident. Refusing here is the
    # same trade the bypass refusal above makes, and it costs nothing that the
    # foreground round does not still provide.
    #
    # Not closed with a `mkdir`/PID lockfile instead: this file's `_lock_session`
    # states why at length — such a lock survives its owner and needs a
    # stale-timeout heuristic that either wedges the loop or breaks mutual
    # exclusion, which is worse than declining the mode.
    if [[ "$serialized" -eq 0 ]]; then
        echo "--start is unavailable without 'flock': two detached rounds of one" >&2
        echo "  persona could not be prevented, and both would write the same" >&2
        echo "  artifact, thread and disposition snapshot (ADR-0015, issue #142)." >&2
        echo "  Run the round in the foreground instead:" >&2
        echo "  scripts/codex-review.sh ${persona} ${base}" >&2
        exit 2
    fi

    mkdir -p "$session_dir"

    # `--start` is itself a read-modify-write — it READS whether a round is in
    # flight and then WRITES one, truncating the log and launching a child — and
    # #142's argument about the loop's state applies to it unchanged: two
    # invocations interleaving between those two steps both launch. Exactly one
    # round still runs, because only one child can claim the persona lock; what
    # goes wrong is the REPORT. The loser's parent finds the winner's marker,
    # cannot tell it from its own child's, and returns 0 for a child that was
    # refused — and its truncation of the shared log can take the winner's early
    # output with it. So the whole of it runs inside an exclusive lock.
    #
    # `-n` rather than a bounded wait: a second concurrent `--start` of one
    # persona is a mistake, not contention worth queueing behind. Held for the
    # confirmation poll too, which is what makes the in-flight probe below
    # conclusive — by the time this lock is released, this invocation's child
    # holds the persona lock, so the next probe sees it. Blocks nothing else: the
    # lock is per (loop, persona), and the loop's own lock is untouched.
    # The descriptor is opened unconditionally and only LOCKED where `flock`
    # exists, so the launch below can name it in a literal `{fd}>&-` — a
    # redirection is parsed before any expansion, so it cannot be assembled
    # conditionally out of a variable.
    local start_lock_fd=""
    exec {start_lock_fd}<>"$start_lock_file"
    if [[ "$serialized" -eq 1 ]] && ! flock -n "$start_lock_fd"; then
        echo "another 'scripts/codex-review.sh --start ${persona}' is in progress in" >&2
        echo "  this clone. Personas run one at a time (ADR-0015, issue #142); if it" >&2
        echo "  is the round you wanted, wait on it:" >&2
        echo "  scripts/codex-review.sh --wait ${persona}" >&2
        exit 1
    fi

    # Refused here as well as in the round, so the caller reads the reason on its
    # own terminal instead of having to go and find it in a log. Under the start
    # lock above this is conclusive rather than advisory; without `flock` it
    # degrades to a probe, and the token check below is then what keeps this
    # invocation from claiming another's round as its own.
    if _lock_held; then
        echo "another '${persona}' review of this loop is already running in this" >&2
        echo "clone; refusing to start a second one. Two rounds of one persona share" >&2
        echo "an artifact, a thread and a disposition snapshot, so they cannot both" >&2
        echo "be recorded (ADR-0015, issue #142)." >&2
        echo "wait on the one that is running:" >&2
        echo "  scripts/codex-review.sh --wait ${persona}" >&2
        exit 1
    fi

    local self="$0"
    case "$self" in
    /*) ;;
    *) self="${PWD}/${self}" ;;
    esac

    # A token for THIS attempt, so the confirmation below is about the child this
    # invocation launched rather than about "some round of this persona". The
    # start lock makes a rival child impossible in the normal case; the token is
    # what still answers correctly where there is no `flock` to take, and what
    # keeps a `--start` from reporting success for a child that was refused.
    local start_token launched_at
    start_token="$(_mint_id)"
    launched_at="$(date +%s)"
    : >"$log_file"

    # Detached, deliberately, and not merely backgrounded. The caller of `--start`
    # is by construction about to exit — that is the entire reason this mode
    # exists — and a bare `&` leaves the round in the caller's process group and
    # session, where the caller's own teardown takes the round down with it. A
    # round killed at minute eight is the same lost round `--start` exists to
    # prevent, only harder to notice. `setsid --fork` gives it a session of its
    # own; `nohup` is the fallback where util-linux is absent and closes the
    # SIGHUP half of the same problem.
    #
    # The start lock is CLOSED in the child. An flock lives on a descriptor and a
    # forked child inherits it, so a round launched with it open would hold its
    # parent's start lock for the whole round — long after the `--start` that took
    # it had returned. The next `--start` would then be refused as "another start
    # is in progress" when what is really true is "a round is running", which is a
    # different fact with a different remedy. The parent keeps its own copy: a
    # redirection binds to the command it is written on.
    if command -v setsid >/dev/null 2>&1; then
        CODEX_REVIEW_DETACHED_LOG="$log_file" CODEX_REVIEW_START_TOKEN="$start_token" \
            setsid --fork "${BASH:-bash}" "$self" "$persona" "$base_sha" \
            >"$log_file" 2>&1 </dev/null {start_lock_fd}>&- &
    else
        CODEX_REVIEW_DETACHED_LOG="$log_file" CODEX_REVIEW_START_TOKEN="$start_token" \
            nohup "${BASH:-bash}" "$self" "$persona" "$base_sha" \
            >"$log_file" 2>&1 </dev/null {start_lock_fd}>&- &
    fi

    # Hand back only once THIS invocation's round has published the tree it
    # pinned. Returning any earlier would let `--start` succeed on a round that
    # died in its first second — a dirty tree, a missing rubric, a Codex that is
    # not there — and the caller would then poll for an artifact nothing is
    # producing until it gave up. Three things are checked, and each excludes a
    # different wrong marker: the token excludes another invocation's child,
    # `started_at` excludes a marker left by an earlier round of this same loop,
    # and the tree excludes a round reviewing other content.
    local deadline=$((launched_at + start_grace)) r_tree r_started r_token
    while :; do
        r_tree="$(_round_field tree)"
        r_started="$(_round_field started_at)"
        r_token="$(_round_field start_token)"
        if [[ "$r_token" == "$start_token" && "$r_tree" == "$tree" &&
            "$r_started" =~ ^[0-9]+$ && "$r_started" -ge "$launched_at" ]]; then
            break
        fi
        # A live round under a different token: this invocation lost a race the
        # start lock is meant to prevent, so it is only reachable without `flock`.
        # Said at once rather than after the grace, because the answer is already
        # known and it is not "your round is starting".
        if [[ -n "$r_token" && "$r_token" != "$start_token" ]] &&
            [[ "$r_started" =~ ^[0-9]+$ && "$r_started" -ge "$launched_at" ]]; then
            echo "another '${persona}' round of this loop claimed it first; this start" >&2
            echo "  was refused. Exactly one round is running — wait on it:" >&2
            echo "  scripts/codex-review.sh --wait ${persona}" >&2
            exit 1
        fi
        if [[ "$(date +%s)" -ge "$deadline" ]]; then
            # Stated as what is known — the claim did not arrive — rather than as
            # "it is not running", which this cannot see. The child is left alone
            # rather than killed: if it is merely slow it will claim the loop and
            # `--wait` will find it, where killing a round mid-flight would throw
            # away work to make a message true.
            #
            # The ORDER of the sentences is the fix issue #1670 asks for. The
            # message used to lead with "It failed at startup", which is the one
            # reading this code cannot support and the one that invites the
            # relaunch `--start` exists to prevent; both reports of it were rounds
            # that were running perfectly well. So it now leads with the action,
            # says plainly that nothing here has killed anything, and names the
            # reason a healthy round is often still unclaimed at this point.
            #
            # The status stays 1. It is not a claim about the round — it is
            # `--start`'s own contract, which is to return zero once THIS
            # invocation's round is confirmed running, and that has not happened.
            # A distinct code would only help a caller that acted differently on
            # it, and the one thing any caller should do here is the one line
            # below.
            echo "the detached '${persona}' round has not claimed this loop within" >&2
            echo "  ${start_grace}s. Nothing here has killed it, and nothing here can" >&2
            echo "  see whether it is dead: a round claims the loop only after it has" >&2
            echo "  rendered the whole diff and computed the patch identity, so a" >&2
            echo "  healthy round on a large branch — or on a machine where another" >&2
            echo "  clone is reviewing — is often still short of that point." >&2
            echo "  Do NOT start a second round; ask --wait, which is the only thing" >&2
            echo "  that can tell a slow start from a failed one:" >&2
            echo "    scripts/codex-review.sh --wait ${persona}" >&2
            echo "  Its output so far:" >&2
            _echo_log "$log_file"
            exit 1
        fi
        sleep 1
    done

    local r_loop r_pid
    r_loop="$(_round_field loop_id)"
    r_pid="$(_round_field pid)"
    printf 'persona=%s\n' "$persona"
    printf 'loop_id=%s\n' "${r_loop:-noloop}"
    printf 'tree=%s\n' "$tree"
    printf 'sha=%s\n' "$sha"
    printf 'base_sha=%s\n' "$base_sha"
    printf 'pid=%s\n' "$r_pid"
    printf 'log=%s\n' "${log_file#"${repo_root}/"}"
    {
        echo
        echo "===== ${persona} review started, detached ====="
        echo "  loop     ${r_loop:-noloop}"
        echo "  tree     ${tree:0:12}  (HEAD ${sha:0:12} vs ${base})"
        echo "  pid      ${r_pid}"
        echo "  log      ${log_file#"${repo_root}/"}"
        echo "  wait     scripts/codex-review.sh --wait ${persona}"
        echo
    } >&2
    return 0
}

# --- `--wait`: block on the round for HEAD's tree, then report it ------------
#
# Answers one question — "is there a review of the content HEAD carries yet?" —
# and answers it in a bounded call, so a caller that cannot hold a process open
# for the minutes a round takes can ask it repeatedly instead of once (#1594).
#
# Three outcomes, three exit statuses, because the caller's next move differs for
# each: 0 with the artifact (read it), 3 `still running` (call again), 4 with no
# round in flight for this tree (start one, or look at what went wrong). Only 3
# means "ask again"; treating a 4 as a 3 is the poll that never terminates, and
# treating a 3 as a 4 is the relaunch that throws away a round mid-flight.
_mode_wait() {
    local timeout="${timeout_arg:-540}"
    if [[ ! "$timeout" =~ ^(0|[1-9][0-9]{0,8})$ ]]; then
        echo "--timeout must be a non-negative decimal integer of at most 9 digits" \
            "with no leading zero (a shell reads a leading zero as octal), not" \
            "'${timeout}' — it bounds the seconds --wait blocks before reporting" \
            "'still running'" >&2
        exit 2
    fi
    local interval="${CODEX_REVIEW_WAIT_INTERVAL:-5}"
    if [[ ! "$interval" =~ ^[1-9][0-9]{0,3}$ ]]; then
        echo "CODEX_REVIEW_WAIT_INTERVAL must be a decimal integer from 1 to 9999" \
            "with no leading zero, not '${interval}' — it is the seconds between" \
            "polls, and zero would spin" >&2
        exit 2
    fi

    local deadline=$(($(date +%s) + timeout))
    local artifact line verdict r_tree marker m_tree m_base live unknown now remaining
    local noted_base=0
    while :; do
        # LIVENESS IS READ FIRST, AND THE ARTIFACT SECOND. The order is the whole
        # of issues #1629 and #1630: a round records its artifact and only then
        # exits, so "gone" always arrives after "recorded". Reading the artifact
        # first inverted that — a round that recorded and exited between the two
        # reads was seen as neither, and every path below answers exit 4, "stop
        # polling", about a finished green round. Three lanes were told that in one
        # day (#1624 r1, #1625 r4, #1626 r8), each with the verdict visible in the
        # log printed as evidence of failure.
        #
        # This order makes the window unreachable rather than narrower: the file
        # listing below is expanded strictly after the liveness observation, so a
        # round observed gone has necessarily already renamed its artifact into
        # place (`mv`, atomic, far below) and the listing contains it. Re-reading
        # the artifact directory a second time before each exit 4 would be the same
        # guarantee bought with two reads instead of one, and with two scan sites
        # to keep in step.
        #
        # The direction it can still be wrong in is the harmless one: a round that
        # finished after the liveness read is reported as still running, and the
        # next poll — one interval later — reports its artifact.
        #
        # This loop key's own marker, kept for the "it died" diagnosis below: that
        # question is about the round THIS invocation would have started, and its
        # log is the one at this key's path.
        r_tree="$(_round_field tree)"
        # Liveness, across every loop key on this branch — a base that moved while
        # a round ran filed it under a key this invocation no longer computes.
        # Liveness has two independent sources and BOTH are consulted, because
        # each sees something the other cannot.
        #
        # `_live_marker` scans every loop key on this branch, which is what finds
        # a round whose base moved under it — the loop key folds in the base, so
        # such a round is filed under a key this invocation no longer computes. It
        # already prefers a round covering HEAD's tree over a newer one that does
        # not.
        #
        # The current loop's lock sees what no marker can: a round that has
        # claimed the loop but not yet published its marker. `_claim_persona`
        # clears the previous marker on the way in and republishes about a second
        # later, so every round has such a window, and in it the round's tree is
        # UNKNOWN rather than absent.
        #
        # Keeping them separate is what makes both answers right. Reading only the
        # scan reports exit 4 about a round that is starting; reading only the
        # current lock lets a round in this loop, on some other tree, mask a live
        # round elsewhere that covers HEAD exactly. Each of those was a real
        # defect here.
        marker="$(_live_marker)"
        m_tree=""
        m_base=""
        live=0
        unknown=0
        if [[ -n "$marker" ]]; then
            live=1
            m_tree="$(_marker_field "$marker" tree)"
            m_base="$(_marker_field "$marker" base_sha)"
        fi
        if _lock_held; then
            live=1
            if [[ -z "$(_round_field tree)" ]]; then
                unknown=1
            fi
        fi

        # A record for HEAD's tree is the authoritative answer (ADR-0027 §6 — it is
        # what `ship` selects by), so it is read after the liveness observation
        # above and wins over it in both directions.
        artifact="$(_artifact_for_tree)"
        if [[ -n "$artifact" ]]; then
            line="$(head -n 1 "$artifact")"
            # The artifact only exists because the round's own verdict guard
            # accepted its last line, so what is left is stripping the optional
            # label the guard permits. `LC_ALL=C` for the reason that guard states
            # at length: `[^[:alnum:]]` is locale-dependent, and in a single-byte
            # non-ASCII locale an em dash's leading byte reads as a letter.
            verdict="$(_last_verdict_line "$artifact")"
            verdict="$(LC_ALL=C sed -E 's/^[Vv][Ee][Rr][Dd][Ii][Cc][Tt][^[:alnum:]]*//; s/\.$//' \
                <<<"$verdict" | tr '[:lower:]' '[:upper:]')"
            printf 'artifact=%s\n' "${artifact#"${repo_root}/"}"
            printf 'persona=%s\n' "$persona"
            printf 'tree=%s\n' "$tree"
            printf 'round=%s\n' "$(_provenance_field "$line" round)"
            printf 'verdict=%s\n' "$verdict"
            {
                echo
                echo "===== ${persona} review of tree ${tree:0:12} is recorded ====="
                echo "  artifact  ${artifact#"${repo_root}/"}"
                echo "  verdict   ${verdict}"
                echo "  round     $(_provenance_field "$line" round)"
                echo "  churn     $(_provenance_field "$line" churn_ratio)"
                echo
            } >&2
            return 0
        fi

        # Only where the tree is actually KNOWN: an unpublished marker in this
        # loop means a round is starting, and "stop polling" is the one answer
        # that must never be guessed.
        if [[ "$live" -eq 1 && "$unknown" -eq 0 && -n "$m_tree" && "$m_tree" != "$tree" ]]; then
            echo "the '${persona}' round running in this clone is reviewing tree" >&2
            echo "  ${m_tree:0:12}, not HEAD's ${tree:0:12}. Nothing will record an" >&2
            echo "  artifact for HEAD's tree until a round is started on it — most" >&2
            echo "  often because a commit landed after that round was started." >&2
            exit 4
        fi

        # Said once, not every poll. The round is reviewing HEAD's tree against a
        # base that has since moved, so it will record an artifact for this tree
        # under the older base — which is worth waiting out either way, since
        # whether that artifact still covers the PR is ADR-0027 §2's question and
        # `ship` is what answers it.
        if [[ "$live" -eq 1 && "$unknown" -eq 0 && -n "$m_base" &&
            "$m_base" != "$base_sha" && "$noted_base" -eq 0 ]]; then
            noted_base=1
            echo "note: the round in flight was started against base ${m_base:0:12}," >&2
            echo "  which has since moved to ${base_sha:0:12}. It is reviewing HEAD's" >&2
            echo "  tree and will record an artifact for it; whether that still covers" >&2
            echo "  the PR is ADR-0027 §2's question, which 'just ship' answers." >&2
        fi

        if [[ "$live" -eq 0 ]]; then
            if [[ "$r_tree" == "$tree" ]]; then
                # The log is read from the path THAT ROUND recorded in its own
                # marker, not from the one this invocation would compute. They are
                # normally the same file, but the marker is the round's own
                # statement about where its output went, and it is empty for a
                # round that ran in the foreground — which `_echo_log` then says,
                # instead of pointing at a file that was never written.
                echo "the '${persona}' round for HEAD's tree ${tree:0:12} is no longer" >&2
                echo "  running and recorded no artifact — it failed rather than" >&2
                echo "  finished. Its own output follows:" >&2
                _echo_log "$(_round_field log)"
                exit 4
            fi
            echo "no '${persona}' round is in flight for HEAD's tree ${tree:0:12}, and" >&2
            echo "  no artifact covers it." >&2
            echo "  start one:  scripts/codex-review.sh --start ${persona}" >&2
            if [[ "$bypass" -eq 1 ]]; then
                echo "  (this invocation is on the bypass path, which keeps no in-flight" >&2
                echo "   state — a round running under it cannot be observed at all, only" >&2
                echo "   its finished artifact can.)" >&2
            fi
            exit 4
        fi

        now="$(date +%s)"
        if [[ "$now" -ge "$deadline" ]]; then
            echo "still running: the '${persona}' round for HEAD's tree ${tree:0:12}" >&2
            echo "  has not finished within ${timeout}s. Nothing is wrong and nothing" >&2
            echo "  is lost — call --wait again to keep waiting (issue #1594)." >&2
            exit 3
        fi
        remaining=$((deadline - now))
        if [[ "$remaining" -lt "$interval" ]]; then
            sleep "$remaining"
        else
            sleep "$interval"
        fi
    done
}

case "$mode" in
start)
    _mode_start
    exit 0
    ;;
wait)
    _mode_wait
    exit 0
    ;;
esac

# One limit is left standing, deliberately, and it cuts both ways. The name is
# all that identifies the loop, so reusing a name inherits the old branch's
# rounds and over-counts, while *renaming* a branch mid-loop orphans every
# artifact filed under the old name and resets the count to 1.
#
# The second direction is the worse of the two and is worth stating plainly: this
# number exists to make a runaway loop legible, so under-counting hides the very
# thing it is for, where over-counting only says "look at your loop" too loudly.
# What keeps it acceptable is not the direction but the occasion — an open PR is
# bound to its branch name, so a rename mid-review breaks the PR before it can
# skew the count, and neither case arises from the rewrites this is built to
# survive, since squash, amend and rebase all preserve the name.
#
# Fixing it needs a durable per-loop identifier — a ledger in `.review/`, which
# is state to maintain and to keep consistent across those same rewrites. That
# is a real design with failure modes of its own, and #97 lists it as a candidate
# without mandating it. Not worth building for an advisory number until one of
# these cases is actually observed.

# --- The reviewed range's rendering, and its identity (ADR-0027 §2) ----------
#
# THIS BLOCK IS DUPLICATED VERBATIM IN scripts/ship.sh AND MUST STAY IDENTICAL.
# One script records the identity and the other recomputes it to decide whether a
# review still covers HEAD across a moved base, so a divergence between the two
# spellings would not fail loudly — it would compute two different identities for
# one patch and quietly cost a review round every time. Same reasoning as
# `artifact_has_verdict`, which is duplicated across the pair for the same
# reason.
#
# `core.quotePath=false` in the pinned set below is also what the reviewer's own
# diff uses, so a non-ASCII path reaches it as `docs/café.md` rather than
# `"docs/caf\303\251.md"` — an escaped path is a file it cannot find in the tree.
# >>> shared-patch-identity (ADR-0027 §2) — kept byte-identical in both scripts
# The diff options are PINNED rather than inherited from the repository or user
# config. Every one of them changes the rendered patch text and therefore the
# identity, so leaving them to config would make the identity a function of when
# and where it was computed rather than of the two commits. `diff.context` and
# `diff.interHunkContext` decide how much surrounding text a hunk carries and
# whether two nearby hunks render as one; `diff.renameLimit` decides whether
# rename detection completes at all, and a silent fallback to no detection is a
# different patch; `color.ui=always` emits ANSI escapes even off a terminal,
# which would land in the hashed bytes and in what the reviewer reads.
#
# THE LIST IS NOT CLAIMED EXHAUSTIVE, and the residual is stated rather than
# argued away: git exposes further rendering inputs (`diff.orderFile`, an
# attribute-selected diff driver) that a `-c` cannot neutralise. What bounds the
# damage is the DIRECTION of the failure. An unpinned knob differing between the
# recording run and the ship run reorders, merges or decorates the rendered
# patch, so the two identities differ and the artifact is REFUSED — one spurious
# round, which is the cost this decision removes, not a review reused for content
# nobody read.
#
# The dangerous direction is an option that STRIPS information until two
# different patches collide, and there are exactly two, both closed by a flag
# rather than by config — config is what an option like this is usually set from,
# and a `-c` can be outranked by a narrower one:
#
#   whitespace       — closed by `patch-id --verbatim` over `--stable` (§2);
#   submodules       — closed by `--ignore-submodules=none`. Under
#                      `diff.ignoreSubmodules=all`, or a narrower
#                      `submodule.<name>.ignore=all` that outranks it, a changed
#                      gitlink vanishes from the patch, from `--raw`, and from
#                      the `--name-status` listing — so an identity would omit a
#                      submodule bump the reviewer never saw, and §4 would publish
#                      as "whole" a drift set missing one. The command-line flag
#                      is used because it outranks both config forms.
_diff_opts=(
    -c core.quotePath=false
    -c color.ui=false
    -c diff.renames=true
    -c diff.renameLimit=4000
    -c diff.algorithm=myers
    -c diff.context=3
    -c diff.interHunkContext=0
    -c diff.indentHeuristic=true
    -c diff.noprefix=false
    -c diff.mnemonicPrefix=false
)

# Whether the range carries an entry with NEITHER a hunk NOR an `index` line, so
# its contribution to the identity is a function of its PATHS ALONE (ADR-0027 §2).
# That is exactly the set of entries whose pre- and post-image blobs are the same
# object: a 100%-similarity rename or copy, and a mode-only change. git emits
# `similarity index 100% / rename from / rename to` or `old mode / new mode` for
# those and no `index` line at all, so a reviewed rename of `f` to `g`, rebased
# onto a base that changed `f`'s contents, presents a byte-identical identity
# while `g` now holds content no reviewer saw.
#
# Read from `--raw -z` rather than by scanning the rendered patch text: the blob
# pair is the structural fact, where a text scan would have to guess at entry
# boundaries in a format where a pathname may itself contain a newline.
# A LISTING THAT COULD NOT BE READ IS REPORTED AS PATHLESS. The producer's exit
# status has to be captured rather than read through a process substitution,
# which discards it: `git diff` can fail *after* emitting a prefix — an
# unreadable blob in a partial clone, a broken pipe — and a truncated listing
# read as a complete one would say "no pathless entry" about a range it never
# finished describing. So it is written to a file whose write is checked, and any
# failure answers the fail-closed way rather than the convenient way.
_range_has_pathless_entry() {
    local -a rec=()
    local raw
    raw="$(mktemp -t patch-raw.XXXXXX)" || return 0
    if ! git "${_diff_opts[@]}" diff --no-color --ignore-submodules=none --no-ext-diff --no-textconv --raw --abbrev=40 -z \
        "$1...$2" >"$raw"; then
        rm -f "$raw"
        return 0
    fi
    mapfile -d '' -t rec <"$raw"
    rm -f "$raw"
    local i=0 meta old new status
    while [[ $i -lt ${#rec[@]} ]]; do
        meta="${rec[$i]}"
        # ":<oldmode> <newmode> <oldsha> <newsha> <status>"
        read -r _ _ old new status <<<"${meta#:}"
        case "$status" in
        R* | C*) i=$((i + 3)) ;;
        *) i=$((i + 2)) ;;
        esac
        # A record that runs off the end is a format this cannot parse, so it is
        # reported as pathless: unparsed is not the same as safe.
        if [[ $i -gt ${#rec[@]} || "$old" == "$new" ]]; then
            return 0
        fi
    done
    return 1
}

# The identity of the patch `git diff <$1>...<$2>` renders (ADR-0027 §2). Echoes
# the identity, or NOTHING when the range has no identity that may be trusted.
#
# The mechanism is `git patch-id --verbatim`, and specifically NOT `--stable`.
# Both ignore hunk line numbers — the first property, so a base move elsewhere in
# a touched file merely renumbers the hunk headers and must not invalidate — but
# `--stable` also STRIPS WHITESPACE, which fails the second property outright: a
# base move that re-indents a context line inside a reviewed hunk is semantic in
# Python, and under `--stable` the identity would not move, so a review of
# content that is no longer there would be reused. `--verbatim` calculates the id
# of the input as given and implies `--stable`, so it satisfies both. The two
# spellings differ by one flag and only one of them is safe; ADR-0027 §2 fixes
# the choice here rather than leaving it to the implementation.
#
# Empty output is the fail-closed answer, never a value to compare: an empty
# range, an entry anchored on its paths alone, or a `patch-id` that produced
# nothing all make the moved-base acceptance path UNAVAILABLE rather than
# satisfied. Two such artifacts must never compare equal to each other.
patch_identity() {
    if _range_has_pathless_entry "$1" "$2"; then
        return 0
    fi
    git "${_diff_opts[@]}" diff --no-color --ignore-submodules=none --no-ext-diff --no-textconv "$1...$2" |
        git patch-id --verbatim | awk 'NR == 1 { print $1 }' || return 0
}
# <<< shared-patch-identity

diff="$(git "${_diff_opts[@]}" diff --no-color --ignore-submodules=none --no-ext-diff --no-textconv "${base_sha}...${content_sha}")"
if [[ -z "$diff" ]]; then
    echo "no changes between ${base_sha} and ${content_sha} to review" >&2
    if [[ -n "$ratify_adr" ]]; then
        echo "  (HEAD is the ratification flip of ${ratify_adr}, so the reviewed range" >&2
        echo "   is its parent's — and this PR carries nothing but the flip. There is" >&2
        echo "   no content for a round to cover, and none for 'just ship' to ask" >&2
        echo "   about either; ADR-0165 §3 anchors both on that parent.)" >&2
    fi
    exit 0
fi

# The identity of the patch this review reads, pinned here with the other three
# edges and for the same reason: everything the artifact certifies is resolved
# before the review starts, never after it. `ship` recomputes it against the
# PR's current merge base, and where the base has MOVED it is what says whether
# the reviewer read this content (ADR-0027 §2). Recorded empty when the range has
# no trustworthy identity, which is what makes the moved-base path unavailable
# rather than accepted.
patch_id="$(patch_identity "$base_sha" "$content_sha")"

# --- Aggregate (ADR-0020 §2) -------------------------------------------------
#
# Printed on every run, unasked, and recorded in the provenance line so `just
# ship` carries it to the PR. The failure mode this addresses is illegibility,
# not excess: every round of a runaway loop is locally defensible, and neither
# runaway case in issue #91 terminated on its own — both were stopped from
# outside by someone holding an aggregate view. So this blocks nothing and gates
# nothing. It is a number, deliberately: a round cap would have forbidden the
# round of #90 that found `gh pr merge --match-head-commit`.
#
# Everything below is `git log --numstat` arithmetic — no model, no judgment.

# Round: how many *distinct reviewed states* of this branch already exist, plus
# this one. A round is a review of a content state, so that is what is counted —
# the trees recorded in `.review/`, not the commits those artifacts are filed
# under (issue #97).
#
# Counting lineage commits was the obvious reading of §2, and it does not
# survive the very operations §3 exists to make cheap. A squash, an amend or a
# rebase in place removes the previously reviewed SHAs from `base..HEAD`, so the
# count resets toward 1 — precisely on the branch that has been through enough
# rounds to be worth squashing. The mechanism that encourages the rewrite was
# erasing the aggregate the rewrite is evidence for.
#
# Keying on the recorded tree fixes that for free, because `.review/` is
# git-ignored: rewriting history does not touch the artifacts, and a tree is
# stable across every rewrite that preserves content. The same property makes
# the count behave as before where it was already right — a second persona on
# one commit, or a re-run of one persona, reviews the same tree as HEAD and so
# is excluded rather than inflating the round.
#
# Scoped by *branch name*, which `.review/` records for this purpose. The scope
# key has to identify "this review loop", and the branch is the only thing that
# does: `.review/` is a per-clone directory that accumulates across every branch
# worked in it, so an unscoped count would report a previous PR's rounds as this
# one's. The base commit is not a usable key either — two branches cut from the
# same `origin/main` share it exactly, so scoping on it would let a finished
# branch's rounds leak into a fresh one — while the branch name is stable across
# precisely the rewrites this is trying to survive, rebase onto a moved base
# included.
#
# An artifact written before the field existed is skipped rather than guessed
# at, so the count resets once across that upgrade and is right afterwards.
declare -A reviewed_trees=()
shopt -s nullglob
for artifact_file in "${review_dir}"/*.md; do
    artifact_line="$(head -n 1 "$artifact_file")"
    artifact_branch="$(_provenance_field "$artifact_line" branch)"
    artifact_tree="$(_provenance_field "$artifact_line" tree)"
    # No recorded tree or branch means the artifact predates this and says
    # nothing usable. HEAD's own tree is this round, not a previous one — which
    # is what keeps a second persona, or a re-run, from inflating the count.
    if [[ -z "$artifact_branch" || -z "$artifact_tree" ]]; then
        continue
    fi
    if [[ "$artifact_branch" != "$branch" || "$artifact_tree" == "$tree" ]]; then
        continue
    fi
    reviewed_trees["$artifact_tree"]=1
done
shopt -u nullglob
round=$((${#reviewed_trees[@]} + 1))

# How many of those earlier reviewed states are still reachable on this branch.
# One that is not means history was rewritten, which is what makes the churn
# figure below a lower bound: the commits carrying that rework are gone from
# `base..HEAD`, so `git log --numstat` cannot see the lines they touched.
declare -A lineage_trees=()
while read -r commit; do
    if [[ -n "$commit" ]]; then
        lineage_trees["$(git rev-parse "${commit}^{tree}")"]=1
    fi
done < <(git rev-list "${base_sha}..${sha}")

orphaned_rounds=0
for reviewed_tree in "${!reviewed_trees[@]}"; do
    if [[ -z "${lineage_trees[$reviewed_tree]:-}" ]]; then
        orphaned_rounds=$((orphaned_rounds + 1))
    fi
done

# Sum added+deleted across a --numstat stream, and count the entries that report
# `-` in both columns. Those are binary: git measures no lines for them at all.
# Skipping them in the sum is right — coercing `-` to 0 would imply a
# measurement that was never taken — but skipping them *silently* is what issue
# #100 is about, since a commit that replaces a binary asset then reports
# `net_lines=0` and `churn_ratio=n/a`, indistinguishable from a rename- or
# mode-only change that really did touch nothing. Counted here so the output can
# say "unmeasured" instead of implying "unchanged".
#
# Emits both numbers on one line so the stream is consumed once.
_numstat() {
    awk '{ if ($1 ~ /^[0-9]+$/) a += $1
           if ($2 ~ /^[0-9]+$/) d += $2
           if ($1 == "-" && $2 == "-") b++ }
         END { print a + d + 0, b + 0 }'
}

# Pinned against config for the same reason as the patch-identity block above,
# with a much smaller stake: these two feed ADR-0020 §2's advisory aggregate, so
# a decorated stream that `_numstat`'s `^[0-9]+$` guard then declined to sum
# would understate a printed figure, not move a gate. Current git colours neither
# stream, so no number changes here — the reads are pinned because nothing pinned
# them.
read -r net_lines net_binary < <(
    git -c color.ui=false diff --no-color --numstat "${base_sha}...${sha}" | _numstat
)
read -r churn_lines churn_binary < <(
    git -c color.ui=false log --no-color --numstat --format= "${base_sha}..${sha}" | _numstat
)
commits="$(git rev-list --count "${base_sha}..${sha}")"

# Churn ratio: cumulative lines touched across the branch's commits divided by
# net lines in the final diff. Far above 1 means most of the work has been
# rework — the mechanical proxy for "consecutive commits fixing what the
# previous commit introduced". A diff of pure renames or mode changes touches no
# lines, so guard the division rather than reporting a ratio of nothing.
churn_ratio="n/a"
if [[ "$net_lines" -gt 0 ]]; then
    churn_ratio="$(awk -v c="$churn_lines" -v n="$net_lines" 'BEGIN { printf "%.1f", c / n }')"
fi

# Churn is defined over the branch's commits (ADR-0020 §2), and a rewrite takes
# commits away, so after a squash the figure counts only the work done since —
# understating the rework exactly where it matters most. That definition is not
# quietly redefined here: recovering the true figure would mean reconstructing
# work from trees that may already have been garbage-collected, and inventing a
# number is worse than reporting a smaller one honestly.
#
# So the limitation is labelled instead of defeated. Where an earlier reviewed
# state is no longer on the branch, the ratio is marked a lower bound and the
# missing rounds are named, which is what the aggregate is for: the number
# exists to be legible, and a figure silently understating rework on a
# much-reworked branch is the opposite of legible.
churn_bound="exact"
if [[ "$orphaned_rounds" -gt 0 ]]; then
    churn_bound="lower"
fi

# Where the change supersedes or amends another document, that document's size
# belongs next to this one's: ADR-0017 superseded one clause of a 175-line ADR
# and peaked at 821 lines, and it was that comparison — one number next to
# another — that made two hours of drift legible. Read off the *added* lines
# only, so an unchanged historical mention does not register.
#
# Matched case-sensitively, and that is a decision rather than an oversight
# (issue #100). `Supersedes:` and `Amends:` are ADR *fields*, and every
# occurrence in docs/adr/ is capitalised as one. Matching lowercase too would
# pick up ordinary prose — "this amends ADR-0004", "which supersedes ADR-0012" —
# in body text and running commentary, which names a document the change does
# not actually supersede. The field convention is the signal; the word is not.
supersedes=""
supersedes_pretty=""
mapfile -t superseded_refs < <(
    printf '%s\n' "$diff" | grep -E '^\+' | grep -E 'Supersedes|Amends' |
        grep -oE 'ADR-[0-9]{4}' | sort -u
)
if [[ ${#superseded_refs[@]} -gt 0 ]]; then
    for ref in "${superseded_refs[@]}"; do
        for target in "${repo_root}/docs/adr/${ref#ADR-}-"*.md; do
            [[ -f "$target" ]] || continue
            target_lines="$(wc -l <"$target" | tr -d '[:space:]')"
            supersedes="${supersedes:+${supersedes},}${ref}:${target_lines}"
            supersedes_pretty="${supersedes_pretty:+${supersedes_pretty}, }${ref} (${target_lines} lines)"
        done
    done
fi

{
    echo
    echo "===== aggregate (ADR-0020 §2) ====="
    echo "  round        ${round} — distinct reviewed states of this branch, plus this one"
    net_desc="${net_lines} lines across ${commits} commit(s)"
    if [[ "$net_binary" -gt 0 ]]; then
        net_desc="${net_desc}, plus ${net_binary} binary file(s), unmeasured"
    fi
    echo "  net diff     ${net_desc}"
    churn_desc="${churn_ratio} — ${churn_lines} lines touched ÷ ${net_lines} net"
    if [[ "$churn_binary" -gt 0 ]]; then
        churn_desc="${churn_desc}, plus ${churn_binary} binary change(s), unmeasured"
    fi
    echo "  churn ratio  ${churn_desc}"
    if [[ "$churn_bound" == "lower" ]]; then
        echo "               ^ a LOWER BOUND: ${orphaned_rounds} earlier reviewed state(s) are no"
        echo "                 longer on this branch's history (squash, amend or rebase), so the"
        echo "                 rework before that rewrite is not counted. The round count above"
        echo "                 does include them."
    fi
    if [[ -n "$supersedes_pretty" ]]; then
        echo "  supersedes   ${supersedes_pretty}"
    fi
    echo "  (advisory — nothing here blocks. A high round count or a churn ratio"
    echo "   far above 1 is the signal that the loop is reworking itself.)"
    echo
} >&2

prompt="$(mktemp -t "codex-prompt-${persona}.XXXXXX.md")"
out="$(mktemp -t "codex-review-${persona}.XXXXXX.md")"
# The `--json` event stream from a persistent round is captured here to read the
# `thread_id` back; `$inject_tmp` holds re-injected prior dispositions on a
# degraded round. Both are cleaned on every exit path alongside `$out`.
stream="$(mktemp -t "codex-stream-${persona}.XXXXXX.json")"
inject_tmp="$(mktemp -t "codex-inject-${persona}.XXXXXX.md")"
# Every temporary, on every exit path. `$out` holds the full review text and
# `$artifact_tmp` a half-written copy of it, so leaving either behind accumulates
# review content in /tmp and in .review/ — the latter invisible to the dirty-tree
# check, since .review/ is ignored. ${var:+...} expands to nothing while
# artifact_tmp is still unset, which it is for most of this script.
trap 'rm -f "$prompt" "$out" "$stream" "$inject_tmp" ${artifact_tmp:+"$artifact_tmp"}' EXIT

# --- Persistent session identity and read-only proof (ADR-0025 §1) -----------
#
# A review loop keeps ONE Codex conversation, resumed each round via `codex exec
# resume`, so the reviewer carries what it already said and what the author
# already answered (#125's memoryless re-raise is gone at the root). The session,
# its fallback transcript, and the recorded dispositions are bound to a durable
# per-loop identity, not the bare branch name — a reused or renamed branch must
# not inherit another loop's session or findings (#97, now load-bearing).
#
# The identity key is `sha1(branch)-sha1(base_sha)`. It is stable across exactly
# the rewrites the workflow relies on — an amend, a squash, or an in-place rebase
# all keep both the branch name and the base — so those resume the same warm
# session. It CHANGES on the two events that must invalidate a session: a rebase
# onto a moved base (the re-validation ADR-0025 §1 requires — a moved base is a
# different diff, so a fresh key selects a fresh session and the old base's
# session simply lingers unreferenced) and a branch cut from a newer base reusing
# a name (a fresh key, so no stale thread is resumed). The residual — a reused
# name that happens to share a base — is bounded to soft memory carry-over, never
# a wrong ship anchor: the shippable artifact is still tree-anchored (§4), and
# ship matches on `(base, tree)` regardless of which thread produced the verdict.
# The bypass path (no sandbox, or CI) is not the persistent path (see the
# invocation below):
# a cold one-shot that keeps no session and runs no read-only proof, today's
# behaviour preserved. `bypass` is resolved with the loop's paths near the top,
# so the mode dispatch can read it; nothing here creates session state on it.
#
# The disposition record is a per-reviewed-state SNAPSHOT (ADR-0025 §4), named by
# the full anchor `<loop_id>-<persona>-<tree>.md`, so `ship` selects the one
# belonging to the terminal artifact's tree and fails closed if two loops claim
# the same (persona, tree). `snapshot_file` and `prior_snapshot` are resolved
# once loop_id is known, below.

# The loop id is minted with `_mint_id`, defined with the other shared helpers
# near the top (the mode dispatch needs it too): a durable, opaque id recorded in
# the artifact so the ship-time snapshot can be selected by the full anchor
# (loop, persona, base, tree) rather than the tree alone (ADR-0025 §4). Written
# atomically.

# --- Serializing the loop's read-modify-write (issue #142) -------------------
#
# Deciding the loop identity is a READ (the meta) then a WRITE (a minted id, a
# thread wipe), and advancing the loop at the end of a round is another. Each
# individual `mv` is atomic, but two concurrent invocations — `adversarial` and
# `architecture` started at once on a fresh loop — could interleave *between*
# read and write: both see no meta, both mint a different loop_id, and a later
# run then pairs one run's loop_id with the other run's thread, mixing
# differently-anchored records into one disposition ledger. So each phase runs
# inside an exclusive lock on `<loop_key>.lock`, making it one read-modify-write.
#
# The lock is held only across the two filesystem phases, NEVER across the Codex
# call itself: a round runs for minutes, and blocking a sibling persona for the
# whole of it would trade a latent race for a guaranteed stall.
#
# `flock` is used rather than a hand-rolled `mkdir`/`O_EXCL` lockfile precisely
# because of the stale-lock failure mode: an flock lives on an open file
# descriptor, so the kernel releases it when the holder exits — cleanly, on a
# crash, or on SIGKILL. A crashed prior round therefore cannot wedge the review
# loop; the worst it leaves behind is an inert zero-byte lock file. A directory
# or PID lockfile would survive its owner and need a stale-timeout heuristic
# that either wedges or breaks mutual exclusion. `-w` bounds the wait anyway, so
# even a live-but-hung holder produces a loud failure instead of a hang.
#
# The wait is validated BEFORE `flock` sees it, and unconditionally at the point
# it is read, the same way `ship.sh`'s `require_byte_budget` validates a budget.
# A malformed `-w` cannot abort bash arithmetic here — `flock` parses it itself —
# so what it corrupts is the DIAGNOSTIC: `flock` exits non-zero for a reason that
# has nothing to do with contention, and the branch below then reports a timeout
# that never happened and sends the operator hunting for a concurrent review that
# does not exist (issue #221). A leading zero is refused rather than reinterpreted,
# because a shell reads one as octal.
lock_wait="${CODEX_REVIEW_LOCK_WAIT:-60}"
if [[ ! "$lock_wait" =~ ^(0|[1-9][0-9]{0,8})$ ]]; then
    echo "CODEX_REVIEW_LOCK_WAIT must be a non-negative decimal integer of at most" \
        "9 digits with no leading zero (a shell reads a leading zero as octal)," \
        "not '${lock_wait}' — it bounds the seconds spent waiting for the" \
        "review-loop lock" >&2
    exit 2
fi
lock_fd=""
_lock_session() {
    if [[ -n "$lock_fd" || "$serialized" -eq 0 ]]; then
        return 0
    fi
    mkdir -p "$session_dir"
    exec {lock_fd}<>"$lock_file"
    if ! flock -w "$lock_wait" "$lock_fd"; then
        echo "timed out after ${lock_wait}s waiting for the review-loop lock" >&2
        echo "  ${lock_file}" >&2
        echo "another codex-review run is holding it; personas run sequentially in" \
            "one clone (ADR-0015)" >&2
        exit 1
    fi
    return 0
}
_unlock_session() {
    if [[ -z "$lock_fd" ]]; then
        return 0
    fi
    flock -u "$lock_fd"
    exec {lock_fd}>&-
    lock_fd=""
}

# One round per persona per loop AT A TIME, and this one is refused rather than
# queued. Serializing the loop's state is not enough on its own: two rounds of
# the SAME persona write the same artifact path, the same thread file and the
# same snapshot path, so whichever ordering they interleave in, the published
# verdict can end up paired with the other round's dispositions — the terminal
# turn ADR-0025 §4 requires them to belong to. There is nothing to merge and no
# ordering that helps, so the second invocation is refused loudly (the "detect
# and refuse a second concurrent init" half of #142). Held for the whole round,
# Codex call included, and never released explicitly: process exit closes the
# descriptor, so a crashed round leaves nothing to wedge the next one.
#
# The loop lock above is still taken and released around the short state phases,
# so a DIFFERENT persona is only ever blocked for that filesystem work, never for
# the minutes a round spends in Codex.
inflight_fd=""
_claim_persona() {
    if [[ "$serialized" -eq 0 ]]; then
        return 0
    fi
    mkdir -p "$session_dir"
    exec {inflight_fd}<>"$inflight_file"
    if ! flock -n "$inflight_fd"; then
        echo "another '${persona}' review of this loop is already running in this" >&2
        echo "clone; refusing to start a second one. Two rounds of one persona share" >&2
        echo "an artifact, a thread and a disposition snapshot, so they cannot both" >&2
        echo "be recorded. Run personas one at a time (ADR-0015, issue #142)." >&2
        exit 1
    fi
    # The round marker (`--wait`'s answer to "which tree is in flight?") belongs
    # to the round holding this lock, so the previous round's is dropped the
    # moment this one owns it and republished once this round's identity is
    # settled. Dropping it here rather than overwriting it later is what keeps
    # the two from ever being confused: between the two points there is no
    # marker, which `--wait` reads as "in flight, tree not yet published" and
    # waits on — where a stale marker would have read as a different tree and
    # sent the caller away.
    rm -f "$round_file"
    return 0
}

# `serialized` — whether the loop phases can be serialized at all — is resolved
# with the loop's paths near the top, for the same reason `bypass` is: `--wait`
# reasons about the in-flight lock and has to know whether one is taken.

# The loop meta, written atomically. `last_sha` is the ancestry anchor the next
# round continues from, so it is passed explicitly: init publishes the identity
# WITHOUT advancing it, and only a fully recorded round moves it forward.
_write_meta() {
    local last="$1" tmp="${meta_file}.partial.$$"
    printf 'loop_id=%s\nbranch=%s\nbase_sha=%s\nlast_sha=%s\n' \
        "$loop_id" "$branch" "$base_sha" "$last" >"$tmp"
    mv "$tmp" "$meta_file"
}
# No session state on the bypass path — it keeps no thread to resume. loop_id
# stays empty there and is recorded empty, alongside the empty thread_id.
#
# Off the bypass path, decide continuation vs reset. The loop_key
# (sha1(branch)-sha1(base_sha)) is necessary but not sufficient: a branch name
# reused for unrelated work off the *same* base collides on it exactly. So a run
# continues the recorded loop only when the last state that loop reviewed is an
# ancestor of HEAD — i.e. HEAD builds on it. A reused name (its recorded last
# state is unrelated to the new HEAD) fails that test and resets: a fresh loop_id
# and a wipe of any thread and dispositions filed under this key, so no prior
# loop's session, findings, or proposals bleed into this verdict (ADR-0025 §1's
# explicit reset on reuse). An amend, squash, or in-place rebase also fails the
# ancestry test and resets to a fresh cold session — safe, never worse than
# today's cold loop, and such rewrites usually land at the end of a loop rather
# than between the warm rounds this is optimising.
#
# A meta carrying a loop_id but NO last_sha is a loop whose identity has been
# reserved and which has recorded no round yet — an invocation still in flight,
# or one that died before completing a round. That is ADOPTED, not reset: the
# reset exists to detect a branch name reused for unrelated work, and the
# evidence for that is the recorded last state, which such a loop does not have.
# Adopting is what makes two concurrent fresh starts agree on one identity
# (#142); there is also nothing to bleed, since no thread or disposition is
# filed until a round completes. It is not resumed either (the ancestry test
# gates that), so an adopted loop's first recorded round is a cold one.
loop_id=""
recorded_thread=""
if [[ "$bypass" -eq 0 ]]; then
    _claim_persona
    _lock_session
    recorded_last_sha=""
    if [[ -f "$meta_file" ]]; then
        loop_id="$(sed -n 's/^loop_id=//p' "$meta_file")"
        recorded_last_sha="$(sed -n 's/^last_sha=//p' "$meta_file")"
    fi
    if [[ -n "$loop_id" && -n "$recorded_last_sha" ]] &&
        git merge-base --is-ancestor "$recorded_last_sha" "$sha" 2>/dev/null; then
        # Continuing this loop: resume the persona's thread if it has one.
        if [[ -f "$thread_file" ]]; then
            recorded_thread="$(head -n 1 "$thread_file")"
        fi
    elif [[ -n "$loop_id" && -z "$recorded_last_sha" ]]; then
        # Reserved, not yet advanced: adopt the identity as described above.
        :
    else
        # New loop, or a reused/rewritten branch: reset the per-loop identity and
        # clear any session and dispositions filed under it. Threads are keyed by
        # loop_key so are cleared by that; the disposition snapshots are keyed by
        # the OUTGOING loop_id, cleared by it (the new loop_id has none of its own).
        old_loop_id="$loop_id"
        loop_id="$(_mint_id)"
        recorded_last_sha=""
        rm -f "${session_dir}/${loop_key}."*.thread
        [[ -n "$old_loop_id" ]] && rm -f "${disposition_dir}/${old_loop_id}-"*.md
    fi
    # Publish the identity before releasing the lock, so a concurrent invocation
    # reads it instead of minting a rival one. `last_sha` is deliberately carried
    # unchanged (empty on a fresh or reset loop): reserving the identity must not
    # advance the anchor the next round continues from — only a fully recorded
    # round does that, below.
    _write_meta "$recorded_last_sha"
    _unlock_session
fi

# Publish WHICH CONTENT this round is reviewing (issue #1594). The in-flight lock
# says only that a round of this persona is running — the tree is not in its key
# and cannot be, since the lock is claimed before the round has resolved anything
# — so `--wait`, which is always asked about a tree, has nothing to match on
# without this. Written once the identity is settled, so it carries the loop id
# `--start` reports; written atomically, because a poller can arrive between any
# two lines of it; and never removed on exit, because a marker whose round is
# gone is exactly what tells `--wait` the round died rather than finished.
#
# NOT written on the bypass path, which creates no state under `.review/session`
# at all (ADR-0025 §1, pinned by `test_the_bypass_path_keeps_no_session`). That
# path takes no in-flight lock either, so there would be nothing to pair the
# marker with; `--start` refuses there rather than pretending otherwise, and
# `--wait` still reports a *finished* bypass round, because an artifact is found
# by its recorded tree and not by any of this.
_write_round_marker() {
    local tmp="${round_file}.partial.$$"
    mkdir -p "$session_dir"
    printf 'pid=%s\npersona=%s\nbranch=%s\nbase_sha=%s\nsha=%s\ntree=%s\n' \
        "$$" "$persona" "$branch" "$base_sha" "$sha" "$tree" >"$tmp"
    # `start_token` is set by `--start` and empty for a foreground round, which is
    # why `--start` requires a MATCH rather than merely a non-empty value: an
    # unrelated foreground round must not satisfy a start's confirmation either.
    printf 'loop_id=%s\nstarted_at=%s\nlog=%s\nstart_token=%s\n' \
        "$loop_id" "$(date +%s)" "${CODEX_REVIEW_DETACHED_LOG:-}" \
        "${CODEX_REVIEW_START_TOKEN:-}" >>"$tmp"
    mv "$tmp" "$round_file"
}
if [[ "$bypass" -eq 0 ]]; then
    _write_round_marker
fi

# The disposition snapshot for this reviewed state, and the most recent snapshot
# from an earlier round of this same loop+persona. The prior snapshot is what a
# new round both re-injects (mechanism b) and carries forward from (so a finding
# retired in an earlier round stays visible in this state's snapshot). Empty on
# the bypass path (no loop_id, no dispositions).
snapshot_file=""
prior_snapshot=""
if [[ "$bypass" -eq 0 && -n "$loop_id" ]]; then
    snapshot_file="${disposition_dir}/${loop_id}-${persona}-${tree}.md"
    prior_round=-1
    shopt -s nullglob
    for _snap in "${disposition_dir}/${loop_id}-${persona}-"*.md; do
        [[ "$_snap" == "$snapshot_file" ]] && continue
        _r="$(sed -n 's/.* round=\([0-9][0-9]*\).*/\1/p' <(head -n 1 "$_snap"))"
        [[ -n "$_r" ]] || _r=0
        if [[ "$_r" -gt "$prior_round" ]]; then
            prior_round="$_r"
            prior_snapshot="$_snap"
        fi
    done
    shopt -u nullglob
fi

# The effective sandbox for a completed round, read from Codex's own session
# rollout (`$CODEX_HOME/sessions/.../rollout-*-<thread_id>.jsonl`). Every round's
# `turn_context` records the sandbox policy it actually ran under, so read-only is
# *proven from Codex's record*, not assumed from the flags we passed — which is
# what the driver must show, since a resume takes no `-s` and still honours a
# widening `$CODEX_HOME/config.toml`. The newest `turn_context` is this round's.
# Empty output (rollout missing or unparseable) is treated as unproven and fails
# closed by the caller.
_effective_sandbox() {
    local tid="$1" sess
    [[ -n "$tid" ]] || return 0
    sess="$(find "${codex_home}/sessions" -type f -name "*${tid}*.jsonl" 2>/dev/null |
        sort | tail -1)"
    [[ -n "$sess" && -f "$sess" ]] || return 0
    grep -E '"type":[[:space:]]*"turn_context"' "$sess" | tail -1 |
        sed -nE 's/.*"sandbox_policy":[[:space:]]*\{[[:space:]]*"type":[[:space:]]*"([^"]*)".*/\1/p'
}

# --- What the reviewer is reading (ADR-0020 §1) ------------------------------
#
# Adversarial review applies a code rubric, and applied to prose its findings
# about illustrative snippets are noise: a fenced block in an ADR is an example
# for a human operator, and "no error handling" or "untested" is not a defect in
# one. The qualification goes *here*, in the per-run preamble, rather than in a
# rubric or in docs/review/guide.md: those are standing contracts, true of every
# change, and editing one would apply this unconditionally — including to the
# changes where it is false. What this particular diff is, is per-run data.
#
# The classification is by path, and the exemption is stated per *block*, not
# per file. A fenced block can BE the decision — ADR-0016 defines the
# ToolRegistry Protocol in one — and a prose file routinely carries both kinds.
#
# Only `.md` and `.rst` count as prose. `.txt` is deliberately excluded: this
# repository's documentation is Markdown, while a `.txt` is as likely to be
# machine-consumed (a requirements list, a test fixture) as read. The two
# misclassifications are not symmetric — calling prose "code" costs a few noisy
# findings, calling code "prose" hands it an exemption from exactly the scrutiny
# it needs — so the split fails toward strict.
#
# Read NUL-delimited with `core.quotePath=false`, not as newline-separated text.
# Under git's default `quotePath=true` a non-ASCII path is emitted quoted and
# octal-escaped — `docs/café.md` becomes `"docs/caf\303\251.md"` — and the
# trailing quote defeats a `\.(md|rst)$` test, so the file would be classified
# as machine-consumed and silently lose the prose qualification. NUL delimiting
# also handles a path containing a newline, which no line-based read can.
#
# Classification is then a glob rather than a regex, since there is no longer a
# text stream to match against.
mapfile -d '' -t changed_paths < <(
    git "${_diff_opts[@]}" diff --no-color --ignore-submodules=none --no-ext-diff --no-textconv -z --name-only "${base_sha}...${content_sha}"
)

# One list item per path. Reading NUL-delimited keeps a path with a newline in
# it whole as one array element, but printing it raw would still put its second
# line into the prompt as *structure* rather than as a filename — one path
# rendering as two list items, neither of which exists. Escaped only when there
# is a control character to escape, so an ordinary path — a non-ASCII one
# included — is shown exactly as it appears on disk.
#
# This is a legibility fix, not a security boundary. The diff itself is handed
# to the reviewer verbatim a few lines below, so anyone who can commit a file
# can already put arbitrary text in front of it; the path is not a privileged
# channel and treating it as one would be theatre.
_render_path() {
    case "$1" in
    *[$'\n\t\r']*) printf -- '- `%s` (control characters escaped)\n' "$(printf '%q' "$1")" ;;
    *) printf -- '- `%s`\n' "$1" ;;
    esac
}

prose_paths=()
other_paths=()
for changed_path in "${changed_paths[@]}"; do
    case "$changed_path" in
    *.md | *.rst) prose_paths+=("$changed_path") ;;
    *) other_paths+=("$changed_path") ;;
    esac
done

# Writes the round's prompt to `$prompt`. With a non-empty, non-blank injection
# file as $1, the recorded prior-round dispositions are prepended (mechanism b,
# ADR-0025 §1) so a cold round that lost the warm session still sees what was
# already raised and answered. Round 1 and every resumed round pass nothing.
_write_prompt() {
{
    if [[ -n "${1:-}" && -s "${1:-}" ]]; then
        cat "$1"
        echo
    fi
    cat "$rubric"
    echo
    echo "## Change under review"
    echo
    echo "Review ONLY the committed diff below (${content_sha} vs ${base}). You may read full"
    echo "files in the repo for context, but do not modify anything. Output exactly the"
    echo "ranked findings and verdict from docs/review/guide.md."
    echo
    echo "### What these paths are"
    echo
    if [[ ${#prose_paths[@]} -gt 0 ]]; then
        echo "**Prose** — documentation read by a human operator, not executed or tested:"
        echo
        for p in "${prose_paths[@]}"; do _render_path "$p"; done
        echo
    fi
    if [[ ${#other_paths[@]} -gt 0 ]]; then
        echo "**Code, scripts, config, and tests** — machine-consumed, and judged as such:"
        echo
        for p in "${other_paths[@]}"; do _render_path "$p"; done
        echo
    fi
    if [[ ${#prose_paths[@]} -gt 0 ]]; then
        cat <<'PROSE'
In the prose files above, a fenced code block is by default **illustrative**: an
example shown to a human reader, not a program this repository runs, ships, or
tests. Judge such a block on whether it would **mislead the reader who follows
it** — a command that does not work, a wrong path or flag, a claim the
repository contradicts. Do **not** judge it for runtime correctness, error
handling, edge cases, concurrency, or test coverage, and do not ask for tests
on it. Findings of that kind on an illustrative snippet are noise; drop them.

**This exemption does not extend to a normative snippet.** Where a fenced block
*states a contract the repository will implement against* — a Protocol or type
definition, an interface signature, a schema, a required file format or
provenance line, a rule stated as the decision itself — the snippet **is** the
decision, and its internal validity is the subject of the review. Judge it as
strictly as you would the same text in a source file: correctness, internal
consistency, completeness, and whether an implementation could satisfy it.
ADR-0016 defines the `ToolRegistry` Protocol in exactly such a block.

Decide this **per block, not per file**: one document can carry both kinds, and
which one a block is depends on whether something is meant to be built against
it. If a block's status is genuinely ambiguous, review it as normative and say
that you did.
PROSE
        echo
    fi
    echo '```diff'
    printf '%s\n' "$diff"
    echo '```'
} >"$prompt"
}

# Re-injects the most recent prior snapshot into $1 (mechanism b), with a header
# telling the reviewer these are its own prior findings, not to be blindly
# re-raised (a warm re-raise past a seen rejection is a deliberate signal the ADR
# leaves un-suppressed). The snapshot already carries retired findings, so the
# reviewer sees the full disposition history, not just the last round.
_render_dispositions() {
    {
        echo "## Prior findings of THIS review (re-injected — the live session was unavailable)"
        echo
        echo "You have already reviewed earlier states of this same change in this review"
        echo "loop. Below are the findings you raised and their current disposition. Do NOT"
        echo "blindly re-raise a finding marked retired or already answered — engage it or"
        echo "leave it retired. You MAY re-raise a finding you still hold after reading the"
        echo "history; that is a deliberate, informed signal, not noise."
        echo
        cat "$prior_snapshot"
    } >"$1"
}

# A stable, unique id for a finding: its text with markdown and case flattened to
# an alnum key, hashed. Stable across reformatting of the same claim, distinct
# across different claims (ADR-0025 §4's id uniqueness/stability). The leading
# list enumerator (`1.`, `2)`, …) is dropped first, so the same finding keeps its
# id when its rank shifts between rounds. The WHOLE key is hashed — never a
# prefix — so two long findings sharing an opening (a shared reproduction
# preamble, say) do not collide and silently drop one. Reads stdin.
_finding_id() {
    local key
    key="$(tr -d '*#`_>~' | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' ' ' |
        sed 's/^ *//; s/^[0-9][0-9]* //; s/ *$//')"
    printf '%s-%s' "$persona" "$(printf '%s' "$key" | sha1sum | cut -c1-12)"
}

# Writes the per-finding disposition snapshot for this reviewed state (ADR-0025
# §4). This round's findings — parsed from the review body — are recorded status
# `open`; any finding present in the prior snapshot but absent now is carried
# forward status `retired` (Codex's own reassessment: it stopped raising it), so
# the snapshot for the terminal tree is self-contained and `ship` can render the
# verdict-changing history from it alone. Each finding block is delimited so the
# renderer can bound, select, and secret-scan it. Written atomically.
_write_snapshot() {
    [[ -n "$snapshot_file" ]] || return 0
    mkdir -p "$disposition_dir"
    local work
    work="$(mktemp -d -t "codex-snap-${persona}.XXXXXX")"

    # The review body without its trailing verdict line (validated present
    # already), so the verdict is not folded into the last finding block.
    awk 'NF{last=NR} {l[NR]=$0} END{for(i=1;i<=NR;i++) if(i!=last) print l[i]}' \
        "$out" >"${work}/body"
    # Split into finding blocks at each TOP-LEVEL ranked list item ("1.", "2)",
    # …). Markdown treats 0–3 leading spaces as top-level and 4+ as nested, so
    # that is the split rule: a finding's own indented reproduction steps stay
    # part of it, while a top-level list a reviewer happens to indent a couple of
    # spaces still splits. Text before the first item (a preamble) is discarded.
    awk -v dir="$work" '
        /^ {0,3}[0-9]+[.)]/ { n++; f=sprintf("%s/cur-%04d", dir, n) }
        n>0 { print >> f }
    ' "${work}/body"
    # A review the reviewer did not format as a ranked list yields no blocks
    # above. Rather than silently lose it (a lost finding is exactly what §4
    # forbids), record the whole body as one finding.
    if ! compgen -G "${work}/cur-*" >/dev/null; then
        cp "${work}/body" "${work}/cur-0001"
    fi

    local -A cur_text=() cur_sev=()
    local -a cur_order=()
    local bf id sev
    shopt -s nullglob
    for bf in "${work}"/cur-*; do
        id="$(_finding_id <"$bf")"
        [[ -n "${cur_text[$id]:-}" ]] && continue
        # `|| true`: no severity word is not an error, and a failing grep in this
        # bare assignment would trip `set -e` (the pipeline fails under pipefail).
        sev="$(grep -m1 -oiE 'blocker|major|minor' "$bf" | tr '[:upper:]' '[:lower:]' || true)"
        [[ -n "$sev" ]] || sev="unknown"
        cur_order+=("$id")
        cur_sev["$id"]="$sev"
        # Escape the HTML-comment markers so a finding that quotes `<!-- ... -->`
        # (a review OF this very script does) cannot be mistaken for a finding
        # header or terminator and truncate the record. Escaped once, here, so a
        # retired finding carried forward from a prior snapshot is not re-escaped;
        # GitHub renders the entities back to the literal markers.
        cur_text["$id"]="$(_escape_markers <"$bf")"
    done
    shopt -u nullglob

    local snapshot_tmp="${snapshot_file}.partial.$$"
    {
        echo "<!-- snapshot loop_id=${loop_id} persona=${persona} base_sha=${base_sha}" \
            "tree=${tree} sha=${sha} round=${round} verdict=${last_line} -->"
        for id in "${cur_order[@]}"; do
            local first="$round"
            local prior_first
            prior_first="$(_snapshot_field "$prior_snapshot" "$id" first_round)"
            [[ -n "$prior_first" ]] && first="$prior_first"
            _emit_finding "$id" "${cur_sev[$id]}" open "$first" "$round" "${cur_text[$id]}"
        done
        # Findings from the prior snapshot that this round did not raise: retired.
        local pid psev pfirst plast
        while IFS=$'\t' read -r pid psev pfirst plast; do
            [[ -n "$pid" ]] || continue
            [[ -n "${cur_text[$pid]:-}" ]] && continue
            _emit_finding "$pid" "$psev" retired "$pfirst" "$plast" \
                "$(_snapshot_text "$prior_snapshot" "$pid")"
        done < <(_snapshot_ids "$prior_snapshot")
    } >"$snapshot_tmp"
    mv "$snapshot_tmp" "$snapshot_file"
    rm -rf "$work"
}

# Neutralises the HTML-comment framing markers in finding text so payload can
# never be read as structure. GitHub renders the entities back to `<!--`/`-->`.
# Applied once, when a finding is first parsed (not on carry-forward).
_escape_markers() {
    sed 's/<!--/\&lt;!--/g; s/-->/--\&gt;/g'
}

# Emits one finding block: a machine header the renderer parses, then the
# finding text (its markers already escaped at parse time), then a terminator.
_emit_finding() {
    echo "<!-- finding id=${1} severity=${2} status=${3} first_round=${4} last_round=${5} -->"
    printf '%s\n' "$6"
    echo "<!-- /finding -->"
}

# The `id<TAB>severity<TAB>first_round<TAB>last_round` of every finding in a
# snapshot file, one per line. Empty when the file is missing.
_snapshot_ids() {
    [[ -n "$1" && -f "$1" ]] || return 0
    sed -n 's/.*<!-- finding id=\([^ ]*\) severity=\([^ ]*\) status=[^ ]* first_round=\([^ ]*\) last_round=\([^ ]*\) -->.*/\1\t\2\t\3\t\4/p' "$1"
}

# One header field of a specific finding in a snapshot file.
_snapshot_field() {
    [[ -n "$1" && -f "$1" ]] || return 0
    sed -n "s/.*<!-- finding id=${2} .*${3}=\\([^ ]*\\).*/\\1/p" "$1" | head -n 1
}

# The verbatim text of a specific finding in a snapshot file (between its header
# and terminator).
_snapshot_text() {
    [[ -n "$1" && -f "$1" ]] || return 0
    awk -v id="$2" '
        $0 ~ ("<!-- finding id=" id " ") { grab=1; next }
        grab && /<!-- \/finding -->/ { grab=0 }
        grab { print }
    ' "$1"
}

# Unset by default, so local runs keep using the Codex CLI's own default model.
# CI pins this (CODEX_REVIEW_MODEL in codex-review.yml) so the reviewer model is
# an explicit, deliberate choice there rather than whatever the pinned CLI
# version happens to default to.
model_args=()
if [[ -n "${CODEX_REVIEW_MODEL:-}" ]]; then
    model_args=(-m "$CODEX_REVIEW_MODEL")
fi

# On the bypass path (detected above) Codex's own bubblewrap sandbox is skipped:
# in CI the runner is already an ephemeral, externally-sandboxed environment where
# bwrap cannot set up its network namespace ("bwrap: loopback: Failed
# RTM_NEWADDR"), which breaks every file read and degrades the review to an
# apology — the exact case --dangerously-bypass-approvals-and-sandbox documents.
# The review loop is local (ADR-0015 §1), so this bypass does not reach a
# persistent session — a persistent review never widens its sandbox (ADR-0025 §1).
# When it applies, this is a cold one-shot exactly as before: no thread recorded,
# no resume, no read-only proof (the sandbox is deliberately off).

# The injection budget bounds `diff + re-injected dispositions` (ADR-0025 §1's
# graceful-degradation floor): past it, mechanism (b) would not fit, so the round
# drops to a plain cold review of the diff rather than a truncated injection.
#
# Validated before the `$(( ))` below reads it, for the reason ship.sh's
# `require_byte_budget` states at length: `$(( ))` evaluates its operand as an
# ARITHMETIC EXPRESSION, so `not-a-number` or `1/0` aborts inside the shell
# instead of refusing, and a negative value silently forces the degradation floor
# under a message blaming the dispositions for the operator's typo. A leading zero
# is rejected for the reason stated there too: bash reads it as octal, so `08` is
# a syntax error that leaves the guard FALSE rather than refusing, and `0500000`
# silently means 163840. Spelled out here rather than shared: the two scripts have
# no common library, and the pair that share bytes do so under an explicitly-marked
# block with a test enforcing it — a third such contract for a few lines is not
# worth its weight.
inject_budget="${CODEX_REVIEW_INJECT_BUDGET:-500000}"
if [[ ! "$inject_budget" =~ ^(0|[1-9][0-9]{0,8})$ ]]; then
    echo "CODEX_REVIEW_INJECT_BUDGET must be a non-negative decimal integer of at" \
        "most 9 digits with no leading zero (bash reads a leading zero as octal)," \
        "not '${inject_budget}' — it bounds the bytes of diff plus re-injected" \
        "dispositions one round may carry (ADR-0025 §1)" >&2
    exit 2
fi
diff_bytes="$(printf '%s' "$diff" | wc -c)"

# The thread this round actually ran on, recorded afterwards so the next round
# resumes it. Empty on the bypass path (no persistence).
round_thread=""

# What `codex exec --json` said when it failed, and why nothing said it before.
#
# Under `--json` the CLI puts its ENTIRE event stream on stdout — `thread.started`,
# the items, and the `error`/`turn.failed` events that carry a failure — and
# leaves stderr EMPTY. Both invocations below redirect that stdout into `$stream`,
# a `mktemp` file the EXIT trap deletes. So a round that failed for a reason Codex
# stated perfectly clearly wrote the reason into a file nobody reads and then
# deleted it; and the fresh-start call was a bare command under `set -e`, which
# left the script with nothing of its own to say either. Detached, the log then
# ends at "Running Codex …" with no error line at all — which is exactly what
# issues #1674 and #1675 record, twice each, as a round that "died without saying
# why", and what sent both lanes to diagnose a Codex that was healthy.
#
# Measured, not inferred: on codex-cli 0.146.0, `codex exec --json` given a model
# the account cannot use exits 1 with **zero bytes on stderr** and the 400 on
# stdout, as `{"type":"error",…}` and `{"type":"turn.failed",…}`.
#
# This diagnoses and does not rescue. A failed round is still a failed round, no
# retry is attempted, and `--wait` still answers exit 4 about it — what changes is
# that the log it prints as evidence now names the reason.
_report_codex_failure() {
    local what="$1" status="$2"
    echo "codex exec (${what}) exited ${status}." >&2
    if [[ -s "$stream" ]]; then
        echo "  Its --json event stream ends (stdout, where codex puts failures):" >&2
        tail -n 5 "$stream" | cut -c 1-400 | sed 's/^/  | /' >&2
    else
        echo "  It wrote no event stream at all, so it failed before starting a" >&2
        echo "  turn — an auth or config failure, or a process killed outright." >&2
    fi
}

if [[ "$bypass" -eq 1 ]]; then
    _write_prompt ""
    echo "Running Codex '${persona}' review of HEAD vs '${base}' (bypass, cold)…" >&2
    # -o captures just the final review; progress streams to stderr.
    #
    # The status is captured rather than left to `set -e` for the reason
    # `_report_codex_failure` gives: an exit that says nothing is one a detached
    # round cannot be diagnosed from. This path carries no `--json`, so its output
    # is already on stderr and there is no stream to quote — only the status is
    # missing, and only the status is added.
    bypass_status=0
    codex exec --dangerously-bypass-approvals-and-sandbox "${model_args[@]}" \
        -o "$out" - <"$prompt" >&2 || bypass_status=$?
    if [[ "$bypass_status" -ne 0 ]]; then
        echo "codex exec (bypass, cold) exited ${bypass_status}; its output is above." >&2
        exit 1
    fi
else
    # Enforced read-only on every round, proven from Codex's own record below.
    # Resume takes no `-s`, and a widening `$CODEX_HOME/config.toml` is honoured
    # over a bare invocation, so read-only is forced with `-c sandbox_mode` — a
    # driver-set `-c` overrides config.toml, on both a fresh start and a resume.
    # `-s read-only` is kept on the fresh start too: it is redundant with the
    # `-c`, but it is the flag the CLI documents for the initial sandbox and it
    # keeps the start invocation self-describing. Neither the sandbox-bypass flag
    # nor any widening `-s`/`-c sandbox_mode` override is ever passed here.
    ro_config=(-c sandbox_mode="read-only")
    used_resume=0

    if [[ -n "$recorded_thread" ]]; then
        _write_prompt ""
        echo "Resuming Codex '${persona}' session ${recorded_thread:0:12} vs '${base}'" \
            "(read-only)…" >&2
        # `--json` puts the event stream (carrying thread.started) on stdout,
        # captured to $stream; Codex's human progress stays on stderr. `-o` still
        # writes just the final review to $out.
        resume_status=0
        codex exec resume "$recorded_thread" --json "${ro_config[@]}" \
            "${model_args[@]}" -o "$out" - <"$prompt" >"$stream" || resume_status=$?
        if [[ "$resume_status" -eq 0 ]]; then
            used_resume=1
            round_thread="$recorded_thread"
        else
            # Resume is unavailable — a pruned session, an ephemeral host. Not a
            # failure: fall through to a fresh read-only session with the prior
            # dispositions re-injected (mechanism b), the ADR-0025 §1 fallback.
            #
            # Reported all the same, and BEFORE the fall-through, because the
            # fresh start below truncates `$stream` — so this is the only moment
            # the reason exists. A pruned session and a refused request degrade
            # identically here, and telling them apart is the difference between
            # "the fallback worked as designed" and "the service is refusing this
            # loop", which is the pair issue #1675 could not distinguish.
            echo "resume unavailable; starting a fresh read-only session with prior" \
                "findings re-injected" >&2
            _report_codex_failure "resume ${recorded_thread:0:12}" "$resume_status"
        fi
    fi

    if [[ "$used_resume" -eq 0 ]]; then
        # A fresh start: round 1 of this loop, or a degraded resume. Re-inject the
        # recorded dispositions when they exist and `diff + injection` fits the
        # budget; past the budget, drop to a plain cold review of the diff (the
        # floor) rather than truncating — the dispositions stay on record, never
        # silently lost, and a re-raise then costs at most one round.
        inject=""
        if [[ -n "$prior_snapshot" && -s "$prior_snapshot" ]]; then
            _render_dispositions "$inject_tmp"
            inject_bytes="$(wc -c <"$inject_tmp")"
            if [[ $((inject_bytes + diff_bytes)) -le "$inject_budget" ]]; then
                inject="$inject_tmp"
            else
                echo "prior findings + diff (${inject_bytes}+${diff_bytes} bytes) exceed the" \
                    "injection budget (${inject_budget}); dropping to a plain cold review of" \
                    "the diff (the degradation floor). The dispositions remain recorded in" \
                    "${prior_snapshot}." >&2
            fi
        fi
        _write_prompt "$inject"
        echo "Running Codex '${persona}' review of HEAD vs '${base}' (read-only, fresh" \
            "session)…" >&2
        fresh_status=0
        codex exec --json -s read-only "${ro_config[@]}" "${model_args[@]}" \
            -o "$out" - <"$prompt" >"$stream" || fresh_status=$?
        if [[ "$fresh_status" -ne 0 ]]; then
            _report_codex_failure "the fresh read-only session" "$fresh_status"
            exit 1
        fi
        round_thread="$(grep -o '"thread_id":"[^"]*"' "$stream" | head -1 |
            sed 's/.*:"//; s/"$//')"
    fi

    # Read-only proven, not assumed (ADR-0025 §4): read the sandbox Codex actually
    # ran this round under from its session rollout, and fail closed unless it is
    # read-only. Empty means the rollout could not be found or parsed — unproven,
    # which is not the same as read-only, so it fails closed too. This holds even
    # against a widening config.toml, since the `turn_context` records the
    # effective policy after all config layering.
    effective_sandbox="$(_effective_sandbox "$round_thread")"
    if [[ "$effective_sandbox" != "read-only" ]]; then
        echo "refusing to record: could not prove the review ran read-only" >&2
        echo "effective sandbox for thread ${round_thread:-<unknown>} was" \
            "'${effective_sandbox:-unreadable}' (a widening \$CODEX_HOME/config.toml, a" \
            "bypass flag, or a missing session rollout can cause this)" >&2
        exit 1
    fi
fi

# Pinning the diff is not enough on its own: Codex reads files from the working
# tree as it goes, so if the checkout moved *during* the review — another commit,
# a stray edit — it reasoned about a tree that is not the SHA this artifact would
# name. Re-check both, and record nothing if either changed. A missing artifact
# costs a re-run; a false one is evidence for code nobody reviewed.
if [[ "$(git rev-parse HEAD)" != "$sha" || -n "$(git status --porcelain)" ]]; then
    echo "the checkout changed while the review was running; not recording it" >&2
    echo "HEAD was ${sha}, now $(git rev-parse HEAD); re-run on a settled tree" >&2
    exit 1
fi

# An artifact is evidence that a review happened, so an empty one is worse than
# none: ship.sh checks that the file exists, and would post silence as though it
# were a clean review. Codex can exit 0 having written nothing (a dropped
# connection, a refusal); fail loudly instead of recording that.
if [[ ! -s "$out" ]] || ! grep -q '[^[:space:]]' "$out"; then
    echo "codex produced an empty review; not recording an artifact" >&2
    # A zero exit with an empty review is the other half of the same illegibility:
    # `--json` can carry a `turn.failed` and still exit 0, and that event is on the
    # stdout this script routes into a temp file it is about to delete. Quoted here
    # for the same reason it is quoted on a non-zero exit.
    if [[ "$bypass" -eq 0 && -s "$stream" ]]; then
        echo "its --json event stream ends (stdout, where codex puts failures):" >&2
        tail -n 5 "$stream" | cut -c 1-400 | sed 's/^/  | /' >&2
    fi
    echo "re-run: scripts/codex-review.sh ${persona} ${base}" >&2
    exit 1
fi

# Non-empty is a weak test: a refusal or a timeout message ("I'm unable to
# review this repository") is prose, and would be recorded and posted as though
# it were a review. The rubric requires a closing one-line verdict
# (docs/review/guide.md), so demand exactly that.
#
# Matched against the *last non-blank line*, not anywhere in the body: a
# substring search accepts prose that merely mentions the words, e.g. "I cannot
# provide a verdict or APPROVE this change". Markdown emphasis is stripped
# first, since the reviewer writes "**Verdict: X**", "Verdict: X" and
# "VERDICT: X" interchangeably.
#
# The `Verdict:` label is optional, because the contract this check enforces
# does not require it. docs/review/guide.md asks the reviewer to "end with a
# one-line verdict: BLOCK, APPROVE WITH NITS, or APPROVE", and the preamble
# tells it to output the verdict "from docs/review/guide.md" — so a bare
# `APPROVE WITH NITS` is a conforming review. Demanding the label made this
# check stricter than the rubric it cites and discarded conforming reviews as
# refusals, at the cost of a full run each time (issue #120).
#
# The guard is not weakened by it. What it exists to catch is a refusal or a
# timeout — "I'm unable to review this repository" — and those do not end in a
# line that is exactly a verdict word. Anchoring to the whole line is what does
# the work here; the label never did.
#
# Which is why the label's separator is `[^[:alnum:]]*` rather than an
# enumeration. The reviewer writes `Verdict: X`, `Verdict — X`, `Verdict – X`
# and `Verdict - X` interchangeably, and demanding a colon discarded the three
# dash spellings as refusals — a full run and the whole findings body lost each
# time, presenting as the reviewer refusing (issue #555). Enumerating the dashes
# instead would only move the next unlisted separator into the same trap, and a
# bracket class of multibyte dashes is not even locale-safe: under `LC_ALL=C`,
# `[—–-]` degrades to the individual UTF-8 bytes and stops matching an em dash
# at all. Accepting any non-alphanumeric run costs nothing the guard was relying
# on, since the whole-line anchor and the exact verdict word are what reject a
# refusal.
#
# `LC_ALL=C` on the match is what makes that class mean the same thing
# everywhere, and it is not optional. Character classes are locale-dependent: in
# a single-byte non-ASCII locale such as `en_US.ISO-8859-1`, an em dash's
# leading UTF-8 byte 0xE2 decodes as a letter and *is* `[[:alnum:]]`, so
# `[^[:alnum:]]*` cannot consume it and the dash verdicts are discarded again —
# the same bug, reappearing only on machines nobody tested on. These scripts pin
# no ambient locale, so the match pins its own. Matching bytes is the right
# choice here: the verdict words are ASCII, and the separator is only ever
# skipped over, never interpreted.
last_line="$(_last_verdict_line "$out")"
if ! LC_ALL=C grep -qiE '^(verdict[^[:alnum:]]*)?(block|approve with nits|approve)\.?$' <<<"$last_line"; then
    echo "codex output does not end in a verdict; not recording it as a review" >&2
    echo "this is usually a refusal or a timeout rather than a review" >&2
    echo "last line was: ${last_line}" >&2
    exit 1
fi

# A verdict and nothing else is not a review either. The rubric's own
# anti-patterns say so: "No rubber-stamping. 'Looks good' with no scrutiny is a
# failure. If you genuinely find nothing, say so explicitly and state what you
# checked." So an output whose only non-blank line is the verdict has skipped
# the part that carries the value.
#
# This check is new rather than moved. Dropping the `Verdict:` label above let a
# bare `APPROVE` through, which the label had been excluding by accident — but
# `Verdict: APPROVE` alone always passed, so the hole predates that and merely
# widened. Closed for both forms, since closing it for one would leave the rule
# depending on which spelling the reviewer happened to pick.
body_lines="$(grep -c -v '^[[:space:]]*$' "$out" || true)"
if [[ "$body_lines" -lt 2 ]]; then
    echo "codex returned a verdict with no review body; not recording it" >&2
    echo "the rubric requires ranked findings, or an explicit statement of what" >&2
    echo "was checked when there are none (docs/review/guide.md)" >&2
    exit 1
fi

# Record the review against the content it covers (ADR-0020 §3, superseding
# ADR-0015 §1's commit anchor). `just ship` refuses to report a review whose
# recorded base and tree do not match the PR's current merge base and HEAD tree,
# which turns "did you review the current code?" from a matter of care into a
# check. The artifact is git-ignored: evidence for the local ship step, not
# history.
#
# THE ARTIFACT IS NAMED BY THE ANCHOR IT IS SELECTED BY (ADR-0027 §6). The name
# used to carry the commit, which stopped being what the artifact is selected by
# when ADR-0020 §3 re-anchored acceptance onto content — and issue #149 is what
# that vestige cost: two runs of one SHA against different bases collided on one
# path, so the older-base run finishing last replaced the current-base artifact
# and `ship` rejected a valid review as stale. Carrying every field the
# acceptance rule selects on — the loop identity (ADR-0025 §4), the persona, the
# base and the tree — makes that collision UNCONSTRUCTIBLE rather than unlikely:
# two runs the rule would distinguish can no longer occupy one path. This is the
# same mechanism as the patch identity, not a second one; once selection is by
# content, naming by content is the identity function.
#
# `noloop` stands in for a run with no loop identity — the bypass path (no
# sandbox, or CI), which keeps no session — so the field is never empty and the
# segments never collapse.
# The name is an identity and nothing parses it: `ship` reads the persona from
# the recorded provenance field, never off the filename.
mkdir -p "$review_dir"
artifact="${review_dir}/${loop_id:-noloop}-${persona}-${base_sha}-${tree}.md"
# base_sha was pinned before the diff (above), not re-resolved here: ship.sh
# compares it against the PR's real base, so a review run against a narrower or
# since-moved base — which still produces a correctly-named artifact — cannot
# pass as review of the whole PR diff.
#
# Written to a temporary file and renamed into place, never streamed straight
# to the final path: an interrupt partway through the write would otherwise
# leave a truncated artifact carrying a valid name and base_sha, which ship
# would accept as proof of a completed review. `mv` within one directory is
# atomic, so the artifact either exists whole or not at all.
#
# The aggregate (§2) is recorded on the same line so `just ship` can render it
# into the PR comment: the human at merge then sees the same round count and
# churn ratio the author saw, which is the whole point of printing it.
artifact_tmp="${artifact}.partial.$$"
{
    # Both binary counts are recorded, not just the one in the final diff. §2's
    # requirement is that the reviewer at merge holds the aggregate the author
    # held, and the terminal prints both — so persisting only `net_binary` would
    # drop a caveat the author saw. They come apart for real: a binary added in
    # one commit and reverted in a later one is absent from the net diff while
    # still being unmeasured work the branch did.
    #
    # Each is omitted rather than recorded as 0, so ship renders a caveat only
    # where there is one. `${var:+…}` cannot express that: the counts are the
    # string "0" when empty, which is non-empty and would expand.
    binary_field=""
    if [[ "$net_binary" -gt 0 ]]; then
        binary_field="binary_files=${net_binary} "
    fi
    if [[ "$churn_binary" -gt 0 ]]; then
        binary_field="${binary_field}binary_churn=${churn_binary} "
    fi
    # loop_id and thread_id are recorded for ADR-0025 §4's ship-time snapshot
    # selection by the full anchor (loop, persona, base, tree, terminal turn).
    # thread_id is empty on the bypass path, which keeps no session.
    # patch_id is ADR-0027 §2's coverage anchor across a moved base. Recorded
    # even when empty, so `ship` can tell "this artifact predates the field" from
    # "this range had no trustworthy identity" — both make the moved-base path
    # unavailable, and neither may be read as a match.
    echo "<!-- persona=${persona} base=${base} base_sha=${base_sha} sha=${sha}" \
        "branch=${branch} tree=${tree} patch_id=${patch_id} round=${round}" \
        "loop_id=${loop_id} thread_id=${round_thread}" \
        "net_lines=${net_lines} churn_lines=${churn_lines}" \
        "churn_ratio=${churn_ratio} churn_bound=${churn_bound} commits=${commits}" \
        "${binary_field}${supersedes:+supersedes=${supersedes} }-->"
    cat "$out"
} >"$artifact_tmp"
mv "$artifact_tmp" "$artifact"

# Persist the session and dispositions only on the persistent path — the bypass
# path keeps no thread. Written last, after every validation has passed, so a
# rejected round never advances the loop the next round continues: the meta's
# last_sha (the ancestry anchor above) only moves once a round is fully recorded.
#
# The whole advance is one read-modify-write under the loop lock (#142): re-read
# the meta and refuse to record if the identity this round was anchored to is no
# longer the loop's. That happens when another invocation reset the loop while
# this round was in flight — recording anyway would file this round's thread and
# dispositions under a loop_id no later round will look up, silently orphaning
# them. The review itself is already on disk at `$artifact`; only
# the session advance is refused, and re-running the persona records it cleanly.
#
# The identity is necessary but not sufficient: the anchor must also only ever
# move FORWARD. Two concurrent rounds of the same loop can finish out of order —
# one started at B, another at its descendant C — and the later-finishing older
# round would otherwise rewind last_sha to B and replace the persona's thread
# with its own staler session, so the next round resumes the conversation that
# saw less. The settled-tree check above catches the ordinary shape of this (the
# older round's HEAD has moved under it), but it is a check about the *checkout*,
# not about the loop's state, and it passes if the checkout is put back. So the
# loop guards its own anchor too: the advance requires the recorded state to be
# an ancestor of this round's — "this round builds on what the loop recorded".
# Sequentially this always holds: the meta's last_sha is either empty (a fresh,
# reset, or adopted loop) or the state this round continued from.
if [[ "$bypass" -eq 0 ]]; then
    _lock_session
    current_loop_id=""
    current_last_sha=""
    if [[ -f "$meta_file" ]]; then
        current_loop_id="$(sed -n 's/^loop_id=//p' "$meta_file")"
        current_last_sha="$(sed -n 's/^last_sha=//p' "$meta_file")"
    fi
    if [[ "$current_loop_id" != "$loop_id" ]]; then
        _unlock_session
        echo >&2
        echo "another codex-review run reset this review loop while this round was" >&2
        echo "in flight (loop ${loop_id:0:12} was replaced by ${current_loop_id:0:12})." >&2
        echo "Refusing to record this round's session state under a dead identity." >&2
        echo "Run one persona at a time in a clone (ADR-0015), then re-run this one." >&2
        exit 1
    fi
    if [[ -n "$current_last_sha" ]] &&
        ! git merge-base --is-ancestor "$current_last_sha" "$sha" 2>/dev/null; then
        _unlock_session
        echo >&2
        echo "this review loop has already recorded a newer state (${current_last_sha:0:12})" >&2
        echo "than this round's (${sha:0:12}), so this round finished out of order." >&2
        echo "Refusing to rewind the loop's anchor and session to the older state." >&2
        echo "Run one persona at a time in a clone (ADR-0015), then re-run this one." >&2
        exit 1
    fi
    _write_meta "$sha"
    if [[ -n "$round_thread" ]]; then
        thread_tmp="${thread_file}.partial.$$"
        printf '%s\n' "$round_thread" >"$thread_tmp"
        mv "$thread_tmp" "$thread_file"
    fi
    _write_snapshot
    _unlock_session
fi

echo >&2
echo "===== ${persona} review (HEAD vs ${base}) =====" >&2
echo "(recorded at ${artifact#"${repo_root}/"}, tree ${tree:0:12}, round ${round})" >&2
cat "$out"
