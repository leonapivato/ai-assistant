# 171. A supersession sweeps in only a labelled contradiction, and the labelling bound rises to fifteen

- Status: Proposed
- Date: 2026-08-21
- **Partially supersedes:**
  [ADR-0159](0159-a-conflict-is-labelled-before-it-is-ruled-on-and-similarity-alone-folds-nothing.md)
  in two scopes — §3's **default value clause**, *"`Settings` gains
  `reconciler_max_conflicts: int`, positive, defaulting to **3**"*, in the respect
  that the default is now fifteen (§1 here); and §5's **second clause**, which
  states that ADR-0079 §3's retirement obligation *"is narrowed by the clause above
  and is otherwise unchanged"*, in the respect that §2 here narrows it further.
  [ADR-0079](0079-a-correction-resolves-every-conflict-it-is-shown.md) §3 and
  [ADR-0050](0050-resolving-the-full-contradiction-set.md) §1, in the same
  scope as §2: the retirement set of a `SUPERSEDE` made on a crossing for which the
  writer holds a `CONTRADICTS` relation no longer reaches a member the writer holds
  no relation for.
  [ADR-0070](0070-amendment-and-supersession-rules.md) §1's test decides the form
  and decides it against an amendment in each case: a reader holding only ADR-0159
  would ship a default of three and would build a writer that retires records §2
  forbids retiring, and a reader holding only ADR-0079 §3 or ADR-0050 §1 would build
  the same writer. Each is a rule a reader obeys rather than an explanation of one,
  so each is a partial supersession taking ADR-0070 §3's form and §4's status
  vocabulary. The remainder of all three stands: ADR-0159 §3's bound, its rank
  order, its unlabelled-beyond-the-bound rule, its one-request clause, its temporal
  clause and its never-raises clause are untouched; ADR-0159 §5's `RESTATES`/`ADDS`
  exclusion, its refusal of a `SUPERSEDE` naming such a member, and its
  enforced-at-the-writer clause are untouched and are extended rather than replaced;
  ADR-0079 §1 and ADR-0050 §1's `USER_ASSERTED` hold-out stand word for word.

  The three `Status` lines and their dated notes land **in this same change**, so
  no line names an ADR that does not exist — the hazard ADR-0070 §1 guards against.
  While this ADR stands `Proposed` those lines name a supersession that is drafted
  rather than ratified, which [ADR-0083](0083-the-hub-is-a-resident-process.md) §15
  rules outright: *"the existence condition is that the naming ADR ships in the same
  change, not that it has ratified"*.
- **This ADR decides a contract surface.** §2 changes an obligation
  `MemoryWriter.ingest`'s docstring states in `core/protocols.py`, which the shared
  conformance suite drives and the canonical `FakeMemoryWriter` mirrors. It adds no
  Protocol, no method, no parameter and no `core` type, and moves no signature — but
  a reader building a writer from the contract as it stands would build one this ADR
  forbids, so it is a contract change under golden rule 5 and not a tuning change.
  The required review set is therefore **adversarial and architecture**
  (ADR-0015 §1, `CONTRIBUTING.md` → "Stop when the required reviews are green"), the
  status is flipped only once both return clean on one tree, and nothing implements
  against §1 or §2 until this has merged (ADR-0015 §5, golden rule 5).
  `CONTRIBUTING.md` → "Finishing an ADR PR" holds that sequence and is pointed at
  rather than re-argued here.

## Context

### What the widening does today, exactly

A `SUPERSEDE` retires more than the record the ruling names. `_retirement_set` in
`memory/ingest.py` returns the named `target` plus every other member of the
conflict set whose source is in the retirement class and for which the writer holds
no `RESTATES` or `ADDS` relation. That is ADR-0050 §1's set, promoted to a
`MemoryWriter` obligation by ADR-0079 §3, widened to `EXTERNAL` by ADR-0092 §4, and
narrowed by ADR-0159 §5. `testing/writer.py` carries the same predicate for
`FakeMemoryWriter`, duplicated rather than imported.

The predicate's relation test is written over the relations the writer **holds**.
`_UNRETIRABLE_RELATIONS` is `{RESTATES, ADDS}`, and its own comment says why
`CONTRADICTS` is absent: *"a labelled contradiction is exactly what a correction is
warranted to retire"*. Nothing in that set is a member's *absence*. A member the
writer holds no relation for is therefore swept in, because the lookup returns
nothing and nothing is not in the set.

Which members carry a relation is decided somewhere else entirely, and the two rungs
are bounded differently. `ConflictReconciler.reconcile`'s only implementation builds
the certain rung's labels over **the whole conflict set** — a comprehension across
`conflicts`, labelling `RESTATES` wherever `agrees` holds, exactly as ADR-0159 §3's
first clause requires ("that predicate is the reconciler's first rung and it is
unconditional"). Only the *model* consultation is bounded: `conflicts[:max_conflicts]`
in rank order, minus whatever the rung already settled, the value coming from
`reconciler_max_conflicts` in `core/config.py`, defaulting to **3**, wired at
`app/composition.py` and read nowhere in `memory/ingest.py`.

**So the protection that exists today is exact where a string comparison can settle
it, and absent everywhere else.** A member past the bound that restates the proposal
*verbatim* is labelled `RESTATES` at any rank and is spared. A member past the bound
that the certain rung could not settle — a paraphrase, a near-duplicate, a distinct
fact on the same topic, a genuine contradiction — carries no relation at all, and
`_retirement_set` sweeps it in, because the lookup returns nothing and nothing is not
in `_UNRETIRABLE_RELATIONS`. That is the residue `agrees` was never able to judge and
is precisely the population ADR-0159 §3 sends to a model, which is why the bound on
that call is the thing deciding what survives.

**ADR-0159 §5 protects a member the writer holds a relation for. The bound decides
how many members get the only relation a model can supply. The two were never
connected.**

### What the audit found

#1294's supersede audit read all 56 supersede events of the Step B replay against
their source content, and #1302 records the anatomy. The figures below are that
issue's, cited as its record; the replay artifacts live in the bench clone and are
not read here.

- 56 `SUPERSEDE` decisions retired **146 records** — 2.6 per decision.
- The verified worst case (conv-50) offered **13** members. Three were labelled: one
  `ADDS`, protected and kept, and two `CONTRADICTS`. **Twelve were retired, ten of
  them never labelled at all** — including 'performed on stage 2 Aug', 'met artists
  in Boston 3 Oct' and 'touring with Frank Ocean', which no reading calls
  contradicted. They were in the set by similarity and past the bound.
- The bound explains **100%** of the replay's 2,522 unlabelled relations: every
  crossing offering three or fewer labelled fully, and all residue sits in the 657
  crossings offering more than three.
- The offered-size distribution: 1,268 crossings offered 1–4, 382 offered 5–9, 80
  offered 10–14, and 23 offered fifteen or more.

**This refutes the reasoning ADR-0159 §3 gave for the number**, which is repeated
verbatim in `core/config.py`: *"Three is where the measured distribution puts the
records a proposal could plausibly restate or contradict, and a fourth is nearly
always a topical neighbour."* On this corpus a fourth member is ordinary — 657 of
1,753 crossings reach one — and calling it a topical neighbour is not a reason to
destroy it. ADR-0159 §12 anticipated exactly this and left the question open:
*"Three and 0.75 are the ratified starting values … a measurement question this ADR
deliberately does not [decide]"*. The measurement has since been made, and dense
conflict sets are what ADR-0162 makes the expected shape rather than an outlier.

### What the A/B measured

#1302 also records a controlled replay: the identical LoCoMo proposal stream, run
twice, `reconciler_max_conflicts` at 3 and at 15, everything else equal.

| | bound 3 | bound 15 |
|---|---|---|
| records retired by supersede | 146 | **73** |
| supersede decisions | 56 | 58 |
| retired per decision | 2.6 | **1.26** |
| relations unlabelled | 2,522 (39.5%) | **196 (2.9%)** |
| `adds` labels | 3,283 | 6,023 |
| `restates` | 509 | 549 |
| `contradicts` | 66 | **81** |
| decisions accept / reinforce | 2,043 / 447 | 2,034 / 454 |
| final beliefs (shrink) | 2,099 (−17.6%) | 2,092 (−17.8%) |

Four readings matter, and the fourth is the one that decides §3 below.

**Retirements halve while supersede decisions stay flat.** The same contradictions
are acted on — 56 rulings against 58 — but each ruling retires 1.26 records instead
of 2.6. The collateral, not the judgement, is what the bound was controlling.

**Raising the bound extends protection; it does not inflate supersession.**
`contradicts` grows only 66 → 81 while `adds` nearly doubles. Asked about more
candidates, the model finds mostly distinct facts.

**The store is not being kept larger by mistake.** Final shrinkage is −17.8% against
−17.6%: the extra survivors are supersede-spared and the extra folds near-identical.

**Fifteen real contradictions live beyond a bound of three.** That is the 66 → 81
delta, and it is what rules out narrowing the widening on its own. Under bound 3
with §2's narrowing and nothing else, those fifteen are never labelled, so they are
never retired, and the stale beliefs they name stay live — which is the honesty gap
#244 reported and ADR-0079 §1 was written to close.

### Why the bound is the wrong thing to be deciding this

`reconciler_max_conflicts` is a **cost control**. `core/config.py` says so — *"It is
**not** a second `conflict_limit`: that ceiling is 100 and is a circuit breaker on a
runaway store, nowhere near a cost bound, where this one is exactly that"* — and
ADR-0159 §3 puts it there for the reason `observation_max_proposals` is there, as a
knob an operator tunes against their own corpus.

An operator tuning a spend knob downward is not making a decision about destruction,
and today they are. At 1 the widening is unprotected for every member but the
first; at 100 §5's protection reaches every member the store surfaced. No default
value closes that, because the defect is the coupling and not the number. A default
fixes the magnitude for the deployment that leaves it alone; a rule fixes the class
for every deployment.

That is the whole shape of this ADR. §1 fixes the magnitude, with the measurement
that was owed. §2 fixes the class, by stating as a rule what §1 achieves only as a
statistic — and on a fully labelled crossing the two are the same behaviour, which
is the best evidence available that they are one fix approached from two sides.

## Decision

### 1. The labelling bound's default is fifteen

> **Normative.** `reconciler_max_conflicts` defaults to **15**.

Everything else ADR-0159 §3 says about the bound stands, and stands unread by this
ADR: it is positive, it is applied over the conflict set in rank order, it bounds the
**model consultation** and not the unconditional `agrees` rung above it, a label the
reply carries for a member beyond it is discarded by the reconciler, and one ingest
still makes at most one model request covering every member consulted.

**Fifteen, because fifteen is what was measured.** It is the value the A/B ran on
the identical proposal stream, and it labels every crossing the distribution puts
below fifteen — 1,730 of the replay's 1,753. #1302 observes that a bound of roughly
25 would zero the residual 196 unlabelled relations; that is an extrapolation from a
distribution rather than a measurement, and §7 leaves it where ADR-0159 §12 left
three: to a run. Under §2 the residual also stops being a destruction question and
becomes a recall one, which is what makes waiting for that run cheap.

**What it costs is tokens, not calls.** ADR-0159 §3's one-request clause is per
ingest and not per member, so a larger bound grows the size of one prompt and never
the number of prompts; the A/B records zero additional model calls and comparable
wall time across the two runs. The reconciler's request is inside
`MemoryIngestor.ingest`'s lock (ADR-0159 §6), so a longer request is a longer lock
hold — the measured runs do not separate on it, and §6's three bounds on what that
costs are unchanged: one request per ingest, most ingests make none, and the
population that does make one arrives from a scheduled job rather than a turn.

**It changes what one prompt carries, and not what it may do with it.** Five times
as much stored content reaches one reconciler request. ADR-0098's rule is unchanged
and is what governs it: the content is data, never instruction, and this ADR widens
the amount rather than the class.

**A deployment's value is already legible in the measures.** `reconciler_max_conflicts`
is on ADR-0119 §9's allowlist and is stamped in the `CONFIGURATION` trace at every
hub startup (`service/configuration.py`), so a report partitioned by ADR-0120 §8
does not state one figure across decisions made under different bounds. Raising the
default without that stamp would have been the ADR-0141 §10 defect one accumulation
over; with it, the raise creates a datable boundary for free.

### 2. A supersession sweeps in only what the writer labelled a contradiction

> **Normative.** Where a writer holds a `CONTRADICTS` relation for at least one
> member of the conflict set the policy ruled on, a `SUPERSEDE` retires the record
> `target_id` names and, beyond it, only those other members of that set it holds a
> `CONTRADICTS` relation for. A member it holds **no** relation for is left live,
> whatever its source.

> **Normative.** The clause above withholds from the retirement set only what **this
> ADR** withholds. It does not reach ADR-0078 §5b: a `USER_ASSERTED` member that
> section's confirmation covers is retired exactly as it requires and on exactly the
> footing it had before this ADR, and §2 adds no condition to that retirement and
> removes none.

> **Normative.** Where a writer holds a `CONTRADICTS` relation for **no** member of
> that set, ADR-0079 §3's obligation binds exactly as it stands, narrowed by
> ADR-0159 §5 and by nothing in this ADR.

> **Normative.** A conflict the writer holds a `RESTATES` or `ADDS` relation for is
> still never retired, by any ruling, and a `SUPERSEDE` naming it is still refused
> rather than performed (ADR-0159 §5). This ADR narrows the widening further and
> reverses no part of it: every record ADR-0159 §5 spares, this spares.

> **Normative.** The clauses above are enforced at the writer, from the writer's own
> relations, never read off the ruling — ADR-0038 §2a's shape, at the boundary that
> performs the write. The canonical `MemoryWriter` fake in `ai_assistant.testing`
> carries the same narrowing, duplicated rather than imported (golden rule 1), and
> the shared `MemoryWriter` conformance suite pins it.

> **Normative.** This ADR opens no exception to `_refuse_unsafe_fold`'s clause 1,
> widens neither the reinforce-safe class nor the retirement class, and adds no
> source to either. Every write it permits is one the writer floor already permitted,
> and it permits strictly fewer.

**The predicate is stated over the relations the writer holds, and over nothing
else.** That is not a stylistic choice; it is what makes the rule representable at
the boundary ADR-0038 §2a puts it at. The writer already holds the mapping — it
determined it, it passes a read-only copy of it to `MemoryPolicy.decide`, and it
rules the retirement set from its own unhanded one (ADR-0159 §8). No new input
crosses any seam, `_retirement_set`'s signature does not grow, and §4 below states
what this deliberately does not reach for.

**The discriminator is "does this crossing carry a labelled contradiction", and the
three arms it separates are the three that exist.** A `SUPERSEDE` reaches the
widening by one of three routes, and the clauses above sort them correctly by
construction:

- **The reconciled arm** (ADR-0159 §4(b)). `DefaultMemoryPolicy` rules `SUPERSEDE`
  here only at a member labelled `CONTRADICTS`, so the crossing always carries one
  and the first clause always governs. This is the arm #1302 is about, and it is the
  arm where the narrowing bites.
- **The asserted arm** (ADR-0038, ADR-0092 §4, #244). A `USER_ASSERTED` proposal
  never reaches a reconciler at all — the invocation condition in `memory/ingest.py`
  excludes it, and excludes any crossing holding a `USER_ASSERTED` member — so the
  writer holds no relations, no member is labelled `CONTRADICTS`, and the third
  clause hands the whole set to ADR-0079 §3 unchanged. **This is the case a naive
  narrowing would have destroyed**, and it is the reason the rule is stated the way
  it is rather than as "retire only labelled contradictions". A user correcting a
  belief still retires every stale sibling it is shown, exactly as ADR-0079 §1 and
  #313/#314 require. Nothing about the asserted path changes.
- **The degraded arm** (ADR-0159 §6). With no reconciler injected, or with one whose
  answer failed, the writer holds at most the certain rung's `RESTATES` labels. The
  certain rung can never produce `CONTRADICTS`, so the third clause governs and
  §6's ratified floor behaves exactly as it does today. Sparing on the strength of a
  test that was never run would have been the wrong direction, and the rule does not.

**The disjointness the second and third clauses rest on is a property of the
invocation condition, not a prediction about a policy.** A crossing carrying a
`CONTRADICTS` relation is one the writer reconciled, and a crossing the writer
reconciled holds no `USER_ASSERTED` member — so the confirmation batch and the
narrowing cannot meet on one crossing. The second clause is stated anyway, because a
contract that leaves it to inference is a contract ADR-0078 §5b can be read out of.

**The second clause is scoped to this ADR's own withholding, and that scoping is
load-bearing rather than cautious.** An earlier draft said a confirmation-covered
member is retired "whatever relations the writer holds", which the architecture
review found unsatisfiable against the fourth clause below: a writer holding `ADDS`
for such a member was commanded to retire it and to refuse. The finding is correct,
and the right response is to stop restating a tension this ADR did not create. That
tension is already in the ratified corpus — ADR-0159 §5 says a `RESTATES`/`ADDS`
member is "never retired, by any ruling, at any writer", and ADR-0078 §5b says every
confirmed asserted conflict is retired in one batch — and it is unreachable there for
the same structural reason it is unreachable here. Ruling its precedence would mean
partially superseding ADR-0159 §5's *first* clause, on no evidence, for a case no
conforming writer can construct. §7 records it as expressly not decided and #1326
carries it.

**The same asymmetry ADR-0159 §5 relies on is what makes this safe against an
untrusted label.** A relation is a model-derived input, and §5's last paragraph is
the argument for admitting one: the labels *only ever narrow what happens*, so a
safety property they can tighten needs no verification at the boundary. That holds
here in both directions. A reconciler that under-reports `CONTRADICTS` causes
records to be spared, which is the conservative direction. A reconciler that
volunteers `CONTRADICTS` for a member ADR-0159 §3 required it to discard can now
cause that member's retirement — but the writer would have retired it anyway today,
unlabelled, so the narrowing takes destruction away from that reconciler and never
grants it. §4 records what it does do to #1225's stakes.

**Worked against the audit's own worst case.** conv-50 offered 13, of which the
model was asked about 3 and labelled one `ADDS` and two `CONTRADICTS`. Today: 12
records retired, 10 never labelled. Under §2 alone: the ruling names one of the two
`CONTRADICTS` members, the retirement set adds the other, the `ADDS` member is
spared by ADR-0159 §5 as it already is, and the ten unlabelled members are left
live — **2 retired instead of 12**. Under §1 alone: all 13 are labelled, the
measured mix says most become `adds`, and the retirement set is whatever came back
`CONTRADICTS`. The two remedies converge on the same records, which is the point —
§1 gets there by making the labelling complete, and §2 gets there by not depending
on it.

**The trace stays honest with no change.** ADR-0119 §8 wants the ids that were
actually closed rather than the one that was named, and the applier already reports
the retirement set it built. A shorter set is reported as a shorter set. No metric
key, trace field or qualifier is added, moved or retired by this ADR.

### 3. The raise is a precondition of the narrowing, never the other way round

> **Normative.** No change narrows the widening under §2 unless §1's default already
> stands in `core/config.py` — in the same change, or in an earlier merged one.

**Narrowing under a bound of three would trade a destruction defect for a recall
defect, and the corpus already ruled that trade the wrong way.** The A/B measures
fifteen genuine contradictions living beyond rank three. Under §2 with the bound
left at three, none of them is labelled, so none of them is retired, and fifteen
beliefs the assistant has been told are false stay live on the same topic as their
correction. That is #244's honesty gap, which ADR-0079 §1 answers with *"a
correction resolves every conflict it is shown, or it does not land"*. §2 changes
the extension of "shown" — a member the writer has no relation for was not shown to
the correction — and §1 is what keeps that extension close to the truth.

Read the other way: §1 without §2 leaves a spend knob governing destruction, and §2
without §1 leaves real contradictions standing. The ordering clause exists because
only one of those two orderings is safe to be halfway through.

### 4. What this does not reach for: no consulted set, no new seam

> **Normative.** This ADR carries no consulted set across the `memory`-internal
> reconciler seam, adds no field to the reconciler's outcome report, and changes no
> part of `ConflictReconciler`. §2's predicate reads only relations the writer
> already holds, so ADR-0164 §6 and §9's refusal stands unmoved.

**This is the design constraint the section exists to record, because the obvious
remedy fails it.** #1302's second candidate direction — retire only labelled
contradictions "plus certain-rung records" — reads naturally as a rule about *why* a
member is unlabelled: beyond the bound, or never reconciled. A writer cannot tell
those apart. `_relations_for`'s own docstring says so — *"a **beyond-bound** entry is
read like any other: this writer holds no consulted set to except it with"* — and
telling them apart means carrying which members a request covered, which ADR-0164 §6
and §9 decline in terms and #1225 records as an open question with three unruled
resolutions. §2 sidesteps it by asking a question the writer can answer from what it
holds: not *why is this member unlabelled*, but *did this crossing produce a labelled
contradiction at all*.

**It raises #1225's stakes and answers none of its question.** #1225 is that
ADR-0159 §3's bound is unenforced at the writer: a non-conforming reconciler's
label for a beyond-bound member installs, and `DefaultMemoryPolicy` will select a
`SUPERSEDE` target on it. After §2 such a label additionally decides *membership of
the retirement set*, where today an unlabelled beyond-bound member is swept in
regardless. So the harm class does not grow — the same record is destroyed either
way — but the label becomes load-bearing in a second place, and #1225's cheapest
resolution (its option 2: the reconciler applies its own bound to what it returns,
tested against ADR-0159 §3, with no seam change and no writer change) is worth more
after this ADR than before it. §1 also shrinks its population: at a bound of fifteen
the beyond-bound region is 23 crossings of 1,753 rather than 657.

### 5. What the implementing lane owes

> **Normative.** The implementation is **one lane**: `core/config.py`,
> `core/protocols.py`, `memory`, `ai_assistant.testing`, the shared conformance
> suite and their tests, ratified and merged behind this ADR.

ADR-0137 §1 asks whether the slice puts substantial new machinery into at most one
subsystem. It puts no new machinery anywhere: one integer moves, one predicate gains
a condition, and its mirror gains the same one. The `core` delta is the contract
sentence that predicate is written at plus one default; the fake's mirroring is
adaptation, which ADR-0137 §1 excludes from the bound.

The lane owes:

- `core/config.py` — the default of `reconciler_max_conflicts`, and the block
  comment above it, whose stated reasoning for three (§"Three is where the measured
  distribution puts …") is what the audit refutes and must not be left standing
  beside a different number.
- `memory/_reconciler.py` — the module's own default constant, which must not
  disagree with `Settings`.
- `memory/ingest.py` — `_retirement_set`'s predicate under §2, and the docstring
  paragraph stating why.
- `testing/writer.py` — the same predicate on the canonical fake, duplicated rather
  than imported.
- `core/protocols.py` — `MemoryWriter.ingest`'s docstring paragraph on the
  ruled-on-set retirement, which today states ADR-0079 §3's obligation as narrowed by
  ADR-0159 §5 alone.
- The shared `MemoryWriter` conformance suite — §2's three arms, each of which fails
  on a writer that implements only the others:
  - a crossing carrying one `CONTRADICTS` member and one **unlabelled** supersedable
    member: the first is retired, the second is left live;
  - a crossing carrying **no** relations at all and several supersedable members:
    every one of them is retired, which is ADR-0079 §3 unchanged and is the test that
    fails on a writer that narrowed unconditionally;
  - a crossing carrying only certain-rung `RESTATES` labels beside unlabelled
    supersedable members: every unlabelled one is retired, which is ADR-0159 §6's
    floor unchanged.
- Tests pinning the pilot's own shape by its measured values: the conv-50 shape — a
  crossing offering more members than the ruling labels, with one `ADDS`, two
  `CONTRADICTS` and the rest unlabelled — retires two records and leaves eleven live;
  and the asserted-path shape — a `USER_ASSERTED` proposal against several
  `OBSERVED` conflicts, no reconciler consulted — retires all of them, so the
  regression §2's third clause exists to prevent has a test that names it.
- A test pinning that the default reaching `ConflictReconciler.reconcile` is the one
  `Settings` carries, since three sites hold that number today.

**No `core/types.py` change, no Protocol method, parameter or signature change, no
`MemoryPolicy` change, and no `Settings` field added or removed.** `MemoryDecision`
still carries exactly one `target_id`; the widening stays applier-side, which is what
ADR-0050 §1 and #244 bought by putting it there. `DefaultMemoryPolicy`'s arms are
untouched in both `memory/policy.py` seams — §2 changes what a `SUPERSEDE` retires
and never which member a policy names.

**Not this lane's, and not to be absorbed into it:** #1225's enforcement question,
#1206's remaining half (`reconciler_model` is still not on ADR-0119 §9's allowlist,
though `reconciler_max_conflicts` now is), and #1303's arrival-order supersession.
Each is its own issue and stays one.

### 6. What this records against earlier ADRs, under ADR-0082 §1

ADR-0082 §1's test, applied to each: would a reader holding only the earlier ADR now
act differently, or read one of its clauses more widely than it now holds?

**A record is owed on three.**

- **ADR-0159 §3 and §5 — partially superseded**, in the two scopes the header names.
  §3's default is a number a reader configures, so moving it fails the test outright
  (ADR-0070 §1). §5's second clause states that ADR-0079 §3's obligation "is narrowed
  by the clause above and is otherwise unchanged"; after §2 it is narrowed by a second
  clause as well, so a reader holding only §5 would build a writer that retires
  records §2 forbids. ADR-0159's `Status` already carries a leading `Partially
  superseded by` token naming ADR-0161; a second pair is added and the first is not
  dropped (ADR-0070 §4), with the record in the dated note.
- **ADR-0079 §3 — partially superseded**, in §2's scope. §3 promoted the full-set
  retirement to a `MemoryWriter` conformance obligation stating the set as "the named
  `target`, plus every other conflict in the set the policy ruled on whose source is
  supersedable". §2 narrows that set again, on a ground §3's sentence has no term
  for — exactly the reasoning ADR-0159 §11 gave for its own record on the same
  section, one narrowing further along. ADR-0079's `Status` already carries the
  leading token naming ADR-0159; a second pair is added and the first is not dropped.

  **The intensional statement that saved §3 from ADR-0092 does not save it here,
  for the second time.** ADR-0050's 2026-08-02 note ruled that §3 needed no record of
  ADR-0092's widening because §3 names "whose source is supersedable" rather than a
  list, so widening the class left its sentence true verbatim. That is right, and it
  is right for the same reason ADR-0159 §11 gave: §2 does not change which *sources*
  are supersedable. It withholds retirement from a member whose source **is**
  supersedable, which §3's sentence cannot express.
- **ADR-0050 §1 — partially superseded**, in the same scope. §1 is where the set is
  defined, on the premise that "every entry in the conflict set the detector surfaced
  is a same-kind, at-or-above-threshold contradiction of the proposal". #1188
  measured that premise false at the ratified threshold and ADR-0159 §5 acted on the
  measurement for the members it had relations for; #1302 measures that the members
  it had no relations for are the majority, and §2 acts on that. ADR-0050's `Status`
  already carries the leading token with several pairs; one more is added and none is
  dropped, with the record in the note.

**No record is owed on the rest**, and each is named because a reader may expect
otherwise.

- **ADR-0079 §1.** "A correction resolves every conflict it is shown, or it does not
  land" stays true, on the reading ADR-0159 §11 already gave it: what moves is the
  extension of "conflict shown", not the rule. §1's own honesty claim — "not 'every
  conflict that exists on the topic'" — is the same claim made more accurately again,
  and §1 above is what keeps the gap between the two small enough to say so.
- **ADR-0092 §4.** `EXTERNAL` is still in the retirement class, in the policy's
  ruling and in the applier's widening, and the class is still an enumerated
  allow-list rather than "not `USER_ASSERTED`" (ADR-0038 §2a). §2 adds a relation-side
  condition and touches no member of the class — the same structure ADR-0159 §5
  introduced, which ADR-0159 §11 likewise recorded nothing against ADR-0092 for.
- **ADR-0045 §5 and ADR-0078 §5b.** Clause 1 is untouched and gains no exception.
  `USER_ASSERTED` stays out of the widening save by §5b's confirmation exception,
  which §2's second clause states in terms rather than leaving to inference, and which
  cannot collide with the narrowing at all because a reconciled crossing holds no
  `USER_ASSERTED` member.
- **ADR-0159 §4, §6 and §8.** §4's arms are untouched — a policy names the same target
  on the same grounds. §6's degraded floor behaves identically, by §2's third clause.
  §8's mapping clauses are untouched: the writer still hands `decide` a read-only view
  over a copy and still rules the retirement set from its own unhanded mapping.
  ADR-0161's partial supersession of §4 and §6 is unaffected in either direction.
- **ADR-0121 §1.** `agrees` is unchanged, reads no model value, and stays the
  reconciler's unconditional first rung. §2 reads its output and changes neither its
  definition nor what it may read.
- **ADR-0038 §2 and §2a.** §2's "topical similarity is not contradiction" is what §2
  here finishes applying to the retirement set; §2a's enforced-at-the-writer shape is
  honoured rather than excepted.
- **ADR-0119 §9 and ADR-0120 §8.** The allowlist's roster is unchanged and the stamp
  already carries `reconciler_max_conflicts`, so a default change creates a datable
  boundary with no measurement work owed. This ADR neither adds to the roster nor
  rules on #1206's remaining half.
- **ADR-0164 §3, §6 and §9.** The outcome vocabulary, the write trace's rung split and
  the declined consulted set are all untouched; §4 above states that as a clause
  rather than leaving it implied.
- **ADR-0098.** Ingested content stays data and never instruction. §1 changes how much
  of it one prompt carries and nothing about what the prompt may do with it.
- **ADR-0156 §2 and ADR-0159 §3's temporal clause.** Unchanged, and made
  load-bearing for more members: at fifteen, more of the crossing is judged with its
  event-time anchors in view, which is the clause working on a larger population.
- **ADR-0077 §2.** The observer's selectivity bar and `observation_max_proposals` are
  untouched. No producer-side bound moves.

### 7. What this ADR does not decide

- **Whether the bound should go higher than fifteen.** #1302 observes that roughly 25
  would zero the replay's residual 196 unlabelled relations. That is read off a
  distribution rather than measured, and §2 changes what the residual costs: an
  unlabelled member is now spared rather than swept, so the residual is a **recall**
  question — a real contradiction left live — and no longer a destruction one.
  Moving it again is the same kind of question ADR-0159 §12 left open and takes the
  same kind of answer: a replay at the higher bound showing retirements down,
  `contradicts` approximately flat, no additional model calls and unchanged store
  shrinkage. Nothing here forbids an operator from running higher in the meantime.
- **An upper bound on the setting.** `reconciler_max_conflicts` carries `ge=1` and no
  ceiling. A value above `conflict_limit` is inert rather than harmful, since the
  reconciler's bound is applied to a set that ceiling already caps. Whether the field
  should carry an `le` is a validation question with no measurement behind it, and
  it is adjacent to #1225 rather than to this.
- **#1326 — the precedence between ADR-0159 §5's absolute exclusion and ADR-0078 §5b's
  confirmed batch. Left open, and deliberately not restated.** §5 says a `RESTATES` or
  `ADDS` member is "never retired, by any ruling, at any writer"; ADR-0078 §5b says
  every confirmed asserted conflict is retired in one batch. A writer holding `ADDS`
  for a confirmation-covered member could satisfy neither. It is structurally
  unreachable — ADR-0159 §2's invocation condition means a writer holds no relation for
  a `USER_ASSERTED` member at all — and it predates this ADR, which changes nothing
  about either rule. §2's second clause is scoped to this ADR's own withholding
  precisely so that it does not promote the tension into a stated one. Ruling it means
  partially superseding ADR-0159 §5's first clause on no evidence, for a case no
  conforming writer can construct, and that is a decision to make on its own.
- **#1325 — ADR-0159 §3's own internal contradiction about what the bound reaches.
  Left open, and untouched.** §3's second clause ends "members beyond that bound are
  left unlabelled", which read literally denies its first clause's *unconditional*
  `agrees` rung. The code resolves it in clause 1's favour — the certain rung ranges
  over the whole set and only the model consultation is bounded — and so does clause 3,
  which discards a volunteered label for a member "the `agrees` rung already labelled".
  §1 restates the bound as a bound on the consultation, which is the reading that was
  always ratified; whether ADR-0159's own sentence is worth an ADR-0070 §1 amendment is
  a corpus judgement this ADR does not make. Filed because the false reading is a live
  trap: it reached this ADR's own first draft and was caught by review.
- **#1225 — the bound's ceiling unenforced at the writer. Left open, and its priority
  raised.** §4 states what changes about its stakes and why §2 does not answer it.
- **#1206's remaining half.** `reconciler_model` still meets ADR-0119 §9's stated
  roster test and is still not on the list. That is #1206's, needs no ADR by its own
  argument, and is not this lane's to absorb.
- **#1303 — supersede direction follows arrival order, not event time. Left open, and
  its blast radius reduced.** A supersession pointed the wrong way retires fewer
  records after §2, which makes the failure cheaper and not less wrong. The remedy
  #1303 names — prompting the reconciler to prefer event-time ordering, or refusing a
  `SUPERSEDE` whose proposal predates its target — is a rule about *direction* and
  belongs with whoever writes it.
- **Whether an unlabelled member should be labelled at all.** §2 spares a member the
  reconciler never judged; it does not schedule a second pass to judge it, and
  consolidation remains where ADR-0159 §12 and #871 put the collapsing of
  near-identical records.
- **The reconciler's prompt.** ADR-0159 §12 leaves its wording to the implementing
  lane and this ADR does not take it back, including how a fifteen-member set is
  rendered into one request.

## Consequences

**A correction stops destroying facts it was never shown.** That is the whole
purpose, and #1302's conv-50 case is the measure of it: two records retired where
twelve are today, with the ten distinct events left live.

**A spend knob stops governing destruction.** After §2, lowering
`reconciler_max_conflicts` costs *recall* — contradictions that go unlabelled and
therefore unretired — and no longer costs records. That is a defensible thing for an
operator to trade against cost, where the current coupling is not.

**One prompt gets bigger.** Five times as many conflict-set members reach one
reconciler request at the default, inside `MemoryIngestor.ingest`'s lock. The A/B
measures no additional calls and comparable wall time, and ADR-0159 §6's bounds on
what a reconciler costs an ingest are unchanged, but a deployment with a small
context budget or an expensive route has a knob to turn and now knows what turning it
down buys and costs.

**The `MemoryWriter` contract gets one more condition, and the conformance suite one
more axis.** A writer must now hold relations to know how far its own supersession
reaches — which it already did after ADR-0159 §5 — and must additionally distinguish
a crossing that produced a labelled contradiction from one that did not. A writer
that determines no relations at all conforms unchanged, which keeps the seam
implementable without a model.

**The rule is harder to state than the one it replaces**, and that is the honest
cost. "A supersession retires the whole ruled-on set" is one sentence; §2 is three
clauses and an exception. The three arms it separates are real, they behave
differently, and the alternative that collapses them is the one that breaks user
corrections — so the complexity is in the domain rather than in the wording.

**What would trigger revisiting this.** A run at a higher bound with the shape §7
names. A measurement showing that the records §2 now spares include stale beliefs
being retrieved and answered from — which is the recall cost made visible, and which
the retrieval measures can see where the ingestion measures cannot. Or #1225 being
resolved in a way that gives the writer a consulted set after all, which would make a
sharper rule available than the one §2 could reach for.

## Alternatives considered

**Raise the default and stop there.** Rejected. It fixes the magnitude for a
deployment that leaves the default alone and fixes nothing for one that does not: at
any bound, an operator lowering it re-arms wholesale retirement silently, and the
2.9% residual is still destruction rather than recall. #1302's own framing — that
the widening's assumption is "exactly wrong for the unlabelled majority" — is a
statement about a class, and a default value cannot answer one.

**Narrow the widening and stop there.** Rejected on the A/B's own numbers: fifteen
genuine contradictions live beyond rank three, and under a bound of three the
narrowing leaves every one of them standing beside its correction. §3 makes the
ordering normative for this reason.

**Raise to 25 now, zeroing the residual.** Rejected as unmeasured. §7 states what
would settle it and why waiting is cheap once §2 is in place.

**Apply the bound at the writer — retire only the first `reconciler_max_conflicts`
members.** Rejected. It is representable, and it is wrong on the arm that matters
most: the asserted path never runs a reconciler and never applied a bound, so a
spend knob would truncate a *user's own correction* to its first three siblings.
That is ADR-0079 §1 defeated by a cost control, which is a worse version of the
defect being fixed.

**Carry the consulted set across the reconciler seam** (#1225's third resolution).
Rejected as unnecessary here and refused elsewhere. It would let the writer say
precisely why a member is unlabelled, and ADR-0164 §6 and §9 decline the membership
in terms. §2 needs a coarser fact the writer already holds, so this ADR does not
reopen a boundary two ADRs draw deliberately.

**Remove the bound and label the whole conflict set.** Rejected. `conflict_limit` is
100 and is a circuit breaker rather than a cost bound, so the request's size would
become a property of how noisy the store is, inside the ingest lock, with a
correspondingly larger untrusted payload in one prompt. ADR-0159 §3 put a cost bound
there deliberately; this ADR moves its value and keeps it a cost bound.

**Amend ADR-0159 §3 and §5 in place.** Refused. ADR-0070 §1's test is what a reader
would act on, and a reader acting on either clause would ship a different default and
build a different writer. Both changes are decisions, so both take a superseding ADR
however small the edit.
