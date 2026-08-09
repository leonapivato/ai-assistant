# 120. A measure is a rate over one window of the trace stream, read offline while the hub is stopped

- Status: Proposed
- Date: 2026-08-09
- **This decision adds no contract surface, and §9 argues it rather than
  asserting it.** No Protocol in `core/protocols.py` gains a member or changes a
  signature; no type, enum member, constrained string or constant is added to
  `core/types.py`; no `Settings` field appears; no `AssistantEngine` method, wire
  operation or CLI command is created. Every quantity the three measures are
  defined over is a field the emitters ADR-0119 §8 ratified already carry on
  `main`. Golden rule 5 and ADR-0015 §5 therefore do not bind this ADR, and §12
  records that nothing here reaches ADR-0119 §13e's gate on the four trace
  enumerations either.
- **It still ships as its own `Proposed` PR and carries both review lenses.** The
  reporting tool §9 decides is a follow-on lane and #846 names it as one; review
  while the decision is still `Proposed` is what lets a finding change it rather
  than supersede it (`CONTRIBUTING.md` → "Contract ADRs land before their
  implementation"). The architecture lens is run because the decision that
  actually needs adjudicating here is a *placement* — which package may hold the
  walk, and by what route an operator reaches it — not because the diff touches
  the contract floor, which it does not.
- **This ADR amends nothing and supersedes nothing.** §13 applies ADR-0082 §1's
  test to each place a record looks owed and records why none is.
- **It discharges ADR-0119 §15's first and fourth bullets** — "the measures'
  definitions" and "the inspection and report surface" — by the route those
  bullets name, which is the mechanism working rather than an amendment
  (ADR-0102 §13).

## Context

### Leg 8's exit test is a question about numbers that do not exist yet

`docs/roadmap.md`'s leg 8 exits when *"is the user model getting more accurate?"
is answered by data, not opinion*, and it names the data: "a first few of
VISION.md's success measures: memory precision, correction rate,
repeated-explanation rate". `VISION.md` → "Measures of Success" lists those three
among a dozen, as English phrases and nothing more. Neither document says what
any of them *is*.

ADR-0119 built the stream they are computed over and deliberately stopped there.
Its §15 records the deferral in as many words — "what each one *is*, and where it
is computed, is a follow-on slice once traces exist (#846)" — and hands forward
two constraints, ADR-0119 §1's split between a fact and an opinion about facts,
and ADR-0119 §5's denominator rule. This ADR is that slice.

**One of the three numbers is owed to a previous leg.** Leg 7's exit hands over
the claim that months of use made retrieval "not noisier", explicitly because leg
7 "had no instrument for it and refused to assert what it could not test". #846
repeats it. Memory precision is the instrument, so this ADR has to produce a
definition under which that claim is *testable over successive windows*, not
merely a figure.

**And one of the three windows is a one-time experiment.** #829's entry ruling
opens leg 8's measurement window with consolidation unarmed, accumulates a
baseline, then arms consolidation "mid-window as a dated intervention", because
"consolidation writes durably, so once it has run there is no unconsolidated
control left to compare against". A measure whose value moves when consolidation
arms *for reasons that have nothing to do with the user model getting more
accurate* would destroy that experiment while looking like a result. §3 and §4
are shaped by that hazard more than by anything else.

### What the stream actually holds, as merged

The definitions below are only as good as their agreement with the emitters, and
the emitter lanes departed in reviewed, flagged ways from what a reader of
ADR-0119 §8 would assume. This is the inventory the definitions were checked
against, at `origin/main`.

- **`RETRIEVAL`**, one per `MemoryStore.search`, emitted inside
  `SqliteMemoryStore` at the seam `memory/traces.py` names `SEAM_SEARCH`. It
  carries `limit` and, when the caller restricted bands, `bands`, both observed
  before the work and so present on the fault path; and, on a read that reached
  the filter pass, `fetch_k`, `candidates`, `returned`, `excluded_kind`,
  `excluded_retention`, `excluded_window` and `excluded_band`. Its
  `records[TraceRecordSet.RETURNED]` holds the returned ids.
- **`MEMORY_WRITE`**, one per crossing of `MemoryWriter.ingest` (seam
  `SEAM_INGEST`) or `MemoryWriter.ingest_reading` (seam `SEAM_INGEST_READING`) —
  ADR-0119 §8's "the write's mode" carried by the label rather than by a field.
  A completed crossing carries **all six** `decisions_*` keys, zeros included,
  and `records` under `WRITTEN`, `REINFORCED` and `SUPERSEDED`, plus `RETIRED`
  and `closed` where a coverage reconciliation ran. Entry quantities `proposals`
  and, for a reading, `coverage_declared` are present on the fault path too.
- **`OPERATION`**, one per `AssistantEngine` call, emitted from `Engine._tracked`
  with the public method's own name as the seam. Three operations add result
  metrics — `purge_expired`, `ingest` and `consolidate` — and `consolidate` is
  the only producer of `TraceOutcome.INCOMPLETE`.
- **`CONFIGURATION`**, one per hub startup at the seam `hub_startup`, carrying
  the nineteen allowlisted figures `service/configuration.py` enumerates in
  `ALLOWLIST_KEYS`.

Four properties of that inventory are load-bearing below, and each is a place a
plausible definition would be wrong.

**Only `TraceRef.CORRELATION` is ever populated.** `TraceRef` also declares
`CONVERSATION`, `TURN` and `EXECUTION`, and no emitter on `main` writes any of
them: `orchestration/traces.py` builds `refs={TraceRef.CORRELATION: correlation}`
unconditionally, and `memory/traces.py` builds the same mapping or an empty one.
So the only join across operations is by **record identity**, exactly as
ADR-0119 §4 says — but the conversation-scoped join a reader might assume from
the enum's membership does not exist. §11 states what that costs and §12 files
it.

**`excluded_band` is a structural zero.** ADR-0113 §2 binds the band predicate
before the ranking cut, so the post-KNN pass never sees an out-of-band candidate
to drop, and `SqliteMemoryStore` writes the key as the literal `0` rather than as
a counter. `bands` — how many bands the caller restricted to — is the figure that
carries information there.

**The four `excluded_*` counts are complete only on a read that fell short.**
`_search_sync`'s filter loop breaks the moment `len(results) >= limit`, so on a
read that filled its page the counters describe the *prefix* of candidates the
loop examined, not the candidate set. They partition the candidate set exactly
when `returned < limit`. §7 is defined inside that bound, and a definition that
ignored it would compute exclusion densities that are systematically understated
on precisely the healthy reads.

**The observation stage has no durable cursor, and a repeat folds into a
`REINFORCE`.** `orchestration/observation.py` states it as a design property —
"There is no durable cursor either — a repeat folds into a `REINFORCE` and the
producer's confidence is deterministic on its inputs" (ADR-0077 §8). Successive
observation batches overlap, so `decisions_reinforce` under the `observe` seam
counts batch overlap at least as much as it counts a user repeating themselves.
§6 is narrowed by that and says so; it is the single finding that most changed a
measure's shape.

### Two constraints this ADR did not choose

**ADR-0119 §5's denominator rule.** "Every measure must be a rate whose denominator is
drawn from the same stream — never from an external count of turns, rows or
runs", because the stream is lossy in principle and "a ratio of two quantities
that lost rows at the same rate survives the loss". The rule is stronger than it
first reads: it is not enough that both parts come from *the stream*. They must
come from parts of it that lose rows *together*, which is why §5 and §6 below
draw every denominator from the same trace, or the same population of traces, as
their numerator.

**ADR-0119 §2's content rule.** A trace carries numbers, booleans, enum members
and opaque ids, and nothing else. So no measure defined here can consult the
*content* of a belief, a query or an utterance, and no measure can be validated
against a human relevance judgement — there is nothing in the stream to judge.
Every definition below is therefore behavioural: it asks what the system and the
user subsequently
*did*, never what anything meant. §11 is the honest accounting of what that
excludes.

### What makes this a decision rather than a query somebody writes

Four things, each with a reasonable-looking wrong answer.

1. **"Precision" has an obvious definition that this system cannot compute.**
   Retrieved-and-relevant over retrieved is the textbook figure and it needs a
   relevance judgement per (query, record) pair. There is no query text in the
   stream and no judge. A lane that reached for the textbook figure would either
   invent a labelling step nobody asked for or quietly substitute a proxy without
   saying so. §4 substitutes a proxy and says so in the clause.
2. **The obvious denominator is the wrong one.** "Corrections per turn" and
   "repeated explanations per conversation" are the phrasings a human reaches
   for, and both take their denominator from a count of events the *stream* does
   not carry as a population — a turn that raised before producing an outcome is
   an `OPERATION` trace, a turn whose trace was lost is nothing at all. ADR-0119
   §5's rule forbids exactly that shape.
3. **Arming consolidation moves a naive correction rate, and it would look like
   a finding.** A supersession is a supersession whether a user asserted it or a
   consolidation job derived it, and #829's whole experiment turns on being able
   to read the before/after. A measure that pools the two answers "did the user
   model get more accurate?" with "did a maintenance job start running?". §3 is
   the mechanism that separates them, and it exists because pooling is the
   default a query would fall into.
4. **A measure taken at the trailing edge of a window is biased and the bias is
   invisible.** A record surfaced an hour before the report has had an hour to be
   contradicted; one surfaced a month before has had a month. Comparing a
   baseline window to an armed window without equalising that opportunity
   compares two different things. §8 makes the settling period a parameter of the
   measure rather than an implementation detail, because it is the difference
   between a comparison and a coincidence.

## Decision

### 1. A measure is a rate over one window, and the window and its settling are part of the figure

> **Normative.** Every measure defined by this ADR is a ratio of two counts
> derived from the same walked stream, over an explicit half-open window of
> `occurred_at` and, where the measure looks forward from an event, an explicit
> settling period. A figure reported without both is not one of these measures.

> **Normative.** No measure defined here carries a threshold, a target, a
> pass/fail verdict or a trend claim.

A measure is a number; whether it is good is the operator's ruling, which is what
leg 8's exit test asks for.

**Notation, fixed here so the definitions below are unambiguous.** `W = [a, b)`
is a half-open interval over the `occurred_at` field; `s` is a non-negative
settling period; and `t ≺ u` means that trace `t` precedes trace `u` in the
store's **total insertion order**, which is the order `TraceStore.walk` returns
and the only total order the stream has. ADR-0119 §7a is explicit that an order
over `occurred_at` "is therefore neither total nor stable", because the emitter
stamps the instant and a slow sink can land an earlier instant after a later one,
so `occurred_at` bounds a window and insertion order decides precedence. Mixing
the two is deliberate: a window is a wall-clock notion an operator chooses, and
"after" is a fact about the stream.

**Two implementations must produce the same number, which is the whole point of
the clauses being this fussy.** Every population below is defined by tests on
fields that are present or absent, on enum members, and on integer comparisons.
None depends on ordering ties, on floating-point accumulation order, or on which
chunk boundary a walk happened to draw.

### 2. Presence is the completeness test, not the outcome

> **Normative.** A trace's eligibility for a population defined by this ADR is
> decided by which keys it carries, and never by its `TraceOutcome`.

> **Normative.** A `RETRIEVAL` trace is eligible for an identity population
> exactly when `records` carries `TraceRecordSet.RETURNED` and that set is **not
> truncated** — `total == len(ids)`.

> **Normative.** A `MEMORY_WRITE` trace is eligible for a ruling population
> exactly when **all six** `decisions_*` metric keys are present.

> **Normative.** A trace carrying a strict, non-empty subset of the six
> `decisions_*` keys is **malformed** for the purposes of this ADR and enters no
> population.

> **Normative.** Every value this ADR reads as a **count** — the six
> `decisions_*` values, and `limit`, `fetch_k`, `candidates`, `returned` and the
> four `excluded_*` values — is a non-negative integer that is not a `bool`. A
> trace carrying anything else under a key this ADR reads as a count is
> **malformed** and enters no population.

> **Normative.** A truncated set excludes its trace from a population **joining
> on that set** and from no other, per ADR-0119 §3.

> **Normative.** The report states, separately from every other exclusion, how
> many traces it excluded as malformed and how many as truncated.

**This is ADR-0119 §3's observation rule used as intended rather than
re-derived.** "A metric key appears in a trace only when the quantity it names
was **observed**. An absent key means *not observed* and never zero." The
emitters honour it in both directions: `_retrieval_reading` supplies
`records[RETURNED]` only on a read that completed, and `_reconciliation_reading`
supplies all six decision counts together or, on the fault path where no reading
is taken, none of them. So "does it carry the key" is already exactly the
question "was the quantity observed", and adding an outcome test on top would be
a second, weaker copy of the same test that can disagree with it.

**It also admits data an outcome test would throw away, correctly.** A
`MemoryWriter.ingest_reading` that raises part-way through carries a `partial`
reading — `memory/ingest.py` passes `partial=lambda: _reconciliation_reading(...)`
over the proposals that stayed applied, precisely so a trace does not deny writes
that are live. That trace's outcome is `FAULT` and its six counts are a truthful
account of the rulings that *did* happen. Excluding it would discard real rulings
to honour a field that is not about them. What is excluded is the crossing that
observed nothing, and absence already says so.

> **Normative.** A `RETRIEVAL` trace carrying the eight counts §7 reads is
> excluded from §7's population, and from no other, unless all three of
> `returned ≤ candidates`, `candidates ≤ fetch_k`, and — where `returned <
> limit` — `returned` plus the four `excluded_*` values equal `candidates`
> exactly. The report counts such a trace among the malformed.

**Counts are constrained because the metric type does not constrain them.**
`TraceMetricValue` is `int | float | bool` refused only for non-finiteness, so a
`decisions_supersede` of `-1`, of `0.5` or of `True` type-checks and stores.
Every emitter on `main` writes these from integer counters, but the rates above
are only meaningful over non-negative integers — a negative numerator produces a
negative rate and a fractional one produces a count of half a ruling, and both
would be reported as figures rather than caught. `bool` is excluded by name
because it *is* an `int` in Python, so a `True` slipping into a count would
satisfy an integrality test while meaning something else entirely. The rule costs
one comparison per value and turns a silent wrong answer into a counted
exclusion.

**Malformed is named rather than assumed away.** No emitter on `main` can produce
a partial decision set — `_reconciliation_reading` builds all six from
`dict.fromkeys` — but a measure that silently divided by a partial sum would be
wrong in a way nobody could see, and a later emitter is not bound by an emitter's
current habits. Counting them is cheap and makes the assumption checkable.

### 3. A write is attributed to the operation that caused it, and the attribution is by seam

> **Normative.** A `MEMORY_WRITE` trace's **attribution** is the `seam` of the
> unique `OPERATION` trace in the retained stream carrying the same
> `TraceRef.CORRELATION` value. A write whose `refs` lacks `CORRELATION`, or
> whose correlation matches no retained `OPERATION` trace, is **unattributed**.

> **Normative.** Three seam sets are fixed here. The **user** set is `converse`,
> `resume`, `observe`, `learn` and `answer`. The **machine** set is `ingest`,
> `consolidate`, `purge_expired` and `start`. The **direct** set is `learn` and
> `answer`, and is a subset of the user set. A write attributed to a seam on none
> of these lists is **unclassified**.

> **Normative.** An unattributed or unclassified write enters no population
> defined by this ADR, in neither numerator nor denominator.

> **Normative.** The report states the count of unattributed writes and the count
> of unclassified writes, and names each unclassified seam it met.

> **Normative.** Attribution is resolved over the **whole retained stream** and
> not over the window. A write inside the window whose operation trace falls
> outside it is attributed normally.

**Attribution is the mechanism #829's experiment depends on, and without it every
measure below is confounded.** Arming consolidation adds a job that supersedes
and retires records on its own initiative. A correction rate that counted those
would rise on the day of the arming, and the rise would be a fact about the
scheduler rather than about the user model. Splitting the population by the
*cause* of the write is the only way the before/after reads as what #829 says it
is — "a before/after on the machinery leg 7 built" — rather than as an artefact
of the intervention.

**The correlation join is the one ADR-0119 §4 ratified and it is exact here.**
`correlated_operation` mints an identifier per `Engine._tracked` call and binds
it for that call's duration; a nested scope mints its own and restores the outer
on exit; every emitter reads the ambient value and never sets one. So one
correlation value names one `AssistantEngine` operation, and the join is a
lookup rather than a heuristic.

**The seam is the discriminator rather than anything about the record, because
the record's own provenance is not in the trace.** A written id is an opaque
`Identifier` under ADR-0119 §2; its `BeliefBand`, its `MemorySource` and its
`Attestation` are Tier 1-adjacent structure the trace deliberately does not
carry. So "was this a user's correction?" cannot be asked of the record. It can
be asked of the operation, because ADR-0083 §8 makes every scheduler job a public
`Engine` call and `Engine._tracked` labels each with the method's own name. The
answer is coarser — it attributes a write to a *cause*, not a provenance — and it
is the one the stream can give.

**`observe` is in the user set, and that is a judgement worth stating.** The
observation stage mines a conversation's episodes into proposals: the content
originates with the user even though the proposal is the model's. A supersession
reached that way is the user correcting the system through the only route the
system offers. What it is not is a *direct* user act, which is why §6 needs the
narrower set.

**Two lists rather than a denylist, and an unclassified count rather than a
default.** Every public `Engine` method carries a seam, most of them write no
memory at all, and a later one might. Defaulting an unrecognised seam into either
list would silently absorb a new writer into a measure, which is how a measure
starts meaning something different without anybody deciding it should. An
unclassified count that rises is a visible prompt to classify the new seam.

**Attribution costs the report a second pass, and the reason is worth stating so
an implementer does not assume otherwise.** An `OPERATION` trace is emitted
*after* the work it wraps, so every `MEMORY_WRITE` it encloses precedes it in
insertion order. A single forward pass therefore meets writes before their
operation. The walk is resumable from the floor and the store is append-only
(ADR-0119 §7a), so a second walk is well defined; buffering unresolved writes
within one walk is equally admissible. This ADR fixes the answer, not the number
of passes.

### 4. Memory precision is one minus the rate at which surfaced records are later overturned by the user

> **Normative.** A **surfacing** is a pair of a `RETRIEVAL` trace `r` eligible
> under §2, whose `occurred_at` lies in `W`, and one id in
> `r.records[TraceRecordSet.RETURNED].ids`. The same id returned by two
> retrievals is two surfacings.

> **Normative.** A surfacing `(r, i)` is **overturned within `s`** exactly when
> some `MEMORY_WRITE` trace `w` satisfies all four of: `i` appears in
> `w.records[SUPERSEDED].ids` or in `w.records[RETIRED].ids`, in a set eligible
> under §2; `r ≺ w`; `w.occurred_at ≤ r.occurred_at + s`; and `w` is attributed
> to a **user** seam under §3.

> **Normative.** **Memory precision** over `(W, s)` is `1 − (overturned
> surfacings ÷ surfacings)`. It is defined only when there is at least one
> surfacing and the last retained trace's `occurred_at` is at or after `b + s`.

> **Normative.** The **machine overturn rate** over `(W, s)` is the same ratio
> computed with the **machine** seam set in place of the user set.

> **Normative.** The machine overturn rate is a diagnostic reported beside memory
> precision, and is never folded into it.

**What this measures, said plainly, because the name promises more.** It is the
rate at which the system surfaced a belief that the user's own subsequent
activity retired. It is *not* retrieved-and-relevant over retrieved, and it
cannot be: relevance is a judgement about content and the stream carries none
(ADR-0119 §2). Every wrong belief the user never corrects counts here as
correct, so this figure is an **upper bound** on precision as VISION means it. The
bound is the honest one available and it is stated in the measure's own
definition rather than in a footnote.

**It is nevertheless the right instrument for the claim leg 7 handed over.** That
claim is comparative — did months of use make retrieval *noisier* — and a bound
that is biased in a fixed direction still answers a comparison across windows,
provided the windows are comparable. §8's settling parameter is what makes them
comparable, and the machine overturn rate reported beside it is what shows
whether a change came from the user or from a job.

**Surfacings rather than distinct records, deliberately.** A belief surfaced in
ten turns and then retired was wrong in front of the user ten times, and
precision is a statement about what the user was shown. Counting distinct records
instead would answer a different question — what fraction of the *corpus* is
wrong — and would need a corpus count, which ADR-0119 §5's denominator rule puts
outside the stream. The per-record variant is therefore not offered as an
alternative reading of the same number; it is a different measure and is not
defined here.

**`SUPERSEDED` and `RETIRED` both count, and `REINFORCED` does not.** A
supersession retires what the target held (`MemoryDecisionKind`'s own docstring:
"the applier retires what the target held and carries **nothing** of it across"),
and ADR-0110's coverage reconciliation closes a window on a belief a covered
reading no longer supports. Both are the system ceasing to hold what it surfaced.
A reinforcement is the opposite and is §6's subject.

**A `SUPERSEDE`'s `WRITTEN` id is not an overturn and must not be counted.**
ADR-0045 §4 makes a supersession install the correction at a freshly-minted id,
and `_WRITE_DISPOSITIONS` in `memory/ingest.py` puts that id under `WRITTEN`; the
displaced ids travel separately under `SUPERSEDED`. A definition that joined on
`WRITTEN` would count the *correction* as the thing overturned. The sets exist to
make that distinction, which is ADR-0119 §3's reason for refusing "a flat
sequence of ids".

**Insertion order decides "later", and the residue is named.** A retrieval and a
write whose emissions interleave — a long retrieval finishing after a write that
began later — would be ordered by their appends rather than by their starts. The
window is at most one emission latency wide, both candidate orders have a defect,
and `occurred_at` has the worse one: ADR-0119 §7a rules it neither total nor
stable, so a tie or an inversion there is unresolvable rather than merely rare.

**Why the numerator is scoped to user-attributed writes and the machine rate is
reported apart.** A consolidation job that supersedes a belief is the system
revising itself, which may be an improvement; counting it as evidence the system
was wrong in front of the user is a category error, and pooling the two is how
#829's natural experiment would be destroyed in exactly the way it warns about.
Reporting the machine rate beside it costs one line and is what makes the arming
legible: the arming should move the machine rate and leave precision's numerator
alone, and if it does not, that is a result rather than a confound.

### 5. The correction rate is the share of rulings that overturned a held belief

> **Normative.** The **ruling population** over `W` is every `MEMORY_WRITE` trace
> eligible under §2 whose `occurred_at` lies in `W` and which is attributed to a
> **user** seam under §3.

> **Normative.** **Rulings** is the sum, over that population, of the six
> `decisions_*` metric values, and **corrections** is the sum, over the same
> population, of `decisions_supersede`.

> **Normative.** The **correction rate** over `W` is corrections ÷ rulings,
> defined when rulings is positive.

> **Normative.** The denominator is the sum of the six decision counts and
> **never** the `proposals` metric, even though the two agree on a completed
> crossing.

**The denominator rule is ADR-0119 §5's co-lossiness requirement taken
literally.** ADR-0119 §5 demands a denominator "drawn from the same stream", and
its argument is that "a ratio of two quantities that lost rows at the same rate
survives the loss". `proposals` and `decisions_supersede` do *not* lose at the
same rate: `proposals` is an entry quantity, present on the fault path, while
the decision counts are absent there unless a partial reading supplied them. A
rate over those two would understate itself by exactly the crossings that
faulted before ruling. The six counts are observed by one act and lost by one
act, so their sum is the denominator the rule actually asks for.

**A correction is a `SUPERSEDE` and this ADR says why that is the whole of it.**
ADR-0092's title is the definition — "a user assertion retires" an attested
belief — and ADR-0045 §4 fixes the mechanics: the target's window closes and the
correction lands at a fresh id. `REJECT` is the policy declining a proposal, not
the user overturning a belief. `ASK_USER` defers rather than decides. `ACCEPT`
and `STORE_TEMPORARY` add. `REINFORCE` agrees. One ruling kind means "what was
held is now wrong", and it is the one counted.

**Corrective acts, not beliefs overturned, and both are available.** A single
correction may retire several beliefs — ADR-0079's title is "a correction
resolves every conflict it is shown" — so `decisions_supersede` counts acts while
`records[SUPERSEDED].total` counts beliefs. The rate is over acts, because the
question "how often does the user have to correct us" is about occasions. The
beliefs-per-correction figure is reported beside it as a diagnostic, computed
from `total` rather than from `len(ids)` so a truncated set costs it nothing —
`RecordIdSet` keeps the true total through truncation by construction.

**`Engine.forget` is a correction this rate cannot see, and the gap is stated
rather than papered over.** A user deleting a belief outright is the strongest
correction signal the system has, and `MemoryStore.delete` emits no trace at all:
the only record is an `OPERATION` trace at the seam `forget`, carrying an
outcome, a duration and no record id. So an explicit deletion enters neither this
rate nor §4's numerator. §12 files it; the cost of closing it is an emitter, not
a vocabulary addition, because `TraceRecordSet.RETIRED` already exists.

### 6. The repeated-explanation rate counts direct user acts that added nothing new

> **Normative.** The **direct ruling population** over `W` is every
> `MEMORY_WRITE` trace eligible under §2 whose `occurred_at` lies in `W` and
> which is attributed to a **direct** seam under §3.

> **Normative.** The **repeated-explanation rate** over `W` is the sum of
> `decisions_reinforce` over that population, divided by the sum of the six
> `decisions_*` values over the same population, defined when the denominator is
> positive.

> **Normative.** `decisions_reinforce` under the `observe` seam is **not** part of
> this measure, and is not admissible as a substitute for it.

> **Normative.** The report states the `observe` reinforcement share separately,
> labelled as the observation stage's re-mining overlap.

**What a `REINFORCE` means is fixed by the enum and it is the right event.**
`MemoryDecisionKind`'s docstring: "`REINFORCE` — the incoming record agrees with
the target and strengthens it." A direct user act that produces a reinforcement
is the user supplying a belief the system already held — which is a repeated
explanation, whether the user volunteered it (`learn`) or the system asked
(`answer`). Both readings describe the same defect: the system made the user
provide what it had.

**The `observe` exclusion is the finding that shaped this measure, and it is not
a nicety.** `orchestration/observation.py` records that "There is no durable
cursor either — a repeat folds into a `REINFORCE`", which ADR-0077 §8 chose
deliberately because the producer's confidence is deterministic and a fold takes
the maximum. Successive observation batches overlap by design, so their
reinforcements are dominated by the *stage re-reading the same episodes*. A rate
computed over them would move when the observation cadence or batch size moved —
both of which are on `service/configuration.py`'s allowlist as
`observation_interval_seconds` and `observation_batch_size`, which is how an
operator would discover the confound, months late, as a step change with no
product meaning. Excluding the population is the only honest option available
without an emitter change.

**The cost is a small population, and it is accepted rather than hidden.** Today
`learn` and `answer` are low-volume operations, so this rate will be noisy early
and will sharpen as the window lengthens. That is a worse instrument than the
other two and it is still the right one: the alternative is a larger population
measuring something else. The report states the denominator alongside the rate,
so a figure computed over four rulings is visibly a figure computed over four
rulings.

**What would make it the measure VISION names.** VISION's phrase is "reduction in
repeated explanations", which is about the user re-explaining because the
assistant failed to use what it knew. The trace-visible form of that is a turn
whose retrieval surfaced nothing, followed by a write reinforcing a record the
store already held — and `records[REINFORCED]` carries exactly the pre-existing
record's id (`MemoryIngestResult.record_id`: "For a `REINFORCE` it is the
reinforced record's id"). What is missing is the link from the write back to the
turn: the observation stage runs as its own operation, and no emitter populates
`TraceRef.CONVERSATION` or `TraceRef.TURN`. Both members already exist, so
closing this is an emitter lane and not an ADR-0119 §13e vocabulary ADR. §12
files it.

### 7. Three diagnostics travel with the measures and none of them is one

> **Normative.** The report carries three diagnostics beside the measures: the
> #824 shortfall watch, the operation-latency summary, and the stream-health
> counts.

> **Normative.** No diagnostic is a measure of this ADR, none carries a threshold
> verdict, and none may be substituted for a measure.

**The #824 shortfall watch, defined inside the bound the emitter imposes.** #824
arms its mitigation on "leg 8's telemetry showing a real store developing
topic-concentrated window-closure approaching the measured threshold", and #799
established the threshold as filtered-neighbour density crossing `fetch_k −
limit`. Define a **saturated shortfall read** as a `RETRIEVAL` trace carrying
`limit`, `fetch_k`, `candidates`, `returned` and the four `excluded_*` keys —
the eight this figure reads — with `returned < limit` and `candidates ≥
fetch_k`: the KNN ceiling bound the candidate set, and the page did not fill. On
exactly those reads the filter loop ran to exhaustion, so `returned +
excluded_kind + excluded_retention + excluded_window + excluded_band` equals
`candidates` and the counts are a partition rather than a prefix. The watch is
two figures over `W`. The first is the **shortfall incidence**: saturated
shortfall reads divided by every `RETRIEVAL` trace in `W` carrying those same
eight keys, which is the population the question is about — a read that never
reached the filter pass carries none of them and is neither a shortfall nor a
healthy read. The second is the **window share** of each shortfall,
`excluded_window ÷ (candidates − returned)`, defined for a read where the two
differ; a shortfall read that excluded nothing is one the KNN ceiling alone
bound, and is counted in the incidence and left out of the share.

**The consistency rule is the same argument as the integrality rule, one level
up.** Each of the eight counts can be individually valid and jointly impossible —
`candidates = 0` with `returned = 1` satisfies every per-value rule and makes
`candidates − returned` negative, which would be reported as a window share below
zero. `SqliteMemoryStore` cannot produce it: `returned` counts a subset of the
rows `candidates` counts, and the filter loop's exhaustion is what makes the
partition hold. But the emitter's arithmetic is not the type's, and a diagnostic
that divides by a difference must know the difference is non-negative. Excluding
the trace from this diagnostic alone, rather than from every population, is
deliberate: `records[RETURNED]` is observed independently of the counters, so a
trace whose counters disagree can still tell §4 which ids came back.

**And the half of #824's trigger this cannot see is stated.** "Approaching" the
threshold would be read off healthy reads as headroom, and healthy reads are
exactly the ones whose counters are a prefix, because `_search_sync` breaks at
`limit`. So the watch reports *incidence* and cannot report *headroom*. Closing
that is an emitter change — count the whole candidate set rather than the
examined prefix — and it adds no metric key and no vocabulary member. §12 files
it, and #824's trigger is readable meanwhile because a threshold effect that is
"0% below it, 100% above it" announces itself as incidence.

**The latency summary is #829's other baseline half and needs no new definition.**
#829 asks for "a precision/latency baseline". Every `OPERATION` trace carries
`elapsed`, measured by `perf_counter` around the work; the summary is that
distribution over `W`, per seam. It is a diagnostic and not a measure because it
answers "is the hub fast" rather than "is the user model getting more accurate",
and because it is not a rate — ADR-0119 §5's rule binds measures, and a latency
summary makes no claim about a population it might have lost rows from.

**The stream-health counts are what let a reader distrust the rest.** The report
states, over `W`: traces walked by kind; the count excluded as truncated, as
unattributed, as unclassified, and as malformed; the instant of the oldest and
newest retained traces; and every `CONFIGURATION` trace with the gap to the trace
preceding it. ADR-0119's own consequences record that "the stream cannot report
its own completeness" — traces lost to an emission failure are logged and not
counted — so these counts are not a completeness claim. They are the exclusions
this ADR's own rules caused, which is a different and fully computable thing.

### 8. A window is partitioned at every configuration change, and settling is equalised across the parts

> **Normative.** The report partitions `W` at every `CONFIGURATION` trace whose
> metric mapping differs from that of the preceding `CONFIGURATION` trace in the
> stream, and states every measure for each part as well as for `W` whole.

> **Normative.** A `CONFIGURATION` trace whose mapping equals its predecessor's
> partitions nothing.

> **Normative.** For every `CONFIGURATION` trace that has a predecessor of any
> kind in the retained stream, the report states the interval from that
> predecessor as an **upper bound** on how long the hub was not running.

> **Normative.** A part whose end is later than the newest retained trace's
> `occurred_at` less `s` carries no memory-precision figure, and the report says
> so rather than reporting a figure over an unequal settling.

> **Normative.** Over an **empty** retained stream the report states that the
> stream is empty, states no measure and no diagnostic, and applies no window
> validation. Every clause of this ADR naming the oldest, the newest or the last
> retained trace presupposes a non-empty one.

> **Normative.** The report refuses a window whose start precedes the oldest
> retained trace's `occurred_at`, naming both instants. A retention horizon that
> has swept the window's early traces makes the figure a statement about a
> different period than the one asked for.

**The empty stream is stated because it is reachable and every other clause
assumes it away.** A hub that has just opened its seventh database has written
nothing, and a horizon that has swept everything leaves the same state; ADR-0119
§10 makes the second a normal outcome rather than a fault. Without this clause an
implementation must crash, invent an instant, or disobey a reporting clause, and
the three would disagree. Saying "empty" is the honest answer and it needs no
figure to carry it.

**The partition is what turns ADR-0119 §9's stamp into an answer rather than a
record.** ADR-0119 §9 made every startup stamp the effective configuration so a
before/after would be datable, and #829's requirement 2 is that "the arming
moment is stamped somewhere telemetry can see — a before/after nobody can date is
two opinions". Partitioning on the diff is that requirement discharged at the
reading end: the operator does not date the intervention and then choose two
windows by hand; the report finds the change and reports the two sides.

**Settling is a parameter of the measure because a trailing edge is a bias, not a
noise term.** Every surfacing in a window must have had the same opportunity to
be overturned, or the last day of the window contributes systematically fewer
overturns than the first. That understates the overturn rate — overstates
precision — by an amount that grows as the window's end approaches the report,
which is exactly when an operator reads it. Bounding the numerator's search at
`r.occurred_at + s` and refusing the figure until the stream extends `s` past the
window makes every surfacing's opportunity identical, and makes two windows
comparable when their `s` agree. That is the precondition #829's before/after
needs and cannot supply for itself.

**Downtime inside the settling period is a residue, and it is declared rather
than corrected.** `s` is wall-clock, and a hub that was down for part of it gave
its surfacings less real opportunity to be contradicted. Correcting for that
would need an "active time" denominator the stream does not carry as a
population. So the report states the restarts and their bounding gaps (§7) and
leaves the judgement with the operator, which is the same disposition ADR-0119 §9
took when it noted that "a gap between a shutdown and the next configuration
trace is a hub that was not running, which a measure must not read as a period of
no activity".

**The report's own act is dated by the instrument.** Reading a measure requires
stopping the hub (§9), and restarting it emits a `CONFIGURATION` trace. So the
measurement leaves a footprint in the stream it measured, under the second clause
above, and a later reader can see when each reading was taken.

### 9. The measures are computed by an offline report, and this ADR adds no contract surface

> **Normative.** The measures are computed by a **reporting tool that runs while
> the hub is stopped**, in its own process, and never by the hub.

> **Normative.** The reporting mechanism lives in `ai_assistant/evaluation/`, it
> is wired in `app/composition.py`, and its console entry point lives in
> `ai_assistant/service/` and imports no subsystem directly.

> **Normative.** The tool takes `<data_dir>/hub.lock` before it opens any store
> and holds it until it exits. A contended lock is refused immediately with a
> diagnostic naming the data directory and the lock path; the tool does not
> retry.

> **Normative.** No `AssistantEngine` method, no wire operation and no
> `assistant` CLI command is created for reading traces or measures.

> **Normative.** The tool's entry point is its **own** console script, beside
> `ai-assistant-hub` and `ai-assistant-reembed`, and never an `assistant`
> subcommand.

> **Normative.** No Protocol in `core/protocols.py` changes, and no type, enum
> member or constant is added to `core/types.py`.

> **Normative.** No component of the request pipeline computes, holds, caches or
> consults a measure, and no measure is an input to anything the system does.
> ADR-0119 §7's prohibition on reading a trace back stands unchanged and is not
> narrowed by the existence of a reader outside the pipeline.

**Three shapes were available and two of them breach a ratified clause.**

*An `Engine` maintenance-side operation* — the shape ADR-0119 §10's trace purge
takes — is refused, and not on taste. ADR-0119 §7 rules that "no component of
the request pipeline — `orchestration`, `memory`, `context`, `planning`, `readers`,
`learning`, `tools`, `permissions` — holds a seam carrying the **walk**, and none
reads a trace back", and the `Engine` is `orchestration`. The purge is reachable
because `TraceRetention` is a *different* seam from `TraceStore`; there is no
such narrowing for the walk, by construction. `pyproject.toml`'s "nothing imports
the evaluation package" contract makes the same thing mechanical. Taking this
shape would need an amendment record on ADR-0119 §7 and an addition to
`AssistantEngine` against ADR-0085 §1's "and nothing else", to buy a capability
whose absence is the property ADR-0119 §7 exists to protect.

*A CLI command reading through the API* is refused twice over. It needs a wire
operation, and the wire's operations are `AssistantEngine`'s, so it reduces to
the first shape; and putting the computation in `interfaces/` breaches golden
rule 3, while putting it behind the adapter breaches ADR-0083 ruling 4's "the API
is the only door".

*An offline tool* is refused by nothing and is named by two ADRs. ADR-0083 §10 —
the ruling that establishes exclusivity — says in its own words: "Everything else
that needs the data goes through the API, **or runs while the hub is stopped**. An
offline tool — the re-embedding migration (#425) is the first and for now the only
one — takes the same instance lock, which serialises it against the hub by
construction and needs no new mechanism." And ADR-0119 §15 leaves open "whether
the measures lane reads them through the API or offline in the shape ADR-0104's
re-embedder uses". This takes the second option by the route both texts name.

**The console script is not the CLI command the clause above forbids, and the
two are kept apart because the corpus already keeps them apart.** What is refused
is a measure reachable from the assistant client — an `assistant` subcommand, or
anything routed over the wire — because that is the read path ADR-0119 §7 exists
to prevent and because `interfaces/` may hold no business logic (golden rule 3).
What is required is a separate console script, and ADR-0084 §6's reasoning makes
that the only available shape rather than a preference: a subcommand "would live
in `interfaces`, which would then have to import `service` — and ADR-0083 §8
forbids anything importing `service` at all", which is why `ai-assistant-hub` and
`ai-assistant-reembed` are their own scripts and not `assistant hub` and
`assistant reembed`. The reporting tool is the third of that family.

**The placement inside that shape is forced rather than chosen.** ADR-0104 §5
settles it for the re-embedder and every term transfers: the entry point must
take the instance lock, the lock lives in `service/lock.py`, `lint-imports`'
"nothing imports the service" contract means the entry point has to *be* in
`service/`, and `service` "may import `app` … and `core`" (ADR-0083 §8) so it
reaches the mechanism through the composition root. The mechanism belongs in
`evaluation/` because that is the package that already implements the three trace
Protocols, that `pyproject.toml` restricts to `core` and nothing else, and that
no subsystem may import — which is the same contract that makes ADR-0119 §7's
prohibition mechanical. A measure computed there is unreachable from the
pipeline by the architecture checker, not by a promise.

**No `core` type crosses a boundary, and that is why golden rule 5 does not
bind.** The tool consumes `EvaluationTrace`, `TraceChunk` and `TracePosition`,
all of which `core/types.py` already carries, through `TraceStore.walk`, which
`core/protocols.py` already declares. Its result is produced in `evaluation/`,
handed to the entry point through `app`, and rendered there — the same indirect
route `service/reembed.py` takes to `build_reembedder`, which the "nothing
imports the evaluation package" contract permits because it forbids only the
*direct* edge. A report type in `core/types.py` would be a type that crosses no
subsystem boundary, which is the opposite of what `core` is for
(`CLAUDE.md`: "Public data that crosses subsystem boundaries is a pydantic model
in `core/types.py`").

**The accepted cost is that reading a measure requires stopping the hub, and it
is small for the reason ADR-0104's is.** A measure is read at a decision point —
is the baseline long enough, what did the arming do, is the exit test met — not
on a monitoring loop; the tool is a walk over a store of numbers and ids and
returns in seconds; and ADR-0083 §1 gives the supervisor an automatic restart. The
alternative buys a permanently-open read path into the instrument, and a read
path that exists is a read path a later lane can consume, which is the failure
ADR-0119 §7 spent a whole clause and an import contract preventing. Paying an
operator act to keep that door shut is the better trade while there is one hub
and one operator.

**One capability of the store is used and the others are not.**

> **Normative.** The reporting tool calls `TraceStore.walk` and no other member
> of the trace store's contract.

> **Normative.** The reporting tool emits no trace and purges none.

### 10. The report reads the trace store only, and prints no identifier

> **Normative.** The reporting tool opens no store but the trace store, and never
> resolves a record id against another one.

> **Normative.** No figure the report states is derived from anything but retained
> traces.

> **Normative.** The report's output carries counts, rates, instants, seam labels
> and metric keys. It carries **no** record id, correlation id or trace id.

> **Normative.** The report is Tier 2 under ADR-0004 §1 and never leaves the
> device.

> **Normative.** This ADR creates no designated seam under ADR-0017, and no
> opt-in that would enable trace or measure egress.

**Reading only the trace store is what keeps a measure a statement about
events.** ADR-0119 §8 refuses to derive corrections "from what the store now
holds, which is a measure of the present rather than a record of an event", and
the same objection applies to any resolution step: a record deleted since it was
surfaced would drop out of a population it belonged to, and a record edited since
would be judged on content it did not have. ADR-0119 §10 additionally makes a
dangling reference *correct* — "an opaque id that now resolves to nothing … the
deletion does not un-happen the retrieval" — so a report that resolved ids would
turn the ratified behaviour into a failure mode.

**Printing no id is a cheap rule that closes the one bridge left.** An opaque id
in a report is Tier 2 by ADR-0119 §2's own reasoning and identifies nobody. What
it does is invite the operator to go and look it up, which is the resolution step the
clause above refuses, performed by hand. The measures need no id to be checked —
every figure is a count over a population defined by rules a second
implementation can re-run — so nothing is lost.

### 11. What the measures cannot see, stated as limits

> **Normative.** Nothing in this ADR is to be read as a measure of relevance,
> correctness, helpfulness or user satisfaction. Each measure is a rate over
> observed system events and is bounded by what those events can distinguish.

The list is the honest accounting ADR-0119 §2's content rule forces, and each is
a real question a reader of the numbers will ask.

- **Semantic judgement of any kind.** No query, no belief content, no utterance
  and no model output is in the stream (ADR-0119 §2). So a retrieval that
  returned ten plausible-but-useless records and one that returned ten perfect
  ones are the same trace.
- **A wrong belief nobody corrects.** §4's numerator requires an overturning
  write. Silence counts as correctness, which is why §4 calls itself an upper
  bound.
- **An explicit deletion.** `Engine.forget` writes no record id to any trace
  (§5), so the most decisive correction the user can make is invisible to both
  §4 and §5.
- **The conversation a write came from.** `TraceRef.CONVERSATION` and
  `TraceRef.TURN` exist and no emitter populates either, so a reinforcement
  cannot be joined to the turn that produced it and §6 cannot be defined the way
  VISION phrases it.
- **A record's band, source or attestation.** Not carried, so no measure here
  decomposes by belief band or by provenance of the record — only by the cause of
  the operation (§3).
- **Band-scoped exclusion at retrieval.** `excluded_band` is a structural zero
  under ADR-0113 §2; `bands` says only that a restriction was in force.
- **Headroom on a healthy retrieval.** The `excluded_*` counters are a prefix on
  any read that filled its page (§7).
- **Identity in a large retrieval.** A read returning more than 256 records
  declares truncation and leaves §4's population (#848). Every production caller
  is bounded far below the cap today, so the loss is zero and observable when it
  stops being.
- **The stream's own completeness.** A trace lost to an emission failure is
  logged and not counted; ADR-0119 states this as an accepted property. ADR-0119
  §5's denominator rule is what keeps the measures usable despite it, and is why
  no measure here counts an absolute.

### 12. No trace vocabulary is added, and the four gaps are filed with their costs

> **Normative.** This ADR adds no member to `TraceKind`, `TraceOutcome`,
> `TraceRef` or `TraceRecordSet`, defines no new metric key and requires no
> emitter to carry a quantity it does not carry today. ADR-0119 §13e's gate is
> not reached.

**Every definition above was checked against the merged emitters before it was
written, which is the property this clause is really claiming.** §4 joins on
`records[RETURNED]`, `records[SUPERSEDED]` and `records[RETIRED]`; §5 and §6
read the six `decisions_*` keys; §3 reads `refs[CORRELATION]` and the seam of an
`OPERATION` trace; §7 reads `fetch_k`, `candidates`, `returned`, the four
`excluded_*` keys and `elapsed`; §8 reads the `CONFIGURATION` allowlist. All of
them are emitted on `main`.

**Four gaps are named rather than closed, because each costs an emitter lane and
none of them blocks a measure this ADR defines.** ADR-0119 §13e permits a
ratified ADR to add vocabulary; this one declines, because adding a member is
the one change that would make this a contract ADR, and no member is needed —
every gap below is a matter of *populating* what the vocabulary already declares.

1. **No emitter populates `TraceRef.CONVERSATION` or `TraceRef.TURN`.** Closing
   it makes §6 definable as VISION phrases it and enables the retrieval-miss join.
   Cost: emitter work at the engine boundary and in the observation write path.
   No vocabulary addition.
2. **`Engine.forget` carries no record id.** Closing it puts explicit deletions
   into §4's numerator and §5's rate. Cost: either a `records[RETIRED]` on that
   operation's trace or a new emitter at the store's delete seam. `RETIRED`
   already exists.
3. **`_search_sync`'s counters stop at `limit`.** Closing it makes #824's
   "approaching" half readable. Cost: counting the whole candidate set on a read
   that fills its page, against a small cost on the hot retrieval path.
4. **`Settings.consolidation_interval` does not exist**, so #829's arming is not
   yet a diff between two `CONFIGURATION` traces and §8's partition will not
   find it. `core/config.py` withholds the field pending the lane that re-adds
   it. Until then the arming is datable only by ADR-0119 §9's stated fallback —
   "the **first `OPERATION` trace whose seam label is consolidation's** dates the
   arming from above" — which dates the first *run* rather than the
   configuration change. Nothing here re-adds the field or brings the arming
   forward; #829 owns both.

### 13. What this records against earlier ADRs, under ADR-0082 §1

ADR-0082 §1 puts the judgement in this ADR's text, and the test is ADR-0070 §1's:
*would a reader holding only the earlier ADR now act differently, or read one of
its clauses more widely than it now holds?* Applied to each place a record looks
owed. **None is owed.**

**ADR-0119 §15's first and fourth bullets — not owed, and this is the closest of
the set.** They defer "the measures' definitions" and "the inspection and report
surface" to a follow-on slice, and name the two candidate shapes for the second.
This ADR supplies the first and takes one of the two named shapes for the second.
A reader holding only ADR-0119 defers both, before and after. Discharging a
deferral by the route the deferral itself named is "the mechanism working"
(ADR-0102 §13, quoting ADR-0100 §11).

**ADR-0119 §1 — not owed.** Its second clause binds *traces*: "No
`EvaluationTrace` carries a rate … and no emitter computes one." Every rate here
is computed outside every emitter, by a tool the pipeline cannot reach. That is
the arrangement ADR-0119 §1's own reasoning asks for — "a rate computed over the
stream is computed over a window somebody chose" — so it is obedience, not
amendment.

**ADR-0119 §5's denominator rule — not owed.** This ADR's §1, §5 and §6 obey it,
and §5's commentary explains where the obligation bites. No sentence of it
becomes wider.

**ADR-0119 §7 — not owed, and it is the one most worth checking.** Its second
clause names eight packages and says none of them holds a seam carrying the walk
or reads a trace back. `evaluation` is not among the eight, has never been a
pipeline component, and is the package `pyproject.toml`'s contract forbids all
eight from importing. This ADR's §9 fourth clause restates ADR-0119 §7's
prohibition rather than narrowing it, and the reporting tool runs in a different
process from the hub entirely. A reader holding only ADR-0119 keeps the walk out
of the pipeline, before and after.

**ADR-0119 §13e — not owed.** §12 adds no member to any of the four
enumerations, so the gate is not reached and its price is not paid or waived.

**ADR-0083 ruling 4 and §10 — not owed**, on ADR-0102 §13's reasoning and
ADR-0119 §14's application of it. The decision is that the hub owns the databases
exclusively and the API is the only door; ADR-0083 §10 states the exception in
its own words and requires the instance lock, which this ADR's §9 takes. "The
re-embedding migration … is the first and for now the only one" is a dated
observation in a dated document, as "the five SQLite databases" was when
ADR-0119 opened the seventh. A reader holding only ADR-0083 acts identically.

**ADR-0104 §5 and §6 — not owed.** §9 borrows the mechanism for a second offline
tool. Nothing about re-embedding moves, its lock discipline is unchanged, and
ADR-0104 §6's "re-embedding is never automatic" is untouched — as is the
reporting tool, which is likewise never automatic and for a weaker reason:
nothing schedules it.

**ADR-0085 §1's "and nothing else" — not owed.** No method is added to
`AssistantEngine`, and §9's third clause says so as a ruling rather than as an
omission.

**ADR-0004 §2's telemetry clause — not owed.** ADR-0119 §12 argued it for the
store; the report is a local rendering of local Tier 2 data and transmits
nothing. §10's third clause makes it a ruling.

**ADR-0111 §9 and §11 — not owed.** ADR-0111 §9's one-record rule is about
emission and nothing here emits. ADR-0111 §11's ruling that arming a
shipped-disabled job is "an implementation lane's act against this text once
ratified" is untouched: §12 item 4 records that the arming is not this ADR's,
and §8 only reads the stamp.

**ADR-0113 §2 and ADR-0079 §3 — not owed.** Each is cited for a fact it already
decides — the band bound before the cut, and a correction resolving every
conflict it is shown — and neither acquires an obligation here.

**Addition, in ADR-0102 §13's form.** A reviewer who reads any of these the other
way is invited to name the sentence of the earlier ADR that becomes false or
over-wide, which is the showing ADR-0082 §1 requires of a demand for a record.

### 14. What this ADR does not decide

- **The baseline's duration.** #829 says "the baseline's duration and the
  precision measure's design are leg 8's own slices"; this ADR takes the second
  and leaves the first with the operator. §8 supplies what the choice needs — the
  settling rule that says when a window is readable at all.
- **The arming moment**, which is #829's and an operator's act under ADR-0111
  §11. §8 partitions on it; it does not schedule it.
- **The numbers.** No target, no threshold and no expected value is set for any
  measure here. Leg 8's exit is the operator ruling on data, and a threshold
  written now would be an opinion pre-empting the data.
- **Which of VISION's other measures come next.** The roadmap picked three; the
  other nine are not refused here, and each would need the same treatment against
  the stream that §12 gave these.
- **#824's mitigation**, which stays behind its trigger. §7 makes the trigger
  readable and selects nothing.
- **#848's cap question**, which stays open with its three named options.
- **Whether erasure sweeps traces**, which ADR-0119 §15 files as a privacy
  decision of its own.
- **The report's output format** beyond §10's content rules — whether it renders
  text, JSON or both is the implementing lane's, since nothing depends on it.

## Consequences

**Leg 8's exit test becomes a procedure.** Accumulate a baseline with
consolidation unarmed; arm it; wait `s` past the window's end; stop the hub; run
the report; read the two parts §8's partition produces. Every step is now named,
and the one step that was missing — what number to read — is §4, §5 and §6.

**Leg 7's handed-over claim becomes testable rather than assertable.** Memory
precision over successive windows of equal settling answers "did months of use
make retrieval noisier", which is what leg 7 refused to assert without an
instrument. It answers it as a bound rather than as a point estimate, and the
bound's direction is fixed and stated.

**#829's natural experiment survives the arming.** §3's attribution and §4's
machine overturn rate mean the arming moves a diagnostic and leaves the measure's
numerator alone unless something real changed. Without the split, the arming
would have moved every figure and the experiment would have produced a number
nobody could interpret.

**Reading a measure costs a hub restart.** That is the price of §9's placement and
it is the visible cost of this decision. It also means measurement is punctuated
rather than continuous, so nobody will watch these numbers hourly — which is
mostly a feature, since a rate over a short window of a single-user system is
noise.

**Three of the four gaps §12 files are worth closing and none is urgent.** The
conversation ref is the largest: it is what stands between §6 and the measure
VISION actually names, and it costs an emitter lane rather than a contract
change. The others buy incidence-plus-headroom on #824's trigger and explicit
deletions in the correction rate.

**The repeated-explanation rate ships weakest, deliberately.** Its population is
small and it will be noisy for a while. The alternative — the reinforcement rate
under `observe` — has a large population and measures the observation stage's
batch overlap, which is a number that would have looked like a product measure
for as long as nobody checked. Shipping the honest narrow one, with the wide one
labelled beside it as what it is, is the trade this ADR takes.

**What becomes harder: adding a fourth measure quickly.** Every definition here
had to be checked against what the emitters carry, and §12's four gaps are what
that check found. A fifth measure gets the same treatment, and the odds are good
that it too finds a field that is not emitted. That is the intended friction: the
alternative is a measure defined over a field somebody assumed.

## Alternatives considered

**Precision as retrieved-and-relevant over retrieved.** Refused; §4. It needs a
relevance judgement per (query, record) pair, and the stream carries neither the
query nor the content. Approximating it with a model-judged relevance step would
put the model back inside the instrument, which is the circularity ADR-0119 §7
forbids by construction, and would send Tier 1 content to a provider to compute a
Tier 2 number.

**Rates per turn, per conversation or per day.** Refused; ADR-0119 §5's
denominator rule, argued at §5 above.
Each takes its denominator from a count the stream does not carry as a
co-observed population, so each loses rows at a different rate from its
numerator. "Per unit time" additionally moves when the hub is down.

**Pooling user- and machine-caused writes.** Refused; §3. It is the simplest
definition and it destroys #829's experiment, because arming consolidation moves
the pooled figure for reasons unrelated to the question being asked.

**A repeated-explanation rate over `observe` reinforcements.** Refused; §6. It has
the population one would want and it measures the observation stage re-reading
its own overlap, because ADR-0077 §8 chose not to keep a durable cursor. It would
move with `observation_interval_seconds` and `observation_batch_size` and would
look like a product signal.

**Deferring the repeated-explanation measure entirely** until the conversation
ref is emitted. Refused. The roadmap names three measures for leg 8, and a narrow
honest measure over direct user acts is available now, tells the truth, and gives
the follow-on emitter lane something to widen rather than something to invent.

**No settling period — take the window as given.** Refused; §8. The trailing-edge
bias is invisible, is largest exactly when an operator reads the number, and
makes two windows incomparable, which is the one thing #829's before/after
requires.

**An `Engine` maintenance operation computing the measures.** Refused; §9. It
breaches ADR-0119 §7, needs an addition to `AssistantEngine` against ADR-0085 §1,
and would put a permanently-open trace read path inside the pipeline — the thing
ADR-0119 §7's clause and `pyproject.toml`'s import contract exist to prevent.

**A wire operation and a CLI command.** Refused; §9. It reduces to the previous
alternative, since the wire's operations are the engine's.

**A `MeasureReport` model in `core/types.py`.** Refused; §9. It crosses no
subsystem boundary — it is produced in `evaluation` and rendered by the entry
point through `app`, the route `service/reembed.py` already uses — so it would
put a type in `core` for a reason `core` does not exist for, and would turn a
docs-only decision into a contract change with everything golden rule 5 attaches
to one.

**Storing computed measures back into the trace store**, so a report is
incremental. Refused. ADR-0119 §1's first clause makes a trace an event and not
a measurement, ADR-0119 §5 forbids a trace of a trace write, and a stored
measure is a definition frozen at the moment it was computed — the exact thing
ADR-0119 §1 split the design to avoid. Recomputing from the stream is cheap and
always reflects the current definitions.

**Resolving record ids against `memory.db` to enrich the report.** Refused; §10.
It measures the present instead of the record of events, breaks on the dangling
references ADR-0119 §10 rules correct, and opens a second store the tool has no
other reason to hold.
