# 81. No write consumes the evidence its own proposal cites

- Status: Partially superseded by ADR-0108 (§8's first deferred item and its assignment to the #104 lane)
- Date: 2026-07-29
- Partially superseded: 2026-08-05 by ADR-0108 — **§8's first deferred item is
  ruled, and its assignment of that item to the #104 lane no longer holds. Two of
  the three grounds §8 gave for deferring have also expired. §8's second deferred
  item, §§1–7, §9 and §10 stand untouched.**
  [ADR-0108](0108-a-write-declares-its-intent-and-a-cross-kind-collision-is-refused.md)
  §4 rules it: a cross-kind same-id write is refused with `MemoryStoreError`, at
  **every** upsert-capable door, on every implementation.

  **Replaced**, two clauses of §8's first bullet:

  1. The **deferral** — "whether a proposal arriving at the id of a stored record of
     a *different kind* should be refused rather than silently upserted … **Deferred.**"
     A reader of §8 would treat the question as open; it is not.
  2. **The operative one, the owner.** "**Owner: the `MemoryStore` write-semantics
     lane**, the one that takes #104's compare-and-swap." ADR-0108 takes it in a
     lane that leaves #104 untouched. §8's stated reason for the pairing was that
     the cross-kind rule "wants the same conformance-suite rewrite across all three
     backends that #104's CAS wants" — and that rewrite happens in ADR-0108's
     implementing lane anyway, for its §1's sake, so pairing them again would mean
     doing it twice. That is a good reason to reassign, and reassigning is still a
     change to what §8 decided: recorded as a supersession rather than argued into
     an amendment. #104 itself is untouched and stays open.

  **Not replaced: §8's reasoning is assessed, not overruled.** Of the three grounds
  it gave, **one is stale and two stand** — and §4 is built on one of the two that
  stand.

  1. **The cost ground stands, and ADR-0108 §4 honours it.** §8 wrote that a writer
     "could only enforce [it] by paying a `get(proposed.id)` on every ingest to see
     something the store sees for free while it replaces the row — giving up §1's
     no-I/O, cannot-be-raced property". Still exactly true, and it is *why* the
     refusal is in the store: a writer cannot learn the stored record's **kind**
     without reading it, and `INSERT_IF_ABSENT` does not supply it — that mode
     refuses every collision without reporting what it collided with. §4's check
     costs no read because the store's own `SELECT` already reads the row, which is
     the "something the store sees for free" §8 predicted. (#630's thread argued
     this ground had expired; it had not. That argument holds for the *absence*
     check ADR-0108 §1 needs, and was carried across to a different rule.)
  2. **The coverage ground is stale in both halves.** §8 wrote that "a cross-kind
     collision arriving from capture would pass a writer-side rule untouched. A
     rule at `add` covers every caller; a rule at `ingest` covers one." Episodic
     capture does not call `add` at all — `ConversationCapture` writes a
     one-element `write_atomic` in `INSERT_IF_ABSENT` mode and refuses `add`
     explicitly, for §8's own reason — so the caller §8 named as the reason had
     already protected itself. And `add` is not "every caller": `write_atomic` is
     a second door into the store, which is why ADR-0108 §4 binds both.
  3. **The residue ground stands unchanged**, and is why this remained a
     low-priority defect properly fixed rather than an incident: with §1 closed,
     what remained was a silent replacement of an *unrelated* record, with no
     fabricated warrant behind it.

  **§8's trigger fired before the deferral was taken**, so its own terms were met
  rather than overridden: §8 named "a producer that *derives* a record id from
  content rather than minting one" as what would make the question urgent, and
  #735 records `FakeBeliefObserver` deriving ids from a content hash on `main`.
  §8's "until then no producer can collide" is correspondingly no longer true.

  §8's **second** deferred item — the general "no stored record cites itself"
  invariant, owned by the belief-presentation lane — is untouched, as is every
  other section of this ADR.

  This record lands in ADR-0108's own (`Proposed`) change, in the shape this ADR
  used for its ADR-0077 note (commit `4bc008b`), so the review that can still
  change ADR-0108 §4 reads it alongside.
- **This is a contract change, of the semantics-only kind.**
  `MemoryWriter.ingest` gains one refusal clause (§1): a ruling that would
  *install* the proposal at an id that same proposal cites is refused rather
  than applied. **No signature changes, no Protocol is added, and
  `core/types.py` and `core/errors.py` are untouched** — what changes is the
  documented meaning of one method and the shared conformance suite, which is
  the review concern `CONTRIBUTING.md` names when a Protocol's meaning changes
  without its shape. Golden rule 5 therefore applies: this ADR ships as **its
  own docs-only PR**, is reviewed while still `Proposed` so a finding can still
  change the decision, and is flipped to `Accepted` on merge (`CONTRIBUTING.md`,
  "Contract ADRs land before their implementation"; ADR-0015 §5). **No code
  changes with it.**
- **This ADR supersedes nothing, and amends one clause of
  [ADR-0077](0077-the-observer-proposes-beliefs-from-episodes.md).** §5 applies
  ADR-0070 §1's amend-versus-supersede test to §5's "it is a check, not a
  guarantee" clause and finds that no decision there changes: the clause governs a
  *concurrent* destruction leaving a citation that no longer resolves — §6's
  ratified residue, untouched — while this ADR forbids a *self-inflicted* one
  leaving a citation that resolves to the wrong record, which §6 cannot render.
  Because the sentence read in isolation is broader than the case it argues, the
  bound is recorded on ADR-0077's `Status` line and in a dated header note, in
  ADR-0078 §10's shape for ADR-0045 §5 clause 1 — **an amendment, not a partial
  supersession** (§5 gives the reasoning and the two `main` precedents). **No
  ratified body text is rewritten and both files land in this one change**, so
  ADR-0077's `Status` never names an absent ADR. ADR-0077 carries no leading
  partial-supersession token, so #477's coexistence question does not arise on that
  line and stays filed.

## Context

ADR-0077 §5 landed a write-time floor on `MemoryWriter.ingest`: a proposal in the
`DERIVED` band whose `provenance.evidence` names a record the store does not hold
is refused with `UnresolvedEvidenceError`, before conflict detection and before
the policy is asked. What it buys is stated in the same section and in the
`MemoryWriter.ingest` docstring on `main`: **every citation resolved once**, so a
citation that later stops resolving is *loss* rather than a producer bug, and §6's
tombstone can say so honestly.

Issue #472 reports a way for a proposal to pass that check and then destroy the
very record it cited — with its **own** write, not another actor's.

**The shape, verified against `src/ai_assistant/memory/ingest.py` at `origin/main`
rather than taken from the report.** `MemoryIngestor._apply` dispatches four
write-producing rulings:

| ruling | write | lands at |
| --- | --- | --- |
| `ACCEPT` | `store.add(proposed)` | `proposed.id` |
| `STORE_TEMPORARY` | `store.add(proposed + expires_at)` | `proposed.id` |
| `REINFORCE` | `store.add(_merge(target, proposed))` | `target.id` |
| `SUPERSEDE` | `write_atomic([UPSERT(closed T_i)…, INSERT_IF_ABSENT(P')])` | each `T_i.id`, plus a freshly minted id |

`MemoryStore.add` is an upsert, documented on the Protocol in as many words:
"Adding a record whose `id` already exists overwrites the previous one (an
upsert), so `id` is the caller's idempotency key. All backends share this
behaviour; the shared conformance suite enforces it." So:

- the store holds `EpisodicMemory(id="e")`;
- a proposal arrives: `OBSERVED SemanticMemory(id="e", evidence=("e",))`, with
  content that conflicts with nothing;
- `_require_resolvable_evidence` calls `get("e")`, finds the episode, and passes;
- conflict detection is kind-scoped and excludes the proposal's own id, so it
  surfaces nothing; `DefaultMemoryPolicy` rules `ACCEPT` (its rule 2 rejects a
  derived belief citing *nothing*, and this one cites something);
- `store.add(proposed)` overwrites `"e"`.

The store now holds one record: a belief at `"e"` whose only citation is `"e"`.

**Two halves of #472's original finding do not hold, and the difference is
load-bearing.** `REINFORCE` was reported as destroying a cited fold target; it
does not — `_merge` writes at the *target's* id and unions both evidence tuples,
so a record at that id survives and the citation still resolves. `SUPERSEDE`
writes its correction `INSERT_IF_ABSENT` at a minted id, so it can overwrite
nothing at all, and it *retires* rather than destroys the records in its
retirement set (ADR-0080 §1 preserves every field but `valid_until`; ADR-0077 §6
has `export` carry the record as stored). The live destruction is `ACCEPT`'s and
`STORE_TEMPORARY`'s upsert at a colliding id.

But `REINFORCE` is not innocent either, in a way the report understates: if the
proposal cites the fold target, `_merge`'s union puts `target.id` into the
evidence of the record it writes *at* `target.id`. Nothing is destroyed and the
citation resolves — to the belief itself. So the general defect is not
"destruction" but **a belief that ends up standing as its own warrant**, and any
rule stated only over `ACCEPT` would miss a third of it.

**Why this is worse than the residue ADR-0077 §5 and §6 already ratify, and not
an instance of it.** §5's third clause accepts that "an episode deleted between
the check and the write leaves a citation that no longer resolves, and no seam
closes that", and §6 makes that honest: the presenting surface resolves each
citation lazily, renders a tombstone for what is gone, and lowers the presented
confidence. Every part of that machinery is triggered by a citation **failing to
resolve**. Here the citation *resolves* — to the record that replaced its
referent — so no tombstone renders, no confidence is lowered, and the provenance
display answers "why do you believe that?" with the belief itself. §6's honesty
mechanism is not merely bypassed; it is actively fed a false input. That is the
distinction the decision turns on.

**Nothing reachable produces the shape today, and this ADR says so plainly rather
than implying urgency it does not have.** Both shipped producers mint record ids
from an injected `id_factory` (`learning/observer.py`, `learning/processor.py`,
`uuid4` by default), and the observer's evidence is a label→episode-id map built
from the batch it actually read (ADR-0077 §5), never a value the model or the
record supplies — so `proposed.id ∈ evidence` is unconstructible from either.
ADR-0077 §2 additionally forbids the observer to propose an `EPISODIC` record at
all, so it cannot mint a belief onto an episode's id even by accident. What
remains is a proposal built by hand, or by a producer injected into the
`FeedbackProcessor`/`Observer` seams that does not follow ADR-0077 §5's mapping
rule.

That is precisely the class of case the writer boundary already guards.
`_refuse_unsafe_fold` exists because "`MemoryIngestor` takes rulings from *any*
injected `MemoryPolicy`, so the safety property has to hold at the boundary that
performs the write rather than at the one that recommends it"; `_checked_id`
exists because a pathological id factory must "fail loudly rather than spin".
Both are guards against producers nothing ships. So the question this ADR settles
is not whether the hazard is imminent — it is not — but whether the writer's
floor should be *complete* over the writes the writer itself performs, at a cost
proportionate to a defect nobody can currently trigger.

Issue #472 states the two open questions. This ADR decides the first and defers
the second with a named owner (§8).

## Decision

### 1. No write that installs the proposal may land at an id the proposal cites

**A ruling that *installs* the proposal is refused when the id it writes at
appears in the observed proposal's `provenance.evidence`** — whether or not a
record is currently stored at that id. Concretely, over the four write-producing
rulings:

- **`ACCEPT`** and **`STORE_TEMPORARY`** install at `proposed.id`. Refused if
  `proposed.id` is cited.
- **`REINFORCE`** installs at the ruling's `target_id`. Refused if that id is
  cited.
- **`SUPERSEDE`** installs at a *freshly minted* id and **re-mints** rather than
  refusing where that id is cited (§4); its retirement-set writes retire rather
  than install and are never refused by this rule.

On refusal **nothing is written**: no record added, no window closed, no ruling
returned. `REJECT` and `ASK_USER` write nothing and are therefore unaffected —
**once the call reaches the policy**, a self-citing proposal the policy declines is
reported as the decision the policy made, rather than converted into an exception
(§2). The qualifier is load-bearing: the two refusals that already precede a
ruling still precede this one, so a self-citing proposal whose evidence does not
resolve (ADR-0077 §5) or whose conflict set is over the ceiling (ADR-0079 §1) is
still refused before any policy is asked, and this rule changes nothing about that
order.

**"Install" and "retire" are defined once, here, and used throughout.** A write
**installs** when it stores the *proposal's* content at an id: whatever stood at
that id, if anything, stops being retrievable, and the id now names the belief the
proposal carries. A write **retires** when it stores an *existing* record back
with only its validity window narrowed — ADR-0080 §1 preserves `valid_from` and
every other field, the record is retained on disk off the read path, and ADR-0077
§6 has `export` carry it as stored. **The distinction is a property of the write,
not of what the store happens to hold**, which is what keeps the predicate free of
any store read, and why an install at a cited id is refused even where that id
names nothing yet.

**The predicate reads nothing from the store.** Its inputs are the proposal this
call observed (`ingest`'s single deep copy, ADR-0065), the ruling, and — for
`SUPERSEDE` alone — the writer's own freshly minted candidate id (§4). None of the
three is a store read. So it costs no `get`, adds no I/O to a section that holds
the ingestor's lock, introduces no new read-modify-write window, and — unlike §5's
resolvability check — cannot itself be raced, because every input is already fixed
and private to the call. That is the whole reason the rule is affordable at all,
and it is why it is stated over ids and write modes rather than over stored
content.

**The empty-slot case is refused too, and it is not the harmless one it looks
like.** For a `DERIVED` proposal it cannot arise: §5 already refused a citation
that resolves to nothing. For an `ASSERTED` or `EXTERNAL` proposal — the bands §5
does not check — the install would store a record whose evidence names itself and
nothing else that exists: a belief standing as its own only warrant, which is the
defect this ADR is about arriving with no destruction at all. It is the same state
§4 makes the `SUPERSEDE` applier re-mint away from, and refusing it is what makes
the rule statable without a store read rather than *in spite* of having none.

**One consequence of the id-only predicate, accepted deliberately.** It refuses
even the degenerate case where the record already standing at that id is *itself*
already self-citing, so the install would change nothing observable.
Distinguishing that would cost a `get` on every write-producing ingest to protect
a state §1 says must not exist. A holder of such a record — reachable only as
legacy data written before this rule, or through a direct `MemoryStore.add`
outside the gate — repairs it through the affordances ADR-0077 §6 already names
(`assistant forget`, or the user asserting the belief, which supersedes it at a
fresh id), not by re-ingesting it.

#### 1a. The rule is quantified over the *proposal's* evidence, not the write's

For `REINFORCE`, `_merge` unions the target's evidence into the record it writes.
A target that *already* cited itself would therefore make the merged record
self-cite without the proposal citing anything of the kind. That is **out of
scope**, and the exclusion is deliberate:

- the fold neither creates the condition nor destroys the cited record — a record
  survives at that id and the citation resolves exactly as it did before;
- testing the merged tuple instead would make such a record permanently
  unfoldable, with no repair path through the write path, in exchange for a
  display pathology this ADR is not about (§8 gives that its owner);
- and it would make the writer's refusal depend on state it read from the store,
  giving up §1's raced-by-nothing property for the sake of one legacy shape.

The rule is over the ids **this proposal** cites and the ids **this write** lands
at. Both are in hand at the point each write is formed.

#### 1b. The rule is band-wide, unlike §5's

ADR-0077 §5's resolvability floor is scoped to the `DERIVED` band, because that
is the band ADR-0072 §3 obliges to cite at all. **This rule is scoped to no
band.** It asks only whether a write consumes a citation that is *there*, so a
record citing nothing satisfies it trivially and band-scoping would buy nothing —
while leaving the `ASSERTED` and `EXTERNAL` bands free to fabricate their own
warrant, which is the same defect wearing a different source. The two rules stay
distinguishable and each still lives in exactly one place: §5 asks *does every
citation resolve*, this one asks *does any write consume one*.

### 2. Where the check sits: after the ruling, before the write dispatch

It sits **between the policy's ruling and the write dispatch** — the seam
ADR-0078 §10 names for its check 0, "reached by every write-producing ruling, and
by no ruling that writes nothing". Three placements are ruled out, each for a
reason already on the record:

- **Not in `_require_resolvable_evidence`.** That runs before detection and
  before the policy, and at that point the write set is not yet known:
  `REINFORCE`'s destination is `decision.target_id`, which the ruling supplies.
- **Not in `_refuse_unsafe_fold`.** `ACCEPT` and `STORE_TEMPORARY` never reach
  it, which is exactly the hole ADR-0078 §10 records when it excepts check 0 from
  that helper — "a check placed there passes `SUPERSEDE` and writes the secret on
  them". The same helper would pass the two rulings that carry most of this
  defect.
- **Not split in two**, with the `proposed.id ∈ evidence` half hoisted ahead of
  the ruling where it *is* computable. Two reasons, both borrowed rather than
  invented. Putting one rule in two places is what ADR-0077 §5 says it exists to
  avoid ("each lives in exactly one place"). And a pre-ruling refusal would
  pre-empt a ruling the policy is entitled to make — §5's own argument against a
  writer-side emptiness floor, that it "would make the policy's `REJECT`
  unreachable for the case, turning a reportable decision the user can read into
  an exception". A self-citing proposal the policy rejects should be a `REJECT`
  the user can read. ADR-0080 §3 declined to hoist its window refusal into
  detection on the same ground: a refusal that matters only for a ruling that
  reaches it belongs where that ruling is applied.

**Two evaluation points, one rule — and this is not what "not split" forbids.**
The three installing rulings take their destination from the proposal
(`proposed.id`) or from the ruling (`target_id`), so all three are decided at the
seam above. **`SUPERSEDE`'s destination does not exist until it is minted**, inside
the applier's bounded retry loop, so its candidate is tested **there** —
immediately beside the existing "does this id name a retained target" test, before
the write batch is assembled, and a hit is a re-mint rather than a refusal (§4).
The ordering is stated explicitly because an implementation cannot infer it from
§1: mint; reject the candidate if it names a retained target **or** an id the
proposal cites; otherwise build the batch.

What the bullet above refuses is evaluating **one** destination at **two** seams —
where the copies drift and the earlier one pre-empts a ruling. Here each
destination is tested exactly once, at the only point at which it exists. A rule
cannot be enforced before its subject is created, and pretending otherwise would
either drop the `SUPERSEDE` arm or hoist the minted id out of the retry loop it
belongs to — which is ADR-0045 §4's mechanism for making a collision recoverable
instead of fatal.

### 3. It raises `MemoryStoreError`, and earns no new error class

The refusal is a plain **`MemoryStoreError`** — "what every other writer-boundary
refusal raises" (ADR-0079 §4, quoted by ADR-0077 §5), the class
`MemoryWriter.ingest` already documents, and the one `_refuse_unsafe_fold`,
`_close_window` and `_checked_id` all use. It is **not** a fabricated `REJECT`: a
ruling is the policy's to make (ADR-0005 §3) and a writer inventing one puts a
decision nobody made into the ingest result.

It is specifically **not** `UnresolvedEvidenceError`, and **no new subclass is
added.** ADR-0080 §7 drew this exact line for its own refusal:
`UnresolvedEvidenceError` "names a proposal whose *evidence* does not resolve
rather than a *target's* window". Here the evidence resolves perfectly well;
what is wrong is that the write would consume it. And the reason
`UnresolvedEvidenceError` earned existence does not recur: it exists because the
observation stage "cannot otherwise tell a race from a bug" and needs the
unresolved ids to compare against the batch it selected (ADR-0077 §5). This
condition is a pure function of the proposal and the ruling, both fixed inside the
writer's own lock — so it is **never** a race and **always** a producer fault.
There is no second branch for a caller to take, and a subclass with one caller
and one branch is surface with no consumer.

The message names the id, the ruling, and that the id is cited, so the producer
bug is diagnosable from the error alone.

### 4. `SUPERSEDE` is exempt in one direction and re-mints in the other

**The retirement set's window closes are not refused.** They retire rather than
install (§1's definition): ADR-0080 §1 writes the target back with every field
preserved but a clamped `valid_until`, and the record is retained. A cited target
leaving the read path is therefore **exactly** ADR-0077 §6's case — a citation
that stops resolving, rendered as a tombstone, with the presented confidence
lowered — which is ratified handling, not a defect. Refusing here would do two
wrong things at once: break a correction that is working because of a citation
carried by the record correcting it, and put the writer in the business of
protecting a belief's warrant from a retirement, which is the cascade ADR-0077 §6
refuses, arriving from the writer's side.

**"Not refused by this rule" is not "permitted".** Every standing refusal at this
boundary keeps its precedence and its scope, and being *cited* neither triggers one
nor excuses one: ADR-0045 §5 clause 1 — as narrowed by exception by ADR-0078 §5b —
still refuses a fold onto a `USER_ASSERTED` target, cited or not, and a citation
confers no licence to retire what the user told us; ADR-0079 §1's ceiling and
ADR-0080 §3's unrepresentable window still refuse before the batch. This ADR adds
one refusal to the writer and subtracts none, which is why the conformance clause's
third limb is qualified rather than absolute (§6).

**The correction's minted id re-mints if it names a cited record.** `_supersede`
writes `INSERT_IF_ABSENT` at a freshly minted id, so it can overwrite nothing;
but a minted id that happened to be *cited* would leave the correction standing
as its own warrant — the same defect §1 forbids, reached without replacing
anything. Where the minted id appears in the proposal's evidence the applier
**re-mints**, joining the bounded re-mint loop already there for an id naming a
retained target, under the same `_MAX_SUPERSEDE_ATTEMPTS` bound, raising on
exhaustion with every target left live and unchanged (ADR-0045 §4). It re-mints
rather than refuses because a re-mint is free and always available — which is
precisely why the retained-target collision is handled that way already.

**For a `DERIVED` proposal this clause is belt to §5's braces**, and it is worth
saying which case actually needs it: a cited record that resolves is *stored*, so
`INSERT_IF_ABSENT` at its id already fails with `MemoryStoreConflictError` and the
existing loop already re-mints. The clause does real work only for the bands §5
does not check — an `ASSERTED` or `EXTERNAL` proposal citing an id that resolves
to nothing, where the insert would succeed. Written anyway, because a rule whose
enforcement depends on a *different* rule's scope is one refactor away from being
false.

### 5. What this does to ADR-0077 §5: an amendment on its `Status`, not a supersession

The clause this ADR bounds is ADR-0077 §5's third:

> **It is a check, not a guarantee.** An episode deleted between the check and
> the write leaves a citation that no longer resolves, and no seam closes that:
> it is the same two-store race ADR-0074 §8 accepted and bounded, arriving from
> the other side. §6 is what makes the residue honest rather than a dangling id.

**Applying ADR-0070 §1's test — would a reader acting on ADR-0077 §5 or §6 act
identically before and after this ADR?** Yes. The clause makes two claims and
this ADR contradicts neither:

- **Its subject is a destruction by another actor.** Its own justification says
  so — "the same two-store race ADR-0074 §8 accepted and bounded". §1's case has
  no other actor: the destroying write is the ingest's own, wholly determined by
  the proposal and the ruling, both fixed inside the ingestor's lock. Nothing this
  ADR says makes a *concurrent* deletion closeable, and §1 does not attempt it.
- **Its residue is a citation that no longer resolves.** §1's case leaves a
  citation that *does* resolve, to the record that replaced its referent. §6's
  entire mechanism — lazy resolution, tombstone, lowered presented confidence — is
  keyed on non-resolution, so it never fires on §1's case and is neither narrowed
  nor extended by removing that case from existence.

So §1 is an additional *pre-write admissibility* condition, in the same family as
§5's own resolvability check, which removes one input from the set that can produce
a destroyed citation rather than repairing one afterwards. The clause's claim — that
no seam closes a citation destroyed between the check and the write — stays true of
every case where such a destruction actually happens.

**But the sentence read in isolation is broader than the case it argues, and that
is worth recording rather than leaving for a reader to reconcile.** "An episode
deleted between the check and the write" does, on a literal reading detached from
its own justification, sweep in a deletion performed by *this* write. A reader who
opens ADR-0077 and never opens this ADR would take the clause at its widest and
conclude that ADR-0081's refusal does not exist. So the boundary is recorded where
that reader is: **ADR-0077's `Status` line gains "§5's check-not-a-guarantee clause
amended by ADR-0081", and a dated header note states the bound** — the clause
verbatim for a destruction by another actor leaving a citation that no longer
resolves, §6 unchanged, and ADR-0081 §1 refusing a self-inflicted one whose citation
still resolves. No ratified body text is rewritten (ADR-0070 §1), and **both files
land in this one change**, so ADR-0077's `Status` never names an ADR that is absent.

**Why "amended by" and not "partially superseded by", stated because a reviewer
read it the other way.** ADR-0070 §1's line is the *decision*, and the two things
ADR-0077 §5's third clause decides are intact: (a) that the resolvability check
carries no guarantee against a destruction it cannot see, and (b) that §6's
tombstone — not a repair, not a cascade, not a rewrite — is the handling for a
citation that has stopped resolving. This ADR replaces neither. It removes one
*input* to (a) whose residue (b) was never able to render, and the case it removes
is not the case the clause describes: the residue there is a citation that
**resolves to the wrong record**, and every mechanism §6 specifies is keyed on
non-resolution.

The repository has decided this classification twice already, both on `main`:

- **ADR-0078 §10 / ADR-0045.** ADR-0078 added an *exception* to ADR-0045 §5 clause
  1's ratified refusal — a strictly larger interference with a decided rule than
  this ADR makes — and recorded it as `"§5 clause 1 amended by ADR-0078"` with a
  dated note reading "narrowed by exception, not lifted", **not** as a partial
  supersession. If narrowing a ratified refusal by exception is an amendment,
  bounding a clause to the case it argues is one too.
- **ADR-0079 §4 and ADR-0077 §5 themselves.** Each *added* a refusal to
  `MemoryWriter.ingest` — two and one respectively — and neither superseded
  anything, though each made prose describing what `ingest` refuses incomplete.
  ADR-0077 §9 names the relation in as many words: §5's clause is "a **third**
  obligation on that method, **stacked** on the two ADR-0079 §4 landed days ago
  … and conflicting with neither". This ADR's is the fourth, stacked the same way.
  Were an added writer refusal a supersession of every ADR whose text does not
  anticipate it, ADR-0077 §5 would have had to partially supersede ADR-0028 and
  ADR-0079. It did not, and it is ratified.

Declaring a partial supersession instead would also make ADR-0077's `Status` say
something false. Per ADR-0070 §4 and the template, the partial form **leads** and
`Accepted` is dropped — so a three-day-old, heavily-referenced ADR would read as
partly replaced at exactly the clause whose ratified handling (§6) this ADR leans
on in §4 to keep a `SUPERSEDE` retiring a cited record permitted. That would leave
this very ADR resting on a clause its own `Status` edit had retired.

**The edit is permitted while this ADR is `Proposed`, and the pair is atomic for
exactly that reason.** ADR-0070 §1 permits, on a ratified ADR's header, both
"**recording a supersession that has landed** … This presupposes the superseding
ADR *exists*: flipping a live decision to `Superseded` with no such ADR is not a
status change but an unrecorded decision change" and "adding a **dated header
note**". The condition §1 sets is **existence**, not ratification — the hazard it
names is a `Status` line pointing at nothing — and an atomic pair makes that hazard
unreachable, because ADR-0077's qualifier and ADR-0081 land in one change and can
only be merged or reverted together. `main` carries the precedent: ADR-0079 and
ADR-0080 each edited a ratified partner's `Status` in their own `Proposed` change
on this exact reasoning ("the hazard ADR-0070 §1 guards against is unreachable when
the pair is atomic"), and ADR-0080's header records that `main` "already carries the
precedent three times over". Reading §1's clause as requiring *ratification* first
is a standing misreading tracked as issue #458; it would make an atomic pair
impossible and force a two-PR sequence in which `main` transiently carries the
weaker state §1 exists to prevent. It is also not what §1 says.

**One book-keeping note.** ADR-0077's `Status` is a plain `Accepted`, so the
qualifier accumulates after it in ADR-0028's established shape (`Accepted, §8
amended by ADR-0040, ADR-0045 and ADR-0078`). No leading partial-supersession token
is present or added, so the coexistence question #477 records — how an `amended by`
qualifier sits beside a leading partial-supersession token — does not arise on this
line and stays filed for its owner.

**The `MemoryWriter.ingest` docstring carries the same boundary**, since that is
where a reader of the *contract* looks rather than at either ADR: it will state
both that a citation destroyed by another actor between check and write is the
accepted residue §6 handles, and that a citation this call's own write would
consume is refused (§6's list of what the implementing lane owes).

**And nothing is edited on ADR-0028 either.** Adding a clause to the
`MemoryWriter` conformance suite contradicts nothing §8 decided, including its
exclusion list: this is not the fold's own rule, not the conflict threshold, not
the conflict limit, not the relocated tuning check. That follows the precedent
`main` already carries twice over — ADR-0077 §9.1 and ADR-0079 §3 each added a
`MemoryWriter` obligation *and* its conformance clause without touching ADR-0028's
`Status`, while ADR-0040, ADR-0045 and ADR-0078 (which each changed what §8
*said*) are recorded there. That the boundary between those two treatments is not
itself written down anywhere is a real inconsistency in the repository's
book-keeping; it is parked as a GitHub issue rather than settled here, because
settling it is an ADR-governance decision and not a memory one.

### 6. The contract surface owed, and what the implementing lane owes

**New surface in `core`: none.** No Protocol is added or reshaped, no
`core/types.py` entry, no `core/errors.py` class. `MemoryStore` is untouched (§8).

**`MemoryWriter.ingest`'s documented semantics gain §1's refusal clause** — a
**fourth** obligation on that method, stacked on ADR-0079 §4's two and ADR-0077
§5's one, and conflicting with none of them. Those three are about the *conflict*
set (the full-set `SUPERSEDE`, the over-ceiling refusal) and about the evidence
set's *existence*; this one is about the write set's *disjointness* from the
evidence set. No signature change.

**The conformance clause**, joining the clauses ADR-0079 §3 promoted and ADR-0077
§9.1 added. It has **three** limbs, because a clause carrying only the first can
be satisfied by a writer that still stores a self-standing warrant through
`SUPERSEDE`:

> 1. A ruling that would **install** the proposal at an id the proposal cites is
>    refused with `MemoryStoreError`: nothing is written, no window is closed, and
>    no decision is returned. This holds whether or not a record already stands at
>    that id, and for every band.
> 2. Where a `SUPERSEDE`'s **minted** id names an id the proposal cites, the writer
>    mints another rather than installing the correction there; where it cannot
>    find a free id within its own bound it raises `MemoryStoreError` with every
>    target left live and unchanged.
> 3. A proposal citing ids that no write lands on is unaffected, and a `SUPERSEDE`
>    whose **retirement set** holds a cited record still retires it and still
>    lands — **where the ruling is otherwise admissible**. This rule adds no
>    refusal to `SUPERSEDE` and removes none: the standing writer-boundary
>    refusals keep their precedence and their scope unchanged, whether or not the
>    record they protect happens to be cited.

**Limb 2 is a suite clause and not one writer's regression, because the suite can
already force it.** `WriterFactory` exposes `id_factory` precisely "so the
id-factory cases (ADR-0045 §5) drive it deterministically", and the suite already
drives a scripted collide-then-succeed factory and an always-colliding one for the
retained-target case. A cited id substituted into those two factories forces the
re-mint and the exhaustion with no new seam. Leaving limb 2 out — the shape an
earlier revision of this ADR had, caught in review — would let a conforming writer
mint an `EXTERNAL` proposal's cited id, insert the correction there, satisfy limbs
1 and 3, and store the record §1 exists to forbid.

`FakeMemoryWriter` matches all three, for ADR-0079 §3's reason: a fake that stores
what production refuses lets a consumer's test pass on state the real writer would
never produce.

**What the implementing lane owes:**

1. The check at the write-dispatch seam (§2), and the `MemoryWriter.ingest`
   docstring restated as §1, §4 and §5 rule it — including §5's reconciliation of
   the "check, not a guarantee" sentence, which is the only place that
   reconciliation lands.
2. All three limbs of the conformance clause above, in `MemoryWriterContract`,
   plus the matching `FakeMemoryWriter` behaviour. Both existing bindings run
   them — the fake's and `TestMemoryIngestorContract`'s — as ADR-0028 §8
   requires, since a suite bound only to the fake "certifies the double while the
   production writer drifts".
3. **Limb 1 over the *reachable* matrix, written out rather than left as a
   product.** The naive product — every installing ruling × every `MemorySource` ×
   cited-id-present-or-absent — has cells that no composition can reach, and a lane
   that writes them gets a false pass in one and a false failure in the other. The
   matrix is therefore:
   - **Cited id present in the store** — every installing ruling × **all four**
     `MemorySource` members (`OBSERVED`, `INFERRED`, `USER_ASSERTED`, `EXTERNAL`).
     This is the cell the clause lives in. Both parametrisations are named rather
     than sampled for ADR-0078 §10's reason — each omission is a live hole. A check
     written for the two rulings that came up in discussion passes `REINFORCE`
     (whose case drives a proposal citing its own fold target, the one an
     implementation reading only #472 will not write); and one that reused §5's
     `band_of(...) is BeliefBand.DERIVED` guard clause, or bolted a
     `USER_ASSERTED` arm beside it, passes every other test on this list while
     letting an `EXTERNAL` install at a cited id through. `EXTERNAL` is both the
     member most likely to be missed and the one where a self-citing record is
     most plausible in practice, since its ids come from another system rather than
     from an `id_factory`. Parametrising over the enum also fails closed if a fifth
     source is ever added.
   - **Cited id absent from the store** — `ACCEPT` and `STORE_TEMPORARY` only, and
     only for `USER_ASSERTED` and `EXTERNAL`. The two exclusions are structural,
     not oversights: a `DERIVED` proposal citing an id that resolves to nothing is
     refused by ADR-0077 §5 *before* the policy is asked, so that cell proves
     nothing about this rule; and `REINFORCE`'s write id is its fold target, which
     is drawn from the conflicts and therefore always stored, so "absent" is not a
     state its destination can be in.
   - **Precedence, asserted rather than assumed to follow.** A `DERIVED` proposal
     that self-cites *and* carries a second, unresolvable citation is refused with
     **`UnresolvedEvidenceError`** — §5's pre-policy refusal keeps precedence, and
     the class stays the more specific one. This needs its own assertion precisely
     because `UnresolvedEvidenceError` **is** a `MemoryStoreError`, so a test
     written against the base class passes whichever refusal fired and certifies
     nothing about the order. Likewise a `REINFORCE` naming a target absent from
     the conflicts still raises the existing not-among-the-conflicts error.
   - **The negative arm** — `REJECT` and `ASK_USER` neither raise nor write —
     driven on a self-citing proposal whose cited id **resolves**, so no earlier
     refusal can fire and the assertion is about this rule rather than about §5's.
4. **Limb 2's two arms, through the existing `id_factory` seam**: a scripted
   factory whose first id is cited and whose second is free re-mints and lands,
   and an always-cited factory exhausts the writer's bound
   (`_MAX_SUPERSEDE_ATTEMPTS` in `MemoryIngestor`), raises, and leaves every
   target live and unchanged. Both drive a **non-`DERIVED`** proposal, for §4's
   reason: a cited id that resolves is already re-minted away from by the existing
   collision path, so the arm is only observable where §5 does not check.
   **Limb 3's arm** is the one that fails loudly rather than subtly if a lane
   implements the rule over "every write in the batch": a cited record in the
   retirement set is still retired and the correction still lands. Driven on a
   **supersedable** cited target (`OBSERVED`/`INFERRED`), so no standing refusal
   fires and the assertion is about this rule — **with the negative beside it**: a
   cited `USER_ASSERTED` target is still refused by ADR-0045 §5 clause 1, so limb
   3's "still lands" cannot be read as a licence a citation buys.

**No test asserts the degenerate identical-content case is *permitted*** — §1
refuses it, and pinning that is what keeps a later "optimisation" from
reintroducing a `get` on the hot path.

### 7. Why the decision is this size

The shape is unreachable through any shipped producer (§Context). A decision that
is right and cheap therefore beats one that is thorough and speculative, and this
one is deliberately the cheapest complete thing:

- one predicate over two values already in hand, no store read, no new type, no
  new error class, no `MemoryStore` change, no signature change;
- placed at a seam that already exists for this class of guard, beside two
  refusals with the same justification (`_refuse_unsafe_fold`, `_checked_id`);
- and stated as a *contract* rather than as one implementation's habit, because
  the cost of doing so is one conformance clause and the alternative is a fake
  that accepts what production refuses.

What it buys is that ADR-0077 §5's guarantee stops being conditional on the
producer's id discipline. "Every citation resolved once" is a promise about the
store's state at the moment of the write; a write that consumes its own citation
makes the promise true and useless in the same instant.

### 8. Deferred, with owners

- **Whether a proposal arriving at the id of a stored record of a *different
  kind* should be refused rather than silently upserted** — #472's second
  question. **Deferred. Owner: the `MemoryStore` write-semantics lane**, the one
  that takes #104's compare-and-swap. Three reasons, and none of them is that the
  question is unimportant:
  - **It is `MemoryStore.add`'s semantics, not `MemoryWriter`'s.** The upsert and
    the idempotency-key promise are stated on `add` and enforced by
    `MemoryStoreContract` across all three backends. The writer could only
    enforce a cross-kind rule by paying a `get(proposed.id)` on every ingest to
    see something the store sees for free while it replaces the row — giving up
    §1's no-I/O, cannot-be-raced property for a weaker version of a rule that
    belongs one layer down.
  - **Stating it at the writer would leave the callers who need it outside it.**
    `MemoryWriter` is not the only path into `add`: episodic capture is exempt
    from the write-path rule entirely (ADR-0075 §1), so a cross-kind collision
    arriving from capture would pass a writer-side rule untouched. A rule at
    `add` covers every caller; a rule at `ingest` covers one.
  - **With §1 closed the residue is materially smaller.** What remains is a
    silent replacement of an *unrelated* record — the ordinary hazard of a
    documented idempotency key — with no fabricated warrant behind it and no
    honesty mechanism fed a false input. That is a real defect and a much less
    urgent one.

  **What would make it urgent, named so the deferral has a trigger:** a producer
  that *derives* a record id from content rather than minting one — a content
  hash, or an external system's key adopted as the id — which is the only way a
  cross-kind collision stops being a bug and starts being a design. Until then no
  producer can collide. Adding the refusal later is additive for every caller that
  never collides, so nothing here forecloses it, and it wants the same
  conformance-suite rewrite across all three backends that #104's CAS wants —
  which is why the two belong in one lane rather than two.

- **A general "no stored record cites itself" invariant, and how such a record
  presents.** **Deferred. Owner: the belief-presentation lane ADR-0077 §6 hands
  the tombstone and the adjusted confidence to.** Once §1 lands, no path through
  the write path creates one, so the only sources are legacy data and a direct
  `MemoryStore.add` outside the gate. A display rule for a state nothing produces
  is surface with no consumer — the ground ADR-0077 §10 declined a reason enum on
  a discarded entry — and the surface that resolves citations lazily is the one
  that can render a self-citation for what it is, at the point it already reads
  every citation.

### 9. Explicitly declined

- **Repairing the proposal instead of refusing it** — dropping the offending id
  from the evidence tuple, or re-minting the proposal's own id, before the write.
  It edits a record the producer made, which the writer does not do (ADR-0068's
  frozen graph; ADR-0077 §6's no-rewrite posture), and it is ADR-0077 §5's
  "evidence attached to satisfy a rule is not evidence" arriving from the other
  side — evidence *removed* to satisfy a rule leaves a warrant nobody assessed.
  It is also the shape `_refuse_unsafe_fold` exists to refuse: "a write that loses
  data while reporting success is worse than one that stops."
- **A fabricated `REJECT`.** ADR-0005 §3, and ADR-0077 §5's first clause.
- **A new `MemoryStoreError` subclass** for this refusal. §3 — there is no race
  to distinguish and no caller with a second branch.
- **Hoisting the computable half of the check ahead of the ruling.** §2 — one
  rule in two places, and it makes the policy's `REJECT` unreachable for the case.
- **Refusing a `SUPERSEDE` that retires a record the proposal cites.** §4 — a
  retirement retains the record, and the residue is §6's ratified tombstone.
- **Dropping `MemoryStore.add`'s upsert, or making it insert-if-absent by
  default.** It would turn a re-ingest of the same proposal into a failure,
  invert a promise `MemoryStoreContract` enforces across three backends, and is a
  far larger change than the hazard warrants — the write mode a caller needs for
  the strict semantics already exists (`MemoryWriteMode.INSERT_IF_ABSENT`,
  ADR-0046).
- **Stating §1 as a `MemoryStore` obligation.** The store does not see the
  proposal and cannot know which of the ids in a batch are citations *of the
  record being written*; enforcing it there would mean reading every stored
  record's evidence. The rule needs the proposal, so it belongs to the seam that
  has one.
- **A conformance clause pinning the exception *message*.** ADR-0028 §8's
  standing exclusion of one implementation's detail; the clause pins the class,
  that nothing is written, and that no window closes.

### 10. What this ADR does not decide

- **The cross-kind id collision** (§8), and **the self-citation display rule**
  (§8). Both with owners above.
- **A compare-and-swap on `MemoryStore`** (#104, with #248) — the cross-process
  race `MemoryWriter.ingest`'s lock explicitly does not cover. Untouched: §1's
  predicate reads nothing from the store, so it neither needs nor weakens a CAS.
- **Whether conflict retrieval is exhaustive** (#457). Unrelated and unchanged;
  §1 quantifies over the write set, not over what search surfaced.
- **Anything about ADR-0077 §6's tombstone, the presented-confidence function, or
  its floor.** §5 — untouched in every direction.
- **How an `amended by ADR-NNNN` qualifier coexists with a leading partial
  supersession token on a `Status` line** (#477). The one `Status` line this change
  edits is a plain `Accepted` with no leading token, so the qualifier accumulates in
  ADR-0028's established shape and the contradiction #477 records is not reached
  (§5). It stays filed for its owner, undecided here.
- **The `Status`-line book-keeping inconsistency** §5 names — whether an
  additive `MemoryWriter` conformance clause should be recorded on ADR-0028's
  `Status` line, as ADR-0078 did, or not, as ADR-0077 and ADR-0079 did. Parked as
  a GitHub issue; it is an ADR-governance decision, and deciding it inside a
  memory ADR would put the rule in the wrong file.

## Consequences

**Easier.**

- ADR-0077 §5's "every citation resolved once" becomes a statement about the store
  after the write, not before it. A citation that stops resolving is loss, a
  citation that resolves is a warrant, and no third state survives an ingest.
- §6's tombstone can be trusted as the *only* way a belief loses support. The
  presenting surface has one case to render, not two, and the one it renders is
  the one it can detect.
- A producer that gets ids wrong fails loudly at the writer instead of quietly
  corrupting the store — the same trade `_refuse_unsafe_fold` and `_checked_id`
  already make, extended to the last write the writer performs unguarded.

**Harder.**

- One more refusal on `MemoryWriter.ingest`, which now documents four. Each is
  narrow and each names its ADR, but the method's contract is getting long, and a
  future implementer reads all four before writing one.
- A conforming writer must place the check where §2 says, not in the fold helper
  where a reader would naturally look for a refusal. The conformance clause and
  the parametrised regressions are what keep that from being advice.
- The degenerate identical-content case is refused rather than treated as
  idempotent (§1), so a caller holding a legacy self-citing record cannot repair
  it by re-ingesting. The repair path is `forget` or a user assertion, which is
  where ADR-0077 §6 already put it.

**What would trigger revisiting.**

- A producer that derives record ids from content or adopts an external key
  (§8) — it makes the deferred cross-kind question urgent, and it is the first
  thing that could make a cited-id collision a legitimate shape rather than a bug.
- #104's compare-and-swap landing, which is the lane that owns the deferred
  `MemoryStore` half and will be rewriting `MemoryStoreContract` anyway.
- A second `MemoryWriter` implementation. §1 is stated as a pure predicate
  precisely so a writer that is not `MemoryIngestor` can satisfy it without
  reproducing `_apply`'s structure — but the first such writer is what tests that
  claim.

## Alternatives considered

**Leave it, as ADR-0077 §5's ratified residue.** The reading is defensible on the
sentence alone and it was the right call in the lane that found it (#472 records
the waiver). Rejected on the distinction §Context draws: §5's residue leaves a
citation that *fails* to resolve, which §6 renders honestly; this one leaves a
citation that resolves to the wrong record, which §6 cannot see and will render as
support. A residue an honesty mechanism cannot detect is not the same residue.

**Refuse only `ACCEPT`, the case #472 demonstrates.** Rejected: `STORE_TEMPORARY`
takes the identical `add` path one line below, and a `REINFORCE` citing its fold
target produces the same self-standing warrant by a different route (§Context). A
rule written to the reported example would leave two thirds of it live and read as
complete.

**Refuse any write landing at a cited id, including a `SUPERSEDE`'s window
closes.** Simpler to state and simpler to test. Rejected in §4: it breaks a
correction that is working because of a citation the corrected record carries, and
it protects a warrant from a retirement, which is ADR-0077 §6's refused cascade
from the writer's side.

**Close the general case at `MemoryStore.add` — refuse a cross-kind upsert — and
say nothing at the writer.** It catches #472's literal example (an episode at
`"e"`, a belief at `"e"`) and it covers callers the writer never sees. Rejected
as the *whole* answer: it misses every same-kind case, including a belief citing
itself at its own id and a `REINFORCE` onto a cited target, and those are the
cases where a citation keeps resolving. It is the right rule for a different
question, which is why §8 defers it to the lane that owns `add` rather than
declining it.

**A named `SelfCitingProposalError`.** Rejected in §3: `UnresolvedEvidenceError`
earned its class because a caller had to tell a race from a bug. This condition is
always a bug, so no caller branches on it.
