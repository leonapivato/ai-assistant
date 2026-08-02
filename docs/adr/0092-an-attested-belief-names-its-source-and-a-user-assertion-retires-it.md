# 92. An attested belief names its source and its report time; a user assertion retires it

- Status: Accepted
- Date: 2026-08-02
- **This is a contract change.** §1 adds an `Attestation` value object and an
  `attestation` field to `Provenance` in `core/types.py`, with a band-keyed
  validator — a `core` addition every subsystem reading a belief will meet. §4
  widens the class of sources a user assertion may retire, which is a
  `MemoryWriter` conformance obligation since
  [ADR-0079](0079-a-correction-resolves-every-conflict-it-is-shown.md) §3, not one
  implementation's habit. Golden rule 5 therefore applies: this ADR ships as its
  **own docs-only PR**, was reviewed while still `Proposed` so a finding could still
  change the decision, and is flipped to `Accepted` on merge (`CONTRIBUTING.md`,
  "Contract ADRs land before their implementation"; ADR-0015 §5). **No code changes
  with it.** The type, the policy, the applier and the producer are later lanes
  (§9).
- **This ADR partially supersedes
  [ADR-0038](0038-a-user-assertion-supersedes-a-conflicting-inference.md)**, in the
  scope named in §8: **§2a's policy-side exclusion of `EXTERNAL` from the
  supersedable set**. §2a's `USER_ASSERTED`-target refusal, its allow-list
  *shape*, and §§1, 1a, 2, 3, 4, 5 all stand.
- **This ADR partially supersedes
  [ADR-0050](0050-resolving-the-full-contradiction-set.md)**, in the scope named in
  §8: **§1's `EXTERNAL` hold-out from the retirement widening**. §1's
  `USER_ASSERTED` hold-out, its bounded-honesty claim, and §§2 and 3 stand.
- **It discharges two named deferrals rather than superseding them.**
  [ADR-0073](0073-the-band-scoped-read-is-an-enumeration.md) §4 left "whether that
  needs `Provenance` to grow fields" to "leg 6's first `EXTERNAL` producer" lane,
  *with a producer in hand*; §1 answers it. ADR-0045 §5/§7/§10 left "whether
  `DefaultMemoryPolicy` adopts `EXTERNAL` supersession" to a policy lane and filed
  an "identity-aware re-sync" residual; §4 and §6 take both. Each earlier ADR's
  own sentences stay true of what that ADR decided, so the record is a dated note
  and not a supersession pair (ADR-0082 §1, §2).
- **Follow-up to** ADR-0073 §4 and ADR-0045 §7, which teed this up between them:
  one named what an attested belief must be able to say, the other made saying it
  safe and left the adoption open.

## Context

Leg 6 builds the first read-only ingestion source. The project owner has ruled
that the first one is a **local `.ics` calendar file** read from disk, so no
device boundary is crossed and ADR-0017 §1 and §3 are not engaged (ADR-0084 §9
already settled that moving bytes on one machine engages neither). That ruling is
what makes this ADR decidable rather than speculative: ADR-0073 §4 deferred the
`core` question explicitly *to the lane with a producer in hand*, and this is it.

**Nothing has ever produced an `EXTERNAL` record.** The only mention of
`MemorySource.EXTERNAL` anywhere in `src/` is the arm of `band_of` that maps it to
`BeliefBand.ATTESTED`; no module constructs one. Every rule below is therefore
being decided *before* its first live case — which is not merely convenient. It is
what makes §2's validator admissible, and it is why the id discipline in §6 can be
ruled rather than migrated to.

Three questions are entangled, and answering any two without the third leaves a
hole that §7 traces end to end:

1. **What an attested record carries.** ADR-0073 §4 rules a gate: an attested
   belief's complete answer to "why is this held?" names "what reported it, and
   when that source said so", and **neither half is carried by any field today.**
   `Provenance.source` records that the source was `EXTERNAL` and never *which*
   connected system; `last_updated` is transaction time — when *we* revised the
   belief (ADR-0045 §3) — so a Tuesday sync of a calendar that said so on Monday
   renders "Tuesday", a true statement about us and a false one about the source.
   §4 makes carrying both "a precondition of [the first `EXTERNAL` producer]
   shipping".
2. **Whether a user assertion may retire an attested belief.** The owner has
   ruled it must: the external calendar is an *input*, not the truth.
3. **What an imported record's id is**, because 1 and 2 both turn on it.

### The state on `main` is not the state the deferrals describe

This matters enough to state plainly, because the obvious reading of ADR-0038 §2a
is a full round out of date and would send an implementing lane at a problem that
is already solved.

ADR-0038 §2a excluded `EXTERNAL` from the supersedable set "for a mechanical
reason rather than a philosophical one": supersession kept the *target's* id, an
external record's id is the integrating system's idempotency key, and the next
routine sync's upsert restored the external value over the user's correction. It
recorded a verified reproduction of exactly that.

**That mechanism is gone.** ADR-0045 §4 makes a `SUPERSEDE` close the target's
window and write the correction at a **freshly-minted id**, and ADR-0045 §5
narrowed the ingestor's refusal accordingly — `_refuse_unsafe_fold` permits a
`USER_ASSERTED` → `EXTERNAL` `SUPERSEDE` and still refuses the `REINFORCE`, which
alone still inherits the target's id. All of it has landed: `core/types.py`
carries `Validity`, `MemoryIngestor` carries an injected `id_factory` and an
`_apply_supersede` that closes windows and mints, and issue #254 closed as
completed on 2026-07-23.

What survived is narrower and lives in two places ADR-0045 deliberately did not
touch:

- **The policy-side exclusion.** `DefaultMemoryPolicy._SUPERSEDABLE` is still
  `{OBSERVED, INFERRED}`, so a correction contradicting an import is `ACCEPT`ed
  *beside* it and both stay live — the "stale belief stays live" shape of #38, for
  the one source. ADR-0045 §5 says why it stopped there: widening the shipped
  policy would have been "a behavioural change smuggled in" to a temporal-model
  ADR, and it filed the adoption as a policy-lane choice (§7, §10).
- **The resurrection residual**, filed at ADR-0045 §10 as "identity-aware re-sync
  so a superseded `EXTERNAL` record does not resurrect".

**And the residual is worse than ADR-0045 §7 states it.** §7 describes it as a
similarity problem: conflict scoring is asymmetric, so a re-sync "may see no
conflict, `ACCEPT`, and make the stale external belief live again *alongside* the
surviving correction", which is "the two-live-records shape, not destruction — no
user data is lost". The similarity half is right. What §7 does not name is what
that `ACCEPT` actually writes. `MemoryIngestor._apply`'s `ACCEPT` arm is
`store.add(_installed(proposed))`, and `MemoryStore.add` is documented as an
upsert in which "`id` is the caller's idempotency key". So a re-sync proposing at
the retired record's own id does not land beside it — **it lands on top of it**,
replacing a record whose `validity.valid_until` was closed with one whose window
is open by default. The retired belief is not merely re-stated; the *retirement
itself* is erased, and with it the only on-disk evidence that the user's
correction ever took effect, which ADR-0045 §6 had guaranteed `export` would keep.
That is a loss of the audit trail ADR-0045 exists to create, and it is reached
through the ordinary, non-destructive-looking ruling.

Correcting §7 is not a detour. It is the reason §6 rules on ids at all.

## Decision

### 1. `Provenance` grows one optional `Attestation`, present exactly when the band is `ATTESTED`

`core/types.py` gains a small value object and one field:

```python
class Attestation(BaseModel):
    """What reported a belief, and when that source said so (ADR-0073 §4)."""

    reported_by: str          # required, non-empty: the connected source instance
    reported_at: UtcInstant   # required: the source's own clock (§3)
```

and `Provenance` gains `attestation: Attestation | None = None`, governed by a
model validator: **the field is set if and only if `band_of(source)` is
`ATTESTED`.**

**On `Provenance`, not on `MemoryBase`.** ADR-0045 §2 put `Validity` on the
envelope and argued the placement in a way that decides this one in the opposite
direction: the window is "a lifecycle property of *the record's life in the
store*, set operationally by the applier", and putting it on `Provenance`, "whose
every other field is set by the *producer* of the belief, would mix two
authorships." An attestation is the pure case of the other kind. Who reported a
belief and when they said so are producer-set facts about *trust and source* —
which is what ADR-0045 §2 says `Provenance` stays about — and they are exactly the
"why is this held?" that ADR-0073 §4 asks the provenance to answer. The same
argument, read the same way, lands them here.

**The `if and only if` is deliberate in both directions.**

- *Set when `ATTESTED`* is ADR-0073 §4's gate made structural rather than
  procedural. §4 says carrying both halves is "a precondition of [the producer]
  shipping"; a precondition that a producer can satisfy by remembering is one it
  can fail by forgetting, and the failure is silent — an attested record with no
  attestation renders exactly the misleading answer §4's floor forbids.
- *Absent otherwise* keeps `source` the single classifier. ADR-0072 §4 rules that
  classification "is keyed on `source` and never on `confidence`, so no producer
  can promote a belief into the asserted band by claiming certainty." An
  attestation attached to an `INFERRED` record would be the same laundering by a
  different field: a derived guess wearing a citation to a system that never
  reported it. Nothing may acquire the standing of a band it is not in by
  decorating itself.

### 2. Why a value object and a validator, and why the validator is admissible here

**One object rather than two nullable fields**, because the two halves are one
fact and ADR-0073 §4 requires *both*. Two independent `| None` fields admit four
states, of which two are half-answers — a record naming a source but not when it
spoke renders "your calendar had this as of …" with a blank, and a record naming a
time but not a source attributes it to nobody. A value object whose fields are
both required, held in one optional slot, makes the half-states **unconstructable**
instead of merely discouraged. This is the shape ADR-0045 §2 chose for `Validity`
over two loose fields on the envelope, for the same reason.

**A validator on the type, not a rule at the `MemoryPolicy` gate**, and the
precedent is on this exact class. `Provenance` already carries two band-keyed
model validators, and `_derived_is_never_certain`'s docstring states the placement
argument in full: "the gate is not the only path a `Provenance` takes —
`Goal` carries one and reaches no propose/dispose gate at all — and a validator on
the value needs no gate." An attested `Goal` would owe the same disclosure as an
attested belief for the same reason, and only a validator reaches it.

**And the validator is admissible here, on the test the corpus already states.**
ADR-0086 §3 refused a `max_length` on `Provenance.evidence` because a validator
runs on *deserialisation* as well as construction, so it "would take a belief a
running deployment already holds … and make `get`, `list_beliefs` and `export`
fail on it: a strictly new failure invented on the read path." It then gives the
governing test outright: "The test is not 'is it a validator on a `core` type' but
'does it refuse something that already worked'."

**What was actually verified, stated as narrowly as it was checked:** no module
under `src/` constructs a `Provenance` with `source=MemorySource.EXTERNAL` — the
only mention of the member anywhere in `src/` is the arm of `band_of` that maps it
to `ATTESTED`. So **no code path this project ships can have persisted one**, and
no store a deployment of this software holds can contain a record the validator
would refuse on decode. That is the same condition ADR-0072 §3 named when it
declined `_derived_is_never_certain` ("there is no producer yet that could violate
the rule"), which ADR-0077's observer later met — and the validator that landed
then went onto this same class, for the same band-keyed reason, at the same moment
in that band's life. This is that precedent one band over.

**Two things that verification does not cover, and neither is waved away.**
`MemorySource.EXTERNAL` is a public `core` value that `Provenance` accepts today,
so a *library* consumer constructing their own records could hold data this
validator refuses; and roughly thirty-four test sites construct such records
in-process (§9). The second is a code-edit cost, not a read-path failure on
retained data, and §9 budgets it. The first is real but unreachable through
anything this repository ships, and it is answered by enforcement rather than by
assertion: **§9 makes a store scan a precondition of the validator landing** — the
implementing lane confirms via `export` that the deployment holds no `EXTERNAL`
record, and if one is found it stops rather than shipping a decode failure. That
is ADR-0045 §4's "enforced not assumed" applied to this ADR's own premise, and it
is the same discipline §6 declines to overclaim without.

**And the timing is not incidental — it is the argument.** The choice is now or
never: the first import makes the band permanently non-empty, after which this
validator is a data migration rather than a rule, and the band whose entire warrant
is someone else's would have acquired the ability to say nothing about whose. A
deferral "until compatibility is established" is therefore not a smaller version of
this decision; it is the decision not to make it.

### 3. `reported_at` is the source's clock, and it is never reconciled with ours

`reported_at` is **the instant the reporting source asserts the fact was current,
on that source's own clock**. It is not when we read the file, not when we wrote
the record, and not a value we may substitute for. `last_updated` remains ours and
keeps ADR-0045 §3's meaning exactly.

**A source that supplies no report time cannot be attested — there is no
fallback, and a local proxy is the failure this rule exists to prevent.** No
substitute may be put in the field: not our clock, not the ingest instant, and in
particular **not the file's mtime**, which is a property of the last local write
and is changed by a copy, a restore or a `touch` while the source's claim stays
where it was. Substituting one asserts a report time the source never made, which
is precisely ADR-0073 §4's "a true statement about us and a false one about the
source" — reintroduced under a different field name, and harder to spot because it
is *nearly* right. Where the source genuinely says nothing about when it spoke, the
producer has no attestation to make, and §1's validator then settles the outcome
structurally rather than by discretion: no attestation means no `EXTERNAL`
provenance, so the record is not proposed as an attested belief at all. The
capability is bounded by what sources can actually say, which is the honest place
for the boundary. In practice it rarely binds for the producer in hand — RFC 5545
makes `DTSTAMP` mandatory on a `VEVENT`, so the `.ics` case has an answer by
construction — but the rule is written for the source that does not, so a later
producer meets it as a constraint instead of reaching for the nearest local
timestamp.

Two further consequences follow, and both are rulings rather than observations:

- **`reported_at` earlier than `last_updated` is the normal case, not an
  anomaly.** It is the whole point: Monday's report, revised into the store on
  Tuesday. Any consumer that treats the pair as an ordering invariant has
  misunderstood which clock each belongs to.
- **A `reported_at` in our future is not refused.** Source clocks skew, and a
  validator comparing the two would refuse a record that is perfectly encodable,
  perfectly readable, and merely early — inventing a read-path failure, which is
  precisely what §2's admissibility test permits this validator to avoid. Skew is
  a *rendering* concern: a surface may say so, and must still not present our
  clock as the source's (ADR-0073 §4's floor). Nothing in `core` compares them.

**`reported_by` identifies the connected source *instance*, not the vendor** —
"the user's work calendar", not "iCalendar" — and it must be **stable across
syncs**, because §6 leaves it as the only durable handle the record keeps on where
it came from. It is rendered to the user and it survives into `export`, so it is
not a place for a credential or a filesystem path that discloses more than the
source's identity. Whether a human-facing display label is configured alongside it
is the sensor-seam lane's — the wave's other contract decision, tracked by #625 — and is **not** this field; a surface
with no label falls back to `reported_by`.

### 4. A user assertion retires an attested belief: `EXTERNAL` joins the supersedable class

**`DefaultMemoryPolicy` adopts `EXTERNAL` supersession.** The class of sources a
user assertion may retire becomes `{OBSERVED, INFERRED, EXTERNAL}` — in the
policy's ruling (`memory/policy.py`) *and* in the applier's retirement widening
(`memory/ingest.py`, and with it the shared `MemoryWriter` conformance suite that
has driven it since ADR-0079 §3). This discharges the choice ADR-0045 §5/§7/§10
deferred and partially supersedes ADR-0038 §2a's policy-side exclusion and
ADR-0050 §1's `EXTERNAL` hold-out.

**It stays an allow-list, and that property is the point.** The set is still
enumerated membership, never `is not USER_ASSERTED`, so ADR-0038 §2a's surviving
argument holds verbatim: "a `MemorySource` added later is not silently enrolled in
a destructive rule by omission." What changes is one member, chosen; not the shape
that makes the next member a decision.

**Why the band may be retired at all.** ADR-0072 already ruled it, in the sentence
that defines the band: an attested belief is "neither entitled to the standing the
supersession law protects nor re-derivable by observing harder." The first clause
is the permission. The second is usually read as a *reason for caution* — and for
this rule it is the opposite, once completed. ADR-0038 §2's error calculus turned
on recoverability: an inference may be retired wrongly because "if it was in fact
still true the same observations will propose it again", while an assertion may
not because "nothing but the user can restore it". An attested belief is not
re-derivable *by us* — and it is **re-reportable by its source**, on a schedule,
which is a recovery path at least as reliable as re-observation. So the band sits
on the recoverable side of §2's asymmetry, and the case for retiring it is the
case §2 already made for inferences.

**What does not move.** Clause 1 of `_refuse_unsafe_fold` — no fold of any kind
onto a `USER_ASSERTED` target — stands record-keyed for both rulings (ADR-0045 §5,
narrowed only by ADR-0078 §5b's confirmation exception). ADR-0038 §3's one-way
asymmetry stands: this widens what an *assertion* may retire and touches nothing
about who may retire an assertion. `_SUPERSEDABLE`'s `USER_ASSERTED` hold-out in
the widening stands (ADR-0050 §1). And the `EXTERNAL` `REINFORCE` refusal stands —
which is not automatic, and is why §5 exists.

### 5. The one constant that must become two, or the adoption reopens the loss it waited on

This is the section an implementing lane most needs, because the obvious way to
perform §4 is wrong in a way that passes as a one-line change.

`memory/ingest.py` holds a `_SUPERSEDABLE` frozenset serving **two unrelated
jobs**:

1. the **retirement widening** — which sibling conflicts a `SUPERSEDE` closes
   alongside the named target (`_retirement_set`, ADR-0050 §1, ADR-0079 §3); and
2. the **reinforce refusal** — `_refuse_unsafe_fold` raises when a
   `USER_ASSERTED` proposal would `REINFORCE` onto a target whose source is
   **not** in the set.

Job 2 reads the set as "targets a user assertion may safely fold *at the target's
id*". Job 1 reads it as "beliefs a correction is warranted to retire". Those were
the same set only by coincidence, and §4 breaks the coincidence: adding `EXTERNAL`
for job 1 makes job 2's condition `source not in _SUPERSEDABLE` **false** for an
`EXTERNAL` target, so the refusal stops firing — and a `USER_ASSERTED` `REINFORCE`
onto an imported record folds at the external id again. That is precisely the
data loss ADR-0038 §2a reproduced, that ADR-0045 §5 kept refused *by name* while
lifting its `SUPERSEDE` sibling ("a `USER_ASSERTED` proposal reinforcing an
`EXTERNAL` target still folds at the external id … removing the refusal here would
reopen it"), and that this ADR has no ground to touch.

**So the constant splits into two named sets**, and the implementing lane may not
widen one identifier:

- the **retirement class** — `{OBSERVED, INFERRED, EXTERNAL}` — used by the policy's
  ruling and the applier's widening; and
- the **reinforce-safe class** — `{OBSERVED, INFERRED}`, unchanged — used by
  `_refuse_unsafe_fold`'s `REINFORCE` arm, whose membership means "does not carry
  a foreign idempotency key", which `EXTERNAL` still does not satisfy.

The general shape of the mistake is worth naming, since it is the second time this
file has produced it: ADR-0045 §5 had to make the `EXTERNAL` refusal *relation*-aware
after ADR-0040 §3 had keyed it on the records. A set that answers two questions
answers neither once the questions come apart.

### 6. An import's id is ours; the source's key is not the store's key

**An `EXTERNAL` producer proposes each record at an id it mints, opaque to the
source.** It may not use the source's own key — a VEVENT `UID`, a row id, a
URL — as `MemoryRecord.id`, whether directly or namespaced.

`MemoryRecord.id` and a source's key are two different things that ADR-0038 §2a's
hazard analysis showed were being made one. The store's id is a primary key: the
address a record is written at, and — under `add`'s upsert — an instruction to
replace whatever already lives there. A source's key is an assertion about
sameness *in the source's world*. Every failure in the §Context trace comes from
letting the second one aim the first.

**What this buys, stated exactly — and it is a removal of aim, not a guarantee of
absence.** What goes is the *systematic* route by which an import addresses a
record the store already holds: the §Context resurrection is no longer reachable
by construction, because a re-sync of the same calendar entry no longer computes
the retired record's id and so cannot erase its closed `validity` window. The
hazard was that the source's key **is** an address, aimed at the same record every
sync, deterministically. Minting removes the aim.

**It does not make a minted id provably absent, and this ADR does not claim it
does.** ADR-0045 §4 settled the neighbouring case and settled it against the
weaker reading: a probabilistic generator "makes a collision unlikely, not
impossible", so the supersession applier writes with **insert-if-absent** under the
atomic primitive and a bounded retry, because "the one id requirement is 'names no
existing record,' **enforced not assumed**". The `ACCEPT` path has no such
enforcement — it is a blind `store.add` upsert — so an import whose minted id
collided would overwrite the colliding record, and a producer that ignored this
section entirely would too. Both remain possible after this ruling.

The difference is one of kind rather than degree, which is why the ruling is worth
making anyway: with the source's key as the store's id the overwrite is *certain
and repeated*, and it lands on precisely the record whose retirement carries the
user's correction; with a minted id it is a `uuid4` collision against an unrelated
record. **The residual is not import-specific** — every minting producer already
has it, since `ACCEPT` and `STORE_TEMPORARY` install at `proposed.id` through a
blind upsert — so it is a pre-existing property this ADR neither creates nor
closes, and §10 files it rather than half-ruling a contract for one caller.

**And ADR-0081 §8 already named this fork, from the other side.** Deferring the
question of a proposal arriving at a stored record's id, it names what would make
the deferral urgent: "a producer that *derives* a record id from content rather
than minting one — a content hash, or **an external system's key adopted as the
id** — which is the only way a cross-kind collision stops being a bug and starts
being a design. Until then no producer can collide." §6 is a ruling not to pull
that trigger. The first `EXTERNAL` producer was the obvious candidate to adopt a
foreign key as an id, and declining it keeps leg 6's producer inside the class
ADR-0081 §8's deferral already assumes safe, with its owner (the `MemoryStore`
write-semantics lane that takes #104's compare-and-swap) unchanged.

What §9 does owe is the narrower discipline ADR-0045 §4 already established for a
minted id — the producer's id factory is **guarded at its output** — so a
malformed mint fails loudly instead of becoming a key. ADR-0081 §1's
`_refuse_self_consuming_write` does not reach this case and is not being leaned
on: it refuses a write landing at an id the proposal *cites*, and an attested
record cites nothing.

**What it does not buy, equally exactly.** It does not make the re-synced value
disappear, and it does not guarantee one live record per calendar entry. §7 traces
what actually happens.

**Idempotency does not vanish; it moves.** The reason to key a record by the
source was so that re-reading an unchanged entry updates rather than duplicates.
That still happens, one seam later: an unchanged re-sync proposes the same content,
`_detect_conflicts` scores an identical live record at the top of its ranking
(lexical overlap under the in-memory store, embedding similarity under SQLite —
identical text is the one case neither can miss), and `DefaultMemoryPolicy` rules
`REINFORCE`, which folds at the **target's** id. One record, updated in place, no
duplicate — reached through the ordinary write path rather than through a key the
producer asserts.

**`MemoryStore.add`'s contract is unchanged.** `add` still upserts at whatever id
it is given and `id` is still available as a caller's idempotency key; this ADR
rules what one *producer* passes, and declines a facility rather than removing
one. No Protocol clause moves.

**`REINFORCE` takes the incoming attestation.** With §1's validator in force,
`_merge` — which builds a fresh `Provenance` field by field — would raise on an
attested fold that carried no attestation, so this is required rather than
optional. The rule follows `_merge`'s own shape: it already takes `source` and
`last_updated` from the incoming record because "newer content wins", and the
attestation describes the content that survived. It therefore never disagrees with
the `source` beside it, including in the awkward case where one source's record is
reinforced by another's report: the survivor honestly says who reported the text
it now holds.

### 7. What the re-sync then does, case by case, and the residual that stays

Take the ADR-0038 §2a reproduction, on the tree this ADR describes. Monday: the
calendar reports "the user works from the London office"; the import lands as an
attested record at *our* id `m1`, attesting `reported_by="calendar:work"`,
`reported_at=Monday`. The user corrects it: "the user works from the Berlin
office". Conflict detection surfaces `m1`; §4 puts it in the retirement class; the
policy rules `SUPERSEDE`; the applier closes `m1`'s window and writes the
correction at a fresh id `m2` (ADR-0045 §4). `m1` is off `get`/`search` and
retained in `export`.

Tuesday, the calendar still says London.

- **The correction surfaces as a conflict.** The proposal is `EXTERNAL`, a conflict
  is `USER_ASSERTED`, so `DefaultMemoryPolicy` rule 4 rules **`ASK_USER`** and
  nothing is written. The correction stands and the contradiction reaches the one
  authority that can settle it. This is the intended path, and it is behaviour
  already ratified — §4 and §6 are what let the proposal *reach* it.
- **The correction does not surface** (ADR-0045 §7's asymmetry). No conflicts, so
  `ACCEPT` writes at the fresh id: two live records, the user's `m2` and a new
  attested one, plus `m1` still retired in `export`. Nothing is destroyed, both are
  visible to the ADR-0073 §1 enumeration with their bands, ADR-0072 §5 ranks
  `ASSERTED` above `ATTESTED` when assembling context, and the user can kill either
  (ADR-0073 §5). This is the #38 "stale belief stays live" shape — a real residual,
  and the one this ADR does not close.

The comparison that matters is with the same similarity miss under the source's
key as the store's id: there, `ACCEPT` upserts onto `m1`, and the store keeps two
live records *and* no record that a retirement ever happened. **§6 does not remove
the two-live-records residual; it removes the destruction of the retirement.** The
honest claim is that narrow one, and it is worth stating narrowly because the
wider one is tempting and false.

**One more residual, and it is §6's own cost.** Because identity is re-established
by similarity rather than asserted by a key, a calendar entry that changes
*materially* between syncs ("standup 9am" → "sprint planning, Thursday, room 4")
may score below `conflict_threshold` against its own predecessor and land as a
second live record rather than folding into it. A small edit folds; a rewrite
duplicates. Closing that needs what §10 defers: the source's key carried on the
record and an index to look it up by, which is a `MemoryStore` read surface with no
consumer until a producer exists to want it. It is filed, not solved, and the
failure is duplication rather than loss.

### 8. What ratification amends, and under which rule

Each edit below is classified under ADR-0070 §1's test — would a reader holding
only the earlier ADR now act differently, or read one of its clauses more widely
than it now holds — and placed under ADR-0082 §1 and §2. All of them land in **this
ADR's PR**, so no `Status` line ever names an ADR that does not exist (ADR-0070
§1's hazard, and the form ADR-0045's own 2026-07-28 note established).

- **ADR-0038 — partially superseded; `Status` takes the leading token.** §2a
  *decided* that `EXTERNAL` is excluded from the supersedable set, and §4 reverses
  that decision, which ADR-0070 §1 classifies as a supersession and not an
  amendment. The line becomes:

  ```text
  Partially superseded by ADR-0092 (§2a's policy-side exclusion of `EXTERNAL` from the supersedable set)
  ```

  Under ADR-0082 §2, a line taking the leading token moves any qualifier already on
  it into the dated note in the same change, so §1b's ADR-0040 discharge and
  §2a's ADR-0045 narrowing come off `Status` — losing nothing, since both stand in
  full in the existing `Amended:` notes directly below and in §1b's own in-text
  block. This also retires one of ADR-0070 §4's five grandfathered multi-line
  `Status` fields.
- **ADR-0050 — partially superseded; a second pair joins the leading token.** §1
  states the retirement set extensionally — "`provenance.source` is in
  `{OBSERVED, INFERRED}`" — and rules the `EXTERNAL` hold-out with the deferral as
  its reason. §4 makes that sentence false. The line becomes:

  ```text
  Partially superseded by ADR-0079 (§1's over-limit surplus clause) and ADR-0092 (§1's `EXTERNAL` hold-out from the retirement widening)
  ```

  which is ADR-0070 §4's accumulation rule, one physical line, each pair naming
  what its ADR replaced. Under ADR-0082 §2 the record goes in the dated note only,
  and no amendment qualifier joins the line.
- **ADR-0079 — nothing, and this is not an oversight.** §3 states the promoted
  obligation *intensionally*: "every other conflict in the set the policy ruled on
  **whose source is supersedable**". Widening what is supersedable leaves that
  sentence true verbatim and leaves no reader acting differently, so under
  ADR-0082 §1 no record is owed. §3's own load-bearing clause — that a named
  `EXTERNAL` target is retired regardless — is unaffected.
- **ADR-0045 — a dated note, no `Status` edit.** §5, §7 and §10 deferred the
  policy adoption and filed the identity residual; §4 and §6 discharge them, which
  is not a reversal of anything ADR-0045 decided. A note is owed all the same,
  because §7's "the shipped default policy does not yet adopt it" and its
  characterisation of the residual as "no user data is lost" both stop being true
  of the tree, and §Context above corrects the second on the merits. ADR-0045's
  `Status` is a leading-token line, so ADR-0082 §2 puts the whole record in the
  note; no ratified text is rewritten (ADR-0070 §1 is append-only).
- **ADR-0073 — a dated note, no `Status` edit.** §4 deferred the `core` question
  to this lane and §1 answers it, so a reader holding only ADR-0073 would
  otherwise still believe the decision is open. The **gate itself is not
  discharged**: §4 makes carrying both halves "a precondition of [the producer]
  shipping", and no producer has shipped. What changes is that the precondition now
  has a checkable form — an `Attestation` the type refuses to omit — rather than an
  open question. ADR-0073's `Status` is a leading-token line, so the note is the
  whole record.
- **ADR-0072 — nothing.** §2's band definitions and §4's keyed-on-`source` rule are
  relied on, not changed. §5's `ATTESTED`-above-`DERIVED` ordering names its own
  revisit trigger — "when the first real sensor exists" — which has not fired: this
  ADR decides a contract, not a sensor. §10 leaves it.

### 9. What the implementing lanes owe

Sequenced, because the first two collide on `core/types.py` with the lanes
the sensor-seam lane and must not run beside them.

- **`core/types.py`** — the `Attestation` model (both fields required,
  `reported_by` non-empty); `Provenance.attestation: Attestation | None = None`;
  the iff validator (§1); `Provenance`'s class docstring gaining the rule beside
  the two band-keyed validators already there. `MemorySource`, `BeliefBand` and
  `band_of` are **untouched** — this adds no source and moves no band.
  **Precondition on the validator landing**, per §2: the lane confirms through
  `export` — which returns every retained record, window-closed ones included
  (ADR-0045 §6) — that the deployment's store holds no `EXTERNAL` record. Finding
  one falsifies §2's premise, and the lane **stops and reports** rather than
  shipping a decode failure onto retained data. Expected to find none; run because
  §2's admissibility rests on it and an unverified premise is the one thing a
  read-path validator may not rest on.
- **`memory/policy.py`** — the retirement class gains `EXTERNAL` (§4).
  `_rule_on_assertion` arm 2's docstring stops citing the deferral as its reason;
  arm 3's "with only `EXTERNAL` conflicts … the assertion lands beside them" is now
  reachable only when the conflict set is empty.
- **`memory/ingest.py`** — the constant splits in two (§5), and only the retirement
  half widens; `_retirement_set`'s `EXTERNAL` hold-out goes, and with it the
  `retires`-is-a-ceiling passage's second justification (the *rule* stands — a
  confirmation exists to authorise retiring an **assertion**, and the applier's
  widening now sweeps `EXTERNAL` siblings anyway); `_merge` carries the incoming
  attestation (§6).
- **The `MemoryWriter` conformance suite** — the retirement obligation's set widens
  with the class (ADR-0079 §3), and `FakeMemoryWriter` matches it. A case for a
  correction retiring an attested sibling, and a case pinning that a
  `USER_ASSERTED` → `EXTERNAL` `REINFORCE` **still raises** (§5), which is the
  regression a one-line widening would ship.
- **Roughly thirty-four `MemorySource.EXTERNAL` construction sites across seven
  test files** acquire an attestation. Mechanical, absorbable by a fixture, and
  named here because it is the visible cost of choosing a required field over an
  optional one — a cost paid once, now, and unpayable later without a migration
  (§2).
- **The producer lane** — mints its own ids (§6) through a factory **guarded at
  its output** exactly as ADR-0045 §4 guards the applier's (a non-empty `str`, its
  raising caught and re-raised as the writer's error), so a malformed mint fails
  before the store rather than becoming a key. It fills `reported_by` stably, and
  fills `reported_at` **only** from what the source itself says: for `.ics`, a
  `VEVENT`'s `DTSTAMP` (mandatory under RFC 5545) or its `LAST-MODIFIED`. Which of
  the two is a producer decision; reaching outside them is not one, and the file's
  mtime is specifically excluded (§3). An entry that supplies neither is not
  proposed as an attested belief. It **proposes** through the
  `MemoryPolicy` gate and never writes — the sensor-seam lane's ruling, cited here, not
  decided.

### 10. What this ADR does not decide

- **The sensor seam** — what a read-only source is as a contract, how the hub's
  scheduler drives it, its durable cursor, and how it is configured and enabled.
  The sensor-seam lane's, in full (#625).
- **The grant surface.** "You may read my calendar" still has nowhere to live:
  `ActionPolicy` governs *actions*, not *sources*. Leg 6's exit test says "from a
  source the user granted" and nothing records a grant. Its own decision, next
  wave.
- **Whether `ACCEPT` should install insert-if-absent for a producer that mints its
  id.** §6 removes the *systematic* route by which an import addresses a stored
  record; it does not make a minted id provably absent, and the blind upsert behind
  `ACCEPT` is what would. The property is **pre-existing and general** — every
  minting producer in the tree already has it, and ADR-0045 §4 enforced absence for
  `SUPERSEDE` alone — so ruling it here would decide a contract for one caller.
  Filed as issue #630, and named in §6 so the residual is never mistaken for a
  claim. ADR-0081 §8's neighbouring deferral keeps its owner and its trigger; §6
  declines to pull it.
- **Carrying the source's own key on the record, and an index to resolve it.** §7's
  duplication residual is what it would close, and §6 is deliberately a *negative*
  rule — the source's key is not the store's key — rather than a third field. A
  field with no consumer is surface (ADR-0045 §1, ADR-0028 §7), ADR-0073 §4 asks
  for two halves and not three, and the lookup it would serve is a `MemoryStore`
  read surface owing its own ADR. Filed as issue #631, which records the trigger:
  the first observed duplicate from a rewritten entry.
- **Context facets carrying an as-of timestamp and provenance.** Next wave,
  `core/types.py`, sequenced behind the sensor seam.
- **ADR-0072 §5's band precedence.** Its revisit trigger is a real sensor, not this
  contract (§8).
- **Anything about a networked source.** ADR-0017 §1 and §3 are not engaged by a
  local file (ADR-0084 §9), and the first source is local by the owner's ruling.
  The day a source crosses a device boundary, §3's conditions are that lane's and
  nothing here has spent them.
- **#545's model** — expectations, the ledger, met/not-met/unknown. Parked; its own
  header says do-not-implement. This ADR uses it only for the owner's rulings it
  records.

## Consequences

- **The attested band becomes shippable.** ADR-0073 §4's gate had no answer and
  now has a checkable one; the band that ADR-0072 named and nothing could produce
  gets the disclosure its standing was defined in terms of.
- **The user outranks the calendar, and says so on disk.** A correction retires the
  import rather than sitting beside it, the retirement survives in `export`
  (ADR-0045 §6), and a re-sync that contradicts the correction becomes a question
  rather than a write (§7).
- **A half-attested record is unconstructable**, at the cost of a required field
  on a `core` type and thirty-four mechanical test edits (§9). The alternative was
  a convention, and a convention that fails silently on the band whose whole
  warrant is someone else's is the wrong side of that trade.
- **One constant becomes two, and the reason must survive refactoring.** §5's split
  is the kind of thing a later reader tidies back together. The two sets answer
  different questions and the conformance case pinning the `REINFORCE` refusal is
  what stops the tidy-up.
- **Two live records remain possible on a similarity miss** (§7), and a materially
  rewritten calendar entry can duplicate rather than fold (§7, §10). Both are
  duplication, not loss, both are visible to inspection, and both are filed.
- **ADR-0038 §2a's reproduction is now a historical record of a fixed defect**, and
  its `Status` says so for the first time — the third and last thing to move off
  that clause after ADR-0040 and ADR-0045.
- **Revisit when** the first non-local source arrives (ADR-0017 §3's conditions
  become live and `reported_by` starts naming something across a boundary), when a
  producer wants identity by key rather than by similarity (§10's filed lookup),
  or if real sources turn out to report *nothing* about when they spoke often
  enough that §3's no-substitute rule keeps useful records out of the band
  entirely — which would be an argument about what sources actually emit, not
  about the contract, and is the one input this decision could not get before
  shipping a producer.

## Alternatives considered

- **Two nullable fields on `Provenance` and a producer convention.** Rejected in
  §2: it admits two half-answers, and the half-answer is exactly the misleading
  render ADR-0073 §4's floor exists to forbid. The value object costs one class.
- **Put the attestation on `MemoryBase` beside `validity`.** Rejected in §1 on
  ADR-0045 §2's own reasoning, read the other way: `validity` is store-set and
  belongs on the envelope precisely because `Provenance` is producer-set, and an
  attestation is producer-set.
- **Enforce the pair at the `MemoryWriter` seam, like `MAX_EVIDENCE_CITATIONS`.**
  Rejected in §2: the seam is not the only path a `Provenance` takes — `Goal`
  carries one and reaches no gate — and `_derived_is_never_certain` already
  ratified that argument on this class. The seam is right for a bound that must not
  break `export`; it is wrong for a field whose absence is a lie.
- **Rule the override without ruling ids** — widen the supersedable class and stop.
  Rejected in §Context and §7: the adoption alone is what makes the re-sync's
  `ACCEPT` able to land on a retired record, so it would ship the erasure of the
  retirement as the feature's own side effect. The two questions were entangled and
  the brief that separated them was wrong to.
- **Rule ids without ruling the override** — mint opaque ids and leave
  `_SUPERSEDABLE` alone. Rejected: it fixes a hazard nothing can reach, since with
  no adoption there is no retirement to resurrect, and leaves the user unable to
  override the calendar, which is the owner's ruling this lane exists to serve.
- **Keep the source's key as the record id and forbid a re-sync from overwriting a
  retired record.** Rejected in §6. It needs the writer to *see* the retirement,
  and ADR-0045 §6 deliberately hides closed windows from `get` and `search` alike,
  so the check is unimplementable without a new `MemoryStore` read — a Protocol
  growth (golden rule 5) to preserve a coupling §6 removes for free. It also gets
  the semantics wrong: "never re-import" blinds us to a calendar that later changes
  to something the user *would* accept.
- **Carry the source's key as a third `Attestation` field now**, so the lookup
  index is buildable later without touching stored records. Rejected in §10: it is
  surface with no consumer on a migration argument, ADR-0073 §4 asks for two halves,
  and §6's negative rule closes the hazard without it. If the duplication residual
  bites, the field arrives with the index that consumes it.
- **Let a producer fall back to a local timestamp — the file's mtime — when the
  source supplies no report time.** Rejected in §3, and it is the most tempting
  wrong answer here because it keeps every record importable and looks like a
  detail. An mtime is a property of the last local write: a copy, a restore or a
  `touch` moves it while the source's claim does not. Putting it in `reported_at`
  asserts a report the source never made, which is ADR-0073 §4's "true statement
  about us and a false one about the source" wearing the field built to end it — a
  worse outcome than today's, because today the gap is visible and a fallback would
  make it plausible. The band being unreachable for a source that will not say when
  it spoke is the correct outcome, not a limitation to engineer around.
- **Refuse a `reported_at` in our future.** Rejected in §3: it invents a read-path
  failure over clock skew, which is the failure mode §2's admissibility test exists
  to keep this validator clear of.
- **Widen the single `_SUPERSEDABLE` constant in `memory/ingest.py`.** Rejected in
  §5 — it silently disables the `USER_ASSERTED` → `EXTERNAL` `REINFORCE` refusal
  and reopens the exact data loss ADR-0038 §2a reproduced. Listed as an alternative
  rather than left as a note because it is what the one-line reading of §4 produces.
