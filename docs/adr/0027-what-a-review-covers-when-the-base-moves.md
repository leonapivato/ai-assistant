# 27. What a review covers when the base moves

- Status: Accepted
- Date: 2026-07-21
- Amends on ratification: ADR-0020 §3, the content anchor — the section
  ADR-0025 §4 already amended once. The edit is **not** made by this change; §7
  records its exact form and why it waits.
- Resolves: #124 (a base move invalidates a review unconditionally) and #149
  (two reviews of one SHA against different bases collide on the artifact
  path). They are one decision: both concern what identifies the content a
  review covers — #124 how it is *tested*, #149 how it is *named*.
- Refs: #153 (`scripts/review_history.py`, in flight) — unaffected, see
  Consequences.

## Context

ADR-0020 §3 accepts a review artifact when its recorded base **and** tree both
match the PR's current merge base and `HEAD`'s tree. The base comparison is
unconditional. #124 measured the cost on #118: two rebases, two review runs, one
of which — onto a base whose only change was in
`src/ai_assistant/orchestration/loop.py`, against a diff confined to
`scripts/ship.sh` — could not have produced a finding. The cost scales with lane
count times merge count, on a repo deliberately running several lanes in
parallel (ADR-0015).

Three facts about the current mechanism are load-bearing here and are in neither
issue.

**A merge to `main` does not move a PR's merge base. A rebase does.** `ship`
computes `expected_base` as `git merge-base FETCH_HEAD "$sha"`
(`scripts/ship.sh`). When `origin/main` advances and the branch is left alone,
that merge base is still the original fork point, so the artifact still matches
and nothing is invalidated. The anchor charges for the *rebase*, not for the
merge — and the rebase is charged twice over, because branch protection's
`strict: true` requires it at merge time and `CONTRIBUTING.md` ("Run it against
a current `main`") requires it before the gate.

**A rebase moves the tree as well as the base, so relaxing the base comparison
alone is inert.** `HEAD^{tree}` is the whole repository tree, which after a
rebase contains the moved base's content. #124's cheap direction — compare
`git diff --name-only <old_base>...<new_base>` against the review's paths and,
if disjoint, keep the artifact — would leave `ship` refusing on the recorded
tree anyway. Any relaxation has to restate what the pair of fields is *for*, not
weaken one of them.

**The moved base is gated before it is shipped.** The standard path rebases and
re-runs the whole gate (`CONTRIBUTING.md` → "The gate"), and CI re-runs it on
push (ADR-0010). Whatever else is unknown about a moved base, "the change still
type-checks, imports legally, and passes every test on it" is not.

Against that, #124 states the objection to path disjointness and it is correct
as stated: a `core/protocols.py` contract change, a moved conftest fixture, a
renamed test helper, a dependency bump, a new `ruff` rule can each invalidate a
diff that touches none of those files. This repo proves the point rather than
softening it — `tests/core/test_protocol_triad.py` imports `core.protocols` and
walks the real `tests/` tree, so a base move landing a Protocol without its
triad fails the gate on a PR that touches neither file.

## Decision

### 1. The anchor answers coverage; the gate answers currency

ADR-0020 §3's single exact-match rule answers two different questions with one
instrument:

- **Coverage** — did a review actually read *this* content? That is what the
  artifact can attest and nothing else can.
- **Currency** — does the change still hold on today's base? That is what
  `ruff`, `mypy`, `lint-imports` and `pytest` establish, mechanically, in
  minutes, on every rebase and every push.

The expensive instrument is currently answering both. This ADR keeps it for
coverage and leaves currency where it already is. Nothing about the gate
changes; the change is that the review is no longer asked to re-certify what the
gate has just certified.

### 2. Coverage is anchored on the reviewed patch, not on base identity

`scripts/codex-review.sh` records, alongside `base_sha` and `tree`, a **patch
identity** for `git diff <base>...<HEAD>`. Two properties are the decision; the
mechanism is chosen to satisfy them and may not be widened:

- **insensitive to hunk offsets** — a base move elsewhere in a file the diff
  touches merely renumbers the hunk headers, and must not invalidate;
- **byte-sensitive to hunk bodies, context lines included** — a base move
  *into* the region the diff touches changes the content the reviewer read, and
  must invalidate.

**The mechanism is therefore `git patch-id --verbatim`, and specifically not
`--stable`.** Both ignore line numbers, but `--stable` also strips whitespace,
which fails the second property outright: a base move that re-indents a context
line inside a reviewed hunk — semantic in Python — would leave the identity
unchanged, and path (b) would reuse a review of content that is no longer there.
`--verbatim` "calculate[s] the patch ID of the input as it is given, do[es] not
strip any whitespace" and implies `--stable`, so it satisfies both. The
distinction is recorded here rather than left to the implementation because the
two spellings differ by one flag and only one of them is safe.

The second property is what makes this more than a proxy for the case #124
measured. It classifies both of #118's rebases the way the operator did, without
a judgement call: the #116 rebase changed `scripts/ship.sh` in the same function
region the diff touched, so the context lines and therefore the identity move,
and the re-review fires; the #117 rebase changed a file the diff's hunks never
cite, so the identity holds. That prediction is falsifiable and is the
implementation's first test, not an assumption it may inherit.

`ship` accepts an artifact when **either**:

- **(a)** its recorded base equals the PR's merge base **and** its recorded tree
  equals `HEAD`'s tree — ADR-0020 §3 exactly as written, unmodified; **or**
- **(b)** its recorded base is a **proper** ancestor of the PR's merge base,
  both patch identities are **hashable** (below) and equal, the base move clears
  §3's floor, and the drift is published per §4.

The tree comparison is not weakened, it is scoped: under (a) it refuses on any
changed byte anywhere in the tree, which is strictly stronger than any identity
computed from a diff, and it is untouched. Under (b) the base itself moved, so a
tree comparison has nothing to say — the tree legitimately differs by the base
move — and content is pinned by the patch identity, the base by §3. A recorded
base that is *not* an ancestor of the current merge base is not drift; it is a
different history, and fails closed.

**Proper is the load-bearing word: (b) is the moved-base path only.** An equal
base is an ancestor of itself, so an (b) that admitted equality would let the
patch identity govern a case (a) already covers — and govern it more weakly,
since the identity ignores hunk line numbers while the tree does not. In a file
with two identical regions, moving the reviewed edit from one to the other
leaves the identity intact and the tree changed, and (a) is what refuses it.
Where the base has not moved, (a) governs and its tree check is the whole test.

**The residual, stated rather than engineered away: the identity knows content,
not location.** Ignoring hunk offsets is the first property, so on a moved base
an identity cannot distinguish the reviewed hunk from a byte-identical
application of it elsewhere in the same file. Constructing the failure takes two
regions whose bodies *and* surrounding context are identical, a base move that
reorders them, and a rebase resolution that lands the hunk in the other one;
the reviewer would then have read the right text at the wrong place. This is
**not** repaired by narrowing (b) to base moves that avoid the diff's own files:
that is path disjointness returning under another name, it forfeits the
same-file off-hunk case that is the decision's main benefit, and it would still
not be sound. It is repaired, if it ever needs to be, by an identity that
carries location — which costs the first property and is the trade §2 already
declines. What holds meanwhile is §4: a base move inside a file the diff touches
is exactly the kind that appears in the published drift record, in front of the
human at merge.

**An entry with nothing to hash makes path (b) unavailable.** What `patch-id`
hashes per file entry depends on whether the entry has hunks, and the three
cases were measured rather than reasoned about — each check is two commands and
belongs in the implementation's tests:

- **An entry with hunks is anchored on its hunks, and its `index
  <old>..<new>` preamble is ignored.** Rewriting those blob IDs by hand leaves
  the identity unchanged. This is what delivers §2's first property, and it is
  load-bearing: an implementation that folded the `index` IDs into the identity
  would invalidate on a base edit anywhere in a touched file and defeat the
  decision. Measured: a PR hunk at line 100 of a 200-line file keeps its
  identity across a rebase onto a base that inserted a line at the top.
- **An entry with no hunks is anchored on that preamble instead, which is why a
  binary change needs no special case.** `git diff` renders it as `Binary files
  … differ`, and there the `index` line *is* hashed — mutating it changes the
  identity, and two different binary deltas to one path produce different
  identities.
- **An entry with neither is anchored on nothing but its paths.** At 100%
  similarity `git diff` emits `similarity index 100% / rename from / rename to`
  and no
  `index` line at all; a mode change emits `old mode / new mode` and no `index`
  line. The identity of such an entry is a function of its **paths alone**. So a
  reviewed PR that only renames `f` to `g`, rebased onto a base that changed
  `f`'s contents, presents a byte-identical identity while `g` now holds content
  no reviewer saw — verified directly, same id before and after.

So path (b) is **unavailable** — not satisfied — when the diff carries any entry
with neither a hunk nor an `index` line, and when either identity is empty. Such
a change falls back to (a) and the moved base costs its round. This is a
fail-closed hole in the mechanism, not a judgement about how much renames
matter; buying the case back means adding blob identity to the entry, which is
available (`git diff --raw` carries it) but trades away the offset-insensitivity
that is the whole benefit, since a raw blob hash moves whenever *any* region of
a touched file moves. The narrow rule is preferred and the trade is recorded so
the implementation does not silently take the other side of it.

### 3. Path disjointness is not adopted as a safety test, because it is not one

#124's objection stands and is not answered by special-casing. Every example it
gives — the contract surface, a conftest fixture, a renamed helper, a dependency
bump, a lint rule — is real, and there is no enumeration of "the files that
could matter" that a repository will not eventually falsify.

But look at where those examples land. Each is a **gate-detectable** failure: a
broken conftest fails `pytest`, a renamed helper fails `pytest`, a dependency
bump fails the gate that installs it, a new `ruff` rule fails `ruff check`, a
Protocol landed without its triad fails `test_protocol_triad.py`. The objection
is an argument that a change can *break* on a base it shares no paths with, and
it is correct. It is not an argument that a *review* is stale — and the thing
being reused is the review, on a branch that is rebased and fully re-gated
before it merges (§1).

So the resolution is not that the objection is wrong. It is that the objection
lands on currency, which the gate holds, and this ADR reuses only coverage.

**What survives the objection, and is therefore the floor.** One class of base
move is invisible to the gate *and* changes what a reviewer would say. A base
move touching any of these invalidates the artifact outright — no patch-identity
relief, no drift disclosure:

- `src/ai_assistant/core/protocols.py`, `src/ai_assistant/core/types.py` — the
  contract surface. Adding a Protocol breaks no gate, and ADR-0015 §5 already
  treats this surface as the class needing a second reviewer, so a base move
  landing new contract surface changes what the architecture lens would say
  about a diff that consumes it or now should. `ship.sh` already greps exactly
  this pair to decide persona requirements, so the floor costs one reuse of an
  existing regex over one extra name listing of the base move.
- `docs/review/**`, `CLAUDE.md`, `CONTRIBUTING.md`, `scripts/codex-review.sh` —
  the standing contracts the review was conducted under. A review run against a
  superseded rubric is not a review under this repo's standard, whatever its
  verdict says. The driver is in this list on the same footing as the rubrics,
  not as an implementation detail: it assembles the prompt — the ADR-0020 §1
  preamble, the persona rubric, the verdict contract — so a base move that adds
  a required instruction there conducts every later review under different
  instructions while touching no document. These paths move rarely; when they
  move, everything open should be re-reviewed, which is the correct answer and
  not a tax.

  `scripts/ship.sh` is deliberately **not** in the floor, and the boundary is
  "what the reviewer read", not "what the review loop touches". `ship` shapes no
  prompt; it applies the acceptance rule, and it applies whatever version of it
  is on disk at ship time. A stale copy of `ship` cannot exist to be reused.

**The floor reads both endpoints of every entry, not a single name.** A plain
`git diff --name-only <old_base>...<new_base>` reports only the *destination* of
a detected rename, so a base move renaming `docs/review/adversarial.md` out of
that tree would clear a floor it plainly breaches — the rubric the review was
conducted under is gone, and the listing never says so. The comparison is
therefore rename-aware and NUL-delimited (`--name-status -M -z`), and a floor
path appearing as either endpoint — source or destination — is a breach, as is
its deletion. The same reading applies to the drift record §4 publishes, so the
file set the merge reviewer reads is the file set the floor tested.

**`docs/adr/` is in the floor, for every persona.** An ADR merged under an open
lane can contradict the one that lane is writing; the gate cannot see it and no
path test will catch it. `docs/review/guide.md` §1 puts the ADRs at the top of
the authority hierarchy — "Binding — blocking" — for *every* reviewer, and
`docs/review/architecture.md` additionally names "relevant files in
`docs/adr/`" among its inputs and makes ADR adherence a blocking rubric item. A
review conducted before a decision was ratified is a review under a different
authority, so it stops covering the content on the same footing as one
conducted under a superseded rubric.

This is the clause that costs the most, and it is taken deliberately. It leaves
the tax in place for a base move that merges an ADR — common on a repo running
parallel docs lanes — while removing it for every base move that does not, which
includes #124's own measured evidence: #118's rebases moved `scripts/ship.sh`
and `src/ai_assistant/orchestration/loop.py`, and both would now be free. Where
the residual bites, §5's un-rebased path avoids it entirely, because a branch
that is not rebased has no moved base to clear.

**A per-persona floor was considered and withdrawn** — `docs/adr/**` binding
architecture, which reads and judges ADRs, and not adversarial, whose rubric is
edge cases, error paths, concurrency, data integrity and test gaps. It is
attractive because architecture is only *required* for a contract-surface change
(ADR-0015 §1), so the split would have cost almost nothing. It is withdrawn
because the authority hierarchy in `guide.md` is not scoped by persona: an
intervening memory, privacy or permission ADR can make an unchanged patch
structurally wrong, and "adversarial would probably not have noticed" is a
prediction about a reviewer, not a property of the content. A floor built on
that prediction fails open, and this floor is the part of §3 that has to be
sound.

### 4. A moved base is disclosed, never silently absorbed

When (b) accepts an artifact, `ship` **must** publish the drift in the comment
it posts: the base the review was taken against, the base being shipped on, and
the files the base move touched — **the whole set, never a bounded rendering of
it.** ADR-0025 §4 bounds the *disposition* record because a local reference
preserves its audit value; here the file set is not context for a decision, it
*is* the decision, so an omitted tail is exactly where the contradicting
`docs/adr/` entry hides. A drift list that does not fit whatever budget `ship`
enforces therefore makes path (b) unavailable, on the same footing as an
unhashable identity: the artifact falls back to (a) and the moved base costs its
round. Truncating and shipping is the one outcome §4 must not have.

This is the substantive difference from the interim operating rule, not a
formality. §3's floor is mechanical and sound, and it now covers the ADR hazard
outright. What no floor covers is §2's relocation residual and, more generally,
a base move that clears every listed path and still bears on the change. What
can be made mechanical is
the *evidence*: the exact file set, computed rather than assembled by hand, put
in front of the human who already owns the merge decision. The judgement stays
human because it is a judgement; what stops being human is the bookkeeping it
depends on — which is precisely the failure mode ADR-0020 named, an outside
observer holding an aggregate nobody wrote down.

### 5. The interim operating rule is not ratified, and is not what this replaces

The rule adopted on #124 on 2026-07-21 — "a `BEHIND` PR may merge when the base
move touches no file the PR's gate reads" — is a relaxation of **branch
protection**, not of ADR-0020 §3. Per the first fact in the Context, an
un-rebased branch's merge base never moved, so its review artifact was never at
risk; what that rule buys is skipping the rebase, and with it the re-gate.

That placement is the one where #124's objection is fatal. Merging behind means
no gate run ever saw the combination, so path disjointness would be carrying the
full weight of "this cannot break `main`" — and "the files the PR's gate reads"
is not a set anyone can eyeball: `mypy` reads the package, `pytest` reads every
conftest, and `test_protocol_triad.py` reads `src/` and `tests/` wholesale. The
rule's applications so far (#129: base move in `docs/adr/0002` and `0024`, PR in
`docs/adr/0023`) are sound *because* nothing in the gate reads `docs/adr/`
today, which is a fact about the current test suite and not a property anyone is
maintaining.

So: **this ADR does not ratify it, and does not make it unnecessary.** It stays
an operator's discretionary risk call on `main`'s health, taken with the
knowledge that no gate ran on the combination. This ADR removes the *review*
tax, which is the part the rule was reaching for and the part that can be made
sound. If the rule is wanted as a rule, it needs its own decision, and the
honest version of it is a required merge-queue gate run rather than a file-set
comparison.

### 6. #149 is the same root: named by a field it is not selected by

`.review/<sha>-<persona>.md` names the artifact by the commit. Since ADR-0020 §3
the commit has not been what the artifact is *selected* by — content is. The
name is a vestige of the pre-ADR-0020 rule, and #149 is what the vestige costs:
two runs of one SHA against different bases collide, the older-base run
finishing last replaces the current-base artifact, and `ship` rejects it as
stale though a valid review completed.

**An artifact's path carries every field the acceptance rule selects on** —
persona, `base_sha`, tree, and the ADR-0025 loop identity where the run has one
— so two runs the rule would distinguish can never occupy one path. This is the
same mechanism as §2, not a second one: once selection is by content, naming by
content is the identity function, and the collision cannot be constructed.
ADR-0025 already set this shape for the disposition snapshots
(`<loop_id>-<persona>-<tree>.md`, `codex-review.sh`); the terminal artifact
adopts it rather than inventing a second scheme. The exact field order is
implementation, bounded by one requirement: `ship.sh` currently derives the
displayed persona from the filename's trailing dash segment, and must read the
recorded provenance field instead — the name is an identity, not a parser input.

### 7. What ratification does to ADR-0020, and to ADR-0025

ADR-0017 §7 requires the operation performed on an amended ADR to be recorded
rather than inferred, in the form ADR-0018 set for ADR-0016: a qualified
`Status` line plus a dated header note, no ratified text rewritten. ADR-0026 §6
is the most recent instance and this ADR follows it exactly, including its
reason for waiting — writing "amended by ADR-0027" onto ADR-0020 while ADR-0027
is only `Proposed` is the state claim ADR-0019 forbids. The operations, to apply
on ratification:

**ADR-0020.** Its `Status` line becomes

`- Status: Accepted, §3 amended by ADR-0025 and ADR-0027`

and a dated note is appended to its header, after the existing ADR-0025 one:

`Amended: <ratification date> by ADR-0027 — §3's acceptance rule no longer
requires the recorded base to equal the PR's current merge base. Where the base
has moved, an artifact covers HEAD if its recorded patch identity is unchanged
and the move touches none of an enumerated floor: the contract surface
(core/protocols.py, core/types.py), the standing review contracts
(docs/review/**, CLAUDE.md, CONTRIBUTING.md, scripts/codex-review.sh), and
docs/adr/**. The move is then published in full at ship rather than costing a
round. Where the base has not moved, the recorded-tree
comparison stands exactly as written. The artifact is named by the anchor it
is selected by rather than by the commit it is filed under. §§1–2 are
untouched.`

**ADR-0025 takes both, with the qualifier scoped to §4.** Its header records
"the acceptance rule (recorded base and tree both match) is unchanged", and §4
says the shippable artifact is "pinned to the final `(base, tree)`" — true of
what ADR-0025 did, and stale as descriptions of the live rule once this lands. A
reader landing on §4 and relying on that phrasing would be misled, which is the
whole function of the qualifier: it warns before the text is relied on. So
ADR-0025's `Status` line becomes

`- Status: Accepted, §4's anchor description amended by ADR-0027`

— scoped deliberately, because what changes is §4's *description of the anchor*,
not what ADR-0025 decides. The persistent session, the retire-only-by-Codex
line, the proposal guardrail, and §4's own reconciliation — the shippable
artifact is the conversation's terminal verdict, not a mid-stream turn — all
stand exactly as ratified. A bare "amended by ADR-0027" would read as though
that reconciliation had been reopened. Appended to ADR-0025's header after
`Refs`:

`Amended: <ratification date> by ADR-0027 — §4's "pinned to the final (base,
tree)", and the Amends line's "the acceptance rule (recorded base and tree both
match) is unchanged", describe the anchor as ADR-0025 left it. ADR-0027 amends
that rule in ADR-0020 §3: where the base has moved, a matching hashable patch
identity and a clear floor can cover the content instead. §4's decision is
unchanged — the shippable artifact is still the conversation's terminal verdict,
pinned to whatever anchor ADR-0020 §3 defines, and its disposition snapshot is
still selected by the full anchor rather than the tree alone.`

Nothing else in either document is edited.

## Alternatives considered

**Path disjointness as the acceptance test (#124's cheap direction).**
Rejected as stated, for its own objection and for a second reason the issue does
not have: relaxing the base comparison while the tree comparison stands changes
no outcome at all, because a rebase moves both. What is kept from it is the
base-move file listing — demoted from an acceptance test to §3's floor and §4's
published evidence, and read rename-aware in both roles.

**Drop the base comparison entirely and anchor on the tree alone.** Rejected for
the reason `ship.sh` already records: a review run against a narrower base
(`just review-codex adversarial HEAD~1`) covers only part of the PR and would be
accepted. §2 (b) requires the recorded base to be an *ancestor* of the merge
base for exactly this reason.

**Ratify the interim operating rule.** Rejected — §5.

**Widen the ADR-0025 in-flight claim to cover the artifact path** (#149's second
option). Rejected as a fix for #149: it serializes the collision rather than
removing it, so the last writer still wins, and it leaves the artifact named by
a field the acceptance rule stopped using. It also solves nothing for #124,
whereas §2 and §6 are one mechanism.

**Re-review on a moved base but with a cheaper reviewer** — a diff-only prompt,
or one persona instead of two. Rejected: it prices the round down without
answering whether the round is needed, and ADR-0020's alternatives already
rejected skipping a lens on a class of change.

## Consequences

**Easier.** The dominant cost #124 measured is gone: an unrelated merge, a
rebase onto it, and a re-gate no longer cost a Codex round per persona per open
lane. The saving grows with lane count, which is the axis ADR-0015 deliberately
runs hot. #149 becomes unconstructible rather than unlikely. The merge reviewer
gains a base-drift record that no one produces by hand today.

**Harder.** `ship` gains a second acceptance path, and its refusal messages must
now distinguish three states, not two: content moved, base moved past the floor,
and history diverged. The patch identity is a fourth provenance field to record
and keep stable, and its normalization is a correctness surface where the safe
and unsafe spellings differ by one flag — a patch identity that is *too*
insensitive silently accepts a review of content that is no longer there, which
is why §2 fixes `--verbatim` rather than leaving the choice open, and why §2
keeps the tree comparison whole on the unmoved-base path rather than replacing
it. The §3 floor also keeps the tax on any base move that merges an ADR (§3),
which on a repo running parallel docs lanes is a large share of them — the
saving is concentrated on code lanes and on the cross-lane merges #124 actually
measured. The residual that remains, §2's relocation case, is a real,
gate-invisible hazard carried deliberately, mitigated by disclosure rather than
by prevention.

**#153 is not broken, stated plainly.** `scripts/review_history.py` parses the
ship comment: the `<!-- ship:<sha> -->` marker and the summary line carrying
round, net lines, commits and churn ratio. Neither changes. The marker keys on
the commit, which stays correct — a ship comment is about a pushed commit, and
it is the `.review/` *filename*, not the marker, that this ADR renames. The
summary line's fields and format are untouched; §4's drift record is a new,
optional block **later in the comment body**, after the summary, leaving the
marker and the header line that must follow it (`ship.sh`) in place. A parser
reading those two lines is unaffected; a parser that assumes the body contains
nothing but persona `<details>` blocks would see one more block.

**Revisit if** an accepted (b) ship is followed by a finding that a re-review
would have caught despite the floor being clear, which argues for a cheap
contradiction check rather than a wider path list. Or, in the other direction,
if the `docs/adr/**` floor is observed costing rounds for base moves that merged
an ADR as `Proposed` — a status that binds no reviewer (`guide.md` §1 makes the
*ratified* ADRs binding) — which argues for narrowing that floor entry to a
ratification rather than any edit under the tree. Or if the patch identity is
observed accepting content it should not have — including §2's relocation
residual, whose remedy is a location-carrying identity, not a narrower (b) —
which argues the mechanism, not the split in §1.

**Follow-on.** Implementation is a separate PR — a review-contract decision
ratified before anything builds on it, which is the ratify-before-build
principle ADR-0025's own follow-on invokes, not golden rule 5, which governs
Protocol and `core` surface: `scripts/codex-review.sh` records the patch
identity and names the artifact by its anchor; `scripts/ship.sh` gains
acceptance path (b), the §3 floor check, the §4 drift rendering, and reads the
persona from provenance rather than from the filename; `CLAUDE.md` and
`CONTRIBUTING.md` carry the one-line restatement of when a base move costs a
round.

The acceptance rule is a fail-closed surface, so the implementation owes a test
per branch of it, not only the happy path: #118's two rebases (§2's falsifiable
prediction — the #117 rebase holds the identity, the #116 rebase moves it); a
whitespace-only change to a context line inside a reviewed hunk, which must
invalidate; **each** floor path — the two `core` files, the review documents and
the driver alike — changed, deleted, renamed *out* of the floor and renamed
*into* it (§3), `docs/adr/**` included and for both personas; a recorded base
that is not an ancestor of the merge base, and
an *unmoved* base whose reviewed edit has been relocated between two identical
regions — same identity, different tree, refused by (a) because (b) requires a
proper ancestor; a rename-only and a mode-only diff rebased onto a base that
changed the renamed file's content, which §2 measured as producing an identical
identity; and a drift list that does not fit the publishing budget, which must
refuse rather than truncate (§4). Every one of those must refuse.
An implementation that satisfies only the #118 cases would accept several of
them.

Two must *accept*, and they are not decoration — they are what stops a
fail-closed implementation from satisfying the list above by refusing
everything: the #117 rebase, and the same-file off-hunk case, where the base
edits a region of a file the PR also touches without entering any reviewed hunk.
The second is the one #118 does not cover and the one an implementation folding
the `index` blob IDs into the identity would fail, and it is the benefit this
whole decision is for.

### The strongest case against this decision

The split in §1 assumes the gate is a faithful proxy for "still correct on this
base", and it is only as good as the test suite. A subsystem with thin coverage
gives the objection its teeth back: the base moves, the gate passes because
nothing exercises the interaction, and the review that would have noticed is the
one being reused. That is not hypothetical — coverage is uneven by construction
in a repo being built subsystem by subsystem.

The answer, and it is partial. The failure requires a base move that breaks the
change, is invisible to the gate, is outside §3's floor, and would have been
caught by a reviewer reading a diff the base move does not textually touch —
a reviewer that never sees the two changes side by side either, since it reads
the diff against its own base. Against that, the measured cost is present in
every session, and #118's #117 rebase is a review run that provably could not
have produced a finding. The trade is a bounded, disclosed risk against a
certain, recurring cost, and §4 exists because the residual is real rather than
argued away.
