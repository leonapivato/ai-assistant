# 93. A sensor reads a source and proposes what it read; the clock bounds the read, so nothing needs a cursor

- Status: Accepted
- Date: 2026-08-02
- **Decides a `core` contract and implements none of it.** Golden rule 5 and
  ADR-0015 §5 put a contract ADR in its own PR, merged before anything implements
  against it. The Protocol, its shared conformance suite and its canonical fake in
  `ai_assistant.testing` ship together as one later lane (`CONTRIBUTING.md` →
  "Adding a Protocol"). **Because this ADR decides a Protocol and a `core` type,
  its required review set is adversarial *and* architecture**, even though the PR
  carrying it is prose only — the reading ADR-0090 §5 and ADR-0091's header each
  recorded in the opposite direction, for ADRs that decided no surface. It is a
  substantive contract ADR, so it was **reviewed while `Proposed` and ratified
  only after** (`CONTRIBUTING.md` → "Contract ADRs land before their
  implementation"), which is what left a finding able to change the decision — and
  several did: §3's two cadences, §8's raise, §7a's enablement matrix and §7b's
  three semantics all arrived through review rather than surviving it.
- **Depends on ADR-0092, and says so as a gate rather than as a note.** ADR-0073 §4
  makes carrying the reporting source's identity and its report time a
  precondition of leg 6's first `EXTERNAL` producer shipping. That vehicle is
  ADR-0092's to decide, together with imported-record identity and whether a user
  assertion may override an attested belief. **ADR-0092 was the other half of the
  same dispatched wave and has merged ahead of this one**, so §9's boundaries are
  stated against text that is in the corpus rather than against an expected one —
  and §5 and §9 say what it actually delivered, which is narrower than this ADR
  assumed while it was pending. **It stands `Proposed` on `main`**: its
  ratification flip is owed and is its own lane's, and this ADR does not present it
  as ratified. Binding to its rulings meanwhile is sound on the corpus's own terms
  — `CONTRIBUTING.md` → "Trivial ADR edits" defines that flip as recording a
  ratification rather than deciding one, so it moves no clause §9 relies on. Collapsing those questions into a guess here was exactly what
  ADR-0073 §4 forbade when it said the decision is "for that lane — with a producer
  in hand — not one to guess here".
- **Amends no earlier ADR and supersedes none**, and §12 applies ADR-0070 §1's
  test and ADR-0082 §1's record rule clause by clause to show why — including to
  the three places where the opposite reading is available: ADR-0008 §2's internal
  seam, ADR-0075 §2's exemption boundary, and ADR-0083 §7's job table.

## Context

### What leg 6 needs, and the three questions it cannot start without

Leg 6 builds the first read-only ingestion source. The project owner's ruling
scoping it is that the first source is a **local `.ics` calendar file** read from
disk. That ruling is doing more work than it looks like: it removes the network
hop, so ADR-0017 §1's rule — user data may leave the device only from `models/` or
a designated `tools/` seam — is not engaged, and §3's fourteen conditions on
designating that seam are not this wave's to spend. ADR-0084 already settled the
reasoning for the symmetric case: "A loopback listener moves bytes between two
processes on one machine; it engages neither clause." Reading a file the user
already has engages them less.

What is left is three questions, and none of them has an answer in the corpus:

1. **What a read-only source *is* as a contract** — what it contributes to the
   situational context, what it proposes into memory, and on whose authority.
2. **What drives it**, given that the hub now has a scheduler and that the one
   job on that scheduler which needed durable state ships disabled for want of it.
3. **How it is configured and enabled.**

### What already exists, and what each of those pieces refuses to be stretched into

**A context seam that is deliberately not a contract.** ADR-0008 §2 put
`ContextProvider` in `core/protocols.py` and kept the composable-source seam —
`ContextSource`, in `context/sources.py` — *inside* `context/`, "ensuring the only
data that crosses a subsystem boundary is the typed `CurrentContext`". Its
contribution is a `Mapping[str, object]`, explicitly "an implementation detail of
`context/`". That seam is the right way to add a facet and the wrong way to reach
memory: a `ContextSource` that also proposed beliefs would put a `MemoryWriter` in
the subsystem ADR-0008 §4 defines as advisory and non-durable.

**A write path that already has the shape a sensor needs, and a named refusal to
extend it.** ADR-0028's propose/dispose/persist path routes every belief through
`MemoryWriter.ingest` and a `MemoryPolicy`. ADR-0075 §2 exempted exactly one
producer from it — deterministic capture of a turn this system conducted — and
named this wave in the exclusion list: "**Any future capture source** — a sensor
(leg 6), or the buffered ambient capture #441 sketches. Each may argue for the
same exemption on the same grounds when it exists; none inherits it here, because
none is deterministic recording of an exchange this system itself conducted and
can vouch for."

**A producer whose shape is the closest available precedent.** ADR-0077 §1 built
the observer as "episodes in, proposals out": it "holds no store handle, and that
is the scope limit rather than a rule about it", and selection "belongs to
`orchestration`, the one place that legitimately holds both stores by injection".
Everything about that shape transfers except its input.

**A scheduler, and the one job on it that could not be enabled.** ADR-0083 §7 runs
jobs from a table of names, intervals and next-due instants, each job "a public
`Engine` call" (§8), each interval a `Settings` field. Observation is on that
table and ships **disabled**, for a reason §7 states exactly: "without a cursor, a
periodic run re-reads the same recent window and spends a model call each time,
and it cannot reach the turns the window has already passed. Enabling it on a
timer before the cursor exists buys repeated cost and no new coverage." The cursor
itself is deferred by ADR-0083 §13 because it is "**new durable state**, so it is
itself subject to §6's upgrade-with-state discipline".

The question this ADR has to answer, and cannot answer by analogy, is whether a
sensor inherits that problem. It does not, and §5 is where the difference is
argued rather than asserted — because the answer decides whether leg 6's first
source ships enabled or ships as a switch nobody can safely flip.

### An honest statement of what this ADR is not allowed to settle

Three things adjacent to every section below belong to other decisions, and are
named here so that their absence reads as a boundary rather than an oversight.
§11 states each as a deferral with the condition that would fire it.

- **A revocable permission-grant model.** `ActionPolicy` governs *actions*, not
  *sources*: "you may read my calendar" has nowhere to live today. §7 decides
  configuration and enablement, which is a different and weaker thing, and says so
  in as many words rather than letting a `Settings` field pass for consent.
- **What a context facet carries.** Whether a facet gains an as-of instant and
  provenance is a `core/types.py` decision sequenced after this one. §3 is built
  so that this ADR does not have to guess it.
- **ADR-0092's half**: the reporting source's identity and report time as they sit
  on a stored record, imported-record identity, and the override of an attested
  belief.

## Decision

We will add a `Sensor` contract in `core`: a read-only producer that reads one
source, returns one bounded reading, and proposes what it read through the gate
that already exists.

### 1. A sensor reads a source and returns a reading; it holds no store and writes nothing

> **Normative.** A `Sensor` takes no store handle, no writer, no policy and no
> engine. It reads its own source and returns a reading. It may not write to any
> store, may not read a belief, and may not decide the fate of anything it
> proposes.

This is ADR-0077 §1's rule with the input changed, and it is taken for the reason
that ADR gave rather than by imitation: a producer that held a store would make
the scope of ingestion "a property of the producer's code rather than of a
ratified seam, and every later reviewer would have to re-derive it by reading an
implementation. Here it is a type."

> **Normative.** Every belief a sensor's reading proposes reaches memory through
> `MemoryWriter.ingest` and the `MemoryPolicy` behind it. A sensor inherits no
> part of ADR-0075's capture exemption.

ADR-0075 §2 already reserved the argument for this wave rather than granting it,
and this ADR declines to make it. The grounds it would have to be made on are not
available: a calendar entry is not "deterministic recording of an exchange this
system itself conducted and can vouch for" — it is a third party's report, which
is the definition of the `ATTESTED` band (ADR-0072 §2, `BeliefBand.ATTESTED`:
"A source the user connected reported it"). A band whose whole standing is that
someone else said it is the last band that should reach the store unmediated.

> **Normative.** Selecting when a sensor runs, and ingesting what it returns, are
> `orchestration`'s. A sensor is never its own caller.

### 2. Where a sensor lives: a new top-level `sensors/` package

> **Normative.** Concrete sensors live in a new top-level `ai_assistant/sensors/`
> package. It may import `core` and nothing else in `ai_assistant`; no subsystem
> may import it. The `lint-imports` contract expressing that is the implementing
> lane's.

Placement is decided here rather than left to the lane because it is an
architecture boundary with a mechanical contract behind it (`CLAUDE.md`, golden
rules 1 and 2), and ADR-0083 §8 set the precedent by placing `service/` in a
lifecycle ADR for the same reason. Each of the four existing homes was tested and
each fails on something specific:

- **`context/`** is advisory and non-durable by ADR-0008 §4's design. A source
  living there would have to hold a `MemoryWriter` to reach memory, which makes
  the advisory subsystem a belief producer and breaks the property ADR-0008 §2
  bought by keeping `ContextSource` internal.
- **`memory/`** owns the store and the gate. A producer that lives beside the
  policy ruling on it is the arrangement ADR-0028's propose/dispose split exists
  to prevent, and it is why the observer is in `learning/` and not here.
- **`learning/`** is model-backed distillation — feedback and episodes into
  beliefs. A sensor infers nothing: it reads a file and reports what the file
  says. Putting a non-inferring reader there would blur the one line ADR-0075 §2
  draws by *what the producer does* — record, or infer.
- **`tools/`** owns definitions, the registry, and the undesignated egress seam of
  ADR-0017 §1. A sensor is not invoked by a plan and transmits nothing; filing it
  there would put a reader inside the package whose network posture is governed by
  fourteen unmet conditions, and invite exactly the confusion §11 is at pains to
  avoid when a networked source eventually exists.

### 3. One reading type, two consumers, two cadences — and the facet half is deferred additively

A sensor's reading has two legitimate consumers: the situational context, and
memory. An earlier draft of this section ruled that they must share **one read**,
so that the facet and the beliefs could never disagree. That was wrong, and the
correction is worth recording rather than quietly making, because the wrong
version looked tidier.

The two consumers have **different cadences by ratified design**. ADR-0008 §5
says `assemble()` "computes fresh each call — context is a point-in-time snapshot,
not cached state", and ADR-0008 §4 makes the whole subsystem advisory. Ingestion,
by contrast, is periodic (§6). Forcing one read to serve both leaves nowhere for a
request-time facet to come from: it would have to be served from a snapshot the
last scheduled run left behind, which is durable-ish cross-subsystem state that §5
forbids, or from nothing at all.

And the disagreement the single read was meant to prevent is not a defect. A facet
read at 10:00 and a belief written from an 09:00 run *should* differ: the facet
states the source's "right now" and the belief states what the source said when we
last asked. What matters is not that they agree but that neither is mistaken for
the other, which is what the reading's own instants are for.

> **Normative.** A sensor's two consumers read at their own cadence: the context
> facet reads at assembly time, and ingestion reads on its schedule. Neither may
> derive its answer from the other's reading, and neither may present a reading's
> content without the instants that reading carries.

> **Normative.** `SensorReading` is a frozen `core/types.py` pydantic model. Its
> **proposal half is decided here** (§10): the sensor's Tier 2 identity, the
> instant this system performed the read, any reading-wide instant the source
> itself declares, and the proposals. Its **facet half is deferred** and lands
> as an **optional** field when the context-facet decision is made; a reading that
> predates that field stays valid.

This is ADR-0008 §1's own additive pattern applied one level up. That section
built `CurrentContext` so "a producer that predates a facet stays valid: an absent
facet is `None`", and the same shape means this ADR does not have to guess what a
facet carries in order to give the sensor a return type. The alternative — a
Protocol returning a bare sequence of proposals — makes the facet's arrival a
signature change, and a signature change is a breaking `core` change owing its own
ADR (golden rule 5), bought purely to avoid naming a model now.

> **Normative.** The facet path is `context/`'s existing internal seam. A
> `ContextSource` in `context/` holds a `Sensor` and contributes from its reading.
> A `Sensor` is not itself a `ContextSource`. This says what the path **is**; §7a
> says it is not wired until the facet exists as an optional `CurrentContext`
> field, which is another ADR's.

**ADR-0008 §2's boundary is satisfied rather than stretched, and the opposite
reading is available enough to be worth refuting.** §2's sentence — the internal
seam "ensur[es] the only data that crosses a subsystem boundary is the typed
`CurrentContext`" — reads on its face as though nothing typed may enter `context/`
either. It cannot mean that, and the sentence says why in its own next clause: the
rule it is honouring is "that cross-boundary data is a `core` pydantic model
(`CONTRIBUTING.md`)", and the property it is protecting is that "nothing
**untyped** escapes the package". Both hold here. The scope is `context/`'s
**output**: `CurrentContext` remains the only thing `context/` hands its
consumers, and a source's `Mapping[str, object]` remains an implementation detail
that never leaves. On the input side `context/` already takes `core` contracts —
`ClockContextSource` is constructed with a `Clock` — and a `Sensor` returning a
`core` pydantic model is that same arrangement with an I/O-bound source. This is
the ADR-0083 §15 pattern of examining a clause and finding it unmet; §12 records
that no amendment is owed.

> **Normative.** The `context/` adapter is **optional** in ADR-0026 §4's sense: it
> carries no `required` marker, so a sensor fault leaves the facet absent and the
> rest of the context assembled.

That is ADR-0008 §4 applied without amendment — "A failing **optional** source
(future: a calendar API outage) is **skipped**, leaving its facet `None`" — and it
is the clause that ADR names a calendar in. It is also why a request-time read is
affordable: the one failure mode it introduces is the one ADR-0008 §4 already
rules on, by name, for this exact source.

### 4. What a sensor may propose: attested beliefs, never an episode, and never an absence

> **Normative.** A sensor proposes records in the `ATTESTED` band. It may not
> propose an `EpisodicMemory`.

The corpus anticipates ingested episodes — ADR-0077 §8 notes that "a sensor's
episodes belong to no conversation, and reaching them needs a second selection
rule in the stage, not a different `Observer`" — but anticipating is not
authorising, and the two ratified clauses that bear on it point the other way and
leave no path through:

- ADR-0075 §2 declines the capture exemption to a sensor, so an ingested episode
  would have to go through the gate; and
- ADR-0075 §4 demonstrates, against the code rather than from first principles,
  that the gate is **destructive** to an episode: `MemoryIngestor._detect_conflicts`
  is kind-scoped, `DefaultMemoryPolicy.decide` rules `REINFORCE` on the first
  conflict, and `_merge` returns "the **new turn stored at the older turn's id**".

An ingested episode therefore has neither a gate it can survive nor an exemption
it can claim. Manufacturing one here would mean arguing an exemption for a record
of an event this system did *not* witness — a strictly larger claim than the one
ADR-0075 made for a turn it did — and doing it inside an ADR about a seam. It is
deferred by name in §11.

> **Normative.** A sensor never proposes the absence, cancellation or retraction
> of anything. An entry missing from a later reading is not evidence that the
> entry was withdrawn.

This is the safety rule the whole seam turns on, and it is a consequence of §5's
bound rather than an independent preference: a bounded read, a truncated file, a
permission error and a genuinely deleted entry are **indistinguishable from the
reading**. A producer allowed to propose absence would retract the user's beliefs
on the strength of a failed read, and the failure would look exactly like success.
Retracting an attested belief when its source stops reporting it is real work and
is deferred in §11, where it belongs beside ADR-0092's override mechanism.

> **Normative.** A sensor's proposals carry a `rationale` naming the source, and
> a `sensitivity` chosen for what the source holds rather than defaulted.

`MemoryUpdateProposal.sensitivity` defaults to `DataTier.PERSONAL`, which is
correct for a calendar and must not be assumed correct for the next source. A
reading that touches Tier 0 material is the one case the propose path already
refuses to queue as a question (`MemoryUpdateProposal._secret_data_carries_no_confirmation`),
and a producer that defaults its way past that classification is the failure
ADR-0004 §1's tiering exists to prevent.

### 5. The read is bounded by the clock and configuration — which is exactly why there is no cursor

> **Normative.** A sensor's read is bounded. The bound is declared by the sensor,
> its figures are `Settings` fields with named defaults, and a figure outside its
> range is refused at load rather than at the first run.

Every read in this system is bounded (ADR-0021 §4, ADR-0073 §2), and ADR-0074 §9.3
already ruled that the defaults are named rather than left to the implementation,
because "a 'bounded default' with no figure is two conforming stores handing the
same continuation different history". ADR-0077 §1 applied both to
`observation_batch_size`, including the reason the refusal belongs at load: "A
setting the store read would refuse must fail at load, not at the first
observation". **The figures for this wave's one sensor are therefore named in §7a
rather than left to its lane** — that rule cannot be invoked here and satisfied
elsewhere.

> **Normative.** A bound is enforced by **refusing**, never by truncating. A read
> whose source exceeds any of its bounds raises under §8 rather than returning the
> part that fitted.

Truncation is the failure ADR-0077 §1 named for the equivalent case — "a silent
truncation disables half the work while the caller keeps reporting health, and the
episodes the caller believed were observed were never read" — and here it is worse
by one step, because §4 forbids proposing an absence: a truncated reading is
indistinguishable from a source that simply has fewer entries, and a consumer
cannot tell which it holds. Widening the cap or narrowing the window is a
deployment's decision; making it silently is nobody's.

> **Normative.** A sensor's bound is a function of the clock, its configuration
> and the source's own content, and of nothing else. It may not be derived from
> durable state recording what previous runs read.

**This is the clause that removes the cursor, and it is the substantive finding of
this ADR.** ADR-0083 §7 ships observation disabled because "without a cursor, a
periodic run re-reads the same recent window and spends a model call each time,
and it cannot reach the turns the window has already passed". Both halves of that
are properties of *observation*, not of periodicity, and neither transfers:

- **The coverage failure does not arise.** Observation's window is the tail of a
  conversation log that grows forever, so a turn that falls out of the tail is
  unreachable by any future run: nothing but a cursor can get back to it. A
  clock-relative window over a calendar is not like that. The window *moves with
  the clock*, so every run's window is recomputed from scratch and an entry inside
  it is read whether or not any previous run read it. There is no accumulating
  backlog for a cursor to track.
- **The cost failure is a different order.** Observation spends a model call per
  run (ADR-0077 §3). A sensor reads a file and parses it. Re-reading is not free,
  but it is not the thing §7 declined to spend.

> **Normative.** The `Sensor` contract carries no cursor and no durable
> per-source state, and a conforming sensor may not introduce one. A source that
> cannot be re-read in full within its bound — an append-only feed, a paginated
> API, a mailbox — is out of this contract's scope and owes its own decision.

That last sentence is the honest boundary rather than a hedge. The no-cursor
result is bought by re-readability, so it must not be inherited by a source that
does not have it, and the condition is stated so a later lane cannot reach it by
adding a source rather than by amending a rule. A cursor would also be new durable
state under ADR-0083 §6's upgrade-with-state discipline — the reason ADR-0083 §13
declined to decide the observation cursor inside a lifecycle ADR — and the same
reason applies here with the same force.

> **Normative.** Re-reading is safe in the sense that matters — nothing the store
> holds is destroyed by a re-read — and it is **not** free of duplicates. A sensor
> mints its own id per record (ADR-0092 §6), so a re-proposed entry is folded by
> *similarity* at the gate and not by identity, and an entry rewritten between
> reads may land as a second live record.

This is the sensor's version of ADR-0077 §8's "re-observation is safe by
construction", and the honest difference is that the observer's safety came free —
the gate folds a repeat into a `REINFORCE` — while a sensor's is now known to be
partial. **ADR-0092 has since answered the question this clause was written
against, and it answered it more narrowly than this ADR expected**, which is worth
recording rather than smoothing over: an earlier draft made "a re-proposed entry
folds rather than duplicates" a *precondition* of ever scheduling a sensor. ADR-0092
§6 rules that an import "proposes each record at an id it mints, opaque to the
source" and may never use the source's own key, and §7 spells out the consequence —
"a small edit folds; a rewrite duplicates", filed as **#631** and explicitly *not*
closed. Read literally, the old clause would therefore have gated scheduled
ingestion on something ADR-0092 declines to provide, forbidding forever what it was
written to sequence.

The premise that survives is the one ADR-0092 §7 actually establishes, and it is
enough: **the failure is duplication, not loss.** Two live records are both visible
to ADR-0073 §1's enumeration with their bands, ADR-0072 §5 ranks `ASSERTED` above
`ATTESTED` when assembling context, and the user can kill either (ADR-0073 §5).
That is a materially different thing from the resurrection ADR-0038 §2a described,
and it is what makes a periodic re-read tolerable rather than merely convenient.

**Two costs are accepted and named, because a bound always has them.** An entry
that falls outside the window before any run reads it is never proposed; and an
entry inside the window is re-read every run, moving `provenance.last_updated`
and therefore the inspection sort key (ADR-0073 §2) exactly as ADR-0077 §8 accepted
for re-observation. The first is the price of not carrying a cursor and is
correct for a calendar, where an entry outside the window is not a belief this
system should be forming. The second is a true statement about us and is what
ADR-0092's report-time field exists to keep from being mistaken for a statement
about the source (ADR-0073 §4).

### 6. Driving: a scheduler job that is an `Engine` call, and it may ship enabled

> **Normative.** A sensor is driven by a job on ADR-0083 §7's scheduler. The job's
> body is a public `Engine` call and holds no store, no sensor and no subsystem
> import, exactly as ADR-0083 §8 requires of every job.

ADR-0083 §7 is explicitly built to be extended this way — it describes a job
arriving "on this list by configuration, which is the shape §8 is built for" — so
adding one uses the mechanism rather than changing it (§12 applies the test).
`Engine` grows an ingestion operation for the job to call: new concrete surface in
`orchestration`, not `core` contract surface, on ADR-0083 §8's precedent that "the
`Engine` therefore grows a maintenance surface".

> **Normative.** **Ingestion** is never wired into a turn: no request-time run
> proposes anything, and there is no ambient trigger. The facet read of §3 is
> permitted at assembly time, must respect §5's bound, and proposes nothing.

The line is drawn between the two halves rather than across the sensor, and
ADR-0077 §8's first reason is what places it: "Nothing is waiting on it, and a
turn is." Ingestion has a model-free but unbounded-in-consequence tail — a policy
ruling, a write, possibly a parked question — and nobody is waiting for any of it.
The facet is the opposite: the turn is *precisely* what is waiting for it, it is
what ADR-0008 built `assemble()` to compute fresh each call, and ADR-0008 §2 made
`contribute` async "because future sources (a calendar API) are I/O-bound". A
source fault on that path is degradation, not a failed request (§3, §8).

> **Normative.** A sensor's job may ship enabled once §9's gate is discharged. The
> reason observation ships disabled is specific to observation and does not
> transfer.

Stating this is the point of §5. Left unstated, the next lane reads "the
observation job ships disabled" as the house posture for scheduled ingestion and
ships a switch nobody can safely flip — which is the same mistake ADR-0083 §7 was
careful *not* to make when it named the disabled default's reason instead of
assuming it. Enablement is still configuration and still defaults to off, for the
different reason §7 gives.

> **Normative.** A failing sensor job never takes the process down. It is logged
> with its class and retried at its next due instant.

ADR-0083 §7 unchanged, and it is a stronger fit here than for the jobs that clause
was written for: a sensor's source is a file the system does not own, so
unreadability is an ordinary state of the world rather than a defect.

### 7. Configuration and enablement — and configuration is not consent

> **Normative.** Leg 6 configures exactly one source, by explicit `Settings`
> fields. There is no source registry and no list-valued source configuration.

The precedent is ADR-0083 §7's own: `retention_purge_interval`,
`conversation_sweep_interval` and `observation_interval` are three flat fields,
not a table. A registry is a schema decision with a validation story, and one
source does not buy it. Revisit at the third source, which is also roughly when
§11's grant question stops being deferrable.

> **Normative.** A sensor's interval follows ADR-0083 §7's convention exactly:
> a `timedelta` refused at load unless finite and strictly positive, with
> **disabled spelled `None`, never `0`**.

The reason is ADR-0083 §7's and applies without modification: the scheduler re-arms
from completion, so an interval of zero makes the job due again the instant it
finishes, and "off" and "as fast as possible" look identical in a config file.

> **Normative.** Every sensor ships **disabled by default**, and the reason is
> that nothing may read a user's personal files because a default said so — not
> that anything technical is missing.

Naming the reason is what stops the default flipping the day the technical
obstacle clears. It also places the default correctly relative to the grant
question: a fresh install that read a calendar unasked would be making the grant
decision by omission, which is the one way it must not be made.

> **Normative.** A sensor's configured location is validated for **shape** at
> load — for a filesystem source, that the path is absolute — and for
> **existence and readability** at run time, where it degrades under §6 rather
> than refusing to start.

The split follows what each thing is a property of. `Settings` already refuses a
non-absolute `data_dir` at load, and ADR-0008 §4 puts a malformed timezone at
startup "not a request-time failure", because both are properties of the
configuration. A file's existence is a property of the world at an instant: a hub
that refused to start because a calendar file was on an unmounted volume would
turn an advisory source into a boot dependency, which is precisely the coupling
ADR-0008 §4 declined for the whole context subsystem.

> **Normative.** A filesystem source is **opened non-blockingly**, its descriptor
> is then checked to be a regular file, and only then is anything read. The check
> is made on the descriptor, never on the path before opening it, and a source
> that is not a regular file raises `SensorError` under §8.

> **Normative.** `calendar_max_bytes` is enforced **on the read itself** — at most
> the cap plus one byte is consumed, and exceeding it raises under §8. It may not
> be enforced by a size check performed before the read.

> **Normative.** **The whole of a read runs off the event loop** — resolving the
> path, opening it, reading it, parsing it, and expanding recurrences alike. It
> runs on a worker the **sensor owns**, never on the event loop's default executor,
> and the sensor awaits that worker. Nothing `read()` does that is bounded by §5's
> figures may run on the loop.

> **Normative.** A sensor worker is **terminable at process exit**: neither
> service shutdown nor interpreter shutdown may join it, and a read blocked
> indefinitely may not delay or prevent the hub exiting. A daemon thread meets
> this; a `ThreadPoolExecutor` does not.

**The obligation is the exit, and the mechanism is named only because the obvious
one fails it.** "Owned, and not the default executor" is not sufficient and an
earlier draft stopped there: a dedicated `ThreadPoolExecutor` satisfies both words
and still hangs, because `concurrent.futures.thread` registers an interpreter-exit
hook that joins its workers — so `serve()` returns, `asyncio.run` finishes, and the
process then waits on the same stalled syscall one layer lower down. The
requirement is therefore stated as a property of the worker rather than of its
owner, and a daemon thread is named as the cheap way to hold it. An equivalently
terminable mechanism — a separately killable subprocess, say — meets it too, and
that choice is the sensor lane's.

> **Normative.** A sensor owns a **deadline** on its own read,
> `calendar_read_timeout` (§7a). On expiry it raises `SensorError` under §8.

> **Normative.** A sensor holds **at most one outstanding worker**. The
> reservation is released when the *worker* completes, never when the coroutine
> exits — so it survives a deadline expiry, an externally delivered cancellation,
> and any other early return alike. While it is held, a new `read()` raises
> `SensorError` immediately and starts nothing.

**Neither clause is defensive hygiene; each closes a hole the other bounds cannot
reach.** A path that is absolute and readable satisfies §7 exactly and may still be
a FIFO — or a symlink to one — with no writer at the other end. Every bound then
sits behind an operation that never returns, so the byte cap, the entry cap and the
expansion budget are all unreachable. **On ADR-0083 §7's scheduler that is not one
stalled job.** That loop is deliberately serial, and it accepts starvation on the
explicit ground that "a missed or late tick is never a correctness bug" — reasoning
that holds for jobs that *finish late* and not at all for one that never finishes.
A hung sensor read takes the retention purge and the conversation sweep down with
it, indefinitely, and every one of them looks merely slow.

**The clause covers the whole read and not just its I/O, and an earlier draft said
"filesystem work".** That version left the loop exposed to the other bounded thing
this ADR permits: §7b's budget allows 100,000 occurrence expansions, and an 8 MiB
calendar within every stated cap can require them. Run on the loop after the worker
returns, that CPU work starves the serial scheduler exactly as a blocked syscall
does — and worse for the deadline, because the timer callback cannot fire while the
loop is occupied, so `read()` overruns `calendar_read_timeout` and then *returns
successfully* instead of raising. A deadline that cannot be observed is not a
deadline. Putting the whole read on the worker is also the simpler rule: there is
no boundary inside `read()` for a reader to get wrong.

**`O_NONBLOCK` closes the FIFO case and closes nothing else, which is why the
clauses above exist.** The flag is a no-op for a regular file, and nothing about
being a regular file makes an operation return: a path on a stalled NFS or FUSE
mount — `/mnt/sshfs/calendar.ics` — stays a perfectly ordinary regular file while
every syscall against it hangs, including the path resolution that precedes the
`fstat` guard. Run on the event loop that starves the scheduler exactly as this
section warns for a FIFO, and it breaches `CONTRIBUTING.md`'s "**Async for all
I/O.** No blocking calls on async code paths" besides. A worker plus a deadline is
what makes the hang the *sensor's* problem instead of the process's.

**The deadline is the sensor's own, and the corpus already distinguishes that
case.** `core/protocols.py`'s cancellation preamble allows a deadline "a method
itself raises to enforce a deadline it owns" to be "its own control flow and may be
classified into a return value — that is exactly what `ToolInvoker.invoke` does on
expiry (ADR-0029 §4)". §8's carve-out for a cancellation delivered *from outside*
is untouched: that one still propagates unchanged.

**The one-worker clause is the honest half, and it is stated because the
alternative is a lie.** A thread blocked in a stalled syscall cannot be killed, so
the deadline abandons it — and ADR-0060 requires that a resource be "still held
exclusively by work the method started", never "left held with nothing running that
will release it". One abandoned worker per sensor, with no second read started
behind it, is the strongest form of that available when the kernel will not give
the thread back: the count is bounded at one, the sensor keeps reporting the fault
on every tick, and a mount that recovers releases the worker. What must not happen
is a scheduler that quietly accumulates one stuck thread per interval forever.

**The worker is the sensor's own and not the loop's, and that is a shutdown
requirement rather than a stylistic one.** The hub runs as `asyncio.run(serve(settings))`
(`src/ai_assistant/service/hub.py`), and `asyncio.run` shuts down the **default
executor** before returning — which means *joining* its threads. A stalled read
offloaded to the default executor therefore hangs the process at teardown, after
the scheduler job has already failed and reported: shutdown looks like it is
draining and is in fact waiting on a syscall that will never return, and the
operator's only recourse is `SIGKILL`. That is precisely the outcome ADR-0083 §4
builds a two-phase shutdown to avoid, reached around it rather than through it.

**Abandoning the worker is safe, and it is safe for a reason specific to this
seam.** ADR-0083 §4 bounds what it can and leaves unbounded only what must not be
interrupted; a sensor read is neither. It holds no lock, opens no transaction,
writes nothing, and its result is discarded the moment §8 raises — so there is no
state to corrupt by walking away and nothing for a later run to reconcile. That is
what makes it different from the engine drain ADR-0042 §2 protects, which waits
because an interrupted write is a torn one. The thread ends when the kernel returns
or when the process does.

> **Normative.** `Sensor` gains **no lifecycle method**. There is no `close`, no
> `aclose`, and nothing for a caller to await at shutdown.

Adding one is the obvious move and it is the wrong one: the only thing a `close`
could do about a thread blocked in an uninterruptible syscall is wait for it, which
re-creates the hang this section just removed while making it look handled. A seam
that cannot honour a lifecycle method should not carry one — and the abandonment
rule above is what makes carrying one unnecessary rather than merely awkward.

**The reservation is keyed to the worker and not to the deadline, and an earlier
draft keyed it to the deadline.** That version left the accumulation reachable by
the shorter route: a read of a stalled mount cancelled *from outside* before its ten
seconds elapse must, under §8 and ADR-0060, re-raise `CancelledError` promptly — and
the worker is still in the syscall when it does. A guard released on "the coroutine
exited" therefore clears while the thread is alive, and the next tick starts a
second one, which is exactly the unbounded growth the clause exists to forbid,
arriving through the one exit path ADR-0060 makes mandatory. Keying on the worker
makes every exit path — return, deadline, cancellation — release the reservation at
the same moment, which is the only moment at which releasing it is true.

**The non-blocking open is load-bearing, and an earlier draft that checked the
descriptor after an ordinary open did not work.** On POSIX, opening a FIFO for
reading *blocks until a writer appears*, so the descriptor the check wanted to
inspect is never produced and the check is never reached — the hazard survives the
clause written to close it. Opening with `O_NONBLOCK` returns immediately for a
FIFO, which is what lets the regular-file test run at all; for a regular file the
flag is a no-op, so nothing is paid for the guard. Checking the descriptor rather
than the path additionally closes the swap between the two operations.

The second clause is the same hazard in its ordinary form: a source checked for
size and then read is a source that can grow or be replaced in between, so the cap
describes a file that no longer exists by the time the bytes are consumed. Reading
one byte past the cap and refusing is the form that cannot come apart, and it is
the same ordering ADR-0017 §3 requires elsewhere — check where the operation
happens, not before it, "otherwise an implementation reads it, then checks, then
stops".

> **Normative.** A sensor's identity is **declared by the sensor** and is not a
> configurable value. It is a stable Tier 2 name, never derived from the source's
> location or contents; a path, filename, address or account identifier may not be
> used as one. The calendar sensor's identity is `"calendar"`.

> **Normative.** No configurable display label is added this wave. A surface
> renders `Attestation.reported_by`, which for the calendar sensor is its declared
> identity.

ADR-0092 §3 hands this lane exactly one question — "whether a human-facing display
label is configured alongside it is the sensor-seam lane's… and is **not** this
field; a surface with no label falls back to `reported_by`" — and the answer is no,
for this wave. A label distinguishes *instances*, and §7 configures one source, so
a label would have nothing to distinguish it from. It would be surface with no
consumer, which is the rule ADR-0092 §10 invokes against its own candidate third
field (ADR-0045 §1, ADR-0028 §7). ADR-0092 already supplies the fallback, so
declining costs nothing and leaves the question live at the point where it acquires
a subject: §11's registry deferral, when a second instance of one source type
exists. Answering it rather than letting it sit unclaimed between two merged ADRs is
the point of this clause.

**Declared rather than configured, and an earlier draft had this wrong.** It said
"configured", which §7a's table then failed to provide a field for — the
inconsistency adversarial review found. Resolving it by *adding* the setting is the
worse of the two repairs, and the reason is this section's own rule: the identity
lands in `Provenance`, in every export and in every log line, which is the one
place ADR-0004 §5 forbids Tier 1 data. A free-text setting is precisely the
mechanism by which a user would put their email address or a path there, and no
validator can tell a chosen label from a personal one. A declared constant cannot
carry personal data at all, which is a property rather than a rule. Revisit when a
second instance of one source type exists and needs distinguishing — the same
point at which §7's registry deferral fires.

This is `ContextSource.name`'s obligation, and it is stricter here rather than
merely inherited, because a sensor's identity has a second consumer. That
docstring already requires the name be Tier 2 "and must stay that way… A source
that wraps personal data names *itself* (`"calendar"`), never the data it holds".
For a sensor the identity is also what ADR-0073 §4's gate carries onto a stored
belief and renders back to the user — so a path used as an identity would put a
home directory and a filename into `Provenance`, into every export, and into every
log line, in a system whose ADR-0004 §5 rule is that logs never contain Tier 1
data. It is stated as its own clause because "used for logging" has been read as
licence before (ADR-0055), and here it would be read as licence twice over.

> **Normative.** Configuration is not a grant, and no surface may present it as
> one. A `Settings` field cannot be revoked by the user through the assistant,
> cannot be scoped, and leaves no audit record.

The grant model is deferred (§11). What is decided here is that the deferral is
not quietly discharged by the configuration this section adds — which is exactly
what would happen if leg 6's exit test ("from a source the user granted") were
read as satisfied by an operator having set a path.

#### 7a. The calendar sensor's figures, named here rather than left to its lane

§5 invokes ADR-0074 §9.3's rule that a bounded default with no figure is two
conforming implementations diverging while each believes it conforms, so the
figures are named. Nine fields, and the reason each exists rather than only its
value — because the *dimensions* are the decision and the numbers are revisable:

| Field | Default | Range | What it bounds |
| --- | --- | --- | --- |
| `calendar_sensor_path` | `None` | absolute path | the source; `None` is disabled |
| `calendar_sensor_interval` | `None` | `> 0` | the cadence; `None` is disabled (§7) |
| `calendar_window_past` | 1 day | `[0, 3650 days]` | how far back the clock-relative window reaches |
| `calendar_window_future` | 7 days | `(0, 3650 days]` | how far forward it reaches |
| `calendar_max_entries` | 500 | `[1, 2**63)` | entries in the window, and so proposals |
| `calendar_max_bytes` | 8 MiB | `> 0` | the source read **before** parsing |
| `calendar_max_expansion` | 100,000 | `[1, 2**63)` | occurrences considered across the whole read (§7b) |
| `calendar_read_timeout` | 10 s | `> 0` | the sensor's deadline on its own read (§7) |
| `calendar_max_content_bytes` | 4 MiB | `> 0` | proposal content materialised across the whole read |

**The sensor's identity is deliberately not in that table.** It is declared, not
configured, for the reason given above this subsection: a free-text setting is how
a path or an address would reach `Provenance` and the logs.

**The two nullable fields interact, so the four states are named rather than left
to compose.** A path locates the source; an interval arms the scheduled ingestion
job. They are separate because the two consumers of §3 are separate, and the
product is four states of which one is incoherent:

| `..._path` | `..._interval` | Meaning |
| --- | --- | --- |
| `None` | `None` | Fully disabled. **The default.** |
| set | `None` | **Facet only** — the shape the facet path takes, and **not reachable until the facet lands** (below). |
| set | set | Both paths live, subject to §9's two gates. |
| `None` | set | Incoherent — refused at load. |

> **Normative.** A configuration with a sensor interval set and that sensor's
> source location unset is refused at load with a `ConfigurationError`.

> **Normative.** The facet-only state is **reserved, not enabled**. Until an ADR
> adds the calendar facet as an optional `CurrentContext` field, a source location
> with no interval configures a source that **nothing reads**: no adapter is
> registered and no file is opened. A lane may not ship the adapter before that
> field exists.

The refusal follows this section's own posture — a figure the runtime would refuse
must fail at load — and the alternative outcomes are all worse and all silently
different: a scheduler that omits the requested job reports health while running
nothing, one that arms it re-runs a failing job forever, and one that treats it as
a source fault turns a configuration mistake into an infinite retry.

**An earlier draft called facet-only "a real deployment, not a degenerate one" and
said a deployment could have a live calendar facet today. That was wrong, and the
error is worth recording because it is the kind a matrix invites.** Naming four
states made the second one *look* live, and nothing in §7a checked whether the
thing it enables exists. It does not: ADR-0008 §1 requires a facet to arrive as an
**optional `CurrentContext` field** added by its own ADR, `CurrentContext` has no
calendar field, and §11 defers that decision out of this lane by the dispatch's
fence and by ADR-0092 §10's matching sequencing. An adapter shipped today could
only read the user's calendar and contribute an empty mapping — I/O on personal
data in exchange for nothing, which is the worst available trade and precisely what
§7's disabled-by-default clause exists to prevent.

So the state is **reserved**: §3's design says what the facet path will be, and §7a
says it is not wired until there is a field to contribute to. The sequencing this
wave was split to allow is still real, just one step longer than the draft claimed
— the facet ADR is the step, and it is named in §11 rather than assumed.

Six of the nine are decisions rather than figures pulled from the air:

- **The window is two fields, not one.** A calendar's usefulness is asymmetric:
  the future is what the assistant needs to know about, and the past is only
  wanted at all so that "this morning" is still in view. One symmetric horizon
  would have to be sized for the future and would then drag a week of history
  along with it. The defaults are deliberately small, following ADR-0077 §1's
  posture on `observation_batch_size` — "a handful of exchanges, not a month of
  transcript" — and for the same reason: this is Tier 1 data being read and
  proposed, and a bound nobody argued is a payload nobody measured.
- **`calendar_window_past` may be zero and `calendar_window_future` may not.** A
  deployment that wants only what is ahead is coherent; one that wants a window of
  zero width has configured a sensor that reads nothing while reporting health,
  which is exactly what ADR-0077 §1 refused for a zero batch.
- **Both are bounded *above*, and the ceiling is not decoration.** `> 0` alone
  admits `timedelta.max`, for which `read_at + calendar_window_future` is not a
  representable instant — so a figure that passes a load-time range check produces
  an `OverflowError` on the first run, escaping §8's two outcomes entirely and
  reaching the scheduler as neither a source failure nor a cancellation. Ten years
  is far past any calendar anyone reads and far short of the representable limit,
  which is the whole requirement of the number.
- **`calendar_max_bytes` is separate from `calendar_max_entries`, and it is the
  one that must exist.** An entry cap can only be applied *after* parsing, so a
  cap on entries alone lets a 2 GiB `.ics` file be fully parsed before anything
  refuses it — the bound applied one step too late to bound the work. The byte cap
  is checked against the source before parsing begins. This is the same ordering
  ADR-0017 §3 requires of a credential read ("otherwise an implementation reads
  it, then checks, then stops"), applied to a parse.
- **`calendar_max_expansion` bounds a *different* thing from the other two**, and
  §7b argues why neither substitutes for it: it bounds the occurrences a read makes
  an implementation *consider*, which is unbounded by both the byte cap (a
  pathological component is tiny) and the entry cap (that counts what lands in the
  window, not what is walked to reach it). It is spent across the whole read rather
  than per component, for the reason §7b gives.
- **`calendar_max_content_bytes` bounds the *output*, which none of the others
  do.** `calendar_max_bytes` bounds what is read, `calendar_max_entries` how many
  occurrences come back, and `calendar_max_expansion` the work of finding them —
  and a source can satisfy all three while the proposals blow up. One recurrence
  carrying a near-8 MiB field with exactly 500 in-window occurrences is inside every
  other cap and materialises roughly 4 GiB, because an occurrence repeats its
  component's content and nothing was counting bytes on the way out. The budget is
  a single accumulator across the read, like `calendar_max_expansion`, and it is
  checked **before** each proposal is materialised rather than after — the same
  ordering as the byte cap, for the same reason: a check that runs after the
  allocation has already paid for it.
- **All four caps refuse rather than truncate** (§5), so exceeding any raises under
  §8. A deployment with a genuinely larger calendar widens the cap or narrows the
  window, and does so knowingly.

**These figures belong to the calendar sensor, not to the `Sensor` contract.** What
the contract obligates is §5: bounded, named, refused at load, derived from the
clock and configuration alone, and enforced by refusing. A second sensor names its
own dimensions — a mailbox's would not be a time window — and inherits the
obligation, not the table.

#### 7b. Three `.ics` semantics that §5's argument depends on

A window and a cap do not define themselves, and adversarial review demonstrated
that two implementations can satisfy §7a's table exactly and still disagree. Three
of those disagreements are not the sensor lane's to settle, because **§5's
no-cursor result is false under the wrong choice** — which makes them this ADR's.

> **Normative.** An entry is in the window when its interval **overlaps** the
> window. Membership is never decided on the start instant alone.

This is the one that would have broken the ADR. Under start-instant membership, an
event that began before the window and is still running is excluded by *every*
future run — the window moves forward and the event's start recedes — so it is
permanently unreachable. That is exactly the coverage failure §5 argues a sensor
does not have, reintroduced by a filter choice rather than by a missing cursor, and
it fails hardest on the entry the facet most wants: the meeting happening now.

> **Normative.** The window's endpoints **saturate** at the representable bounds:
> where `read_at + calendar_window_future` is not representable the upper edge is
> the maximum representable instant, and likewise the lower edge at the minimum.
> The same saturation governs **every instant these sections compute**, including
> §7b's seek anchor `window_start - D` and any override's own anchor. None of this
> arithmetic raises.

The bounded figures above make an overflow unreachable from configuration alone,
but not from configuration *and* a clock: a conforming ADR-0026 reading close
enough to the representable maximum overflows even the seven-day default, and a
sensor is not entitled to assume where in time the clock sits. Saturation is total
where a check is conditional, and it loses nothing — there is no entry beyond the
maximum representable instant to exclude, so the clamped window and the ideal one
select the same set. It is deliberately **not** a refusal: a clock that near the
limit is a wiring problem the sensor neither causes nor can diagnose, and turning
it into a `SensorError` would report a source fault against a source that is fine.

**It is stated over every computed instant rather than over the window's edges
alone, because an earlier draft said the latter and §7b's seek anchor escaped it
immediately.** A yearly event with a multi-millennium `DURATION` makes
`window_start - D` underflow *before* the seek begins, leaving an implementation to
raise a raw arithmetic error or skip an occurrence that genuinely overlaps —
breaking §8's error contract or §7b's overlap rule respectively, and the second one
silently. Saturating the anchor is right for the reason it is right at the edges:
there is no instant before the minimum for a predecessor to have started at, so the
clamped anchor and the ideal one reach the same occurrences.

> **Normative.** Both intervals are **half-open**. The window is
> `[read_at - calendar_window_past, read_at + calendar_window_future)` and an
> entry's interval is `[start, end)`. An entry with a non-zero duration overlaps
> when `start < window_end` and `end > window_start`; a zero-duration entry
> overlaps when `window_start <= start < window_end`.

"Overlaps" alone is not a predicate, and the gap is not academic: an event ending
exactly at the window's lower edge is in under a closed reading and out under a
half-open one, which — with the cap otherwise exactly filled — is the difference
between a successful read and a refusal, from identical settings and an identical
clock. Half-open is chosen because it is the reading under which adjacent windows
partition time without double-counting, which is the property anything comparing
two runs will want. The zero-duration arm is stated separately because the general
overlap test degenerates for it: `end > window_start` is false for an instant
sitting exactly *on* `window_start`, which would silently exclude the one entry
shape that has no duration to spare.

> **Normative.** A recurring entry is counted and proposed as its **occurrences
> within the window**, not as the one component that generates them.

`calendar_max_entries` exists to bound work and payload, and both scale with
occurrences. A single `VEVENT` carrying `RRULE:FREQ=SECONDLY` is a few dozen bytes
— so `calendar_max_bytes` does not catch it — and expands to hundreds of thousands
of occurrences in the default window. A cap counting components would accept it
while the sensor built the tuple the cap exists to bound.

> **Normative.** A component the source marks **cancelled contributes no
> occurrences**, and this is decided before anything is counted or proposed. A
> cancelled master contributes none at all; a cancelled `RECURRENCE-ID` override
> removes the single occurrence it names.

> **Normative.** A `RECURRENCE-ID` override is resolved **against its master's
> expansion before anything is counted or proposed**. It replaces the occurrence it
> names; where it carries `RANGE=THISANDFUTURE` it replaces that occurrence **and
> every later one**, and where it is also cancelled it removes them. A removed or
> replaced occurrence is never counted and never proposed.

> **Normative.** An override whose form a sensor cannot interpret **suppresses the
> occurrences it could affect** rather than leaving them to the master. Where the
> affected extent is itself unknown, the whole series is suppressed.

**The range form is named, and the unnamed forms fail closed.** An earlier draft
said an override "replaces the occurrence it names", which is right for the common
form and wrong for `RANGE=THISANDFUTURE`: for a daily 09:00 master with an in-window
override moving 3 August to 10:00, that rule leaves 4–7 August proposed at a time
the calendar no longer says. An override is a *correction*, so mis-scoping one does
not merely omit information — it proposes stale information as current, which is
worse than proposing nothing. Hence the second clause: an override the sensor
cannot interpret suppresses what it might have changed, because the master's values
for those occurrences are known to be untrustworthy and nothing else is. That is
the same fail-closed posture §5 takes on a source too expensive to read, applied to
one too complex to read, and it is deliberately stated over *forms* rather than
over the two this round happened to enumerate.

**The cancelled-component rule is stated over components rather than over
overrides, and an earlier draft covered only overrides.** That version left the
plainer case open: a recurring `VEVENT` carrying `STATUS:CANCELLED` and no
`RECURRENCE-ID` is a master, not an override, so nothing suppressed it and every
in-window occurrence would have been counted and proposed — beliefs in a whole
series of meetings the calendar marks off. Keying the rule on *what the source
says about a component* rather than on which kind of component it is covers both,
and covers whatever third shape the format has that neither of us enumerated.

**Not emitting an occurrence the source says does not occur is not "proposing an
absence", and the distinction is worth stating because §4's rule looks like it
forbids this.** §4 governs what a sensor *asserts about the world* — it may not
claim a thing was cancelled, and may not retract a belief on the strength of a
reading. Declining to propose an occurrence that the source's own content says does
not happen is neither: it is reading the source correctly. The alternative
readings are both worse and both were available. Emitting the cancelled occurrence
proposes a meeting the user's calendar explicitly says is off. Emitting some
"cancelled" marker is the absence claim §4 actually forbids. Resolving overrides
into the expansion first makes the question disappear rather than answering it,
which is why the ordering is normative rather than advisory.

**The residual is the one §11 already carries.** An occurrence proposed by an
earlier read and cancelled since leaves a stored belief that this read does not
retract — because §4 forbids the sensor retracting anything, and because a bounded
or failed read is indistinguishable from a cancellation. The belief goes stale
rather than wrong-and-invisible: it stays live, enumerable with its band, and the
user can kill it (ADR-0073 §5). Closing it is the retraction decision §11 defers,
and this case is exactly the one that will motivate it.

> **Normative.** `calendar_max_entries` counts **in-window occurrences before
> interpretation**, and the cap is applied before the skip rule below. An
> uninterpretable occurrence counts towards the cap, and a source whose in-window
> occurrence count exceeds it raises under §8 without any occurrence being
> interpreted.

The order is load-bearing and the two rules contradict without it: 501 in-window
occurrences of which all 501 are uninterpretable would, under skip-first, produce a
successful empty reading from a source that busted its cap — a refusal turned into
a false "your calendar is clear", which is the failure §8 exists to prevent. It is
also the only order under which the cap bounds anything: interpreting 501 entries
to discover that 500 survive is precisely the work a cap is for.

> **Normative.** A recurrence is expanded by **seeking to the window**, never by
> enumerating from `DTSTART` and discarding what precedes it. The seek's lower
> bound is `window_start - D`, where `D` is the occurrence duration the component
> declares — never `window_start` itself. A component that overrides an occurrence
> is seeked on its own duration. Where a rule's form
> does not admit a seek, expansion is bounded by `calendar_max_expansion` — a
> **source-wide** budget of occurrences considered across every component of one
> read, default 100,000, range `[1, 2**63)`, refused at load — and a read that
> exhausts it raises under §8.

**An in-window cap does not bound the work of reaching the window, and this is the
one hole a byte cap cannot cover.** A component reading
`DTSTART:19700101T000000Z` with `RRULE:FREQ=SECONDLY` is a few dozen bytes and has
roughly 1.8 billion occurrences before it reaches a window centred on today. Under
`calendar_max_entries` alone a conforming implementation enumerates every one of
them to discover which fall inside, and the read that §5 calls bounded hangs. The
seek is the right answer for the rules that admit one, and the second bound is
belt and braces for those that do not — fail-closed, in the same posture §5 takes
everywhere else: a source too expensive to read is refused, not silently trimmed.
The two together are what make "bounded" a property rather than an intention.

**The seek is anchored a duration early, and anchoring it at `window_start` would
have reintroduced the defect this subsection opens by forbidding.** A yearly event
with `DTSTART` in 2020 and a multi-year duration has occurrences that are running
*through* a 2026 window; a seek to the first occurrence at or after `window_start`
lands in 2027 and skips every one of them. That is the start-instant membership
rule of the first clause above, defeated one level down by the optimisation added
to satisfy the second — and it fails on exactly the same entries, permanently,
because the window moves forward each run and the occurrence's start recedes.
Backing the anchor off by the declared duration is the smallest bound that cannot
miss an overlapping predecessor, since an occurrence starting before
`window_start - D` has already ended by `window_start`.

**The budget is source-wide rather than per component, and a per-component version
was tried and does not hold.** Under a per-component cap, an 8 MiB file can carry
thousands of non-seekable recurrences, each spending its full allowance to
establish that it has *no* in-window occurrence. Every component conforms, no entry
is produced so `calendar_max_entries` never fires, and the read still performs
hundreds of millions of steps. A budget that resets per component bounds each piece
of the work and not the work, which is the failure a bound exists to exclude. One
accumulator across the read is both simpler and the only version that is actually a
bound.

> **Normative.** An entry whose times are floating or date-only is localised in the
> configured `Settings.timezone`, the same value ADR-0008 §5 gives the temporal
> context. A sensor may not invent a second timezone source.

Two components resolving "today" against different zones is the class of defect
ADR-0026 exists to prevent, arriving through data rather than through a clock.

> **Normative.** A floating local time that a DST transition makes **ambiguous** or
> **nonexistent** resolves at `fold=0`. Such an entry is never skipped for sitting
> on a transition.

Naming the zone does not pin the instant, and the gap is not theoretical: in
`America/New_York` a floating `2026-11-01T01:30` is two distinct UTC instants and
`2026-03-08T02:30` is none. Two implementations obeying the clause above therefore
select different occurrences for one window and both conform, which is the
divergence this subsection exists to close. RFC 5545 does not settle it — a
floating time is under-specified *by the source*, so no reading recovers the
author's intent — which makes the requirement **agreement rather than
correctness**, and the cheapest available agreement is the platform default:
`fold=0` names the earlier offset for an ambiguous time and resolves a nonexistent
one through the pre-transition offset, deterministically in both directions with no
special case.

**Not skipping is the other half, and it is the half the user feels.** §7b skips an
entry the sensor *cannot interpret*; a time on a transition is interpretable the
moment a rule exists, and the entry is a real appointment someone holds. Skipping
would drop an hour of a calendar twice a year, and §4 forbids the sensor from
saying anything about the absence — so the loss would also be silent.

**What remains the concrete sensor lane's**, with a marked obligation attached:

> **Normative.** An entry a parseable source contains but the sensor cannot
> interpret is **skipped**, not raised on. A source that cannot be parsed at all
> raises under §8.

The distinction is between a read that *completed with gaps* and one that *could
not complete*, and it is ADR-0074 §5's rule carried unchanged — "an id that does
not resolve is **skipped, not an error**" — which ADR-0077 §8 applied with "A short
batch is the honest consequence of a gap". Skipping proposes nothing about the
skipped entry, so §4's absence rule is respected rather than strained. Everything
else about the format — which properties map to a proposal's content, exotic
`RRULE` and `EXDATE` forms, `RECURRENCE-ID` overrides — is the lane's, and it owes
deterministic tests for each boundary above: an event spanning the window's start,
one spanning its end, an event ending *exactly* at the lower edge and one starting
exactly at the upper, a zero-duration entry on each edge, an all-day entry at both
edges, a recurrence expanding past the cap, an uninterpretable entry among valid
ones, a source whose in-window occurrences are entirely uninterpretable and over
the cap, an old high-frequency recurrence whose expansion must reach the window
without walking to it, a long-duration recurrence whose occurrence began years
before the window and is still running inside it, **many** individually-cheap non-seekable recurrences with no
in-window occurrence between them, a missing configured path whose scheduled
failure is asserted **not** to put that path in the log line, a malformed source
whose parser failure quotes a distinctive event title — asserting neither the title
nor the raw cause message reaches a log — a path that is a **writer-less FIFO**, asserting the read
fails rather than hangs, a source that grows past `calendar_max_bytes` after it is
opened, a long-duration recurrence whose seek anchor underflows, a floating
entry at each of an ambiguous and a nonexistent local time, a **regular file whose
read is suspended**, and separately a **parse or expansion made to run long** —
each asserting the deadline fires, the event loop stayed responsive throughout, and
a second read is refused while the worker is outstanding — a recurrence whose
occurrences each repeat a large content field, asserting the content budget refuses
before memory is spent, a master recurrence with an in-window **cancelled
`RECURRENCE-ID` override** — asserting the occurrence is absent from the proposals,
absent from the cap's count, and that nothing is proposed about its cancellation —
a **cancelled recurring master**, asserting it contributes no occurrences at all,
a non-cancelled override, asserting it replaces rather than duplicates its
occurrence, a `RANGE=THISANDFUTURE` override both shifted and cancelled —
asserting later occurrences follow it rather than the master — an override of an
uninterpretable form, asserting the occurrences it could have affected are
suppressed rather than proposed from the master — and the
same suspended worker **cancelled from outside**, asserting `CancelledError`
propagates unchanged, a second read is still refused while the worker lives, and
reads resume once it is released — and, **in a subprocess**, a hub shut down while a read is
still blocked, asserting the process exits within a bounded time *with the read
still blocked*. The subprocess is not incidental: an earlier draft specified this
case in-process, asserting that the worker is released after shutdown completes,
which no exited process can be around to observe. Only an external observer can
watch a process die.

### 8. Failure has two postures, because the reading has two consumers

There is no single answer, and the two are already ratified in different places:

- **On the facet side, advisory.** ADR-0008 §4: an optional source's failure is
  skipped, the facet is `None`, assembly returns the rest. §3's adapter is
  optional, so this needs no new rule.
- **On the ingestion side, retried.** ADR-0083 §7: logged with its class, retried
  at the next due instant, never a process exit.

> **Normative.** A read either completes within its bound and returns a
> `SensorReading`, or **raises**. A read that cannot complete may not return what
> it managed to gather.

This is §4's absence rule reached from the other direction and it is worth its own
clause: a half-parsed calendar is not a smaller calendar. Proposing from a partial
read would write beliefs whose bound is the failure's shape, and nothing about the
stored record would say so.

> **Normative.** A `SensorReading` whose `proposals` tuple is empty is a
> **successful** reading, and means the source had nothing to propose within the
> bound. It is not a failure signal and no caller may treat it as one.

**Raising rather than returning an empty reading on failure is the decision here,
and the alternative was tried and is wrong.** If a failed read returned an empty
reading, the two states would be indistinguishable at the seam — and both consumers
need to tell them apart, in opposite directions:

- The **scheduled job** would report success on every failure. ADR-0083 §7's whole
  failure posture — "logged with its class… and the job is retried at its next due
  instant" — needs a failure to observe, and an empty reading gives it none. A
  sensor whose file was unreadable for a week would look healthy for a week.
- The **facet** would present "your calendar is clear" when the truth is "we could
  not read your calendar". That is the same class of falsehood §4's absence rule
  forbids, arriving through the other consumer.

An exception is also what ADR-0008 §4's degradation path is already built to
catch: the optional adapter of §3 skips a *failing* source and leaves its facet
`None`, which is a different rendering from a facet that is present and empty.

> **Normative.** A read that cannot complete **because of its source** raises
> `SensorError`, an `AssistantError` (§10), with the underlying failure preserved
> as its `__cause__`. A sensor may not let a source-level exception — an
> `OSError`, a parser's own class — cross the seam unwrapped.

> **Normative.** A cancellation delivered from outside the call is **excepted from
> the clause above**: it is delivered onward unchanged and is never converted into
> a `SensorError`. `read()` is bound by `core/protocols.py`'s cancellation clause
> and by ADR-0060 exactly as every other seam is.

The carve-out is stated rather than left to the general rule because the wording it
qualifies invites the mistake: a cancelled read has, in plain English, "not
completed", and a sensor wrapping everything it catches would convert it. The
preamble is unambiguous — "A cancellation delivered from outside the call is
delivered onward, never absorbed… it never converts such a cancellation into a
return value" — and a `SensorError` is a conversion of exactly that kind, with the
additional harm that both consumers would treat a caller's own cancellation as a
degraded source: the facet would degrade and the scheduler would log a source fault
and re-arm, on a shutdown (ADR-0083 §4) that was working correctly.

**An earlier draft ruled the opposite — "no new error class" — and it was wrong on
a standard the corpus states plainly.** `CONTRIBUTING.md` requires that a
subsystem "raise only from the `AssistantError` hierarchy (`core/errors.py`)", and
every seam here already has one: `MemoryStoreError`, `ContextError`,
`ConversationStoreError`, `DeferralStoreError`. Letting a `PermissionError` or a
parser's exception out of `read()` would make both consumers catch by *implementation*
— the `context/` adapter and the scheduler job would each need to know which
exceptions each sensor's parser can throw — and the alternative to that knowledge
is a bare `except Exception`, which swallows programming errors as degraded
sources. That is the failure the hierarchy exists to prevent, and it is worse here
than usual because §8's whole point is that a failure must be *distinguishable*.

Preserving `__cause__` is what keeps the wrapping from destroying the diagnosis:
ADR-0083 §7 logs a failed job "with its class", and a missing file, a permission
denial and a malformed document are three different operator actions.

> **Normative.** A `SensorError`'s **message is payload-free**: it carries the
> sensor's declared identity and the failure's class, and never the source's
> location, its contents, or any string derived from either. The cause is retained
> on the exception; only its **class** may be logged, never its message.

**Preserving the cause and logging it are different acts, and the obvious wrapper
conflates them.** `raise SensorError(str(exc)) from exc` satisfies every word of
the clause above it — and for a missing
`/home/alice/Private/therapy.ics` the resulting message *is* that path, which the
scheduler then writes to a log under ADR-0083 §7. That is Tier 1 data in an
operational log, which ADR-0004 §5 forbids outright, arriving through the one
mechanism §7 spent a whole clause keeping the identity out of. The path is exactly
as sensitive as the identity — arguably more, since a filename is chosen by the
user and a directory names them — so it gets the same treatment rather than a
weaker one because it arrived inside an exception. `PermissionError` and
`FileNotFoundError` are Tier 2 facts and are the useful half anyway: they tell an
operator which action to take, and the operator already knows the path, because
they configured it.

### 9. What ADR-0092 settled, and where this seam meets it

ADR-0073 §4 put a precondition on this wave in as many words: "The gate is on leg
6's first `EXTERNAL` producer: carrying **both** the reporting source's identity
and its report time is a precondition of it shipping, and whether that needs
`Provenance` to grow fields is a `core` decision for that lane — with a producer
in hand — not one to guess here." **ADR-0092 is that lane and it has answered.**
This section is therefore a boundary rather than a wait, and it records what the
answer was — including the half that came back narrower than this ADR expected.

**ADR-0092 has merged and stands `Proposed`; this ADR treats its text as the
corpus's and its status as its own lane's to finish.** The distinction is kept
rather than glossed, because §9 leans on three of its rulings. What makes leaning
safe is not optimism: `CONTRIBUTING.md` → "Trivial ADR edits" and ADR-0070 §1 both
class the `Proposed` → `Accepted` flip as an edit that alters no decision, so the
clauses cited below are as stable now as they will be after it. Were ADR-0092
instead to *change* at ratification, that would be a decision change owing its own
supersession, and this section would be owed a matching one.

> **Normative.** This ADR does not discharge ADR-0073 §4's gate and does not own
> the vehicle. `SensorReading` is where the source's identity, our read instant,
> and any reading-wide as-of the source declares enter the system (§3, §10). How
> they reach a stored belief is ADR-0092 §1's `Attestation` on
> `Provenance.attestation`, and the **per-entry** report time lives there, not on
> the reading.

The two ADRs meet cleanly and independently, which is the useful evidence that the
boundary was drawn in the right place. §10 below argues that a reading-wide `as_of`
must never be filled from a file's mtime, because that is a fact about our
filesystem rather than a claim the source made; ADR-0092 §3 rules the same
prohibition from the other side — "**not the file's mtime**, which is a property of
the last local write and is changed by a copy, a restore or a `touch`" — and
supplies the per-entry answer this ADR declined to guess: RFC 5545 makes `DTSTAMP`
mandatory on a `VEVENT`, so the calendar case has a true report time per
occurrence. Neither lane read the other's draft.

> **Normative.** ADR-0092 §6 settles imported-record identity: a sensor **mints its
> own id** for every record it proposes and may never use the source's key — a
> `VEVENT` `UID`, a row id, a URL — whether directly or namespaced.

> **Normative.** Scheduled ingestion is **not** gated on total idempotence, because
> ADR-0092 §7 declines to provide it. What a sensor may rely on is that a re-read
> destroys nothing; what it may not assume is that a re-proposed entry always
> folds.

**An earlier draft of this section gated scheduling on identity "making a
re-proposed entry fold rather than duplicate", and that gate is now known to be
unsatisfiable.** ADR-0092 §7 is explicit that identity is re-established by
similarity, so "a small edit folds; a rewrite duplicates", and it files the
residual as **#631** rather than closing it. A precondition written against an
expected answer became, on the real one, a prohibition without an exit. It is
replaced rather than quietly dropped, because the replacement is the substantive
point: the residual is duplication, and ADR-0092 §7's comparison is the reason that
is acceptable — under the source's key as the store's id the same similarity miss
"upserts onto `m1`, and the store keeps two live records *and* no record that a
retirement ever happened". Minting removes the destruction and leaves the
duplicate.

**Neither boundary reaches the facet path**, which writes nothing, proposes nothing
and touches no record — so when the facet lands it is gated by neither. That is the
point of both being about *ingestion* rather than about the sensor. It does **not**
make the facet reachable today: §7a reserves that state behind the `CurrentContext`
field this lane does not own.

> **Normative.** This ADR decides nothing about whether a user assertion may
> override an attested belief. ADR-0092 §4 rules that it may — `EXTERNAL` joins the
> supersedable class — and this seam conforms to that rather than restating it.

ADR-0038 §2a's exclusion of `EXTERNAL` from supersession was mechanical: it turned
on an external record's id being "the integrating system's idempotency key". That
premise is exactly what ADR-0092 §6 removes, which is why the mechanism and the
identity decision were one decision and why pre-empting either here would have been
cheap-looking and wrong.

### 10. The contract surface owed, and what the triad lane owes

**New surface in `core` — a breaking change (golden rule 5):**

- **`core/protocols.py`** gains **one** Protocol, `Sensor`, `@runtime_checkable`
  as the seams around it are, owing two members:
  - a **`name` property**, `str` — the stable Tier 2 identity §7 governs. It is a
    property rather than a constructor argument for `ContextSource.name`'s
    reason: the assembler and the ingestion stage both log it, and a seam that
    cannot be asked its own name forces every caller to carry one beside it.
  - an **`async read` method** taking no arguments and returning one
    `SensorReading`. It takes no arguments because §1 gives the sensor its own
    source and §5 makes the bound the sensor's own configuration: a caller able
    to widen the read is a caller able to defeat the bound, which is the property
    ADR-0077 §1 bought by putting the maximum on the producer.

  It is named for its product role, as every Protocol here is (`Planner`,
  `Observer`, `MemoryPolicy`).
- **`core/types.py`** gains **one** type, `SensorReading`: a frozen pydantic model
  (ADR-0068) because it crosses a subsystem boundary (`CLAUDE.md`), following
  `ObservationOutcome`'s precedent that a seam returning more than one fact
  returns a named value rather than a tuple. Four fields, and the deferred fifth:
  - `source: EncodableText` — the reading's Tier 2 identity, equal to the
    producing sensor's `name`. Carried on the reading rather than left to the
    caller so the value that reaches ADR-0092's vehicle is the producer's own.
  - `read_at: UtcInstant` — the instant **this system** performed the read. Always
    present, because it is always knowable and always true: it is our own clock.
  - `as_of: UtcInstant | None` — the instant **the source declares for the reading
    as a whole**, where the source declares one, and `None` where it does not.
    Never merged with `read_at`, because collapsing them is the exact defect
    ADR-0073 §4 describes: "a record synced on Tuesday from a calendar that said so
    on Monday renders 'Tuesday', which is a true statement about us and a false one
    about the source."

  **`as_of` is optional, and that is a decision rather than laxity.** A local
  `.ics` file declares no reading-level as-of: the format's report times are
  per-`VEVENT` (`DTSTAMP`, `LAST-MODIFIED`), and the file's mtime is a fact about
  our filesystem rather than a claim the source made. So the only two values a
  required field could take for the first source are a filesystem observation —
  which collapses the very distinction ADR-0073 §4 draws — or one entry's stamp
  applied to all of them, which is false for every other entry. A source that
  *does* declare one (a feed's `Last-Modified`, a sync API's server instant) has an
  honest home for it, and an empty reading is unaffected either way.

  > **Normative.** `as_of` carries only an instant the source itself declares for
  > the whole reading. It may never be filled from the filesystem, from the clock,
  > or from one entry's stamp applied to the rest.

  > **Normative.** Per-proposal report time is **not** decided here. Where a
  > source's report time is per-entry — as a calendar's is — it belongs on the
  > proposal, in ADR-0092 §1's `Attestation`, and a sensor sets it when
  > constructing the proposal. For the calendar sensor that value is the
  > occurrence's `DTSTAMP`, which RFC 5545 makes mandatory (ADR-0092 §3).

  This is the boundary between the two lanes taken seriously rather than
  approximately, and the outcome is the evidence it was worth the care. An earlier
  draft made `as_of` required at the reading level, which would have decided the
  *granularity* of ADR-0073 §4's report time — reading-wide — inside the seam ADR,
  leaving the lane that owns that gate unable to recover a per-entry time this
  contract never carried. ADR-0092 §1 then chose per-record, and §3 chose
  `DTSTAMP`; a required reading-level field would have been a contradiction to
  reconcile instead of a slot to leave empty. Deciding a neighbouring lane's
  question by choosing a field's cardinality is the quietest way to decide it.
  - `proposals: tuple[MemoryUpdateProposal, ...]` — possibly empty, which under §8
    means the source had nothing to propose within the bound and is a successful
    answer. A failed read raises and constructs no reading at all.
  - the **facet field, absent for now**, landing as an optional field under §3.

  `UtcInstant` and `EncodableText` are the existing `core` aliases; no new
  primitive is owed. `MemoryUpdateProposal` already exists, which is why the cost
  is one type rather than a family.
- **`core/errors.py`** gains **one** class, `SensorError(AssistantError)`, raised
  by §8 when a read cannot complete, carrying the underlying failure as its
  `__cause__`. One class and not a family: a missing file, a permission denial and
  a malformed document are the *same* fact to both consumers — the source could not
  be read — and they differ only in what an operator should do, which is what the
  cause and the log line carry. `ContextError` is not reused: it is reserved for
  "programmer/wiring bugs the assembler should not paper over" (ADR-0008 §4), and a
  calendar file that is absent is neither.
- **Nothing else.** No change to `MemoryWriter.ingest`, whose semantics §1 relies
  on exactly as ratified. `Provenance` is **not** touched here — that is
  ADR-0092's (§9).

An illustrative signature, in ADR-0073 §1's and ADR-0077 §9's form — the semantics
above are the contract, the spelling is the lane's:

```python
@runtime_checkable
class Sensor(Protocol):
    @property
    def name(self) -> str: ...

    async def read(self) -> SensorReading: ...
```

**What the triad lane owes, as one change (`CONTRIBUTING.md` → "Adding a
Protocol"):**

1. The Protocol and `SensorReading`, with `read_at`/`as_of` documented as the two
   distinct instants ADR-0073 §4 distinguishes, and `source` documented under §7's
   Tier 2 obligation in the form `ContextSource.name`'s docstring already uses.
2. **The shared conformance suite** — the clauses that bind **every** `Sensor`,
   which are the ones expressible without a source. Each maps to a ruling above:
   - `name` is stable across calls and non-empty (§7).
   - `read()` returns a reading whose `source` equals `name` (§10).
   - `read_at` is tz-aware; `as_of`, where present, is tz-aware. Neither is ever
     naive (ADR-0026 §1).
   - **No proposal is `EPISODIC`** (§4) — the clause that keeps §4's refusal a
     property of the seam rather than of one implementation.
   - **Every proposal is in the `ATTESTED` band**, i.e. `band_of` its provenance
     source is `BeliefBand.ATTESTED` (§4).
   - **An empty `proposals` tuple is a valid, successful reading** and every
     clause above holds on it (§8).
   - **A read that cannot complete for a source reason raises `SensorError`** —
     checkable generically against the canonical fake scripted to fail, and the
     clause that makes the leak this suite would otherwise miss detectable at all.
   - Input observation (ADR-0065) and cancellation (ADR-0060), as every seam owes —
     and cancellation here carries **one clause beyond the standard pair**: a
     `read()` cancelled from outside while suspended re-raises `CancelledError`
     unchanged and does **not** raise `SensorError` (§8). It is spelled out because
     it is the one place a conforming-looking sensor could satisfy every other
     clause on this list and still absorb a cancellation.
3. **The canonical fake in `ai_assistant.testing`**, scriptable to return a
   reading with proposals, an empty reading, and a read raising `SensorError` —
   the three states §8 distinguishes, so a consumer can test its own degradation path. That
   third capability is the gap ADR-0022 §Consequences filed against
   `FakeMemoryStore` as #105, not repeated here.

   **A fourth capability is required, and it is what makes the cancellation clause
   above testable at all:** the fake exposes the existing suspension gate —
   `SuspendableResource.suspend_next`, whose handle's `reached` and `release` are
   `ai_assistant/testing/cancellation.py`'s — so the suite can cancel a `read()`
   that has demonstrably arrived at an await, and only then. Without it the clause
   passes vacuously: a fake that completes immediately can only be cancelled
   *before* it starts, which exercises none of the code an implementation would use
   to catch a `CancelledError` during source I/O and convert it. That conversion is
   the exact failure the clause exists to forbid, so a test that cannot reach it is
   worse than no test — it reports the property as held.

**Four rulings above are deliberately *not* suite clauses, and putting them there
would be the error.** (§8's `SensorError` type *is* one, above; what is not is the
provenance of the failure that reaches it.) The test is whether a clause is decidable from `name` and
one `read()` return value, which is the whole of what a conforming `Sensor` is:

- **§5's bound refused at construction.** `Sensor` specifies no constructor and no
  configuration surface — `read()` takes no arguments precisely so a caller cannot
  widen the bound (§10) — so a generic suite has nothing to over-supply. This is
  where the shape differs from ADR-0077 §9, whose equivalent clause was testable
  only because `observe` *takes* the batch whose size the bound governs. It is a
  concrete sensor's test and a `Settings` test, and stating that here is what stops
  an implementation-specific rule from wearing the Protocol's authority.
- **That a *real* source failure is what raises.** A suite cannot make an
  arbitrary implementation's source fail, so it can pin the *type* (above) but not
  that the type is reached from a missing, unreadable or malformed source. Those
  three cases are the concrete sensor's tests, and they are named so the lane
  writes all three rather than the one that is easiest to provoke.
- **§4's "never proposes an absence."** A statement about what a producer declines
  to emit; nothing in a return value exhibits it.
- **§3's "neither consumer derives its answer from the other's reading."** A
  statement about how a *caller* wires two paths.

Each is named here so the triad lane does not read its absence from the suite as
its absence from the contract.

**What later lanes owe, and this ADR does not:** the concrete `.ics` sensor in
`sensors/`, the `context/` adapter and the facet, the `orchestration` ingestion
stage, the `Engine` operation, the scheduler job and its `Settings` fields, and
the `lint-imports` contract pinning §2.

### 11. Deferred, by name, each with the condition that fires it

- **A revocable permission-grant model.** `ActionPolicy` governs actions, not
  sources. Fires when a second source exists or when leg 6's exit test is
  evaluated against its own wording; §7's last clause exists so nothing reads
  configuration as having discharged it in the meantime.
- **What a context facet carries** — an as-of instant and provenance — **and the
  optional `CurrentContext` field itself.** §3 is additive precisely so this ADR
  does not decide it, and §7a reserves the facet-only enablement state until it
  exists: an adapter has nothing legal to contribute before there is a field to
  contribute to (ADR-0008 §1). It is the next step in this leg's sequence rather
  than a distant one, and ADR-0092 §10 sequences it the same way.
- **Whether an ingested record may ever be an `EpisodicMemory`.** §4 declines it
  for leg 6. Fires when something wants a timeline rather than beliefs; it needs
  an ADR arguing a capture exemption for an event this system did not witness,
  which is a larger claim than ADR-0075 §2 made and must be made on its own.
- **Retracting an attested belief when its source stops reporting it.** §4 forbids
  proposing absence, which makes this real work rather than a special case. Fires
  with ADR-0092's override mechanism, whose id discipline it shares.
- **A source that cannot be re-read in full** — a feed, a paginated API, a
  mailbox — and therefore the cursor. §5 scopes this contract to re-readable
  sources; ADR-0083 §13's upgrade-with-state discipline governs whoever takes it.
- **A networked source.** ADR-0017 §1 governs data leaving the device and §3's
  fourteen conditions govern designating the `tools/` seam. A remote calendar
  transmits a credential and a request, so it engages §1 and cannot be reached by
  changing a path to a URL — the same sentence ADR-0084 wrote about its own
  transport, for the same reason.
- **A source registry**, and with it a **configurable display label** (§7) and an
  instance-distinguishing `reported_by`. §7 revisits at the third source; the label
  acquires a subject at the second instance of one source type.
- **Folding a rewritten entry into its predecessor.** ADR-0092 §7's residual, filed
  as **#631**: identity is re-established by similarity, so a small edit folds and a
  rewrite duplicates. §5 relies on the narrower guarantee — a re-read destroys
  nothing — and does not assume this one. It fires on the first observed duplicate,
  which is the trigger #631 records.
- **#545's model in full** — expectations, the ledger, and met/not-met/unknown.
  That issue is a proposal carrying its own do-not-implement header, and leg 6
  builds one channel rather than the model. Its three prerequisites are what has
  near-term force, and this ADR touches the third and depends on the second.

### 12. This ADR classified under ADR-0070 §1 and ADR-0082 §1

ADR-0082 §1 requires the judgement to be made in the later ADR's text. It is made
here, clause by clause, and the answer is that **no earlier ADR's status line
changes**. The three places where the opposite reading is available:

- **ADR-0008 §2** keeps the `ContextSource` seam inside `context/`. §3 adds a
  *different* Protocol in `core` and has a `context/` adapter hold it. The
  full argument is in §3: §2's sentence scopes `context/`'s **output**, its stated
  purpose is that cross-boundary data be a `core` pydantic model and that nothing
  untyped escape, and both hold — `context/` already takes `core` contracts as
  inputs (`ClockContextSource` takes a `Clock`). A reader holding only ADR-0008
  would act no differently after this ADR than before it, which is ADR-0070 §1's
  test, unmet. No clause is changed; a new one is added beside it. Not an
  amendment.
- **ADR-0008 §5** says `assemble()` "computes fresh each call". §3's facet read is
  that clause obeyed, not narrowed: a fresh call reads the source. §6 restricts
  *ingestion* at request time, which ADR-0008 never granted and does not govern.
  Not an amendment.
- **ADR-0075 §2** listed a sensor among the producers that do *not* inherit the
  capture exemption and said each "may argue for the same exemption on the same
  grounds when it exists". §1 and §4 decline to argue it. Agreeing with a ratified
  clause is not amending it.
- **ADR-0083 §7's job table.** §6 adds a job. §7's own text describes a job
  arriving "on this list by configuration, which is the shape §8 is built for", so
  the table enumerates what shipped rather than closing the set. Using a mechanism
  as specified is not amending it. This is the ADR-0083 §15 pattern — examining a
  clause and finding it unmet — applied to three clauses at once.

**ADR-0092 — nothing owed, in either direction, and the pair was checked rather
than assumed.** Its §10 leaves "the sensor seam… in full" to this lane and its §3
leaves the display label here; §7 and §9 answer both and narrow neither of its
rulings. This ADR restates `Attestation`, §6's minting rule and §4's supersedable
widening as constraints it conforms to, and a reader holding ADR-0092 would act no
differently after reading this one — ADR-0070 §1's test, unmet. Under ADR-0082 §1
this ADR's own additions are **stacked additions** on it, recorded here and nowhere
else.

ADR-0073 §4's gate is *bound to* rather than discharged (§9); ADR-0038 §2a was
moved by ADR-0092 §8 and not by this ADR; ADR-0017 §1 and §3 are examined in
Context and found not to engage.

## Consequences

- **Leg 6 has a contract to implement against**, and the triad that follows is one
  lane rather than a Protocol plus an argument about what it means.
- **The no-cursor result is the load-bearing one.** A clock-relative bound makes
  scheduled ingestion honest without new durable state, which is what lets leg 6's
  source do the thing ADR-0083 §7 could not let observation do. It is bought by
  re-readability, and §5 names that so the next source cannot inherit it silently.
- **Two gates now sit visibly between this seam and a running sensor** (§9), both
  ADR-0092's. That is the intended shape: the contract can merge, and nothing can
  ship against it that would put an unattributable or duplicating belief in the
  store.
- **The `ATTESTED` band gets its first producer's shape**, and the band's whole
  premise — someone else's word, stale in ways we cannot detect (ADR-0072 §5) — is
  now expressed as rules rather than as a name: propose only, never write; never
  state an absence; and fail loudly rather than return a partial reading that
  reads as an empty one.
- **What gets harder:** a second source that is not a re-readable file needs its
  own decision rather than a new class, and an ingested timeline needs an ADR
  rather than a field. Both are deliberate — each would otherwise be reached by an
  implementation choice, and each is a larger claim than it looks.
- **A gap stays open and is now visible**: configuration is not consent, and leg
  6's exit test speaks of a source the user *granted*. §7's last clause makes that
  a stated debt rather than a sentence nobody re-reads.
- **Revisit when** a source arrives that cannot be re-read in full, when a third
  source makes flat configuration unwieldy, or when something needs the timeline
  §4 declines to write.

## Alternatives considered

- **Make a sensor a `ContextSource` and nothing more.** Smallest possible change,
  and it fails on reach: `ContextSource.contribute` returns a `Mapping[str, object]`
  that ADR-0008 §2 confines to `context/`, so the memory half would have no path
  out of the subsystem, and giving `context/` a `MemoryWriter` to fix that makes
  the advisory subsystem a belief producer.
- **Two Protocols — one for the facet, one for the proposals.** Rejected in §3:
  two reads at two instants, and a facet that can disagree with the beliefs
  written in the same run, with nothing recording that they came from different
  moments.
- **Give the sensor a durable cursor now, mirroring what observation is waiting
  for.** Rejected because the symmetry is false (§5), and because a cursor is new
  durable state under ADR-0083 §6 — it would owe the upgrade decision ADR-0083 §13
  declined to bury inside another ADR, and it would buy nothing over a
  clock-relative window.
- **Let a sensor write episodes directly under a capture exemption.** This is what
  #545's model wants and what ADR-0077 §8 anticipates. Rejected in §4: ADR-0075 §2
  reserved the argument rather than granting it, ADR-0075 §4 shows the gate would
  corrupt an episode that went through it, and the exemption would have to be
  argued for an event this system did not witness. It is deferred rather than
  refused.
- **Let a re-read retract what it no longer sees**, so a cancelled meeting stops
  being believed. Rejected in §4 as the seam's single most dangerous move: a
  bounded read, a truncated file and a permission error are indistinguishable from
  a deletion, so this trades a stale belief for silent destruction of the user's
  data on a failed read. Deferred to a decision that can tell those cases apart.
- **Defer the whole sensor contract until the grant model exists.** Rejected: the
  grant model is a next-wave decision of its own, and blocking a read-only local
  file behind it would stall leg 6 on a question that a single-user machine with
  an operator-set path does not yet pose. §7 makes the debt explicit instead.
