#!/usr/bin/env bash
# Report the local Codex review to the pull request — the merge-readiness step
# (ADR-0015 §1).
#
# Review runs locally now, so the PR record depends on someone pasting it. This
# script is that paste, with the forgettable parts checked rather than trusted:
# it refuses unless a review artifact covers the content the PR head carries. The
# common failure under a paste-it-yourself norm is a review of stale content —
# that one is mechanical.
#
# The anchor used to be the exact commit SHA (ADR-0015 §1). Content is the
# stricter thing to check and the cheaper one to satisfy: a commit that changes
# no reviewed byte — an amended message, a squash, an in-place rebase, a revert
# back to a reviewed tree — no longer forces a fresh round (ADR-0020 §3).
#
# ADR-0027 then separates the two questions that one rule was answering with one
# instrument. COVERAGE — did a review actually read this content? — is what the
# artifact can attest and nothing else can, so it stays here. CURRENCY — does the
# change still hold on today's base? — is what ruff, mypy, lint-imports and
# pytest establish on every rebase and every push, so the review is no longer
# asked to re-certify it. Concretely: where the base has NOT moved, the recorded
# base and tree must both match and that is unchanged; where it HAS moved, an
# artifact still covers HEAD if the reviewed patch's identity is unchanged and
# the move touches none of §3's floor — and the move is then published in full on
# the PR rather than costing a Codex round.
#
# What is *not* relaxed: an adversarial record is still required, the
# architecture lens is still required for a change touching the contract surface,
# and every clause of the moved-base path fails closed.
#
# Deliberately not a pre-push hook: review is a pre-merge step, not a per-push
# one. Gating every push would force a full Codex run per WIP commit, which is
# the fix-per-finding cost pattern ADR-0015 exists to remove.
#
# Usage: scripts/ship.sh
set -euo pipefail

die() {
    echo "ship: $1" >&2
    exit 1
}

command -v gh >/dev/null 2>&1 || die "gh CLI not found on PATH"

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

branch="$(git rev-parse --abbrev-ref HEAD)"
[[ "$branch" == "HEAD" ]] && die "detached HEAD — check out the PR branch first"
[[ "$branch" == "main" ]] && die "on main; ship reports a PR branch's review"

# The review covers the committed diff, so uncommitted work is by definition
# unreviewed — shipping here would report a review of something else. Use
# `status --porcelain`, not `diff --quiet`: an untracked file is unreviewed work
# too, and a pair of diff checks silently passes it.
if [[ -n "$(git status --porcelain)" ]]; then
    die "working tree is dirty (tracked or untracked) — commit or stash first"
fi

sha="$(git rev-parse HEAD)"

# The PR must already show this commit, or the review would name a SHA a reader
# cannot find on the PR.
pr_sha="$(gh pr view --json headRefOid --jq .headRefOid 2>/dev/null || true)"
[[ -z "$pr_sha" ]] && die "no PR found for '${branch}' — open one first (gh pr create)"
if [[ "$pr_sha" != "$sha" ]]; then
    die "PR head is ${pr_sha:0:12} but HEAD is ${sha:0:12} — push first"
fi

# A change to the shared contract surface needs the architecture lens too
# (CONTRIBUTING, "Contract ADRs land before their implementation"). That was
# documented but unenforced, which is precisely the prose-not-mechanism failure
# ADR-0015 exists to correct — so check it here rather than trusting recall.
base_ref="$(gh pr view --json baseRefName --jq .baseRefName 2>/dev/null || true)"
[[ -z "$base_ref" ]] && die "could not resolve the PR's base branch"

# Everything below fetches from `origin`, which is only the PR's base repository
# in a direct-push clone — the model this project uses (ADR-0010, ADR-0015). From
# a fork, `origin` is the fork and origin/<base> is *its* copy of the branch, so
# the range check and the core/ scan would silently validate the wrong diff.
# Refuse rather than build fork support for a workflow nobody here runs: a loud
# stop is recoverable, a quietly-wrong contract check is not.
#
# `isCrossRepository` is a real `gh pr view` field, unlike the `baseRepository`
# this first reached for — which does not exist, so the query failed, the error
# was swallowed, and the check silently never ran. Errors are not suppressed
# here for that reason: a check that cannot run must stop the ship, not wave it
# through.
cross_repo="$(gh pr view --json isCrossRepository --jq .isCrossRepository)" ||
    die "could not determine whether this PR comes from a fork"
if [[ "$cross_repo" == "true" ]]; then
    die "this PR comes from a fork, so origin is not its base repository
     ship assumes origin is the base repo (ADR-0015 clone-per-agent)
     post the review by hand instead"
fi
# Fetch the base so the comparison is against the real merge target, not a
# possibly-stale local ref; FETCH_HEAD is that ref as of this moment.
git fetch --no-tags --quiet origin "$base_ref" ||
    die "could not fetch base '${base_ref}' to check for contract changes"

# Capture the file list before matching, rather than piping git into `grep -q`.
# `grep -q` exits at the first match and closes the pipe; on a diff large enough
# to fill the pipe buffer, git then dies of SIGPIPE and — under `set -o
# pipefail` — the whole pipeline reports failure. The `if` would read that as
# "no core change" and skip the architecture requirement entirely: a fail-open
# on the one check that guards the shared contract surface.
changed_files="$(git diff --name-only "FETCH_HEAD...${sha}")"
core_change=0
if grep -qE '^src/ai_assistant/core/(protocols|types)\.py$' <<<"$changed_files"; then
    core_change=1
fi

# --- Which reviews cover this PR (ADR-0020 §3, as amended by ADR-0027 §2) ----
#
# An artifact is accepted when EITHER:
#
#   (a) its recorded *base* equals this PR's merge base AND its recorded *tree*
#       equals HEAD's tree — ADR-0020 §3 exactly as written, unmodified; or
#   (b) its recorded base is a PROPER ANCESTOR of the merge base, both patch
#       identities are hashable and equal, the base move clears §3's floor, and
#       the drift is published per §4.
#
# Under (a) the two conditions are independent and both load-bearing:
#
#   tree: the content reviewed. A scope cut, a fixup, any real edit changes it,
#         so a review of different content is refused exactly as before. This is
#         what makes the commit SHA safe to stop matching on: an amended message,
#         a squash, an in-place rebase, or a revert back to a reviewed tree
#         changes the commit but not one reviewed byte.
#   base: the left edge of the range. A review run against a narrower base
#         (`just review-codex adversarial HEAD~1`) covers only part of the PR
#         and must still force a fresh review.
#
# The tree comparison is not weakened, it is SCOPED. Under (a) it refuses on any
# changed byte anywhere in the tree, which is strictly stronger than any identity
# computed from a diff, and it is untouched. Under (b) the base itself moved, so
# the whole-repository tree legitimately differs by the base move and a tree
# comparison has nothing to say — content is pinned by the patch identity instead,
# and the base by the floor.
#
# PROPER is the load-bearing word in (b). An equal base is an ancestor of itself,
# so a (b) that admitted equality would let the patch identity govern a case (a)
# already covers, and govern it more weakly: the identity ignores hunk line
# numbers where the tree does not, so in a file with two identical regions,
# moving the reviewed edit from one to the other leaves the identity intact and
# the tree changed. Where the base has not moved, (a) governs and its tree check
# is the whole test.
#
# A recorded base that is NOT an ancestor of the merge base is not drift; it is a
# different history, and fails closed.
expected_base="$(git merge-base FETCH_HEAD "$sha")"
head_tree="$(git rev-parse "${sha}^{tree}")"

# --- The reviewed range's rendering, and its identity (ADR-0027 §2) ----------
#
# THIS BLOCK IS DUPLICATED VERBATIM IN scripts/codex-review.sh AND MUST STAY
# IDENTICAL. One script records the identity and the other recomputes it here, so
# a divergence between the two spellings would not fail loudly — it would compute
# two different identities for one patch and quietly cost a review round every
# time. Same reasoning as `artifact_has_verdict`, duplicated across the pair for
# the same reason.
#
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
# nobody read. The unsafe direction would be an option that strips information
# until two different patches collide, and whitespace is the case that does: §2
# closes it by fixing the `patch-id` flag, not by config.
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
    if ! git "${_diff_opts[@]}" diff --no-color --no-ext-diff --no-textconv --raw --abbrev=40 -z \
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
    git "${_diff_opts[@]}" diff --no-color --no-ext-diff --no-textconv "$1...$2" |
        git patch-id --verbatim | awk 'NR == 1 { print $1 }' || return 0
}
# <<< shared-patch-identity

head_patch_id="$(patch_identity "$expected_base" "$sha")"

# --- The §3 floor ------------------------------------------------------------
#
# One class of base move is invisible to the gate AND changes what a reviewer
# would say. A base move touching any of these invalidates the artifact outright
# — no patch-identity relief, no drift disclosure:
#
#   the contract surface   — a Protocol or type landed on the base breaks no gate,
#                            and changes what the architecture lens would say
#                            about a diff that consumes it or now should;
#   the standing contracts — the rubrics, the guide, the working agreements, and
#                            the review DRIVER, which assembles the prompt: a base
#                            move adding a required instruction there conducts
#                            every later review under different instructions while
#                            touching no document;
#   docs/adr/**            — for EVERY persona. docs/review/guide.md §1 puts the
#                            ADRs at the top of the authority hierarchy for every
#                            reviewer, so a review conducted before a decision was
#                            ratified is a review under a different authority.
#
# `scripts/ship.sh` is deliberately NOT here. The boundary is "what the reviewer
# read", not "what the review loop touches": ship shapes no prompt, it applies
# the acceptance rule, and it applies whatever version of it is on disk at ship
# time. A stale copy of ship cannot exist to be reused.
_is_floor_path() {
    case "$1" in
    src/ai_assistant/core/protocols.py | src/ai_assistant/core/types.py) return 0 ;;
    CLAUDE.md | CONTRIBUTING.md | scripts/codex-review.sh) return 0 ;;
    # A `case` glob is not pathname expansion, so `*` spans `/` and these cover
    # the whole subtree at any depth.
    docs/review/* | docs/adr/*) return 0 ;;
    esac
    return 1
}

# The base move, read into parallel arrays plus a floor verdict.
#
# BOTH ENDPOINTS OF EVERY ENTRY ARE READ, not a single name. A plain
# `--name-only` reports only the *destination* of a detected rename, so a base
# move renaming `docs/review/adversarial.md` out of that tree would clear a floor
# it plainly breaches — the rubric the review was conducted under is gone, and the
# listing never says so. So the comparison is rename-aware and NUL-delimited, a
# floor path appearing as either endpoint is a breach, as is its deletion, and the
# same reading feeds §4's published record: the file set the merge reviewer reads
# is the file set the floor tested.
declare -a drift_status=() drift_src=() drift_dst=()
drift_floor=0
_read_base_move() {
    drift_status=()
    drift_src=()
    drift_dst=()
    drift_floor=0
    local -a rec=()
    # The listing is written to a file whose write is CHECKED, not read through a
    # process substitution, which discards the producer's exit status. `git diff`
    # can fail *after* emitting a prefix — an unreadable blob in a partial clone,
    # a broken pipe — and a truncated listing read as a complete one is the worst
    # available outcome here: it could clear the floor because the breaching path
    # was in the part that never arrived, and publish as "whole" a set that is
    # not. Both are what §§3-4 fail closed against, so any failure is unreadable.
    local listing
    listing="$(mktemp -t ship-drift.XXXXXX)" || return 1
    if ! git -c core.quotePath=false -c color.ui=false -c diff.renameLimit=4000 \
        diff --no-color --no-ext-diff --name-status -M -z "$1" "$2" >"$listing"; then
        rm -f "$listing"
        return 1
    fi
    mapfile -d '' -t rec <"$listing"
    rm -f "$listing"
    local i=0 st s d
    while [[ $i -lt ${#rec[@]} ]]; do
        st="${rec[$i]}"
        case "$st" in
        R* | C*)
            s="${rec[$((i + 1))]:-}"
            d="${rec[$((i + 2))]:-}"
            i=$((i + 3))
            ;;
        *)
            s="${rec[$((i + 1))]:-}"
            d=""
            i=$((i + 2))
            ;;
        esac
        # A record running off the end means the listing could not be parsed, and
        # an unparsed drift set cannot be published whole. Fail closed.
        if [[ $i -gt ${#rec[@]} ]]; then
            return 1
        fi
        drift_status+=("$st")
        drift_src+=("$s")
        drift_dst+=("$d")
        if _is_floor_path "$s"; then
            drift_floor=1
        fi
        if [[ -n "$d" ]] && _is_floor_path "$d"; then
            drift_floor=1
        fi
    done
    return 0
}

# --- Publishing a pathname (ADR-0027 §4, issue #165) -------------------------
#
# §4 requires the drift set to be published WHOLE. Reading it safely is not the
# same as rendering it safely: git permits a pathname containing a newline, and
# Markdown/HTML delimiters. A line-oriented renderer would emit `docs/adr/a<LF>b.md`
# as two apparent paths, or emit a name that alters the comment's structure — and
# the merge reviewer would then not receive the exact set that IS the evidence.
#
# So a pathname is published through a reversible, single-line, Markdown-safe
# encoding, applied identically to BOTH endpoints of a rename:
#
#   1. Backslash layer, which removes every line break and control byte:
#      `\` -> `\\`, TAB -> `\t`, LF -> `\n`, CR -> `\r`, any other C0 byte or DEL
#      -> `\xHH`. Bytes >= 0x80 pass through untouched, so a UTF-8 path stays
#      readable as itself.
#   2. Entity layer, which removes every character GitHub's inline Markdown or
#      HTML would read as structure. `&` goes FIRST, so every `&` remaining in the
#      output is one this pass introduced and the decode is unambiguous; then
#      `< > \ ` * _ [ ] | ~`.
#
# To decode: HTML-entity-decode, then undo the backslash escapes. The legend is
# printed alongside the list so a reader can do it by hand.
#
# `LC_ALL=C` makes `substr`/`length` operate on bytes, and the value is passed
# through the environment rather than `-v`: awk's `-v` interprets backslash
# escapes in the assigned value, which would corrupt a path containing a literal
# backslash before the encoder ever saw it.
_encode_path() {
    _encode_arg="$1" LC_ALL=C awk 'BEGIN {
        s = ENVIRON["_encode_arg"]
        for (i = 1; i < 32; i++) ctl = ctl sprintf("%c", i)
        ctl = ctl sprintf("%c", 127)
        out = ""
        n = length(s)
        for (i = 1; i <= n; i++) {
            c = substr(s, i, 1)
            if (c == "\\") { out = out "\\\\"; continue }
            k = index(ctl, c)
            if (k == 0) { out = out c; continue }
            v = (k == 32 ? 127 : k)
            if (v == 9) out = out "\\t"
            else if (v == 10) out = out "\\n"
            else if (v == 13) out = out "\\r"
            else out = out sprintf("\\x%02x", v)
        }
        gsub(/&/, "\\&amp;", out)
        gsub(/</, "\\&lt;", out)
        gsub(/>/, "\\&gt;", out)
        gsub(/\\/, "\\&#92;", out)
        gsub(/`/, "\\&#96;", out)
        gsub(/\*/, "\\&#42;", out)
        gsub(/_/, "\\&#95;", out)
        gsub(/\[/, "\\&#91;", out)
        gsub(/\]/, "\\&#93;", out)
        gsub(/\|/, "\\&#124;", out)
        gsub(/~/, "\\&#126;", out)
        printf "%s", out
    }'
}

# The §4 drift record for a base move from $1 to the PR's merge base, rendered
# from the arrays `_read_base_move` last populated.
_render_drift() {
    local old="$1" i n
    n=${#drift_status[@]}
    echo "<details><summary><strong>base drift — this review is reused across a moved base (ADR-0027 §2b)</strong></summary>"
    echo
    echo "The review was taken against base \`${old:0:12}\`; this ships on base"
    echo "\`${expected_base:0:12}\`. The reviewed patch identity is unchanged and the base"
    echo "move touches none of ADR-0027 §3's floor, so the artifact still covers this"
    echo "content and the move is disclosed here rather than costing a review round."
    echo
    echo "**${n} file(s) changed by the base move**, published in full and never"
    echo "truncated (ADR-0027 §4). No floor covers a base move that clears every listed"
    echo "path and still bears on the change — that judgement is yours at merge:"
    echo
    for ((i = 0; i < n; i++)); do
        if [[ -n "${drift_dst[$i]}" ]]; then
            printf -- '- `%s` <code>%s</code> → <code>%s</code>\n' \
                "${drift_status[$i]}" \
                "$(_encode_path "${drift_src[$i]}")" \
                "$(_encode_path "${drift_dst[$i]}")"
        else
            printf -- '- `%s` <code>%s</code>\n' \
                "${drift_status[$i]}" "$(_encode_path "${drift_src[$i]}")"
        fi
    done
    echo
    echo "_Pathnames are encoded so the set survives publication intact (issue #165):"
    echo "\`\\\\\`, \`\\t\`, \`\\n\`, \`\\r\` and \`\\xHH\` are backslash escapes, and \`&…;\` are"
    echo "HTML entities. To recover a name, decode the entities first, then the"
    echo "backslash escapes._"
    echo
    echo "</details>"
    echo
}

# A drift record that does not fit its budget makes path (b) UNAVAILABLE, on the
# same footing as an unhashable identity — the artifact falls back to (a) and the
# moved base costs its round. §4 is explicit that truncating and shipping is the
# one outcome it must not have: here the file set is not context for a decision,
# it IS the decision, so an omitted tail is exactly where the contradicting
# `docs/adr/` entry hides.
drift_budget="${CODEX_SHIP_DRIFT_BUDGET:-20000}"

# Evaluated once per recorded base and cached: several artifacts commonly share
# one. `drift_verdict` is `ok`, `floor`, `toobig`, or `unreadable`.
declare -A drift_verdict=() drift_block=()
_evaluate_drift() {
    local old="$1" block
    if [[ -n "${drift_verdict[$old]:-}" ]]; then
        return 0
    fi
    if ! git cat-file -e "${old}^{commit}" 2>/dev/null; then
        drift_verdict["$old"]="unreadable"
        return 0
    fi
    if ! _read_base_move "$old" "$expected_base"; then
        drift_verdict["$old"]="unreadable"
        return 0
    fi
    if [[ "$drift_floor" == "1" ]]; then
        drift_verdict["$old"]="floor"
        return 0
    fi
    # A set that cannot fit even at the smallest an entry can render (a status,
    # a wrapped path, a newline — never under 20 bytes) is over budget already,
    # and rendering it would be wasted work: the path encoder runs once per
    # pathname, so this is what keeps a pathological base move from spending
    # thousands of subprocesses to reach a refusal it is already committed to.
    # A pure short-circuit — anything it rejects the real measurement rejects.
    if [[ $((${#drift_status[@]} * 20)) -gt "$drift_budget" ]]; then
        drift_verdict["$old"]="toobig"
        return 0
    fi
    block="$(_render_drift "$old")"
    if [[ "$(printf '%s' "$block" | wc -c)" -gt "$drift_budget" ]]; then
        drift_verdict["$old"]="toobig"
        return 0
    fi
    drift_verdict["$old"]="ok"
    drift_block["$old"]="$block"
    return 0
}

declare -A covering=()
# Why an artifact was rejected. ADR-0020 already required "content moved" to be
# distinguishable from "base moved"; ADR-0027 adds a third state and the message
# must now separate all of them — content moved, base moved past what the review
# can cover, and history diverged — or a refusal reads as the old stale-commit
# error and the author re-runs the wrong thing.
saw_tree_mismatch=0
saw_diverged_history=0
saw_identity_mismatch=0
saw_identity_unhashable=0
saw_floor_breach=0
saw_drift_toobig=0
saw_drift_unreadable=0
saw_unreadable=0
saw_persona_mismatch=0

# The lenses ship knows about. This is the whole set: `adversarial` is required
# before merge and `architecture` on top of it for a contract change, and an
# artifact naming anything else satisfies neither requirement — so rather than
# posting it under a heading that claims a lens nobody defined, refuse it.
# Adding a third persona means adding it here as well as writing its rubric.
declare -A known_persona=([adversarial]=1 [architecture]=1)

# Read one provenance field. The value is captured up to the next space rather
# than as "however many hex characters happen to follow", because `[0-9a-f]*`
# silently *stops* at the first non-hex byte: `base_sha=<expected>junk` would
# capture exactly the expected hash and compare equal, accepting an artifact
# whose recorded field is not the hash at all. Capturing the whole token means a
# malformed field mismatches and fails closed, which is what the comment below
# promises. The leading space also pins the field name, so `base_sha=` can never
# be read as `sha=` and a future `<x>_tree=` can never be read as `tree=`.
provenance_field() {
    sed -n "s/.*[[:space:]]$1=\([^[:space:]]*\).*/\1/p" <<<"$2"
}

# The closing line every genuine review carries (docs/review/guide.md). Matched
# against the *last non-blank line*, not anywhere in the body: a substring search
# accepts prose that merely mentions the words, e.g. "I cannot provide a verdict
# or APPROVE this change". Markdown emphasis is stripped first, since the
# reviewer writes "**Verdict: X**", "Verdict: X" and "VERDICT: X" interchangeably.
#
# The `Verdict:` label is optional: docs/review/guide.md asks only for "a
# one-line verdict: BLOCK, APPROVE WITH NITS, or APPROVE", so a bare
# `APPROVE WITH NITS` conforms and must not be read as an incomplete artifact
# (issue #120). Kept deliberately identical to the same test in
# codex-review.sh — one records the artifact and the other refuses to post an
# incomplete one, so a review the recorder accepts and the shipper rejects would
# strand a valid review with no way to ship it.
#
# A verdict alone does not count, for the same reason the recorder rejects one:
# the rubric's anti-patterns forbid rubber-stamping, and an artifact whose only
# non-blank body line is the verdict carries no findings and no statement of
# what was checked. Line 1 is the provenance comment and is not body — the same
# line `tail -n +2` strips before posting.
artifact_has_verdict() {
    local last body_lines
    last="$(grep -v '^[[:space:]]*$' "$1" | tail -n 1 |
        tr -d '*#`' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
    grep -qiE '^(verdict:?[[:space:]]*)?(block|approve with nits|approve)\.?$' <<<"$last" ||
        return 1
    body_lines="$(tail -n +2 "$1" | grep -c -v '^[[:space:]]*$' || true)"
    [[ "$body_lines" -ge 2 ]]
}

# --- Disposition snapshots (ADR-0025 §4) -------------------------------------
#
# A persistent review round records a per-finding disposition SNAPSHOT of the
# state it reviewed, named by the full anchor `<loop_id>-<persona>-<tree>.md`.
# ship publishes the snapshot belonging to the terminal artifact's tree so the
# merge reviewer can read the verdict-changing history — which findings were
# retired, and across which rounds — not only the terminal verdict.

# The snapshot for a terminal artifact, selected by the full anchor
# (loop_id, persona, tree). Echoes the path, or nothing when the artifact carries
# no loop_id — a bypass or pre-ADR-0025 artifact, which has no persistent-session
# dispositions to publish. An artifact that DOES carry a loop_id is a persistent
# round and must have its anchored snapshot: a missing one fails closed rather
# than posting the verdict with no disposition evidence (e.g. a snapshot write
# that failed). Fails closed too on ambiguity (more than one loop recorded a
# snapshot for the same content) or a loop mismatch (the snapshot found is not
# the loop the artifact names — a stale snapshot from another path). $1 persona,
# $2 tree, $3 the artifact's recorded loop_id.
disposition_snapshot() {
    local persona="$1" tree="$2" want="$3" want_base="$4" want_sha="$5" f lid
    # No loop_id: not a persistent artifact, so nothing to select. Requiring a
    # non-empty match below is what closes the stale-snapshot case a bypass
    # artifact would otherwise pick up.
    [[ -n "$want" ]] || return 0
    local -a matches=()
    local -A loops=()
    shopt -s nullglob
    for f in .review/dispositions/*-"${persona}-${tree}".md; do
        lid="$(provenance_field loop_id "$(head -n 1 "$f")")"
        [[ -n "$lid" ]] || continue
        loops["$lid"]=1
        [[ "$lid" == "$want" ]] && matches+=("$f")
    done
    shopt -u nullglob
    if [[ ${#loops[@]} -gt 1 ]]; then
        die "ambiguous disposition snapshots for ${persona} tree ${tree:0:12}:
     ${#loops[@]} loops recorded one for the same content, so which belongs beside
     this verdict cannot be determined (ADR-0025 §4). Clear stale
     .review/dispositions/ and re-run the review."
    fi
    if [[ ${#matches[@]} -eq 0 ]]; then
        die "the review artifact for ${persona} tree ${tree:0:12} is a persistent
     round (loop ${want}) but its anchored disposition snapshot is missing —
     refusing to post a verdict with no disposition evidence (ADR-0025 §4).
     Re-run: just review-codex ${persona}"
    fi
    # Validate the rest of the full anchor: a snapshot keyed on (loop, persona,
    # tree) can still have been overwritten by a later round that reviewed the
    # same tree under a different base or commit. base_sha and the terminal sha
    # from its header must match the artifact's, or the snapshot belongs to a
    # different terminal turn and is refused (ADR-0025 §4).
    local shdr sbase ssha
    shdr="$(head -n 1 "${matches[0]}")"
    sbase="$(provenance_field base_sha "$shdr")"
    ssha="$(provenance_field sha "$shdr")"
    if [[ "$sbase" != "$want_base" || "$ssha" != "$want_sha" ]]; then
        die "the disposition snapshot for ${persona} tree ${tree:0:12} was recorded
     for a different terminal turn (base ${sbase:0:12}/sha ${ssha:0:12}) than the
     review artifact (base ${want_base:0:12}/sha ${want_sha:0:12}) — refusing to
     post dispositions from another round (ADR-0025 §4). Re-run: just review-codex ${persona}"
    fi
    printf '%s\n' "${matches[0]}"
}

# Each finding's header fields as `id<TAB>severity<TAB>status<TAB>first<TAB>last`.
snapshot_finding_lines() {
    sed -n 's/.*<!-- finding id=\([^ ]*\) severity=\([^ ]*\) status=\([^ ]*\) first_round=\([^ ]*\) last_round=\([^ ]*\) -->.*/\1\t\2\t\3\t\4\t\5/p' "$1"
}

# The verbatim text of one finding (between its header and terminator).
snapshot_finding_text() {
    awk -v id="$2" '
        $0 ~ ("<!-- finding id=" id " ") { g = 1; next }
        g && /<!-- \/finding -->/ { g = 0 }
        g { print }
    ' "$1"
}

# Whether a proposal carries a plausible secret (a key Codex may have read from an
# ignored file like .env). Deliberately broad and fail-toward-exclude: a false
# positive costs one finding its published proposal (it takes ordinary review), a
# false negative would publish a secret. $1 the text to scan.
contains_secret() {
    local t="$1"
    # Shaped credentials, matched literally.
    grep -qE '(-----BEGIN [A-Z ]*PRIVATE KEY-----|AKIA[0-9A-Z]{16}|xox[baprs]-[0-9A-Za-z-]{10,}|gh[posur]_[0-9A-Za-z]{20,}|github_pat_[0-9A-Za-z_]{20,}|[Bb]earer[[:space:]]+[A-Za-z0-9._~+/-]{12,}|eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,})' <<<"$t" && return 0
    # A named credential assigned a value, with `=`, `:`, or whitespace between
    # the name and the value (so `Bearer x`, `api_key: x`, `password = x` match).
    grep -qiE '(api[_-]?key|secret|passwd|password|token)[[:space:]'\''":]+[^[:space:]'\''"]{6,}' <<<"$t"
}

# Renders a disposition snapshot into a collapsible section, bounded by a
# cumulative published-byte budget so a long loop cannot exceed ship's comment
# limit (ADR-0025 §4). A §3 Codex proposal is the exception: it appears in full,
# unless it cannot be published exactly and safely (too large, or carrying a
# secret), in which case it is excluded — not truncated — and that finding takes
# ordinary review, fail-closed. $1 snapshot path, $2 persona.
render_dispositions() {
    local snap="$1" persona="$2"
    # Budget derived from the comment's remaining capacity by the caller; the env
    # override (default 20000) is the fallback and the cap.
    local budget="${disp_budget:-${CODEX_SHIP_DISPOSITION_BUDGET:-20000}}"
    local total used=0 hidden=0
    total="$(grep -c '<!-- finding id=' "$snap" || true)"
    [[ "${total:-0}" -eq 0 ]] && return 0

    echo "<details><summary><strong>${persona} — dispositions (${total} finding(s))</strong></summary>"
    echo
    echo "_Per-finding disposition record from the persistent review session"
    echo "(ADR-0025 §4). A **retired** finding was raised in an earlier round and"
    echo "not re-raised in the terminal round; its withdrawal is not separately"
    echo "recorded, so verify each retirement against this PR's diff._"
    echo
    local id sev status first last text note has_fence entry entry_bytes when
    while IFS=$'\t' read -r id sev status first last; do
        [[ -n "$id" ]] || continue
        text="$(snapshot_finding_text "$snap" "$id")"
        note=""
        # A retired finding: report only what retirement actually knows — raised,
        # then not re-raised — and assert NO cause. The mechanism retires on
        # absence alone, so it cannot know whether a code change resolved the
        # finding or the reviewer dropped it on reflection with no change. Naming a
        # cause would fabricate audit evidence; the merge reviewer is pointed at
        # the diff to judge for itself (ADR-0025 §4).
        when="(rounds ${first}–${last})"
        if [[ "$status" == "retired" ]]; then
            when="raised through round ${last}, not re-raised in the terminal round —"
            when="${when} no explicit withdrawal was recorded; verify against this PR's diff"
        fi
        # Any fenced block is a possible §3 proposal (a language label is not a
        # reliable signal). Nothing bypasses the cumulative budget: a proposal is
        # published in full only if it fits, else it is EXCLUDED — not truncated —
        # so several proposals cannot together exceed ship's comment limit.
        has_fence=0
        grep -qiE '^[[:space:]]*```' <<<"$text" && has_fence=1
        # The secret scan covers the WHOLE finding, not only a labelled fence: a
        # key Codex read from an ignored file could sit in prose or any fence. If
        # found, the entire finding text is excluded — not redacted in place — so
        # publishing never leaks it (ADR-0025 §3, fail-closed).
        if contains_secret "$text"; then
            text="_(finding content excluded — see note)_"
            note="  "$'\n'"> ⚠ **Content excluded** — this finding may carry a secret, so it is not published; it takes ordinary independent review (ADR-0025 §3, fail-closed)."
        fi
        entry="$(printf -- '- **%s** — _%s_ %s\n\n%s\n%s\n' \
            "$sev" "$status" "$when" "$text" "$note")"
        entry_bytes="$(printf '%s' "$entry" | wc -c)"
        if [[ $((used + entry_bytes)) -le "$budget" ]]; then
            printf '%s\n\n' "$entry"
            used=$((used + entry_bytes))
            continue
        fi
        # Does not fit. A fenced proposal is excluded whole (its audit value needs
        # the full patch or nothing); its header is still recorded if that fits.
        if [[ "$has_fence" -eq 1 ]]; then
            entry="$(printf -- '- **%s** — _%s_ %s  \n> ⚠ **Codex proposal excluded** — it does not fit the published budget in full; this finding takes ordinary independent review (ADR-0025 §3, fail-closed).\n' \
                "$sev" "$status" "$when")"
            entry_bytes="$(printf '%s' "$entry" | wc -c)"
            if [[ $((used + entry_bytes)) -le "$budget" ]]; then
                printf '%s\n\n' "$entry"
                used=$((used + entry_bytes))
                continue
            fi
        fi
        hidden=$((hidden + 1))
    done < <(snapshot_finding_lines "$snap")
    if [[ "$hidden" -gt 0 ]]; then
        echo "_…${hidden} more finding(s) omitted to stay within the published-size"
        echo "budget; the complete record is in \`.review/dispositions/\` (local)._"
        echo
    fi
    echo "</details>"
    echo
}

declare -A covering_rank=()
# The recorded base of the artifact selected for a persona, when it was accepted
# under (b) — empty under (a). This is what §4 publishes.
declare -A covering_drift=()

shopt -s nullglob
for a in .review/*.md; do
    provenance="$(head -n 1 "$a")"
    recorded_base="$(provenance_field base_sha "$provenance")"
    recorded_tree="$(provenance_field tree "$provenance")"
    recorded_persona="$(provenance_field persona "$provenance")"
    recorded_patch="$(provenance_field patch_id "$provenance")"
    recorded_sha="$(provenance_field sha "$provenance")"

    # An artifact predating ADR-0020 records no tree, so its content cannot be
    # verified at all. Fail closed: unverifiable is not the same as matching,
    # and re-running a review costs one round where accepting this costs the
    # guarantee. Same for a hand-edited or truncated provenance line. The
    # persona field has been recorded since the artifact was introduced, so an
    # artifact old enough to lack it lacks the tree too and fails here anyway.
    if [[ -z "$recorded_base" || -z "$recorded_tree" || -z "$recorded_persona" ]]; then
        saw_unreadable=1
        continue
    fi

    # Which lens ran is the one claim ship makes on the artifact's behalf, and it
    # is read from the RECORDED FIELD, never from the filename (ADR-0027 §6). The
    # name is an identity — every field the acceptance rule selects on — not a
    # parser input, and it never was evidence: an architecture artifact renamed to
    # claim the adversarial lens used to satisfy the mandatory adversarial
    # requirement without that lens ever having run (issue #99). Reading the field
    # closes that outright rather than by requiring the two to agree, because
    # renaming an artifact now says nothing at all.
    #
    # This does not make the artifact tamper-proof and does not try to be — a
    # forged file can set the field. What it requires is that the claim be a lens
    # this script actually knows, so an artifact naming something else is refused
    # rather than posted under a heading claiming a lens nobody defined.
    persona="$recorded_persona"
    if [[ -z "${known_persona[$persona]:-}" ]]; then
        saw_persona_mismatch=1
        continue
    fi

    drifted=""
    if [[ "$recorded_base" == "$expected_base" ]]; then
        # (a) — ADR-0020 §3 exactly as written. The tree is the whole test here.
        if [[ "$recorded_tree" != "$head_tree" ]]; then
            saw_tree_mismatch=1
            continue
        fi
    else
        # (b) — the moved-base path, and the moved-base path only. Every clause
        # below fails CLOSED: the artifact falls back to (a), which will refuse
        # it, and the moved base costs its round.
        if ! git merge-base --is-ancestor "$recorded_base" "$expected_base" 2>/dev/null; then
            saw_diverged_history=1
            continue
        fi
        # An empty identity on either side is "nothing to hash", never a match:
        # an artifact predating the field, an empty range, or a range carrying an
        # entry anchored on its paths alone — a 100%-similarity rename, a
        # mode-only change — whose identity would compare equal across a base
        # move that rewrote the very content the rename carried.
        if [[ -z "$recorded_patch" || -z "$head_patch_id" ]]; then
            saw_identity_unhashable=1
            continue
        fi
        if [[ "$recorded_patch" != "$head_patch_id" ]]; then
            saw_identity_mismatch=1
            continue
        fi
        _evaluate_drift "$recorded_base"
        case "${drift_verdict[$recorded_base]}" in
        floor)
            saw_floor_breach=1
            continue
            ;;
        toobig)
            saw_drift_toobig=1
            continue
            ;;
        unreadable)
            saw_drift_unreadable=1
            continue
            ;;
        esac
        drifted="$recorded_base"
    fi

    # Several artifacts can legitimately cover this same content — that is the
    # point of the change — so pick between them deterministically rather than
    # taking whichever the glob yielded first.
    #
    # Completeness outranks everything: selecting an incomplete artifact while a
    # valid one covers the same content would refuse the ship on the strength of
    # a file the author has already superseded, and the verdict check below is a
    # test of the *review*, not a way to lose one. Then an unmoved base outranks
    # a moved one, because (a)'s whole-tree comparison is strictly stronger than
    # any identity computed from a diff. Among equals, prefer the artifact
    # recorded for the current commit, so a reader comparing the posted comment
    # against the PR head sees no discrepancy.
    rank=0
    if artifact_has_verdict "$a"; then
        rank=4
    fi
    if [[ -z "$drifted" ]]; then
        rank=$((rank + 2))
    fi
    if [[ "$recorded_sha" == "$sha" ]]; then
        rank=$((rank + 1))
    fi
    if [[ -z "${covering[$persona]:-}" || "$rank" -gt "${covering_rank[$persona]}" ]]; then
        covering["$persona"]="$a"
        covering_rank["$persona"]="$rank"
        covering_drift["$persona"]="$drifted"
    fi
done
shopt -u nullglob

# The reason each refusal names, appended to whichever requirement fails below.
why=""
if [[ "$saw_tree_mismatch" == "1" ]]; then
    why="${why}
     a review exists for *different content* — the change moved since it was
     reviewed, so it needs a fresh one (this is not the old stale-commit error:
     amending or squashing without editing content no longer costs a round)"
fi
if [[ "$saw_diverged_history" == "1" ]]; then
    why="${why}
     a review exists whose recorded base is *not an ancestor* of this PR's merge
     base — that is not base drift, it is a different history (a review run with
     a narrower base such as HEAD~1, or a branch reset onto an unrelated base),
     so it does not cover this PR's full diff (ADR-0027 §2)"
fi
if [[ "$saw_identity_mismatch" == "1" ]]; then
    why="${why}
     a review exists against an *earlier base* whose reviewed patch is no longer
     the patch being shipped — the base moved INTO the region the diff touches,
     so the context the reviewer read has changed and the review no longer covers
     it (ADR-0027 §2)"
fi
if [[ "$saw_identity_unhashable" == "1" ]]; then
    why="${why}
     a review exists against an *earlier base*, but this range has no patch
     identity that can be trusted — it predates the field, or it carries an entry
     anchored on its paths alone (a 100%-similarity rename, a mode-only change),
     whose identity would not move even if the base rewrote that file. Refused
     rather than guessed at (ADR-0027 §2)"
fi
if [[ "$saw_floor_breach" == "1" ]]; then
    why="${why}
     a review exists against an *earlier base*, and the base move touches
     ADR-0027 §3's floor — the contract surface, the standing review contracts
     (docs/review/**, CLAUDE.md, CONTRIBUTING.md, scripts/codex-review.sh), or
     docs/adr/**. The gate cannot see those and they change what a reviewer would
     say, so the move costs its round"
fi
if [[ "$saw_drift_toobig" == "1" ]]; then
    why="${why}
     a review exists against an *earlier base*, but the base move's file set is
     too large to publish whole within ${drift_budget} bytes. §4 requires the whole
     set or nothing — truncating and shipping is the one outcome it must not
     have — so the moved base costs its round"
fi
if [[ "$saw_drift_unreadable" == "1" ]]; then
    why="${why}
     a review exists against an *earlier base* that cannot be read from this
     clone, or whose file listing could not be parsed, so the drift §4 requires
     published cannot be computed — fetch, or re-run the review"
fi
if [[ "$saw_unreadable" == "1" ]]; then
    why="${why}
     a review exists with no recorded persona/base/tree — it predates ADR-0020
     or was edited, so what it covers cannot be verified"
fi
if [[ "$saw_persona_mismatch" == "1" ]]; then
    why="${why}
     a review exists whose recorded persona names a lens this script does not
     know — and the recorded field is the only claim ship reads, so renaming the
     record changes nothing; run the review the lens actually needs"
fi

# Adversarial is the required lens before merge. ADR-0020 relaxes neither this
# nor the architecture requirement below; it changes only what counts as a
# review of *this* content.
if [[ -z "${covering[adversarial]:-}" ]]; then
    die "no adversarial review covering this PR's content
     (HEAD tree ${head_tree:0:12}, base ${expected_base:0:12})${why}
     run: just review-codex adversarial"
fi

# A change to the shared contract surface needs the architecture lens too
# (CONTRIBUTING, "Contract ADRs land before their implementation").
if [[ "$core_change" == "1" && -z "${covering[architecture]:-}" ]]; then
    die "this change touches core/protocols.py or core/types.py, so it needs
     the architecture lens as well as the adversarial one${why}
     run: just review-codex architecture"
fi

# Posting order is fixed rather than glob order, so the comment reads the same
# way every time regardless of which commits the artifacts happen to be under.
# Enumerating the known personas is exhaustive: the loop above rejects anything
# outside `known_persona`, so nothing else can be in `covering` to be missed.
artifacts=()
posting_personas=()
for persona in adversarial architecture; do
    if [[ -n "${covering[$persona]:-}" ]]; then
        artifacts+=("${covering[$persona]}")
        posting_personas+=("$persona")
    fi
done

# Re-check the verdict here, not just when recording. A base and a tree say what
# an artifact covers, not that it holds a finished review: a file truncated by an
# interrupt, or edited by hand, keeps valid metadata while losing its body. ship
# is the last point before this becomes the record, so it verifies rather than
# trusts.
for persona in "${posting_personas[@]}"; do
    if ! artifact_has_verdict "${covering[$persona]}"; then
        die "$(basename "${covering[$persona]}") does not end in a verdict — it is
     incomplete
     re-run: just review-codex ${persona}"
    fi
done

# Resolve each artifact's disposition snapshot by the full anchor now, before
# building the body, so an ambiguity or a loop mismatch fails the ship closed
# rather than after posting (ADR-0025 §4).
declare -A snapshot=()
for a in "${artifacts[@]}"; do
    prov="$(head -n 1 "$a")"
    a_persona="$(provenance_field persona "$prov")"
    a_tree="$(provenance_field tree "$prov")"
    a_loop="$(provenance_field loop_id "$prov")"
    a_base="$(provenance_field base_sha "$prov")"
    a_sha="$(provenance_field sha "$prov")"
    snap="$(disposition_snapshot "$a_persona" "$a_tree" "$a_loop" "$a_base" "$a_sha")"
    [[ -n "$snap" ]] && snapshot["$a_persona"]="$snap"
done

# The disposition budget is derived from the comment's ACTUAL remaining capacity,
# not a fixed allowance — otherwise a large terminal artifact plus a small
# disposition section could together exceed GitHub's limit and break a ship that
# would have succeeded without dispositions (ADR-0025 §4: the cumulative budget
# must not break the existing ship path). Sum the artifact sizes, subtract a
# margin for the aggregate line and the details wrappers, and split what remains
# across the personas that have a snapshot; the env override only lowers it.
max_bytes=60000
artifacts_bytes=0
for a in "${artifacts[@]}"; do
    artifacts_bytes=$((artifacts_bytes + $(wc -c <"$a")))
done
# §4's drift record is published in full or path (b) is unavailable, so it is
# not a claimant on the remaining capacity — it is subtracted from it, ahead of
# the dispositions, which ADR-0025 §4 does allow to be bounded.
drift_bytes=0
counted_drift=""
for persona in "${posting_personas[@]}"; do
    drifted="${covering_drift[$persona]:-}"
    [[ -n "$drifted" ]] || continue
    case "$counted_drift" in *" ${drifted} "*) continue ;; esac
    counted_drift="${counted_drift} ${drifted} "
    drift_bytes=$((drift_bytes + $(printf '%s' "${drift_block[$drifted]}" | wc -c)))
done
num_snap=${#snapshot[@]}
disp_budget=0
if [[ "$num_snap" -gt 0 ]]; then
    remaining=$((max_bytes - artifacts_bytes - drift_bytes - 4000))
    [[ "$remaining" -lt 0 ]] && remaining=0
    disp_budget=$((remaining / num_snap))
    cap="${CODEX_SHIP_DISPOSITION_BUDGET:-20000}"
    [[ "$disp_budget" -gt "$cap" ]] && disp_budget="$cap"
fi

num="$(gh pr view --json number --jq .number)"
body="$(mktemp)"
trap 'rm -f "$body"' EXIT

# The two lines that identify a ship comment: a hidden marker naming the commit,
# then the visible header. They lead the body precisely so the lookup below can
# recognise a comment from its opening lines alone, without pulling whole comment
# bodies through a shell variable.
marker="<!-- ship:${sha} -->"
header="🔍 **Local Codex review** — commit \`${sha:0:12}\`"

# The aggregate the author saw when the review ran (ADR-0020 §2), rendered into
# the comment rather than left in the provenance line — `tail -n +2` below strips
# that line, so without this the merge reviewer would never see the numbers. The
# whole point is that the human at merge holds the same aggregate view the author
# had; in both runaway cases in issue #91 it was an outside observer holding
# exactly this that ended the loop.
adversarial_provenance="$(head -n 1 "${covering[adversarial]}")"
agg_field() { sed -n "s/.* $1=\([^ ]*\).*/\1/p" <<<"$adversarial_provenance"; }
agg_round="$(agg_field round)"
agg_net="$(agg_field net_lines)"
agg_churn="$(agg_field churn_lines)"
agg_ratio="$(agg_field churn_ratio)"
agg_commits="$(agg_field commits)"
agg_supersedes="$(agg_field supersedes)"
# Both are absent from artifacts recorded before they existed, and `binary_files`
# is absent whenever the diff has no binary path at all — so each is rendered
# only when present, never as a zero or an "exact" the reader has to discount.
agg_bound="$(agg_field churn_bound)"
agg_binary="$(agg_field binary_files)"
# Binary work can be absent from the net diff and still be work the branch did —
# added in one commit, reverted in a later one. Carried separately for that
# reason, so the caveat the author saw is not lost on the way to the PR.
agg_binary_churn="$(agg_field binary_churn)"

{
    echo "$marker"
    echo "$header"
    echo
    # Older artifacts carry no aggregate; omit the line rather than print blanks.
    if [[ -n "$agg_round" ]]; then
        summary="round ${agg_round} · ${agg_net} lines net"
        [[ -n "$agg_commits" ]] && summary="${summary} across ${agg_commits} commit(s)"
        if [[ -n "$agg_binary" ]]; then
            summary="${summary} + ${agg_binary} binary file(s) unmeasured"
        fi
        if [[ -n "$agg_ratio" ]]; then
            # A churn figure computed after a squash, amend or rebase counts only
            # the work still on the branch, so it is a floor rather than a
            # measurement. The merge reviewer has to see that distinction or the
            # number reads as "little rework happened" on precisely the branch
            # that was reworked enough to be worth squashing (issue #97).
            #
            # `n/a` is not a ratio, so it takes neither the `≥` nor the `×` — a
            # diff with no measurable text lines (a binary-only or rename-only
            # state) reports no ratio at all, and `churn ≥n/a×` would be noise
            # in the one line that exists to be read at a glance. The
            # rewritten-history caveat still applies and is stated on its own.
            if [[ "$agg_ratio" == "n/a" ]]; then
                summary="${summary} · churn n/a (${agg_churn} touched)"
                if [[ "$agg_bound" == "lower" ]]; then
                    summary="${summary} · history rewritten, earlier rounds not counted"
                fi
            elif [[ "$agg_bound" == "lower" ]]; then
                summary="${summary} · churn ≥${agg_ratio}× (${agg_churn} touched;"
                summary="${summary} lower bound — history rewritten, earlier rounds not counted)"
            else
                summary="${summary} · churn ${agg_ratio}× (${agg_churn} touched)"
            fi
            if [[ -n "$agg_binary_churn" ]]; then
                summary="${summary} + ${agg_binary_churn} binary change(s) unmeasured"
            fi
        fi
        if [[ -n "$agg_supersedes" ]]; then
            # `ADR-0004:175,ADR-0012:98` → `ADR-0004 (175 lines), ADR-0012 (98 lines)`
            pretty="$(sed 's/:\([0-9]*\)/ (\1 lines)/g; s/,/, /g' <<<"$agg_supersedes")"
            summary="${summary} · supersedes ${pretty}"
        fi
        echo "_${summary}_"
        echo
    fi
    # §4's drift record, when any selected artifact was accepted across a moved
    # base. Placed after the summary line and before the persona blocks, so the
    # `<!-- ship:<sha> -->` marker and the header line that must follow it are
    # untouched and a parser reading those two lines is unaffected (ADR-0027,
    # Consequences: #153). Deduplicated by base, since two personas commonly
    # share one.
    printed_drift=""
    for persona in "${posting_personas[@]}"; do
        drifted="${covering_drift[$persona]:-}"
        [[ -n "$drifted" ]] || continue
        case "$printed_drift" in *" ${drifted} "*) continue ;; esac
        printed_drift="${printed_drift} ${drifted} "
        printf '%s\n' "${drift_block[$drifted]}"
    done
    for persona in "${posting_personas[@]}"; do
        a="${covering[$persona]}"
        echo "<details><summary><strong>${persona}</strong></summary>"
        echo
        # Drop the provenance comment; it is metadata for this script, not for
        # a reader of the PR.
        tail -n +2 "$a"
        echo
        echo "</details>"
        echo
        # The verdict-changing evidence: the per-finding dispositions belonging to
        # this terminal artifact's tree (ADR-0025 §4). Rendered into the published
        # comment so it reaches the merge reviewer, not only git-ignored .review/.
        if [[ -n "${snapshot[$persona]:-}" ]]; then
            render_dispositions "${snapshot[$persona]}" "$persona"
        fi
    done
} >"$body"

# One comment per commit — the whole report is a single API call, so there is no
# partial-success state to reconcile. (Posting per persona would avoid the shared
# size budget below, but a transient failure on the second call would leave the
# first posted and make re-running `ship` duplicate it.)
#
# GitHub rejects a body over 65536 characters, and nothing here is truncated:
# cutting at a byte boundary drops the tail, which is exactly where the ranked
# findings and the verdict sit. A silently-shortened review posted as a
# successful ship is worse than no comment, so an oversized report fails closed.
# This stays the backstop; the disposition budget above keeps dispositions from
# being what trips it (max_bytes was set there).
if [[ "$(wc -c <"$body")" -gt "$max_bytes" ]]; then
    die "the review report is over ${max_bytes} bytes and cannot be posted intact
     truncating it would risk dropping the findings and the verdict
     post it by hand, or re-run the review to get a shorter one"
fi

# Posting is not idempotent on its own: if GitHub creates the comment but the
# response is lost in transit, `gh` exits non-zero having already succeeded, and
# a re-run adds an identical second review. Look for this commit's comment first
# and update in place when it is there, so a re-run converges on one comment
# whether the previous attempt failed before, during, or after the write.
#
# `@tsv` keeps one comment per line — a body's own newlines are escaped — so the
# match happens here rather than in a jq filter, which is also what lets this be
# tested against a fake `gh`. Only the opening two lines are fetched; whole
# bodies are not needed and would be megabytes on a long-running PR.
#
# A failure to read the existing comments stops the ship. Posting anyway would
# give up the very guarantee this lookup exists to provide, and a re-run costs
# nothing now that it converges.
comment_lines="$(gh api --paginate "repos/{owner}/{repo}/issues/${num}/comments" \
    --jq '.[] | [(.id | tostring), (.user.login // ""),
        (.body | split("\n")[0]), (.body | split("\n")[1] // "")] | @tsv')" ||
    die "could not read the PR's existing comments to check for an earlier ship
     re-run once the API is reachable"

# The marker alone does not identify *our* comment — it is public text anyone can
# write or quote. Patching on it alone would destroy someone else's comment where
# permissions allow it and fail the ship where they do not. Two further
# conditions narrow the match: the comment must be authored by this account, and
# it must carry ship's own header on the line after the marker.
#
# A byte-identical forgery still matches, and nothing short of server-side state
# this script deliberately does not keep would catch that. What is closed is the
# case that actually happens — a comment quoting or mentioning a ship marker.
me="$(gh api user --jq .login)" ||
    die "could not determine the authenticated GitHub account
     re-run once the API is reachable"

existing_ids=()
while IFS=$'\t' read -r id author line1 line2; do
    # GitHub returns comment bodies with CRLF line endings, so every line
    # arrives with a trailing carriage return and would never compare equal.
    # `@tsv` encodes that CR as the two characters `\` and `r` — it cannot emit
    # a raw one without breaking the one-record-per-line format — so what is
    # stripped here is the escape, not a control byte.
    if [[ "$author" == "$me" && "${line1%'\r'}" == "$marker" &&
        "${line2%'\r'}" == "$header" ]]; then
        existing_ids+=("$id")
    fi
done <<<"$comment_lines"

# Re-read the PR head immediately before writing. Fetching the base, building the
# body, and reading the PR's comments all take seconds, and a push landing in
# that window would leave a review on the PR that reads as current but covers
# superseded code. This check sits after the lookup for that reason: everything
# between it and the write must be the write itself. It cannot be atomic with
# comment creation — hence the SHA in the comment header as well — but it closes
# the realistic window rather than the theoretical one.
if [[ "$(gh pr view --json headRefOid --jq .headRefOid)" != "$sha" ]]; then
    die "PR head moved while preparing the review — re-run ship"
fi

# Every match is updated, not just the first. Check-then-create is not atomic —
# GitHub offers no conditional comment creation — so two ships racing on one
# commit can both find nothing and both post. That window is narrow (one clone
# per agent, one PR per branch, ADR-0015) and its outcome is cosmetic. What
# would not be cosmetic is a duplicate that then goes stale: updating only the
# first match would leave the second showing a superseded review forever.
#
# The loop is not atomic — GitHub has no multi-comment write — so a failure part
# way through leaves the PR showing this review on one comment and a superseded
# one on another. Two things follow, and they are what issue #76 asked for.
#
# First, a failed PATCH does not abort the rest. Under a bare `set -e` the first
# failure stops the loop, so a transient error on the first of three comments
# leaves the other two stale as well — the script gives up on comments it had
# every chance to fix. Attempting all of them makes the divergence as small as
# the failures actually were.
#
# Second, the exit names which comments were written and which were not, rather
# than surfacing gh's bare error. The state is self-healing — a re-run finds
# every comment for this commit and rewrites all of them — but only if the
# operator can see that a re-run is what is needed, and where to look.
#
# What the message deliberately does *not* say is that a failed comment is
# stale. A non-zero PATCH does not prove the write was not applied: the request
# can succeed and its response be lost, exactly the ambiguity this script
# already documents for comment creation below. Reporting "showing a superseded
# review" would be a claim ship cannot support, and re-reading the comments to
# find out would add a round of API calls to the path where the API is already
# failing. Naming the uncertainty is both honest and sufficient, because the
# recovery for either case is the same re-run.
#
# Retrying in-process was the other option the issue offered and is not taken:
# a retry without backoff buys almost nothing against the failures that actually
# happen (auth, rate limit, network down), and a re-run of ship is already the
# correct and tested recovery.
if [[ ${#existing_ids[@]} -gt 0 ]]; then
    echo "ship: updating ${#existing_ids[@]} existing review comment(s) for" \
        "${sha:0:12} on PR #${num}…" >&2
    updated_ids=()
    failed_ids=()
    for id in "${existing_ids[@]}"; do
        if gh api --silent --method PATCH \
            "repos/{owner}/{repo}/issues/comments/${id}" -F "body=@${body}"; then
            updated_ids+=("$id")
        else
            failed_ids+=("$id")
        fi
    done
    if [[ ${#failed_ids[@]} -gt 0 ]]; then
        # `${arr[*]}` rather than `${arr[@]}`: one space-joined string for the
        # message, and both arrays are known non-empty on the branches that read
        # them, so `set -u` has nothing to trip on.
        updated_desc="none"
        if [[ ${#updated_ids[@]} -gt 0 ]]; then
            updated_desc="${updated_ids[*]}"
        fi
        die "could not update every review comment on PR #${num}
     for commit ${sha:0:12}:
       updated:        comment(s) ${updated_desc}
       write failed:   comment(s) ${failed_ids[*]}
     the failed comment(s) may or may not have been updated — a lost response
     looks the same as a rejected request — so treat the PR as inconsistent
     until a re-run settles it
     nothing is wrong with the review itself; the write failed, not the record
     re-run: just ship — it rewrites every comment it owns for this commit, so
     a re-run converges on one current review"
    fi
else
    echo "ship: posting ${#artifacts[@]} review(s) for ${sha:0:12} to PR #${num}…" >&2
    gh pr comment "$num" --body-file "$body"
fi
echo "ship: done. Resolve or file issues for any blocker/major finding before merging." >&2
