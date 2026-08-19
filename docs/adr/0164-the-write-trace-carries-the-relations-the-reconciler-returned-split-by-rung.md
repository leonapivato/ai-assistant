# 164. The write trace carries the relations the reconciler returned, split by rung

- Status: Accepted
- Date: 2026-08-19
- **Note (2026-08-19): ratified, on the second flip.** `Proposed` → `Accepted` on the
  content this ADR merges with, after **adversarial** — the required set, which §7
  argues from §2's no-contract-surface finding — returned a non-blocking verdict on one
  tree and again on the flipped tree. `just ship` posts the terminal verdict and the
  aggregate to PR #1217; the round count and the churn ratio are taken from that comment
  rather than restated here, so this note cannot disagree with it.

  **This ADR was flipped once before and returned to `Proposed`.** A fresh reviewer
  session found three defects on the first flipped tree, so the status went back and the
  sequence re-entered at step 1 (§7). The loop that followed ran under three successive
  holders on ADR-0138 §1's handoff rule; what each round bought is recorded in §7 and in
  `Alternatives considered`, where every refused direction is answerable without this
  PR's history.

## Context

### ADR-0159 changed the fold rule and left its effect unreadable

ADR-0159 replaced a fold that rested on similarity with one that rests on a
labelled relation. Its §9 predicted the shape of the move: `decisions_reinforce`
falls, `decisions_accept` rises by nearly the whole difference, and
`decisions_supersede` "becomes non-zero on the observed path for the first time".

Pilot-4 (#1029) then ran on a tree carrying it and reported 1,057 LoCoMo
proposals ruling 1,051 `ACCEPT`, 6 `REINFORCE` and **0** `SUPERSEDE`. Two
readings fit that observation exactly and they call for opposite responses. Either
the reconciler labelled a member `CONTRADICTS` and ADR-0159 §4's purity conditions
refused the supersession that would have followed — in which case the guards are
doing their work, or doing too much of it — or the reconciler never returned
`CONTRADICTS` at all, in which case the prompt, the bound or the temporal clause is
where the attention belongs. #1209 is the request to be able to tell them apart.

Nothing in the stream distinguishes them. A `MEMORY_WRITE` trace carries the six
`decisions_*` counts, which are what the policy *ruled*; the relation is what the
policy was *told*, and it is recorded nowhere. It is not recoverable after the
fact either: a relation is a statement about a pair of records made in the course
of one ingest, and no store row holds it. When the crossing ends it is gone.

### §12 reserved this, and named what the reservation was about

ADR-0159 §12 declined to add it, in terms:

> **A relation in the trace stream.** §9 adds no metric key and no trace field.
> Whether the relation distribution is worth emitting is a decision about what the
> stream is for, and naming it properly is its own ruling — the same call ADR-0121
> §7 made about a policy-change marker.

ADR-0161 §8 re-examined that clause and left it standing — "§9 adds no metric key
and this ADR adds none" — so the reservation is live text and not a stale one. This
ADR is the ruling it reserved. A lane briefed to add the keys without one stopped at
pre-flight on exactly this ground, and the analysis it left on #1209 is where this
document starts.

### What the tree can see, and what it cannot

Three facts about `src/ai_assistant/memory/ingest.py` decide the shape below, and
each was checked against the tree rather than assumed.

**Two rungs are merged into one mapping.** `MemoryIngestor._relations_for` computes
ADR-0121 §1's certain predicate itself — `own`, which by construction can only ever
hold `RESTATES` — and then overlays the reconciler's determinations, returning
`labelled | own`. A count taken over that mapping cannot say whether the *model*
ever answered anything, because every `RESTATES` in it may have come from a string
comparison that costs nothing and asks nobody. #1209's question is precisely about
the paid rung, so the merged count is the one shape that cannot answer it.

**The mapping a policy sees is not the mapping the writer holds.** Where no
reconciler is injected, `MemoryIngestor` passes `relations=None` to
`MemoryPolicy.decide` while continuing to hold `own` for its own retirement-set
exclusion. ADR-0159 §8 ratifies that reading of `None` — "no reconciler ran at all
(§2's condition excluded this ingest, or none is injected)" — and ADR-0161 §4 rules
the degraded path on it, keying clause (ii) on `agrees` "rather than on a `RESTATES`
label" for that exact reason. So the policy's view is lossy by construction in a
deployment ADR-0159 §6 ratifies, quite apart from whether a policy can be trusted
with it.

**The bound is invisible from the stream.** `reconciler_max_conflicts` is a
`Settings` field, and `src/ai_assistant/service/configuration.py` does not name it:
its allowlist carries the job cadences, the observation controls, the retention
horizons, the embedding deadline, ADR-0119 §9's cardinality controls and ADR-0141's
three notification tunings, and nothing of the reconciler's. #1205 states this
sharply — a deployment upgraded with unchanged operator settings "emits
configuration traces with the same existing allowlisted metrics — `reconciler_*` is
not stamped". So a reader of the stream cannot tell a member left unlabelled
because it fell beyond the bound from one left unlabelled because the model
declined to label it, and cannot see the bound move.

### Why this is a ruling and not a lane's discretion

ADR-0119 leaves a lane real latitude here: §2 makes a metric key "a literal constant
written in the emitting module", §3 closes the four enumerations and does not close
the key vocabulary, and §8 calls the emitting-seam list "the floor rather than the
ceiling". Nothing mechanical would have stopped the keys being added. What made
§12 reserve it anyway is that the useful vocabulary is not the obvious one: the
obvious count — one key per `ConflictRelation` member over the mapping the writer
returns — is the count that answers nothing, for the first reason above. Choosing
against it is a decision about what the stream is for, which is the sentence §12
actually wrote.

## Decision

### 1. The relation distribution is emitted, and the write trace is where it belongs

> **Normative.** A `MEMORY_WRITE` trace carries what the reconciliation step of that
> crossing observed: how many of the crossing's proposals reached it, what state the
> reconciler was in, and how many relations were held, counted by relation and by
> the rung that produced it.

**What the stream is for, answered for this case.** ADR-0119 §1 fixes it: "a trace
is a fact about the system, and a measure is an opinion about the facts". A relation
is a fact about an event at the write seam — determined there, read there, and
discarded there. ADR-0119 §8's own argument for putting decision counts on this
trace applies to it unchanged and more strongly: "Counting corrections from outside
the write path would mean re-deriving them from what the store now holds, which is a
measure of the present rather than a record of an event." A decision count is at
least re-derivable from the store, expensively and approximately. A relation is not
re-derivable at all — no row ever held it — so either this trace carries it or
nothing does.

**And it is worth emitting**, which is §12's other half. ADR-0159 §9 predicts three
figures will move and predicts the direction of each; the pilot then produced a
distribution that fits two incompatible explanations of the same numbers. An
instrument that cannot separate "the reconciler said `CONTRADICTS` and a purity
condition refused the supersession" from "the reconciler never said it" cannot tell
whether ADR-0159 works, and ADR-0159's own Consequences name the reconciler as "a
new place to be wrong" and "the thing to watch in the pilot-4 arm". This is the
watching.

### 2. Metric keys only: no trace field, no enum member, no `core` change

> **Normative.** What this ADR adds to the trace family is **metric keys and
> nothing else**. It adds no field to `EvaluationTrace`; no member to `TraceKind`,
> `TraceOutcome`, `TraceRef`, `TraceRecordSet`, `ConflictRelation` or
> `MemoryDecisionKind`; and it changes no type, field, signature or docstring
> obligation in `src/ai_assistant/core/types.py` or
> `src/ai_assistant/core/protocols.py`. What it changes inside `memory` — the
> reconciler's outcome report (§3) — reaches no contract and no trace of its own.

> **Normative.** Every key this ADR names is a literal constant declared in
> `src/ai_assistant/memory/traces.py` beside the keys already there, and every value
> it carries is a non-negative integer that is not a `bool` — ADR-0120 §2's count
> rule, so one predicate serves both ADRs. No key is composed at runtime, and no
> relation's name reaches a trace as a string.

**Keys rather than a field, because the family has no shape for a relation.**
ADR-0119 §2 admits four string origins and rules that "every non-reference
observation a trace carries is a number or a boolean. There is no free-text field,
no serialised payload and no open-value-type mapping anywhere in the family". A
`ConflictRelation`-valued field would be a fifth field on `EvaluationTrace` carrying
an enum, which §3 fixes as "those §13 sets out and no others" — a `core/types.py`
change, a contract change under golden rule 5, and an ADR-0119 amendment, for an
observation that is a count.

**Counts rather than a per-pair record set, because the crossing is the unit.**
ADR-0119 §5's one-crossing rule makes one `ingest_reading` call one trace, "not one
per resulting `MemoryIngestResult`… the per-reading counts ride as metrics", and §3
types `records` as ids under a closed `TraceRecordSet` key. There is no shape in
which a relation travels attached to the pair it is about without either a new
enumeration member or one trace per pair, and each of those is a larger change than
the question warrants. §6 states what that costs.

**No `core` change is the finding, not the goal.** It was checked rather than
assumed: `ConflictRelation` is already in `core/types.py` and already imported by
`memory`, the keys are the emitting module's under ADR-0119 §2, and the counts are
integers the envelope already carries. Had any of those been otherwise this would be
a contract ADR with an architecture lens; it is not one.

### 3. The vocabulary: ten keys, two units, and the rung named on every label

> **Normative.** Four keys count **proposals** of the crossing. `reconciled` counts
> those for which ADR-0159 §2's invocation condition held, so relations were
> determined. `reconciler_absent` counts those among them ingested by a writer
> holding no reconciler — ADR-0159 §6's floor. `reconciler_failed` counts those among
> them whose model rung did not complete: the reconciler made a request that yielded
> no readable answer, or it was non-conforming and the writer's guard absorbed it.
> `reconciler_unconsulted` counts those among them whose reconciler completed without
> making a model request at all — ADR-0159 §3's other half of the one-request clause,
> whatever left it with nothing to ask about.

> **Normative.** Proposals whose model rung answered are `reconciled` less the three
> keys that qualify it, and no key counts them.

> **Normative.** The three qualifying keys are mutually exclusive — a proposal counts
> under at most one of them — and each counts only proposals `reconciled` counts. A
> proposal ingested by a writer holding no reconciler counts under `reconciler_absent`
> alone and never under `reconciler_unconsulted`, which is a statement about a
> reconciler that ran. So the three sum to at most `reconciled` and the answered count
> is exactly the remainder.

> **Normative.** The reconciler reports which of those outcomes it took, across the
> `memory`-internal seam ADR-0159 §2 keeps inside this subsystem, beside the
> relations it returns.

> **Normative.** The report is read for exactly two purposes: to fill the four proposal
> keys, and to decide whether the model rung's labels are installable under the clause
> below. Nothing else reads it. It reaches a ruling only the way any other determination
> of the relation set does — **through the relations the writer therefore holds**, which
> is the one route ADR-0159 §6 admits ("other than by the relations it therefore does
> not hold"). No ruling, no retirement set and no ingest outcome turns on it by any
> other route, no ruling reads the report itself, and no ingest is ever refused or
> delayed because of it.

> **Normative.** A model-rung label is installed only where the report says the model
> answered. A report of `reconciler_unconsulted` or `reconciler_failed` arriving
> **with** model labels is incoherent: the labels are discarded, those members stay
> unlabelled, and the proposal counts under `reconciler_failed`.

> **Normative.** Where a reconciler ran, its report names **exactly one** of the three
> outcomes it can take: the model answered, `reconciler_failed`, or
> `reconciler_unconsulted`. (`reconciler_absent` is not among them — no reconciler ran,
> so no report was due.) A report that does **not** name exactly one of them — missing
> where one was due, naming none of them, or naming more than one — is itself
> **non-conforming in whole**: the mapping it accompanies installs nothing, every
> member it would have labelled stays unlabelled, and the proposal counts under
> `reconciler_failed`. A report naming more than one is no more usable for carrying a
> valid outcome among them, because nothing here says which of them to read. That is
> the same all-or-nothing shape this section takes for a non-conforming mapping, and it
> is what stops two implementations reporting the same unusable report differently.
> How the report is **represented** across the seam is not decided here: it is
> `memory`-internal, where ADR-0159 §2 keeps it, and a closed type is one way to meet
> this clause rather than a requirement of it.

> **Normative.** Six keys count **pairs** — one proposal of the crossing against one
> member of its resolved conflict set. `relations_offered` counts every pair the
> determination ranged over. `relations_certain_restates` counts those the certain
> predicate labelled. `relations_model_restates`, `relations_model_adds` and
> `relations_model_contradicts` count those a reconciler labelled, one key per
> `ConflictRelation` member. `relations_unlabelled` counts offered pairs that ended
> with no relation at all.

> **Normative.** The five label keys partition `relations_offered`: every offered
> pair is counted under exactly one of them, and their sum equals `relations_offered`.

> **Normative.** A pair the certain predicate labelled is counted under
> `relations_certain_restates` and under no model key, whatever a reconciler
> returned for it. ADR-0159 §3 rules the certain rung unconditional and rules that a
> model-supplied label for a member the rung already labelled is discarded; the
> count records the label that stands.

> **Normative.** What the writer reads is **the mapping a reconciler returns** across
> the `memory`-internal seam, and nothing else. It is not the model's reply to the
> reconciler — the term ADR-0159 §3 uses — which this writer never sees and no clause
> of this ADR is about.

> **Normative.** The writer installs a reconciler's relation for a member only where
> the value **is** a `ConflictRelation` member. A returned mapping supplying any other
> value for a member the writer reads it for is **non-conforming in whole**: no label
> from that mapping installs, every member it would have labelled stays unlabelled,
> and the proposal counts under `reconciler_failed`.

> **Normative.** The members a returned mapping is read for are this crossing's
> resolved conflict set less those the certain rung labelled — the set
> `MemoryIngestor._relations_for` looks up, and nothing wider. An id the mapping
> invented is dropped unread (ADR-0159 §8) and a value for a member the certain rung
> labelled is discarded unread (ADR-0159 §3), so neither can make a mapping
> non-conforming.

> **Normative.** Where a crossing's reading is taken, the ten keys are **present**,
> each carrying the count it reached, zero included. That includes a crossing in
> which ADR-0159 §2's invocation condition excluded every proposal: the condition was
> evaluated, and `reconciled = 0` beside nine other zeros is what that evaluation
> found.

> **Normative.** The ten keys are **absent** only where no reading is taken at all —
> a fault path carrying the entry quantities alone, or ADR-0119 §5's mapper that
> raised. The six `decisions_*` keys are absent on exactly those paths and present on
> exactly the others, so the ten are observed exactly when the six are, are written in
> the same statement, and no crossing carries one set without the other.

**Coherence is what makes a positive model count mean anything, and it is the property
#1209 actually needs.** With the clause, `relations_model_restates`,
`relations_model_adds` or `relations_model_contradicts` above zero on a crossing
**entails that the reconciler reported a model answer** for the proposal those labels
came from — and, on a **conforming** reconciler, that a model answered. Without the
clause not even that holds: a reconciler could report that it never asked and hand back
labels anyway, and the two halves of the same trace would deny each other, leaving a
reader no conclusion to draw from a positive contradiction count — the one conclusion
this ADR exists to make drawable. The guard is deliberately one-directional and §6
states the residue: it catches a report that **under**claims beside labels that stand,
which is the incoherence a reader can detect, and it does not catch a reconciler that
reports an answer it never obtained, which no writer-side check can.

**Reading the report to decide installability is not a ruling turning on
availability.** ADR-0159 §6 promises that "no ingest is refused or ruled differently
because a reconciler was unavailable, **other than by the relations it therefore does
not hold**", and a discarded incoherent label is precisely a relation the writer does
not hold. Nothing is refused, nothing waits, and a **conforming** reconciler is
unaffected in every case — which is the test to apply to this clause and to the one
below. Both are ADR-0159 §3's absorption of a non-conforming reconciler, extended
from the shapes `MemoryIngestor._relations_for` already guards to the values and the
combinations it does not.

**Installing on identity is not defensive typing; it is what keeps the instrument
and the ruling saying the same thing about one input.** `DefaultMemoryPolicy`
selects its target with `is ConflictRelation.RESTATES` and `is
ConflictRelation.CONTRADICTS`, so a value merely *equal* to a member is unlabelled to
the arm. `ConflictRelation` is a `StrEnum`: the bare string `"contradicts"` compares
equal to `CONTRADICTS` **and hashes with it**, so a metric mapping keyed by the enum
finds it and counts it. Without this clause the trace would report a model
contradiction the arm never saw — the instrument contradicting the ruling, silently,
about the same pair. A value equal to no member fails in the other direction: the
mapping raises, ADR-0119 §5 makes a mapper that raises a **lost trace** rather than a
lost write, and one non-conforming reconciler costs the whole crossing's record. Both
are closed by installing on the test the policy already applies. **No ruling moves**:
a value that is not a member is unlabelled to the arm today, by the same `is`. And
this is ADR-0159 §3's absorption of a non-conforming reconciler reaching *values*,
where `MemoryIngestor._relations_for`'s existing guard reaches shapes — "a reconciler
that *returns* something unusable… is as non-conforming as one that raises".

**And it is the whole mapping that fails, because partial trust is what would make the
arithmetic lie.** A returned mapping carrying one valid `ADDS` and one bare
`"contradicts"` could install the valid label and count its proposal `reconciler_failed`
— and then one trace would say a model label stood *and*, through the answered
arithmetic above, that no model rung answered on that proposal. Discarding the mapping
whole is the arm that keeps both statements true, and it is the shape `_relations_for`
already has: its guard's `except Exception: return own` discards the entire
`determined`, not the member that failed. The rejected alternative is to keep the valid
labels and add an eleventh key for a partly malformed mapping; it buys a distinction
nobody has asked for, and it leaves `answered` needing a footnote in every report that
states it. The same answer is given to the later proposal to split `reconciler_failed`
itself into an attempted-request key and a pre-request one: no key here reads that
difference, so it does not earn a key, and the operator bullet in `Consequences` stops
asserting the difference instead.

**A beyond-bound entry marks a reconciler that already failed to conform, and the clause
above competes with no rule of ADR-0159's.** ADR-0159 §3's discard binds the
**reconciler**: "A reconciler installs a model-supplied label only for a member it
consulted the model about. A label the reply carries for any other record — including a
member of the conflict set that fell beyond the bound … — is discarded." That happens on
the reconciler's side of the `memory`-internal seam, before anything crosses to this
writer. So a returned mapping still carrying such an entry is already the output of a
reconciler that did not conform, and the clauses here do not re-derive §3's rule at the
writer. They rule on **values**: a non-member beyond-bound value fails the mapping whole
exactly as any other non-member value does, and the crossing holds the relations it
therefore does not hold, which is ADR-0159 §6's admitted cost. Whether the writer should
*also* refuse a **well-formed** beyond-bound label — which it cannot tell from a
consulted one — is ADR-0159's enforcement question and §9 declines it in terms; issue
#1225 records it. Deciding it here would need the consulted set carried across the seam,
which §6 and §9 decline ("which members a request covered is not emitted"; "the
economics ADR-0159 §3 deliberately leaves inside the reconciler"), and
`MemoryIngestor._relations_for` has the matching shape today — it ranges over
`conflicts` and never over a consulted set, because it is not the layer that knows one.
§7 pins the mixed case rather than leaving an implementer to meet it fresh.

**A crossing that reconciled nothing observed a zero; it did not fail to observe.**
ADR-0119 §3 is the clause under strain here — "an absent key means *not observed* and
never zero", and an emitter "may not substitute one for the other" — and the
substitution it forbids is available in both directions. A crossing whose proposals
ADR-0159 §2 all excluded **did** evaluate the invocation condition, on every proposal,
and found none of them admitted; `reconciled = 0` is that finding. Making the ten
absent there would record it identically to a crossing that faulted before any reading
was taken, which is the one distinction a reader of this stream cannot afford to lose:
"the reconciler was never reached" and "the trace never got that far" call for opposite
responses. The asymmetry is already in the tree rather than invented here.
`_reconciliation_reading` fills every `decisions_*` key with a zero because "a
completed ingest observed every kind"; `MemoryIngestor.ingest` passes `observing` no
`partial` reading, so a fault there carries `proposals` and none of the six. The ten
ride that existing split rather than a new one.

**The two units are different populations and conflating them is the trap.**
ADR-0159 §2's condition is a property of a proposal; a relation is a property of a
pair. A proposal that clears the condition with an **empty** conflict set counts in
`reconciled` and contributes nothing to `relations_offered` — `_may_reconcile`'s
`all(...)` over an empty sequence is vacuously true, so this is the common case and
not an edge one. `reconciled` is therefore the wrong denominator for any relation
figure and `relations_offered` is the right one, which is why both are emitted and
why each clause says which it counts.

**`reconciler_unconsulted` is not a measure of certainty, and on this corpus it will
be dominated by the empty case.** A reconciler makes no request when the certain rung
settled every member within the bound *and* when there was no member to settle: a
proposal clearing ADR-0159 §2's condition with an empty conflict set reaches the
reconciler with nothing consulted and returns immediately. Both are "no model request
was made", which is what the key says and the whole of what it says. Which of the two
it was is `relations_offered` on the same trace — zero for the empty set, positive
where the rung settled the set — so the pair reads what neither key does alone, and
nothing needs a further key.

**The complement of `reconciled` is already there and is not re-emitted.** The
`proposals` key is observed at entry on both write seams, so proposals excluded by
§2's invocation condition are `proposals` less `reconciled`. Emitting a further key
for a difference of two the trace already carries would be a quantity nobody
observed, and the same argument is why the answered case has no key of its own.

**`certain` names the property and not the symbol.** The predicate is
`ai_assistant.memory._agreement.agrees` and ADR-0159 §3 calls the rung "certain
where it fires, silent everywhere else, costing nothing". Keying on the property
means renaming the function does not orphan a metric key, and it keeps the key from
reading as a claim about a specific implementation of agreement.

**One key for the certain rung and three for the model's, because the predicate has
one answer.** ADR-0159 §3's first clause admits exactly `RESTATES` from it. A
`relations_certain_adds` would be a key whose value is zero by construction, which
is a different thing from ADR-0128's deliberately retained structural zeros: those
decompose a set the same trace reports and their going to zero on a date is itself
an observation. Nothing about this system could ever move a certain-`ADDS` count.

**Totality over `ConflictRelation` is asserted by test, following
`DECISION_METRICS`.** `src/ai_assistant/memory/traces.py` already maps a closed enum
to literal keys that way and documents why — "a member added later fails loudly here
instead of silently dropping a count". A fourth relation is possible in a later ADR;
it should break a test, not vanish.

**Failure is separated from silence, and that is the third proposal key's whole
job.** `_relations_for` today absorbs a non-conforming or unavailable reconciler by
returning `own`, so a reconciler that raised and one that answered with nothing
useful are indistinguishable from their result. ADR-0159 §3 is right to make them
rule identically; a *measure* that cannot tell them apart, though, reads an unusable
determination as a model that had nothing to say. The emitter observes which of those
two it was at the point the guard absorbs it, and no more than that.

### 4. The counts are read from the writer's own mapping, never the one a policy was handed

> **Normative.** Every count in §3 is read from the relations `MemoryIngestor` holds
> for itself, and never from the read-only mapping passed to `MemoryPolicy.decide`
> nor from anything a policy returns.

ADR-0159 §8 already requires the writer's own mapping for §5's retirement exclusion
— "A relation the writer reads to determine what a `SUPERSEDE` retires is never one
a `MemoryPolicy` was given the opportunity to change" — and the same reasoning
carries to the instrument for the same reason it carries to the exclusion: an
injected policy can narrow a `Mapping` with `isinstance(..., dict)` at run time, and
an instrument a policy can move is measuring the policy rather than the reconciler.

**The stronger reason is that the policy's view is lossy even when the policy is
honest.** In a deployment with no reconciler injected the writer holds `own` and
`decide` is handed `None` (§2's context above; ADR-0159 §8; ADR-0161 §4). An emitter
reading the parameter would report `relations_offered = 0` for a crossing in which
the certain rung labelled every member — which is the ADR-0159 §6 floor, a ratified
deployment, reported as if no reconciliation had happened at all. The writer's
mapping is not the safer of two adequate sources; it is the only adequate one.

### 5. The bound is configuration, and it joins ADR-0119 §9's allowlist

> **Normative.** `Settings.reconciler_max_conflicts` joins
> `src/ai_assistant/service/configuration.py`'s `_allowlisted` under its own
> metric-key literal declared in that module, as a number, in the shape the existing
> entries take. The test that pins the declared allowlist against what a deployment
> produces is extended to expect it. This names a field that already exists and adds
> no `Settings` field.

> **Normative.** `Settings.reconciler_model` does **not** join the allowlist.

> **Normative.** The allowlist entry lands no later than the emitter, in the same
> change.

**The bound is not the writer's to observe, so it is not the write trace's to
carry.** ADR-0159 §3 leaves the reconciler's own economics to the reconciler:
`MemoryIngestor` hands it the whole conflict set and never learns how many members
it consulted about. The configured value is not an observation of the write event
either — putting a constant on every crossing would be a configuration dump wearing
a trace's clothes, against ADR-0119 §1. §9 is the carrier the corpus already has for
exactly this, and reading the bound from it beside `relations_unlabelled` is what
lets a reader separate "beyond the bound" from "the model declined to label".

**This is the route ADR-0119 §9 provides for and ADR-0141 §10 has already taken.**
§9 states the allowlist's property and leaves its roster open — "A later change that
needs one adds it", in `service/configuration.py`'s own words — and ADR-0141 put the
three notification tunings on it by exactly this argument: without the entry "the
trace stream cannot see a cap, a retention horizon or a reconsideration interval
move". `reconciler_max_conflicts` meets the same inclusion test: it bounds how many
pairs can carry a model label at all, so it shapes the accumulation every figure in
§3 is read over. ADR-0141's sequencing clause is taken with it — an emitter running
while the bound is off the list writes a stretch of stream no boundary divides.

**The route is refused because §9's third clause refuses it.** A model identifier
"is recorded as its presence or absence, or not at all", and presence of a
configured route is not the fact anyone wants: whether a reconciler was actually
*injected* is answered per crossing by `reconciler_absent`, from the writer, which
is a stronger statement than a setting's presence at startup.

### 6. What this instrument cannot say, stated rather than left to be discovered

> **Normative.** A figure computed from these keys is stated in the unit §3 gives
> each key — the proposal keys count proposals, the pair keys count pairs — and
> whatever report states one states with it that no pair it counts is attributable to
> a particular proposal or to a particular record.

The **trace's** unit is the crossing (§2), and the keys' units are not: an aggregate
over many traces is a rate in the unit §3 fixes, so `reconciled` against `proposals`
is a proposal-level reconciliation rate and is stated as one. What no aggregate
recovers is which proposal or which record a counted pair belonged to. A trace saying
`relations_model_contradicts = 2` does not say which of the reading's proposals they
arose from, nor which conflict member. For #1209's question — did the model ever
return `CONTRADICTS`, and how often — that is sufficient, and it is worth saying
plainly that it is the whole of what is bought. A per-pair attribution needs a
carrier the family does not have (§2).

**A label held is not a ruling refused, and the trace does not say which clause
declined.** These keys record what relations stood when the arm ran; they record
nothing about why it ruled as it did. ADR-0159 §4(b) names a `SUPERSEDE` target only
among members whose `provenance.source` is `OBSERVED` or `INFERRED`, and only where
no member is labelled `RESTATES` — two independent bars, and §4 keeps them apart
deliberately: an `EXTERNAL` member "is never *named* by either exception, and it
counts in both purity conditions exactly as any other member does". So a stream
carrying `relations_model_contradicts` above zero beside `decisions_supersede` at
zero says a contradiction was held and no supersession followed, and does not say
whether the target class excluded it, a purity condition blocked it, or both.
Narrowing that needs the member's `provenance.source` and the pair it belonged to,
which the clause above and §2 put out of reach.

**Which members a request covered is not emitted, and neither is whether one reached
a provider.** §3's outcome report answers which of the reconciler's three outcomes it
took — the model answered, `reconciler_failed`, or `reconciler_unconsulted` — because
that is the difference between a silent model and a reconciler that delivered nothing
usable, and it is the fact #1209 is actually about. It does **not** say a request was
made: `reconciler_failed` covers a non-conforming reconciler the writer's guard
absorbed as well as a request that yielded no readable answer, and `Consequences`
records that limitation where an operator meets it. It stops there. Which members the
reconciler consulted about, and how the bound cut the set, stay inside the reconciler on
ADR-0159 §3's ground that its own economics are its own — "a mis-scoped one is
unobservable in the ruling", and this ADR does not make it observable in the trace
either. What remains, read with §5's configured bound beside `relations_unlabelled`,
is a bound on the consulted set rather than the set itself.

**And a model label that was returned but discarded is not counted, and neither is one
discarded before it was returned.** §3 counts the label that **stands**, so a
reconciler answering `CONTRADICTS` about a pair the certain rung already labelled
leaves every model key at zero for it. ADR-0159 §3 makes such a reconciler
non-conforming, which is why this is the right count and not a gap. A **conforming**
reconciler reaches the same zero by the other route: §3 requires it to discard a label
for a member beyond `reconciler_max_conflicts` before it returns, so a model that did
say `CONTRADICTS` there is never counted here either. Either way a zero model count is
a statement about labels *held*, not about strings a model emitted.

**And a model key is a statement about what the reconciler reported, not an
independently verified fact about a provider.** §3's coherence clause rejects a report
that claims *less* than the labels beside it — `unconsulted` or `failed` arriving with
model labels — because that incoherence is visible at the writer. The symmetric lie is
not: a reconciler reporting `answered` while having made no request produces a positive
model count the writer cannot distinguish from a true one, because verifying it would
mean observing the provider call, which lives inside the reconciler on ADR-0159 §3's
ground. Such a reconciler is non-conforming, exactly as one fabricating labels is, and
this instrument inherits that trust rather than replacing it. What the keys measure
without qualification is what the reconciler *reported*; that this equals what a model
did is a property of a conforming reconciler.

**A pair's relation is not joinable to the ruling that followed it.** The trace says
six proposals ruled `ACCEPT` and says three pairs were labelled `CONTRADICTS`; it
does not say the `CONTRADICTS` pairs belonged to `ACCEPT`-ruled proposals. On a
one-proposal crossing — every `MemoryIngestor.ingest` call — the join is exact, and
on a reading it is not. That asymmetry is a property of ADR-0119 §5's one-crossing
rule and is inherited, not introduced.

### 7. What the implementing lane owes, and that it is one lane

> **Normative.** The implementation is **one lane**: `memory`, `service`'s allowlist
> entry, and their tests, ratified and merged behind this ADR.

ADR-0137 §1 asks whether the slice "puts substantial new machinery into at most one
subsystem". It does: the observation, the ten keys, the reconciler's outcome report
and the reading that fills them
are `memory`'s. The allowlist entry is one literal and one mapping line in
`service`, which is the adaptation §1 excludes from the bound, and ADR-0141's lane is
the precedent — "The allowlist entry is `service`, the emitter is `memory`… that is
admissible rather than a widening".

The lane owes:

- `src/ai_assistant/memory/traces.py` — the ten literal keys with their docstrings,
  and a closed mapping from `ConflictRelation` to the three model keys in the shape
  `DECISION_METRICS` takes.
- `src/ai_assistant/memory/_reconciler.py` — the outcome §3 requires the reconciler
  to report, on its own `memory`-internal Protocol and its model-backed
  implementation, carried beside the relations rather than inferred from them. The
  seam gains what it reports and loses nothing: the never-raises clause, the bound,
  the one-request clause and the discard rule are ADR-0159 §3's and are untouched.
- `src/ai_assistant/memory/ingest.py` — the observation of each quantity in §3 at the
  point it is known, carried to the reading through the writer's own internal types,
  and written in the statement that writes the decision counts. §3's whole-mapping
  clause reaches this file too: `_relations_for` installs member by member today, so
  the values it reads are validated before any of them installs.
- `src/ai_assistant/service/configuration.py` — the allowlist entry of §5.
- Tests under `tests/memory/` against the emitted trace, pinning at least: that a
  member the certain predicate labels is counted under
  `relations_certain_restates` and under no model key, on a reading where a
  recording reconciler also returns a label for it; that a reconciler returning
  `CONTRADICTS` is counted as such **on a crossing whose ruling is `ACCEPT`**, which
  is the pilot-4 shape this ADR exists to make readable; that the five pair keys sum
  to `relations_offered`; that a proposal clearing §2's condition with an empty
  conflict set counts in `reconciled` and contributes nothing to
  `relations_offered`; that a writer holding no reconciler emits `reconciler_absent`
  and still counts the certain rung's labels, on the same ingest for which `decide`
  receives `None`, with `reconciler_unconsulted` at zero on that trace — the
  exclusivity clause, and the one overlap the two keys' wording invites; that a
  reconciler raising is counted under
  `reconciler_failed` — and, because that is the finding this ADR nearly got wrong,
  a test driving a **raising `ModelProvider`** through the real reconciler rather
  than a reconciler stub, since `ModelBackedReconciler.reconcile` absorbs a provider
  failure itself and the writer's guard never sees it; that a reconciler completing
  with an **empty** mapping — a conforming "nothing to add" under ADR-0159 §3, and
  the `{}` ADR-0159 §8 distinguishes from `None` — leaves `reconciler_failed` at zero
  and counts its offered pairs under `relations_unlabelled`, on a trace that differs
  from the failing provider's; that a proposal whose certain rung settled every
  member within the bound is counted under `reconciler_unconsulted` with no provider
  request made; that a proposal clearing §2's condition with an **empty** conflict set
  counts under `reconciler_unconsulted` with `relations_offered` at zero, which is the
  path that dominates the population and the one an implementation reading the key as
  "certainty settled it" gets wrong; that a reconciler returning a value **equal to** a
  `ConflictRelation`
  member but not one — the bare string a `StrEnum` makes equal to it and hashable
  with it — leaves the member unlabelled, counts its proposal under
  `reconciler_failed`, and costs the crossing no trace; that a returned mapping pairing
  **one valid member value with one such non-member value** installs *neither*, leaves
  both members under `relations_unlabelled`, counts its proposal under
  `reconciler_failed` and leaves every model key at zero for it — the whole-mapping
  clause, and the case where a partial install would make one trace report a model label
  beside an answered count of zero; that on a conflict set **longer than
  `reconciler_max_conflicts`** a returned mapping pairing a valid label for a member
  **within** the bound with a **non-member value for a member beyond** it installs
  neither, leaves both under `relations_unlabelled` and counts the proposal under
  `reconciler_failed`, pinning that the writer reads the resolved conflict set and
  holds no consulted set to except the second entry from — a mapping carrying that
  entry at all is already the output of a reconciler ADR-0159 §3 required to discard
  it, and what the writer does with a *well-formed* beyond-bound label is §9's
  undecided question rather than a test here; that a report of
  `unconsulted` and a report of `failed`, each arriving with a model label, discard
  that label, leave the member unlabelled and count the proposal under
  `reconciler_failed` — the two combinations that would otherwise let one trace deny
  itself; that a report from a reconciler that **ran** failing to name exactly one of
  its three outcomes — missing, carrying a value that is none of them, or naming more
  than one, the last pinned on a report carrying **both** an answered model and
  `reconciler_unconsulted` beside valid labels — retains the certain rung's labels,
  installs nothing from the mapping beside it however well formed that mapping is,
  leaves the remaining offered pairs under `relations_unlabelled` and counts the
  proposal under `reconciler_failed`, which are the cases on which two implementations
  would otherwise report the same input differently; that each of the three
  **non-raising** shapes
  `MemoryIngestor._relations_for`'s guard already absorbs — a reconciler returning
  `None`, one returning a non-mapping, and one returning a mapping whose lookup
  raises — retains the certain rung's labels, leaves the remaining offered pairs under
  `relations_unlabelled`, and counts its proposal under `reconciler_failed`, since
  those are the paths on which an implementation can keep today's silent fallback and
  still pass every other test here; that a proposal §2's condition
  excludes contributes zero to each of the ten
  while `proposals` still counts it, and that a crossing **all** of whose proposals
  §2 excludes emits the ten present at zero rather than absent, beside the six
  `decisions_*` keys; that an `ingest_reading` whose
  **second** proposal raises after the first was applied emits the first's relation
  keys on the fault path's partial reading, beside the `decisions_*` keys it already
  emits there, since §3 binds the two sets to one observation; and totality over
  `ConflictRelation`.
- A test under `tests/service/` extending the pinned allowlist.
- No change under `src/ai_assistant/core/`, `src/ai_assistant/evaluation/`,
  `src/ai_assistant/learning/`, `src/ai_assistant/orchestration/` or
  `src/ai_assistant/testing/`. The canonical `MemoryWriter` fake emits no trace and
  the shared conformance suite asserts none, so neither is reached.

**This ADR's own ratification.** The required set is **adversarial** alone. §2 is the
clause that decides it: no contract surface moves — nothing in `core/types.py` or
`core/protocols.py` changes, and the vocabulary this ADR names is a metric-key
roster ADR-0119 §2 places in the emitting module. `CONTRIBUTING.md` → "Finishing an
ADR PR" holds the sequence and is pointed at rather than re-argued: drafted, reviewed
and revised as `Proposed`, with the status flipped only once adversarial returns clean
on one tree, and that review re-run on the flipped tree. **This ADR takes step 3's
recovery route**: adversarial returned `APPROVE` at round 6, the status was flipped,
and a fresh reviewer session found three defects on the flipped tree — so the status
is returned to `Proposed` and the sequence re-enters at step 1, as ADR-0127 and
ADR-0133 each did on their own PRs. Two of the three were taken in full — the
whole-mapping clause and the three non-raising test cases above. The third named a real
ambiguity in the key-presence clause and a direction that would have closed it by
making the ten keys absent where nothing reconciled; the ambiguity is closed by
stating the two cases apart, and the direction is refused on ADR-0119 §3's own text
and recorded among the alternatives. A later round found a second ambiguity of the
same kind in §3 — the clauses said *reply*, ADR-0159 §3's term for what the model
sends the reconciler, where they meant the mapping the reconciler returns to the
writer — and its direction would have closed it by carrying the consulted set across
the `memory`-internal seam; the wording is corrected and that direction too is refused
and recorded among the alternatives. It records itself as ratified on its second
flip.
Nothing implements against this until it has merged (ADR-0015 §5).

**Most rounds so far have changed this text, and eight of them narrowed a claim it had
no right to make** — that a positive contradiction count implicated ADR-0159 §4's purity
conditions specifically; that a figure over these keys was a crossing-level figure; that
a zero model count meant nothing was returned; that `reconciler_unconsulted` measured
certainty; that a zero contradiction count was a statement about the model even where
the three qualifier keys account for the crossing and no model answered at all; that a
positive one placed the contradiction in the proposal the absent supersession belonged
to, the join §6 rules unavailable on a reading; that the outcome report reached no
ruling at all, when it reaches one by the single route ADR-0159 §6 admits; and that a
positive model key *entailed* a model answer, when it entails a reported one and the
rest is the reconciler's conformance. Another found the defect that reshaped the
decision: `ModelBackedReconciler.reconcile` absorbs its own provider failures, so a key
counted at the writer could not have distinguished a failed determination from a silent
model, which is why §3 takes the outcome across the reconciler seam at all. That is
recorded here because it is the evidence for §3's shape, not as process narration.

### 8. What this records against earlier ADRs, under ADR-0082 §1

ADR-0082 §1's test, applied to each: would a reader holding only the earlier ADR now
act differently, or read one of its clauses more widely than it now holds?

**No record is owed on any, and the one that looks owed is the one to argue.**

- **ADR-0159 §12.** Its bullet defers this question and names that a ruling would
  settle it. This is that ruling, so the sentence stays true — ADR-0159 still decides
  nothing here — and acquires an answer elsewhere. ADR-0083 §15 rules this shape
  directly: "A deferral discharged by the ADR it named is a stacked addition, not an
  amendment", and ADR-0040's own amendment note applies it in the same words while
  declining to owe anything for it. §12 names the ruling rather than its number,
  which is the relation ADR-0083 §15's own clauses have to the scheduler they
  deferred to — none of them could name an ADR that did not yet exist either. No note
  is appended to ADR-0159 and its text is not touched.
- **ADR-0159 §3 and §10.** §3's clauses bind what a reconciler *answers*, what it may
  spend and that it never raises; §10's list of what the implementing lane owes names
  "the reconciler behind a `memory`-internal seam" and its rungs. Neither fixes the
  seam's **return type**, and §8's contract surface is `core/types.py` and
  `core/protocols.py` alone — ADR-0159 §2 is explicit that "no Protocol for it goes in
  `core/protocols.py`". So §3's requirement that the reconciler report its outcome
  changes no ratified text, and a reader building a reconciler from §3 builds the same
  rungs with the same spend and the same never-raises guarantee. What the report may
  not do is feed a ruling, which §3 confines by naming the two things that read it.
  That one of those two discards a non-conforming reconciler's labels is not a ruling
  turning on availability: §6 admits exactly that cost — "other than by the relations
  it therefore does not hold" — and a conforming reconciler never reaches the clause.
- **ADR-0159 §9.** Its first clause — "This ADR adds no metric key, removes none, and
  changes no metric key's definition" — is a statement about ADR-0159 and stays true
  of it. This ADR removes no key and redefines none; `decisions_reinforce`,
  `decisions_accept` and `decisions_supersede` "count what they have always counted".
  Its second clause, on labelling a window spanning the rule change as not
  comparable, is untouched and is **not** discharged here (§9).
- **ADR-0161 §8.** "§9 adds no metric key and this ADR adds none" is a statement
  about ADR-0159 §9 and about ADR-0161, and both halves stay true. A later ADR adding
  one is succession, not contradiction.
- **ADR-0119 §3, §8 and §9.** §3 closes four enumerations and this adds no member to
  any. §8 calls its seam roster "the floor rather than the ceiling" and forbids a
  later lane only a `TraceKind`; the `MEMORY_WRITE` clause states what a trace
  carries "the ingest reached" and is a floor in the same sense. §9 leaves the
  allowlist's roster to the change that needs an entry, which §5 above is — ADR-0141
  §11 examined the identical route and found no record owed, and that finding is
  applied here rather than re-derived.
- **ADR-0120 §2.** Its `MEMORY_WRITE` eligibility clause is stated over "all six
  `decisions_*` metric keys" and its malformed clause over "a strict, non-empty
  subset of the six". Neither reads a key outside the six, so no population this ADR
  can affect changes, and no figure moves. §3's shared count predicate is adopted
  rather than restated (§2).
- **ADR-0121 §7.** Its measures clause is about ADR-0121 and its policy-change-marker
  refusal is left exactly where it is (§9).

### 9. What this ADR does not decide

- **Any measure.** No figure in ADR-0120's report is added, removed or redefined; no
  key here joins `src/ai_assistant/evaluation/_vocabulary.py`'s allowlists, so none
  contributes to any measure; `evaluation` is untouched and reads nothing new. What
  this ADR buys is that the distribution can be **read from `traces.db`**, which is
  what #1209 asks for. Whether it deserves a rendered figure is the successor
  question and belongs to whoever wants the figure.
- **#1205's semantic-rule revision. Left open and explicitly not taken.** That issue
  asks whether the stream should carry a marker a window can be partitioned on when
  a *decision rule* changes under unchanged settings — ADR-0121 §7's deferral, which
  ADR-0159 §12 names as the same call. This ADR adds observations of one seam's own
  event and no marker: it says what a reconciliation held, never that the rule
  governing reconciliation changed. **The near-miss is worth refusing explicitly.** A
  window whose `MEMORY_WRITE` traces carry none of §3's keys is a window that predates
  this *emitter*, which is a different date from ADR-0159's rule change and later than
  it. Reading key absence as a rule-change boundary would date the discontinuity
  wrong, in the direction that makes a spanning window look partitioned when it is
  not. It is not the marker #1205 wants and must not be used as one.
- **Per-pair or per-proposal attribution**, and whether the family should ever grow a
  carrier for it. §6 states the limit; closing it is a change to `EvaluationTrace`
  and would be ADR-0119's to reopen.
- **Which members a reconciler consulted about, and how its bound cut the set.** §3
  takes the *outcome* across the reconciler seam and §6 declines the membership: the
  first is the difference between a silent model and a broken one, the second is the
  economics ADR-0159 §3 deliberately leaves inside the reconciler. Taking the second
  as well is available without disturbing any contract and is not needed for #1209's
  question.
- **Whether a writer should refuse a well-formed label for a member beyond
  `reconciler_max_conflicts`.** ADR-0159 §3 obliges the **reconciler** to discard such a
  label, so the question arises only for a reconciler that already broke that rule, and
  the writer cannot tell one from a consulted member's label without the consulted set
  the bullet above declines to carry. This ADR neither requires nor forbids installing
  it: it observes what stood and moves no installation rule, and that rule is ADR-0159's
  — its bound, its enforcement and its seam. Issue #1225 records the gap and the
  candidate resolutions, none ruled.
- **The right value of `reconciler_max_conflicts`**, which stays where ADR-0159 §12
  left it — an empirical question a pilot arm answers. §5 makes the value readable
  and takes no view on it.
- **Anything about the reconciler's prompt, its economics, its bound's enforcement or
  ADR-0159 §4's purity conditions.** This ADR observes them and changes none of them.
  Its point is that the next argument about them can be had against data.
- **Whether traces are swept by erasure**, which ADR-0119 §15 leaves open. These keys
  are counts and reference nothing, so they neither help nor hinder it.

## Consequences

- **#1209's question becomes answerable, and it is the question that decides what to do
  next.** On a pilot run reporting zero supersessions, a **positive**
  `relations_model_contradicts` says a model contradiction **stood somewhere in the
  crossing** and that no **supersession** followed in it — not that no retirement did,
  since a reading's coverage reconciliation retires under `closed`, a key this bullet
  does not read. That is the whole of the join: §6 rules that a pair's relation is not
  joinable to the ruling that followed it, exact on a **one-proposal** crossing — every
  `MemoryIngestor.ingest` call — and not on a reading, so on a reading the count does
  not say that the proposal the contradiction belonged to is the one ruled without a
  supersession. Where the join is exact it points at ADR-0159 §4, and even there it does
  **not** say which of §4's bars declined — an `EXTERNAL` contradiction outside the
  target class and a contradiction standing beside a `RESTATES` member present as the
  same positive count against the same zero, and §6 says so.
- **A zero contradiction count is read against the answered count first, and says
  nothing about the model until it is.** `relations_model_contradicts = 0` means **no
  model-rung `CONTRADICTS` label was returned by the reconciler and stood**, and it says
  even that only over proposals **whose model rung answered** — §3's `reconciled` less
  `reconciler_absent`, `reconciler_failed` and `reconciler_unconsulted`. It is not a
  statement that the model was silent, and a reply the reconciler discarded before
  returning is **outside its meaning**: ADR-0159 §3 requires a **conforming** reconciler
  to discard a label for a member beyond `reconciler_max_conflicts`, so a model that did
  say `CONTRADICTS` there leaves this zero standing (§6). Read that way, and only there,
  does the zero point at the prompt, the bound or ADR-0159 §3's temporal clause. Each of
  those three qualifiers yields that same zero with **no model answer behind it at
  all**, so where they account for the crossing the zero is not evidence about the model
  and the prompt is the wrong place to look. Read the qualifier keys first, and read the
  three apart, because they do not all say the same thing. `reconciler_absent` and
  `reconciler_unconsulted` mean **no request was made**, so an operator who skips them
  will investigate a prompt that was never sent. `reconciler_failed` says only that the
  **determination was unusable**, and takes no view on whether a request was made: §3
  counts under it both a request that yielded no readable answer and a non-conforming
  reconciler the writer's guard absorbed, and the second of those need never have
  reached a provider. So this key sends an operator to the reconciler — its conformance,
  and its own logs — before the provider or the route, because the trace does not say
  which of the two arms produced the count.
- **The floor deployment becomes visible for the first time.** `reconciler_absent`,
  `reconciler_failed` and `reconciler_unconsulted` distinguish a hub running ADR-0159
  §6's ratified floor, a hub whose reconciler cannot deliver a usable determination, a
  hub whose model is never asked at all, and a hub whose model is asked and adds
  nothing — four states that
  today all present as an unremarkable run of `ACCEPT`s. `reconciler_unconsulted` is
  read with `relations_offered` beside it, because it does not say *why* nothing was
  asked (§3). Three of them need the reconciler's own report, because it absorbs its
  failures itself and the writer sees only a mapping (§3).
- **The write trace grows by ten integers per crossing**, and one number joins the
  startup stamp. Both are small against what the envelope already carries, and the
  keys ride the statement that writes the decision counts rather than adding a
  branch.
- **A window spanning the emitter's arrival has these keys on one side only.**
  ADR-0119 §3 makes an absent key *not observed* rather than zero; a reader that
  averages across the boundary as if it were zero will understate every rate. This
  is the ordinary hazard of adding a key and is named so nobody meets it fresh.
- **The corpus acquires one more thing it must keep honest**: the merged mapping and
  the rung split are two views of one determination, and an implementation that
  starts counting the merged one passes every test that does not specifically
  distinguish them. §7's first pinned test exists for that.
- **Revisit when** a relation distribution shows a `CONTRADICTS` rate ADR-0159 §3's
  guards do not explain; when a figure over these keys is wanted in the report, which
  reopens the measure question §9 declines; or if #1205 is taken, since a real
  partition marker would change how a window over these keys is cut.

## Alternatives considered

- **One key per `ConflictRelation` member, counted over the mapping
  `_relations_for` returns.** The obvious shape, and the reason §12 reserved this
  ruling. It cannot answer #1209: the certain rung contributes only `RESTATES`, so a
  merged `RESTATES` count conflates a free string comparison with a paid model call,
  and the two come apart hardest in exactly the deployment ADR-0161 §4 rules on.
  Rejected in §3.
- **A `relations` field on `EvaluationTrace`, or a per-pair `TraceRecordSet`.**
  Rejected in §2: ADR-0119 §2 admits no open-value mapping and §3 fixes the
  envelope's fields and closes `TraceRecordSet`; either would be a `core/types.py`
  change and a contract ADR for what is a count.
- **Reading the counts from the mapping handed to `MemoryPolicy.decide`.** Rejected
  in §4. It is reachable by an injected policy, and it is `None` in the no-reconciler
  deployment while the writer holds labels — so the emitter would report an empty
  reconciliation for a crossing that had one.
- **Emitting a trace from the reconciler itself.** Rejected: ADR-0119 §5's
  one-crossing rule makes a second trace per ingest the wrong shape, and §7 requires
  a `TraceSink` at every emitting site — which would put a trace seam behind
  ADR-0159 §2's `memory`-internal reconciler boundary and make an optional component
  a wiring obligation.
- **Carrying `reconciler_max_conflicts` on every `MEMORY_WRITE` trace instead of the
  startup stamp.** Rejected in §5: it is configuration and not an observation of the
  write event (ADR-0119 §1), and ADR-0119 §9 is the carrier the corpus already has.
- **Deriving the distribution offline from the store.** Rejected in §1, on ADR-0119
  §8's own ground, and more strongly than for decision counts: a relation is a
  statement about a pair made during one ingest and written to no row, so there is
  nothing to derive it from once the crossing ends.
- **Preserving the valid labels in a partly malformed returned mapping, under an
  eleventh key for "the mapping was partly malformed".** Rejected in §3. It keeps a
  label from a component that has already returned one unusable value, and it either
  breaks the answered arithmetic — a proposal counted `reconciler_failed` while a model
  label of its own stands — or forces `answered` to be stated with an exception clause
  wherever it is read. Discarding the mapping whole costs a conforming reconciler
  nothing and is the shape `_relations_for`'s existing guard already takes.
- **Carrying the reconciler's consulted set across the `memory`-internal seam, so the
  writer can except a beyond-bound entry from validation.** Rejected in §3. The
  distinction it wants is already made, one layer earlier and unconditionally:
  ADR-0159 §3 obliges the reconciler to discard a label for any member it did not
  consult the model about, so a mapping still carrying one is non-conforming before
  it crosses. Bringing the set across would reopen a boundary §6 and §9 draw
  deliberately — "which members a request covered is not emitted"; "the economics
  ADR-0159 §3 deliberately leaves inside the reconciler" — and would grow the seam,
  the outcome report and §7's owed lane to support a distinction no key here reads
  and no ruling turns on. What the round found that *was* real — that "reply" named
  the wrong artefact — is fixed in the clauses instead. This is not §9's open
  question: that one is whether the membership is *emitted*, which stays undecided
  and unneeded there; this one is whether the writer's validation rule turns on it,
  and that is answered no.
- **Making the ten keys absent on a crossing that reconciled nothing.** Rejected in
  §3. It reads ADR-0159 §2's invocation condition excluding every proposal as an
  absence of observation, when the condition was evaluated and found none admitted —
  so it would record that crossing identically to one that faulted before any reading
  was taken, the substitution ADR-0119 §3 forbids in terms. The ambiguity that
  suggested it was real and is closed by stating the two cases apart, not by moving
  the boundary.
- **Leaving it to lane 2.6's discretion under ADR-0119 §2.** Mechanically available —
  nothing in the gate or the import contracts would have stopped it. Rejected because
  ADR-0159 §12 reserved it, because the corpus's test is whether an ADR's text
  enumerated the thing being changed and §12's does, and because the vocabulary that
  works is not the one a lane reaching for the obvious count would have written.
