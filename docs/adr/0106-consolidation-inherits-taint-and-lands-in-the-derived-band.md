# 106. Consolidation inherits taint, lands in the derived band, and is the seam that makes externality recoverable

- Status: Proposed
- Date: 2026-08-05

## Context

Leg 7 of `docs/roadmap.md` names consolidation as "many episodes distilled into
few durable beliefs, run by the hub's scheduler". That is a model-backed producer
that **reads stored records in bulk** and **proposes durable beliefs through the
`MemoryPolicy` gate**. No such producer exists yet; the lane that builds it is
sequenced behind this ADR, which is why this decision is being taken now rather
than alongside the code (golden rule 5, ADR-0015 §5).

The question is what survives a *derivation* over ingested material. ADR-0098
ruled that ingested content is data and never instruction, and bounded what it may
*become*; it did not rule what happens when this system's own model reads a stored
external record and writes a new belief from it. That is the laundering step:
"a stranger sent an invite" becoming "the assistant believes something", with
every provenance field along the path correct.

### This ADR is not a new idea — it is a deferral firing, and ADR-0098 named it

ADR-0098 §12's first deferral is **"The seam that makes externality recoverable at
the ruling point"** — "a marker on a record or a proposal, and whatever
`MemoryPolicy` change reads it". That bullet names its own trigger, and names this
lane inside it:

> **Also fires with**: a second reader whose output can be cited; an ADR that lets
> an ingested record be an `EpisodicMemory` (ADR-0093 §11's own deferral); and
> **leg 7's consolidation** — `docs/roadmap.md` names it as "many episodes
> distilled into few durable beliefs, run by the hub's scheduler", which is a
> model-backed producer reading records in bulk and proposing through the gate,
> and therefore the largest instance of §5's laundering path the roadmap currently
> contains. The lane that takes the seam owes the caller-stamped/producer-declared
> argument named in §9.

And ADR-0098 §9 states the debt: "**The lane that builds the seam of §5** owes §4's
fourth clause its enforcement point, and owes the choice between a caller-stamped
and a producer-declared marker an argument against ADR-0094 §5."

So this ADR owes three things and is measured against them: the enforcement point,
the marker choice with its argument, and the taint semantics through derivation
that #668's remedy 3 asks for.

### The floor is already ratified, and it is stricter than the fork this ADR was sent to ratify

The brief this lane was dispatched under states the ruling as *"output carries the
most-tainted input's origin marker and lands only in the derived band"*. Read next
to ADR-0098 §4's fourth clause, that is not the operative constraint:

> **Normative.** A model-authored proposal whose externality is recoverable at the
> ruling point is never auto-accepted into durable memory. Its terminal ruling is a
> user question or a refusal.

A consolidator is a model-authored producer. The moment this ADR supplies the
recoverability, that clause binds it — and it says something stronger than "lands
low": a tainted consolidation **does not land at all** without a user's answer. The
band ruling is still owed, because it decides where the belief goes once the user
says yes; it is simply not the whole of the rule. Ratifying only the band half
would leave a reader believing tainted consolidations auto-accept at `DERIVED`,
which the corpus already forbids.

### The two halves of the fork's own sentence cannot both be about `Provenance.source`

"Carries the most-tainted input's origin marker" and "lands only in the derived
band" are in direct tension if the marker is the source, because `band_of` is a
**total function of `MemorySource`** (ADR-0072 §2) and `MemorySource.EXTERNAL` maps
to `ATTESTED`. There is no construction in which a record carries `EXTERNAL` and
sits in `DERIVED`.

It is worse than a naming collision. `Provenance` carries
`_attested_iff_attestation`, which makes an `Attestation` mandatory and exclusive
in that band (ADR-0092 §1), and an `Attestation` names exactly one `reported_by`
and one `reported_at`. A fold over forty calendar entries from three connected
sources has no honest value for either field. The "origin marker" therefore cannot
be the source, and this ADR's marker is a separate fact.

### The evidence chain cannot carry taint either, and #668's remedy 3 says it can

#668's third remedy is "Taint through the evidence chain": "Evidence citation is
already contractual (ADR-0081/0088), so taint is nearly free: an episode born from
an external source is marked; any belief citing it inherits the mark transitively."
The intent is right and the mechanism is not available, for two reasons that are
both in the tree.

**The citation tuple is lossy by ratified design.** `Provenance.evidence` is
"ordered oldest-accumulated first" and carries no `max_length`; the bound lives at
the `MemoryWriter` seam, on installs, and a fold **displaces by age** (ADR-0086 §2,
§3). `Provenance.evidence_elided` records how many displacements a record's history
has performed and is documented as "an **upper bound** rather than a total"
(ADR-0086 §4). So the one citation that made a belief tainted is exactly the kind
of thing a later fold drops, and a taint recomputed by walking citations would
silently become false. A fact that a routine maintenance operation can erase is not
a safety property.

**And the producer chooses its own citations.** A consolidator that cites four of
the six records it read is under-citing — a correctness defect that nothing on
`main` detects. Deriving taint from the citations a model-backed producer emitted
is therefore a producer-declared marker wearing an evidence-chain costume, with the
same fail-open failure: a producer that forgets, or is steered into forgetting,
produces untainted output.

### What has changed on `main` since ADR-0092 and ADR-0098 were written

Two premises those ADRs verified have expired, and both matter here.

**The attested band is no longer empty.** ADR-0092 §2 recorded, as the precondition
for its validator, that "no module under `src/` constructs a `Provenance` with
`source=MemorySource.EXTERNAL` — the only mention of the member anywhere in `src/`
is the arm of `band_of` that maps it to `ATTESTED`", and said the choice was "now or
never" because "the first import makes the band permanently non-empty". Leg 6
landed that import: `readers.calendar` builds a `Provenance` with
`source=MemorySource.EXTERNAL` and an `Attestation` for each occurrence it reads.
Attacker-authored text is in the store today, held as attested beliefs. Nothing
about ADR-0092 is wrong — it anticipated exactly this — but this ADR is on the far
side of that line and may not reach for the migration-free options ADR-0092 §2 had.

**ADR-0098 §5's standing test is now met.** §5 deferred the marker partly because
"no producer on `main` can breach the clause it would serve", resting on the fact
that "no derived belief on `main` cites external evidence": the observer is the only
`DERIVED` producer, its citations are episode ids (ADR-0077 §5), and a sensor may
not propose an `EpisodicMemory` (ADR-0093 §4). Every one of those sentences still
holds. What has changed is that the producer which breaks the pattern is the next
thing leg 7 builds, and golden rule 5 puts its contract ahead of it.

### The enforcement point ADR-0098 §5 could not find

§5's blocker was concrete: "`MemoryPolicy.decide` receives a proposal and a sequence
of conflicting records, and holds no store, so it cannot resolve the ids in
`Provenance.evidence` to see what they are." That is still the signature on `main` —
`decide(proposal, *, conflicts)`. §5 then closed the obvious workaround with a
clause:

> **Normative.** No lane may implement the fourth clause of §4 by having the writer
> substitute a ruling the policy did not make.

Both constraints point at the same answer: put the fact **on the proposal**, where
the gate already looks, and the gate needs no store, no Protocol change, and no
writer inventing a ruling. That is the shape this ADR takes.

## Decision

Marked under ADR-0089: every obligation this ADR imposes is a marked clause, and
unmarked text supplies none.

### 1. What "rests on external content" means, as a predicate over a stored record

> **Normative.** A record **rests on external content** when `band_of` places it in
> the `ATTESTED` band, or when its `Provenance` carries the derived-taint marker of
> §2. External content is ADR-0098 §1's class, unchanged and not re-decided here.

The predicate is two-part because the two bands need different carriers, and saying
so plainly is what keeps the marker minimal.

- In `ATTESTED`, externality is already recorded: the band is reached only through
  `MemorySource.EXTERNAL`, whose whole meaning is that a connected source reported
  it. A marker there would be a second spelling of a fact `band_of` already gives
  for free, and a second spelling is a second thing that can disagree.
- In `ASSERTED`, the predicate is false by ADR-0098 §1, which is explicit that "the
  user's own utterance is not [external], however it was composed — a user who
  pastes an email into a turn is exercising judgement". This ADR does not reopen
  that, and §5 below is what stops a tainted belief from acquiring the exemption by
  a route other than the user actually speaking.
- In `DERIVED`, nothing on the record answers the question. That is the gap, and
  §2 is the field that fills it.

### 2. The marker is one durable boolean on `Provenance`

> **Normative.** `Provenance` gains `derived_from_external: bool = False`: whether
> the belief's warrant traces to external content. It is `core/types.py` surface and
> lands as its own contract PR ahead of any consumer (golden rule 5, ADR-0068 §2).

> **Normative.** The field carries no `Attestation` and names no source. Which
> source a derived belief traces to is ADR-0098 §8's second clause, undischarged
> there and not discharged here.

**A boolean, because that is what the consumers need and nothing more.** The
consumers are §6's gate, which needs a yes or no, and ADR-0098 §12's deferred
presentation state for an inference resting on external evidence, which needs the
same yes or no before it needs anything finer. ADR-0045 §1 and ADR-0028 §7 both rule
that a field with no consumer is surface, and a richer marker — a set of source
keys, a depth, a per-citation map — has no consumer today and would additionally
have to survive the elision problem the citation tuple already fails.

**On `Provenance` rather than on `MemoryBase`**, and the placement argument runs
through ADR-0045 §2's division, which ADR-0092 §1 already applied to this class.
`MemoryBase.validity` is "a lifecycle property of *the record's life in the store*,
set operationally by the applier"; `Provenance` is where producer-set facts about
**trust and source** live. Whether a belief's warrant came from outside is a fact
about trust and source in the pure sense — it is the answer to ADR-0073 §4's "why is
this held?" — and it belongs with `evidence` and `attestation`, not beside a
validity window.

**The default is `False`, and it is correct rather than merely convenient.** ADR-0098
§5's verified chain — the observer is the only `DERIVED` producer, its citations are
episode ids, and no episode is `EXTERNAL` because ADR-0093 §4 forbids a sensor
proposing one — means every derived record a deployment holds today genuinely does
not rest on external content. So a decoded pre-field record reads `False` and reads
truthfully. This is not a case where a default papers over unknown history; the
history is knowably empty, and §7 says what changes the moment it is not.

### 3. The marker is computed by whoever selected the inputs, never read from the producer

> **Normative.** For a model-backed producer, `derived_from_external` on its
> proposals is computed by the component that **selected the input set**, as the
> disjunction of §1's predicate over those inputs, and written onto the proposal
> before it reaches the `MemoryWriter`. Any value the producer itself emitted for
> the field is discarded, not merged.

**This is ADR-0098 §4's third clause, one step further along the same path.** That
clause put the marking of a mixed-origin payload on `orchestration` rather than on
the producer, and gave the reason: "it is fail-closed against a producer that
forgets, because the producer never had the choice." A producer that never had the
choice about the payload should not acquire it about the payload's record.

**And it is the argument ADR-0098 §9 asked for against ADR-0094 §5.** §5 rules that
"a claim carried in a submission is not evidence of the standing it claims". A
producer-declared taint flag is the mirror of that move — a producer declaring its
own standing — and the mirror does not exempt it, because the failure that matters
is not a producer over-claiming taint but a producer **omitting** it. A self-declared
demotion is safe only if declaring it is guaranteed, and nothing guarantees a model's
output field. The caller holds the input set as data it fetched, so its computation
is a fact rather than a claim. Discarding rather than merging the producer's value is
what makes the guarantee total: there is no code path in which forgetting has an
effect.

**"The component that selected the input set" rather than a named module**, because
ADR-0077 §1's "Selection therefore belongs to `orchestration`" is a ruling about the
observer's stage and this ADR does not extend it by implication to a scheduler job
nobody has designed. The obligation attaches to whichever component does the
selecting; the consolidation lane places it, and cannot place it on the producer.

### 4. The marker never clears, and a user's assertion is the only exit

> **Normative.** No fold, merge, reinforcement, or supersession clears
> `derived_from_external` on a record that carries it. Where a write combines a
> tainted record with an untainted one, the result is tainted.

> **Normative.** A record whose `MemorySource` is `USER_ASSERTED` never carries the
> marker, and no rule in this ADR obliges a user's own assertion to inherit taint
> from anything it retires or contradicts.

**Monotonicity is what makes §1's predicate mean anything over time.** Without it,
the laundering path simply moves: consolidate tainted material into a belief, then
reinforce that belief with one clean observation and watch the marker clear. This
is the same shape as ADR-0103 §3's ratchet on evidence-strength, arrived at from the
other direction — evidence-strength ratchets up because evidence is never unseen,
and taint ratchets on because a warrant is never un-received.

**The clause is stated over the *fold*, not over the incoming record, because
`memory`'s fold is not symmetric and the asymmetry runs the wrong way here.**
`MemoryIngestor._merge(target, incoming)` builds its `Provenance` field by field and
takes `source`, `last_updated` and `attestation` from **`incoming`**; only
`confidence` (a `max`) and `evidence` (a union) combine both sides. A new field
written in the majority style — `incoming.provenance.derived_from_external` — would
clear a tainted target the first time a clean proposal reinforced it, which is
precisely the laundering above. The marker belongs with `confidence` and `evidence`
in the combining minority: **the fold's value is the disjunction of both sides**,
and the direction that has to be exercised is a *tainted target* reinforced by an
*untainted incoming*, which §10 obliges. The opposite direction passes an
implementation that merely copies the incoming field and proves nothing.

**The exit is supersession by the user, and it is already built.** ADR-0072 §4 and
ADR-0038 state the asymmetry: `ASSERTED` may retire `DERIVED`, never the reverse,
and the applier "closes the superseded record's validity window and writes the
correction at a fresh id". The fresh record is the user's own word, so it is not
external by ADR-0098 §1 and the second clause above keeps it that way. That is the
recovery layer #668 names — "user assertions supersede anything injected" — reaching
this marker without a special case.

### 5. Consolidation output lands in the `DERIVED` band, always

> **Normative.** A consolidation proposal is proposed in the `DERIVED` band — its
> `MemorySource` is `OBSERVED` or `INFERRED` — whatever the bands of its inputs. It
> is never proposed as `ATTESTED` and never as `USER_ASSERTED`.

**Stated as an absolute, because the comparative in the fork does not resolve.**
"Never a higher band than its weakest input" presumes an ordering over
`BeliefBand`, and there is none: ADR-0072 §2 defines three bands and orders nothing.
The only ordering in the corpus is ADR-0072 §5's *precedence for an assembler
filling a budget*, which is live and under revisit — ADR-0098 §10 adds an input to
it and #663 records the trigger as fired. A rule that read its meaning off an
ordering under active revision would change meaning when that revisit lands. An
absolute does not.

**And `ATTESTED` is refused on its own merits, not by elimination.** A consolidation
is this system's generalisation over records; calling it attested would claim a
source reported it, which is false, and `_attested_iff_attestation` would demand an
`Attestation` the fold cannot honestly fill (§Context). #668's remedy 1 offers "a
capped-confidence ATTESTED/INFERRED belief" as an alternative to a question; the
`ATTESTED` half of that is refused here, and the reason is ADR-0098 §10's own:
"`ATTESTED` is the band an outsider can write into, and ordering it above `DERIVED`
gives that outsider budget priority over the system's own inferences." Landing
consolidated output in `ATTESTED` would hand the attacker the better band as a
reward for having been consolidated.

**This clause forbids a promotion nothing on `main` can perform, and is worth
stating anyway.** ADR-0098 §4's second clause already rules that "a producer does not
raise the band of what it proposes by any means, including by claiming a
`MemorySource` it is not". This clause is that rule read on the one producer whose
*inputs* sit in a different band from its output — the case where "raise" is
ambiguous unless someone says which way is up.

### 6. The enforcement point: the gate rules, and it can see the fact without a store

> **Normative.** **No `MemoryPolicy`** returns a committing ruling on a proposal
> carrying `derived_from_external` and no `UserConfirmation` — whatever the policy's
> other rules, and however trusted the producer. Its terminal ruling is `ASK_USER`
> or `REJECT`. This is ADR-0098 §4's fourth clause given its enforcement point, and
> adds no condition to it.

> **Normative.** The clause above is an obligation of the `MemoryPolicy` contract:
> it is stated on the Protocol and asserted in the shared `MemoryPolicyContract`
> suite, beside the secret-tier ceiling and by the same `_COMMITTING` predicate.
> The suite covers the confirmed case as well as the unconfirmed one, so that a
> policy admitting the confirmed re-ingest is not failed by it.

> **Normative.** The rule is an admissibility rule — a property of the proposal
> alone, committing nothing — so in `DefaultMemoryPolicy` it sits in the
> admissibility floor, **behind both of that floor's existing rulings** — the
> secret-tier deferral and ADR-0077 §5's rejection of a derived belief citing no
> evidence — and ahead of every conflict rule. A proposal carrying a
> `UserConfirmation` for the deferral this rule raised passes it and is judged on
> the ordinary path.

> **Normative.** `DefaultMemoryPolicy`'s ruling under that rule is **`ASK_USER`**,
> never `REJECT`. The contract ceiling above admits either; the default takes the
> question.

> **Normative.** The ruling is the `MemoryPolicy`'s. No writer, applier, or
> scheduler substitutes, upgrades, or downgrades it, and none of them may implement
> this section by converting a ruling the policy made into a different one.

**It is a contract obligation and not the default policy's rule, and an earlier
draft made it the default's.** `MemoryIngestor` accepts any `MemoryPolicy` by
injection, and `MemoryPolicyContract`'s docstring is explicit that the suite
"deliberately does **not** encode *which* ruling a given proposal earns: that is
each policy's reasoning". So a conforming policy that returned `ACCEPT` on a tainted
proposal would breach ADR-0098 §4 while passing every test, and every test §10 would
have obliged — they all run against `DefaultMemoryPolicy`. Adversarial review found
it on round 4.

**The precedent is exact and is one line above where this clause lands.** The suite
already asserts one never-commit ceiling that is nobody's reasoning: "ADR-0004 §3:
Tier 0 data belongs in the OS keyring, never the memory store — whatever the
policy's other rules, however trusted the source". Its docstring states the test for
what may join it — "Every obligation here traces to something already ratified" and
"A conformance suite **is** contract: an obligation the Protocol does not state
widens that contract without an ADR (golden rule 5)". This clause traces to ADR-0098
§4, and this is the ADR golden rule 5 asks for, which is why the promotion is ruled
here rather than left to the implementing lane's discretion.

**It collides with neither exclusion the suite carries.** ADR-0040 §5 refuses to let
the suite assert *which relation* a target-carrying ruling picks, and ADR-0028 §8
keeps the fold's own rule out; ADR-0103 §7 keeps confidence composition out for the
same reason. This clause asserts none of those — it is a ceiling on what may commit,
not a rule about what a policy concludes, and a policy remains free to choose
`ASK_USER` or `REJECT` and free to rule anything it likes once a confirmation is
present.

**The default's ruling is pinned separately, because a ceiling that admits two
outcomes does not choose between them and §10 needs one chosen.** ADR-0098 §4's
wording is "a user question **or** a refusal", so the contract ceiling keeps both:
a policy with a different posture — one deployed somewhere a user cannot be asked —
conforms by refusing, and pinning `ASK_USER` into the *contract* would refuse it.
But a `DefaultMemoryPolicy` that refused would make §10's end-to-end clause
unimplementable, because `MemoryWriteStage` queues on `ASK_USER` and on nothing
else: there would be no `DeferredProposal` to enumerate and no affirmative answer to
give. Adversarial review found the two marked clauses jointly unsatisfiable on
round 6.

Choosing the question is also the substantive answer rather than a repair. #668's
goal, which this ADR inherits, is converting a successful injection into "a visible,
source-attributed proposal — spam, not poison"; a silent `REJECT` on the scheduler's
path destroys the consolidation, tells nobody, and leaves the user unable to keep a
summary they would have wanted. That is a worse outcome than a question, and under
ADR-0098 §8 it would additionally reach nobody at all.

**Behind the whole floor rather than beside part of it**, which is ADR-0078 §5a's
ordering taken exactly. That floor holds two rulings that "precede any conflict
reasoning": the secret-tier deferral, and ADR-0077 §5's rejection of a derived
belief citing no evidence. Both outrank taint, and each for its own reason.

- A proposal that is both secret and tainted takes the **secret** path — unqueued —
  because §1 of ADR-0078 refuses to queue a secret proposal at all, and a taint rule
  ordered first would queue one.
- A tainted derived proposal citing **nothing** is a `REJECT` and not a question. A
  taint rule ordered first would return `ASK_USER` and put an unwarranted belief in
  front of the user as though answering it could make it admissible; ADR-0077 §5
  rejects it whatever the user says.

ADR-0078 §5a made the same call for the confirmed rule and gave the reason for
stating it rather than relying on the case being unreachable: "a floor that holds
only while a coincidence holds is not a floor." Here it is not even a coincidence.
§5a could observe that a derived belief citing nothing "is rejected at its first
ingest, so it is never deferred and never confirmed"; a consolidator's *first*
ingest is exactly where a citation-less proposal would arrive, so the case is live
rather than unreachable. Adversarial review found the missing half of the ordering
on round 7.

**The confirmation carve-out is what makes the question a question, and an earlier
draft omitted it and thereby ruled the opposite of this ADR's own §5.** ADR-0078 §5
is explicit that "the confirmed answer is a **re-ingest**": the coordinator rebuilds
the proposal with a `UserConfirmation` and calls `MemoryWriter.ingest`, so "Conflict
detection, the policy, the atomic applier and the full-set retirement rule all run
unchanged." The taint marker rides along on that re-ingest. A rule stated without
the carve-out therefore fires a second time on the confirmed proposal and defers it
again — "The user answers, and is asked again", which is the failure ADR-0078 §3
names in its own words — and a tainted consolidation could never land, contradicting
§5 above and the Consequences below. Adversarial review found it on round 3.

**The carve-out is what "auto" already means, not a relaxation of ADR-0098 §4.**
That clause reads "never **auto**-accepted into durable memory. Its terminal ruling
is a user question or a refusal." A ruling reached by asking the user and receiving
their answer is not an automatic acceptance; and a question whose only admissible
answer is "no" is not a question, which is the reading under which §4's second
sentence would forbid the first sentence's own remedy. ADR-0098's posture is stated
as "a real containment and it is not a prevention", and #668's goal that this ADR
inherits is the conversion of a successful injection into "a visible,
source-attributed proposal — spam, not poison". A user who reads a consolidated
belief and says yes is the containment working.

**The ordering is ADR-0078 §5a's, taken rather than re-derived.** That section put
the confirmed rule "ahead of every conflict rule but behind the admissibility floor"
because the floor's rulings "are properties of the proposal alone and neither commits
anything, so nothing a confirmation says can make either safe to skip". Taint is a
property of the proposal alone and commits nothing, so it belongs in the floor. It
differs from the secret-tier rule in exactly one respect and the difference is
principled: the secret rule is *never* satisfiable by a confirmation, because §1 of
ADR-0078 refuses to queue a secret proposal at all and `MemoryUpdateProposal`'s
validator makes the combination unconstructable — there is no question to answer. A
tainted proposal *is* queued, so there is one, and answering it is the point.

**This requires no Protocol change, which is the whole reason the marker is on the
record.** ADR-0098 §5 could not site the enforcement because
`MemoryPolicy.decide(proposal, *, conflicts)` "holds no store, so it cannot resolve
the ids in `Provenance.evidence`". A boolean on `proposal.proposed.provenance` needs
no resolution: the gate reads it off the argument it already receives. The seam
§5 said did not exist turns out to cost one field and no signature.

**The second clause is ADR-0098 §5's own restated at this ADR's seam**, and it is a
separate clause because the pressure is real and specific: a scheduled bulk job that
produces a thousand questions will tempt its lane to have the applier auto-answer
the easy ones. ADR-0081 §3 already rules that a writer refuses by raising rather than
returning "a fabricated `REJECT`", "because a ruling is the policy's to make
(ADR-0005 §3) and a writer inventing one puts a decision nobody made into the ingest
result". The same sentence reads on an upgrade as on a refusal.

> **Normative.** A consolidator reaches the store through the orchestration write
> stage, never through `MemoryWriter.ingest` directly.

**Without that clause the ruling of §6 is a black hole, and an earlier draft of this
section asserted the opposite.** That draft said `ASK_USER` "does not merely report —
it writes a durable `DeferredProposal`", which is false at the writer.
`MemoryIngestor` states it in its own words: "`REJECT` and `ASK_USER` write nothing
at all." ADR-0078 §3 rules where the durability actually comes from — "`MemoryWriter.ingest`
… does not change, and does not learn to queue … Instead the **orchestration write
stage** — which already holds the `MemoryWriter` by injection and now also holds the
`DeferralStore` — observes `result.decision.kind is ASK_USER` and enqueues" — and
`orchestration.MemoryWriteStage` is documented as "the one place a proposal" takes
that route. A scheduled job that called the writer directly, which is the convenient
thing for a scheduler to do, would rule `ASK_USER` on a thousand consolidations and
persist not one question. Adversarial review found the claim on round 1; the
correction is the clause above, because the property has to be *obliged* rather than
assumed.

**With it, this section does not hit #659's wall.** ADR-0098 §8 warns that "a ruling
made on the ingestion path reaches nobody at all" because `Engine.ingest`'s result
reaches no adapter, and §10 says a later ADR wanting to report a capped or refused
proposal "would hit that wall first". The write stage's enqueue is not a report: it
writes a `DeferredProposal` into a `DeferralStore` exposing `pending`, `interrupted`
and `export`, so the question outlives the job that raised it and is enumerable
afterwards. #659 remains open and remains about the *report* of a ruling; nothing
here discharges it, and a lane that wanted to tell the user "a consolidation was
refused" would still hit it.

**One case the stage already excludes, named so the consolidation lane does not
rediscover it.** ADR-0078 §3 filters a `DataTier.SECRET` proposal out before `defer`,
so its `ASK_USER` is reported and nothing is persisted. A consolidation over secret
material therefore terminates in an `ASK_USER` that is **never queued and so can
never be answered** — not a `REJECT`, and the distinction matters to an operator
reading the result: the ruling is a question nobody will be asked, not a refusal.
Nothing lands either way, so §6's first clause is satisfied; that the question
evaporates is #659's channel problem, and neither is a licence to route around the
stage.

**The cost is named rather than minimised.** A store holding a lot of external
material will produce a lot of questions, and a scheduled consolidator can generate
them faster than a user answers them. This ADR does not solve that and does not
pretend the levers are free: the consolidator may **scope its input selection to
untainted records**, which keeps its output auto-acceptable and is the shape
available today; batching, question-merging, and any bound on the deferral queue are
the consolidation lane's and leg 8's, on measurement. What is not available is
relaxing the clause, which would be superseding ADR-0098 §4.

### 7. No validator, and the window for one has closed

> **Normative.** `derived_from_external` is not enforced by a `Provenance` model
> validator, and no lane adds one that conditions the field on the band.

The obvious tightening is a validator asserting §1's implications — `ATTESTED`
implies rests-on-external, `ASSERTED` implies not. It fails ADR-0086 §3's test,
which the corpus states outright: "The test is not 'is it a validator on a `core`
type' but 'does it refuse something that already worked'." A validator implying
`ATTESTED ⟹ True` would refuse, on decode, every attested record `readers.calendar`
has already written — "a strictly new failure invented on the read path".

ADR-0092 §1 landed exactly such a band-keyed validator, and it could, because §2
verified that no record it would refuse could exist. That verification is expired
(§Context), and the difference is the point: ADR-0092 §2 argued "the choice is now or
never", and for a validator on this axis the answer is now *never*. §1's predicate is
therefore stated as a rule over producers and callers, checked by tests at the seams
that write, not by a type that refuses on read.

### 8. What this ADR does not decide

> **Normative.** This ADR rules nothing about either confidence quantity. What a
> consolidated belief's evidence-strength is, and what its currency is or when it
> declines, are ADR-0103's and its implementing lane's, and no clause here may be
> read as constraining them.

> **Normative.** This ADR grants the marker no retrieval-side role. It does not
> rank, weight, filter, or order anything in `MemoryStore.search`, and it is not an
> input to band precedence.

The currency question is a real one — a belief consolidated from a calendar the user
has since disconnected is a genuine currency case — and it is ADR-0103's territory
under its §9, which leaves the representation of both quantities on `Provenance` to
its own implementing lane. Two lanes therefore add to `Provenance`; they sequence
behind one another as ADR-0068 §2's "single `core` contract PR" requires, and neither
needs the other's field.

The retrieval clause exists because a taint marker is exactly the kind of field a
later lane would reach for as a down-ranking signal, and ADR-0072 §5 refuses that
class of move on grounds that read here with full force — a store that quietly
down-ranks a belief starves the loop that would correct it. ADR-0103 §8 declined the
same thing for currency, and this is that clause one field over.

**#301 is not closed by this ADR and is not narrowed by it.** That issue is
cross-step confidentiality and taint tracking across `ActionPolicy` and
`MemoryPolicy` decisions. This ADR marks a *record's warrant* on the memory write
path; it says nothing about a taint that survives a planning step, and ADR-0098 §3
and §5 are explicit that the link between a model's output and the span that
produced it is not recoverable. A lane taking #301 inherits nothing from here but
the field.

### 9. Preconditions on the consolidation implementation lane

> **Normative.** No consolidator is scheduled against a `MemoryStore` write path on
> which `#630` is unfixed. A bulk-writing minting producer on a blind upsert
> destroys unrelated live records, and this ADR's marker does not make that safe.

> **Normative.** `#631` is **not** a precondition on consolidation, and no lane may
> record it as one.

**#630 is real and is owned elsewhere.** `MemoryStore.add` is an upsert keyed on id,
so a minting producer whose id collides silently replaces a live belief that was
never among the ruled-on conflicts. A consolidator mints, in bulk, unattended. The
hand-off recorded on #630 establishes that the fix belongs at `MemoryStore.add`
rather than at `MemoryIngestor` — "A rule at `add` covers every caller; a rule at
`ingest` covers one", because episodic capture is exempt from the write-path rule
(ADR-0075 §1) — and that ADR-0081 §8 assigns it to the `MemoryStore` write-semantics
lane taking #104's compare-and-swap. That lane is not scheduled. This clause is what
stops wave 3 starting without confronting it, and this ADR does not pick the lane's
shape: #630's genuine difficulty is that ADR-0022 §4 *ratifies* last-write-wins on a
repeated record id and names a legitimate use for it, so the fix must separate the
deliberate re-proposal from the accidental minted collision rather than ban both.

**#631 is recorded here because the brief this lane was dispatched under, and #729
itself, both name it as a prerequisite and it is not one.** #631 is *duplication*
reached only by a producer that **re-syncs** a source — the mechanism is a second
read of the same external entry whose text changed between reads. A consolidator
mints and does not re-sync, so it can never reach it. #631's own trigger, ADR-0092
§10's "first observed duplicate from a rewritten entry", is also unfired. Stating
this as a clause rather than as prose is deliberate: an unfired prerequisite in a
dispatch plan costs a lane, and this one has already been inherited twice.

### 10. What the implementing lanes owe

> **Normative.** The lane landing `derived_from_external` on `Provenance` ships a
> test that a record decoded without the field reads `False`.

> **Normative.** The same lane states §6's ceiling on the `MemoryPolicy` Protocol
> and adds it to `MemoryPolicyContract`, in the same change as the field. The
> contract PR therefore touches `core/protocols.py` as well as `core/types.py`.

> **Normative.** The lane changing `memory`'s fold ships a test covering **both
> positions of the tainted side** — tainted target with untainted incoming, and
> untainted target with tainted incoming — asserting the folded result is tainted in
> each (§4). One parametrised test over the two positions satisfies this clause;
> either position alone does not.

> **Normative.** The consolidation lane ships a test that a proposal built from an
> input set containing an `ATTESTED` record reaches the gate carrying the marker
> **when the producer's own output omitted it** (§3), and a test that the gate's
> terminal ruling on it is `ASK_USER` or `REJECT` (§6).

> **Normative.** The same lane ships a test whose only tainted input is a `DERIVED`
> record carrying `derived_from_external`, asserting the proposal reaches the gate
> tainted. A selection step that computes the marker from the input's *band* alone
> satisfies the clause above and fails this one.

> **Normative.** The same lane ships a test in which every selected input is
> untainted and the producer emits `derived_from_external=True`, asserting the
> proposal reaching the gate carries `False` (§3's discard-not-merge).

> **Normative.** The same lane ships a test that a tainted, unconfirmed, derived
> proposal citing **no evidence** is rejected rather than queued, pinning §6's floor
> ordering. Every other clause here supplies evidence, so none of them can fail on
> that ordering.

> **Normative.** The same lane ships an end-to-end test that a tainted consolidation
> routed through the orchestration write stage leaves a `DeferredProposal`
> enumerable from the `DeferralStore` afterwards, and that **answering it
> affirmatively lands a durable record still carrying the marker** (§4, §6). A test
> that stops at the policy's ruling does not satisfy this clause.

**Each clause names the case that can fail, because every one of these has a wrong
implementation the neighbouring test waves through.** The producer-omits case is
named because a test exercising only a cooperative producer passes a fail-open
selection step. The `DERIVED`-input case is what makes "inherits" mean anything past
a single hop: a selection step checking `source is EXTERNAL` and nothing else is
fail-open against exactly the second-order consolidation §4's monotonicity exists to
stop, and it is invisible to a test whose tainted input is attested. The two fold
positions are required together because `_merge` reads most of its `Provenance` from
one side, so a test in either position alone passes an implementation that simply
copies that side. The producer-emits case is the mirror of the omits case, and its
failure is noisy rather than unsafe — a merging implementation raises spurious
questions — but §3 states discard as an obligation and an unwitnessed obligation
decays. The end-to-end case carries both of this ADR's own review defects: its
first leg would have caught round 1's, where the ruling was right and the question
reached nobody, and its second leg round 3's, where the question was raised and
answering it yes could not land anything. This is the discipline ADR-0098 §9 imposed
on the prompt-assembly lane, whose clause insists on rendering "a record whose
`content` contains that assembler's own container syntax" rather than merely
asserting a label is present — the test has to be able to fail.

Unmarked, and owed by nobody as an obligation: the observer is unaffected. Its
payload holds episodes and nothing else (ADR-0077 §1, §3), no episode is `EXTERNAL`
(ADR-0093 §4), so its stage computes `False` for every proposal it will ever make
and the field costs it one constant.

### 11. This ADR classified under ADR-0070 §1 and ADR-0082 §1

ADR-0082 §1's test is whether "a reader holding only the earlier ADR" would now act
differently or read one of its clauses more widely.

- **ADR-0098 §4, fourth clause.** Unchanged in text and in reading. What changes is a
  fact about the world: the recoverability its own wording is conditioned on now
  exists, because §9 of that ADR assigned this lane the job of supplying it. A reader
  of §4 alone applies the same sentence to the same condition. **Addition — a
  deferral firing on its own stated trigger, not an amendment.**
- **ADR-0098 §5.** Its argument for deferring the marker had three grounds, and it
  named the one that would expire: "The standing test is unmet … no producer on
  `main` can breach the clause it would serve." §12 carries the trigger. Discharging
  a deferral by the route the deferral specified is what the deferral is for.
  **Addition.**
- **ADR-0072 §2 and §5.** §2 is relied on exactly as written — the totality of
  `band_of` is the reason §5 of this ADR is an absolute rather than a comparative —
  and §5 is untouched, with §8 above refusing the retrieval role rather than taking
  it. **Addition.**
- **ADR-0092 §1.** Relied on as written: this ADR's §5 refuses `ATTESTED` for
  consolidation partly *because* `_attested_iff_attestation` would demand an
  attestation the fold cannot supply. The validator's scope is not widened and the
  new field is deliberately outside it. **Addition.** §2's *verification* has expired
  as a fact, which is not an amendment of anything §2 ruled — §2 stated the
  verification narrowly and predicted the expiry in the same paragraph.
- **ADR-0086 §2, §3, §4.** Relied on as the reason the citation tuple cannot carry
  taint, and as the test that refuses a validator. Neither is read more widely.
  **Addition.**
- **ADR-0078 §3, §5 and §5a.** Relied on exactly as written. §6's routing clause
  obliges a new producer to use the write stage §3 already designates as the enqueue
  point, and takes no ruling about what that stage does; §3's `DataTier.SECRET`
  filter is named rather than narrowed. §6's confirmation carve-out and its ordering
  are §5's re-ingest and §5a's floor-then-confirmed sequence applied to one more
  admissibility rule — §5a's own reason for that sequence ("properties of the
  proposal alone… neither commits anything") is the reason taint sits in the floor,
  and no rule of §5a's is read more widely. **Addition.**
- **ADR-0004 §3.** Relied on only as the *shape* precedent for a never-commit
  ceiling in the shared suite. Nothing about the secret tier is read more widely, and
  §6's rule is deliberately unlike it in the one respect §6 names — a confirmation
  can satisfy this one and can never satisfy that one. **Addition.**
- **ADR-0028 §8, ADR-0040 §5, ADR-0103 §7.** Each keeps something *out* of the
  `MemoryPolicy` suite — the fold's own rule, which relation a ruling picks, how
  confidence composes. §6 adds a ceiling on what may commit, which is none of those,
  and the suite already carries one of exactly that kind. No exclusion is narrowed.
  **Addition.**
- **ADR-0022 §4 and ADR-0081 §8.** Named in §9 as constraints on a *different* lane,
  with no ruling taken over either. **Addition.**
- **ADR-0103.** §8 above declines to touch it in either direction. **Addition.**

**Nothing here is a supersession**, wholly or partially. No decision moves, and there
is no sentence in the corpus a reader would now act differently on. This branch
touches no file but this one.

**This ADR is marked under ADR-0089** and is in the marked regime: its unmarked prose
supplies no obligation and exists to determine what the marked clauses mean
(ADR-0089 §3). Marking is forward-only (§5), and nothing ratified before it is drawn
into the regime by it.

### 12. Deferred, by name, each with the condition that fires it

- **The presentation state for a belief that rests on external evidence.** ADR-0098
  §12 defers it and says it "needs the marker of the deferral above to exist before
  there is anything to present, so it **fires with that seam**". This ADR is that
  seam, so the trigger fires here — but the surface it would land on is the one
  ADR-0098 §8 records as lossy in three places already (**#568**, **#673**, the
  dropped `Attestation`), and adding a fourth field to a projection that drops three
  is the wrong order of work. **Fires with the lane that next revises `Belief` /
  `BeliefSummary`**, which #568 and #624 already own.
- **Naming which external source a derived belief traces to.** Undischarged under
  ADR-0098 §8's second clause, whose own trigger is "the second reader", when
  "attested" stops identifying the source by elimination. Not reached by this ADR's
  boolean, deliberately (§2).
- **Whether a tainted belief may parameterise an egress or actuation.** #668's
  remedy 3 names it as a consumer of the same boolean — "tainted context
  parameterizing an egress action requires confirmation". ADR-0098 §3's actuator
  clause rules on the *span*, not on a belief derived from it, and its last clause
  leaves standing authorisations open by name. **Fires with the first actuator**, in
  that lane's ADR, which now has a recorded fact to reason over rather than an
  unrecoverable one.
- **A bound on the deferral queue a scheduled producer may fill.** §6 names the
  volume cost and does not solve it. **Fires with the consolidation lane's own
  measurement**, and its parameters are leg 8's under ADR-0103 §5's division.
- **Whether taint survives a planning step.** #301, untouched here (§8).

## Consequences

**The laundering path named in ADR-0098 §5 and §12 is closed at the memory write
path**, and closed by construction rather than by detection: a consolidation over
attested material cannot become a durable belief without the user answering a
question, and the fact that makes that true is computed by the component holding the
inputs rather than claimed by the model reading them. ADR-0098 §6's rule that no
bound may be bought from a filter is honoured — nothing here inspects text.

**Consolidation becomes more expensive over external material, on purpose.** The
cheap consolidations are the ones over the system's own observations; a consolidator
that reaches into the attested band pays in user questions. That is a design
pressure toward keeping the two apart, and it is the right pressure, but it is also a
real reason a future lane will want this relaxed. The relaxation is a supersession of
ADR-0098 §4, not of this ADR, and should be argued there.

**`Provenance` grows a field, and two lanes now want to.** This one and ADR-0103's
implementing lane both add to the cross-subsystem hinge, so they sequence as separate
`core` PRs (ADR-0068 §2). Neither depends on the other's field, so the order is a
scheduling choice.

**The `MemoryPolicy` contract grows an obligation, so the core PR is larger than one
field.** It touches `core/protocols.py` and `MemoryPolicyContract` as well as
`core/types.py`, and every existing `MemoryPolicy` implementation must pass the
widened suite — which means **both** of them change, the canonical
`FakeMemoryPolicy` as much as `DefaultMemoryPolicy`. A fake configured to return
`ACCEPT` returns it for a tainted unconfirmed proposal too; its secret-tier override
does not reach that input, and the suite's new case will hand it one. So the
contract PR gives the fake the same non-committing override and tests it, and the
lane should budget for that rather than discovering it when its own conformance run
fails.

**A `bool` will feel too coarse the first time someone asks "from which source?"**
and the answer will be to discharge ADR-0098 §8's second clause rather than to widen
this field. That is stated so the next lane does not quietly grow the boolean into a
source list on the way past.

**What would trigger revisiting this decision:** a measured deferral-queue flood that
makes consolidation unusable over a realistic store; the first actuator, whose lane
must decide what a tainted belief may parameterise; or a demonstration that the
caller-stamped computation is itself forgeable — which would mean the input set is
not held where §3 assumes it is.

## Alternatives considered

**Derive taint by resolving the evidence chain at the ruling point.** #668's remedy
3, and the shape the fork's "inherits taint" wording most naturally suggests.
Rejected on two grounds in §Context: `Provenance.evidence` displaces citations by age
and `evidence_elided` is an upper bound, so a fold can erase the citation that
carried the taint; and the producer chooses what it cites, so the derivation is
producer-declared in disguise. It also requires the ruling point to hold a store,
which ADR-0098 §5 establishes it does not.

**Widen `MemoryPolicy.decide` to receive the resolved evidence records.** The
writer already resolves them — `MemoryIngestor._require_resolvable_evidence` reads
each cited record — so passing them to the gate is mechanically available and keeps
the ruling with the policy. Rejected because it is a Protocol change bought to
obtain a fact that a one-field record change supplies directly, it inherits the
elision problem above, and it makes every policy implementation pay for a signal one
producer needs.

**Carry the taint as `MemorySource.EXTERNAL` on the consolidated record.** The
literal reading of "carries the most-tainted input's origin marker". Rejected because
`band_of` is total, so it lands the record in `ATTESTED` — contradicting the same
sentence's second half, claiming a source reported what this system inferred, and
requiring an `Attestation` a fold cannot honestly fill.

**A new `MemorySource` member for consolidated-from-external.** Rejected because
`MemorySource` is the band classifier (ADR-0072 §2) and a new member forces a band
choice for it; the honest band is `DERIVED`, which the existing members already
express. It would also enrol the new member in ADR-0092 §4's supersedable set by
hand, for no gain.

**Producer-declared taint, with the model asked to mark its own output.** Rejected
in §3: the failure that matters is omission, and nothing guarantees a field in a
model's output. It is ADR-0094 §5's refused move with the sign flipped, and flipping
the sign does not restore the guarantee.

**Cap the confidence instead of gating the write.** #668's remedy 1 offers "a
capped-confidence ATTESTED/INFERRED belief" as an alternative to `ASK_USER`. Not
available: ADR-0098 §4's fourth clause is ratified and says the terminal ruling is a
user question or a refusal. Taking the softer option would be superseding it, which
is a decision for a lane arguing against §4 on its merits — with measurement this
lane does not have.

**Defer the whole question to the consolidation implementation lane.** Rejected by
golden rule 5 and ADR-0015 §5: the marker is `core` surface, and a lane that
discovered it needed one mid-implementation would either ship without it or stop. It
is also the outcome ADR-0098 §12 wrote its trigger to prevent.
