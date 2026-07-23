# 43. Explicit review markers: a grounded withdrawal and a tagged proposal replace inference

- Status: Proposed
- Date: 2026-07-22
- Amends: ADR-0025 §2 and §3. §2 required a finding to be "retired only by
  Codex's own updated assessment, recorded in the review artifact." The v1
  implementation retires a finding by **inferring** withdrawal from its *absence*
  in a later round (`codex-review.sh` `_write_snapshot`), and detects a §3
  proposal by a **fence heuristic** (`ship.sh` `render_dispositions`). Both infer
  a reviewer signal the reviewer never emitted. This ADR replaces each inference
  with an explicit marker the reviewer emits — a grounded `WITHDRAW <finding-id>`
  citing a prior finding, and a tagged `PROPOSAL` block bound to the finding it
  follows — and makes absence fail closed. ADR-0025's decision text is unchanged;
  this sharpens *how* two of its rules are met. The `Status`/`Amended` edit this
  makes to ADR-0025 is **recorded in §5 below to apply on ratification, not made
  now** (ADR-0026 §6, ADR-0031 §7): writing "amended by ADR-0043" onto a ratified
  ADR while ADR-0043 is only `Proposed` is the state claim ADR-0019 forbids.
- Refs: #144 (explicit grounded withdrawal), #145 (explicit proposal format),
  PR #143 (the honest-rendering fix this builds on). ADR-0027 §3 (this touches
  the review-contract floor). ADR-0001 (ADRs are append-only; ADR-0025's body is
  not rewritten). ADR-0019, ADR-0026 §6, ADR-0031 §7 (an amendment edit to a
  ratified ADR is recorded to apply on ratification, not made while `Proposed`).

## Context

ADR-0025 gave the review loop a persistent session and two audit rules that make
its added capabilities checkable after the fact:

- **§2** — a finding is retired only by Codex's own recorded reassessment, never
  by author assertion. This is what keeps the author from *authoring the verdict*.
- **§3** — a Codex-proposed fix is recorded and published in full alongside the
  change, so the human at merge can compare what Codex proposed against what was
  committed. This is what keeps a wholesale paste from becoming a self-review.

Both rules are about a **signal the reviewer emits**. The v1 implementation,
however, *infers* both signals rather than reading an emitted one:

1. **Retirement is inferred from absence.** `_write_snapshot` carries a prior
   finding forward as `retired` when this round did not re-raise it. Absence is
   not a reassessment: the reviewer may have dropped the finding on reflection,
   or the author's code change may have resolved it, or the reviewer may simply
   have run out of context and not mentioned it — the record cannot tell which,
   so it asserts none. PR #143 already made `ship`'s *rendering* honest about
   this ("no explicit withdrawal was recorded; verify against this PR's diff").
   But the underlying `status=retired` is still an inference #144 argues is
   ADR-0025 §2-invalid *even with honest rendering*: §2 wants a grounded
   `WITHDRAW <id>` the reviewer actually emits, and a silent disappearance
   treated as **still open**, not retired.

2. **A proposal is detected by a fence heuristic.** `render_dispositions` treats
   any fenced ```` ``` ```` block in a finding as a possible §3 proposal —
   published in full within the cumulative budget, else excluded fail-closed. A
   proposal written in **prose** ("replace `allow=True` with `allow=False` in
   `authorize()`") carries no fence, so it is treated as ordinary finding text
   and can be silently omitted by the budget — defeating exactly the §3
   authorship comparison the rule exists to guarantee (#145).

Both defects share one root and one fix direction: **replace an inferred signal
with an explicit marker the reviewer emits, and fail closed on its absence.**
This matters because review runaways are the dominant review cost (ADR-0020,
ADR-0025 Context), and a firmer marker contract is what lets the audit record be
trusted without a human re-deriving each disposition by hand.

This is a change to the **review contract** — the prompt the reviewer answers,
the parse in `codex-review.sh`, the render in `ship.sh`, and the rule text in
`docs/review/**` — not to a `core/protocols.py` Protocol. Golden rule 5's
ratified-before-implementation rule therefore does not strictly bind it, but the
weaker *ratify-before-build* principle ADR-0025 itself followed does: it is
reviewed under both the adversarial and architecture lenses because it moves the
standing review contract (ADR-0027 §3's floor), and its implementation is a
separate PR tracked by #144 and #145.

## Decision

We replace each inferred signal with an **explicit marker the reviewer emits**,
grounded to a finding by the stable id the driver already computes, and we make
the absence or malformation of a marker **fail closed** — never a fabricated
disposition. Three parts and a set of implementation obligations follow.

**The parse is governed by four fail-closed principles; the exact recogniser is
implementation.** The decision below fixes *what the contract guarantees*, not the
byte-level parser — that is delegated to the implementation PR (as ADR-0025 §4
delegated its schema), which must satisfy these invariants under every input:

1. **No fabricated disposition** — nothing retires or records a proposal except a
   well-formed, reviewer-emitted marker meeting the grammar.
2. **No lost finding** — no input, malformed markers included, drops a real
   finding from the **recorded** review (the terminal artifact plus the complete
   disposition record). This governs the parse and the record, not the *published
   comment*, whose disposition rendering ADR-0025 §4 already bounds — a
   carried-forward `open` finding may be summarised under §4's omission signal
   ("…N more finding(s) omitted; the complete record is in `.review/`") rather than
   shown in full. What this principle forbids is a finding *lost from the record*,
   not one condensed in the budgeted rendering §4 governs.
3. **No marker parsed from payload** — a marker-looking line that is quoted (inside
   a Markdown code fence) or inside a recognised proposal region is text, never a
   signal.
4. **Fail closed on ambiguity, and refuse losslessly** — an ambiguous or malformed
   marker resolves toward the safe state (finding stays `open`, no structured
   proposal), never a guess; where the review's structure itself is broken, the
   round is refused and re-run (below), not silently recovered. **Every refusal is
   lossless**, wherever it is triggered (a malformed proposal, a duplicate
   `WITHDRAW` or proposal, a missing verdict): before the re-run is requested the
   driver **retains the rejected round's complete raw output in `.review/`, records
   every complete parseable finding as `open`, and re-injects the retained raw
   output — the undecidable tail included — into the re-run's prompt** so the
   reviewer sees it and either re-raises a candidate finding from it or consciously
   drops it. A re-run is therefore *informed*, never blind: what can be parsed is
   already recorded open, and what cannot (a numbered line after an unterminated
   proposal that may be a new finding or proposal body) is put back in front of the
   reviewer rather than silently discarded — the fail-closed best for input whose
   structure is genuinely undecidable (principle 2). **The tie-breaker is explicit: when a
   line *could* be a marker or *could* be payload (list-item continuation, a quoted
   line, lazy paragraph text), it is payload.** No lexical rule is fully unambiguous
   against adversarial Markdown, so the contract does not rest on one — a
   marker-candidate is honoured only where its structural position is unambiguous
   (below), and every residual doubt falls to payload, where the cost is a
   still-`open` finding, never a fabricated disposition.

**Markers are recognised only outside Markdown code fences** (principle 3).
`WITHDRAW`, `PROPOSAL`, and `END PROPOSAL` are signals only as *top-level review
prose*; a line matching the grammar **inside a fenced block** — of any standard
Markdown fence form (three-or-more backticks, or three-or-more tildes `~~~`) — is
**payload, not structure**. A review OF this very mechanism quotes these tokens,
so treating a fenced `WITHDRAW …` as a real withdrawal would let quoted text
fabricate the exact signal this ADR makes explicit. Fence-awareness precedes
marker recognition in the parse order (as it precedes the finding split, §2). The
set of fence forms the recogniser must honour is the standard CommonMark set; the
exact recogniser is implementation, held to principle 3.

### 1. Withdrawal: a grounded `WITHDRAW <finding-id>` retires; absence does not

**The id.** A finding's identity is the driver-assigned stable id already minted
by `_finding_id` — `<persona>-<12 hex>`, a hash of the finding's normalised
text, stable across reformatting and rank shifts (ADR-0025 §4). The reviewer does
not compute this id; the **driver surfaces it**. Every round for which prior
findings exist, the prompt presents a roster of the loop's still-open findings,
each as one line: its id and a short label (the finding's first line, truncated).
This roster is **separate from, and far smaller than, the full disposition
injection** ADR-0025 §1 bounds — id + one truncated line per open finding, not each
finding's whole grounding — so the two budgets do not conflict: §1's cold floor may
drop the full dispositions while the compact roster still fits. The roster is
**never truncated**, because a dropped id is a finding the reviewer cannot ground a
`WITHDRAW` against — silently un-retirable. But it is also **not made mandatory to
the point of deadlock**: if even the compact roster cannot fit the input budget (a
loop with so many open findings that their id-lines overflow the diff's remaining
room), the round drops to **ADR-0025 §1's floor — a plain cold review of the diff,
with no roster and therefore no withdrawals that round**, and **every prior finding
stays `open`** (fail-closed: nothing is retired when the reviewer cannot see the
ids). This is the same floor §1 already defines for oversized dispositions, reused
rather than replaced — a withdrawal simply waits for a round whose roster fits, and
until then the findings stay visibly open, never lost. On the warm path the resumed
session is handed the roster (it never saw the ids assigned); on the cold/degraded
path the re-injected snapshot already carries the `<!-- finding id=… -->` headers,
and the roster is the same id set drawn from it. The reviewer grounds a withdrawal
by citing a roster id.

**The marker, and where it lives.** Withdrawals are emitted in a **dedicated
`## Withdrawals` section** the reviewer writes after its ranked findings and before
the verdict — one marker per line, at column 0 of that section:

```text
## Withdrawals

WITHDRAW <finding-id> — <grounding>
WITHDRAW <finding-id> — <grounding>
```

A dedicated section, rather than a marker recognised anywhere in the body, is what
removes the structural ambiguity round 10 identified: an indented
`WITHDRAW …` inside a finding's Markdown body is the finding's prose, not a signal
(principle 4's tie-breaker). Only a column-0 line in the `## Withdrawals` section
is a withdrawal; a `WITHDRAW`-looking line anywhere else is payload. **The section
is unique and terminal**, fixed deterministically: it runs from the **first**
`## Withdrawals` heading that has **no top-level finding between it and the verdict**,
through to the verdict. A `## Withdrawals` heading *followed by* a top-level finding
is **not** terminal — it is a mid-findings heading and is **payload** (so the finding
after it survives as a real finding, §2 parse), retiring nothing (principle 4). A
*further* `## Withdrawals` heading appearing **within** the already-open terminal
section is simply an in-section heading — its `WITHDRAW` lines are part of the one
section, never a competing section and never discarded. So "first qualifying heading
to the verdict" names exactly one section with no withdrawal lost, deterministically. (The section heading text, the column-0
requirement, and this unique-terminal boundary are the structural anchor; the exact
heading recogniser is implementation, held to the four principles.) The marker
form is:

```text
WITHDRAW <finding-id> — <grounding>
```

- `WITHDRAW` is a case-sensitive keyword anchored at line start.
- `<finding-id>` is a single whitespace-delimited token that must equal the id
  of a prior finding currently **open** in this loop (as surfaced in the roster).
- `<grounding>` is required, non-empty text — the reassessment itself: what the
  reviewer now concludes and why (a fact the author supplied, a constraint the
  finding overlooked, a reconsideration). The separator between id and grounding
  is a punctuation delimiter (`—`, `-`, or `:`); the exact tolerance is
  implementation. A bare `WITHDRAW <id>` with no grounding is **not** a
  reassessment and does not retire. **Grounding is a single line** — the remainder
  of the `WITHDRAW` line; a reviewer needing more context states it compactly there,
  not across multiple lines. This is what keeps the withdrawals section
  structurally clean: it contains only `WITHDRAW` lines and blanks, so no
  ordered-list or finding-looking line (`^ {0,3}[0-9]+[.)]`) ever appears inside it,
  and the terminal-section detection ("no top-level finding after the heading")
  cannot be fooled by a multi-line grounding that embeds a numbered list — such a
  list after `## Withdrawals` is therefore always a real finding, and the heading
  before it a mid-findings payload heading (§2), never a lost withdrawal.

**The effect — and the three statuses.** A finding has one of three statuses:
`open`, `pending-withdrawn`, and `withdrawn`. A well-formed, id-matching, grounded
`WITHDRAW` marks that finding **`pending-withdrawn`**, carrying its grounding text
forward — *recorded* as withdrawn, but **treated as `open`** for a later round's
roster and for silence (§1 rule 3) until a successful `ship` publishes its
grounding, at which point it becomes **`withdrawn`** (§3, publication gates
retirement). This distinction is what makes §1 and §3 consistent: a withdrawal is
the §2 "recorded reassessment" the moment it is emitted, but it does not *retire*
the finding — for the merge reviewer or the next round — until its grounding has
actually reached the record the human at merge reads (ADR-0025 §4).

**This round's explicit output outranks a carried-forward status — the
precedence rule.** A finding's status each round is decided in this order, and
the first match wins:

1. **Raised this round** (it appears as an open finding block) → `open`. A later
   round that raises a finding whose id was previously `withdrawn` or
   `pending-withdrawn` **reopens it**: the defect is live again (a code change
   reintroduced it, or the reviewer no longer stands by the withdrawal), and a live
   re-raise must never be suppressed by an older withdrawal. A withdrawal is
   permanent only *across silence*, not against a re-raise — this is what keeps the
   no-silently-lost-finding floor true when a withdrawn defect returns.
2. **Withdrawn this round** by a valid grounded `WITHDRAW`, and not also raised
   → `pending-withdrawn` (→ `withdrawn` once published, §3). (Raised *and*
   withdrawn in one round is contradictory and stays `open`, §3.)
3. **Neither** (silence) → carry the prior status forward unchanged, **treating
   `pending-withdrawn` as `open`** (it is surfaced in the roster and can be
   re-raised or re-withdrawn): `withdrawn` stays `withdrawn`, `pending-withdrawn`
   stays `pending-withdrawn` (open to a later round), `open` stays `open`.

**Absence retires nothing.** The `retired`-on-absence rule is removed. By rule 3
a prior finding this round neither re-raises nor withdraws stays `open`, carried
forward, and is rendered as open ("raised in an earlier round and still open —
not explicitly withdrawn; verify against this PR's diff"). Silence is not a
signal. This is #144's core, and it is the fail-closed direction: a finding that
should have been withdrawn but was not stays visible and costs the author a
verify (or a grounded reject/waive on the PR, the §2 recourse), where the old
inference would have *hidden* a live finding on a reviewer's silence.

### 2. Proposal: a tagged `PROPOSAL` block bound to the finding it follows

The proposal marker grounds **differently from `WITHDRAW`, and deliberately
so.** A withdrawal names a *prior* finding, whose id the driver has already
computed and can surface in the roster; but a proposal is offered for a finding
the reviewer is raising **in this same output**, and the driver computes that
finding's id only *after* the round, by hashing the finding text. The reviewer
therefore cannot emit the id of a finding it is raising — so the proposal is
**not** grounded by an emitted id. It is bound **positionally**.

To offer a fix, the reviewer places a delimited block after the finding it
addresses, **separated from it by a blank line**:

```text
1. **major** the value is compared before it is validated  (a finding)

PROPOSAL
<the proposed change — prose, a patch, or fenced code>

END PROPOSAL
```

- `PROPOSAL` opens the block on its **own column-0 line, preceded by a blank
  line**, and `END PROPOSAL` closes it on its **own column-0 line, likewise
  preceded by a blank line, not inside a code fence** — the two delimiters are
  symmetric. Two rules make each **deterministic**, so there is no ambiguity for
  principle 4 to resolve, only a fixed grammar:
  - *the blank line* — a column-0 line not set off by a blank line is a CommonMark
    *lazy continuation* of the text above it, hence payload: a `PROPOSAL` not
    blank-line-separated is a finding's prose, an `END PROPOSAL` not blank-line-
    separated is proposal-body text.
  - *the fence* — the terminator is the first blank-line-separated column-0
    `END PROPOSAL` **outside any code fence** (principle 3). **This is the normative
    escape**: to place a literal `END PROPOSAL` in the proposal body, fence it — a
    proposal body is normally a fenced patch anyway — and inside the fence it is
    payload, never the terminator. An author who writes a blank-line-separated
    column-0 `END PROPOSAL` in *un-fenced* prose has written the terminator, by this
    rule, deterministically; nothing is ambiguous, so nothing is guessed.

  The block carries **no id**: the driver binds it to the **finding block it
  follows** (a finding raised or re-raised this round, the blank line
  notwithstanding) and records it under that finding's computed id.
- **Every malformed proposal structure *in the findings area* refuses the round;
  nothing degrades to budget-omittable payload.** (Proposal recognition applies only
  to the findings area — the terminal `## Withdrawals` section is not scanned for
  proposals, below — so this rule never fires on a `PROPOSAL`-looking line there.) A
  proposal is audit-bearing under ADR-0025 §3 — it must be published in full or the
  finding routed to independent review — so a proposal-shaped block that cannot be
  *recorded as a structured region* must not quietly become ordinary text the
  disposition budget can drop. Three findings-area cases all **reject the review and
  ask for a re-run** (principle 4, the same fail-closed
  move a missing verdict line already triggers): a `PROPOSAL` with **no
  `END PROPOSAL`** (undecidable extent — the driver cannot tell the proposal's own
  numbered lines from the next real finding); a terminated `PROPOSAL` **preceded by
  no finding** (nothing to bind to); and **two or more `PROPOSAL` blocks for one
  finding** in one round (ambiguous which is authoritative, §2 below).
  **Refusing is lossless — nothing in the rejected output is discarded.** Two things
  happen before the re-run is requested (per principle 4's lossless rule): (a) the
  driver **retains the rejected round's complete raw output** in the durable
  `.review/` record, so *every* line — including the undecidable tail after an
  unterminated `PROPOSAL`, where a `2. blocker B` may be a new finding or the
  proposal's own body — survives verbatim; (b) it **records every complete finding
  it can parse before the structural break as `open`**, first-class in the
  disposition record immediately; and (c) it **re-injects that retained raw output
  into the re-run's prompt**, so the reviewer sees the undecidable tail and either
  re-raises B or consciously drops it — the re-run is informed, not blind. Thus no
  finding is lost even if the re-run differs (principle 2): what can be parsed is
  recorded open, and what cannot is both preserved raw and put back before the
  reviewer, never guessed at nor silently discarded. The malformed
  proposal itself is **not** recorded as a structured region — so it can never
  masquerade as a published §3 audit or slip past the budget as opaque text (the
  round-14 concern) — and the finding it attached to takes independent review. So
  refusing re-emits for a clean proposal **without discarding anything**; a
  marker-less or well-formed review is untouched (the no-marker floor, §3).
- **One region-aware left-to-right pass decides every region, so the rules cannot
  conflict.** Rather than separate ordered extractions that can contradict, the
  driver makes a single top-down pass tracking which region each line is in — a code
  fence, an open `PROPOSAL` region, the findings area, or the terminal
  `## Withdrawals` section — and the region a line opens **first** wins:
  - Inside a **code fence**, everything is payload (principle 3).
  - Inside an **open `PROPOSAL` region** (findings area), everything up to its
    `END PROPOSAL` is payload — a `## Withdrawals` heading or a `WITHDRAW` line
    there is the proposal's text, not structure.
  - The **terminal `## Withdrawals` section** runs from the **first** `## Withdrawals`
    heading (outside a fence and an open proposal region) with **no top-level finding
    between it and the verdict** — "terminal" means exactly that: only withdrawals and
    the verdict follow it. A further `## Withdrawals` heading inside that span is an
    in-section heading (its `WITHDRAW` lines still count), never a rival section. A `## Withdrawals` heading that *is* followed by a
    top-level finding is **not** the terminal section but a **mid-findings heading,
    hence payload** (§1) — so the finding after it survives as a real finding, never
    consumed as section payload (that is what keeps the preamble's "no lost finding"
    true here). Withdrawals written under such a misplaced heading are payload too
    and simply do not process, which is fail-closed (no withdrawal fabricated,
    findings stay `open`). The section runs from the true terminal heading to the
    verdict. **Proposal recognition does not apply inside it**: a `PROPOSAL`-looking
    line in the withdrawals section — even an unclosed one — is withdrawal-section
    payload, neither a bindable proposal nor a malformed-proposal round-refusal.
    (This is what resolves the precedence: the
    "unterminated `PROPOSAL` refuses the round" rule above is scoped to the
    **findings area**, where a proposal can legitimately open; the withdrawals
    section is not scanned for proposals at all.)
  - The **findings area** is everything before that section; proposal regions are
    recognised and extracted here, then the remaining text is split into findings.
  Because the pass extracts each proposal region and the withdrawals section before
  the finding split, a finding's id is computed from finding text with both already
  removed — so a re-raised finding keeps its id whether or not the round also
  withdrew something or attached a proposal. Marker-looking content inside a
  recognised region — a numbered list, or a fenced literal `END PROPOSAL` — is
  payload; the region's close is its delimiter under the escaping already used for
  framing markers.
- **The proposal region is removed from the finding block *before* `_finding_id`
  is computed.** A finding's identity must not depend on whether it carries a
  proposal, or the *same* finding raised with a proposal in one round and without
  one in another would hash to two different ids — splitting one finding into two
  and breaking the positional binding's claim to "that finding's computed id."
  So the driver strips the `PROPOSAL … END PROPOSAL` region out of the block, then
  hashes the remaining finding text for the id, then records the stripped proposal
  under that id. Identity is a function of the finding text alone, proposal or not.
  (The *normalisation* that can make two distinct findings collide on one id is a
  pre-existing property of `_finding_id`, tracked in #276 — but because ADR-0043
  newly makes the id an authoritative **withdrawal target**, collision-free
  identity stops being cosmetic and becomes a **fail-closed prerequisite of this
  ADR's implementation**: see §3 and §4.)
- **At most one proposal per finding per round.** The grammar permits a reviewer
  to write two `PROPOSAL` blocks for one finding in a single round (a P1 then a
  "corrected" P2); the driver cannot reliably know P2 supersedes P1, so it does
  **not** guess — nor does it degrade to budget-omittable payload, which would let
  an audit-bearing patch (§3) slip past. Two or more proposal blocks bound to one
  finding in one round **refuses the round** (above), re-emitting the whole review
  so neither block is lost or falsely published as *the* proposal. A well-formed
  finding carries exactly zero or one proposal region.
- The body between a single block's markers is the proposal, recorded as a
  **first-class region** in the snapshot (`<!-- proposal finding=<id> … --> …
  <!-- /proposal -->`, the id being the bound finding's), with the framing markers
  inside the body escaped exactly as finding text already is (so a proposal that
  quotes `-->` cannot truncate the record).
- **Every distinct proposal a finding received across the loop's rounds is carried
  forward in the snapshot, so the terminal snapshot publishes them all — without
  touching ADR-0025 §4's anchor.** ADR-0025 §3's audit compares *what Codex
  proposed* against *what was committed*, so it must hold whichever round's proposal
  the author adopted: if round 1 proposes P1, the author materially adopts P1, and
  round 2 revises it to P2, an audit that saw only P2 would let Codex effectively
  certify P1-derived code the merge reviewer never compared against P1. The fix
  keeps ADR-0025 §4 intact — `ship` still renders **only the terminal artifact's
  tree snapshot**, never other trees' — by making that snapshot **self-contained**:
  each round's snapshot **carries forward every distinct proposal each finding has
  received** (append-only per finding, labelled by round), exactly as it already
  carries forward a retired finding's text. So the terminal snapshot holds P1 *and*
  P2, `ship` renders that one snapshot (§4 unchanged, unamended), and both are
  published under §3's unchanged publish-in-full-or-exclude rule. A proposal is
  never silently replaced by a later one, and no off-terminal-tree snapshot is ever
  posted. This resolves what #275 raised, folded into ADR-0043 rather than deferred
  because the explicit-proposal contract is where §3's cross-round provenance must
  be made sound (the mechanism — de-duplicating identical proposals across rounds,
  ordering them — is implementation).

`ship` then identifies a proposal by **the recorded region**, not by a fence, and
applies the unchanged §3 rules to it: published **in full** within the cumulative
byte budget, else **excluded — not truncated** — with the finding taking ordinary
independent review; secret-scanned over the whole region and excluded fail-closed
if a plausible secret is present (ADR-0025 §3). A prose proposal is now detected
because it is *marked*, closing #145.

**ADR-0025 §3's routing rule is binding and this ADR preserves it, not defers it:**
a materially-proposal-derived change "is Codex's output" that "no Codex session may
certify," and "is treated as Codex-authored and routed to a human or genuinely
different model unless independently certified." ADR-0043 does not weaken that.
What ADR-0025 §3 *defers* is only the **mechanical** enforcement — a machine-readable
provenance field that "`ship` refuses a terminal verdict without" — with v1 resting
on the author's discipline plus the human comparison at merge that ADR-0043's
published proposals make possible. The one case ADR-0043 must **strengthen** is an
**excluded** proposal (secret, or over the aggregate budget): there the human
comparison is defeated — the proposal is not published, so the merge reviewer has
nothing to compare the committed code against. So an excluded proposal is surfaced
to the merge reviewer **with §3's routing requirement flagged**: that finding's
change must be **independently certified** (human or genuinely different model), not
cleared on the Codex terminal verdict alone, exactly because Codex may have authored
it and the evidence to tell is unpublishable. The full *mechanical* tree-level gate
stays §3's deferred upgrade; the binding routing rule, and its explicit surfacing
for the excluded case where v1's comparison cannot run, are preserved here.

The rule is applied **per finding over its whole set of carried-forward
proposals**: because the §3 audit needs *every* proposal that could have authored
the committed code, publication for a finding is all-or-nothing. If a finding's
complete distinct-proposal set (P1, P2, …) cannot all be published in full within
the budget — or any one carries a secret — the **finding is routed to independent
review** (its Codex proposals excluded from the published record, none shown in
part), never some-published-some-omitted. Fail-closed at the finding, so a partial
proposal set can never masquerade as the complete authorship comparison §3 requires.

### 3. Fail-closed behaviour and the degradation floor

Every ambiguity resolves toward the safe, honest direction — no fabricated
disposition, no silently lost finding, no broken in-flight lane.

- **A `WITHDRAW` citing an unknown id, or carrying no grounding, has no effect on
  the status §1's precedence selects.** The marker is ignored; it does not add a
  status of its own. So the finding's status is exactly what §1 decides: if it was
  **also re-raised** this round it is `open` (precedence rule 1 — a genuine reviewer
  signal, which an invalid marker is not), and if it was **not** raised it keeps its
  carried-forward status (a validly `withdrawn` finding stays `withdrawn`; an `open`
  one stays `open`). An invalid marker thus never reopens *and* never suppresses — it
  is inert, leaving §1 to rule. The stray marker is surfaced in the round's
  diagnostics rather than silently dropped.
- **A finding both re-raised (open) and named by a `WITHDRAW` in the same round**
  stays `open`. A reviewer that both holds and withdraws a finding is
  contradictory; the fail-closed reading keeps it visible.
- **Two `WITHDRAW` lines for the same id in one round refuse the round.** Both may
  be well-formed with different groundings ("constraint X makes it safe" then "the
  prior test was misread"), and which is *the* recorded reassessment cannot be
  resolved by a parser rule without an arbitrary first/last choice — the verdict-
  changing evidence must not depend on that. So a repeated id in one round's
  withdrawals is ambiguous input and rejects the review for re-emission (§2's
  fail-closed pattern), rather than persisting one grounding and dropping the other.
  The refusal is **lossless** like every other (principle 4): the rejected raw output
  is retained and this round's parseable new findings are recorded `open` before the
  re-run, so a re-emission that drops a newly raised finding cannot lose it.
- **A shared id is a re-raise or a collision, told apart by a canonical identity,
  not the display hash — and only a collision fails closed.** Two representations of
  a finding must be distinguished. The **display hash** is `_finding_id` — lossy by
  design (it drops the rank enumerator, markdown, and, per #276, non-ASCII and
  punctuation), which is what the reviewer *cites* in a `WITHDRAW`. The **canonical
  identity** excludes only *permitted presentation changes* — the rank enumerator,
  emphasis, whitespace — while **preserving meaning-bearing content** the display
  hash drops. Sameness is judged by the canonical identity: **same canonical
  identity = the same finding** (a re-raise; reopen per §1, one record), so round 1's
  `1. **major** Foo` and round 2's `2. **major** Foo` are correctly one finding
  across the rank shift — the stable-id property §2 promises. A **collision** (#276)
  is the narrower case of **distinct canonical identities that share one display
  hash** (e.g. findings about `café` and `cafè`, which the display hash's lossy
  normalisation merges): only *that* fails closed. Because the display hash is now a
  withdrawal target, the implementation must detect such a collision across **every
  persisted finding identity in the loop — this round's findings and every
  carried-forward finding, `open`, `pending-withdrawn`, or `withdrawn`** (colliding
  with a withdrawn id would otherwise overwrite its record and lose the withdrawal),
  and keep the distinct findings `open` without dedup-dropping, retiring, or
  overwriting either, never resolving it by guessing. Defining the canonical
  identity (which presentation changes it excludes; a collision-free key distinct
  from the display hash) is the #276 mechanism; the fail-closed obligation and this
  canonical-identity-vs-display-hash discriminator are ADR-0043's.
- **Publication gates retirement: a `pending-withdrawn` finding is treated as
  `open` until a successful `ship` has published its grounding.** ADR-0025 §4
  requires a retirement's deciding context to reach the merge reviewer ("a dialogue
  whose deciding context cannot be published does not retire the finding"). The
  strongest and simplest way to honour that is to make publication the
  **precondition** for retirement, not a later step that might silently fail: a
  `WITHDRAW` records the finding `pending-withdrawn` with its grounding (§1), but a
  `pending-withdrawn` finding is **treated as `open`** — surfaced in every later
  round's roster, and absent-implies-still-`open` — **until a successful `ship` has
  published that grounding**, which promotes it to `withdrawn`. A successful ship is
  what *confirms* the retirement; only a confirmed `withdrawn` reads as retired to a
  later round or the merge reviewer.
  This closes the race the round-by-round design kept re-exposing. A grounding that
  can *never* be published — it carries a secret the §3 scan excludes — is rejected
  when the round is recorded, so it never even provisionally retires. And if a
  terminal ship cannot fit every pending withdrawal grounding within the comment's
  hard limit, it **fails closed** (refuses to post, the oversized-report path it
  already takes) rather than omit one — so a retirement is never *confirmed* without
  its grounding, and none is silently lost either: the finding simply stays `open`
  until a ship succeeds. There is thus **no window** in which a finding is treated as
  retired while its grounding is unpublished — an author who commits and starts the
  next round before shipping loads an `open` finding it can re-examine, which is
  exactly ADR-0025 §4 made structural rather than argued. (Whether the
  pending-vs-confirmed state lives in the snapshot, is recomputed from the published
  artifact, or is fed back by a successful ship is mechanism, held to this
  invariant.)
- **A malformed `PROPOSAL` structure refuses the round (§2).** An unterminated
  block, a terminated block with no finding to bind to, and two blocks for one
  finding all reject the review and re-run — a proposal is audit-bearing (ADR-0025
  §3), so it is never allowed to degrade to budget-omittable text. Re-emitting
  loses nothing; a marker-less or well-formed review is untouched.
- **The no-marker floor — the backward-compatibility guarantee.** Markers are
  **additive**: a review that emits none is valid and is recorded and shipped
  through the **same ship path** as today — its *disposition* differs by design (an
  absent prior finding stays `open`, where the old mechanism inferred `retired`),
  the one fail-closed change this ADR makes; nothing else about recording or
  shipping such a review changes. A round predating this contract (an in-flight
  lane, a
  reviewer that never learned the markers) degrades cleanly:
  - *Withdrawals:* with no `WITHDRAW` markers, nothing is withdrawn — every prior
    finding stays `open`. This is strictly the fail-closed floor; it never
    fabricates a retirement. The floor is "open, verify against diff," which is
    exactly the honest state PR #143 already renders.
  - *Proposals:* the fence fallback is **per proposal-bearing round, not per
    finding**. For each round a finding appeared in, `ship` uses that round's
    recorded `PROPOSAL` region if it has one, and otherwise applies the **fence
    heuristic** to that round's finding text — so a finding that carried a *marked*
    P1 in round 1 and a *bare fenced* P2 in round 2 still has P2 caught, even though
    the finding already "has" a recorded region from round 1. (Per-finding fallback
    would inspect the fence only when the finding had no region at all, dropping P2.)
    A mixed review that marks A's proposal and leaves B's as a bare fence still
    catches B. An unmarked, unfenced *prose* proposal degrades to ordinary review —
    the finding ships in the artifact, only the structured comparison is missed.
    This is not a regression against ADR-0025 §3, but its **strict improvement**:
    §3's v1 detects proposals by a fence heuristic, which misses *every* prose
    proposal (the exact gap #145 records); ADR-0043 makes a conforming reviewer's
    prose proposal **auditable by marking it** (the reviewer is instructed to mark
    all proposals, §4), so §3 is *better* satisfied, not worse. The residual — an
    *unmarked* prose proposal from a non-conforming reviewer — is inherently
    undetectable (there is no reliable signature for "proposal-shaped prose"; that
    undetectability is the very reason this ADR makes proposals explicit), so
    degradation to ordinary review is the fail-safe for a protocol violation, the
    v1 residual #145 already accepts — not an accepted bypass of §3.
  - *Legacy records:* a disposition snapshot written before this implementation
    may carry `status=retired`. Two cases, and they do not conflict. *Rendering a
    terminal legacy snapshot* (a PR whose review predates this contract, no new
    round): `ship` renders `retired` with the existing honest, cause-free language
    (PR #143), so records on disk are not misread. *Carrying a legacy `retired`
    entry into a new round* under this contract: it is migrated to `open`, not
    preserved — `retired` was the absence-inference this ADR removes, so the
    precedence rule's "carry prior status forward unchanged" (§1 rule 3) treats a
    legacy `retired` as `open`, never as a withdrawal it never was. A legacy
    retirement is thus reopened for honest reassessment, never silently honoured.

The floor is therefore the *safe half* of the old mechanism: absence never
retires (stronger than before), and proposal detection retains the fence as a
compatibility backstop while the marker becomes authoritative.

### 4. What this ADR does not decide — implementation obligations

The implementation PR (tracked by #144 and #145) owns the mechanism, as
fail-closed obligations it may not quietly skip:

- **Collision-free finding identity, as a prerequisite (§3).** Because the id is
  now a withdrawal target, the implementation must detect an id shared across every
  persisted finding identity in the loop — this round's findings and every
  carried-forward finding, `open` or `withdrawn` — and fail closed: never
  dedup-drop one, never retire on or overwrite the ambiguous id. The
  lossless-identity mechanism is #276; making it a blocking prerequisite rather
  than a cosmetic nicety is ADR-0043's.
- **The reviewer prompt/rubric text** that instructs Codex to emit withdrawals in
  a `## Withdrawals` section and a `PROPOSAL` block after the finding it addresses,
  and the exact shape of the per-round open-findings roster that gives the warm
  session an id vocabulary to cite. The normative rule text — §2 "retire only on a
  grounded `WITHDRAW`" and §3 "a proposal is the marked region" — lands in
  `docs/review/guide.md` (the standing contract ADR-0025's follow-on already
  assigned there), and the marker grammar in the per-run prompt the driver
  assembles.
- **The parse in `_write_snapshot`** (`codex-review.sh`): make marker recognition
  fence-aware over the standard Markdown fence forms (a
  `WITHDRAW`/`PROPOSAL`/`END PROPOSAL` inside any code fence is payload, per the
  Decision preamble); recognise `WITHDRAW` only in the `## Withdrawals` section and
  `PROPOSAL`/`END PROPOSAL` only at a blank-line-separated column-0 line, treating
  an indented, lazy-continuation, or otherwise structurally ambiguous
  marker-candidate as payload (§1/§2, principle 4's tie-breaker); decide regions in
  **one region-aware left-to-right pass** (fence, open proposal region, findings
  area, terminal withdrawals section), where the withdrawals section is **not
  scanned for proposals** so a `PROPOSAL`-looking line there — even unclosed — is
  payload, not a round-refusal (§2); refuse the round on a **findings-area** malformed
  `PROPOSAL` — unterminated, unbindable, or two for one finding — but **losslessly**:
  retain the rejected round's complete raw output in `.review/` and record every
  complete parseable finding as `open` before the re-run, so nothing (not even the
  undecidable tail after an unterminated proposal) is lost (§2, principle 2), the
  malformed proposal itself not recorded as a structured region (audit-bearing →
  re-run, never budget-omittable payload); extract each terminated findings-area
  `PROPOSAL` region and the `## Withdrawals` section **before** the finding split and
  **before** `_finding_id` (§2, so a marker quoted inside a proposal is payload, and
  neither region pollutes a finding's id); bind
  each proposal to its finding and **carry forward every distinct proposal each
  finding has received across rounds, append-only** (§2, so the terminal snapshot is
  self-contained and ADR-0025 §4's terminal-tree render stays intact); match
  `WITHDRAW` markers against open ids, record the finding `pending-withdrawn` with
  its grounding — but reject at write time a grounding carrying a secret (it can
  never be published, so it can never retire); carry `pending-withdrawn` as `open`
  for the roster and for silence until a successful ship promotes it to `withdrawn`
  (§3 publication-gates-retirement — the three statuses `open`/`pending-withdrawn`/
  `withdrawn` are a decision; their storage representation is mechanism); apply §1's
  precedence (a re-raise reopens a `pending-withdrawn` or `withdrawn` id); and stop
  retiring on absence. The exact fence
  recogniser, the separator tolerance, the roster format, the marker
  escaping/nesting, and the stray-marker diagnostic are mechanism, held to the
  four principles in the Decision preamble.
- **The render in `render_dispositions`** (`ship.sh`): render `withdrawn` with
  its grounding and `open` carried-forward findings honestly; publish a withdrawal
  grounding as **mandatory, non-omittable** verdict-changing evidence — render
  every `withdrawn` grounding, and if they cannot all fit the comment's hard limit,
  **fail closed** (refuse to post, the oversized-report path) rather than omit one;
  a successful ship having published the grounding is what **promotes**
  `pending-withdrawn` to `withdrawn` (§3 publication-gates-retirement, ADR-0025 §4);
  migrate a legacy `retired` entry to `open` when a new round carries it (§3);
  publish **every distinct proposal a finding carried across the loop** (labelled by
  round) from the **terminal snapshot alone** — which carries them forward
  append-only (below), so ADR-0025 §4's terminal-tree anchor is untouched — each
  under §3's publish-in-full-or-exclude rule, with the fence retained as the
  compatibility fallback **per proposal-bearing round** (so a finding's marked P1
  and bare-fenced P2 both count), not per finding (§2/§3); keep the §3 secret-scan
  and cumulative budget otherwise unchanged.
- **Required end-states proven by test:** the **no-marker degradation path** —
  a review that emits no markers is recorded and shipped, retires nothing, and
  keeps every prior finding `open` — alongside the positive `WITHDRAW`-retires
  and `PROPOSAL`-is-published paths; a **finding proposed P1 in one round and P2 in
  a later one publishes both** (labelled by round), so the merge reviewer can
  compare the committed code against whichever it derived from (§2/§3 cross-round
  provenance); a **finding whose P1+P2 together exceed the budget routes the whole
  finding to independent review** rather than publishing a partial set (§3 all-or-
  nothing per finding), and an **excluded proposal (secret or over-budget) surfaces
  §3's routing requirement** so materially proposal-derived code is not cleared on
  the Codex terminal verdict alone (ADR-0025 §3 binding rule); a **finding with a
  marked P1 (round 1) and a bare fenced P2
  (round 2)** still catches P2 (§3 per-round fence fallback); a **`PROPOSAL` block
  inside the terminal `## Withdrawals` section — including an *unclosed* one** — is
  withdrawal-section payload, binding to no finding and never refusing the round (§2
  region-aware pass); a **valid finding before *and* a numbered finding after an
  unterminated `PROPOSAL`** are both preserved on refusal — the former recorded
  `open`, the latter kept in the retained raw output **and re-injected into the
  re-run's prompt** — so a re-run cannot blindly drop either (principle 4 lossless
  refusal, principle 2); an **open-finding roster too large to fit** drops to ADR-0025
  §1's plain-cold-diff floor (no roster, no withdrawals that round, all prior
  findings stay `open`), never truncating ids (§1); the fail-closed
  unmatched/malformed-marker
  paths; **withdraw-then-identical-re-raise reopens** (§1 precedence, not silent
  suppression); **a finding both re-raised (as an open block) and named by a valid
  terminal `WITHDRAW` in the same round stays `open`** end-to-end — no grounding can
  retire a finding the round also holds (§1 rule, snapshot and render); **a finding's
  id is stable whether or not the round also carries a
  proposal or a withdrawals section** (§2, both stripped before hashing) — including
  an unchanged final re-raised finding alongside a withdrawal of an earlier one; a
  **proposal body containing a top-level numbered list** spawns no spurious finding
  (§2 parse order); a **mixed marked-plus-fenced** review catches both (§3
  per-finding fallback); a **secret-carrying withdrawal grounding never retires**
  (rejected at write time, can never be published); a **`pending-withdrawn` finding
  in a re-run started before `ship`** loads as `open`, re-examinable, and is
  confirmed `withdrawn` only after a successful ship (§3 publication-gates-retirement,
  the three-status model); a **failed post/publish persists no promotion** — the
  next round reloads the finding `pending-withdrawn`/`open`, never as confirmed
  `withdrawn` (§3, promotion follows a *successful* ship); a **re-raise of a
  previously `withdrawn` finding together with an invalid (no-grounding) `WITHDRAW`**
  is `open` — the re-raise wins, the invalid marker inert (§1 precedence, §3
  invalid-marker); a **missing-verdict
  refusal is lossless too** — raw output retained, parseable findings recorded
  `open`, rejected output re-injected (principle 4, the same as every refusal); withdrawal groundings that **cannot all fit the
  cumulative budget fail the ship closed** rather than omit one — including the
  zero-remaining-capacity and many-withdrawals cases — leaving the findings
  `pending-withdrawn`/`open`, never confirmed-retired without their grounding (§3,
  ADR-0025 §4); a **legacy `retired`
  entry carried into a new round migrates to `open`** (§3 legacy-records); and a
  **`WITHDRAW`/`PROPOSAL`/`END PROPOSAL` quoted inside a code fence** — backtick or
  tilde, **including an unclosed fence that runs to EOF** (CommonMark treats the
  remainder as code) — is payload, retiring nothing and recording no proposal
  (Decision preamble); a **literal `END PROPOSAL` fenced inside a proposal body**
  is payload, not the terminator — while an unfenced blank-line-separated column-0
  `END PROPOSAL` deterministically closes the block (§2 normative escape); an **indented `WITHDRAW` inside a finding's body** (outside the
  `## Withdrawals` section) is payload, retiring nothing (§1, tie-breaker); a
  **`## Withdrawals` heading or `WITHDRAW` line inside a `PROPOSAL` body** is payload
  (§2 proposal-first extraction), retiring nothing; a **`## Withdrawals` heading
  followed by a top-level finding** is mid-findings payload and **the finding after
  it survives** (§1 terminal = no finding after; not a competing section); **two
  trailing `## Withdrawals` headings** form one section (first-to-verdict), both
  their withdrawals counted, none discarded (§1 deterministic terminal section); a
  **column-0 numbered line after `## Withdrawals`** (grounding is single-line, so it
  cannot be a wrapped grounding) is a real finding, its heading mid-findings payload
  (§1 single-line grounding, no lost withdrawal); **two `WITHDRAW` lines for one id in a round** refuse the round (§3, no
  arbitrary grounding choice) **losslessly** — a newly raised finding in that round
  survives a differing re-run (principle 4); each
  **malformed `PROPOSAL` structure — unterminated, unbindable, or two for one
  finding — refuses the round** (§2), including an **oversized or secret-bearing
  unbindable/duplicate block**, which must re-run rather than slip past the §3
  audit as payload; a **re-raise across a rank shift (`1. Foo` → `2. Foo`, same
  canonical identity) reopens as one finding** (§1, *not* a collision), while a
  **distinct-canonical-identity collision sharing one display hash (e.g. `café`
  vs `cafè`) — same-round, cross-round-open, or cross-round-`withdrawn` — fails
  closed** so a `WITHDRAW` on the ambiguous id retires nothing and no colliding
  finding (including a withdrawn one) is overwritten or dropped (§3 prerequisite,
  told apart by canonical identity, not display hash).

Fixing the exact grammar tolerance or the roster layout here would over-reach;
those are mechanism, and the obligations above are the states it must satisfy.

### 5. The edit to ADR-0025, recorded here to apply on ratification

ADR-0025 is ratified, and ADR-0019 forbids writing a state claim like "amended by
ADR-0043" onto it while ADR-0043 is only `Proposed` — the same situation ADR-0031
§7 faced with ADR-0029, resolved the same way (ADR-0026 §6): the edit is **not
made by this change**, but recorded here in the exact form to apply **on
ratification of this ADR**. ADR-0001 requires *both* the old ADR's `Status` line
updated *and* the append-only note, as ADR-0026/0031 do, so §5 records both. On
acceptance, **replace** ADR-0025's `Status` line:

```text
- Status: Accepted, §4's anchor description amended by ADR-0027; §2's and §3's
  *inferred* implementation of their signals (retire-on-absence, fence-detected
  proposals) replaced with explicit markers by ADR-0043 — the §2/§3 decisions
  themselves stand
```

and **add** to ADR-0025's header block:

```text
- Amended: <ratification date> by ADR-0043 — §2 and §3 require a
  *reviewer-emitted* signal, but the v1 implementation infers both: it retires a
  finding on its *absence* from a later round, and detects a §3 proposal by a
  *fence heuristic*. ADR-0043 replaces each inference with an explicit marker —
  a grounded `WITHDRAW <finding-id>` and a positionally-bound `PROPOSAL` block —
  and makes absence fail closed (a silently dropped finding stays *open*, never
  retired). §2's and §3's decisions stand; ADR-0043 sharpens how they are met,
  with its implementation deferred to a separate PR (#144, #145).
```

These are the `Status` change and the append-only note the amendment relationship
needs; recording both in the amending ADR rather than mutating ADR-0025 now is
what keeps the ratified document free of a premature state claim (ADR-0019).

## Alternatives considered

**Keep the honest rendering (PR #143) and stop there.** Rejected: PR #143 makes
the *rendering* of an absence-inferred retirement honest, but the recorded
`status=retired` is still an inference the reviewer never made, which #144 shows
is ADR-0025 §2-invalid on its own terms. Honest rendering of an unsound record is
weaker than a sound record; this ADR is the stronger contract PR #143 was
explicitly deferred toward.

**Ground a withdrawal by restating the finding's text, letting the driver
re-hash it.** Rejected: `_finding_id` hashes normalised text, so a restatement
retires the finding only if it is byte-stable after normalisation — which a
paraphrase is not. It would fail closed often *and* unpredictably (a near-miss
restatement silently withdraws nothing), where citing the surfaced id is exact.

**Let the reviewer assign its own finding tags (`[F1]`, a slug) and cite those.**
Rejected: reviewer-chosen tags are not stable across rounds (rank renumbering is
the exact pathology `_finding_id` drops the enumerator to avoid), and a tag→id
mapping persisted across rounds is more machinery than surfacing the id the driver
already owns. The driver owns identity; the reviewer cites it.

**Drop the fence heuristic entirely in favour of the marker.** Rejected for
backward compatibility: a review predating the marker emits bare fenced patches,
and removing the fence would make those proposals budget-omittable — a regression
for in-flight lanes. The fence is retained as the compatibility floor while the
marker is authoritative, so detection strictly improves and nothing in flight
breaks.

**Require a marker for a review to be valid (reject a marker-less review).**
Rejected: it would break every in-flight lane whose review predates the contract,
for no safety gain — a marker-less review is handled correctly by the fail-closed
floor (nothing withdrawn, fence fallback for proposals). Markers are additive.

## Consequences

**Easier.** The disposition record stops asserting a reassessment the reviewer
never made: a `withdrawn` finding now carries the reviewer's own grounding, and an
un-withdrawn finding stays visibly open instead of silently retired. A prose
proposal is detected and either published in full or excluded fail-closed, so the
§3 authorship comparison holds for every marked proposal, not only fenced ones.
The audit record is trustworthy without a human re-deriving each disposition.

**Harder.** The reviewer's output contract grows two markers, and the driver must
surface an id roster the warm session can cite — a small token cost added back to
the round `codex exec resume` was cutting, accepted because a citeable id is what
makes a grounded withdrawal possible at all. A finding the reviewer forgets to
withdraw now stays open across rounds rather than aging out on absence; that is
the intended fail-closed cost, remedied by the reviewer emitting `WITHDRAW` or the
author grounding-rejecting on the PR (§2's recourse), never by silence.

**Follow-on.** Implementation is a separate PR (this is a ratify-before-build
review-contract decision, not golden rule 5's Protocol case), tracked by #144 and
#145: the prompt/rubric and `docs/review/guide.md` rule text, the `_write_snapshot`
parse, the `render_dispositions` render, and the tests named in §4 — including the
no-marker degradation test. On ratification, ADR-0025 gains the `Amended` line §5
records, applied then rather than now.

**Revisit if** a reviewer proves unable to cite the surfaced id reliably (make the
roster more prominent, or accept a fuzzy match with a confirmation step), or if the
open-finding accumulation from strict fail-closed retirement produces enough noise
that a periodic reviewer-confirmed bulk-withdrawal round is worth its own rule.
