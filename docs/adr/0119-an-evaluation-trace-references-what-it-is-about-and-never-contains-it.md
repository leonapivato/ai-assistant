# 119. An evaluation trace records an event at a seam, references what it is about, and never contains it

- Status: Proposed
- Date: 2026-08-08
- **Decides `core` surface and implements none of it.** Two new Protocols —
  `TraceSink` and `TraceStore` — in `core/protocols.py`, and the
  `EvaluationTrace` family plus four small enumerations in `core/types.py` (§13).
  No existing Protocol gains a member and no existing signature changes:
  `MemoryStore`, `MemoryWriter` and `AssistantEngine` are all untouched, and §4
  refuses the one change that would have touched `MemoryStore`. Golden rule 5 and
  ADR-0015 §5 put a contract ADR in its own PR, ratified and merged before
  anything implements against it; the triad — Protocols, shared conformance
  suites, canonical fakes — ships in a later lane
  (`CONTRIBUTING.md` → "Adding a Protocol: land the triad together").
  **Its required review set is therefore adversarial *and* architecture**, even
  though the PR carrying it is prose only, for the reason ADR-0117's header
  records: `CONTRIBUTING.md` → "Stop when the required reviews are green" makes a
  change contract-surface "when it is the ADR deciding that surface", and
  `scripts/ship.sh` fires its own architecture requirement on a diff touching
  `core/protocols.py` or `core/types.py`, which this diff does not.
- **This ADR amends nothing and supersedes nothing.** §14 applies ADR-0082 §1's
  test to each of the fifteen places where a record looks owed, and records why
  none is.

## Context

### Leg 8's exit test names an instrument that does not exist

`docs/roadmap.md`'s leg 8 is "Minimal evaluation", and its exit is *"is the user
model getting more accurate?" is answered by data, not opinion*. The leg's first
sentence names the slice this ADR opens — "The `EvaluationTrace` slice — Tier-2
operational data, no egress (ADR-0004)" — and its second names a second job for
the same instrument: "This is also the hub's operational telemetry; a process
that runs for weeks cannot be debugged by rerunning it."

Those are two demands on one artifact, and it is worth stating early that they do
not conflict. A measurement wants a durable, joinable, queryable record with a
known horizon. Operational debugging of a resident process wants exactly the same
thing, because the alternative — reproduce the fault — is the one thing a
weeks-resident hub forecloses. What operational debugging additionally wants is a
*log*, and the hub already has one (ADR-0004 §5, ADR-0083 §6); this ADR does not
replace it and §5 states the relationship.

### Three ratified deferrals and one open trigger route here by name

**ADR-0074** declines to capture a turn that fails, and says where the record
belongs instead: "**A turn that raises before producing an outcome is not
captured**, and the gap is deliberate. There is no exchange to record: the adapter
rendered an error, the engine produced no result, and what failed is *operational*
information — Tier 2, and the subject of leg 8's `EvaluationTrace`, not of Tier 1
memory (ADR-0004 §1)."

**#829**, the operator's leg-8 entry ruling, makes a carrier for configuration
changes an entry criterion rather than a preference: "**The arming moment is
stamped somewhere telemetry can see** — a before/after nobody can date is two
opinions. Whether that is an `EvaluationTrace` config event or another carrier is
the leg-8 lane's design call, but the requirement is entry criteria, not
preference." §9 makes that call.

**#824** defers leg 7's k-shortfall mitigation behind a trigger phrased in this
slice's terms: "leg 8's telemetry (the `EvaluationTrace` slice) showing a real
store developing topic-concentrated window-closure approaching the measured
threshold." That is a *quantitative* demand on one trace kind, and it is the
sharpest available test of whether the shape decided here carries enough: #799
established that k-shortfall is a threshold effect driven by the density of
*filtered* neighbours against `fetch_k − limit`, so a retrieval trace that records
only what came back cannot see the trigger approaching. §8 records what it must
carry instead.

**Leg 7's exit** hands over the claim that months of use made retrieval "not
noisier", explicitly because leg 7 "had no instrument for it and refused to assert
what it could not test". Memory precision is that instrument, and it is computed
over traces rather than defined here (§15).

### ADR-0004 fixes the tier, and the tier fixes the shape

ADR-0004 §1 classifies every stored datum: Tier 0 secrets, Tier 1 personal data
("user-model facts, memories, conversation history, anything identifying the user
or third parties"), Tier 2 operational ("non-sensitive settings, caches, logs
(which must never contain Tier 0/1 data — see §5)"). §5 states the rule directly:
"Logs are Tier 2 only. Tier 0/1 data must never be logged."

The consequence for a trace is the whole of this ADR's shape and not a caveat on
it. Every interesting thing a trace is *about* is Tier 1: a retrieval is about
beliefs, a memory write is about what the system now holds, a turn is about what
the user said. So a trace that is honest about its subject and obedient to its
tier can only be a record that **references** Tier 1 content — ids, counts,
scores, durations — and never contains it. The design question is not whether to
follow that rule; it is whether the rule is a property of the type or a promise
in a review checklist. §2 makes it a property of the type.

### What makes this a decision rather than an implementation detail

Four things, each with a wrong answer that looks reasonable.

1. **The obvious trace type is an attributes bag**, `Mapping[str, str]` or a JSON
   payload, because that is what every structured logger does. It is also the one
   shape in which ADR-0004 §5's rule cannot be enforced by anything but care, on a
   store that will be written by five call sites and read by a measure lane that
   does not exist yet. ADR-0004 §5 answers the same hazard for logs with "a
   redaction processor that drops/masks known sensitive keys … as a safety net" —
   a denylist, which is the right instrument for a stream this system does not
   fully control and the wrong one for a type it does.
2. **A second record for one event looks free, and #710 is the proof that it is
   not.** ADR-0111 §9 had to rule that "an expected refusal produces exactly one
   operational record per run" because a correct deployment was emitting two, the
   second at a severity that made a ratified behaviour look like a failure. A
   trace stream added carelessly beside the log stream is that failure again with
   a new writer, so the relationship between the two records has to be decided
   rather than assumed.
3. **An instrument that can fail the work it measures is worse than no
   instrument**, and an instrument whose failures are silent is worse than one
   that fails loudly. Both directions have to be taken, and they pull against each
   other.
4. **Retention is where a measurement design quietly dies.** A horizon shorter
   than the window, or a count cap that discards the oldest rows, deletes the
   *baseline* — the half of #829's natural experiment that cannot be re-created,
   because consolidation writes durably and "unarming later does not restore one".
   So retention is decided here, with the reason attached, rather than defaulted
   by whoever writes the schema.

## Decision

### 1. A trace records an event at a seam; it is not a measurement

> **Normative.** An `EvaluationTrace` records that a named event occurred at a
> named seam, with its instant, its duration, its outcome, the ids it is about and
> the numbers it observed.

> **Normative.** No `EvaluationTrace` carries a rate, ratio, average, threshold
> verdict or other judgement over more than the one event it records, and no
> emitter computes one.

**The split is what lets measures be redecided without a contract change.** Leg
8's three measures — memory precision, correction rate, repeated-explanation rate
— are named in `VISION.md` → "Measures of Success" and picked by the roadmap, and
none of them has a definition yet. A trace that carried a measure would freeze one
definition into `core/types.py` on the day the first emitter shipped, and the
first refinement would be a contract change. A trace that carries events lets a
measure be a query.

**It also decides the arithmetic's location.** A rate computed inside an emitter
is computed over the window that emitter happens to see; a rate computed over the
stream is computed over a window somebody chose. The second is the only one whose
denominator can be stated.

**A trace is therefore a fact about the system, and a measure is an opinion about
the facts.** That is the distinction leg 8's exit test turns on, and putting it in
the type is cheap here and expensive later.

### 2. A trace references Tier 0/1 content and never contains it, and no string in it is derived from data

> **Normative.** Every `EvaluationTrace` is Tier 2 under ADR-0004 §1. No field of
> the family, at any depth, may carry Tier 0 or Tier 1 content.

> **Normative.** Every string-typed value reachable from an `EvaluationTrace`
> falls in exactly one of four categories: an **identifier** as the third clause
> below defines it; a member of an enumeration defined in `core/types.py`; a
> literal constant written in the emitting module; or the `__name__` of an
> exception class. A string in none of the four appears nowhere in the family.

> **Normative.** Outside the identifier category, no string-typed value in the
> family is derived at runtime from user input, model output, store content, a
> filesystem path, or any other observed datum. An exception's class name is
> admitted by the clause above; its message is not.

> **Normative.** An **identifier** in a trace is an opaque value **minted by this
> system** — a record id, a conversation id, a turn id, an execution id, or the
> trace's own id. What qualifies it is its origin, never its current
> resolvability: an identifier whose referent has since been deleted is still an
> identifier (§10). It is never a label, a name, a title, a query, a snippet or a
> digest of content, and a value a user or a model chose is not an identifier for
> this purpose, whatever its type.

> **Normative.** Every non-reference observation a trace carries is a number or a
> boolean. There is no free-text field, no serialised payload and no
> open-value-type mapping anywhere in the family.

**The point of stating it as clauses about *strings* is that it is checkable.**
"Do not put Tier 1 in a trace" is a rule a reviewer applies to intent; "no string
in this type is derived from data" is a rule a reviewer applies to a line of code,
and a rule a test can approximate by walking the type graph the way ADR-0085 §5's
closure walk does. Tier 1 content is text. Numbers are not Tier 1: a count of
returned records, a similarity score, an elapsed duration and a chunk size are all
facts about the machine.

**The identifier category is carved out of the origin rule rather than excused
from it, and the carve-out is the whole reason a trace can say anything at all.**
An id *is* derived at runtime — it is read off the row the trace is about — so a
flat "no runtime-derived string" rule would forbid the references §1 requires and
leave no conforming trace. The second clause therefore excludes identifiers by
name, and the third clause supplies the property the exclusion is bought with:
minted here, opaque, a pointer rather than a payload. What that property excludes
is exactly what a leak would need — a value whose *content* is the datum rather
than an address for it.

**Origin and not resolvability, deliberately.** An id that once named a row and
no longer does is still a pointer and still carries no content, so deleting the
referent cannot turn a compliant trace into a non-compliant one — which it would,
retroactively and in bulk, if the test were "resolves to a row". §10 requires
exactly that dangling to be permitted; this clause is the half of the pair that
makes it coherent rather than a contradiction.

**The third clause is needed because `Identifier` alone does not carry that
property.** `Identifier` in `core/types.py` is a non-blank encodable string, and a
subject label under ADR-0100 satisfies it while being exactly the Tier 1 datum
this rule is about — ADR-0100's own title says the label "resolves to nothing", so
it is not an id in any sense but the type's. A conformance suite can check the
shape; only this clause can state the origin.

**The exception-class permission is narrow on purpose.** An exception's
*class* is Tier 2 and the corpus already logs it — ADR-0111 §9 ratifies drawing
the refusal/fault distinction "from the exception's class, never from its message
text", and #710 records `Scheduler._log_failure` writing `error_class`. An
exception's *message* is not: `SourceNotGrantedError`'s message names a source,
and a `MemoryStoreError`'s may quote a row. So the class name is admitted by name
and the message is excluded by the same clause that admits it.

**The residue is named rather than hidden.** A metric key is a string the emitting
module chooses (§3), so an author who derives one from data breaches the second
clause. Nothing mechanical stops that; what the clause buys is that the breach is
a *reviewable line of code* rather than a runtime property of a payload, and §3's
key pattern makes an accidental one loud.

**A reference is permitted to dangle and is never resolved to check it.** §10
says why deletion leaves an id pointing at nothing; the consequence here is that
nothing in the emission path reads the referent back, so no trace write can
observe Tier 1 content in the course of recording that it exists.

### 3. The family: one envelope, four kinds, numbers keyed by constants

> **Normative.** `core/types.py` gains one model, `EvaluationTrace`, carrying its
> own id, a `TraceKind`, the instant it occurred, an optional elapsed duration, a
> label naming the seam, a `TraceOutcome`, an optional fault class name, a mapping
> of `TraceRef` keys to identifiers, an optional bounded sequence of record
> identifiers, and a mapping of label keys to `int | float | bool` values. It
> gains no other field.

> **Normative.** `TraceKind` has exactly four members at this decision:
> `OPERATION`, `RETRIEVAL`, `MEMORY_WRITE` and `CONFIGURATION`. A later ADR may add
> one; nothing else may.

> **Normative.** `TraceOutcome` has exactly four members: `OK`, `REFUSED`, `FAULT`
> and `INCOMPLETE`.

> **Normative.** An emitter chooses between `REFUSED` and `FAULT` by the
> exception's class and never by its message text — the same discriminator
> ADR-0111 §9 binds the scheduler's log record to, so the two records about one
> event cannot disagree.

> **Normative.** A metric key and a seam label are of one constrained string type
> whose values match a lowercase identifier pattern of bounded length.

> **Normative.** Every float-valued observation in a trace is **finite**. `NaN`
> and the infinities are refused at construction, recursively over the metric
> mapping.

> **Normative.** A metric key appears in a trace only when the quantity it names
> was **observed**. An absent key means *not observed* and never zero, and no
> emitter writes a placeholder for a quantity the event did not reach.

> **Normative.** An absent `records` sequence means *no set of ids was observed*;
> an empty one means *a set was observed and it was empty*. The two are distinct
> and an emitter may not substitute one for the other.

> **Normative.** `records` holds at most **256** ids, in the order the observed
> operation produced them. Where the operation produced more, `records` holds the
> first 256 and the trace's returned-count metric holds the true total. No trace
> fails construction, and no trace is dropped, because an operation was large.

> **Normative.** A trace whose `records` was truncated **declares that it was**. A
> measure needing record identity excludes a truncated trace from its population;
> it never reads a partial list as a complete one.

**The observation rule is what makes a fault-path trace honest, and it is the
numeric axis's version of §5's argument about a dropped trace.** An operation can
raise before a quantity exists — a `search` whose embedding fails has no candidate
count, an `ingest` that raises before commit has no decision set — and the two
available shortcuts both lie. Recording zero asserts an observation nobody made,
and in the retrieval case asserts *precisely* #824's trigger condition. Omitting
the trace entirely loses the fault. Absence, defined as absence, is the third
option, and it costs a mapping that was already sparse.

**Finiteness is refused at construction because the corpus has already paid for
the alternative twice.** `int | float | bool` admits `NaN` and the infinities;
`_deep_freeze` in `core/types.py` refuses them for `FrozenJson` with the reason
written down — they "have no JSON representation, so they would silently change
value on the way through the store or an export", and `json.dumps` renders them to
a non-JSON token instead of raising, so the encoder does not catch them. The
numeric fields in `core/config.py` carry `allow_inf_nan=False` for the same
reason, noting that `gt=0` "rejects NaN but happily accepts" an infinity. A metric
map is the third place this can enter, and the failure it produces here is the
worst of the three: a single `NaN` score from a provider poisons every average and
every threshold computed over the walk, silently, long after the trace was
written. §5 already accepts that the stream can be *incomplete*; it must not also
be able to be *wrong*.

Keys and labels are additionally governed by §2's second clause — each is a
literal constant in the emitting module — which is where the obligation is stated
and is not restated here.

**Four kinds, and the brief's five seams fall out of them.** The dispatch names
retrieval, memory writes, consolidation runs, scheduler jobs and failed turns.
Three of those five are the same event seen from different callers: ADR-0083 §8
ratifies that "every scheduler job is a public `Engine` call", so a consolidation
run, a retention purge and a user's turn are all one `AssistantEngine` operation,
distinguished by the seam label and the outcome. A failed turn is that operation
with `outcome = FAULT`, which is precisely what ADR-0074 predicted the record would
be. Collapsing them is not a simplification imposed on the list; it is the list
read against what the corpus already decided a scheduler job *is*.

**`INCOMPLETE` is ADR-0111 §9's third clause, given a value.** That clause rules
that "a run that halts under §5 without processing its remaining work is recorded
as a completed run that did not exhaust its work, not as a failure", and argues
that recording it as either of the two neighbouring outcomes destroys information
an operator needs. A three-valued outcome would force exactly that choice on the
trace stream; the fourth member is what stops the trace and the log disagreeing
about a halt.

**Why an open metric map rather than a closed union of per-kind types.** A closed
union — a distinct model per kind, every number a declared field — is the stricter
design and it is refused, because the numbers are the part of this system most
certain to change. The measures are undefined (§15); #824's trigger will want
figures nobody has named; a consolidation lane will want its own counters. Under a
closed union every one of those is a `core/types.py` change, an ADR, and a
migration, for a datum that is a number in a Tier 2 store. Under this design the
*envelope* is closed — every string axis, which is where Tier 1 could enter, is
governed by §2 — and the open axis is the one whose value type structurally cannot
carry content. The strictness is spent where the risk is.

**The bounded id sequence is separate from `refs` because a retrieval returns
many.** `refs` answers "what is this trace about" with one id per relation;
`records` answers "which rows did this read return", which memory precision needs
and which a single-valued mapping cannot hold.

**The cap is a figure and the overflow is a defined representation, because the
read it observes has no bound of its own.** `MemoryStore.search` takes
`limit: int = 10` with no ceiling, so "as many ids as the read returned" is an
unbounded row on a Tier 2 store, and a cap without an overflow rule is worse than
either — a large read would fail the trace's construction and lose the record of a
retrieval that did happen, which is §5's failure arriving through validation.
The *count* is a required metric either way, so the total survives the truncation
the ids do not. 256 rather than a `Settings` field: the cap belongs to the type, so
every implementation agrees without configuration.

**What truncation costs is coverage, not correctness, and the third clause is what
keeps it that way.** A cross-operation join — was the record the user corrected
among those retrieved two turns ago? — is by record identity, so a truncated list
genuinely cannot answer it. The wrong response is to answer anyway from the first
256, which under-counts precision's numerator and looks like a real signal. The
right one is the response §3's observation rule already gives to an unobserved
quantity: say so, and let the measure drop the row from its denominator too. §5
already accepts a stream that is incomplete; this is the same acceptance made
explicit at one more place.

**Every shipped default sits far below the cap, but one configuration point can
cross it, and that is stated rather than glossed.** `tools/builtin.py`'s recall
tool refuses a `limit` above `_MAX_RECALL_LIMIT`, which is 25; `memory/ingest.py`'s
conflict detector passes its own small figure; `MemoryStore.search`'s contract
default is 10. But `LearningLoop`'s `retrieval_limit` is validated only from below
— `_check_tuning` refuses a non-integer and anything under 1, and imposes no
ceiling — and `orchestration/retrieval.py` passes the remaining budget straight
through to `search`. Its default is 5, and nothing in `Settings` exposes it, so
reaching 256 takes a deliberate composer; but "no production caller can" would be
false, and the design must hold when one does.

**It holds, because exclusion is per trace and the deployment-level record is a
diagnostic beside it.** The exact signal is the truncation declaration on the
individual trace, and it has to be, because a configured limit above the cap does
not mean anything truncated: a read asking for 300 over a store holding ten
matching records returns ten, and that trace is complete and countable. Excluding
the whole window on the configuration alone would throw away a population that was
never lost.

What the configuration record buys is the diagnosis, which the per-trace flag
alone does not give. §9's allowlist carries the **effective `search` limit** of
every cardinality control that can drive a traced read past the cap —
`retrieval_limit` and `conflict_limit` at this date, the latter reaching `search`
as `conflict_limit + 2` — so when truncated traces do start appearing, an operator
reads *why* off a dated record rather than inferring it, and a measure lane can say
in advance that this window is at risk. Exclusion stays where the fact is.

**#848** carries the standing question — raise the cap, bound the caller, or give
the family a spilled-ids representation — for the day a real deployment wants both
a large retrieval and an identity-based measure. It is not pre-solved, because
each answer costs something different and none of them is owed by any deployment
that exists.

**The emitter stamps the instant, from the `Clock` it already holds.** The store
could stamp on append, and that would measure the write rather than the event —
wrong for any latency figure, and wrong again if a sink ever buffers. ADR-0096's
treatment of a facet's two instants is the corpus's precedent for caring which
instant a record means.

### 4. Traces about one operation are joinable, and the carrier is not a contract change

> **Normative.** Every trace emitted while serving one `AssistantEngine` operation
> carries that operation's correlation identifier under `TraceRef.CORRELATION`.

> **Normative.** A measure over a pair of events is computable from the stream
> alone: by the correlation identifier where the pair falls inside one operation,
> and by record identity where it does not. The one pair the stream cannot join is
> one whose retrieval trace declares itself truncated (§3), which that trace says
> outright rather than leaving to be inferred.

> **Normative.** The correlation identifier is **not** added to `MemoryStore`,
> `MemoryWriter` or any other existing Protocol's signature. Its carrier is
> ambient to the request and is the implementing lane's to choose, subject to the
> clause above.

**Joinability is the requirement, not the mechanism, and the requirement is the
one this ADR must not get wrong.** Memory precision is a statement about a
retrieval judged by what happened afterwards — a correction, a repeat, an
acceptance — so it is a measure over *pairs* of traces. A stream of individually
perfect traces that cannot be joined computes nothing, and discovering that after
the emitters ship is the expensive failure available here.

**The signature is refused because a correlation id is not an input to a relevance
read.** Adding it to `MemoryStore.search` would put an observability concern into
a contract every implementation and every fake must carry, break golden rule 5's
seal on a Protocol for a reason that has nothing to do with what the Protocol
does, and still not reach the write path or the reader path without doing it
again. `contextvars` is the expected shape — `core/logging.py` already configures
`structlog.contextvars.merge_contextvars`, so the pattern is in the tree — and
asyncio propagates a context into tasks created inside it, which is what
`Engine._tracked`'s shielded task is. Naming it here as the expectation without
binding it leaves the lane free to do better and unfree to do without.

### 5. The instrument is subordinate to the work it observes, and a lost trace is loud

> **Normative.** A failure to record a trace never propagates into the operation
> being traced. No retrieval, write, turn, scheduled run or startup fails, retries,
> or changes its result because a trace could not be written.

> **Normative.** A trace that could not be recorded is logged as a Tier 2 log
> record naming the kind, the seam and the failure's class. Emission failure is
> never silent.

> **Normative.** No trace is emitted for the writing of a trace.

> **Normative.** One crossing of a seam produces at most one trace, and two
> components may not both emit for one event.

**Subordination is forced.** ADR-0074 already settled the neighbouring case in
the other direction and for a good reason: a memory-store failure "leaves a turn
recorded with **no** episode", and failing the turn "would throw away an answer
the user already has because the record of it could not be written". A trace is
one tier further from the user's answer than an episode is; if an episode's loss
does not fail a turn, a trace's certainly does not.

**Silence is refused because a missing trace is indistinguishable from a
non-event.** This is the specific way an instrument lies: a measure over a stream
with dropped rows reports a smaller numerator and does not know it. The log record
is the detector, and it is enough because the log is the surface an operator
already watches (ADR-0083 §6).

**The accepted cost, stated so the measures lane inherits it rather than discovers
it.** The trace stream is lossy in principle, so **every measure must be a rate
whose denominator is drawn from the same stream** — never from an external count
of turns, rows or runs. A ratio of two quantities that lost rows at the same rate
survives the loss; a numerator over an external denominator does not. That is a
constraint this ADR hands forward, not one it discharges.

**The third clause is the #710 lesson applied before the fact**, and it also
closes the obvious regress: a trace store that traced its own appends would emit
forever. What it does *not* forbid is two traces at two different seams during one
operation — a retrieval inside a turn is its own crossing of its own seam, joined
to the turn by §4, and counting it as a duplicate would delete the detail the whole
design exists to capture.

### 6. Traces live in a seventh hub-owned database under `Settings.data_dir`

> **Normative.** The trace store is the **seventh** SQLite database under
> `Settings.data_dir`. The lane that opens it corrects every live claim in `src/`
> and `tests/` that this tree holds six stores, in the same change.

**ADR-0083's exclusivity needs nothing, for the reason ADR-0102 §12 gave when it
added the sixth.** The seventh database lives inside the directory the instance
lock already covers, is opened by the same process, is closed in the same ordered
shutdown, and is reached only through the API. ADR-0083's fourth ruling decides
ownership and exclusivity — "The hub owns the five SQLite databases exclusively.
The API is the only door; no other process opens them" — and a seventh store
opened by the same process inside the same locked directory obeys both.

**The count claim is corrected in code and not in the ADRs**, following ADR-0102
§12 exactly: `service/lock.py`, `service/datadir.py`, `interfaces/cli.py`,
`orchestration/engine.py`, `app/composition.py` and `memory/sqlite_store.py` all
carry a live "six" today, as do the service and wire tests. The same figure in
ADR-0042, ADR-0083, ADR-0084, ADR-0085 and ADR-0102 is **not** corrected: an ADR is
dated, so a count in one is history and stays correct as history
(`CONTRIBUTING.md` → "No state claims in living documents", whose ADR exemption
says so in as many words).

**A separate database rather than a table in an existing one.** Two reasons, and
the second is the one that decides. A trace about a failed write inside the failed
write's own database is lost exactly when it is most wanted — the connection is
the thing that failed. And the trace store is the only store here with a decided
deletion horizon (§10); putting a swept table beside `memory.db`'s retention axes
(ADR-0007's `expires_at`, ADR-0045's validity window) is three lifetimes in one
file, each meaning something different.

### 7. Two Protocols: an append-only sink the pipeline holds, and a store the pipeline does not

> **Normative.** `core/protocols.py` gains two Protocols. `TraceSink` carries one
> operation, an append. `TraceStore` carries the append, a resumable walk (§7a),
> and a purge below an instant.

> **Normative.** Every emitting site takes a **`TraceSink`** as a required
> constructor argument with no default. A composition that omits it does not
> type-check.

> **Normative.** No component of the request pipeline — `orchestration`, `memory`,
> `context`, `planning`, `readers`, `learning`, `tools`, `permissions` — holds a
> `TraceStore` or reads a trace back. Nothing this system does is conditioned on
> what a trace says, and no trace is ever assembled into a prompt.

**The split is ADR-0097 §5's mechanism, mirrored.** There the query seam is the
narrow one — "Every site that drives a reader takes a **`SourceGrants`** — the
query seam, never `SourceGrantStore` — as a **required constructor argument** with
no default … a driver that could record a grant does not type-check either". Here
the *write* seam is the narrow one, and the property protected is different but
the mechanism is the same: what you cannot reach, you cannot misuse.

**What the third clause protects is the instrument's independence.** An instrument
whose readings change behaviour is measuring a system that includes the
instrument. Leg 8 exists to answer "is the user model getting more accurate?" with
data; a pipeline that consults its own telemetry makes that question circular, and
it does so in a way that is nearly impossible to see afterwards in the numbers.
The clause also closes an egress question by construction: a trace the pipeline
cannot read is a trace `models/` cannot send, so ADR-0004 §2's egress rule needs no
new exception and §7's data-minimisation rule needs no new judgement call.

**Required-with-no-default is deliberate friction, and it is bought against a
specific failure.** An optional sink defaults to unwired, an unwired emitter
produces no traces, and no traces is indistinguishable from no events — the same
lie §5 refuses, arriving through composition instead of through I/O. A canonical
fake in `ai_assistant.testing` (the triad, §13) keeps the friction off the tests
that do not care.

**`TraceStore` structurally satisfies `TraceSink`**, so one concrete implements
both and the composition root hands each collaborator the seam it is entitled to.
That is the same arrangement `SourceGrants`/`SourceGrantStore` uses today.

**Append never raises into its caller, and that is a contract obligation the
conformance suite pins.** It is safe to state because the trace is a validated
pydantic model before `emit` is called: a malformed trace is an emitter bug that
fails at construction, in the emitter's own tests, and never reaches the sink. What
`emit` can therefore encounter is environmental — a locked database, a full disk —
which is precisely the class §5 subordinates.

#### 7a. The walk is a total insertion order, and a page boundary is stable under concurrent appends

> **Normative.** `TraceStore`'s read is a walk in the store's **total insertion
> order** — the order in which appends landed, never `occurred_at` order — bounded
> by a caller-supplied count and resumed from an opaque position, under ADR-0114
> §2's rule that a position "is opaque to its caller, and is never a value a
> caller composes".

> **Normative.** A walk resumed from a position returns, exactly once and in
> order, every trace appended after that position and still present; it returns no
> trace at or before it. An append that lands during a walk takes a position after
> every position already issued, so no page boundary skips or duplicates a trace.

> **Normative.** The position is the caller's to hold. `TraceStore` persists no
> cursor, names no walk, and two concurrent readers never contend.

> **Normative.** A bound of zero or below is refused, as ADR-0114 §6 refuses one
> for the chunked walk and for the same reason. Every refusal in this contract is
> a `ValueError`, mirroring ADR-0114 §6a.

**Insertion order rather than `occurred_at`, and the difference is not
cosmetic.** §3 has the *emitter* stamp the instant, so two traces can carry the
same instant, and a buffered or slow sink can land an earlier instant after a
later one. An order over `occurred_at` is therefore neither total nor stable, and
a page boundary drawn on it can skip a row that arrives behind the cursor. This is
ADR-0114 §2's ruling reached by the same route — "a cursor is a position in a
total insertion order, and nothing else", and whatever order a walk uses "must be
total and must not reorder under later writes". A measure that wants a time window
filters within the walk; it does not order by time.

**An append-only store needs no snapshot, which is why this is three clauses and
not a transaction model.** A trace is never updated and never re-ordered; the only
thing that removes one is §10's purge, which deletes from the *old* end. So a
resumed walk can see rows appended since the position was issued — correct, since
they are genuinely later — and can find rows gone that were present when it
started, which is a purge doing its job. Neither is an anomaly a snapshot would
need to hide, and both are stated so a conformance suite can assert them rather
than a fake and SQLite disagreeing quietly.

**No cursor in the store, unlike ADR-0114's walk.** That walk is resumed by a
scheduled *job* across process restarts, so ADR-0111 §1 put the cursor in the
store and ADR-0114 §5 had to name walks so two could not share a position. A
measure is a reader, not a job: it holds its own position for the length of one
computation, and importing the naming machinery would buy durable state nothing
here needs.

### 8. Which seams emit, and what each must carry

> **Normative.** Four seams emit, and they are the floor rather than the ceiling:
> the `AssistantEngine` boundary in `orchestration` emits one `OPERATION` trace per
> call; `memory`'s relevance read emits one `RETRIEVAL` trace per `search`;
> `memory`'s write path emits one `MEMORY_WRITE` trace per `MemoryWriter.ingest`;
> and `service` emits one `CONFIGURATION` trace per hub startup (§9).

> **Normative.** A `RETRIEVAL` trace carries every one of the following the read
> reached (§3's observation rule governs the rest): the requested `limit`, the
> pre-filter candidate count the store fetched, the count returned, the count
> excluded by each read-time predicate separately — retention, validity window,
> kind and band — and the ids returned, under §3's `records` cap.

> **Normative.** A `MEMORY_WRITE` trace carries every one of the following the
> ingest reached: the write's mode, the count of each `MemoryDecisionKind` the
> ingest produced, and the ids of the records written, reinforced, superseded or
> retired, under §3's `records` cap.

**A faulting operation still emits its trace, and its trace still tells the
truth.** A `search` whose query embedding raises never computes a candidate set; an
`ingest` that raises before commit never has a decision set. Under §3's
observation rule those keys are simply **absent**, the `records` field is `None`
rather than empty, and the trace carries what the operation did reach — its
`limit`, its elapsed time, its `FAULT` outcome and its fault class. The two clauses
above say "the following the read reached" for exactly that reason: an
unconditional "carries" would be unsatisfiable on the fault path, and satisfying it
with zeros would make a read that never ran indistinguishable from one that
excluded everything — which is #824's trigger condition, fabricated.

**The store emits its own retrieval trace, and that placement is forced by
#824.** The numbers the trigger needs do not exist outside the store: ADR-0113 §8
leaves "the post-KNN `kind`/expiry/window predicates keeping their placement"
inside the read, so `orchestration` sees only what came back and cannot see how
many candidates were filtered away. #799 established that k-shortfall is a
threshold effect at filtered-neighbour density crossing `fetch_k − limit` — 0%
below it, 100% above — which is a statement entirely about quantities visible only
inside `MemoryStore.search`. A retrieval trace emitted one layer up would satisfy
the letter of "we have retrieval telemetry" and be blind to the exact thing #824
watches for. Per-predicate counts rather than one total, for the same reason: the
trigger is about *window* closure specifically, and a single filtered count cannot
distinguish it from an expiry sweep or a band filter.

**The engine boundary emits the envelope, and it is one wiring point for three of
the dispatch's five seams.** `Engine._tracked` already wraps every public method,
so the operation's name, its outcome, its elapsed time and its fault class are all
in hand at one place, for a turn, a scheduled job and a client command alike. A
job with detail the envelope cannot see returns it in the operation's own result
type, where it becomes metrics on that operation's one trace, rather than emitting
a second record for the same run (§5).

**The write path emits its own trace because the decisions are what a correction
rate is made of.** `MemoryIngestResult` carries the `MemoryDecision`s, and a
correction under ADR-0092 — a user assertion retiring an attested belief — is a
particular decision kind over a particular record. Counting corrections from
outside the write path would mean re-deriving them from what the store now holds,
which is a measure of the present rather than a record of an event.

**A `MemoryWriter.ingest_reading` call is one crossing and one trace**, not one
per resulting `MemoryIngestResult`, following §5's one-crossing rule; the per-
reading counts ride as metrics.

**Nothing here forbids a fifth seam.** A later lane may emit from a new place
provided it obeys §2's tier clauses, §5's subordination and one-crossing clauses,
and §4's correlation clause. What it may not do is add a `TraceKind` (§3).

### 9. Configuration is a trace, stamped at every startup — #829 requirement 2's carrier

> **Normative.** At every hub startup, after the stores are open and before the
> API accepts a request, `service` emits one `CONFIGURATION` trace recording the
> effective value of each setting on a declared list of measurement-relevant
> settings.

> **Normative.** The list is an **allowlist**: a setting reaches a
> `CONFIGURATION` trace only by being named on it, so no `Settings` object is ever
> recorded whole and no field added later is recorded by default.

> **Normative.** A configuration value reaches the trace as a number or a boolean
> under §2. A setting whose value cannot be reduced to one — a path, a URL, a model
> identifier, a credential reference — is recorded as its presence or absence, or
> not at all.

> **Normative.** For **every cardinality control that can drive a traced read past
> §3's `records` cap** — not a named subset of them — the allowlist records the
> **effective `search` limit that control produces at the seam**, which need not
> equal the control's own value. A control added later joins the list in the change
> that adds it.

> **Normative.** That record is a **diagnostic**: it says a window *could*
> truncate, and it never itself excludes one. Exclusion from an identity-based
> measure is **per trace**, on §3's truncation declaration, and a complete trace
> from a deployment configured above the cap counts like any other.

**This is the design call #829 leaves to this lane, and the reasoning for
answering it with a startup stamp rather than an operator act is that a startup
stamp needs no discipline.** #829's requirement is that the arming moment be
datable. The arming act itself is an operator changing `consolidation_interval`
from `None` to a duration and restarting the hub (#829's third requirement,
ADR-0111 §11's "an implementation lane's act against this text once ratified"). A
carrier that depends on the operator *also* remembering to record something fails
exactly when the operator is busy doing the thing being recorded. A carrier that
fires on every startup, before any request is served, cannot be forgotten, and it
dates every other configuration change for free — which the measures will want,
because a chunk size or a `fetch_k` moving mid-window is as much an intervention
as an arming.

**Every startup, not only on change.** A change is derivable by diffing
consecutive configuration traces, and the converse is not true: an "on change"
stamp needs prior state to compare against, which after a crash it does not have.
Emitting unconditionally also makes the stream self-describing about hub
downtime — a gap between a shutdown and the next configuration trace is a hub that
was not running, which a measure must not read as a period of no activity.

**The allowlist is load-bearing and it fails closed.** `Settings` holds no Tier 0
value — ADR-0004 §3 puts secrets in the OS keyring — but it does hold `data_dir`,
a path that on a normal machine contains the user's account name, and it will hold
provider and model identifiers. A denylist would admit the next field somebody
adds. An allowlist admits nothing until somebody names it, and the third clause
then constrains what naming it can put in the record.

**The cardinality controls are put on the list by this ADR rather than left to the
lane, and the clause states the *property* rather than a roster.** They are the
settings whose values decide whether §3's cap can bind at all, and enumerating
them would put a dated list in a normative clause — which is how the first draft
of this clause got it wrong, naming the retrieval limit alone and leaving the
ingestor's path invisible.

Two hold the property at this date, and both are validated only from below.
`LearningLoop`'s `retrieval_limit` — `_check_tuning` refuses under 1, no ceiling,
default 5 — reaches `MemoryStore.search` through `orchestration/retrieval.py`'s
per-band budget, so its effective limit is its own value. `MemoryIngestor`'s
`conflict_limit` — its own `_check_tuning`, same shape — reaches `search` as
`conflict_limit + 2` on the conflict probe.

**That `+ 2` is why the clause records the effective limit and not the control.**
A `conflict_limit` of 255 sits under the cap while the probe it drives asks for
257, so a diagnostic keyed to the control would say "this deployment cannot
truncate" of one that can. It is only a diagnostic, so nothing miscounts — but a
diagnostic that is wrong two short of its own boundary is worse than none, because
it is the record an operator reaches for when truncated traces appear and cannot
see why. Recording the figure that actually reaches the seam cannot go wrong that
way, and it keeps per-control arithmetic out of the clause.

Neither control is a `Settings` field, which is the other half of why "effective"
is the right word: the figure to record is the one the composition root actually
produced, and a `Settings` dump would show neither.

**The failure mode is named rather than papered over.** A configuration trace that
cannot be written is subordinate under §5, so startup continues and the failure is
logged. A window whose configuration traces are missing cannot date its
intervention from them, which is the entry criterion unmet — so the log record is
the operator's cue, and the condition self-heals at the next restart. There is
also a corroborating bound that costs nothing: the **first `OPERATION` trace whose
seam label is consolidation's** dates the arming from above, because an unarmed
job never runs. That is weaker than the stamp — it dates the first run rather than
the configuration change — and it is stated as a fallback, not as a substitute.

### 10. Retention is a horizon longer than any measurement window, and there is no count cap

> **Normative.** `Settings` gains one field, a trace retention horizon, an
> optional duration refused at load unless finite and strictly positive, where
> `None` means "keep forever". Its default is **365 days**.

> **Normative.** There is **no** count cap and no size cap on the trace store. A
> trace is deleted only for being older than the horizon.

> **Normative.** The horizon is enforced by deletion only. A trace still on disk is
> returned by a read whatever its age; there is no read-time retention filter.

**A count cap is refused because it deletes the baseline.** A cap evicts the
*oldest* rows, and in #829's design the oldest rows are the unarmed baseline — the
half of the natural experiment that "arming before the baseline would make …
permanently unanswerable, not merely unmeasured". A horizon deletes rows nobody is
measuring; a cap deletes the rows the measurement is *about*, silently, at exactly
the moment the store has accumulated enough to be interesting. The unbounded-growth
worry a cap answers is answered instead by the arithmetic: a trace is a row of
numbers and ids, a busy single-user day is on the order of a few hundred events,
and a year of them is tens of megabytes on a store whose neighbours hold embeddings.

**365 days rather than a figure sized to leg 8.** The horizon must exceed any
window a measure will span, and a default sized to the window this lane can foresee
is a default that expires the first time somebody wants a year-over-year
comparison. `None` means keep forever, matching `episode_retention`'s convention,
and a finite default is chosen for the same reason `episode_retention` has one:
unbounded is the wrong thing to inherit by omission.

**Read-time enforcement is not owed here, and that is a difference from ADR-0007
§2 rather than a departure from it.** ADR-0007 §2 enforces retention at read time
because it is a *privacy* guarantee over Tier 1 — "the privacy guarantee does not
depend on a background job". A Tier 2 horizon is a disk-space policy over data that
identifies nobody, so there is no guarantee to make independent of the sweep, and a
read-time filter would only hide rows a measure could legitimately have used.

**The sweep is the job that already sweeps, and no new job appears.** ADR-0078 §10
item 8's instruction — quoted in ADR-0083 §7 — is that a purge "is wired wherever
`purge_expired` is wired and inherits the same fate", because "inventing a second
sweeping mechanism for one store would be the thing that has to be undone".
ADR-0083 §7's retention-purge row already calls two purges through one `Engine`
maintenance operation; the trace purge becomes the third call behind that same
operation. The scheduler's job table does not change, no job acquires new store
surface, and ADR-0083 §7's constraints are obeyed literally rather than
approximately.

**The purge's own `OPERATION` trace lands in the store it just swept**, one instant
after the sweep, and is therefore never a candidate for it. Noted because it looks
like a paradox and is not.

**A reference may dangle, and that is correct.** ADR-0004 §6 gives the user the
right to delete their data, and ADR-0101 scopes erasure by subject; both operate on
Tier 0 and Tier 1. A trace referencing a deleted record keeps an opaque id that now
resolves to nothing — which is the honest record, because the deletion does not
un-happen the retrieval, and an id whose row is gone identifies nobody. Whether the
erasure surface should additionally sweep traces is **not decided here** (§15) and
is filed.

### 11. A trace is not an audit record, and the two stores may not be merged

> **Normative.** No `PermissionDecision` is recorded as an `EvaluationTrace`, and
> no `EvaluationTrace` is recorded in the `AuditTrail`. Neither store substitutes
> for the other.

**They differ in tier, in job, in durability and in truthfulness guarantee, and
each difference alone forbids the merge.** The audit trail is a **Tier 1** store by
ADR-0004 §7's own words, exists to make the assistant's behaviour "transparent and
reviewable" to the *user*, and carries authority: `approval_ref` resolves into it,
and `AuditTrail.record` "enforces the resolution invariant" — a decision whose
`resolves` names an id the trail cannot resolve is **refused**. It is write-once
and it has no `delete(id)`, because "selective erasure of an audit trail is
indistinguishable from tampering with it".

A trace is Tier 2, exists for an operator and a measure, carries no authority,
resolves nothing, is **lossy by design** (§5), and is **deleted on a horizon**
(§10). Put traces in the trail and the trail acquires a TTL and a dropped-record
mode, which destroys the two properties that make it an audit trail. Put audit
records in the trace store and an authority record becomes droppable. And putting
operational data in the Tier 1 store the user inspects is the mirror image of
ADR-0074's objection to capturing failed turns as episodes — "writing an episode
whose outcome is an internal fault would put debugging data in the store the user
inspects and the observer mines".

**ADR-0058 is why the boundary is worth stating rather than assuming.** It ruled
that the executor does not validate trail presence, accepting as residue that a
caller outside the pipeline can hand it an unrecorded decision — "a producer's
contract cannot meaningfully prevent the principal from lying about itself". A
reader who takes from that "the trail is best-effort anyway, so telemetry can live
there" has the argument backwards: ADR-0058 accepts a residue *at the edge of* a
store whose interior invariants it leaves fully enforced. Nothing in it makes the
trail a place for records that may be dropped on purpose.

### 12. ADR-0004 §2's telemetry clause governs transmission, and nothing here transmits

> **Normative.** No `EvaluationTrace` leaves the device, by any route, under any
> setting. There is no opt-in that enables trace egress, and this ADR creates no
> designated seam under ADR-0017.

**The clause that looks like a conflict is ADR-0004 §2's third bullet:
"Telemetry is off by default and there is no data egress for observability …
instrumentation that transmits data requires a documented, opt-in setting."** A
trace stream that is always on could be read as defying it.

It does not, and the distinction is in the clause's own words. Both of its
sentences are about **transmission**: no *egress* for observability, and an opt-in
for instrumentation *that transmits data*. It names `logfire-api` being a no-op
unless Logfire "is explicitly installed and configured" — a network sink. This ADR
adds a local SQLite file that no component may read back into the pipeline (§7) and
that nothing may send anywhere. There is nothing to opt into, because the thing the
setting would gate does not exist. The roadmap says the same in its own words when
it names the slice "Tier-2 operational data, **no egress**".

**Recording is already governed elsewhere and already permitted.** ADR-0004 §5
provides for Tier 2 operational records outright — logs — and §1 defines the tier
this store sits in. The rule this ADR is bound by is §5's content rule, and §2 is
what it obeys, not what it bends.

### 13. The contract surface this ADR names, and what the implementing lane owes

The surface, so the triad lane has a target and a reviewer has something to check
this ADR against:

- **`core/types.py`** — `TraceKind`, `TraceOutcome`, `TraceRef` (the closed key
  vocabulary for `refs`), a constrained label type for seam names and metric keys,
  and the `EvaluationTrace` model of §3. Field names and the exact pattern are the
  lane's within §2 and §3.
- **`core/protocols.py`** — `TraceSink` (append) and `TraceStore` (append, §7a's
  walk, a purge below an instant). §7a fixes the walk's order, its resumption
  guarantee, its bound's refusal and where the position lives; the position
  *type* is the lane's, and reusing `MemoryStore`'s `WalkPosition` across stores
  is not decided here.
- **`core/config.py`** — one field, §10's horizon.
- **No change to any existing Protocol**, and no method added to
  `AssistantEngine`. The inspection surface is §15's.

What the implementing lane owes beyond the triad
(`CONTRIBUTING.md` → "Adding a Protocol: land the triad together" — the Protocols,
a shared conformance suite each, a canonical fake in `ai_assistant.testing`, and
the `Test…Contract` subclass that runs it):

- The seventh database and its correction of every live "six" claim (§6).
- The conformance obligation that a sink whose backing store fails returns
  normally (§5, §7).
- A test that no string-typed value reachable from `EvaluationTrace` is
  unconstrained — the type-graph walk §2 makes possible, in the spirit of
  ADR-0085 §5's closure walk.
- A round-trip obligation on `TraceStore` that an absent metric key and an absent
  `records` sequence survive storage as absent, never as zero and never as empty
  (§3). A schema with `NOT NULL DEFAULT 0` columns would erase the distinction the
  fault path depends on, silently, at the persistence layer.
- The correlation carrier (§4) and the emitters (§8), which are wiring lanes after
  the triad, not part of it.

### 14. What this records against earlier ADRs, under ADR-0082 §1

ADR-0082 §1 puts the judgement in this ADR's text — a record on an earlier ADR is
owed "exactly when the later ADR amends a named clause of that earlier ADR", and
the test is ADR-0070 §1's: *would a reader holding only the earlier ADR now act
differently, or read one of its clauses more widely than it now holds?* Applied to
each place a record looks owed. **None is owed.**

**ADR-0074's failed-turn deferral — not owed, and this is the closest of the
fifteen.** Its sentence is "A turn that raises before producing an outcome is not
captured, and the gap is deliberate … what failed is *operational* information —
Tier 2, and the subject of leg 8's `EvaluationTrace`, not of Tier 1 memory". §8
records that turn — as a Tier 2 trace, which is what that sentence says the record
should be. A reader holding only ADR-0074 writes no episode for a raising turn,
before and after. Discharging a deferral by the route the deferral itself named is
"the mechanism working" (ADR-0102 §13, quoting ADR-0100 §11), and its closing
"Revisit if the observer turns out to need failed turns; it is additive" is
untouched: nothing here puts a failed turn where the observer can mine it.

**ADR-0004 §2's telemetry clause — not owed.** §12 argues it at length. The clause
governs transmission; nothing here transmits, and no opt-in is created that its
sentence would have to cover.

**ADR-0004 §5 — not owed.** "Logs are Tier 2 only. Tier 0/1 data must never be
logged." A trace is not a log record, and it is Tier 2 regardless; §2 binds the
family to the same content rule §5 binds logs to, which is obedience rather than
amendment.

**ADR-0004 §6's retention sentence — not owed.** It says memory "supports
**retention rules** (e.g. TTLs, size caps) … specifics are set per memory type when
`memory/` is designed", about Tier 1 memory. §10 sets a horizon for a Tier 2 store
that is not memory. Its deletion sentence — "Deleting the user's data purges Tier 0
… and Tier 1 … together" — stays exactly true of Tier 0 and Tier 1; §10's dangling
reference is an opaque id in a third tier and is filed as an open question rather
than an answered one.

**ADR-0007 §2's read-time rule — not owed.** It binds `MemoryStore`, and §10 says
so explicitly while declining to copy it to a different store for a different
purpose. No sentence of ADR-0007 becomes false; a reader holding only it still
enforces retention at read time on the store it is about.

**ADR-0083 ruling 4's "the five SQLite databases" — not owed**, on ADR-0102 §13's
reasoning, which this case matches term for term. The decision is that the hub owns
them exclusively and the API is the only door, and both are obeyed by a seventh
store opened by the same process inside the same locked directory (§6). The number
is a dated observation in a dated document. A reader holding only ADR-0083 acts
identically.

**ADR-0083 §3's startup sequence — not owed.** §3 fixes six steps and requires that
"no step begins before the previous one has succeeded". §9 adds a write inside that
sequence's window; it reorders nothing, adds no step whose failure gates a later
one, and leaves every one of §3's exit-code rulings untouched. §3 states an order,
not an exhaustive account of every byte written during it — and its readiness
definition ("the lock is held, every store is open, the at-start sweeps have run,
the scheduler is running, and the API is accepting") stays true word for word, with
the seventh store inside "every store is open".

**ADR-0083 §7's job table and its "No job gets new store surface" — not owed.** §10
adds no job and changes no interval. The trace purge is a third call behind the
retention-purge `Engine` maintenance operation the table already names, which is
ADR-0078 §10 item 8's instruction taken literally, exactly as §7 took it for the
deferral purge. The job's own surface is unchanged: it calls one façade operation,
as before.

**ADR-0083 §8's "the scheduler holds an `Engine` and nothing else" — not owed, and
avoiding this record is one reason §8's design is what it is.** Emitting the
scheduled-run trace at the `AssistantEngine` boundary rather than in the scheduler
means the scheduler acquires no `TraceSink`, no store and no new collaborator. Its
sentence stays literally true. `service` does acquire a sink for §9's configuration
trace — but that is the *service*, not the scheduler, and ADR-0083 §8 already
permits it: "`service` may import `app` … and `core`", and `TraceSink` is `core`.

**ADR-0085 §1's "and nothing else" — not owed.** No method is added to
`AssistantEngine`; §13 says so and §15 defers the inspection surface to its own
lane. §5's closure walk is likewise untouched, because no `AssistantEngine`
signature gains a type.

**ADR-0097 §5 — not owed.** §7 borrows its constructor-injection mechanism for a
different seam. Nothing about grants moves, and a reader holding only ADR-0097
still injects `SourceGrants` into every reader-driving site.

**ADR-0102 §12's "sixth" clause — not owed, and its obligation is inherited rather
than amended.** That clause makes the grant store the sixth and obliges its lane to
correct claims of five. Both stay true: the grant store is still the sixth, and
that correction was made. §6 states the same obligation for the seventh, in the
same form, which is a stacked addition recorded here and nowhere else (ADR-0082
§1).

**ADR-0111 §9 — not owed, and it is the one most worth checking.** Its second
clause is that "an expected refusal produces exactly one operational record per
run. No component may emit a second record for the same refusal at a severity an
operator's monitoring treats as a fault." A trace is not emitted to the log stream,
carries no severity, and is invisible to monitoring that watches log levels — so
no severity-bearing second record appears, and the clause's stated harm cannot
occur. §3 additionally binds the trace's `REFUSED`/`FAULT` discriminator to the
same class-not-message rule §9's first clause binds the log record to, so the two
records about one run agree by construction rather than by coincidence, and §3's
`INCOMPLETE` is §9's third clause given a value. A reader holding only ADR-0111
behaves identically; what changes is that a second, non-severity record now exists,
which §9's own wording — "at a severity an operator's monitoring treats as a
fault" — was written to permit. **#710 stays open and is closed by the lane §9
names**, not by this one.

**ADR-0114 §2, §5, §6 and §6a — not owed.** §7a *applies* §2's opacity rule and
§6/§6a's zero-refusal to a second store rather than changing either, and declines
§5's walk-naming with its reason stated. Every sentence of ADR-0114 is about
`MemoryStore`'s chunked walk and stays true of it; a reader holding only ADR-0114
still names walks, still stores the cursor, and still refuses a zero chunk there.

**ADR-0058 and ADR-0021 §4 — not owed.** §11 states a boundary neither of them
crossed. `AuditTrail`'s obligations, `StepExecutor`'s four collaborators and
ADR-0058's accepted residue are all untouched.

**Addition, in ADR-0102 §13's form.** A reviewer who reads any of these the other
way is invited to name the sentence of the earlier ADR that becomes false or
over-wide, which is the showing ADR-0082 §1 requires of a demand for a record.

### 15. What this ADR does not decide

- **The measures' definitions.** Memory precision, correction rate and
  repeated-explanation rate are named by `VISION.md` → "Measures of Success" and
  picked by the roadmap; what each one *is*, and where it is computed, is a
  follow-on slice once traces exist (#846). §1 is the constraint that slice
  inherits, and §5's denominator rule is the second.
- **The baseline's duration.** #829 says in as many words that "the baseline's
  duration and the precision measure's design are leg 8's own slices".
- **The arming moment.** It is #829's and an operator's act, and ADR-0111 §11
  already rules that "enabling any job the scheduler ships disabled … is an
  implementation lane's act against this text once ratified". §9 decides only the
  carrier that dates it.
- **The inspection and report surface.** No `AssistantEngine` method, no wire
  operation and no CLI command is added here, so how a human reads traces — and
  whether the measures lane reads them through the API or offline in the shape
  ADR-0104's re-embedder uses — is that lane's, against ADR-0083 ruling 4. #494 and
  #659 hold the user-facing progress-report question open and this ADR does not
  touch it.
- **Whether erasure sweeps traces.** §10 rules that a dangling opaque reference is
  correct and identifies nobody. Whether ADR-0101's subject-scoped erasure should
  additionally delete traces referencing erased rows is a privacy decision of its
  own, and is filed as an issue rather than answered in passing.
- **#824's mitigation.** §8 decides what the trigger's telemetry must carry; the
  selection among #457's and #411's mitigations is #824's, warranted by ADR-0112
  §7's measurement gate.
- **#710's fix.** ADR-0111 §9 routes it to `Engine._tracked`'s shielded task, on
  ADR-0042 §2 and ADR-0054's ground. §14 records why this ADR does not disturb it.
- **Retention of anything but traces**, and ADR-0007 §5's deferred size-caps slice,
  which stays deferred where the roadmap's leg 7 left it.

## Consequences

**Leg 8's remaining slices acquire a target.** The triad, the emitters, the
measures ADR and the baseline run all have a ratified shape to build against
instead of a shape to negotiate, and the two that are operating acts rather than
lanes — the baseline and the dated arming — have a carrier that exists before the
window opens, which is #829's requirement 2 met rather than promised.

**#829's entry criteria become checkable.** After the triad and §9's emitter land,
"the arming moment is stamped somewhere telemetry can see" is a query over the
trace store rather than a claim.

**Every measure inherits two constraints it did not choose.** It must be a rate
whose denominator comes from the trace stream (§5), and it may use only numbers,
booleans and opaque ids (§2). Both narrow what is expressible; both are the price
of a Tier 2 instrument that cannot leak and cannot lie about its own completeness.

**A new number costs a line, and a new kind costs an ADR.** That asymmetry is
chosen (§3). It will feel wrong the first time somebody wants a fifth kind, which
is the point: the kinds are the axis along which the tier discipline is stated, and
the metrics are the axis along which measurement iterates.

**The hub gains a seventh database, a seventh open connection, and one more thing
to close in the ordered shutdown.** The count claim in six modules and three test
modules becomes wrong the day the store lands and must be corrected in the same
change (§6) — the same maintenance ADR-0102 §12 paid for the sixth.

**Emission is on the hot path of every retrieval.** A trace per `search` is a
second write per read, on a store whose latency leg 7 measured at an affine
~1.2 µs/record. The write is small, to a different database, and subordinate (§5),
but it is not free, and the implementing lane owes a measurement rather than an
assurance. If it proves material, the answer is buffering behind the sink — which
§3's emitter-stamped instant already anticipates — and not dropping the trace.

**What becomes harder: adding an observability field in a hurry.** There is no bag
to put it in. A number goes in the metric map; anything else is a design
conversation. That is the intended friction, and it is the reason ADR-0004 §5's
redaction processor is a safety net for the log stream and not the model for this
one.

**The instrument is deliberately blind to itself in one respect.** Traces lost to
an emission failure are logged but not counted in the stream, so the stream cannot
report its own completeness. A later decision could add a per-startup dropped-trace
counter to the configuration trace; it is not added now because a counter that is
itself lossy is a weaker guarantee than the log record already gives.

## Alternatives considered

**A free-form attributes bag** — `Mapping[str, str]`, or a JSON payload column.
Refused. It is the shape every structured logger uses and the shape in which
ADR-0004 §5's rule is unenforceable by anything but care, across five call sites
and a measure lane that does not exist yet. §2's value-type constraint is the
whole mechanism by which "references, never contains" is a property rather than a
promise.

**A closed discriminated union, one model per kind, every number a declared
field.** Refused, and it is the strongest of the rejected options. It would make
even the metric keys machine-checkable. It also makes every new figure a
`core/types.py` change, an ADR and a migration — during the one leg whose explicit
purpose is to iterate on what to measure. §3 spends strictness on the string axis,
where content could enter, and buys flexibility on the numeric axis, where it
cannot.

**Reuse the structured log as the trace stream** — measure by parsing
`hub_*` events out of stdout. Refused. The log is a stream an operator reads and a
supervisor rotates; a measure needs a durable, queryable, joinable record with a
decided horizon and a stable schema. Reusing it would also drag the log's severity
model into the measurement, which is the #710 confusion arriving from the other
direction.

**An external observability stack** — OpenTelemetry, or the Logfire integration
`pydantic-ai` already carries. Refused. ADR-0004 §2 names `logfire-api` precisely
because it is a no-op unless configured, and configuring it is egress. A local
single-user store needs no collector, no exporter and no wire format, and adopting
one would buy a dependency and a data-residency argument for a SQLite table.

**Traces in the audit trail.** Refused; §11.

**Traces in `memory.db`.** Refused; §6. A trace about a failed write inside the
failed write's database is lost when it is wanted, and three deletion lifetimes in
one file is one too many.

**Make emission a hard failure**, so a lost trace cannot go unnoticed. Refused;
§5. It inverts the priority between the work and the instrument, and ADR-0074
already settled the neighbouring case the other way for a stronger record than
this one.

**Let the pipeline read traces** — adaptive retrieval that widens `fetch_k` when
telemetry shows shortfall, say. Refused; §7. It is an appealing feature and it
makes leg 8's exit test circular. The mitigation #824 defers is chosen by a human
reading the numbers, which is the same intervention with a date on it.

**Thread a correlation id through `MemoryStore.search`.** Refused; §4. It puts an
observability parameter on a contract that has nothing to do with observability,
breaks a Protocol seal for it, and does not reach the write or reader paths without
doing it again.

**An operator-recorded arming marker** — a CLI command, or a file the operator
writes. Refused; §9. A carrier that depends on the operator remembering fails at
the moment it is needed, and a startup stamp dates every configuration change
rather than the one somebody thought to record.

**A count cap alongside the horizon.** Refused; §10. It evicts the baseline, which
is the one part of #829's natural experiment that cannot be re-created.
