# 115. The writer contract carries the reading: one call, one hold, one reconciliation

- Status: Accepted
- Date: 2026-08-07
- **Note (2026-08-07): ratified, over one waived `blocker`.** `Proposed` →
  `Accepted`, in the separate lane #633 requires. The outcome ADR-0070 §1 obliges
  this edit to record — "the ratifying edit records that review's outcome, it does
  not replace it" — is **not** a uniformly green set, and it is written as it
  stands rather than smoothed: at round 18, 823 lines net across 1 commit, churn
  reported as a lower bound of `≥1.0×` (823 touched; history was rewritten, so
  earlier rounds are not counted), **architecture** returned **APPROVE with no
  findings** and **adversarial** returned **BLOCK** on a single `blocker`, which
  #810's lane **waived with its rationale** and filed as **#815**, open. All of it
  is taken from the `just ship` comment and the description on #810 rather than
  from a report.

  **A waived `blocker` is a ratifiable state, and the texts say so directly.**
  `CONTRIBUTING.md` → "Triage every finding" rules that "Waiving a
  `blocker`/`major` is allowed — write the rationale in the PR or the commit", and
  that "Review is advisory tooling, not a hard gate; the only required check is
  `gate`", which was green. The waiver's own ground is recorded on #810: §1's
  sentence that no implementation "may read" `SourceReading.facet` is unmarked
  prose, so under ADR-0089 §3 it binds nothing in a marked ADR — technically
  correct, and waived because reading `facet` breaches no clause that *is* marked,
  every neighbouring obligation being separately marked and separately tested.

  **This edit does not repair it, and that is a rule rather than a preference.**
  The remedy #815 records is either to mark the prohibition or to soften it to a
  description; both change what this ADR obligates, and ADR-0070 §1 puts any
  change to what was decided outside an in-place edit entirely — `CONTRIBUTING.md`
  → "Trivial ADR edits" says the ratification flip is "not licence to rewrite a
  ratified decision in place", and a ratifying edit is exempt from separate review
  precisely because it records rather than decides. #815 is where that judgement
  is made, by a lane whose change a reviewer reads.

  **This note's date is UTC, as is every timestamp it cites.** #810 merged at
  `2026-08-07T10:05:24Z` and this flip follows it on the same UTC day. This clone
  renders `git log` at `-0400`, an offset under which that merge reads
  `2026-08-07 06:05` — the same calendar day, so the two frames agree here and a
  reader need not reconcile them. The `Date` line above is this ADR's authoring
  date in that same local frame, and the flip does not touch it.

  **Both lenses ran on the decision; this ratifying edit takes one.** The header's
  Surface bullet triggers golden rule 5 — one method on `MemoryWriter` in
  `core/protocols.py` — so this is "the ADR deciding that surface" under
  `CONTRIBUTING.md` → "Report the review, then mark it ready", which is why
  architecture as well as adversarial is recorded above, both taken while this ADR
  still stood `Proposed` (ADR-0015 §5). The flip is reviewed adversarial-only
  because "Trivial ADR edits" exempts it from a separate review *of the edit
  itself*, ADR-0015 §5 exempts trivial ADRs by name, and `scripts/ship.sh` fires
  its own architecture requirement on a diff touching `core/protocols.py` or
  `core/types.py`, which this diff does not.

  **The anchor is not the merged head, and the identity is established through the
  tree rather than assumed**: the comment's
  `<!-- ship:00404c52be1cd422ccc6cb1a479ce561cdbf733d -->` anchor is the pre-merge
  branch head, which is *not* an ancestor of `main` because #810 was
  rebase-merged. Both were resolved with `git rev-parse` rather than trusted:
  `00404c52be1c^{tree}` and `e5cfc4e6a02d^{tree}` — the commit the PR merged as —
  are the same tree, `5ca5dc40f53f`. The content the review read is therefore the
  content that landed, notwithstanding the rewritten hash.

  **Beyond the `Status` line, not one word below is edited** — not a clause, not a
  tense — which is ADR-0070 §1's own test applied to the ratifying edit first: no
  decision text is touched and no normative clause acquires, loses or alters an
  obligation. The line carries no leading `Partially superseded by` token, so
  ADR-0082 §2 would permit an amendment qualifier on it; none is written, because
  a ratification is not an amendment and has none to record.

  **ADR-0110's `Status` line is deliberately not touched.** It reads `Partially
  superseded by ADR-0115 (…)`, and this flip leaves it exactly as §8 above wrote
  it. **ADR-0082 §7 settles it by name**: ADR-0070 §1's condition "is that the
  superseding ADR **exists**, not that it is ratified — the hazard §1 names is a
  `Status` line pointing at nothing, and an atomic pair makes that unreachable",
  and the contrary reading is filed there as "#458 … not a governance gap but a
  reviewer failure mode". The line was therefore well-formed when written, and
  ratification neither repairs nor widens it. **ADR-0070 §4** points the same way
  from the grammar: the machine-legible part is the leading token and the
  `ADR-NNNN` references, so nothing on that line encodes this ADR's status and a
  consumer extracts an identical value before and after. And **ADR-0082 §2** has
  no operation to perform, because a ratification is neither an amendment nor a
  supersession of ADR-0110. Of ADR-0070 §1's permitted header edits, the
  supersession is already recorded and the line already matches what landed, so an
  edit here would rewrite a settled record with no decision behind it. ADR-0110's
  dated note is left standing for the same reason and needs no lapse recorded: it
  says the record is written "rather than at ADR-0115's ratification" and that the
  pair is atomic, both of which stay true.

  **That the status-claim sweep is otherwise empty is a result rather than an
  omission, and the sites are named so it can be checked rather than trusted.** No
  tracked file describes this ADR as `Proposed`, pending or unratified. Outside
  this document the only matches for `0115` are ADR-0110's `Status` line and dated
  note, ADR-0116 (§7's "no record is owed" entry and two Context passages, each
  turning on what this ADR *decides* and none on its standing), and `uv.lock`,
  where the digits occur only inside hash fragments; `docs/roadmap.md` does not
  mention this ADR at all. **No clause below was written forward for this event to
  make true**: §8's own "It is written now rather than at ratification" is
  satisfied by ratification rather than falsified by it, this ADR closes no issue
  on ratification, and it conditions no obligation on it. Refs #729, #639, #803,
  #248, #458, #815, #633.
- **Durability clause.** Every reference below to ADR-NNNN is to its text as merged
  on 2026-08-07, not to its status on any later day. Where a later ADR changes one
  of them, this ADR is read against the text quoted here and the later ADR's own
  record says what moved.
- **This is the contract ADR-0110 §10 said was not needed, and the implementation
  found was.** ADR-0110 §10 rules that its mechanism "is buildable on the `core`
  surface that exists plus §10's one optional field", and in the same clause that a
  lane concluding otherwise "owes its own ratified ADR for it under golden rule 5,
  and may not read this one as pre-authorising it". The lane concluded otherwise, on
  evidence rather than preference (Context). This ADR is that owed record.
- **Surface.** This ADR decides **one method**, with its exact signature, on the
  `MemoryWriter` Protocol in `core/protocols.py`. It adds **no** type to `core/types.py` — every value it
  exchanges already exists, `SourceReading.coverage` included, which
  [ADR-0110](0110-a-covered-readings-absence-closes-a-window-and-a-clock-never-does.md)
  §2 decided and #803 landed. Golden rule 5 is therefore triggered: this ADR is
  ratified and merged as its own PR before anything implements against it (ADR-0015
  §5), and the triad — the Protocol change, the extended `MemoryWriterContract`, and
  the canonical fake — lands together in the implementation lane behind it.
- **No implementation lands with it.** No `src/`, no `tests/`. The reconciliation
  ADR-0110 §3 decides, its wiring, and the composition-root change are an
  implementation lane's act against this text once ratified, never this ADR's.
- **This ADR partially supersedes ADR-0110, in one narrow scope**: §10's ruling that
  the mechanism is buildable on the existing `core` surface and that `MemoryWriter`
  is untouched. **The record lands on ADR-0110's `Status` line and dated note in this
  same change**, because ADR-0070 §1's condition is that the superseding ADR *exists*
  and this one does — ADR-0082 §7 states that in terms and names the opposite reading
  as a recurring reviewer failure mode (#458). §8 states the scope and the tests.
  Every other ruling of ADR-0110 stays accepted and this ADR is built on them — §1's
  spine, §2's coverage, §3's four conditions, §4's presence and suspension, §5's
  retirement obligations, and above all §5a's serialisation prerequisite, which is
  the clause that *forces* this contract rather than merely permitting it. Refs #729,
  #639, #803, #248, #458.

## Context

### The prerequisite and the seam pull in opposite directions

ADR-0110 §3 decides when a covered reading's absence may close a validity window,
and §5a makes one thing a hard prerequisite of building it:

> The reconciliation §3 authorises may not be implemented until its selection, its
> ingest and its closes are **serialised against every other writer on the same
> store** — either because the composition runs one writer and the reconciliation
> shares its serialisation, or because the compare-and-swap ADR-0046 §5 scopes to
> its own lane exists and the closes are conditional on the selected records being
> unchanged. An implementation over an unserialised read-modify-write is refused.

§5a also names which half of that disjunct it expects: "The reconciliation runs on
the hub's scheduler (ADR-0083 §7), where the ingest path it consumes already runs; a
single writer serialised as #262 serialises one today satisfies the clause with no
new `core` surface at all." The lock in question is `MemoryIngestor`'s own, taken
inside `MemoryIngestor.ingest`, one proposal at a time.

§10 concluded from that expectation that no Protocol member is owed: "§5's closes go
through `write_atomic`, which ADR-0046 landed, and §6's enumeration through
`list_beliefs`, which ADR-0073 §1 landed."

**Both statements are true about the individual store calls and neither is true
about the sequence**, which is what the implementation lane discovered.

### What the implementation found, in three review rounds

The evidence is on PR #803 and is summarised here because it is the ground of this
decision rather than background to it.

**Round 1 — the per-proposal seam does not serialise the sequence.** The first
implementation kept `MemoryWriter.ingest` per proposal and added a separate
reconciliation sharing the same lock, so that *each* of the three steps was
serialised. Adversarial review refused it, correctly: a writer landing between the
last ingest and the selection changes what the reading's account says is present,
and a close computed from that account retires a belief the store was told about
after the reading looked. ADR-0046 §5 states the general form — "Atomic-write-set is
orthogonal to read-modify-write isolation" — and §5a's own sentence names all three
steps together rather than severally.

**Round 2 — the fix works, and it puts the whole reading inside one hold.** Moving
the ingest inside the reconciliation's lock hold satisfies §5a: one acquisition
covers ingest, selection and closes, so there is no gap to reason about. That is the
shape this ADR contracts for.

**Round 3 — but the resulting call has nowhere to live.** With the whole reading
entering `memory` as one operation, `orchestration` must *make* that call, and no
`MemoryWriter` member carries it. The lane typed the injected bound method as a
callback Protocol local to `orchestration`. Architecture review refused that, and the
refusal is right on the corpus's own terms: golden rule 1 requires subsystems to
"talk to each other only through the Protocols in `core/protocols.py`", and a local
structural type changes where the *annotation* lives, not what the dependency is —
no alternate `MemoryWriter` can supply the operation, so `orchestration` depends on a
`memory` capability that no shared contract represents.

**The precedent the lane appealed to does not reach.** It cited
`service.scheduler.JobBody`, which types a bound `Engine` method. That is a
different relation: `AssistantEngine` is a *concrete promoted surface* that ADR-0085
§1 fixes deliberately, and `service` sits above the composition root and consumes it
as a façade. `orchestration` reaching a `memory` concrete is the relation golden rule
1 is about. `MemoryWriteStage`'s `id_factory` is weaker still — a pure function, not
a subsystem capability.

### So the disjunct's cheap half is not free after all

§5a offered two routes and this is the state of both:

- **A shared serialisation.** Available, and it is what the implementation does —
  but only if the writer can hold its lock across the ingest, which requires the
  reading to reach the writer as one call, which requires this contract.
- **The compare-and-swap.** Unavailable by ADR-0110's own §5b, which "does **not**
  design that primitive and adds no concurrency token to `MemoryRecord`", scoping a
  `MemoryWriteMode.IF_UNCHANGED` and its token to ADR-0046 §5's own lane and #248.

Neither carrying coverage on the proposal instead of the reading nor letting
`orchestration` reconcile through `MemoryStore` reaches a third route: ADR-0110 §2
pins coverage to `SourceReading`, §4 defines presence over the *whole* reading's
results, and a reconciliation driven from `orchestration` holds no lock at all.

**This is golden rule 5 working rather than failing.** ADR-0110 §10 predicted the
surface honestly and made its own prediction falsifiable in the same clause, by
naming what a lane owes if the prediction did not hold. It did not hold; this is the
record.

## Decision

### 1. `MemoryWriter` gains one member, and it takes a reading's worth of work

> **Normative.** The `MemoryWriter` Protocol in `core/protocols.py` gains **exactly
> one** new method, with exactly this signature:
> `async def ingest_reading(self, reading: SourceReading) -> Sequence[MemoryIngestResult]`.
> It returns **one** `MemoryIngestResult` **per proposal in `reading.proposals`, in
> that order**. No other `MemoryWriter` or `MemoryStore` member is added, widened or
> changed by this ADR.

**The signature is ratified here rather than left to the lane, and that is golden
rule 5 read plainly**: a Protocol member whose name and parameters are still open is
not a contract anything can be built against, and ADR-0015 §5's whole point is that
the shape is visible before another stream builds on it. ADR-0110 §2's
rename-class argument — "a second implementation choosing another name has renamed
something, not decided something" — is about a *field on a value object* whose
domain that ADR pinned; a Protocol member is the surface itself, and ADR-0114 pinned
`walk_records` and `advance_walk` exactly rather than describing them. This ADR
follows that precedent.

**It takes the whole `SourceReading`, and the cohesion is a safety property rather
than a convenience.** A member accepting proposals, `source` and `coverage` as three
arguments admits a call that pairs one reading's proposals with **another** reading's
source and coverage — and that call is not a tampering attack, it is an ordinary
mistake that type-checks. ADR-0110 §3 would then evaluate its four conditions against
a coverage the proposals never came from, closing records on the strength of a slice
nobody exhausted: §6's failure reached by a road §6 does not guard. Passing the
reading makes the mismatch **unrepresentable** instead of forbidden, which is the
disposition this corpus prefers wherever it is available — ADR-0110 §3 makes
`ASSERTED` "unreachable rather than excluded, which is the stronger form and the one
ADR-0080 §2 preferred for the same band".

**The writer receives three fields it does not use** — `read_at`, `as_of` and
`facet` — and that is the price, paid deliberately. It is smaller than it looks:
`SourceReading` is a frozen `core` value that already crosses this boundary's
neighbours, and a writer ignoring a field is ordinary, where a caller silently
crossing two readings is not. `facet` is `context`'s half (ADR-0096 §5) and no
implementation of this member may read it, which §5's sibling clause below already
implies and which the conformance suite has no need to test — nothing observable
turns on a field nobody reads.

`MemoryWriter.ingest` is untouched and stays the seam for a single proposal. The
learn leg and the observation stage propose one at a time and have no reading, no
coverage and nothing to reconcile; giving them a batch call would be surface with no
consumer, which ADR-0045 §1 and ADR-0028 §7 both refuse.

**One result per proposal in the proposals' order is contract rather than
convenience**, because ADR-0110 §4 defines presence as "the record's id is among the
`MemoryIngestResult.record_id` values that ingesting `R`'s proposals returned" and
its suspension clause fires on *any* proposal that stored nothing. A return that
collapsed, reordered or omitted results would make both unanswerable, and the caller
also needs the pairing to park the question a deferral raised (§5). `Sequence` rather
than a concrete container follows `MemoryStore.write_atomic`, which returns
`Sequence[str]` for the same reason: the caller reads it in order and does not own it.

### 2. The reading is one call, and that is the whole point

> **Normative.** A consumer holding a `SourceReading` whose ingest may reconcile
> **puts that reading through §1's member in one call**. It may not ingest the
> proposals individually and request a reconciliation separately, whether through
> this Protocol or any other, and may not construct a reading it did not receive in
> order to pass parts of two.

This is the clause the contract exists for. Two calls reintroduce exactly the gap
round 1 was refused for, and the refusal would not recur, because a gap between two
correct calls is invisible to every test that does not script the interleaving.

**It binds the consumer rather than the implementation** because that is where the
decision is made. An implementation handed a `SourceReading` still cannot tell
whether it is the one the reader returned or one the caller assembled, which is why
the clause is needed *even though* §1's signature already removes the mismatch that
matters most. §1 makes the two-reading pairing unrepresentable; this clause covers
what a type cannot reach — a caller that splits one reading's proposals across two
calls, or synthesises a reading to widen a coverage. The two work together, and
neither is redundant: the structural half is what holds when someone stops reading
this ADR, and the normative half is what tells them why.

### 3. The implementation holds its serialisation across the whole call

> **Normative.** For a reading that **declares a coverage**, an implementation of
> §1's member **serialises the ingest of every proposal, the selection of ADR-0110
> §3's candidates, and the closes against every other writer on the same store, as
> one indivisible sequence** — not as three separately serialised steps. Where it
> serialises by a lock, that is one acquisition spanning all of them.

> **Normative.** Where the reading declares **no** coverage there is no
> reconciliation, so there is no read-modify-write to isolate and this section
> imposes nothing beyond what `MemoryWriter.ingest` already carries for each
> proposal in turn.

> **Normative.** An implementation that cannot provide that guarantee **refuses a
> reading that declares a coverage** by raising `MemoryStoreError`, before any
> proposal is ingested and any close is written, preserving the underlying cause
> where there is one. Ingesting the proposals and silently declining to reconcile is
> not permitted: the caller cannot tell that outcome from a reading that warranted no
> absence.

**The refusal's type is pinned rather than left to the lane**, on ADR-0103 §9's
test: `CONTRIBUTING.md` confines every raise to the `AssistantError` hierarchy, but
that still admits two implementations choosing two different members and both
claiming compliance, while the boundaries above — the orchestration stage and the
CLI — handle `MemoryStoreError` as the recoverable memory fault. `MemoryStoreError`
is also what this corpus already raises for a writer-side refusal that protects the
store's integrity: ADR-0080 §7 rules the unrepresentable-window refusal "plain
`MemoryStoreError` and specifically **not** `UnresolvedEvidenceError`", and this is
the same shape one act over. **Before any write** is the load-bearing half — a
refusal after a partial ingest is the half-applied outcome §3 exists to prevent,
wearing an exception.

This is ADR-0110 §5a's prerequisite restated as an obligation on the seam that can
actually carry it, and it is what makes §5a's cheaper half true rather than hoped
for. The reason is ADR-0046 §5's, quoted in Context: atomicity of a write *set* says
nothing about the read that produced it.

**§4's guarantee is about the *successful* call, and the second clause says what a
failure does.** A `None` coverage removes the reconciliation, not the ordinary ways
an ingest can fail: a proposal can still be refused by the policy or hit a store
fault, and §3 preserves each proposal's existing `ingest` behaviour exactly. Saying
"not an error" without qualification would have promised a call that cannot fail,
which no loop of `ingest` can offer. The failure behaviour is the one the corpus
already has for the per-proposal loop — propagate, leave the earlier writes applied,
claim nothing about the rest — and it is stated rather than inferred because §4 is
where a reader looks for what the default path does.

**The scoping to covered readings is not a softening, and without it the section
contradicts §4.** A reading declaring no coverage is the repository's default — no
reader on `main` declares one — and §4 requires that such a reading be ingested and
says in terms that this "is not an error, not a refusal". An unscoped §3 would oblige
an implementation that cannot serialise to refuse that reading too, and no
implementation could satisfy both clauses for the input every caller actually sends.
The scoping is also what the reasoning always supported: the thing being isolated is
the reconciliation's read-modify-write, and where there is no reconciliation there is
nothing to isolate — the ingests are then exactly the per-proposal writes
`MemoryWriter.ingest` already serialises one at a time, which is what happens today.

> **Normative.** Where any proposal of a **covered** reading raises, the error
> propagates, the proposals ingested before it stay applied, and **no window
> closes** — the reconciliation is not attempted on a partial ingest, and an
> implementation may not reconcile from a `finally` or other cleanup path.

**That is stated as a clause rather than left in the prose beside one, because in a
marked ADR the prose binds nothing** (ADR-0089 §3). An earlier revision asserted it
here unmarked, which under §3 discarded it: an implementation that reconciled in a
`finally` would close records on a reading that was never fully accounted for, and
would satisfy every other obligation in this ADR while doing it. The behaviour is
also the conservative direction rather than a convenience — it is ADR-0110 §4's
suspension clause reached by a second road, since a reading whose account is
incomplete warrants no absence whatever the incompleteness was.

**A reading whose ingest raises part-way closes nothing**, because the
reconciliation is never reached — the safe direction, since a reading that was never
fully accounted for warrants no absence at all (ADR-0110 §4's suspension clause,
reached by a different road).

### 4. No coverage means no reconciliation, and the proposals still land

> **Normative.** Where the reading's coverage is `None` and every proposal's ingest
> succeeds, §1's member **ingests every proposal and closes no window**. That
> outcome is not an error, not a refusal, and not distinguishable in its results
> from a reading whose coverage warranted no absence.

> **Normative.** Where an individual proposal's ingest raises under a `None`
> coverage, the error **propagates** unchanged, the proposals ingested before it
> stay applied, and no window closes. Nothing about the absent coverage suppresses,
> wraps or retries an ingest failure.

ADR-0110 §2 already rules that a reading declaring no coverage "warrants no absence",
and this is that rule at the seam. It is also what keeps the contract additive in
practice: no reader in the tree declares a coverage, so every call takes this arm
until a reader lane opts in, and the behaviour is exactly today's.

### 5. The durable question is parked outside the hold, by the caller

> **Normative.** §1's member **neither enqueues nor reaches a `DeferralStore`**, and
> an implementation may not acquire one. Whatever queuing ADR-0078 requires of an
> `ASK_USER` ruling is performed by the orchestration write stage, from the returned
> results, **after** §3's serialised sequence has completed.

> **Normative.** The consumer takes its **own** deep snapshot of the reading the
> reader returned, before awaiting §1's member; it forwards **that snapshot** to the
> member, and enqueues from **that same snapshot** paired with the returned results
> by index. It never forwards or enqueues from a reading it re-reads after the await.

**One snapshot, taken once, used for both — which is what makes §2 and this clause
consistent rather than competing.** An earlier revision asked the consumer to keep a
snapshot for enqueuing *and* to forward the reader's own object, which cannot both be
done with one value and bought nothing: §6 makes the writer observe whatever it is
handed, so forwarding the snapshot is exactly as safe as forwarding the original,
and it leaves one value for the stage to reason about instead of two that can
diverge. §2's obligation is unaffected — what it forbids is a *synthesised* reading,
and a faithful copy of the reader's is not one.

**Without that clause the batch seam reopens an attack the single-proposal stage
already closes.** `MemoryWriteStage.write` snapshots its proposal on its first
executed line and says why in place: flip `sensitivity` from `SECRET` to `PERSONAL`
while the ingest is in flight, and an unsnapshotted stage "rules on the secret
(correctly, `ASK_USER`) and then queues the credential" — ADR-0004 §3's "never in a
database", reached through the one filter written to prevent it. §6 makes the
*writer* observe the reading, which protects the writer's ruling; it does nothing for
the stage, because `MemoryIngestResult` carries no proposal and the obvious
implementation zips the results against `reading.proposals`. A model tampered past
`frozen=True` is inside this repository's threat model (ADR-0018 §3, ADR-0021 §4), so
the two snapshots are both load-bearing and neither substitutes for the other.

> **Normative.** This ADR decides **where and when** that queuing happens and never
> **what** is queued. ADR-0078 owns the latter unchanged — including §1's ruling
> that a `DataTier.SECRET` proposal is **never** queued, and the queue's own
> refused and suppressed answers. Nothing here obliges a question to be parked that
> ADR-0078 does not park, and nothing here is a warrant to park one it refuses.

This is ADR-0028's ruling carried across unchanged — a writer does not learn to
queue, and ADR-0078 §3 puts the two-store sequence on the coordinator that
legitimately holds both handles — but it is stated normatively here rather than left
to the implementing lane, because §3's single hold makes it a *concurrency* rule as
well as a layering one, and the two reasons fail differently.

**The lock-ordering ground, which is this ADR's own and is why the clause is
marked.** §3 obliges an implementation to hold its serialisation across the whole
call. A `DeferralStore` write is durable I/O to a **second** store, and performing it
inside that hold would put every memory write in the system behind a second store's
latency and, worse, establish a lock order — memory-then-deferrals — that any future
path acquiring them the other way would deadlock against. Nothing today acquires
them in either order, which is precisely when the ordering is cheap to forbid and
invisible to discover later. ADR-0074 §9's coordinator rule already puts the
sequence outside; this clause makes "outside" mean *outside the hold* and not merely
*in another object*.

> **Normative.** Where a reading's ingest raises part-way, an `ASK_USER` ruling
> already made for an **earlier** proposal of that reading is **not** parked, and no
> implementation or coordinator is obliged to park it. The question is recovered by
> re-proposal at the next reading of the same source, and nothing else is owed.

**That residue is real and it is new.** Today the stage parks each question inside
its per-proposal loop, so for a reading `[A, B]` where `A` defers and `B` raises,
`A`'s question is already queued; under §2's one call it is not, because the raise
returns no results to park from.

**ADR-0078 §3's obligation is not breached, because its trigger never fires.** That
section puts the enqueue on the stage that "observes `result.decision.kind is
ASK_USER` and enqueues" — the obligation is keyed on an **observed result**, and a
call that raises produces none for `A` that the stage can see. This is therefore not
a narrowing of §3 and no record is owed on it (§8); it is §3 applied to a call that
returned nothing to apply it to. The distinction matters and is worth stating
sharply, because the queue-cap analogy does *not* carry the argument on its own: a
cap refusal is a question the stage **offered** and the queue declined, which is a
different event from a question never offered.

**What makes the loss tolerable, rather than merely unobligated, is the recovery
path.** ADR-0078 §7's cap already establishes that an `ASK_USER` ruling is not a
promise the user will be asked — a refused admission is a question not asked yet —
so the corpus does not treat an unqueued ruling as data loss. And the reader seam
supplies the recovery directly: the source is re-read on a schedule, the proposal
returns, and it is ruled again, which is the same re-proposal model ADR-0106 §10's
case 8 relies on. The alternative — a typed batch failure carrying the completed
results so the coordinator could park them — is refused in Alternatives: it decides a
second contract inside this one, the ADR-0110 §10 mistake this ADR exists to repair.
Issue #814 records the interleaving so the implementing lane inherits it explicitly.

**Nothing else is lost by parking afterwards.** A question is a fact about a proposal
and about the ruling it drew, not about the store's live set, so it does not go stale
while the hold runs. ADR-0078 §5b's checks are computed from the frozen conflict ids
the ruling was made against, which the result carries.

**The second clause exists because the first one, read alone, obligated too much.**
An earlier draft said the question an `ASK_USER` "is parked", full stop, which an
implementer could satisfy only by queuing a secret-tier proposal — the one thing
ADR-0078 §1 forbids outright, because ADR-0004 §3 is unconditional that Tier 0
content lives "never in a database" and a durable queue is a file. Moving *where*
the parking happens must not silently re-decide *whether* it happens, and a clause
that restates a neighbouring ADR's rule in passing is how a rule acquires a second,
wrong copy. So this ADR names the seam and defers the content, which is also why
`IngestionReport.deferred` can go on counting rulings rather than claiming
questions reached the queue.

### 6. Both inputs are observed on entry, not across the awaits

> **Normative.** §1's member observes the `reading` it is handed **whole**, on its
> first executed lines and before its first `await`, and every later step reads only
> that observation and never the caller's object (`core/protocols.py`'s
> input-observation clause, ADR-0065). The obligation is over every field the
> operation reads, with no field exempt — `proposals`, `coverage` and `source`
> included.

One value arrives, so one copy discharges it — a further dividend of §1's cohesive
input, since separate arguments are separate things to remember to copy.

**The clause is stated over the whole value rather than as a list, and the reason is
that every list of it so far has been short.** Three fields are read after the awaits
and each one, left live, is its own failure. `proposals` is ADR-0065 applied
unchanged. `source` decides *which* records ADR-0110 §3 can reach at all, through its
first condition that `Provenance.attestation.reported_by` is the reading's source —
substitute it mid-call and the reconciliation retires another source's beliefs using
this reading's coverage and this reading's account of what is present, which is the
widest damage available here. And `coverage` is the value that **authorises a
retirement**: the coverage is read *after*
every ingest await, by the reconciliation, and it is the value that **authorises a
retirement** — it decides which records ADR-0110 §3 counts as covered. A model
tampered past `frozen=True` is inside this repository's threat model (ADR-0018 §3,
ADR-0021 §4), and widening a bounded `covers_until` to `None` mid-call is exactly the
edit that turns "states no position in the source's world" into "covered", closing
beliefs on the strength of a slice nobody exhausted. The implementation lane found
this under adversarial review rather than by reasoning, which is why it is contract
here rather than a note.

### 7. What the conformance suite owes

> **Normative.** The `MemoryWriterContract` gains cases pinning: §1's result
> cardinality and ordering against `reading.proposals`; §4's no-coverage arm; §6's
> observation of the reading across a mid-call mutation of its proposals, its
> coverage **and** its source; and ADR-0110 §4's suspension clause, that a reading in
> which any proposal stored nothing closes no window.

> **Normative.** §3's serialisation and §5's refusal to reach a `DeferralStore` are
> **not** conformance obligations of the shared suite. Each is pinned per
> implementation — §3 against that implementation's own serialisation mechanism, and
> §5 by its construction and its collaborators — together with a composition-root
> assertion that the operation reached is the one belonging to the store's single
> writer.

> **Normative.** §2 is pinned at the **consumer**, by a test over the ingestion
> stage: that the reading forwarded to §1's member **equals** the one the reader
> returned — not a reading the stage assembled, and not one carrying another read's
> proposals or coverage — that it is forwarded exactly once per read, and that this
> holds for a reading declaring a coverage as well as for one declaring none.

> **Normative.** §5's consumer snapshot is pinned at the consumer too, over an
> admission the queue **accepts**: that a proposal whose `sensitivity` is mutated
> from `DataTier.SECRET` during the awaited call is still **not** enqueued, and that
> a non-secret proposal whose payload is mutated during it **is** enqueued, carrying
> the payload as it stood when the call began. Dropping it is not an accepted
> outcome; the queue's own suppression and refusal answers are exercised separately,
> where they are the intended result.

**§2 is the one normative clause here that no writer-side test can reach, which is
why it gets its own.** §1's signature stops a caller pairing two readings, but
nothing stops a stage *synthesising* one — a covered reading carrying an empty
proposal tuple is well-formed, and a writer handed it does exactly what ADR-0110 §3
requires: finds nothing present, and closes every covered record the source
reported. Every other obligation in this section would still pass. The only place
that fabrication is visible is the seam between the reader and the writer, so that
is where the assertion goes.

> **Normative.** Each implementation's own tests also prove the **successful covered
> path**: that a covered reading closes the window of an eligible absent attested
> record, and that each of ADR-0110 §3's other conditions independently prevents a
> close. An implementation can satisfy every other obligation here and never close
> anything.

> **Normative.** Each implementation's own tests also pin §3's covered partial-ingest
> path: that a covered reading whose later proposal raises propagates the error,
> leaves the earlier proposals applied, and **closes no window**.

> **Normative.** §5's batch-failure residue is pinned at the consumer as well: a
> reading whose later proposal raises after an earlier one was ruled `ASK_USER`
> leaves **no** question enqueued for the earlier proposal, and the error
> propagates. Without it an implementation can quietly keep the old per-proposal
> behaviour, queue the earlier question, and pass everything else here — which would
> make §5's ruling a description of nothing.

> **Normative.** Each implementation's own tests also pin §3's refusal path: that an
> implementation which cannot serialise raises `MemoryStoreError` **for a reading
> that declares a coverage**, that **nothing was ingested and no window closed** when
> it does, that the underlying serialisation failure is **retained as that error's
> cause** where one exists, and that a reading declaring no coverage is ingested
> rather than refused.

The split is ADR-0103 §7's form, and the line is drawn by **observability through
the Protocol** rather than by importance. A shared suite drives a subject through its
public surface, and neither of these two is visible there. "No other writer ran in
between" is a property of the mechanism and of the wiring, and the wiring obligation
is the kind ADR-0028 §4 calls "a composition-root obligation no type can express".
"Nothing was enqueued" is worse than invisible: `MemoryWriter` neither accepts nor
exposes a `DeferralStore` — the contract's subject fixture supplies a `MemoryStore`
and a `MemoryPolicy` — so a conforming writer and one secretly holding a queue are
indistinguishable to it, and a suite case asserting the negative would pass
vacuously against both. A vacuous case is worse than an absent one, because it
reports coverage it does not have.

**An earlier draft put §5 in the shared suite**, having drawn the observability line
correctly for §3 one paragraph earlier and then not applied it. It is recorded
because the inconsistency is instructive: a *negative* obligation on a seam that
carries no handle to the thing being forbidden is never a black-box case, and the
same test — can the suite tell a conforming subject from a violating one? — decides
both clauses the same way.

### 8. What this records against earlier ADRs

ADR-0082 §1 puts the judgement in the later ADR's text: would "a reader holding only
the earlier ADR now act differently, or read one of its clauses more widely than it
now holds"? ADR-0070 §1 then decides whether the owed record is an amendment or a
supersession — amendment being for a change that "alters no decision".

**One record is owed, and this change writes it.**

**It is written now rather than at ratification, and the question is settled rather
than arguable.** ADR-0070 §1 permits "recording a supersession that has landed" and
adds that this "presupposes the superseding ADR *exists*". Read alone, the two
sentences invite the reading that a `Proposed` ADR has landed nothing and so may
record nothing — and that reading is wrong, has a number, and recurs:
**ADR-0082 §7 adjudicates it by name.** §1's condition "is that the superseding ADR
**exists**, not that it is ratified — the hazard §1 names is a `Status` line pointing
at nothing, and an atomic pair makes that unreachable", and §7 files the contrary
reading as "**#458 — the recurring misreading of ADR-0070 §1's 'a supersession that
has landed' clause**", "not a governance gap but a reviewer failure mode", restated
there because "it recurred on PR #478".

**It recurred here too, and the record is left standing rather than tidied away.** An
earlier revision of this ADR deferred the record to the ratifying change and wrote a
normative clause forbidding it now, on exactly #458's reasoning, after a review raised
it and the author checked ADR-0070 §1 alone without checking whether another ADR had
already ruled on how to read it. The corpus precedent was correct all along:
ADR-0111's `Status` carried its ADR-0114 supersession while ADR-0114 stood `Proposed`.
What makes it safe is §7's own mechanism — the pair is **atomic**, so the reference
never points at nothing.

**Deferring it would also have moved a decision into an edit exempt from review.** The
scope is decided here, in the change both required lenses read; a ratifying edit is
exempt from a separate review of *the edit itself* (`CONTRIBUTING.md` → "Trivial ADR
edits"), which is safe only because it records rather than decides. Putting the scope
there would have used the exemption to carry a judgement nobody reviewed.

**ADR-0110 §10, its buildability ruling and its `MemoryWriter` sentence.** §10 states
that the mechanism "is buildable on the `core` surface that exists plus §10's one
optional field, and it authorises no other Protocol change", and separately that
"**`MemoryWriter` is untouched, and no new member is authorised here.**" A reader
holding only ADR-0110 builds the reconciliation without a Protocol change — which is
what the implementation lane did, twice, and what review refused. Both limbs of
ADR-0082 §1's test are met.

**It is a supersession rather than an amendment, and narrowly scoped.** ADR-0070 §1's
test asks whether the change alters a decision. It does: §10's clause is a normative
ruling about what a lane may build and what surface is authorised, and this ADR
authorises the surface it withheld. That is not "reconciling an ADR with its own text
or with a fact that postdates it" — the fact does postdate it, but the disposition
still replaces a ruling rather than recording one. Note that §10's own last sentence
routes exactly this case to "its own ratified ADR", so the supersession is the
disposition ADR-0110 itself prescribed; what §10 did not anticipate is that the
prescription would fire.

**The scope is that ruling and nothing else, and everything else is relied on.**
`docs/adr/template.md` provides the instrument — "the parenthesis names exactly what
was replaced. The remainder stays accepted." Left standing, and load-bearing here:
ADR-0110 §1 (a window closes on a warranting event and never on a clock); §2 (the
coverage, its endpoint type and its invariant); §3 (the four conditions and the
containment rule); §4 (presence is the ingest's own answer, and the suspension
clause); §5 (the retirement's obligations and the atomic write set); **§5a's
serialisation prerequisite, which this ADR does not relax by one word but rather
supplies the seam that makes it satisfiable**; §5b's withholding of the
compare-and-swap and its token, which stays exactly where ADR-0046 §5 scoped it; §6;
§7; §8; and §9's deferrals. A supersession written any wider would record that the
prerequisite this contract exists to serve is dead.

**§10's `core/types.py` half is untouched and stays accepted.** The one optional
field on `SourceReading` is ratified, landed (#803), and is the value §1's member
carries; nothing here disturbs it.

**No record is owed on:**

- **ADR-0046 §5.** Its residual is scoped to "any two writers not sharing that
  lock", and this ADR makes the reconciliation share it rather than adding a second
  writer. #248 stays open on its own trigger and its own lane, and §5b's withholding
  of `IF_UNCHANGED` is relied on rather than narrowed. Using a mechanism as
  specified is not amending it.
- **ADR-0028 §§2, 4 and 7, and ADR-0078 §3.** §5 above carries ADR-0028's "a writer
  does not learn to queue" across a new member rather than around it, and adds a
  concurrency ground the layering rule did not have. ADR-0078 §3's coordinator keeps
  its job unchanged, and **its enqueue obligation is neither narrowed nor excepted**:
  §3 keys the enqueue on the stage observing `result.decision.kind is ASK_USER`, so
  where a call raises and returns no observable result the obligation does not
  attach — the same clause, applied to a call that produced nothing to apply it to.
  A reader holding only ADR-0078 still builds the same stage and still enqueues every
  observed non-secret `ASK_USER`. §5's residue and #814 record the consequence, which
  is a fact about when results exist rather than a change to what §3 requires of
  them. Neither clause is read more widely than it now holds.
- **ADR-0093 §1 and §4.** A reader still holds no store and proposes no absence; §1's
  "ingesting what it returns is `orchestration`'s" is satisfied — orchestration still
  decides when a reader runs, still calls it, and still drives the write path, which
  is now one call instead of a loop. Where the *loop* lives was never §1's subject.
- **ADR-0085 §1.** The promoted `AssistantEngine` surface is untouched: no scheduler
  job and no `Engine` operation is added, because ADR-0110 §3 keys on a reading and
  the only reading is the one the existing ingest job already produces.
- **ADR-0065's input-observation clause.** §6 applies it and names a second input it
  reaches; that is the clause doing its work.

### 9. What this ADR does not decide

- **The reconciliation's own rules.** ADR-0110 §§3–5 own them entirely and are not
  restated here. This ADR decides the seam the reconciliation is reached through and
  the guarantees that seam carries.
- **#248's compare-and-swap, and any concurrency token on `MemoryRecord`.** Untouched
  and still ADR-0046 §5's lane's. This ADR takes §5a's *other* disjunct, which is why
  it can.
- **Which sources declare a coverage**, and whether the canonical `FakeReader` grows
  a knob for one (#804). That is the reader lane's, with the source in hand — the
  discipline ADR-0110 §9 already applied.
- **Scheduler mechanics.** The chunking and durable-cursor lane's (#632, #710), and
  ADR-0111 and ADR-0114 own what has since been decided there. ADR-0110 §6's
  monotonicity property is what keeps this seam independent of it.
- **Whether other batch producers should reach memory in one call.** The observation
  stage and the learn leg propose one at a time and have no reading; §1 deliberately
  does not generalise, and a lane wanting a batch seam for them owes its own record.

### 10. The contract surface owed

**New surface in `core` — a breaking change (golden rule 5), implemented by a later
lane:**

- **`core/protocols.py`** gains **one method** on `MemoryWriter` (§1). `MemoryStore`
  is untouched: the closes still go through `write_atomic` and the enumeration
  through `list_beliefs`, exactly as ADR-0110 §10 says, and that half of §10 is
  correct and undisturbed.

  **`MemoryStore` has since grown a walk, and the reconciliation still does not use
  it.** ADR-0114 decided `walk_records` and `advance_walk` and their triad has
  landed, so a second enumeration now exists on the contract that did not when
  ADR-0110 was written. The reconciliation reads `list_beliefs` regardless, for two
  reasons that are not preferences. ADR-0110 §6 *rules* that enumeration and this
  ADR does not reopen it. And the walk exists to solve a problem the reconciliation
  does not have: a durable cursor buys resumption across a restart for a job whose
  chunks must each be accounted for, whereas ADR-0110 §6 rules that "each close is
  justified by one record and one reading and by nothing else", so a reconciliation
  that examines part of the live set "closes **fewer** windows and never a different
  one" — the worst an interrupted one produces is a belief that stays live one cycle
  longer, which the next reading closes. A cursor would add durable state to buy a
  guarantee §6 already gives for free, and it would make one reading's closes depend
  on an earlier reading's progress, which is exactly the coupling §6's monotonicity
  removes.
- **`core/types.py`** gains **nothing**. `SourceReading`, `ReadCoverage`,
  `MemoryUpdateProposal` and `MemoryIngestResult` all exist and all carry what §1
  exchanges.

> **Normative.** The implementation lane lands the **triad** in one change (ADR-0015
> §5, `CONTRIBUTING.md` → "Adding a Protocol: land the triad together"): the
> Protocol method, the `MemoryWriterContract` cases §7 enumerates, and the canonical
> fake in `ai_assistant.testing` gaining the member. It may not defer any of the
> three.

**What is genuinely the lane's** is how each implementation provides §3's
serialisation — a lock, a queue, a single-threaded executor — and everything below
the seam: how candidates are selected, how the batch is assembled, how the walk is
paged. What is *not* the lane's, because two lanes could there make incompatible
choices and both claim compliance (ADR-0103 §9's test), is: §1's **whole signature**,
including the member's name, its cohesive input and its return type; §1's cardinality
and ordering; §2's one-call rule; §3's single serialised sequence and its refusal;
§4's no-coverage arm; §5's queue exclusion; §6's whole-value observation; and §7's
split between the suite's obligations and the per-implementation ones.

## Consequences

- **ADR-0110 §3's mechanism becomes buildable**, and buildable with its §5a
  prerequisite met by construction rather than by a composition argument that
  nothing checks. That is the whole purpose of this record.
- **`MemoryWriter` grows for the first time since ADR-0028**, and the cost is
  honest: every implementation owes the member, and the canonical fake owes it in
  the same change. There are two implementations today — the ingestor and the
  canonical fake — which is the cheapest moment this could have happened.
- **One more thing is stated normatively that was previously a habit**: that durable
  work on a second store does not happen inside a memory writer's hold (§5). That
  constrains implementations that do not exist yet, which is when a lock order is
  cheap to fix.
- **The implementation lane's work is already written and reviewed.** The
  reconciliation, its wiring, its composition and its tests exist on
  `memory/demotion-reconciliation-full` and carry an adversarial APPROVE; what they
  lack is this contract. Re-landing is the triad plus that branch, not new design.
- **This makes one thing harder, deliberately.** A consumer may no longer reach the
  reconciliation piecemeal (§2), so a future producer that wants absence-demotion
  must have a whole reading to offer. That is the constraint that makes the
  guarantee real, and it falls on exactly the callers who want the feature.
- **Revisit if** #248's compare-and-swap lands and makes §3's single hold
  unnecessary for this consumer (§3's obligation would then have a second way to be
  satisfied, which is already how ADR-0110 §5a is written), or if a second batch
  producer appears and §9's refusal to generalise starts costing more than it saves.

## Alternatives considered

- **Keep the per-proposal seam and reconcile separately, relying on the
  composition.** Rejected in Context: it is what round 1 built and review refused.
  The argument for it — that this composition has one caller of the ingest job and
  the scheduler cannot overlap it (ADR-0083 §7) — is true and insufficient: a
  request-path write can still fold onto an attested record in the gap, and a
  guarantee that depends on which callers happen to exist is one nothing rechecks
  when a caller is added.
- **Type the injected bound method as a callback Protocol local to
  `orchestration`.** Rejected in Context, on architecture review's ground: it moves
  where the annotation lives without changing what the dependency is, and golden
  rule 1 is about the dependency. It would also have been the more damaging
  outcome, because it *looks* compliant — `lint-imports` passes, no `core` file is
  touched, and the new coupling is discoverable only by reading the two files
  together.
- **Design the compare-and-swap here** so that no writer member is needed.
  Rejected: ADR-0110 §5b withholds it in terms, it needs a concurrency token on
  `MemoryRecord` that ADR-0046 §5 scoped to its own lane, and it would be a second
  lane's contract decided inside this one — the same trade ADR-0110 refused, still
  refused.
- **Put the reconciliation on `MemoryStore` instead**, as a method beside
  `list_beliefs` and `write_atomic`. Rejected: the store does not hold the policy,
  the conflict detection or the lock that the *ingest* half runs under, so the
  sequence would still span two seams and serialise neither. It would also put
  ADR-0110 §3's rules inside the store, where ADR-0028's propose/dispose/persist
  split says they do not belong.
- **Return a typed batch failure carrying the completed results**, so a coordinator
  could park an earlier proposal's `ASK_USER` before propagating a later proposal's
  raise. Rejected in §5, on this ADR's own governing constraint rather than on the
  merits of the shape: it is a second contract — a new failure type and its
  payload — decided inside this one, under review, which is exactly the move ADR-0110
  §10 made and this ADR exists to repair. The loss it would prevent is admissible on
  ADR-0078 §7's own terms (the cap refuses rather than evicting, so an unparked
  question is a question not yet asked) and is recovered by re-proposal at the next
  reading. A lane that later finds the residue costs more than it saves owes its own
  ADR for the failure type, which is the right place for it.
- **Have §1's member park the deferred questions itself**, since it already has the
  results. Rejected in §5: it needs a `DeferralStore` on the writer, which ADR-0028
  refused and ADR-0078 §3 re-refused, and under §3's hold it would additionally
  fix a lock order across two stores for no benefit.
- **Take the proposals, the `source` and the coverage as three arguments**, rather
  than the `SourceReading` whole. Rejected in §1, after an earlier draft did exactly
  this and left the member's spelling to the lane besides. Architecture review named
  the defect and it is the decisive one: three arguments admit a call pairing one
  reading's proposals with another reading's source and coverage, which type-checks,
  reads naturally, and makes ADR-0110 §3 evaluate its conditions against a slice
  those proposals never came from — closing records on a coverage nobody exhausted.
  §2's normative one-call rule forbids it and a rule is not a type. The argument for
  the split form was that the writer has no use for `read_at`, `as_of` or `facet`;
  that is true and is worth three unused fields, because a writer ignoring a field
  is ordinary and a caller silently crossing two readings is not.
- **Add a separate narrow Protocol** — a `ReadingIngestor` in `core/protocols.py`
  carrying this one operation — rather than widening `MemoryWriter`. Rejected, and
  the ground is §3 rather than a documented preference between the two moves: neither
  `CLAUDE.md` nor `CONTRIBUTING.md` states one, and `CONTRIBUTING.md` → "Adding a
  Protocol" treats a Protocol *change* as a first-class act measured against the same
  triad.

  §3 obliges the reading-level operation to share its serialisation with **every
  other writer on the same store**, and the writer it must share with is the one
  behind `MemoryWriter.ingest`. On one Protocol that is true by construction: one
  object implements both members, so "the same lock" needs no wiring to be right. On
  two Protocols it becomes a composition-root obligation that "these two seams are
  the same object" — unexpressible in the type system, exactly the class ADR-0028 §4
  names, and precisely the failure that produced the first blocker on #803, where a
  correctly-typed second seam served the operation while sharing nothing. A narrower
  Protocol would buy a smaller surface for each implementation at the cost of making
  this ADR's central guarantee un-typeable, which is the wrong trade for the one
  clause the ADR exists to secure.

  The cost of widening is real and small: two implementations own the member today —
  `MemoryIngestor` and the canonical fake — and the fake owes it in the same triad.
- **Leave the member's name and signature to the implementing lane**, as ADR-0110 §2
  left its field's spelling. Rejected in §1: §2 was pinning the domain of a *field on
  a value object* and calling the name rename-class, which it is; a Protocol member
  is the contract surface itself, golden rule 5 exists to make that surface visible
  before anything builds on it, and ADR-0114 — the nearest precedent, one ADR ago —
  pinned `walk_records` and `advance_walk` exactly rather than describing their
  shape.
- **Return only the closed-window count, or only the results, rather than one result
  per proposal.** Rejected in §1: ADR-0110 §4 needs every `record_id` to compute
  presence and needs to know whether *any* proposal stored nothing, and the caller
  needs the per-proposal pairing to park questions. A narrower return would move
  those computations behind the seam and make the suspension clause unobservable.
- **Generalise the member to any batch of proposals**, so the observation stage and
  the learn leg could use it too. Rejected in §9: neither has a reading, a `source`
  or a coverage to pass, so they would pass `None` for the only argument that makes
  the operation different from a loop over `ingest` — surface with no consumer, and
  a second way to do what `ingest` already does.
