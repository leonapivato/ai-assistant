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

We will make a user-asserted proposal that conflicts with a non-asserted record
return `MERGE` into that record, rather than `ACCEPT` beside it. Concretely, via
the machinery that already exists:

- the corrected content and the `USER_ASSERTED` provenance are written **at the
  stale record's id**, so exactly one record survives and the wrong belief is
  off the read path immediately;
- `Provenance.evidence` is unioned by `MemoryIngestor._merge`, so the trail that
  produced the inference is retained even though its text is not;
- `confidence` becomes 1.0 and `source` becomes `USER_ASSERTED` — the record
  moves from the user *model* into the user *profile* (ADR-0005 §2), which is
  the correct classification once the user has stated it.

**We decided against three alternatives.**

- **Retire or mark-invalid the stale record and write the correction as a new
  record.** This is the better long-term answer and it is what issue #112
  describes, but there is no representation for "a belief that has stopped being
  true" — `expires_at` is a *retention* deadline (ADR-0004 §6) and overloading it
  would conflate a privacy obligation with a truth claim. Building the
  representation is a `core` change, out of this lane.
- **Delete the stale record.** Strictly worse than merging over it: same loss of
  the old text, and it also discards the evidence list and the record id that
  anything holding a reference would use.
- **`ASK_USER` on every assertion-versus-inference conflict.** Safe, and wrong
  for the product: the user has *just told us*. Turning a correction into a
  question is the interaction that makes an assistant feel like it does not
  listen, and it would fire on the common benign case where the "conflict" is
  the user restating something we had merely guessed.

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

So the existing machinery is good enough for this destructive action *against
inferences specifically* — not because the threshold is trustworthy, but because
the blast radius on that side is bounded and recoverable. It is not good enough
against assertions, and rule 3 below is what keeps it away from them.

### 3. An inference may never supersede an assertion

Stated even though it is obvious, because the whole rule rests on it. The
direction is strictly one-way: an assertion may displace an inference; an
inference may **never** displace an assertion, silently or otherwise. This is not
new — `DefaultMemoryPolicy` already returns `ASK_USER` when a non-asserted
proposal conflicts with a user-asserted record — and this ADR ratifies that rule
as the counterpart of §1 rather than an incidental precaution.

It has a second, less obvious consequence. `conflicts` arrives ordered by
retrieval score, so the top-ranked conflict may itself be user-asserted. The rule
therefore supersedes the best-ranked **non-asserted** conflict, skipping asserted
records rather than taking `conflicts[0]`. Taking the first would have let an
assertion destroy an assertion by ranking accident, which §2 refuses.

### 4. One record is superseded per correction

`MemoryDecision.merge_into` names a single target, and widening it to a list is a
`core` change. Where a correction conflicts with several inferences, the
best-ranked one is superseded and the rest remain until they are re-proposed or
expire. Accepted as a known limit rather than worked around; filed as an issue.

### 5. Assertion-versus-assertion is left as it is

A user-asserted proposal whose only conflicts are user-asserted records is
`ACCEPT`ed beside them, exactly as before. Two things the user said sit at
confidence 1.0 and nothing ranks them; §2 forbids the heuristic from choosing,
and `ASK_USER` would interrogate the user about a "conflict" that is most often
a restatement. This leaves a real gap — a user who contradicts their own earlier
statement gets two live records — which needs the validity window of issue #112
to resolve properly. Filed as an issue.

### 6. Interaction with issue #112 (bi-temporal validity)

Recorded rather than decided. Bi-temporality would keep §1's overwritten text on
disk with a closed validity window instead of losing it, and would give §5 a
principled answer. **This decision does not require it** — merging over the
stale record removes the wrong belief from the read path today, which is the
defect — and it does not foreclose it: when #112 lands, §1's `MERGE` becomes the
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
- **`conflict_threshold` gets sharper teeth.** It already gated a merge; it now
  gates a merge triggered by the highest-trust source in the system. Lowering it
  is no longer only a precision/recall trade on advisory conflicts.
- **The `MemoryPolicy` conformance suite is unaffected.** It deliberately
  asserts no particular ruling — it names issue #38 as the reason — so this
  change lands entirely in `DefaultMemoryPolicy` and its own tests. Any other
  implementation is free to rule differently.
- **Revisit when** issue #112 ratifies a validity window (§1 and §5 both change
  shape), when conflict detection becomes contradiction detection rather than
  similarity (§2's error choice is then re-argued from a better signal), or if
  §4's single-target limit proves to strand stale records in practice.
