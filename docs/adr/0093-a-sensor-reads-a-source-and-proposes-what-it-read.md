# 93. A sensor reads a source and proposes what it read; the clock bounds the read, so nothing needs a cursor

- Status: Proposed
- Date: 2026-08-02
- **Decides a `core` contract and implements none of it.** Golden rule 5 and
  ADR-0015 §5 put a contract ADR in its own PR, merged before anything implements
  against it. The Protocol, its shared conformance suite and its canonical fake in
  `ai_assistant.testing` ship together as one later lane (`CONTRIBUTING.md` →
  "Adding a Protocol"). **Because this ADR decides a Protocol and a `core` type,
  its required review set is adversarial *and* architecture**, even though the PR
  carrying it is prose only — the reading ADR-0090 §5 and ADR-0091's header each
  recorded in the opposite direction, for ADRs that decided no surface. It is a
  substantive contract ADR, so it is **reviewed while `Proposed` and ratified
  only after** (`CONTRIBUTING.md` → "Contract ADRs land before their
  implementation"), which is what leaves a finding able to change the decision.
- **Depends on ADR-0092, and says so as a gate rather than as a note.** ADR-0073 §4
  makes carrying the reporting source's identity and its report time a
  precondition of leg 6's first `EXTERNAL` producer shipping. That vehicle is
  ADR-0092's to decide, together with imported-record identity and whether a user
  assertion may override an attested belief. §9 states what this seam needs from
  it and what it refuses to assume in the meantime. **ADR-0092 is the other half
  of the same dispatched wave and merges ahead of this one**, so for as long as
  this ADR is `Proposed` its number is a gap in the issued set rather than a
  dangling reference — which ADR-0090 §1 rules is "neither failed nor reported".
  This ADR is deliberately not written so as to be readable without it: §9's two
  gates are the point, and collapsing them into a guess here is exactly what
  ADR-0073 §4 forbade when it said the decision is "for that lane — with a
  producer in hand — not one to guess here".
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
> A `Sensor` is not itself a `ContextSource`.

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

> **Normative.** Re-reading is safe only if re-proposing is idempotent at the
> gate. A sensor may not be enabled on a schedule until ADR-0092's imported-record
> identity makes a re-proposed entry fold rather than duplicate.

This is the sensor's version of ADR-0077 §8's "re-observation is safe by
construction", and the difference is that the observer's safety came free from the
gate folding a repeat into a `REINFORCE`, while a sensor's turns on what identity
an imported record carries — which is ADR-0092's, not this ADR's. §9 states it as
a gate.

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

> **Normative.** A sensor's identity is **declared by the sensor** and is not a
> configurable value. It is a stable Tier 2 name, never derived from the source's
> location or contents; a path, filename, address or account identifier may not be
> used as one. The calendar sensor's identity is `"calendar"`.

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
figures are named. Six fields, and the reason each exists rather than only its
value — because the *dimensions* are the decision and the numbers are revisable:

| Field | Default | Range | What it bounds |
| --- | --- | --- | --- |
| `calendar_sensor_path` | `None` | absolute path | the source; `None` is disabled |
| `calendar_sensor_interval` | `None` | `> 0` | the cadence; `None` is disabled (§7) |
| `calendar_window_past` | 1 day | `>= 0` | how far back the clock-relative window reaches |
| `calendar_window_future` | 7 days | `> 0` | how far forward it reaches |
| `calendar_max_entries` | 500 | `[1, 2**63)` | entries in the window, and so proposals |
| `calendar_max_bytes` | 8 MiB | `> 0` | the source read **before** parsing |

**The sensor's identity is deliberately not in that table.** It is declared, not
configured, for the reason given above this subsection: a free-text setting is how
a path or an address would reach `Provenance` and the logs.

Four of the six are decisions rather than figures pulled from the air:

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
- **`calendar_max_bytes` is separate from `calendar_max_entries`, and it is the
  one that must exist.** An entry cap can only be applied *after* parsing, so a
  cap on entries alone lets a 2 GiB `.ics` file be fully parsed before anything
  refuses it — the bound applied one step too late to bound the work. The byte cap
  is checked against the source before parsing begins. This is the same ordering
  ADR-0017 §3 requires of a credential read ("otherwise an implementation reads
  it, then checks, then stops"), applied to a parse.
- **Both caps refuse rather than truncate** (§5), so exceeding either raises under
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

> **Normative.** An entry whose times are floating or date-only is localised in the
> configured `Settings.timezone`, the same value ADR-0008 §5 gives the temporal
> context. A sensor may not invent a second timezone source.

Two components resolving "today" against different zones is the class of defect
ADR-0026 exists to prevent, arriving through data rather than through a clock.

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
ones, and a source whose in-window occurrences are entirely uninterpretable and
over the cap.

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

There is deliberately **no new error class** (§10). A sensor's failures are its
source's — a missing file, a permission denial, a malformed document — and the
seam's contract is that they surface rather than that they are re-typed. Both
consumers catch by the rule above, not by the class.

### 9. The dependency on ADR-0092, stated as a gate

ADR-0073 §4 puts a precondition on this wave in as many words: "The gate is on leg
6's first `EXTERNAL` producer: carrying **both** the reporting source's identity
and its report time is a precondition of it shipping, and whether that needs
`Provenance` to grow fields is a `core` decision for that lane — with a producer
in hand — not one to guess here."

> **Normative.** This ADR does not discharge ADR-0073 §4's gate and does not
> decide the vehicle. `SensorReading` is where the source's identity, our read
> instant, and any reading-wide as-of the source declares enter the system (§3,
> §10); how any of them reaches a stored belief — and where a *per-entry* report
> time lives — is ADR-0092's.

> **Normative.** No sensor may be enabled on a schedule until ADR-0092 has decided
> imported-record identity. Until then §5's idempotence premise is unestablished,
> and a periodic re-read is a duplicate generator rather than a refresh.

The two are separate gates on purpose. The first is about what a stored belief can
honestly say; the second is about what happens when the same entry is proposed
twice. A lane could discharge one and believe it had discharged both.

> **Normative.** This ADR decides nothing about whether a user assertion may
> override an attested belief. Where a sensor's re-read would restore a value the
> user corrected, the governing rule is ADR-0092's, and this seam conforms to
> whatever it ratifies.

ADR-0038 §2a's exclusion of `EXTERNAL` from supersession is mechanical — it turns
on an external record's id being "the integrating system's idempotency key" — and
this wave is the first time it has a live case. That makes it ADR-0092's to move,
and it makes pre-empting it here particularly cheap-looking and particularly
wrong: the mechanism and the identity decision are the same decision.

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

  > **Normative.** Per-proposal report time is **not** decided here and is not
  > foreclosed here. Where a source's report time is per-entry, it belongs on the
  > proposal, by the vehicle ADR-0092 ratifies (§9), and a sensor sets it when
  > constructing the proposal.

  This is the boundary between the two lanes taken seriously rather than
  approximately. An earlier draft made `as_of` required at the reading level, which
  would have decided the *granularity* of ADR-0073 §4's report time — reading-wide
  — inside the seam ADR, leaving the lane that owns that gate unable to recover a
  per-entry time this contract never carried. Deciding a neighbouring lane's
  question by choosing a field's cardinality is the quietest way to decide it.
  - `proposals: tuple[MemoryUpdateProposal, ...]` — possibly empty, which under §8
    means the source had nothing to propose within the bound and is a successful
    answer. A failed read raises and constructs no reading at all.
  - the **facet field, absent for now**, landing as an optional field under §3.

  `UtcInstant` and `EncodableText` are the existing `core` aliases; no new
  primitive is owed. `MemoryUpdateProposal` already exists, which is why the cost
  is one type rather than a family.
- **Nothing else.** No new error class: a sensor's failures are its source's — a
  missing file, a permission denial, a malformed document — and §8 rules that they
  surface rather than that they are re-typed at the seam. No change to
  `MemoryWriter.ingest`, whose semantics §1 relies on exactly as ratified.
  `Provenance` is **not** touched here — that is ADR-0092's (§9).

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
   - Input observation (ADR-0065) and cancellation (ADR-0060), as every seam owes.
3. **The canonical fake in `ai_assistant.testing`**, scriptable to return a
   reading with proposals, an empty reading, and a *raising* read — the three
   states §8 distinguishes, so a consumer can test its own degradation path. That
   third capability is the gap ADR-0022 §Consequences filed against
   `FakeMemoryStore` as #105, not repeated here.

**Four rulings above are deliberately *not* suite clauses, and putting them there
would be the error.** The test is whether a clause is decidable from `name` and
one `read()` return value, which is the whole of what a conforming `Sensor` is:

- **§5's bound refused at construction.** `Sensor` specifies no constructor and no
  configuration surface — `read()` takes no arguments precisely so a caller cannot
  widen the bound (§10) — so a generic suite has nothing to over-supply. This is
  where the shape differs from ADR-0077 §9, whose equivalent clause was testable
  only because `observe` *takes* the batch whose size the bound governs. It is a
  concrete sensor's test and a `Settings` test, and stating that here is what stops
  an implementation-specific rule from wearing the Protocol's authority.
- **§8's raise on an incomplete read.** A suite cannot make an arbitrary
  implementation's source fail. The canonical fake is scriptable to raise so
  *consumers* are testable; the obligation itself is the concrete sensor's.
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
- **What a context facet carries** — an as-of instant and provenance. §3 is
  additive precisely so this ADR does not decide it. Fires with the facet.
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
- **A source registry.** §7 revisits at the third source.
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

ADR-0073 §4's gate is *bound to* rather than discharged (§9); ADR-0038 §2a is
untouched and belongs to ADR-0092; ADR-0017 §1 and §3 are examined in Context and
found not to engage.

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
