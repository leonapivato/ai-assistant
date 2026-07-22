# 38. A user assertion supersedes a conflicting inference

- Status: Accepted
- Date: 2026-07-22
- **Not a contract change.** `MemoryPolicy` is ratified by
  [ADR-0005](0005-memory-model.md) §3 and unchanged here; no Protocol moves, no
  `MemoryDecisionKind` is added, and no `core` type is touched. This ADR changes
  the *ruling* one implementation reaches on inputs the contract already
  describes. Golden rule 5's separate-PR requirement therefore does not apply,
  and this ADR merges with the change it authorises (`CONTRIBUTING.md`,
  "Contract ADRs land before their implementation", which scopes that rule to a
  *substantive contract ADR*).
- **Follow-up to** [ADR-0005](0005-memory-model.md), taking up the question
  [ADR-0009](0009-learning-model.md) §5 recorded and deferred. It supersedes
  nothing: ADR-0009 §5 states the interaction exists and names it out of scope,
  which stays true as history.

## Context

The product thesis is an accumulated user model that improves through continuous
learning. Learning works: a new preference is proposed, ruled on, stored, and
reused. **Unlearning does not.**

`DefaultMemoryPolicy` evaluates its rules in order, and the rule "user-asserted
proposals are trusted and accepted" fired *before* the merge rule. So when a user
explicitly corrected the assistant — "no, I stopped doing that" — and the
correction contradicted an existing **inferred** memory, the correction was
stored as a new record *beside* the stale one. Both stayed live and both stayed
retrievable, one of them wrong, and nothing downstream ranked the correction
above the belief it was issued to replace. ADR-0009 §5 recorded this precisely
and left it for a follow-up; issue #38 tracks it.

The forces:

- **`MemoryDecision` already has a ruling that displaces a record.** `MERGE`
  carries `merge_into`, and `MemoryIngestor` applies it by writing the incoming
  record *at the target's id* — the store's `add` is an upsert, so the target's
  content is replaced in place while `Provenance.evidence` is unioned. Nothing
  new is needed in `core` to express supersession.
- **Conflict detection is a heuristic built for an advisory job.**
  `MemoryIngestor._detect_conflicts` retrieves same-kind records whose retrieval
  score clears `conflict_threshold` (0.75 by default). Under the in-memory store
  that score is lexical term overlap; under `SqliteMemoryStore` it is embedding
  similarity. Neither establishes *contradiction* — only topical proximity. A
  ruling that overwrites a record is destructive in a way `ACCEPT` and
  `ASK_USER` are not, and this signal was not designed to authorise it.
- **Records are not versioned.** There is no validity window and no history: a
  record overwritten at its id leaves no trace of what it said before. Issue
  #112 proposes bi-temporal validity, which would turn "overwrite" into "close
  the old window and write a new record". That is a `core` change with its own
  ADR and is **not decided here.**

## Decision

### 1. Supersession means `MERGE` over the stale record, at its id

We will make a user-asserted proposal that conflicts with a *derived* record
(§2a fixes which sources those are) return `MERGE` into that record, rather than
`ACCEPT` beside it. Concretely, via the machinery that already exists:

- the correction is written **at the stale record's id**, so exactly one record
  survives and the wrong belief is off the read path immediately;
- `confidence` becomes 1.0 and `source` becomes `USER_ASSERTED` — the record
  moves from the user *model* into the user *profile* (ADR-0005 §2), which is
  the correct classification once the user has stated it;
- **nothing else of the overturned record is carried across** — see §1a, which
  is why supersession does not reuse `MemoryIngestor._merge`.

**We decided against three alternatives.**

- **Retire or mark-invalid the stale record and write the correction as a new
  record.** This is the better long-term answer and it is what issue #112
  describes, but there is no representation for "a belief that has stopped being
  true" — `expires_at` is a *retention* deadline (ADR-0004 §6) and overloading it
  would conflate a privacy obligation with a truth claim. Building the
  representation is a `core` change, out of this lane.
- **Delete the stale record.** Strictly worse than superseding it: the same loss
  of the old text, and it also discards the record id that anything holding a
  reference would use.
- **`ASK_USER` on every assertion-versus-inference conflict.** Safe, and wrong
  for the product: the user has *just told us*. Turning a correction into a
  question is the interaction that makes an assistant feel like it does not
  listen, and it would fire on the common benign case where the "conflict" is
  the user restating something we had merely guessed.

### 1a. A correction does not inherit the evidence of the belief it overturns

Supersession does **not** route through `MemoryIngestor._merge`, and this is the
part of §1 most likely to be got wrong by someone reaching for the nearest
existing helper.

`_merge` unions `Provenance.evidence` and takes the maximum `confidence`,
because it was written for records that **agree** — its own docstring says a
merge "strengthens rather than weakens what is known." That is reinforcement,
and supersession is its opposite: the incoming assertion was paired with the
target precisely because they *contradict*.

ADR-0005 §2 defines `evidence` as references **supporting** the record, and
ADR-0005's Consequences make it the field callers use to "explain *why* a memory
exists." So unioning is not a harmless carry-over here. Correct an inferred
"prefers mornings" — evidence `["morning-event"]` — to "prefers afternoons", and
the union attaches the observation that produced the *wrong* belief as
justification for the right one. That is a fabricated warrant, and it is worse
than the stale record this ADR exists to remove: a stale record is at least
honestly attributed.

So supersession takes its own path. The superseding record is the incoming
record rehomed onto the target's id, and nothing else: **a user's assertion is
its own warrant and does not borrow the support of the belief it overturns.**
`_merge` keeps its reinforcement-only semantics and now documents that
precondition, and `MemoryIngestor` picks between the two by reading the pair's
provenance — a `USER_ASSERTED` record landing on a derived one — rather than by
the ruling, since `MemoryDecisionKind` has one `MERGE` for both relations and
splitting it would be a `core` change.

**Discarding is not the same as preserving.** Keeping the displaced evidence as
*history* — "this is what we once believed, and why" — is a legitimate goal and
the right one; it simply is not this field's job, and the representation for it
is what issue #112 proposes. Until that exists the honest choice is to drop the
evidence rather than to relabel it as support for a claim it never supported.

### 1b. This decision rests on a precondition the contract cannot express

§1a has the ingestor decide *which relation a `MERGE` expresses* by reading the
two records' provenance. That is not where the answer belongs. The only party
that knows whether a merge reinforces or overturns is the policy that ruled, and
`MemoryDecision` has no field in which to say it — one `MERGE` serves both
relations. Both review personas identified this independently, and they are
right.

**So this decision is sound only while every `MemoryPolicy` that can reach the
ingestor in production returns `MERGE` for a `USER_ASSERTED` proposal solely to
mean supersession.** That is a real precondition of ADR-0038, not an incidental
property of the code that implements it, and it is stated here so that a future
policy author meets it as a constraint on their design rather than discovering
it as data loss.

Inside the quadrant that matters — asserted proposal, non-asserted target,
ruling `MERGE` — **no rule available to `memory` can distinguish the two
relations**, because the distinguishing fact lives in the policy and has no
channel. Any implementation choice here picks one reading. Narrowing which
sources are supersedable (§2a) moves the boundary; it does not remove the
ambiguity, and a later attempt to fix this by narrowing further will not
converge either.

Two things make it acceptable to decide this inside the policy lane rather than
stopping for the contract change:

- **The misclassification is unreachable for every policy that exists.**
  `DefaultMemoryPolicy` has exactly two `MERGE` sites, partitioned by whether
  the proposal is user-asserted, so no ruling of its can be read the wrong way.
- **The precondition is guarded rather than merely written down.**
  `tests/memory/test_ingest.py` enumerates the `MemoryPolicy` implementations in
  the `memory` subsystem and fails if any returns `MERGE` for an assertion onto
  a record that is not `OBSERVED` or `INFERRED`. Writing the policy that would
  trigger the loss therefore fails the gate, naming this section, instead of
  silently destroying evidence at runtime.

The guard is deliberately **not** in the `MemoryPolicy` conformance suite. A
conformance suite is contract; the Protocol states no such obligation, so
asserting it there would widen the contract without an ADR and would refuse a
policy that genuinely conforms (issue #40). It is a precondition over what this
repository ships, and it is tested as one.

Issue #256 carries the removal: represent supersession on the decision itself —
most likely folded into issue #112's invalidation ruling, which needs a ruling
of its own regardless. When that lands, the inference in §1a and the guard here
both go away, and the relation is read from the decision where it belongs.

### 2. The error we choose: over-supersede inferences, never destroy an assertion

The conflict signal is topical, not contradictory, so both errors are live: a
false-positive conflict superseding a correct memory, and a missed conflict
leaving a wrong one. **We accept false-positive supersession of an inferred
record, and refuse it for a user-asserted one.**

The asymmetry is about what the two cost to be wrong about:

- An inference is **derived and re-derivable.** Its `confidence < 1.0` marks it
  as provisional by construction, the evidence that produced it survives the
  merge, and if it was in fact still true the same observations will propose it
  again. Overwriting one wrongly costs a belief the system can rebuild.
- An assertion is **given and not re-derivable.** Nothing but the user can
  restore it, and it is the highest-value data in the store. Overwriting one on
  the strength of a 0.75 lexical or embedding score is a loss with no recovery
  path.

So the existing machinery is good enough for this destructive action *against a
derived belief* — not because the threshold is trustworthy, but because the
blast radius on that side is bounded and recoverable. It is not good enough
against assertions, and rule 3 below is what keeps it away from them.

### 2a. Supersedable is an allow-list of `OBSERVED` and `INFERRED`

The rule tests membership of those two sources, **not** `is not USER_ASSERTED`.
Both readings agree on every source ADR-0005 §2 defines except `EXTERNAL`, which
is neither derived by us nor given by the user, and which may carry confidence
1.0. It is excluded, for a mechanical reason rather than a philosophical one.

Supersession keeps the *target's* id (§1). An external record's id is the
integrating system's idempotency key, so a correction merged into one inherits
that key — and `MemoryIngestor._detect_conflicts` excludes an existing record
whose id equals the proposal's. The next routine sync therefore proposes that
same id, sees no conflict, and its upsert restores the external value over the
user's correction. Verified before excluding it, on the tree that had `EXTERNAL`
supersedable:

```text
correction : merge  calendar:1  ->  "user works from the berlin office"  user_asserted
re-sync    : accept calendar:1  ->  "user works from the london office"  external
```

That is §2's error direction pointing the wrong way: the unrecoverable thing —
what the user told us — is the thing destroyed, and silently. Excluding
`EXTERNAL` means an assertion contradicting an imported record is `ACCEPT`ed
beside it, which is exactly the pre-existing behaviour and leaves nothing worse
than issue #38 already described for that source.

An allow-list is also the safer default going forward: a `MemorySource` added
later is not silently enrolled in a destructive rule by omission.

Resolving `EXTERNAL` properly needs either an id discipline that keeps a
superseding correction off the external key, or the validity window of issue
#112 — not a policy rule. Filed as issue #254.

### 3. An inference may never supersede an assertion

Stated even though it is obvious, because the whole rule rests on it. The
direction is strictly one-way: an assertion may displace an inference; an
inference may **never** displace an assertion, silently or otherwise. This is not
new — `DefaultMemoryPolicy` already returns `ASK_USER` when a non-asserted
proposal conflicts with a user-asserted record — and this ADR ratifies that rule
as the counterpart of §1 rather than an incidental precaution.

It has a second, less obvious consequence. `conflicts` arrives ordered by
retrieval score, so the top-ranked conflict may itself be user-asserted. The rule
therefore supersedes the best-ranked **supersedable** conflict, scanning past
anything else rather than taking `conflicts[0]`. Taking the first would have let
an assertion destroy an assertion by ranking accident, which §2 refuses.

### 4. One record is superseded per correction

`MemoryDecision.merge_into` names a single target, and widening it to a list is a
`core` change. Where a correction conflicts with several inferences, the
best-ranked one is superseded and the rest remain until they are re-proposed or
expire. Accepted as a known limit rather than worked around; filed as issue #244.

### 5. Assertion-versus-assertion is left as it is

A user-asserted proposal whose only conflicts are user-asserted records is
`ACCEPT`ed beside them, exactly as before. Two things the user said sit at
confidence 1.0 and nothing ranks them; §2 forbids the heuristic from choosing,
and `ASK_USER` would interrogate the user about a "conflict" that is most often
a restatement. This leaves a real gap — a user who contradicts their own earlier
statement gets two live records — which needs the validity window of issue #112
to resolve properly. Filed as issue #245.

### 6. Interaction with issue #112 (bi-temporal validity)

Recorded rather than decided. Bi-temporality would keep §1's overwritten text on
disk with a closed validity window instead of losing it, would give §1a's
displaced evidence a home that is *history* rather than forged support, would
let §2a supersede an `EXTERNAL` record without inheriting its key, and would give
§5 a principled answer. It is the right answer to four of this ADR's five
compromises, which is worth saying plainly.

**This decision still does not require it.** Superseding the stale record
removes the wrong belief from the read path today, which is the defect issue #38
names, and every compromise above degrades to *less capability*, never to
incorrectness — the one case where it would have degraded to incorrectness, a
correction wearing the evidence of what it overturned, is closed in §1a by
discarding rather than by waiting for #112.

Nor does it foreclose #112: when that lands, §1's supersession becomes the
natural place to close the target's window, and the rule ordering here is
unchanged by that.

## Consequences

- **The system can unlearn.** "No, I stopped doing that" now removes the belief
  it contradicts instead of adding a second, contradictory one. This is the
  second half of the learning loop ADR-0009 built.
- **The default policy has one more destructive path.** `MERGE` was previously
  reachable only from a non-asserted proposal; it is now reachable from a
  correction, and a false-positive conflict costs an inferred record. That is
  §2's chosen error, and it is the thing to look at first if memories start
  disappearing unexpectedly.
- **The ingest path's existing lost-update window now spans corrections.**
  `MemoryIngestor.ingest` is an unsynchronised search-decide-write, so two
  concurrent merges into the same target already lose one (true on `main`
  before this decision, for non-asserted proposals). Widening which proposals
  reach `MERGE` widens what can be lost to include a user correction. Not fixed
  here — the mechanism is in the ingestor, not the policy, and a sound fix is
  either a lock or a compare-and-swap on `MemoryStore` — but recorded as issue
  #248 rather than left implicit, because §3's guarantee is about the *ruling*
  and does not survive a lost update.
- **`MERGE` now means two different things at the ingestor, told apart by
  provenance.** Reinforcement keeps `_merge`; contradiction takes `_supersede`
  (§1a). The cost is a second fold path and a precondition on `_merge` that a
  reader must respect; the benefit is that neither path silently does the
  other's job. If `MemoryDecisionKind` ever gains an invalidation ruling
  (issue #112), that discrimination moves back onto the decision where it
  belongs and this inference disappears.
- **A correction loses the overturned belief's evidence outright**, because
  there is nowhere honest to keep it (§1a). This is a real loss of audit trail,
  chosen over a false one, and it is the first thing #112 should give back.
- **Writing a new `MemoryPolicy` now carries a constraint that is not on the
  Protocol** (§1b): its `MERGE` rulings for user-asserted proposals must mean
  supersession. The gate enforces this for policies in the `memory` subsystem,
  so the constraint is discovered at author time; it is still a seam that
  should not exist, and issue #256 is what removes it.
- **`conflict_threshold` gets sharper teeth.** It already gated a merge; it now
  gates a merge triggered by the highest-trust source in the system. Lowering it
  is no longer only a precision/recall trade on advisory conflicts.
- **The `MemoryPolicy` conformance suite is unaffected.** It deliberately
  asserts no particular ruling — it names issue #38 as the reason — so this
  change lands entirely in `DefaultMemoryPolicy` and its own tests. Any other
  implementation is free to rule differently.
- **Revisit when** issue #256 puts the reinforce/supersede distinction on the
  decision contract (§1b's precondition and its guard both retire), when issue
  #112 ratifies a validity window (§1, §1a, §2a and §5 all change shape), when conflict detection becomes contradiction detection rather than
  similarity (§2's error choice is then re-argued from a better signal), or if
  §4's single-target limit proves to strand stale records in practice.
