# 185. Every attempt to read a source is recorded, refusals included, and the trail's bound has no unlimited spelling

- Status: Proposed
- Date: 2026-08-23
- **Decides `core/protocols.py` and `core/types.py` surface — a breaking change
  (golden rule 5).** Two new Protocols with their two triads, one new frozen model,
  one new `StrEnum`, one new error class and one new `Settings` figure. It adds no
  member to `SourceGrants`, `SourceGrantStore`, `AuditTrail`, `Reader` or
  `AssistantEngine`, and changes no field of `SourceGrant` or `PermissionDecision`.
  ADR-0015 §5 puts it in its own PR, ratified before anything implements against
  it; the triads and their primary producer are a separate lane (ADR-0137 §2).
- **Required review set: adversarial *and* architecture.** Compelled, not declared:
  `CONTRIBUTING.md` → "Stop when the required reviews are green" makes a change
  contract-surface when it is "the ADR deciding that surface", and §2 and §4 below
  decide `core/types.py` and `core/protocols.py` respectively.
- **Discharges ADR-0139 §6.** That section fired ADR-0097 §12's read deferral into a
  lane and bound the lane with seven clauses. §1–§8 below answer each of them: the
  new Protocol and its triads (§4), the record's content bar (§2), the growth bound
  refused at load (§6), the ruling on a refused read (§7), never-the-liveness-authority
  (§8), and the grant-management surface disqualified as consumer (§8's last clause).
- **Decides no user surface.** How the trail reaches a person — an engine operation,
  a CLI command, a browser view — is the surface ADR's, which is being written
  beside this one. This ADR decides the record and its store, which is what
  ADR-0139 §6 says the subject is: "the record is a store rather than a surface".
- **Refs:** #1017 (the lane this discharges), #1427 (`track:world`, milestone 24),
  #629 (which asked for this alongside the grant), ADR-0139 §6, ADR-0097 §12.
  **Filed by this lane:** none.

## Context

### What ADR-0139 §6 handed this lane, and what it forbade

ADR-0139 §6 fired ADR-0097 §12's deferral of "an audit record of each *read*" and
declined to build it in the same change, on the stated ground that "the record is a
store rather than a surface" and "one lane delivers one change". It then bound the
lane it created with seven marked clauses. Four are prohibitions — no source
content, entry, path or configured location on any record; never the liveness
authority; the grant-management surface is not the consumer; and ADR-0004 §7 stays
undischarged for source access until something actually records it. Three are
obligations to *decide* something: a new Protocol with its triad, a stated growth
bound refused at load, and an explicit ruling on whether a refused read is recorded,
which "may not [be settled] by silence".

This ADR is that lane. It is written against those seven clauses rather than around
them, and §13 records that discharging them amends none of them.

### The premise that decayed, read against the tree rather than remembered

ADR-0097 §12's deferral rested on one sentence: "the record of what a source said is
the beliefs it produced". `GrantScope` today has three members —

```python
class GrantScope(StrEnum):
    FACET = "facet"
    INGEST = "ingest"
    NOTIFY = "notify"
```

— and the sentence is true of exactly one of them. `FACET` produces a transient
facet that is never stored (ADR-0097 §2, ADR-0008 §4). `NOTIFY` (ADR-0133 §1)
concludes a `NotificationCandidate` **or concludes nothing**, and concluding nothing
is the ordinary outcome. Only `INGEST` leaves the residue, and only when
`MemoryPolicy` accepts what was proposed.

The gap is not an inference. Each of the three gates is written twice — once before
the read and once after it — and `context/sources.py` says in its own comment what
the second one costs:

```python
reading = await self._reader.read()
# The revocation that landed while the read ran wins: the reading is
# discarded whole, and nothing records that it happened.
if await self._grants.live(source=source, use=GrantScope.FACET) is None:
    return {}
```

*Nothing records that it happened.* That is the most security-relevant read the
system performs — a source read across a revocation the user had already made — and
it is the one that leaves the least behind.

The three gates are `_GrantedFacetSource.contribute` in `context/sources.py`,
`IngestionStage.ingest` in `orchestration/ingestion.py`, and
`UpcomingEventStage.notice` in `orchestration/upcoming.py`. Two readers exist,
`CalendarReader` and `EmailReader`, declaring the identities `"calendar"` and
`"email"`.

### The store that exists, and why it cannot be used

ADR-0097 §4 already ruled out the obvious reuse, and it ruled it out for a reason
that transfers to a read without a word changed:

> `PermissionDecision.tool` is a required `ToolDefinition`, embedded by value, and
> ADR-0021 §1 makes that the clause "everything else here rests on" … A grant has no
> declaration. Recording one would mean synthesising a `ToolDefinition` that
> describes no registrable tool — putting a fabricated record into the one store
> whose entire premise is that its records are not fabricated.

A read has no declaration either. `Reader`'s whole surface is `name` and `read()`;
it takes no arguments, declares no risk level, no reversibility and no disclosure,
and `SqliteAuditTrail`'s invariants compare `tool`, `parameters_digest`, `step_id`
and `execution_id`, none of which a read has. So the structure is borrowed and the
store is not shared — which is exactly what golden rule 5 and `CONTRIBUTING.md` →
"Adding a Protocol" turn into a new Protocol with its own triad.

### ADR-0004 §7's unbuilt half, and the sentence it is not

ADR-0004 §7 is one sentence with two halves: "Access to Tier 0/1 data and every
side-effecting tool call is gated by the `permissions/` layer **and recorded in an
audit trail**." ADR-0097 built the gate. Its §4 says of the grant store, correctly,
that it "answers 'are granting and revoking audited' by construction rather than by
adding a log" — and *granting* is not *access*. ADR-0102 §11 restates the same
narrower claim. ADR-0139 §6's third clause exists so that a later reader does not
conclude the charter is discharged because a neighbouring sentence was.

Nothing in this ADR widens ADR-0004 §7. What it does is build the half of it that
has never existed for this subject.

### The arithmetic that makes the bound the hard part, not the record

ADR-0139 §6 named the number this decision has to survive: "A calendar read on a
five-minute interval is on the order of a hundred thousand rows a year, for a
deployment with one source." The arithmetic is 12 reads an hour, 288 a day, 105,120
a year, for **one** `(source, use)` stream. Two readers and three uses admit six
such streams, and ADR-0097 §5 notes the worse case: a source that is configured but
revoked produces a *refusal* every interval, forever, with nobody to stop it but the
user.

Every other durable store in `Settings` carries a retention figure —
`notification_retention`, `trace_retention`, `episode_retention`,
`notification_queue_limit`. `SqliteAuditTrail` and `SqliteSourceGrantStore` carry
none, and they are the two that legitimately do not: a permission decision is minted
by a user act, and so is a grant. A read is minted by a timer. That difference is
what makes "append and see" — the shape ADR-0139 §6 forbids by name — the wrong
default here and the right one there.

### An honest statement of what this ADR is not allowed to settle

- **How the trail reaches the user.** The engine operation, the CLI door, the
  browser view and what any of them renders are the surface ADR's, written beside
  this one. This ADR adds no `AssistantEngine` member and describes no rendering.
- **The grant record's shape, its store, its liveness rule, and revocation's
  effect.** ADR-0097 decided all four; ADR-0139 built a surface over them; this ADR
  reads `SourceGrants.live` and touches nothing else of either.
- **Per-belief grant attribution.** ADR-0097 §12 defers it and §1 of that ADR
  explains what it would cost. §2 below records a read's grant on the *read's* own
  record, which is a different relation and does not close that deferral.
- **Authorised cloud egress in the audit trail** (#747) and **band precedence**
  (#663). Both are milestone 24's and neither is this lane's.
- **The projection cluster** (#1431, #746, #673), unchanged and not re-listed.
- **Gating or recording direct Tier 0 access.** ADR-0004 §7 covers Tier 0 too;
  ADR-0097 §12 leaves #74's model-provider-credential question open and this ADR
  does not reach it. §14 defers it with its condition.
- **`Reader`'s surface.** ADR-0093 §7's no-lifecycle-method ruling and §10's
  argument-free `read()` stand. §5 below is emphatic that the recorder never
  reaches a reader.

## Decision

We will record every **attempt** to read a source — completed, refused,
unanswerable, failed, discarded or unconfirmed alike — as one append-only row in a
new Tier 1 store of its own, written by the same driver that held the grant gate,
bounded by a `Settings` figure that has no unlimited spelling and is refused at
load, pruned only oldest-recorded-first, and never consulted by anything to decide
whether a source may be read.

### 1. The unit is a read **attempt**, and its six outcomes are total

> **Normative.** The unit of record is one **attempt** by a driver to read one
> source for one use: the act that begins when the driver asks `SourceGrants.live`
> and ends when the driver has taken one of the six outcomes below. A driver writes
> exactly one record per attempt it takes to an outcome, whether or not anything was
> opened, and never a second.

> **Normative.** Every attempt that reaches an outcome reaches exactly one of
> `ReadOutcome`'s six members: `COMPLETED`, `REFUSED`, `UNANSWERED`, `FAILED`,
> `DISCARDED`, `UNCONFIRMED`. The six are mutually exclusive and total over the
> outcomes ADR-0097 §5 and ADR-0093 §8 already rule for a gated read; no
> implementation invents a seventh and none records an attempt with no outcome.

> **Normative.** A **cancellation delivered from outside** ends an attempt without
> an outcome. It is delivered onward unchanged, is never converted into an outcome,
> and the driver starts no new recorder call on that path. This is
> `core/protocols.py`'s cancellation clause and ADR-0093 §8's carve-out applied to
> the recording seam.

> **Normative.** Whether a cancelled attempt left a row is **indeterminate where
> the cancellation landed inside a recorder call already in flight**, and no
> component may assume either way: ADR-0060's clause that "a cancelled write may or
> may not have committed. The caller may assume neither" binds this seam as it binds
> every other. Where the cancellation landed before any recorder call began, no row
> exists.

> **Normative.** No consumer reads the **absence** of a row as evidence that a read
> did not happen. The trail states what it holds, and §5 and the clause above name
> the paths on which a read can have run with no row; §6's horizon is a third. No
> surface may present a source with no rows as a source that was never read.

> **Normative.** Whether the source was opened is a **total function of `outcome`**
> and is not a field. `REFUSED` and `UNANSWERED` mean nothing was opened —
> "the source is not resolved, not opened and not parsed" (ADR-0097 §5). `FAILED`,
> `DISCARDED`, `UNCONFIRMED` and `COMPLETED` mean the read ran. No implementation
> records that fact a second time.

The six, each pinned to the ratified clause that creates it. Two are decided at the
gate before the read, and neither opens anything:

- **`REFUSED`** — the first `live()` answered `None`. Nothing was opened.
- **`UNANSWERED`** — the first `live()` raised `GrantError`, so the driver could not
  tell whether a grant existed and failed closed (ADR-0097 §5).

Four follow a read that actually ran:

- **`FAILED`** — the read raised, under ADR-0093 §8: "A read that cannot complete
  may not return what it managed to gather."
- **`DISCARDED`** — the read returned and the re-check answered `None`, so the
  reading was "discarded whole" (ADR-0097 §5).
- **`UNCONFIRMED`** — the read returned and the re-check raised `GrantError`, so the
  reading was discarded "exactly as a withdrawn grant is" (ADR-0097 §5).
- **`COMPLETED`** — the read returned and the re-check confirmed the grant, so the
  reading was handed to its use.

**`COMPLETED` is a fact about the read and its gate, and it deliberately claims
nothing about the use.** It says the reading was handed over; whether the use then
kept, rejected or failed on what it was handed is `MemoryPolicy`'s subject, or the
facet adapter's, and their own records answer it. Claiming more would be
unrecordable as well as untrue: §5 requires the row to be written **before** the use
runs, so an outcome defined by the use's success could not be known when the row is
written, and amending the row afterwards is the mutation §6 forbids.

**The two unanswerable outcomes are separated from their answered twins because
collapsing them would put a false claim in the trail.** "There was no live grant"
and "we could not find out whether there was one" are different facts about the
user's authorisation, and a store whose premise is that its records are not
fabricated may not spell the second as the first. ADR-0097 §5 requires exactly this
distinction to survive elsewhere in its own words — "A store fault and a withdrawn
grant are different facts and an operator must be able to tell them apart" — and a
trail that conflated them would take back at the record what that clause holds at
the error.

**Six members rather than four is the cost of that, and it is the right cost.** The
alternative considered was four, with `DISCARDED` covering both post-read cases on
the strength of ADR-0097 §5's "discarded exactly as a withdrawn grant is". That
sentence is about what the driver *does* — and it is why `UNCONFIRMED`'s `produced`
and `grant` invariants are `DISCARDED`'s exactly — but the sentence immediately after
it is the one about telling the two apart, and the trail is where telling them apart
is now possible for the first time.

**`DISCARDED` and `UNCONFIRMED` are the rows this ADR most exists for.** ADR-0097
§5a states the residual it cannot close — "a read already in flight completes" — and
accepts it because "nothing is stored, nothing reaches a prompt, nothing leaves the
device". What it could not say was that the read left any trace. Now it does, and
the residual moves from invisible to recorded.

### 2. The record: seven fields, two construction invariants, and no content

> **Normative.** `core/types.py` gains one frozen model, `SourceReadRecord`, with
> exactly the fields §12 enumerates, and one `StrEnum`, `ReadOutcome`, with exactly
> the six members §1 names. `ReadOutcome` is **not ordered**, for `GrantScope`'s
> reason (ADR-0097 §10): six outcomes of a read are not ranked, and an order would
> invite a comparison that means nothing.

> **Normative.** A `SourceReadRecord` carries **no source content, no entry, no
> path and no configured location**, and no string derived from any of them
> (ADR-0004 §5, ADR-0093 §8). Its `source` is the reader's declared identity and
> nothing else — the value `Reader.name` returns, which ADR-0093 §7 requires to be
> declared rather than configured and Tier 2, and which ADR-0097 §1 already keys a
> grant on.

> **Normative.** What a read produced is recorded as a **count and never as a
> thing**: `produced` is the number of items the **reading** carried — its
> proposals, and its facet where it carried one — and no field names, identifies or
> describes any of them. It is a property of what the source returned and states
> nothing about what the use did with it.

> **Normative.** `grant` names the `SourceGrant.id` of the live grant the attempt
> ran under, and is `None` exactly when no grant was found at the first check — that
> is, on `REFUSED` and `UNANSWERED` and on no other outcome. Construction refuses a
> record breaching that correspondence.

> **Normative.** `produced` is zero on `REFUSED`, `UNANSWERED` and `FAILED`, and
> construction refuses a record breaching that: no reading exists in any of the
> three. `COMPLETED`, `DISCARDED` and `UNCONFIRMED` may carry any count from zero
> up. A `COMPLETED` zero means the read succeeded and the source had nothing —
> ADR-0093 §8's rule that an empty reading "is a **successful** reading", carried
> onto the record.

**The `grant` pointer is the consumer ADR-0097 §10 wrote `live` for.** That section
chose to return the record rather than a boolean "so a caller can name what
authorised the read instead of merely knowing that something did", and until now
nothing named it. The driver already holds the `SourceGrant` from the check it just
made, so the pointer costs no second query and no new seam.

**It does not close ADR-0097 §12's per-belief attribution, and saying so matters.**
That deferral is about pinning a *stored belief* to the grant its read ran under,
and it needs a field on `Attestation` that ADR-0092 §10 declined. A read record
carries no belief ids (§14 defers those with their trigger), so belief → grant is
still only resolvable through ADR-0097 §1's belief → source → that source's grant
history. What this ADR adds is read → grant, which is a relation that did not exist.

**A non-zero `produced` on a `DISCARDED` or `UNCONFIRMED` row is the point, not an
oversight.** "This read across your revocation carried fourteen proposals that were
dropped" is a materially different audit fact from "it carried none", and both are
known at the moment the row is written. Zeroing them to keep the invariant tidy
would throw away the most informative thing those rows have to say.

**Two invariants rather than prose**, and they are checked at construction for
`SourceGrant`'s reason: a record corrupted past its own model would be stored and
then make every later read of the trail incoherent. Together with §1's opened-ness
clause they let a reader of the trail place a row without trusting the writer's
discipline — `grant is None` partitions {`REFUSED`, `UNANSWERED`} from the rest, and
`produced > 0` is available only to the three outcomes in which a reading exists.

**No `finished_at` and no duration.** One instant is what makes an attempt
reconstructible against a grant history; how long a read took is a performance fact
with no consumer today, and ADR-0045 §1 and ADR-0028 §7 rule that a field with no
consumer is surface. §14 defers it.

### 3. Origin on the read side is the source, and no boolean is minted

> **Normative.** The origin fact a read record carries is its `source`: the declared
> identity of the party this system obtained the content from. No `SourceReadRecord`
> field states, computes or implies an externality claim about what the read
> returned, and no implementation derives one from a read record.

**Milestone 24's exit says "origin included", and this is what discharges it on the
read side.** ADR-0181 §1 rules that origin "is decided by **recorded origin** and
never by inspecting text". A source read is the moment at which content from outside
this system enters it, and the read record is where that entry is recorded — so the
read side's origin is not computed from anything; it *is* the row, and `source`
names the author.

**A boolean would be surface with no consumer, and worse, a redundant spelling.** On
the egress side ADR-0181 §2 needs `planned_with_external_content` because the
material there was assembled from many places and externality is a property of the
assembly. On the read side there is nothing to compute: ADR-0183 rules that "the
adversary writes the source and a reader derives no standing from what it reads", so
a field asserting *this content is external* would be `True` on every row ever
written. ADR-0106 §2's second-spelling failure is exactly that, and ADR-0181 §1
declined to mint an origin type for the same reason — the tree carries
`rests_on_recorded_external_content` and one boolean on a binding, and no
`ContentOrigin` exists anywhere.

### 4. Two Protocols beside the grant pair, implemented in `permissions/`

> **Normative.** `SourceReadRecorder` and `SourceReadTrail` are Protocols in
> `core/protocols.py`, both `@runtime_checkable` as every Protocol in that file is.
> Implementations live in `permissions/`. `SourceGrants`, `SourceGrantStore`,
> `ActionPolicy`, `AuditTrail` and `Reader` are **untouched** by this ADR: no member
> is added to any of them, no parameter widened, no semantics changed.

> **Normative.** The seam splits by capability. `SourceReadRecorder` **writes** and
> can answer nothing; `SourceReadTrail` records and reads. Anything that drives a
> reader holds only `SourceReadRecorder`, and nothing but the hub's read-trail
> operations holds a `SourceReadTrail`.

> **Normative.** **Both** Protocols ship a full triad — Protocol, shared conformance
> suite, and canonical fake in `ai_assistant.testing` — in the change that adds them
> (`CONTRIBUTING.md` → "Adding a Protocol"). Neither is an internal seam of
> `permissions/`.

**The split is ADR-0097 §3's move, and here it buys a different guarantee.** There it
removed `record` from the driver's type so a scheduler job could not mint its own
authorisation. Here the driver *must* write, so the capability removed is the other
one — the ability to **read** the trail — and what that forecloses is the cursor
ADR-0093 §5 forbids by name:

> A sensor's bound is a function of the clock, its configuration and the source's
> own content, and of nothing else. It may not be derived from durable state
> recording what previous runs read.

A read trail is precisely durable state recording what previous runs read. A driver
handed a queryable one is a driver that can ask "when did I last read this, and what
did it produce" and skip, back off, or resume — which is the cursor ADR-0093 §5
removed, arriving through a store built for another purpose. Removing `recent` and
`export` from the type the driver names makes that a `mypy --strict` failure instead
of a review note, which is ADR-0097 §3's own standard: "It holds no store handle, and
that is the scope limit rather than a rule about it … Here it is a type."

**It is a static guarantee and is stated as one**, exactly as ADR-0097 §3 states its
own: structural typing means the concrete store satisfies both, so a composition root
passes one object to a driver and to the hub's operations alike; what the driver
cannot do is *name* `recent`.

**The split costs two triads, and that is named rather than discovered.** Two suites,
two fakes, two binding classes. The `SourceReadRecorder` half is one member, and §12
binds its suite to **both** fakes, which turns part of the cost into evidence that
the store really does satisfy the narrow seam — the arrangement
`tests/permissions/source_grant_contract.py` already uses for the grant pair.

**Why `permissions/` and not `readers/` or a new subsystem.** ADR-0004 §7 charters
this subsystem for both halves in one sentence, and ADR-0097 §3 already answered this
question in this system's words: "A source grant is not a new responsibility; it is
the half the package was chartered with, arriving." The recording half is the same
sentence's other clause. `readers/` is disqualified by construction: a `Reader`
"holds no store handle, no writer, no policy and no engine".

**The names are deliberately *not* close, which is the opposite of ADR-0097 §10's
choice and is right for the opposite reason.** There the pair was named alike because
the narrow seam is the safe one and the widening had to be visible at a constructor.
Here the wide seam is the dangerous one — handing a driver a `SourceReadTrail` is
handing it ADR-0093 §5's forbidden cursor — so the two names should not be
substitutable at a glance.

### 5. The driver records it, on the seam that gated it, before it uses what it read

> **Normative.** The record is written by the **driver** — `context`'s reader adapter
> for `FACET`, `orchestration`'s ingestion stage for `INGEST`, and `orchestration`'s
> upcoming-event producer for `NOTIFY`. A `Reader` neither holds a recorder nor
> learns of one, and `Reader`'s surface is unchanged (ADR-0093 §1, §7, §10).

> **Normative.** Every site that drives a reader takes a `SourceReadRecorder` as a
> **required constructor argument with no default**. A composition that omits it does
> not type-check, on ADR-0097 §5's pattern for the gate itself.

> **Normative.** No `await` on the recorder may stand between the `live()` answer a
> driver gates on and its call to `Reader.read()`. ADR-0097 §5's clause that "the
> check and the start of the read are one synchronous step" is unchanged, and the
> record for any attempt whose read ran is written after `read()` has returned or
> raised and after the re-check has ruled.

> **Normative.** A driver records the attempt **before** it uses what the read
> returned. Where the recorder raises, the driver discards the reading: nothing is
> proposed, no facet is contributed, no candidate is concluded, and the
> `ReadTrailError` is reported to the driver's own failure posture (ADR-0008 §4 on
> the facet side, ADR-0083 §7 on the scheduled side).

> **Normative.** That path leaves the attempt **unrecorded**, and no clause of this
> ADR claims otherwise: §1's obligation is on the driver to write one row per
> attempt, not a guarantee that a row exists for every read that ever ran. What is
> guaranteed instead is the consequence — **nothing durable, nothing in a prompt and
> nothing in a notification comes of a read the trail does not hold.**

#### 5a. Two paths on which a read can run unrecorded, and what they are not

Naming them together, in one place, so no reader has to assemble them and no lane can
cite one as licence:

1. **The recorder raised** (§5). The read ran; the row was attempted and refused.
2. **A cancellation landed after the read began** (§1). Where it landed inside a
   recorder call already in flight, whether the row exists is indeterminate under
   ADR-0060; where it landed earlier, no row exists.

> **Normative.** Neither path is an **exception** to ADR-0004 §7. This ADR amends,
> narrows and supersedes nothing of that section: its requirement that access to
> Tier 0/1 data be recorded in an audit trail stands at exactly the width it has
> always had, and the two paths above are places the mechanism does not reach rather
> than places the obligation does not apply.

> **Normative.** No lane, ADR or implementation cites this ADR as authority to leave
> a source access unrecorded, and none cites either path as a precedent for skipping
> a record it could have written. Closing either needs a mechanism, not a permission.

**Why that is the honest classification and not a dodge.** ADR-0004 §7 states an
obligation on the design, and no store in this tree makes an obligation of that kind
unconditional under fault. `AuditTrail.record` raises too, and
`orchestration/runner.py` answers it the same way this ADR answers its own — the act
does not proceed, the `AuditError` propagates — and ADR-0021 declared no supersession
of §7 for it. Every partial supersession ADR-0004's Status line actually records
against §7 — ADR-0124's, ADR-0126's, ADR-0172's — is of its **gating** clause, and
each is a whole act or context in which the gate structurally *cannot* run.
ADR-0126 §11 makes the distinction in its own title: "ADR-0004 §7's gate cannot reach
this act, so it is superseded for it rather than left engaged and unmet." Here the
recording half **does** reach the act, on every path but two faults. §7 is engaged and
met, and where the mechanism fails it is engaged and unmet — which is a defect to
close, not a decision to record on ADR-0004.

**Fail-closed is what keeps the unmet case from also being an undetected one.** The
charter conditions *access* on a record of it, and a system that keeps what it read
when it could not record the reading has kept Tier 1 data outside the trail its
charter puts it in. Discarding is the act the corpus already reaches for in the
neighbouring case: ADR-0097 §5's re-check discards a reading whose grant has gone, and
ADR-0097 §5a accepts the residual — bytes read into a worker's memory and dropped —
as small "in exactly the way this subject makes it small".

**Why path 1 cannot be closed here.** A read whose record could not be written still
*happened*: the file was opened on the worker ADR-0093 §7 gives the reader, and no
clause here can un-read it. Nor can the failure record itself — the only durable place
a recorder fault could be written is the recorder that just failed, which §14 defers
with the condition that would fire a second, independent sink. So the guarantee
available is over the *effects* of the read rather than the existence of its row,
which is the same shape of honesty ADR-0097 §5a takes about its own in-flight case. An
operator still learns of it through the driver's failure posture — a logged fault
under ADR-0083 §7 for a scheduled read, an absent facet under ADR-0008 §4 — which is a
signal rather than a record and is not offered as one.

**Recording the row *before* the read, which would close path 1 completely, is not
available.** It would put an `await` between the `live()` answer and `Reader.read()`,
and ADR-0097 §5 forbids exactly that: "the check and the start of the read are one
synchronous step". Moving it before `live()` instead buys a two-row protocol with a
correlation id, doubles the store for the refusals that never open anything, and is
weighed in Alternatives considered.

**Ordering matters and is fixed in one direction only.** The record is written after
the re-check because a single row must carry the outcome, and the outcome is not
known before. Writing a row first and amending it after would be the mutation §6
forbids, in the store whose value is that it is not mutated.

**Why path 2 is stated three ways rather than one.** A cancellation can land in three
places, and only two of them are the same. Before `read()` is called nothing was
opened, so there is no access to record and ADR-0004 §7 does not reach it. During
`read()` the source may have been opened by the worker ADR-0093 §7 abandons, and no
row is written: the driver starts no recorder call on the way out. Inside a recorder
call already in flight the row **may or may not exist**, because ADR-0060 rules that
"a cancelled write may or may not have committed. The caller may assume neither, and
in particular may not assume the write did not land" — so the trail may hold a
perfectly good row for an attempt whose driver never learned it landed, and nothing
may treat that row as spurious or the absence of one as proof.

**Why the driver does not start a fresh recorder call on the way out.** ADR-0060's
preamble does permit a bounded deferral to make resources safe, so a shielded write
is not forbidden outright — it is refused on the grounds ADR-0093 §8 and ADR-0083 §4
give. A cancellation in this system is a shutdown or an abandoned assembly rather than
an event about the source, and ADR-0093 §8 spells out the harm of treating it as one:
both consumers would treat "a caller's own cancellation as a degraded source, on a
shutdown (ADR-0083 §4) that was working correctly". Adding an await to the teardown
path to record a non-event is the trade ADR-0083 §4 designed against, and the read a
deadline abandons is *not* in this class anyway — `calendar_read_timeout` raises
`ReaderError` rather than cancelling, which is a `FAILED` row like any other. Refused
in Alternatives considered.

### 6. The bound: a row cap with no unlimited spelling, pruned oldest-first

> **Normative.** `Settings` gains one figure, `source_read_trail_max_rows`, an
> integer with a named default, strictly positive, **refused at load** where it is
> out of range (ADR-0093 §5, ADR-0077 §1). It has **no spelling for "unlimited"** —
> no sentinel, no `none`, no zero, no negative — so no deployment can configure the
> unbounded Tier 1 store ADR-0097 §12 objected to.

> **Normative.** The store holds at most `source_read_trail_max_rows` records. When
> an append would exceed the cap, the store deletes the **earliest-recorded** rows
> until it does not, atomically with the append.

> **Normative.** The only deletions the store performs are that prune and `clear()`.
> No record is ever updated. No record is deleted individually, and no prune may be
> conditioned on a record's `source`, `use`, `outcome`, `grant` or `produced`.

> **Normative.** "Earliest-recorded" is the order of `record` calls, and never
> `started_at`. `recent` returns records in reverse order of recording. No
> implementation derives either order by comparing `started_at` values.

**The cap is a row count rather than a duration, and that is the whole point.** Every
other retention figure in `Settings` is a duration, and each governs a store whose
inflow is bounded by something else — a user act, a conversation, a measurement
window. This store's inflow is a timer, so a duration bound leaves its size a
function of read cadence, which is the exact quantity ADR-0139 §6's arithmetic is
about. A row cap bounds the store no matter how fast the timer runs, and §14 defers a
duration beside it with the condition that would fire one.

**Having no "unlimited" spelling is what discharges ADR-0139 §6's clause, and the
absence is the mechanism.** `notification_queue_limit` already carries the property
in its own description — "Positive, with no unlimited spelling" — and it is the
right precedent: `trace_retention` and `notification_retention` both accept `'none'`,
and a figure this store accepted `'none'` for would be "append and see" with a
config key. Refusing at load rather than at the first prune is ADR-0077 §1's rule,
quoted by ADR-0093 §5: "A setting the store read would refuse must fail at load, not
at the first observation."

**Evicting the oldest rather than dropping the newest is the opposite of
`notification_queue_limit`'s choice, and the two stores are opposite cases.** A
notification queue holds candidates that have not happened yet, so dropping the
newest loses the least. An audit trail holds acts that already happened, and a store
that refused new rows when full would make its own fullness gate the system's
behaviour: under §5's fail-closed rule the assistant would stop reading sources
altogether, silently and permanently, because a log filled up. An audit record must
never gate the act it records beyond the recording itself.

**Pruning does not tear a page out of the book, and the distinction is exact.**
ADR-0021 §4's rule — taken over whole by ADR-0097 §4 — is that "the user may burn the
book, and nobody may tear out a page", and its force is against *selective* removal:
a store from which a chosen record can be removed is one in which a source can have
been read under an authorisation nobody can find. A uniform, content-blind,
oldest-first horizon removes nothing anybody chose. It is also ADR-0004 §6's own
provision, which requires "retention rules (e.g. TTLs, size caps) so data does not
accumulate indefinitely" — a sentence written about exactly this hazard.

**Ordering by recording rather than by `started_at` is where the first
implementation would go wrong, and ADR-0097 §4 supplies the reason in reverse.**
That section deliberately refused a timestamp invariant because `decided_at` is
caller-supplied and the store reads no clock, so "a host clock corrected backwards
… makes every truthfully-timestamped revocation refusable"; it then refused a
monotonic sequence on the ground that "no decision here rests on order". Here a
decision *does* rest on order — the prune — so the same premises reach the opposite
conclusion. A prune keyed on `started_at` after a backwards clock correction deletes
the rows it just wrote, and the trail loses precisely the recent history it exists
for. Recording order is available without new state: ADR-0083 §10 makes the hub "the
only process that opens the … databases", so the sequence of `record` calls is
well-defined, and it is the store's own rather than a field on the `core` model.

**The figures, named here rather than left to the lane** (ADR-0093 §5's rule that
"the figures … are therefore named in §7a rather than left to its lane"): the default
is **200,000 rows**, and the admissible range is every strictly positive integer
below `2**63`, matching `notification_queue_limit`'s form. At ADR-0139 §6's
five-minute figure, 200,000 rows is about 1.9 years of one `(source, use)` stream, or
about 7 months if four such streams ran at that cadence — long enough that a
revocation made last year is still answerable, and bounded whatever happens. **The
size that follows is an illustration and obligates nothing:** a row of seven small
scalars stored as a validated JSON dump, as `SqliteAuditTrail` stores a decision,
runs to a couple of hundred bytes, so the steady state is tens of megabytes rather
than the unbounded growth ADR-0097 §12 refused.

**The prune runs inside `record` and adds no scheduler job.** ADR-0083 §7's loop
gains nothing, no new lifecycle step exists, and there is no window in which the
store is over its cap. A sweep job was the alternative and is refused in Alternatives
considered.

### 7. A refused read is recorded, and it is the row the trail exists for

> **Normative.** A read refused for want of a live grant is recorded, as a `REFUSED`
> record; a read not attempted because the grant could not be answered is recorded,
> as an `UNANSWERED` one. Neither is omitted, sampled, rate-limited, folded or
> suppressed, on any ground including volume.

ADR-0139 §6 required this question to be answered rather than settled by silence, and
noted that the lane "may answer or may decline". It is answered yes, on four grounds.

**It is the only positive answer to the question the user actually asks.** ADR-0139
§6: "'was this source read after I revoked it' has no answer today", because the only
trace is ADR-0097 §8's operator log line, which "is not durable state and is not
exportable". A trail of successes alone answers it only by *absence*, and an absence
in this store is ambiguous by construction: no row could mean not read, or could mean
the record failed, or the horizon pruned it, or the driver was never wired. A
`REFUSED` row is a statement.

**It is the row the security question is about.** A revoked-but-configured source is
ADR-0097 §5's named case, and the interesting fact about it is not that nothing was
read — it is that something kept trying, on a schedule, after the user said no.

**Recording only the interesting reads is not an audit trail.** A store with a
selection policy answers "what happened" with "what we decided to keep", and every
consumer then has to know the policy to read the rows. That is the same defect
ADR-0097 §4 refuses when it forbids a store whose records could differ from what
happened.

**The cost is real, is the largest volume driver here, and is bounded rather than
argued away.** A revoked five-minute source contributes 105,120 `REFUSED` rows a
year and, under §6's uniform prune, shortens the horizon for everything else. That is
accepted for two reasons. The condition is **self-disclosing**: a trail full of
`REFUSED` rows for one source says, in the trail itself, exactly what ADR-0097 §8's
log line was supposed to say and could not — and it says it to the user rather than
to an operator's terminal. And the remedy is the user's and is one act: grant the
source, or unconfigure it.

### 8. Never the liveness authority, never a cursor, and not the grant surface's column

> **Normative.** No read record is ever consulted to decide whether a source is
> granted, what a grant's scope is, or what a source's grant history is. No
> implementation derives liveness, scope or grant history from the read trail, and
> `SourceGrants.live` remains the only answer to whether a read may happen.

> **Normative.** No bound, no schedule, no cursor and no skip decision is derived
> from the read trail. ADR-0093 §5's clause — a sensor's bound "may not be derived
> from durable state recording what previous runs read" — binds this store by name.

> **Normative.** The grant-management surface does not report reads. This ADR adds
> no member to `SourceGrants` or `SourceGrantStore`, and no client presents a read,
> a read count or a last-read instant beside a standing grant. ADR-0139 §6's second
> clause is unchanged and is restated here so that this lane cannot be read as
> relaxing it.

**The direction of the pointer is one-way, and that is what keeps the clause from
being contradicted by §2.** A read record names the grant it ran under; nothing joins
back. A grant store cleared under `clear()`, or a grant whose record predates a
purge, leaves read records citing an id that no longer resolves — and that is
**legible history rather than corruption**, in ADR-0184's sense: the row says
truthfully what the read cited at the time, and the trail makes no claim that the
citation is still resolvable. No implementation may treat an unresolvable `grant` as
a defect, repair it, or drop the row.

**The first two clauses are held by the type as well as stated** (§4): a driver
holding only `SourceReadRecorder` cannot query the trail at all, so neither the
liveness derivation nor the cursor is reachable from the site that would want them.

**The third clause is ADR-0139 §6's own, and it is the reason this store has a
different consumer.** Reporting reads on the grant surface would answer "what has
been happening" where the surface's question is "what do I authorise", and it "would
also make the read record's consumer this surface, which is how an unbounded store
gets built to fill a column". The consumer here is the surface ADR's own, and §6's
bound holds whatever that surface asks for.

### 9. Residency, ownership, erasure and export

> **Normative.** The read trail is a **Tier 1 local store**. ADR-0155 §1's residency
> clause governs it, so no component places any part of it in a service another
> party operates; its file lives under `Settings.data_dir` and is created
> owner-only (ADR-0004 §4, ADR-0084 §9).

> **Normative.** The hub owns it exclusively, as it owns every other database in
> the data directory (ADR-0083 §1, §10), and no interface adapter opens it.

> **Normative.** `ai-assistant-purge` destroys it as part of destroying the data
> directory, with no per-store step and no new clause: ADR-0126 §1's act "carries
> no inclusion list and no exclusion list … and it opens no store to empty it". No
> lane adds one for this store.

A Tier 1 store "by ADR-0004 §7's own words", which is how `AuditTrail`'s own
docstring already classifies its sibling. Nothing here is novel; it is stated because
a new store that omitted to say it would be a store nobody had classified, and
ADR-0155 §1's second clause decides membership by *where this system persists a
value* rather than by what it contains — so the classification follows from the file
being under `data_dir` whether or not this ADR says so. Saying so makes it findable.

### 10. What "from the audit trail alone" means, and the narrowing this ADR declares

#1427's ruled exit for milestone 24 reads:

```text
every read of a source and every egress is reconstructible from the audit trail
alone, origin included
```

> **Normative.** For milestone 24, "the audit trail" is the **pair** of durable
> permission records: `AuditTrail`, which holds what the permission layer decided
> about acts on the world, and `SourceReadTrail`, which holds what this system
> read from it. The two partition the subject — a read is never a
> `PermissionDecision` and an egress is never a `SourceReadRecord` — and neither
> answers the other's half.

> **Normative.** "Reconstructible" means, for a read, that the trail alone yields
> the source's declared identity, the use, the instant the attempt started, its
> outcome, whether the source was opened (§1), the grant it ran under where there
> was one, and how many items the reading carried. It does **not** mean the content
> of the read, and no lane may report the milestone met on the strength of a trail
> that carries any. It also does not mean what the *use* did with what it was
> handed: that is memory's record and the notification store's, not this trail's.

**The second clause is a narrowing of the ruled text, and it is declared rather than
glossed** — the discipline ADR-0181 §8 used on milestone 23's arm (a). Read at full
strength, "reconstructible" would include what the source said, and ADR-0004 §5,
ADR-0093 §8 and ADR-0139 §6's fourth clause each forbid that outright. A trail that
satisfied the stronger reading would be a copy of the user's calendar in the
`permissions/` layer. What the mechanism provides is a complete account of *the
access* — which is also what ADR-0004 §7's sentence asks for, since it is about
access and not about content.

**A second narrowing, smaller, and also declared.** The horizon: §6 prunes, so the
trail reconstructs every read *it still holds*, and reads older than the configured
cap are gone. That is the cost of the bound ADR-0139 §6 requires, and there is no
arrangement that has both. `export()` therefore delivers the horizon rather than the
history, and ADR-0004 §6's export right is satisfied to that extent and no further.

**A third narrowing, and it is the one a lane must not read past.** §5a names two
paths on which a read can run with no row — a recorder that raised, and a
cancellation after the read began — and neither is a read the trail can be relied on
to reconstruct. What holds on both is the consequence rather than the record: nothing
came of them. So the exit's "every read" is measured in §11 over attempts the harness
drove **to an outcome with a recorder that answered**, which is what an arm can
actually assert, and §5a's paths are asserted for their own property instead (arm
(e)). Neither narrowing is an exception to ADR-0004 §7, which §5a rules on
normatively.

**Where "origin included" lands is §3 on the read side and ADR-0181 §2 with ADR-0184
§2 on the egress side**, and the two are different kinds of answer for the reason §3
gives. Nothing joins them: a read row and an egress row about the same content share
no key, and the exit test does not ask them to.

### 11. The pre-registered exit arms for milestone 24's read half

> **Normative.** The read half of milestone 24's exit is pre-registered as the five
> arms and the five figures below. No lane substitutes an arm, drops a figure, or
> reports the read half met on a run that did not produce all five figures.
> The egress half (#747) and band precedence (#663) are pre-registered by their own
> lanes and are not this ADR's.

> **Normative.** Each figure is measured over **its own arm's run and no other**,
> and each arm's run is stated with its denominator. No figure is computed across
> arms: arms (a) and (b) drive fewer attempts than `source_read_trail_max_rows` so
> that nothing is pruned under them, and arm (d) deliberately drives more, so a
> completeness figure taken over arm (d) would count the prune as a loss.

> **Normative.** **Arm (a) — completeness.** A run drives a known number of read
> attempts, fewer than the cap, across all three uses and both readers, including at
> least one of each of `ReadOutcome`'s six members, and reconstructs each one from
> `export()` alone with no other store consulted.

> **Normative.** **Arm (b) — the revocation question.** A run grants a source,
> drives reads, revokes it, and lets the driver run again; the trail alone must
> answer "was this source read after I revoked it", telling an attempt that was
> refused from one that completed, from one discarded at the re-check, and from one
> whose re-check could not be answered.

> **Normative.** **Arm (c) — no content.** The source is seeded with a distinctive
> marker string in its entries, its path and its configured location, and every
> field of every exported record is searched for it.

> **Normative.** **Arm (d) — the bound.** A run drives more attempts than
> `source_read_trail_max_rows` and asserts that the row count never exceeds the cap
> and that the survivors are the most recently recorded.

> **Normative.** **Arm (e) — the two attempts §5a names.** A run drives one attempt
> whose recorder raises, one cancelled while `read()` is outstanding, and one
> cancelled inside a recorder call already in flight. It asserts of each that
> nothing was proposed, no facet was contributed and no candidate was concluded, and
> of the two cancelled ones that the cancellation propagated unconverted. **It
> asserts nothing about whether a row exists** for the third: ADR-0060 makes that
> indeterminate, and an arm that pinned it either way would pin what the contract
> refuses to promise. None of the three is counted against arm (a)'s completeness
> figure.

> **Normative.** The five figures, each reported with its denominator:
> **unrecorded-read count** — over arm (a)'s run, attempts driven minus records
> exported; **misattributed outcome count** — over arm (a)'s and arm (b)'s runs,
> records whose outcome does not match the attempt the harness drove;
> **content-leak count** — over arm (c)'s run, records containing any byte of the
> marker; **overflow count** — over arm (d)'s run, rows held beyond the cap; and
> **leaked-product count** — over arm (e)'s run, proposals, facets or candidates
> that reached a consumer from an unrecorded attempt. All five are **zero by
> construction** under §1, §2, §5 and §6 and are measured rather than asserted.

> **Normative.** A non-zero figure on any of the five is a **breach of a ratified
> clause** and not a threshold to tune. The lane reports it, opens the issue, and
> does not close the milestone on it.

> **Normative.** The suite is **deterministic, offline and in the ordinary gate**,
> against `ai_assistant.testing`'s fakes and a seeded reader. No live arm is
> registered: nothing in the read half depends on a model's behaviour, so ADR-0181
> §8's capped live run has no counterpart here and no lane invents one.

**Arm (c) is the one that would otherwise be held by review.** ADR-0139 §6's content
prohibition is the kind of clause a diff satisfies and a later field quietly breaks —
a failure class stringified into a record, a path arriving inside an exception
message, exactly the mistake ADR-0093 §8 documents at length. A marker search over
every exported field fails on it mechanically.

**Arm (a)'s six-member requirement is deliberate.** `UNANSWERED`, `DISCARDED` and
`UNCONFIRMED` are the three outcomes no ordinary run produces, and they are the three
this ADR adds the most value by recording; an exit test that never drove them would
leave them unexercised in the state that matters. Driving them needs a grant seam
that can be made to answer `None` and to raise on demand, which
`ai_assistant.testing`'s `FakeSourceGrants` is for.

**Arm (e) exists because the honest answer to "is every read recorded" is "on every
path but the two §5a names, and here is what holds on those".** §5's guarantee is over
the *effects* of an unrecorded read, and an exit test that only counted rows would
never touch it — leaving the one clause that carries the fail-closed property
unexercised while the milestone closed on four green figures.

### 12. The contract surface owed, and what the implementing lane owes

**New surface in `core` — a breaking change (golden rule 5):**

- **`core/types.py`** gains **two** types:
  - **`ReadOutcome`**, a `StrEnum` with exactly the six members §1 names. A
    `StrEnum` for `GrantScope`'s reason — a stable, serialisable, user-facing
    vocabulary — and not ordered.
  - **`SourceReadRecord`**, a frozen pydantic model (ADR-0068) because it crosses a
    subsystem boundary (`CLAUDE.md`). Seven fields:
    - `id: DurableIdentifier` — the record's own id, minted by the caller, as
      `PermissionDecision.id` and `SourceGrant.id` are (ADR-0021 §3: a store neither
      mints ids nor reads a clock).
    - `source: Identifier` — the reader's declared identity (§2), matching
      `SourceGrant.source` and `Attestation.reported_by`, so a blank source is
      refused by the type.
    - `use: GrantScope` — which of the three uses the attempt was for.
    - `started_at: UtcInstant` — the instant the attempt started, which is the
      instant the first grant check ruled: ADR-0097 §5 makes the check and the start
      of the read one synchronous step, so one instant is truthful for both.
      Timezone-aware and refused naive.
    - `outcome: ReadOutcome` — §1's ruling, one of six.
    - `grant: DurableIdentifier | None` — required with no default; the
      `SourceGrant.id` the attempt ran under, `None` exactly on `REFUSED` and
      `UNANSWERED` (§2).
    - `produced: int` — required with no default, at least zero, the number of items
      the reading carried, and zero on `REFUSED`, `UNANSWERED` and `FAILED` (§2).

  > **Normative.** `grant` and `produced` are **required with no default**, so a
  > caller states both rather than inheriting a value it did not mean. Any field a
  > later ADR adds to this model is optional with a default, on ADR-0008 §1's
  > additive pattern — a required addition would make every stored row fail
  > validation, which is the failure ADR-0184 records and repairs.

- **`core/protocols.py`** gains **two** Protocols, both `@runtime_checkable`.
  - **`SourceReadRecorder`** — the write seam, one member:
    - `async record(read: SourceReadRecord) -> str` — append and return the id.
      Write-once, atomic over the duplicate check, the append and §6's prune, for
      ADR-0021 §4's reason: without atomicity the single-write guarantee is a race.
  - **`SourceReadTrail`** — the durable store, four members: `record` with exactly
    the semantics above, plus
    - `async recent(*, limit: int = 50) -> list[SourceReadRecord]` — newest-recorded
      first, `limit` strictly positive and refused otherwise. Bounded because every
      read of a Tier 1 store in this corpus is (ADR-0021 §4, ADR-0073 §2).
    - `async export() -> list[SourceReadRecord]` — every record the store holds, in
      recording order. ADR-0004 §6's export right, and `AuditTrail.export`'s shape,
      delivering the horizon §10 describes.
    - `async clear() -> int` — wholesale erasure only, for ADR-0021 §4's reason.

  **No `get(id)`, no `delete(id)`, no query by source and no count.** A selective
  delete is the page torn out of the book. A `get` has no consumer: nothing looks a
  read up by id. A per-source query and a count are the surface ADR's to ask for if
  it needs them, and adding them here would be surface with no consumer
  (ADR-0045 §1, ADR-0028 §7); both are additive later.

  Illustrative signatures, in ADR-0073 §1's and ADR-0093 §10's form — the semantics
  above are the contract, the spelling is the lane's:

  ```python
  @runtime_checkable
  class SourceReadRecorder(Protocol):
      async def record(self, read: SourceReadRecord) -> str: ...


  @runtime_checkable
  class SourceReadTrail(Protocol):
      async def record(self, read: SourceReadRecord) -> str: ...

      async def recent(self, *, limit: int = 50) -> list[SourceReadRecord]: ...

      async def export(self) -> list[SourceReadRecord]: ...

      async def clear(self) -> int: ...
  ```

  `SourceReadTrail` does not inherit `SourceReadRecorder` and does not need to:
  every Protocol in this file is satisfied structurally, so one `permissions/` class
  implementing all four members satisfies both seams, exactly as
  `SqliteSourceGrantStore` satisfies `SourceGrants` and `SourceGrantStore` at once.

- **`core/errors.py`** gains **one** class:
  - `ReadTrailError(AssistantError)` — the read trail could not be written or read,
    including a refused duplicate id. **One class rather than two**, unlike
    `AuditTrail`'s split and unlike `GrantError`/`InvalidGrantError`, because under
    §5's fail-closed rule the driver's recourse is identical however the write
    failed: discard the reading. A caller that could tell a broken store from a
    duplicate id would do nothing different with the answer. §14 defers the split
    with the condition that would fire it.

- **`core/config.py`** gains **one** field:
  - `source_read_trail_max_rows: int` — default `200_000`, `gt=0`, `lt=2**63`, with
    no sentinel and no unlimited spelling (§6).

> **Normative.** The implementing lane ships both triads and the store in one change
> with its primary producer, under ADR-0137 §2's contract-seam exception; it wires
> the recorder into all three drivers, since a driver wired for one use and not
> another would leave §1's completeness claim false for a use nobody noticed.

> **Normative.** The lane's conformance suite binds the `SourceReadRecorder`
> contract to **both** fakes and to the concrete store, so the store's satisfaction
> of the narrow seam is evidence rather than assertion — the arrangement
> `tests/permissions/test_fake_source_grants.py` already uses for the grant pair.

> **Normative.** The store's file is a new database under `Settings.data_dir`, and
> the lane updates every count of the databases in that directory that it touches.
> ADR-0123's Context records that "the count in the most authoritative document
> about the data directory is already wrong by two, and nothing detected it"; a
> lane adding the eighth may not add to that.

### 13. This ADR classified under ADR-0070 §1 and ADR-0082 §1

**This ADR amends no clause of any earlier ADR, and supersedes none.** It is a
**stacked addition** in ADR-0082 §1's sense: "Adding an obligation that contradicts
no sentence the earlier ADR wrote … is recorded in the ADR that makes it, and nowhere
else." The four candidates, each tested by ADR-0070 §1's question — would a reader
holding only the earlier ADR now act differently, or read one of its clauses more
widely?

- **ADR-0139 §6.** Its seven clauses are obligations *on this lane*, and discharging
  an obligation is not amending it. Every sentence of §6 stays true after this ADR:
  the record is still owed of this lane rather than of that surface, the grant
  surface still does not report reads, and §6's third clause — that ADR-0004 §7 "is
  **not** discharged for source access by ADR-0097 §4's grant store" — remains true
  forever, because it is scoped to that store. No record is owed on ADR-0139.
- **ADR-0097 §12.** Its read bullet says a per-read row "would be an unbounded Tier 1
  store with no reader", which was an accurate statement about the tree of its day
  and is not a rule anyone obeys. ADR-0139 §6 already recorded the firing where a
  reader of ADR-0097 will find it. §6 of this ADR answers the unboundedness and the
  surface ADR answers the reader, so nothing of §12 is contradicted. Its *other*
  deferrals — per-belief grant attribution above all — are untouched (§2). No record
  is owed on ADR-0097.
- **ADR-0004 §7.** This ADR builds the recording half for one subject. §7's sentence
  is unchanged, and a reader of it acts identically: access is gated and recorded.
  What changes is that for source access the second half now has an implementation to
  point at. No record is owed.

  **This was put to the ADR-0070 §1 test directly, because §5a names two paths on
  which a read can run with no row, and a reviewer read that as a scoped exception.**
  It is not one, on three grounds, and §5a's clause states the conclusion normatively
  so that no later lane has to re-derive it. *First*, nothing in this ADR permits an
  implementation to skip a record: a reader holding only ADR-0004 §7 would build gate
  plus record, which is exactly what §5 requires, and would read no clause of §7 more
  narrowly afterwards. *Second*, an obligation that a mechanism can fail to meet
  under fault is not thereby narrowed — `AuditTrail.record` raises too, and
  `orchestration/runner.py` answers with the same posture §5 takes here while
  ADR-0021 declared no supersession of §7 for it. Holding otherwise would make every
  audit obligation in the corpus retroactively superseded by its own error class.
  *Third*, the shape the corpus actually uses for a genuine exception is visibly
  different: every partial supersession ADR-0004's Status line records against §7 —
  ADR-0124's, ADR-0126's, ADR-0172's — is of its **gating** clause, and each names a
  whole act or context in which the gate structurally cannot run. ADR-0126 §11 states
  the discriminator in its own title: the gate "cannot reach this act, so it is
  superseded for it rather than left engaged and unmet". §7's recording half reaches
  this act. Where the mechanism fails, §7 is engaged and unmet, which is a defect
  ADR-0004 keeps the standing to name.
- **ADR-0093 §5.** §8 above restates its no-cursor clause about a store ADR-0093 did
  not know of. Restating an obligation over a new subject adds one; it does not widen
  the original, which is about a sensor's bound and stays exactly that. No record is
  owed.

**Under ADR-0089 §1 this ADR is marked**, and the marks are the whole of its
obligations: unmarked text here is read to determine what a marked clause means and
supplies no obligation of its own (ADR-0089 §3).

### 14. Deferred, by name, each with the condition that fires it

- **The failure class on a `FAILED` record.** `PermissionError` and
  `FileNotFoundError` are Tier 2 facts (ADR-0093 §8) and would be recordable, but the
  trail's subject is access rather than diagnosis and nothing asks. Fires with the
  first surface that reports *why* a read failed; it is one optional field under
  ADR-0008 §1's additive pattern.
- **A duration or a `finished_at`.** Fires with the first consumer that needs to know
  how long a read took — a budget, a health measure, a timeout tuning surface — none
  of which exists.
- **What a read produced, beyond a count** — the ids of the proposals an `INGEST`
  read delivered. Fires with the first surface asking "which beliefs came from this
  read", which is the neighbour of ADR-0097 §12's per-belief grant attribution and
  should be decided with it rather than before it.
- **Splitting `ReadTrailError`.** Fires when a caller's recourse differs by cause —
  the first consumer that retries one class and not the other. Additive later.
- **A durable record that the recorder itself failed**, which §5 states plainly is
  unavailable: the only durable place to write it is the store that just refused the
  write. Fires with a second, independent durable sink whose whole purpose is
  recording that the first was unreachable — a decision with a cost and a consumer
  neither of which exists, and not one to reach for by adding a table to the store it
  is supposed to be independent of.
- **Recording a cancelled attempt** (§5a's path 2). Fires with a mechanism for
  durable recording that costs the teardown path nothing — nothing in this tree has
  one, and ADR-0083 §4's shutdown design is why a shielded write is not it.
- **A retention duration beside the row cap.** Fires when a deployment needs an *age*
  bound rather than a *size* one — the likeliest being a legal or policy retention
  ceiling, which is a different obligation from ADR-0097 §12's.
- **A read record for something that is not a `Reader`** — a spoke reporting across
  the process boundary (ADR-0094). Fires when such a producer exists; §2 keys on a
  reader's declared identity, and whether a spoke's identity is the same kind of
  thing is that lane's question, exactly as ADR-0097 §12 defers the grant half of it.
- **Recording access to Tier 0**, which ADR-0004 §7's sentence also covers. Fires
  with #74's ruling on whether a credential is a permission subject at all; this
  store's subject is a `Reader`, and nothing here reaches a keyring.
- **Aggregation** — counts, last-read instants, per-source rollups. The surface ADR's
  to ask for, and §8's third clause forbids the one place they are most tempting.
- **Everything ADR-0097 §12 and ADR-0139 §10 defer other than the read record**,
  unchanged and not re-listed.

## Consequences

**Easier.** "Was this source read after I revoked it" acquires an answer, and it is
durable and exportable rather than a log line nobody kept. ADR-0004 §7's recording
half acquires a mechanism for source access for the first time — met on every path
but the two §5a names, and neither of those is an exception to it. ADR-0097 §5a's
in-flight residual
stops being invisible: a `DISCARDED` row says it happened. `SourceGrants.live`'s
record-returning shape acquires the consumer ADR-0097 §10 wrote it for. And milestone
24's read half becomes measurable by five figures that are zero by construction.

**Harder.** Three drivers gain a required constructor argument and a fail-closed
path, so a composition that forgets one stops type-checking rather than silently
recording nothing — the intended direction, and still a change to three call sites.
The data directory gains an eighth database, with the counting hazard ADR-0123
recorded. Two triads is two conformance suites and two fakes for four members total,
which is the cost §4 pays for holding the no-cursor rule in the type system. And the
trail has a horizon: a deployment that reads on a short interval will lose old rows,
which is the bound ADR-0139 §6 required and not an accident.

**What would trigger revisiting this.** A source whose *read itself* has an effect —
a fetch that marks messages seen, a source that bills per read — makes the residual
in §5 and in ADR-0097 §5a stop being "bytes read and dropped", and ADR-0097 §12
already routes that case to its own decision. A second deployment shape — multi-user,
or a hub reading dozens of sources — would put the row cap under pressure that
`200_000` was not chosen for. And a surface that wants per-source history at scale
would want an index and a query this store declines to offer.

## Alternatives considered

**Record reads in the existing `AuditTrail`.** Refused for ADR-0097 §4's reason
applied to a read: `PermissionDecision.tool` is a required `ToolDefinition`, a read
has no declaration, and synthesising one puts a fabricated record into the one store
whose premise is that its records are not fabricated. ADR-0139 §6 already ruled it
out by name, and it is listed here because it is the first thing a reader will
propose.

**Fold consecutive identical attempts into a run with a count.** This is the shape
ADR-0139 §6 hints at — "a record that is not per-read at all" — and it is genuinely
attractive: it would collapse a revoked source's 105,120 yearly refusals into a
handful of rows and keep an exact count forever. It is refused because it requires
**mutation**: each new attempt updates the open run's count and last instant, in a
store whose entire value (ADR-0021 §4, ADR-0097 §4) is that its records are never
updated. Appending a fresh run row per attempt instead buys nothing and is the
per-read store again. A fold also makes reconstructibility content-dependent — you
would know 412 reads happened between 09:00 and 17:00 and not whether one happened at
14:32 — which is a worse loss than §6's uniform horizon, and it is the loss that
lands on exactly the question §7 exists to answer.

**Record only the reads that produced something.** Refused in §7: a store with a
selection policy answers "what happened" with "what we kept", and the reads worth
recording are precisely the ones that produced nothing.

**Four outcomes rather than six, with `DISCARDED` covering both post-read cases and
`UNANSWERED` covering both unanswerable ones.** Refused in §1. The four-member form
is what ADR-0097 §5's "discarded exactly as a withdrawn grant is" suggests, and it is
wrong on that section's very next sentence: "A store fault and a withdrawn grant are
different facts and an operator must be able to tell them apart." Folding
`UNANSWERED` into `REFUSED` is worse still — it would put the claim *there was no
live grant* into a store whose premise is that its records are not fabricated.

**A boolean `opened` field beside the outcome.** Refused in §1: it is a total
function of `outcome`, so it would be the second spelling of a fact already recorded
(ADR-0106 §2), and a stored derivation is one that can disagree with what it derives
from.

**Define `produced` as what the *use* consumed rather than what the reading
carried.** Refused in §2. It is not knowable when §5 requires the row to be written,
it differs per use in a way no single integer expresses, and it would make the trail
a partial account of memory's decisions rather than a complete account of the read.

**Declare a partial supersession of ADR-0004 §7 for the two paths §5a names.**
Refused in §5a and argued in §13. It would be the wrong record on ADR-0070 §1's test
— nothing in §7 is read more narrowly afterwards — and it would set a precedent that
an obligation is superseded wherever its mechanism has an error path, which is every
audit obligation in this corpus including ADR-0021's own. The three supersessions
ADR-0004's Status line actually records against §7 are of its *gating* clause and
each names a context the gate cannot structurally reach; §5a's paths are faults in a
mechanism that does reach.

**Write the row before the read, so no access can precede its record.** Refused in
§5a: an `await` there is what ADR-0097 §5 forbids between the `live()` answer and
`Reader.read()`. Moving the pre-row ahead of `live()` avoids that clause and costs a
two-row protocol with a correlation id, a second write on the hot path, a doubled
store — the 105,120 yearly refusals that open nothing would each cost two rows — and
a new class of half-recorded attempt whose outcome row never arrived. It buys a
narrower version of the same residual rather than none.

**Shield the recorder write across an external cancellation.** Refused in §5a.
ADR-0060's preamble permits a bounded deferral, so this is available rather than
forbidden; it is declined because a cancellation here is a shutdown or an abandoned
assembly rather than an event about the source (ADR-0093 §8), and adding an await to
ADR-0083 §4's teardown path to record a non-event is the trade that design was made
against. The read a *deadline* abandons is not in this class: it raises `ReaderError`
and lands as a `FAILED` row.

**Bound the store with a duration instead of a row count.** Refused in §6: this
store's inflow is a timer, so a duration leaves its size a function of read cadence,
which is the quantity ADR-0139 §6's arithmetic is about. Deferred as an addition in
§14 rather than refused forever.

**Refuse new rows when the cap is reached**, as `notification_queue_limit` does.
Refused in §6: combined with §5's fail-closed rule it would make a full log stop the
assistant reading sources at all, which is an audit record gating the act it records.

**Prune with a scheduler sweep, as `trace_retention` does.** Refused in §6: a sweep
adds a job to ADR-0083 §7's loop, a `Settings` interval, and a window in which the
store is over its cap — for a prune that is three statements inside the transaction
that appends.

**Give the driver the whole `SourceReadTrail` and hold the no-cursor rule by
review.** Refused in §4: a queryable read trail in a driver's hand is ADR-0093 §5's
forbidden cursor, reachable in three lines, and `tests/core/test_protocol_triad.py`'s
own docstring names this class of gap — "an invariant held by prose rather than
mechanism".

**Put an externality boolean on the record**, mirroring
`EgressBinding.planned_with_external_content`. Refused in §3: it would be `True` on
every row ever written, which is ADR-0106 §2's second-spelling failure and ADR-0045
§1's surface with no consumer at once.

**Have the `Reader` write its own record**, which would put the write next to the
act. Refused: `Reader` "holds no store handle, no writer, no policy and no engine",
takes no arguments, and "is never its own caller" (ADR-0093 §1, §10). It also could
not record a `REFUSED` attempt, because in that case no reader is reached at all.
