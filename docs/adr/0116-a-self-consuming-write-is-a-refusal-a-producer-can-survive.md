# 116. A self-consuming write is a refusal a producer can survive, not a fault that stops it

- Status: Proposed
- Date: 2026-08-07
- **Durability clause.** Every reference below to ADR-NNNN is to its text as
  merged on 2026-08-07, not to its status on any later day. Where a later ADR
  changes one of them, this ADR is read against the text quoted here and the
  later ADR's own record says what moved.
- **This is a contract change of the semantics-only kind, plus one error class.**
  `MemoryWriter.ingest` keeps its signature and refuses exactly what it refuses
  today; what changes is the **class** one of its refusals carries, and therefore
  what a caller may do about it. `core/errors.py` gains one
  `MemoryStoreError` subclass. **No Protocol is added and `core/types.py` is
  untouched**, so golden rule 5 is not triggered by the class itself — ADR-0083 §6
  rules that "a new `AssistantError` subclass is neither a Protocol nor a
  `core/types.py` model". It *is* triggered by the changed meaning of a contract
  method, which is the case `CONTRIBUTING.md` names when "a Protocol's meaning
  changes without its shape", so this ADR ships as its own docs-only PR, is
  reviewed while `Proposed`, and is flipped to `Accepted` on merge (ADR-0015 §5).
  **No implementation lands with it.**
- **This ADR partially supersedes
  [ADR-0081](0081-no-write-consumes-the-evidence-its-own-proposal-cites.md), in one
  narrow scope**: §3's ruling that the refusal earns no new error class, §9's
  matching declined bullet, and §3's characterisation of the refusal as *always* a
  producer fault insofar as that characterisation grounds the ruling. **§1's
  refusal itself is untouched, relied on, and not weakened by a single clause
  below**, as are §§1a, 1b, 2, 4–7, §8's deferrals and the rest of §9. §7 applies
  ADR-0082 §1's and ADR-0070 §1's tests separately and states what is *not* owed.
- **What forced it.** ADR-0081 §Context established that "**Nothing reachable
  produces the shape today**", and §9 declined a subclass because there is "**no
  caller with a second branch**". Both were true when written and neither is now:
  leg 7's consolidator reaches the refusal while following every producer rule the
  corpus states, and it is precisely a caller with a second branch. Refs #472,
  #807, #809.

## Context

### ADR-0081 §1 is right, and nothing here argues with it

§1 refuses a ruling that would *install* the proposal at an id that same proposal
cites, because the result is "a belief that ends up standing as its own warrant".
Its reasoning is intact and this ADR relies on all of it: the predicate reads
nothing from the store, it cannot be raced, and the residue it prevents is worse
than the one ADR-0077 §6 already renders honestly — a citation that **resolves to
the wrong record**, which feeds §6's honesty mechanism a false input rather than
merely bypassing it.

What is at issue is not whether the write is refused. It is what the refusal
*means about the caller*, and therefore what the caller is permitted to do next.

### The producer ADR-0081 could not have had in front of it

§Context surveyed what could reach the shape and found nothing:

> Both shipped producers mint record ids from an injected `id_factory` … and the
> observer's evidence is a label→episode-id map built from the batch it actually
> read (ADR-0077 §5), never a value the model or the record supplies — so
> `proposed.id ∈ evidence` is unconstructible from either.

That survey is correct and it is correct about `proposed.id`. The arm it could not
weigh is `REINFORCE`, whose destination is **`decision.target_id`** — a value
neither the producer nor the writer chooses. The policy picks it, by conflict
detection over the proposal's own content.

Leg 7's consolidator makes that arm live, and it does so **without breaking a
single producer rule**:

- it cites the records it consolidated, by the same label→id mapping ADR-0077 §5
  obliges, so its citations are exactly the input set it read;
- it generalises over that set, which is what a consolidation *is* — "many
  episodes distilled into few durable beliefs" (`docs/roadmap.md`, leg 7);
- the generalisation therefore resembles its inputs, because it was derived from
  them, so `DefaultMemoryPolicy`'s conflict detection can legitimately surface one
  of the cited records and rule `REINFORCE` onto it;
- and then `target_id ∈ evidence`, and §1 refuses.

Every step is the system working as designed. There is no hand-built proposal, no
producer ignoring the mapping rule, no pathological id factory — the three sources
§Context named. **A generalising producer draws its fold target from the same
population as its citations, and that is a property of generalising, not a bug.**

### Why the refusal being a bare `MemoryStoreError` is now the problem

ADR-0081 §3 rules the refusal a plain `MemoryStoreError` and gives its ground:

> It is therefore **never** a race and **always** a producer fault. There is no
> second branch for a caller to take, and a subclass with one caller and one
> branch is surface with no consumer.

The "never a race" half stays true — every input is fixed and private inside the
ingestor's lock. The "always a producer fault" half is what the consolidator
falsifies, and the consequence lands on the scheduler.

A scheduled walk is unattended. ADR-0111 §6 rules that "a run that halts or raises
is retried at its next due instant" with **no backoff and no durable failure
count**, and §5 halts a run at the first chunk it cannot record as done. So a
consolidation whose proposal trips §1 raises out of the write path, the run ends
without recording its chunk, the cursor stays where it was — and the next run reads
the same chunk, asks the same model, gets the same generalisation, and fails
identically. **Forever.** That is the state ADR-0111 §7 names as the thing to
avoid: "a permanent, opaque failure instead of a slow success".

The caller cannot distinguish it. ADR-0111 §9 is explicit that a refusal and a
fault must be different records and that "the distinction is drawn from the
exception's class, **never from its message text**" — quoting ADR-0083 §6, where
the corpus already paid for the alternative. A bare `MemoryStoreError` here is
indistinguishable from a broken disk, so the only ways to survive it are to match
on a message (forbidden) or to catch every store error (which would swallow the
broken disk).

### The three exits that are closed, so the fourth is not reached by elimination

Each was considered and each is refused by ratified text rather than by taste.

**A marker so consolidations are never re-selected** — a field on `Provenance`, or
a `MemorySource` member, letting a consolidator skip its own output. It is
`core/types.py` surface, so golden rule 5 puts an ADR ahead of it; but the
decisive objection is that **it does not fix the defect**. The refusal does not
require the input to be a consolidation. Consolidating fifty ordinary observed
beliefs can produce a generalisation the policy folds onto one of them, and the
marker is silent about that. It addresses the *second-order* case (#809) and
leaves the first-order one exactly where it was.

**Excluding derived beliefs from a consolidator's input set.** Refused by
ADR-0106 §10's third clause, which obliges the consolidation lane to ship "a test
whose only tainted input is a `DERIVED` record carrying `derived_from_external`,
asserting the proposal reaches the gate tainted" — and names what a narrower
selection would cost: "A selection step that computes the marker from the input's
*band* alone satisfies the clause above and fails this one." A producer that
cannot select a derived belief cannot satisfy §10, and §10 exists because
inheriting taint past one hop is what makes the marker mean anything.

**Predicting the fold at the producer.** The producer would have to know which
record the policy will pick as a conflict target, which means running conflict
detection itself — re-implementing the gate outside it, with its own thresholds,
which golden rule 1 and ADR-0081 §3's own "a ruling is the policy's to make"
(ADR-0005 §3) both refuse.

## Decision

Marked under ADR-0089: every obligation this ADR imposes is a marked clause, and
unmarked text supplies none.

### 1. The refusal stands exactly as ADR-0081 §1 states it

> **Normative.** Nothing in this ADR weakens, narrows or adds a condition to
> ADR-0081 §1. A write that installs the proposal at an id the proposal cites is
> refused, nothing is written, and no caller may cause such a write to happen by
> catching, retrying, or repairing anything this ADR makes catchable.

The hazard §1 names is unchanged and so is its handling. What follows is about the
**class** the refusal carries and what a caller may do having caught it — never
about whether the write is refused.

### 2. The refusal carries its own class

> **Normative.** The refusal ADR-0081 §1 states is raised as a distinct
> `MemoryStoreError` subclass declared in `core/errors.py`, and every
> `MemoryWriter` implementation raises that class for that refusal and no other.
> It is documented on `MemoryWriter.ingest` and asserted in the shared
> `MemoryWriterContract`, so a caller can distinguish it on **every**
> implementation rather than on the one it happens to hold.

The shape, stated as ADR-0072 §2 stated `band_of`'s rather than left to the lane;
the spelling is the implementing lane's:

```python
class SelfConsumingWriteError(MemoryStoreError):
    """A ruling would install the proposal at an id the proposal cites."""
```

**A subclass rather than a flag on the existing error**, because the corpus has
already ruled how this distinction is drawn: ADR-0111 §9's "the distinction is
drawn from the exception's class, never from its message text", resting on
ADR-0083 §6's record of what the alternative cost — a refusal that "is a
`MemoryStoreError` — a subsystem error from below the disk line — so the entry
point cannot tell 'this deployment cannot serve this store' from 'this disk is
broken' without matching on a message string".

**It remains a `MemoryStoreError`**, so every existing `except MemoryStoreError`
still catches it and no caller that does not care is disturbed. ADR-0081 §3's
"what every other writer-boundary refusal raises" stays true of it.

> **Normative.** The clause above binds **every** `MemoryWriter` member that
> installs a proposal, not only `ingest`. A member added later that performs an
> installing write raises this class for this refusal on the same terms.

**Stated over the members rather than over one method's name**, because the writer
contract has grown a second install path while this ADR was drafted:
[ADR-0115](0115-the-writer-contract-carries-the-reading.md) §1 adds
`ingest_reading`, which ingests a whole reading's proposals and is subject to
ADR-0081 §1 exactly as `ingest` is. A clause naming `ingest` alone would have left
the newer path raising a bare `MemoryStoreError` for the same refusal, which is the
backend divergence §2 exists to close arriving through a member instead of an
implementation.

**ADR-0111 §9 anticipated this list growing and left it open**: "Which classes are
refusals is the implementing lane's list, and it is short today: `SourceNotGrantedError`
is the one ADR-0097 §5 names, and a queue-at-cap disposition under ADR-0106 §6 is
the next." This is the third, arriving by the route §9 described.

### 3. Why ADR-0081 §3's ground no longer holds, stated as the supersession it is

> **Normative.** ADR-0081 §3's ruling that this refusal earns no new error class,
> and §9's declined bullet stating the same, are replaced. The reasoning §3 gives
> for it is assessed rather than overruled: its "never a race" half stands and is
> relied on; its "always a producer fault" half is **bounded** to a producer that
> chose the colliding id, and does not reach a producer whose fold target the
> policy chose.

§3's ground was a measurement of the consumers that existed — "no caller with a
second branch". A scheduled bulk producer is that caller and its two branches are
distinct in what they do, not merely in what they log:

- **this proposal is inadmissible**: count it, do not write it, do not re-propose
  it, and carry on with the rest of the chunk;
- **the store is broken**: stop, leave the chunk unrecorded, let the run fail.

Collapsing those two costs the first branch entirely, which is the permanent stall
§Context describes.

**One caller, not two, and the count is stated rather than inflated.** ADR-0115's
`ingest_reading` is a second *install path* but not a second consumer of this
class: a reader's proposals cite nothing — `CalendarReader` builds a `Provenance`
with an `Attestation` and no `evidence` — and ADR-0081 §1b rules that "a record
citing nothing satisfies it trivially". So the reconciliation cannot reach this
refusal today, and this ADR does not pretend otherwise.

**One is enough, because §3's ground was not a count.** §9 declined the subclass
because there was **no** caller with a second branch, not because there were fewer
than some threshold; a single caller that cannot function without the distinction
falsifies that ground completely. ADR-0028 §7's promotion discipline — which does
wait for a third consumer — governs hoisting a *generic seam*, and an error class
that one caller must distinguish to avoid a permanent stall is not that: the
alternative is not "wait and see", it is "the job cannot ship".

**A producer fault is still a producer fault.** A hand-built proposal citing its
own id is exactly what ADR-0081 §Context describes and is still a bug; nothing
here makes it less so. What changes is that "the writer refused this write" and
"the producer is broken" stop being the same statement — which they ceased to be
the moment a conforming producer could reach the refusal.

### 4. What a caller may do with it, and what it may not

> **Normative.** A caller that catches this class treats it as a ruling on **one
> proposal**: it may continue with other proposals and may record the chunk it was
> processing as done. It may not fabricate a `MemoryDecision`, may not report the
> proposal as accepted, deferred or rejected by any policy, and may not re-submit
> the same proposal unchanged in the same run.

**No fabricated ruling**, which is ADR-0081 §3's and ADR-0005 §3's rule and is not
touched: "a ruling is the policy's to make and a writer inventing one puts a
decision nobody made into the ingest result". A caller inventing one is the same
move one layer out. The proposal was refused *before* any ruling was applied, so
there is no ruling to report and the caller says so in its own counts.

> **Normative.** A caller that catches this class counts the refused proposal and
> surfaces that count in whatever it reports about its run. A refusal absorbed
> without a number is indistinguishable from a producer that proposed nothing.

That is ADR-0077 §4's discipline — entries "discarded and *counted* rather than
repaired, invented, or re-prompted for" — applied to a refusal instead of a
malformed entry, and ADR-0022 §4a's rule against a report that looks healthy while
nothing happened.

> **Normative.** No caller repairs the proposal to get past this refusal: not by
> dropping the offending id from the evidence tuple, not by re-minting the
> proposal's own id, and not by re-asking the model for a different generalisation
> over the same inputs inside the same run.

The first two are ADR-0081 §9's declined "repairing the proposal instead of
refusing it", restated at the caller because that is where the temptation now
lives: "evidence *removed* to satisfy a rule leaves a warrant nobody assessed".
The third is new and belongs here — a retry inside the run is a second model call
to launder the same inputs past a refusal, which spends egress to defeat a floor.

### 5. A scheduled walk does not halt on it

> **Normative.** This refusal is a per-item disposition and never a chunk that
> could not be recorded as done. A walking job that catches it advances its cursor
> over the chunk exactly as it would have, and ADR-0111 §5's halt is not engaged.

ADR-0111 §5 states its own rule over the disposition rather than the reason, and
names this case on the other side: "A per-item ruling that is a *normal outcome*
of processing — a proposal the gate rejects, a turn ADR-0074 §5 says is 'skipped,
not an error' — is not a chunk that failed to be recorded, and does not halt
anything." A refused self-consuming write is now such an outcome. Left as a fault
it would halt every run at the same chunk forever, which is §5 producing the
opposite of what it was written for.

**This is the whole of what the stall needed.** With the refusal catchable and the
run continuing, the chunk is recorded, the cursor advances, and the material that
produced the refusal is behind the walk — so the next run reads new records rather
than re-deriving the same refusal from the same inputs.

### 6. What this ADR does not decide

> **Normative.** No marker distinguishing a consolidation from any other derived
> belief is created, on `Provenance`, on `MemorySource`, or anywhere else. A lane
> wanting one is proposing `core/types.py` surface and owes its own ADR.

> **Normative.** Nothing here narrows what a consolidator may select. A `DERIVED`
> record carrying `derived_from_external` stays selectable as consolidation input,
> so ADR-0106 §10's third clause remains satisfiable exactly as written.

That second clause is stated rather than left implicit because the marker this ADR
refuses is the mechanism a lane would reach for to *implement* an exclusion, and an
exclusion is what breaks §10's third clause. Recording the pair keeps a later
reader from taking the refusal of the marker as licence to narrow selection some
other way.

- **Whether a second-order consolidation is wanted at all.** #809 asks whether a
  belief generalised over earlier consolidations is useful, and at what depth it
  stops being. This ADR does not answer it: with §2 in hand the case is no longer
  a stall, so what remains is a quality question, and ADR-0106 §12 files this job's
  quality parameters with **leg 8's measurement**. A run excluding its own output
  within one run is an implementation's optimisation, not an obligation this ADR
  imposes.
- **The deferral queue's cap value, the chunk size, the run budget** — ADR-0106
  §12 and ADR-0111 §4, untouched.
- **The general "no stored record cites itself" invariant and how such a record
  presents.** ADR-0081 §8's second deferred item, still owned by the
  belief-presentation lane, still unfired.
- **Anything about `MemoryStore.add`'s upsert.** ADR-0081 §8's first deferred item
  was discharged by ADR-0108 §4 and is not reopened.

### 7. Records under ADR-0082 §1 and ADR-0070 §1

ADR-0082 §1 puts the judgement in the later ADR's text — whether "a reader holding
only the earlier ADR [would] now act differently, or read one of its clauses more
widely than it now holds". ADR-0070 §1 then decides whether the record is an
amendment or a supersession, amendment being the disposition where the change
"alters no decision".

**One record is owed, and this change writes it.**

**ADR-0081 §3, and §9's matching bullet.** §3 *decided* that the refusal earns no
new error class, and §9 lists "**A new `MemoryStoreError` subclass** for this
refusal" among what it explicitly declined. §2 above adds one. A reader holding
only ADR-0081 would build a `MemoryWriter` raising a bare `MemoryStoreError` and
would refuse a lane asking for the subclass — which is acting differently, on both
limbs. ADR-0070 §1's test then makes it a **supersession and not an amendment**:
what changes is the decision itself, not a reconciliation of ADR-0081 with its own
text. It is **partial**, and the scope is one ruling in §3 with its echo in §9;
`docs/adr/template.md` supplies the instrument — "the parenthesis names exactly
what was replaced. The remainder stays accepted."

ADR-0081's `Status` already leads with a partial-supersession token for ADR-0108,
so this ADR's pair is **added on the same line** without dropping the first, in the
form the template states, and the dated note carries the reasoning.

**No record is owed on:**

- **ADR-0081 §1, §1a, §1b, §2, §4.** The refusal, its quantification over the
  proposal's evidence, its band-wide scope, its placement between the ruling and
  the write dispatch, and `SUPERSEDE`'s re-mint are each relied on exactly as
  written. §1 above says so in a clause rather than leaving it to be inferred,
  because a reader could otherwise take "the refusal earns a class" as softening
  the refusal.
- **ADR-0081 §5, §6, §7.** The ADR-0077 amendment, the conformance clause and its
  qualifications are untouched; the suite gains a case about the refusal's *class*
  and loses none about its *occurrence*.
- **ADR-0081 §8.** Both deferrals stand: the first was discharged by ADR-0108 §4
  and this ADR does not reach it, the second is the belief-presentation lane's and
  is neither fired nor reassigned here. ADR-0083 §15's rule covers the shape —
  "Examining a revisit condition and finding it unmet changes nothing."
- **ADR-0077 §5 and §6.** Relied on as written. §5's mapping rule is what the
  consolidator *follows*, which is the whole of why the refusal it meets is not a
  producer bug, and §6's tombstone is keyed on non-resolution and never fires on
  §1's case — unchanged, as ADR-0081 §5 established.
- **ADR-0111 §5, §6, §9.** §5 is applied and found to exclude this case by its own
  words; §6's no-backoff ruling is relied on as the reason a fault here is
  permanent rather than transient; §9's class-not-message rule is taken as written
  and its open list is extended by the route §9 itself describes. Supplying an
  entry a clause invited is the stacked addition ADR-0083 §15 names, not an
  amendment.
- **ADR-0106 §3, §5, §6, §10, §12.** Every one is relied on unchanged. §6 explicitly
  requires a consolidator to reach the store through the orchestration write stage,
  which is the path this refusal travels; §10's third clause is preserved by §6
  above rather than narrowed; §12's assignment of quality parameters to leg 8 is
  quoted and left alone.
- **ADR-0005 §3 and ADR-0081 §9's fabricated-`REJECT` bullet.** §4 above restates
  the prohibition at the caller and takes nothing from it.
- **ADR-0115 §1 and §3.** §1's "No other `MemoryWriter` or `MemoryStore` member is
  added, widened or changed **by this ADR**" is a classification of ADR-0115's own
  change, which ADR-0089 §1 names as the paradigm of what is not normative; it is
  not a prohibition on a later ADR, and §2 above changes no member's shape in any
  case. §3 pins *its* refusal to a plain `MemoryStoreError` on the ground that the
  orchestration stage and the CLI "handle `MemoryStoreError` as the recoverable
  memory fault" — undisturbed, because the class §2 adds **is** a
  `MemoryStoreError` and every handler that catches the base still catches it.
  `ingest_reading` gains no obligation it did not already carry: ADR-0081 §1 bound
  it from the moment it was decided, and §2 above only fixes which class that
  binding raises.
- **ADR-0083 §6 and ADR-0108 §4.** §6's classification of an `AssistantError`
  subclass is applied as written; ADR-0108 §4's cross-kind refusal is a different
  rule at a different door and is neither widened nor narrowed.

**The record is well-formed from the moment it is written**, on ADR-0083 §15's
ground: "The existence condition is that the naming ADR ships in the same change,
not that it has ratified." The note names ADR-0116 and ships in this change; if
this ADR does not land, neither does the note.

### 8. What the implementing lane owes

> **Normative.** The lane landing the class ships it with the `MemoryWriter`
> contract in one change: the subclass in `core/errors.py`, the raise site in every
> `MemoryWriter` implementation including the canonical `FakeMemoryWriter`, the
> `Raises` clause on `MemoryWriter.ingest`, and a `MemoryWriterContract` case
> asserting the class over every implementation. A fake raising the base class
> where a real writer raises the subclass would certify a consumer the real writer
> breaks (ADR-0026 §7).

> **Normative.** That suite case asserts the class on a `REINFORCE` whose
> `target_id` the proposal cites, not only on an `ACCEPT` at a cited
> `proposed.id`. The `REINFORCE` arm is the one a conforming producer reaches, and
> a case exercising only the `ACCEPT` arm passes an implementation that raises the
> subclass on the arm nobody hits and the base class on the arm everybody does.

> **Normative.** The lane landing a consolidator ships a test that a chunk whose
> generalisation is refused under this rule leaves the run **continuing** — the
> chunk recorded as done, the walk advanced, the refusal counted in the run's
> report — and a second test that a run over the same store afterwards does not
> re-derive the same refusal. A test that stops at the raised class does not
> satisfy this clause: what is under test is that the stall is gone.

Each names the case that can fail. The `REINFORCE` clause is there because that
arm is invisible to a suite built from ADR-0081 §Context's worked example, which
is an `ACCEPT`. The continuation clause is there because catching an exception and
then halting anyway satisfies every other clause here and leaves the job exactly as
stuck as it was.

## Consequences

**The consolidation job becomes buildable, and it becomes buildable without new
`core` surface.** It was blocked on a refusal it could reach by behaving
correctly, with no way to tell that refusal from a broken store. One error class
and one caller rule unblock it, where a marker would have cost a `core/types.py`
field, an ADR of its own, a migration question for records written before it, and
would not have fixed the first-order case.

**`MemoryWriter.ingest` grows a documented class and no new refusal.** Every
implementation pays a subclass and a suite case; no caller that does not care
changes, because the subclass is still a `MemoryStoreError`. That is the smallest
change that makes the distinction ADR-0111 §9 requires drawable.

**The refusal stops being evidence of a bug, and that is a real loss worth
naming.** Under ADR-0081 §3 a `MemoryStoreError` from this site meant "some
producer is broken", and an operator could act on it. Now it means either that or
"a generalising producer landed on one of its own citations", and only the caller's
count distinguishes them. §4's counting clause is what keeps the first case
visible; without it the change would trade a stall for a silence, which is the
worse of the two.

**A conforming producer can now be refused repeatedly and legitimately.** A
consolidator over a store whose material keeps generalising onto itself will keep
producing refused proposals, spending a model call each time and writing nothing.
That is not a stall — the walk advances — but it is waste, and it is the shape leg
8's measurement should look at when it sets this job's parameters (ADR-0106 §12).

**What would trigger revisiting this.** A second producer reaching §1's refusal by
a route that is *not* a policy-chosen fold target, which would mean the bound §3
puts on "always a producer fault" is narrower still. A measurement showing refused
consolidations are common enough that the model call spent on them dominates the
job's cost, which would reopen whether a consolidator should select records it has
already generalised over — the question #809 holds. Or a lane that genuinely needs
to distinguish a consolidation from any other derived belief for a reason this ADR
did not weigh, which reopens the marker refused in §6.

## Alternatives considered

**A marker on `Provenance` or `MemorySource` so a consolidator skips its own
output.** The route the blocking lane reached for first. Rejected in §Context and
§6: it is `core/types.py` surface, it needs its own ADR, it raises a backfill
question for every derived record written before it — and, decisively, **it does
not fix the defect**, because the refusal does not require the input to be a
consolidation. It addresses #809's second-order case only.

**Excluding derived beliefs from consolidation input.** Cheapest of all, needs no
contract change. Refused by ADR-0106 §10's third clause, which obliges a test whose
only tainted input is a `DERIVED` record and names what a narrower selection costs:
taint would stop inheriting past a single hop, which is the property §10 exists to
pin.

**Predicting the fold at the producer and not citing what it might land on.** It
would prevent the proposal rather than refusing it, which sounds better. Rejected
because it requires running conflict detection outside the gate — golden rule 1's
seam and ADR-0005 §3's "a ruling is the policy's to make" — with the producer's own
thresholds, which is a second copy of the policy that will disagree with the first.

**Letting the caller match on the message.** Free, and forbidden in terms by
ADR-0111 §9 and by ADR-0083 §6, which records what the corpus already paid to learn
it: the scheduler's one permitted string match is bounded by "the engine's own
message constant, so the two sides cannot drift", and "a second string match, over
messages no constant pins, is not that".

**Catching every `MemoryStoreError` at the consolidation stage.** No contract
change at all. Rejected because it swallows the broken disk with the refusal, which
is the failure ADR-0083 §6 spent a class to fix, and because it would make a store
that has genuinely failed look like a run that consolidated nothing.

**Having the writer fabricate a `REJECT` instead of raising.** It would need no
class and no caller rule. Refused by ADR-0005 §3 and restated by ADR-0081 §3 and
§9: "a writer inventing one puts a decision nobody made into the ingest result".
The gate never saw this proposal, so there is no ruling to report.

**Leaving it, and shipping the consolidation job disabled.** The job ships disabled
anyway, so nothing would run into the stall until an operator armed it. Rejected
because it puts a known permanent failure into `main` behind a default flag's
protection, and because ADR-0111 §11's "enabling any job the scheduler ships
disabled is an implementation lane's act" would hand a lane a switch nobody can
safely flip — the precise state ADR-0083 §7 refuses when it argues a disabled
default rather than assuming one.
