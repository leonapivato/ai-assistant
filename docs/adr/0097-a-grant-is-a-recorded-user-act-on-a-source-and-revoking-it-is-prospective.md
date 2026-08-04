# 97. A grant is a recorded user act on a source; revoking it stops the reading and does not unwrite the beliefs

- Status: Proposed
- Date: 2026-08-03
- **Decides `core` contract surface and implements none of it.** It adds **two**
  Protocols to `core/protocols.py` (`SourceGrants`, `SourceGrantStore` — split by
  capability, §3), two types to `core/types.py` (`GrantScope`, `SourceGrant`), and
  three classes to `core/errors.py` (§10). Golden rule 5 and ADR-0015 §5 put a
  contract ADR in its own PR, merged before anything implements against it, so
  **no code changes with it** — the two triads (Protocol, shared conformance suite,
  canonical fake in `ai_assistant.testing`, each), the `permissions/`
  implementation, the two caller-side gates and the client surface are later lanes
  (§10).
- **Required review set: adversarial *and* architecture**, even though the PR
  carrying it is prose only. It decides `core/protocols.py` and `core/types.py`
  surface, which is the ground ADR-0093, ADR-0094, ADR-0095 and ADR-0096 each took
  the same set for, and which `CONTRIBUTING.md` → "Stop when the required reviews
  are green" states directly: a change is contract-surface "when it is the ADR
  deciding that surface". It is **reviewed while `Proposed` and ratified only
  after**, in a separate lane (`CONTRIBUTING.md` → "Contract ADRs land before
  their implementation"; #633 records why the flip cannot ride in this PR).
- **Discharges ADR-0093 §11's first deferral** — "a revocable permission-grant
  model", whose firing condition is "when a second source exists **or when leg 6's
  exit test is evaluated against its own wording**" — and ADR-0092 §10's "the
  grant surface … its own decision, next wave". It is filed as **#629**.
- **It takes up the *source* slice of ADR-0021 §3's deferral of "gating direct
  Tier 0/1 data access", in the shape that section itself named as presumptive,
  and answers nothing else it defers.** #74's model-provider-credential question
  is untouched, and ADR-0021 §6's **standing grants for actions** are untouched and
  unnarrowed — §7 rules that a source grant may never source a
  `PermissionRuling.authorised_by`, so ADR-0021 §3's named precondition on "the ADR
  that introduces standing grants" is not engaged by this one.
- **Amends no earlier ADR and supersedes none**, and §11 applies ADR-0070 §1's
  test and ADR-0082 §1's record rule clause by clause — including to the four
  places where the opposite reading is available: ADR-0093 §7a's enablement
  matrix, ADR-0096 §4's absence rule, ADR-0021 §3's deferral, and ADR-0045 §4's
  window-closing mechanism.
- **Decided with both consumers in hand.** ADR-0093's `Reader`, `SourceReading`
  and `ReaderError`, the `readers/` package with a working `CalendarReader`,
  `orchestration`'s `IngestionStage` and `Engine` ingestion operation, and all nine
  of ADR-0093 §7a's `Settings` figures are on `main`; ADR-0096 has decided the
  facet and lifted §7a's reserved facet-only state. So the two things a grant has
  to gate both exist as ratified surfaces, and neither is guessed at here.

## Context

### The promise, and what the tree actually does

`VISION.md` states the property as a fact about the system:

> Reading the world and acting on it are governed separately. A **reader** — a
> read-only source the user has connected, feeding situational context and
> observation — is granted, scoped, and revocable, but it changes nothing outside
> the assistant.

`docs/roadmap.md` turns it into leg 6's exit test — "the assistant knows something
true about the user's day it was never told, **from a source the user granted**" —
and then says in the same paragraph that the second half "rests on a surface
nothing offers yet".

It does not. On `main` today a calendar is read because an operator set
`Settings.calendar_reader_path`: `_build_calendar_reader` in
`app/composition.py` returns a `CalendarReader` exactly when that field is not
`None`, `Engine`'s ingestion operation raises `ConfigurationError` when it is, and
the scheduler arms the job exactly when `calendar_reader_interval` is set. Nothing
between the configuration and the file records that the user agreed to any of it.

Measured against the three words, none of them holds:

| | `VISION.md` promises | `main` does |
| --- | --- | --- |
| Granted | the user connects the source | an operator sets a `Settings` field |
| Scoped | the grant bounds what may be read | the bound is a config figure, not a grant |
| Revocable | the user withdraws it | edit the config and restart |

### Why the gap is stated rather than discovered

ADR-0093 §7 ruled the honest thing rather than letting the configuration pass for
consent:

> **Normative.** Configuration is not a grant, and no surface may present it as
> one. A `Settings` field cannot be revoked by the user through the assistant,
> cannot be scoped, and leaves no audit record.

The clause is quoted into `core/config.py` beside `calendar_reader_path`, which
carries the same sentence and cites #629. §11 then deferred "a revocable
permission-grant model" with the reason — "`ActionPolicy` governs actions, not
sources" — and the firing condition this ADR meets. ADR-0092 §10 records the same
hole from the memory side, and ADR-0096 §4 refuses to let `CurrentContext` leak
the enablement state precisely because "that is a grant conversation conducted by a
field nobody designed … while #629 records that the grant surface does not exist".

So the debt has been written down four times and paid none. What has changed is
that the two things a grant would gate now both exist: the ingestion path is built,
and ADR-0096 decided the facet and lifted ADR-0093 §7a's reserved facet-only state.
A grant surface decided today has real consumers on both sides rather than one
consumer and a plan.

### What the corpus already fixes, and this ADR may not re-decide

Three ratified rulings bound the shape of the answer before it is argued, and each
closes off an option that would otherwise look reasonable:

- **A reader's identity is declared, stable and Tier 2** (ADR-0093 §7): "never
  derived from the source's location or contents; a path, filename, address or
  account identifier may not be used as one". ADR-0092 §3 adds that the same value,
  as `Attestation.reported_by`, "identifies the connected source *instance*, not
  the vendor" and "must be **stable across syncs**". That is a key with exactly the
  properties a grant needs, and it is already on every belief a reader writes.
- **A reader holds no policy** (ADR-0093 §1): it "takes no store handle, no
  writer, no policy and no engine". A reader therefore cannot check its own grant,
  and any design in which it does is already forbidden.
- **A reader never proposes an absence** (ADR-0093 §4), because "a bounded read, a
  truncated file, a permission error and a genuinely deleted entry are
  **indistinguishable from the reading**". §6 below is where a revocation is
  distinguished from that case rather than folded into it.

### The one place the neighbouring decisions do not reach

`ActionPolicy` is the obvious home and it is the wrong one, for a reason its own
ADR states. ADR-0021 §3 made `decide` "a genuine function of its argument" — no
clock, no id, no store — and says in terms that this purity "is in turn what makes
§5's monotonicity obligations checkable at all". A standing authorisation is the
opposite kind of thing, and ADR-0021 §6 already says so: "always allow this tool"
needs "durable, per-user policy state with its own data-rights obligations — **a
store, not a field**". §3 also, unprompted, names the shape a second permission
subject should take: "**widening `decide`'s parameter is breaking; adding a second
Protocol beside `ActionPolicy` is additive** … A separate Protocol takes nothing
away from anyone and is therefore the presumptive shape, and it is named as such
rather than left to be discovered."

### An honest statement of what this ADR is not allowed to settle

- **Standing grants for *actions*** (ADR-0021 §6). A different subject, and §7
  rules that this contract may not be used as one.
- **#74's question** — whether ADR-0004 §7's Tier 0 gating reaches a model
  provider credential. A credential is not a connected source and nothing here
  touches it.
- **What a `MemoryStore` read keyed on `reported_by` looks like.** §6 declines to
  need one; §12 defers it with the neighbour ADR-0092 §10 already filed as #631.
- **The `AssistantEngine` method signatures and their wire frames.** §9 rules
  where the grant is made and what may not make one; ADR-0084 §5's split between
  "that the surface promotes" and "what the surface is" is followed rather than
  collapsed.

## Decision

We will add a grant contract in `core` — a `SourceGrantStore` that keeps an
append-only record of the user's decisions about which sources may be read and for
what, and a query-only `SourceGrants` that whoever drives a reader checks against —
revocable by a second record that stops the reading and changes nothing already
written.

### 1. A grant is a recorded user act naming one source instance and what it authorises

> **Normative.** A grant's subject is a **reader's declared identity** — the value
> `Reader.name` returns, which `SourceReading.source` equals (ADR-0093 §10) and
> which reaches a stored belief as `Attestation.reported_by` (ADR-0092 §1). A grant
> keys on nothing else: not a path, not a `Settings` field name, not a class, and
> not a vendor.

> **Normative.** A grant authorises **reading that source and proposing what it
> read**, and nothing else. It authorises no tool call, no transmission, no
> write the user did not already permit through the memory write path, and nothing
> outside the assistant.

> **Normative.** A grant is created **only** by an explicit user act through a
> client (§9). No model, plan, tool, reader, scheduler job, `Settings` value,
> migration or upgrade may create one.

**The key is chosen because the join to the belief already exists — and the join
is to the source's history, not to one grant.** A belief produced by a reader
carries `reported_by` equal to that reader's declared identity, so "which
*source's* authorisations produced this belief?" is answered by a value already on
the record, and the store's history for that value is the complete list of what
the user granted and withdrew. Keying the grant on anything else would mean a
*new* field on `Provenance` or `Attestation` to carry the pointer — a
`core/types.py` change to a ratified surface, at the moment ADR-0092 §10 has just
declined to add a third field to that value object for exactly the reason
ADR-0045 §1 and ADR-0028 §7 give.

> **Normative.** No belief carries the id of the grant that authorised the read
> that produced it, and nothing in this ADR adds a field to `Provenance` or
> `Attestation`. The resolvable relation is **belief → source → that source's
> grant history**, and no surface may present it as belief → one grant.

**The residual is real and is stated rather than glossed, because the stronger
claim is the one a reader would assume.** A source may be granted, revoked and
granted again, and every belief from either era carries the same `reported_by`.
Nothing then distinguishes which of the two grants authorised which belief:
`Attestation.reported_at` is "the source's clock" and not ours (ADR-0092 §3), and
`Provenance.last_updated` is transaction time that a later `REINFORCE` moves
(ADR-0045 §3), so neither brackets a grant era reliably. **What is guaranteed is
therefore exactly this:** every read that ever happened was authorised at the time
it happened (§5), and the store says, completely and in order, what the user
granted and withdrew for that source. **What is not guaranteed** is a per-belief
attribution to one grant record.

**Closing it would cost the field this section just declined**, and there is no
consumer for it yet: the question "which grant authorised this belief" has no
surface that asks it, while the question "what have I granted, and what did I
withdraw" is answered by `recent` and `export` (§10). §12 defers the per-belief
attribution with the condition that fires it, rather than buying a field on a
ratified `core` type for a question nobody is asking.

**And the two properties the key needs are already obligations.** ADR-0092 §3
requires `reported_by` to be stable across syncs "because §6 leaves it as the only
durable handle the record keeps on where it came from"; a grant keyed on an
unstable value would silently stop covering the source it was made about.
ADR-0093 §7 requires the identity to be declared rather than configured and to be
Tier 2, which is what keeps a grant record — which is rendered to the user, kept
forever, and exported — from carrying a home directory or an account name. Neither
property is added here; both are inherited, and this section is where they acquire
a second consumer.

**A path could not have been the key even if it were convenient.** ADR-0093 §7's
clause forbids it in the identity, and the reason transfers verbatim: the grant
store is a durable Tier 1 record that survives into `export`, so a path used as the
key would put the same data in the same class of place the identity rule exists to
keep it out of. **And that is enforced where it can be rather than asserted here:**
`Identifier` refuses only a blank string, so the type cannot tell a declared
identity from a home directory — §9 therefore admits a `source` only when it equals
the `name` of a `Reader` the hub actually holds, which makes the admissible set the
set of declared constants and leaves no free-text route in.

**The grant is not keyed to a user, and that is a property of this system rather
than an omission.** There is no user identity anywhere in the tree — ADR-0036 §3
records that the permission layer "records that a human answered, not which
human" (#113), and ADR-0004 reasons throughout about "a single-user local app".
Adding a subject field now would be surface with no consumer, and the day
multi-user arrives it is one optional field under ADR-0008 §1's additive pattern.
§12 defers it with that condition.

### 2. Scope is the **use**, and the corpus already fixes exactly two of them

> **Normative.** A grant names one or more **uses** from `GrantScope`, whose
> members are `FACET` — reading the source to contribute a `ContextFacet` at
> assembly time — and `INGEST` — reading the source to propose beliefs into
> memory. A use a grant does not name is not authorised by it.

> **Normative.** A grant's scope is non-empty. A grant naming no use is refused
> at construction, because it authorises nothing and would read as a grant.

**The axis is not invented; it is ADR-0093 §3's, promoted to something the user can
answer.** That section rules that a reading has "two legitimate consumers … at
their own cadence: the context facet reads at assembly time, and ingestion reads on
its schedule", and it is emphatic that neither may derive its answer from the
other. The two differ in the one way a user would care about: the facet is
transient, advisory and never stored (ADR-0008 §4, ADR-0096 §4), while ingestion
writes durable beliefs that outlive the turn and reach `export`. "You may look at
my calendar to answer what I am asking now, but do not remember it" is a coherent
sentence, it is one a person actually means, and it is the only scope distinction
the ratified surfaces can honour today.

**Both members have a live consumer**, which is what keeps this from being surface
with no consumer (ADR-0045 §1, ADR-0028 §7): `INGEST` gates
`orchestration/ingestion.py`'s stage and the `Engine` operation the scheduler job
calls, and `FACET` gates the `context/` adapter ADR-0096 §4 has just unblocked.
Neither is speculative and neither is a placeholder.

**Content-level scope — which entries, which fields, which calendar — is not
decided here**, and refusing it is the same discipline. Nothing today can express a
sub-source selector: ADR-0093 §7 configures exactly one source with no registry,
and ADR-0096 §6 gives the calendar facet three scalars and defers its entries.
A scope field enumerating entry kinds would be a schema with no reader on either
side of it. §12 defers it with the condition that fires it.

> **Normative.** A revocation revokes a grant **whole**. There is no partial
> revocation and no in-place narrowing; changing a grant's scope is a revocation
> followed by a new grant, and both records are kept.

**Two records rather than a mutation, for the reason §4 keeps the store
append-only.** A narrowing applied in place is a rewrite of a record the user made,
in a store whose entire value is that it says what the user actually decided. The
two-act form reaches the same end state, is legible at a glance — "revoked
`FACET`+`INGEST` on `calendar` at 14:02, granted `FACET` on `calendar` at 14:02" —
and needs no partial-revocation state for a reader of the store to reconstruct. The
cost is a moment in which nothing is granted, in which a scheduler tick would be
refused under §5; on a single-user local machine that is a log line, and §5's
refusal is designed to be one.

### 3. Where it lives: two Protocols beside `ActionPolicy`, implemented in `permissions/`

> **Normative.** `SourceGrants` and `SourceGrantStore` are Protocols in
> `core/protocols.py`. Implementations live in `permissions/`. `ActionPolicy`,
> `ActionRequest`, `PermissionRuling` and `PermissionDecision` are **untouched**
> by this ADR: no member is added, no parameter widened, no semantics changed.

> **Normative.** The seam splits by capability. `SourceGrants` **answers** about
> grants and can create none; `SourceGrantStore` records them. Anything that
> drives a reader holds only `SourceGrants` (§5), and nothing but the hub's grant
> surface (§9) holds a `SourceGrantStore`.

**The split is what makes §1's "only a user act creates a grant" a type rather
than a promise.** A driver handed the whole store is a scheduler job that can
mint its own authorisation: the ingestion stage runs on ADR-0083 §7's timer, and
a `record` on the object in its hand is a valid `SourceGrant` away from
authorising itself. Nothing about the record would look wrong afterwards. So the
capability is removed from the type the driver names, which is the move ADR-0077
§1 made for the same reason — "It holds no store handle, and that is the scope
limit rather than a rule about it … Here it is a type" — and ADR-0093 §1 repeated
for the reader.

**It is a static guarantee and is stated as one.** Structural typing means the
concrete store satisfies `SourceGrants`, so a composition root passes one object
to both; what the driver cannot do is *name* `record`, because `mypy --strict`
runs over `src` and `tests` and the attribute is not on the annotated type. That
is the same class of enforcement every boundary in this tree rests on, and
overstating it as a runtime capability removal would be the kind of claim §1's
own residual paragraph exists to avoid.

**This is ADR-0021 §3's presumptive shape, taken rather than re-derived.** That
section ruled the choice in advance — "widening `decide`'s parameter is breaking;
adding a second Protocol beside `ActionPolicy` is additive … the presumptive shape,
and it is named as such rather than left to be discovered" — and its reason applies
unchanged: `decide` names a concrete `ActionRequest`, so a union parameter breaks
every structural implementation under golden rule 5.

**Why not one generalised permission surface, which is the tempting move.** Three
independent grounds, each sufficient:

- **`ActionPolicy` is a pure function by ratified design, and a grant is a
  store.** ADR-0021 §3 removed the clock, the id and the trail from the policy
  deliberately, "which leaves `decide` a genuine function of its argument — which
  is in turn what makes §5's monotonicity obligations checkable at all", and
  `ThresholdActionPolicy` is written to that shape today. A surface that must read
  durable state to answer cannot be that function. ADR-0021 §6 reached the same
  conclusion about its own deferred feature in its own words: "a store, not a
  field".
- **The two subjects are governed separately by the document above both of
  them.** `VISION.md`: "Reading the world and acting on it are governed
  separately … Collapsing the two into one notion of 'integration' would either
  over-restrict reading or under-restrict acting." A single surface is that
  collapse, arriving through a type instead of through a name.
- **The obligations do not transfer.** ADR-0021 §5's floors — monotone in
  severity, off-device disclosure never auto-granted, `UNKNOWN` cost never
  auto-granted — are all statements about a `ToolDefinition`'s declared fields. A
  source has no `risk_level`, no `reversibility`, no `discloses` and no cost, so a
  merged contract would carry a conformance suite half of whose clauses are
  vacuous on half of its implementations. Two Protocols, two suites, and each
  clause binds something.

**Why `permissions/` and not a new subsystem.** ADR-0004 §7 charters this
subsystem for both halves in one sentence — "Access to Tier 0/1 data **and** every
side-effecting tool call is gated by the `permissions/` layer and recorded in an
audit trail" — and only the second has ever been built. ADR-0021 §3 says the same
from the other side when it defers the first. A source grant is not a new
responsibility; it is the half the package was chartered with, arriving.

> **Normative.** The contract's weight stays in `core`: **both** Protocols live in
> `core/protocols.py` and **each** ships a full triad — Protocol, shared
> conformance suite, and canonical fake in `ai_assistant.testing`. Neither is an
> internal seam of `permissions/`.

The argument is ADR-0095 §3's, and it is stated rather than assumed because the
shape is identical. Two subsystems hold `SourceGrants` by injection —
`orchestration`, whose ingestion stage checks it (§5), and `context/`, whose
adapter does — and neither may import `permissions`' concrete module under golden
rule 1. A `core` Protocol also cannot skip its triad:
`tests/core/test_protocol_triad.py` enforces it over every Protocol in
`core/protocols.py` with an empty `EXEMPTIONS` tuple, so "a `core` Protocol
shipping no triad" is a red gate rather than a decision an ADR can make.

**The split therefore costs two triads, and that is named rather than
discovered.** Two suites, two fakes and two binding classes, where one Protocol
would have cost one of each. The `SourceGrants` half is small — one member, one
behaviour — and §10 binds its suite to *both* fakes, which turns part of the cost
into evidence that the store really does satisfy the narrow seam. It is worth
paying because the alternative is §1's central clause held by review, which is the
gap `tests/core/test_protocol_triad.py`'s own docstring names as "an invariant held
by prose rather than mechanism".

### 4. The store is append-only, and a revocation is a record rather than a mutation

> **Normative.** A `SourceGrant` is a frozen record. A revocation is a **new
> record** whose `revokes` names the grant it revokes; no record is ever updated
> or individually deleted. Erasure is wholesale only.

> **Normative.** `record` stores a **detached, validated snapshot**, recursively
> over reachable state, and never retains the caller's object. Every query on
> **either** seam returns a detached snapshot likewise — including
> `SourceGrants.live`, which is the only member the narrow seam has and the one
> answer §5's gate rests on.

> **Normative.** At most one **live** grant exists per source at any instant. A
> grant recorded for a source that already has a live grant is refused; narrowing
> or widening is §2's revoke-then-grant.

> **Normative.** The store refuses a revocation whose named grant is absent, is
> itself a revocation, is already revoked, names a different `source`, or
> transcribes a different `scope`.

> **Normative.** Liveness is derived from the `revokes` relation alone. No
> implementation may decide whether a grant is live by comparing `decided_at`
> values, and **a revocation is never refused for its timestamp** — including one
> that predates the grant it revokes.

**The timestamp is deliberately not an invariant, and this is the one place this
ADR departs from `AuditTrail`'s shape on purpose.** `SqliteAuditTrail._check_resolution`
refuses a resolution "timestamped before the confirmation it answers", and an
earlier draft of this section copied that clause across. It is wrong here, and the
failure is the worst one available: `decided_at` is caller-supplied and the store
reads no clock (ADR-0021 §3's rule, which this contract keeps), so a host clock
corrected backwards after a grant was recorded makes every truthfully-timestamped
revocation of it refusable until wall-clock time catches up. A large enough
correction makes a grant **permanently unrevokable** — the one property
`VISION.md` names that this ADR exists to deliver, defeated by an invariant that
was protecting nothing.

**Protecting nothing, precisely.** In the audit trail the ordering check guards a
real claim: that an answer was given after the question was asked, which is what
makes a recorded consent evidence. Here the revocation is identified by `revokes`,
liveness is computed from that pointer, and nothing in this contract compares two
instants — so dropping the check removes a lockout and costs no property. What is
left is a record whose `recent` ordering can put a revocation beside or above the
grant it revokes when the clock moved, which is a display oddity a surface can
render honestly and never a wrong answer to "is this source granted".

**A monotonic sequence was considered and refused.** It would restore a total
order over records, and it would be new durable state and a new mechanism, added
to make a display ordering pretty in a case the tree has never hit. No decision
here rests on order; ADR-0021 §4 lives with wall-clock ordering for a store with
far more of it. If a consumer ever needs a total order it owes its own decision,
and §12 records the trigger.

**Detaching on the *write* path is the half that is easy to drop, and ADR-0021 §4
names the failure in one sentence: "Detachment on queries alone closes the door and
leaves the window open."** `frozen=True` refuses `grant.scope = ...` and does not
refuse `grant.__dict__["scope"] = ...`, so a store that kept the caller's object
would let a grant be rewritten *after* it was appended — through a store whose
entire premise (the clause above) is that its records are not rewritten. The
validating half matters for the same reason `_revalidated` exists on the audit
trail: a record corrupted past its own model — a naive `decided_at`, an emptied
`scope` — would be stored and then make every later read incoherent, and §10's
construction invariants would have been checked on an object nobody kept.

**This answers "are granting and revoking audited" by construction rather than by
adding a log.** The record *is* the audit record: a store in which the only writes
are appends, in which revocation is an append, and in which nothing may be edited
or selectively removed, cannot hold a history that differs from what happened.
ADR-0021 §4's argument is taken over whole — "the user may burn the book, and
nobody may tear out a page" — because a grant history with a removable page is
one in which a source can have been read under an authorisation nobody can find.

**Why not record grants in the existing `AuditTrail`, which is the obvious
reuse.** `PermissionDecision.tool` is a required `ToolDefinition`, embedded by
value, and ADR-0021 §1 makes that the clause "everything else here rests on":
"A decision does not say 'I approved `send_message`'; it says 'I approved *this
declaration*'". A grant has no declaration. Recording one would mean synthesising a
`ToolDefinition` that describes no registrable tool — putting a fabricated record
into the one store whose entire premise is that its records are not fabricated —
and every downstream consumer of the trail would then have to know which of its
rows are real. `SqliteAuditTrail`'s invariants make the same point mechanically:
`_check_resolution` compares `tool`, `parameters_digest`, `step_id` and
`execution_id`, none of which a grant has. The *structure* is borrowed and argued
for above; the store is not shared.

**The transcription is why one type suffices.** A revoking record carries the
`source` and `scope` of the grant it revokes, so it says what was withdrawn
without a join — the same reason ADR-0021 §1 embeds the whole declaration rather
than a name — and the store verifies the transcription, exactly as
`_check_resolution` verifies that a resolution "must answer the question that was
asked".

> **Normative.** The store is a **Tier 1 local store**: ADR-0004 §2's residency
> clause governs it, so no implementation may write it to a remote service. Its
> file lives under `Settings.data_dir` and is created owner-only, as every
> existing SQLite store in this tree is (ADR-0004 §4, ADR-0084 §9).

### 5. No live grant, no read — and the gate is the caller's, held by construction

> **Normative.** A reader is not read for a use unless a **live grant covering
> that reader's identity and that use** exists at the instant the read starts.
> Where none does, **nothing is opened**: the source is not resolved, not opened
> and not parsed. §5a governs a revocation that lands while a read is in flight.

> **Normative.** The check is the **caller's** — `orchestration`'s ingestion stage
> for `INGEST`, and `context/`'s reader adapter for `FACET`. A `Reader` neither
> holds a grant seam nor learns of one, and `Reader`'s surface is unchanged
> (ADR-0093 §1, §10).

> **Normative.** Every site that drives a reader takes a **`SourceGrants`** — the
> query seam, never `SourceGrantStore` — as a **required constructor argument**
> with no default. A composition that omits it does not type-check, and a driver
> that could record a grant does not type-check either (§3).

**Refuse to read, not read-and-discard, and the difference is the whole point.**
Opening the user's calendar is the act the grant is about; a design that reads the
file and then declines to propose from it has already done the thing it was not
permitted to do, and it does it on the schedule. ADR-0093 §7 says this in its own
terms about the default — "nothing may read a user's personal files because a
default said so" — and the same sentence with "an absent grant" in place of "a
default" is this clause.

**The gate is the caller's because the corpus already put it there.** ADR-0093 §1
rules that "Selecting when a sensor runs, and ingesting what it returns, are
`orchestration`'s. A sensor is never its own caller", and that a reader holds no
policy. Both sites are the ones already holding the reader:
`IngestionStage.__init__` takes it today, and ADR-0093 §3 rules that "A
`ContextSource` in `context/` holds a `Sensor`".

#### 5a. What the gate guarantees, stated as a boundary rather than as "nothing is read"

A gate spelled "ask the store, then read" is a check followed by a use, and
ADR-0021 §4 names that shape as a hazard in this system's own terms: "'The system
composes on one event loop' is precisely the setting in which an `await` between a
check and a write is an interleaving point." A revocation arrives over the local
API and is handled on that same loop, so a driver that suspends between the two
can start a read on a source the user revoked in between.

**The guarantee available is bounded, and it is stated first so that nothing below
reads as a stronger one.**

> **Normative.** The gate guarantees that every read is **authorised at the
> instant it starts**, and that nothing produced by a read whose grant has gone by
> the time it returns is used. It is **not** a guarantee that no byte of a source
> is read after a revocation is recorded: a read already in flight completes, and
> §5's "nothing is opened" governs the case where the check fails, never a read
> already begun.

**Why a stronger guarantee is not available without reopening a ratified
decision.** `CalendarReader.read` hands `_read_source` to a worker and awaits it,
because ADR-0093 §7 requires that "**The whole of a read runs off the event
loop** — resolving the path, opening it, reading it, parsing it, and expanding
recurrences alike … on a worker the **sensor owns**". So the `open()` happens on
another thread and genuinely races the loop: the driver can decide to read, the
worker can be scheduled a moment later, and a revocation handled in between is
handled *after* the read was authorised and *before* the file was touched. Nothing
a driver holds can stop that worker — §7 rules that a reader "gains **no lifecycle
method**. There is no `close`, no `aclose`, and nothing for a caller to await at
shutdown", and argues at length that adding one would re-create the shutdown hang
it exists to remove. Linearising the grant check with the file's acquisition
therefore means giving `Reader` a new seam, which is a `core/protocols.py` change
owing its own ADR (golden rule 5) and reopening §7's worker design to buy a
narrower race.

**And the residual is small in exactly the way this subject makes it small.** What
happens in the worst case is that bytes of a file the user just revoked are read
into a worker's memory and then dropped. Nothing is stored, nothing reaches a
prompt, nothing leaves the device — which is `VISION.md`'s own scope for a reader,
"it changes nothing outside the assistant".

**The bound is on *concurrency*, not on duration, and saying otherwise would be
false.** ADR-0093 §7 allows a reader "**at most one outstanding worker**", and that
is the real bound: no second read starts behind an in-flight one, so the residual
can never accumulate. What the reader's `calendar_read_timeout` bounds is the
*coroutine* — "the deadline abandons it", because "a thread blocked in a stalled
syscall cannot be killed" — so on a stalled mount the worker outlives the deadline
by however long the syscall takes, which §7 declines to bound at all. An earlier
draft of this paragraph claimed the ten-second figure as a duration bound on the
residual; it is not one, and the abandonment §7 describes is exactly the case it
was wrong about. The compensations are that the abandoned worker's reading is never
returned to anyone — `read()` has already raised `ReaderError` — and that §7's
reservation keeps the count at one until the kernel gives the thread back. §12
records the condition under which a linearising mechanism would be worth its cost.

Two clauses hold the guarantee that *is* available, and neither needs a lock.

> **Normative.** No `await` may occur between the `live()` result a driver gates
> on and its call to `Reader.read()`. The check and the start of the read are one
> synchronous step.

> **Normative.** A driver re-checks the grant when `read()` returns. A reading
> whose grant is no longer live at that moment is **discarded**: nothing is
> proposed from it, no facet is contributed from it, and the driver refuses under
> §5's outcomes.

> **Normative.** A driver **fails closed on an unanswerable check**. A `live()`
> that raises `GrantError` is not a grant: before the read nothing is opened, and
> after the read the reading is discarded exactly as a withdrawn grant is. No
> driver may proceed on a stale answer, on the earlier of two lookups, or on an
> absent one.

> **Normative.** A `GrantError` **propagates** from an ingestion driver rather
> than being converted into `SourceNotGrantedError`; on the facet path it leaves
> the facet absent, as every optional-source fault does. A store fault and a
> withdrawn grant are different facts and an operator must be able to tell them
> apart.

**Failing closed is stated rather than assumed, because the tempting reading is
the other one.** A store that cannot be read is a fault, and "the check failed, so
carry on with what we already knew" is what an implementer writes when the
alternative looks like losing a scheduled run. It is the wrong trade twice over:
the thing being protected is the user's personal files, and the corpus already
rules this direction for the neighbouring case — ADR-0016 §4's `UNKNOWN` cost is
"the author does not know, so policy must fail closed", which ADR-0021 §5 turned
into a floor. An unanswerable grant check is that sentence with "the store" in
place of "the author". A missed ingestion tick costs one interval; a read on a
revocation nobody could see costs the property this ADR exists to hold.

**The first clause closes the *driver's* window, which is the unbounded one.**
Awaiting a coroutine does not yield to the event loop; it runs that coroutine's
body until *its* first suspension. So with no intervening `await`, the driver
cannot sit on a stale answer at all — whereas a driver free to await anything
between the check and the call could hold one for arbitrarily long, which is the
difference between a race bounded by a worker's scheduling and one bounded by
nothing. It buys exactly that and no more: the worker-side race above survives it,
which is why the boundary clause is stated before these two rather than after.
This is a rule about the driver's body rather than a mechanism, and that is
deliberate: it costs a line and a test, where a mechanism would cost a contract.

**The second clause is what makes a revocation *win* rather than merely arrive.**
A read legitimately begun while granted takes real time, and a revocation may land
inside it. The residual after both clauses is therefore at most one already-started
read per source, whose bytes are **discarded rather than used**: nothing is
proposed, no facet is contributed, and nothing durable records that the read
happened.

**A lease held across the read was considered and refused**, which is the shape the
alternative takes. Holding a source-scoped guard from the check until the read
released it would make a revocation either block or fail while a read is in flight
— a permission withdrawal waiting on the thing it is withdrawing. And it is worse
than it looks: to be sound the guard would have to be released by the *worker*, not
by the coroutine, for exactly the reason ADR-0093 §7 keys its own reservation to
the worker — so a stalled mount would hold the user's revocation for as long as the
kernel holds the thread, which §7 declines to bound. The whole point of a
revocation is that it takes effect at once. Discarding the reading gives it full
effect at the only place it matters — nothing crosses into memory or into a
prompt — without letting a read hold the user's decision hostage.

**Aborting the in-flight read is not available, and ADR-0093 §7 is why.** A
reader's read runs on a worker the reader owns, which "a read blocked indefinitely
may not delay or prevent the hub exiting" makes abandonable but not killable; the
reader exposes no cancellation handle to a driver beyond ordinary task
cancellation, and `Reader` "gains **no lifecycle method**". So "stop the read" is
not a thing a driver can do, and a clause requiring it would be one no
implementation could honour.

**The required constructor argument is the mechanism, not a habit.** The
alternative — an obligation stated in prose and honoured by review — is the shape
`IngestionStage`'s own docstring already names as the weak one, calling the
matching store-identity requirement "a composition-root obligation no type can
express". This one *can* be expressed, so it is: a stage that cannot be built
without a grant store cannot be wired without one, and `mypy --strict` is the
enforcer rather than a reviewer's memory. It is the same move ADR-0093 §1 made when
it said of the producer's scope limit, "Here it is a type."

> **Normative.** An ingestion pass over a source with no live `INGEST` grant
> raises `SourceNotGrantedError` (§10). It is never reported as a successful pass,
> and never as a `ReaderError`.

**Silence is the one answer that is forbidden, and ADR-0093 §8 already argued
why.** An ungranted pass reported as zero proposals is indistinguishable from "the
source had nothing to say within the bound", which that section rules is a
*success*; a deployment whose grant was revoked would then look healthy while
ingesting nothing, which is precisely the shape ADR-0022 §4a refuses. Nor is it a
`ReaderError`: that class means "the source could not be read" (ADR-0093 §10) and
an operator debugging a missing calendar should not be sent to the filesystem for a
fault that lives in the grant store.

The scheduler treats the refusal as ADR-0083 §7 treats any job failure — logged
with its class, retried at the next due instant, never taking the process down.
**A deployment that revokes a grant while leaving `calendar_reader_interval` set
therefore logs a refusal every interval, and that is the correct behaviour rather
than a defect to design around:** it is configuration and consent disagreeing out
loud, which is the state ADR-0093 §7's clause exists to make visible. The operator's
fix is to unset the interval, which is a configuration act answering a
configuration fact.

> **Normative.** A facet whose source has no live `FACET` grant is **absent**, and
> `CurrentContext` says nothing about why. No facet and no field of
> `CurrentContext` reports a source's grant state.

**This is ADR-0096 §4's rule extended to a state that section could not name,
using its own argument.** §4 forbids reporting "a source's configuration or
enablement state" because `CurrentContext` reaches a prompt through
`_render_request`, and a field saying "the calendar is disabled" is "a grant
conversation conducted by a field nobody designed". Grant state is that hazard in
its purest form — a field saying "the calendar is not granted" is a model being
handed a script to ask for access — so the prohibition is restated over the third
state rather than left to be inferred from the first two. ADR-0096 §4's own text is
untouched and stays true; §11 applies ADR-0070 §1's test.

The facet path needs no new failure mode: ADR-0008 §4 already skips an optional
source and leaves its facet `None`, and ADR-0096 §4 already rules that `None` "does
not distinguish unconfigured, disabled, never-read, failed or empty". Ungranted
joins that list and is likewise indistinguishable, which is the intended outcome.

### 6. Revoking is prospective: it stops the reading and does not unwrite the beliefs

> **Normative.** Revoking a grant retires no belief, closes no validity window,
> deletes no record and alters no stored record. Its whole effect is that §5's
> check stops passing.

> **Normative.** A revocation is never presented as, and never produces, a
> retraction or an absence claim about what the source reported.

> **Normative.** A revoked grant's record is **retained**, so a source that has
> been revoked still has its complete grant history on file — under §1's
> source-level relation, never as a per-belief attribution.

This is the sharp question and it deserves the three candidates tested rather than
one asserted.

**Closing the beliefs' validity windows is the appealing answer and it is wrong on
two independent grounds.** Mechanically, there is no operation to do it with:
ADR-0045 §4 closes a window only as step 1 of applying a `SUPERSEDE` for a
*proposed replacement record*, and ADR-0080 §1 refines that close to a clamp within
the same mechanism. A revocation has no replacement record to propose, so
"retire everything from this source" is a `MemoryWriter` operation that does not
exist, and inventing one here would be a `core/protocols.py` semantics change owing
its own ADR under golden rule 5 — decided inside an ADR about permissions, for a
subsystem this one does not own.

Substantively it is worse than unavailable. ADR-0045 §2 defines the window as "the
interval during which a record is the system's live belief", and ADR-0092 §4 gives
the only ratified ground for retiring an attested belief: a **user assertion** that
conflicts with it, admissible because an attested belief "is not re-derivable *by
us* — and it is **re-reportable by its source**". "Stop reading my calendar"
asserts nothing about whether Tuesday's meeting existed. Closing the window would
record that the system stopped believing a fact at the instant a *permission*
changed, which is a false statement about the belief dressed as a lifecycle event.

**Deleting the beliefs is worse still, and it is not what was asked.** ADR-0004 §6
already gives the user the right to delete their data and `forget` already does it;
a revocation that also deleted would fuse two acts whose blast radii differ by
orders of magnitude behind one word. The asymmetry is decisive: a user who wanted
only to stop the reading and got a deletion cannot undo it, while a user who wanted
both and got only the first is one explicit command away from the rest.

**ADR-0093 §4 does not forbid this and its reasoning still governs.** §4 bars a
*reader* from proposing an absence because "a bounded read, a truncated file, a
permission error and a genuinely deleted entry are indistinguishable from the
reading". A revocation is perfectly distinguishable — it is a user act with a
durable record and an instant — so §4's prohibition is not what decides this
section, and saying otherwise would be stretching a ratified clause past its
subject. What survives is its *consequence*: §4 exists because a single act should
not destroy a user's beliefs on evidence the user cannot see, and a revocation that
silently retired a year of calendar beliefs is that failure reached by a different
road. #639 tracks the separate, legitimate question of an entry absent from a later
*complete read*, and nothing here touches it — that is a fact about the source's
report, and this is a fact about permission.

**Retention of the revoked record is what keeps the answer honest.** Beliefs from a
revoked source remain in the store, enumerable, banded `ATTESTED`, and killable by
the user (ADR-0073 §5). Were the record removed on revocation, `reported_by` would
point at a source with **no authorisation on file at all**, and every belief from it
would read as unauthorised; retaining it means the store says what happened for that
source — granted at these instants, revoked at those. That is the source-level
relation §1 rules and its limit: it does not say which grant a given belief was
read under, and §1 is where that residual is argued. Nothing is added to the belief
to achieve any of it.

**What a user who wants forgetting does today, and what is owed.** They use
`forget` per belief. Offering "revoke and forget everything this source told you"
as a **single explicit act** is a real want and is deferred in §12 rather than
refused: it needs an enumeration of beliefs by `reported_by`, which is a
`MemoryStore` read surface ADR-0092 §10 already declined to add for its own
neighbour and filed as #631.

### 7. A source grant is not an action authorisation, and may never be used as one

> **Normative.** A `SourceGrant` may never be cited as
> `PermissionRuling.authorised_by`, and no `ActionPolicy` implementation may
> consult a `SourceGrants` or a `SourceGrantStore`. ADR-0021 §5's disclosure floor
> is neither relaxed nor satisfied by anything in this ADR.

> **Normative.** ADR-0021 §6's deferred **standing grants for actions** are
> untouched by this ADR and stay deferred, with the precondition ADR-0021 §3
> places on the ADR that introduces them unspent.

**This is the clause that keeps two safety systems from being joined by
accident.** ADR-0021 §5 rules that a tool with a non-empty `discloses` "may not
receive `ALLOW` with `authorised_by` unset", and that "*Auto*-granted is the
operative word: the floor is on the policy deciding by itself … an `ALLOW` naming
the user decision it rests on is permitted and is how a standing grant will work".
A `SourceGrant` *is* a recorded user decision with an id. Nothing in its shape
would stop a later lane from citing one, and the result would be a calendar-read
grant silently authorising an off-device transmission — the floor satisfied by a
consent the user gave about something else entirely.

**The two are different subjects and the corpus says so at every level.**
`VISION.md` governs reading and acting separately; ADR-0021 §3's precondition on
standing grants is that they be "resolvable — to a recorded user decision that
**actually covers this tool**", and a grant naming a source covers no tool at all.
So the precondition is not met here because it is not engaged: this ADR introduces
no second source of authorisation for `decide`, and `ThresholdActionPolicy.decide`'s
documented guarantee — "`authorised_by` is always unset: standing grants are
deferred, so this policy has no authorisation source and may not invent one" —
remains exactly as true after this ADR as before it.

**Stated as a rule rather than left to the obvious reading**, because the obvious
reading is what an implementer reaches for when two records in one package both
mean "the user said yes".

### 8. Nothing mints a grant from what is already configured

> **Normative.** No grant is created from a `Settings` value, an existing source
> path, an already-ingested belief, an upgrade, a migration, or a first run. An
> installation that has been reading a source stops reading it until the user
> grants.

> **Normative.** The refusal is legible to an operator: the log line names the
> source's identity and the use that was refused, and carries no path and no
> source content (ADR-0004 §5, ADR-0093 §8).

**This is ADR-0093 §7's clause applied to the moment it is most tempting to
break.** Backfilling a grant from `calendar_reader_path` is precisely
"configuration presenting itself as a grant", performed once, invisibly, by an
upgrade — the one way §7 says the decision must not be made. It would also produce
a grant record with no user act behind it in a store whose entire value (§4) is
that its records say what the user decided.

The cost is real and small: today exactly one source exists, it ships disabled by
default (ADR-0093 §7), and any deployment reading a calendar is one an operator
deliberately configured, so the population that must run one command is the
population that already ran one edit.

**Beliefs already ingested with no grant stand**, under §6's rule — they were
written under the ratified state of the system at the time, and retroactively
retiring them would be the destructive act §6 refuses, applied to records whose
only defect is their date.

### 9. The user grants through a client; the state is the hub's

> **Normative.** Granting, revoking and listing grants are **hub operations
> reached by a client** (ADR-0084). The state lives hub-side under
> `Settings.data_dir`. A grant is never a `Settings` field, never a file the user
> is asked to edit, never a tool a model may invoke, and never a step a plan may
> execute.

> **Normative.** The hub's grant operations are the **only** holder of a
> `SourceGrantStore`. No scheduler job, no pipeline stage, no `context/` source
> and no reader driver holds one (§3, §5).

> **Normative.** The grant operation accepts a `source` **only** when it equals
> the declared `name` of a `Reader` the hub holds. A source naming no such reader
> is refused, and no `SourceGrant` is constructed from it. The operation also
> answers what the grantable sources are, so a client offers a choice among
> declared identities rather than a free-text field.

> **Normative.** A refusal under the clause above names no path and echoes no
> caller-supplied string beyond what the client already sent, so a mistyped value
> cannot reach the log (ADR-0004 §5).

**Without this, §1's key rule is a rule and not a property — and ADR-0093 §7 shows
the difference matters.** `Identifier` refuses a blank string and nothing else, so
a `SourceGrant` carrying `source="/home/alice/calendar.ics"` or an email address
satisfies its own type, records, and survives into `export` — putting exactly the
Tier 1 data §7 forbids in an identity into a durable, user-rendered, exportable
store. §7's own answer to this hazard was not a rule but a shape: the identity is
"**declared by the sensor** and is not a configurable value", because "A declared
constant cannot carry personal data at all, which is a property rather than a
rule". Deriving the grant's subject from the readers the hub actually holds is that
same property, one layer up: the set of admissible values is the set of declared
constants, and there is no free-text path into it.

**The check is here rather than in the store, and that placement is forced.**
`permissions/` may not import `ai_assistant.readers` — ADR-0093 §2 rules that "no
subsystem may import it", and `lint-imports` holds it — so a store cannot know
which identities exist. The hub's grant operation is the one place that holds the
readers by injection and can answer, which is the same reason §5 puts the read gate
in the drivers rather than in the reader.

**A grant whose reader later disappears is not a defect.** A deployment that unsets
`calendar_reader_path` leaves a stored grant naming a source nothing drives; the
record is history and stays readable, `live` keeps answering about it, and no read
happens because no reader exists. Nothing needs to reconcile the two, and a rule
that pruned such grants would be the store editing its own history.

ADR-0084 §5 made the CLI a client of the hub's API and promoted the façade to a
Protocol, and ADR-0083 §2 makes `data_dir` the hub's. A grant is durable state the
scheduler reads on a background tick, so it belongs where the other Tier 1 stores
are; a client that held it would be authorising a hub it cannot see.

**"Never a tool a model may invoke" is the load-bearing half.** A model that could
propose a grant is a model that can widen its own reach, which is the inversion
ADR-0005 §3's "The model proposes; a deterministic policy disposes" exists to
prevent, and it is why §1's third clause names every non-user route explicitly
rather than saying "the user grants".

> **Normative.** The `AssistantEngine` method signatures for these operations, the
> promoted result types, and their wire frames are **not decided here**. They are
> owed as their own contract ADR, on ADR-0084 §5's step-1/step-2 split, and land
> before any client implements them.

**Deliberately split, on the precedent that invented the split.** ADR-0084 §5
separated "*whether* the trigger has fired … from *what the surface is*", and
ADR-0085 then ratified the engine surface as "fifteen methods, twenty-four types,
**one closed graph**" with a size limit as a contract clause and a canonical wire
encoding in ADR-0087. Adding methods to that Protocol is a change to a ratified
closed graph with a byte-level encoding attached; deciding it inside a permissions
ADR would be exactly the pre-emption ADR-0085 was created to prevent. Its firing
condition is this ADR merging.

### 10. The contract surface owed, and what the triad lane owes

**New surface in `core` — a breaking change (golden rule 5):**

- **`core/types.py`** gains **two** types:
  - **`GrantScope`**, a `StrEnum` with exactly two members, `FACET` and `INGEST`
    (§2). A `StrEnum` for `DataTier`'s reason — it is a stable, serialisable,
    user-facing vocabulary — and **not** ordered: `PermissionOutcome` is ordered
    because outcomes are ranked by severity and `_SeverityScale` combines them
    (ADR-0021 §2); two uses of a source are not comparable and an order would
    invite a `max()` that means nothing.
  - **`SourceGrant`**, a frozen pydantic model (ADR-0068) because it crosses a
    subsystem boundary (`CLAUDE.md`). Five fields:
    - `id: DurableIdentifier` — the record's own id, minted by the caller, as
      `PermissionDecision.id` is (ADR-0021 §3: a store neither mints ids nor reads
      a clock).
    - `source: Identifier` — the reader's declared identity (§1). `Identifier`
      rather than `EncodableText`, matching `Attestation.reported_by`, so a blank
      source is refused by the type.
    - `scope: tuple[GrantScope, ...]` — non-empty, without duplicates, and in
      declaration order, so two implementations serialise one grant identically.
      A tuple rather than a `frozenset` for that reason: ADR-0087 fixes a canonical
      wire encoding and a set has no canonical order.
    - `decided_at: UtcInstant` — when the user decided. Timezone-aware and
      refused naive, for `PermissionDecision.decided_at`'s reason: the store is
      durable *and ordered*.
    - `revokes: DurableIdentifier | None = None` — the grant this record revokes,
      `None` on a granting record. This is `PermissionDecision.resolves`'s shape
      and it is chosen for its reason: one type that is both the act and its
      undoing keeps the store's rows homogeneous and its wire encoding
      undiscriminated.

  > **Normative.** A granting record (`revokes is None`) carries a non-empty
  > `scope`. A revoking record carries the `source` and `scope` of the grant it
  > revokes, transcribed verbatim; the store verifies the transcription (§4).

- **`core/protocols.py`** gains **two** Protocols, both `@runtime_checkable` as the
  seams around them are. The split is §3's second clause and it is a capability
  boundary, not a taxonomy.
  - **`SourceGrants`** — the query seam, one member:
    - `async live(*, source: str, use: GrantScope) -> SourceGrant | None` — the
      live grant covering that source and use, or `None`. It returns the
      **record** rather than a boolean so a caller can name what authorised the
      read.
  - **`SourceGrantStore`** — the durable store, five members: `live` with exactly
    the semantics above, plus
    - `async record(grant: SourceGrant) -> str` — append and return the id.
      Write-once, atomic over the duplicate check, the live-grant check, the
      revocation invariants and the append, for the reason ADR-0021 §4 gives:
      without atomicity "the single-use guarantee is a race".
    - `async recent(*, limit: int = 50) -> list[SourceGrant]` — newest first, ties
      broken by id, `limit` strictly positive and refused otherwise. Bounded
      because every read of a Tier 1 store in this corpus is (ADR-0021 §4,
      ADR-0073 §2), and the row count grows with grant churn rather than with the
      number of sources.
    - `async export() -> list[SourceGrant]` — every record, in the same order.
      ADR-0007 §3's export right, and `AuditTrail.export`'s shape.
    - `async clear() -> int` — wholesale erasure only, for ADR-0021 §4's reason.

  **No `get(id)` and no `delete(id)`, each declined for its own reason.** A
  selective delete is the page torn out of the book (ADR-0021 §4). A `get` has no
  consumer: the revocation invariant is checked *inside* `record`, and §1's join
  from a belief runs through `source`, not through an id — so it would be surface
  with no consumer (ADR-0045 §1, ADR-0028 §7). It is additive later.

  Illustrative signatures, in ADR-0073 §1's and ADR-0093 §10's form — the
  semantics above are the contract, the spelling is the lane's:

  ```python
  @runtime_checkable
  class SourceGrants(Protocol):
      async def live(self, *, source: str, use: GrantScope) -> SourceGrant | None: ...


  @runtime_checkable
  class SourceGrantStore(Protocol):
      async def record(self, grant: SourceGrant) -> str: ...

      async def live(self, *, source: str, use: GrantScope) -> SourceGrant | None: ...

      async def recent(self, *, limit: int = 50) -> list[SourceGrant]: ...

      async def export(self) -> list[SourceGrant]: ...

      async def clear(self) -> int: ...
  ```

  **`SourceGrantStore` does not inherit `SourceGrants`, and it does not need to.**
  Every Protocol in this file is satisfied structurally, so one `permissions/`
  class implementing all five members satisfies both seams at once, and a
  driver's `SourceGrants` parameter accepts it. Declaring inheritance would add a
  base-class relationship the tree uses nowhere and buy nothing mypy does not
  already give.

  **The two names are close, and that is the smaller risk of the two available.**
  A driver's parameter is annotated with the type it is entitled to, so the
  narrowing is visible at the one place it matters — `grants: SourceGrants` in a
  constructor signature — and a driver that named the store instead is a
  review-visible widening rather than a silent one. The alternative, a name that
  did not obviously belong to the same pair, would have made the relationship
  invisible instead.

- **`core/errors.py`** gains **three** classes:
  - `GrantError(AssistantError)` — the store could not be read or written.
  - `InvalidGrantError(GrantError)` — the store **refused** the record: a
    duplicate id, a second live grant for one source, or a revocation failing any
    of §4's invariants. **One class rather than three**, unlike
    `AuditTrail`'s split, because the caller's recourse is identical in all three
    — read the store and construct a different record — whereas ADR-0021 §4's
    `DuplicateDecisionError` and `InvalidResolutionError` are split precisely
    because a replayed write and a substituted subject call for different
    handling.
  - `SourceNotGrantedError(AssistantError)` — raised by a *driver* under §5, not
    by the store. **Not `PermissionDeniedError`**, whose docstring scopes it to
    "An action was blocked by the permission/policy layer" and which
    `orchestration/runner.py` raises when a confirmation was refused: §7's whole
    content is that a source refusal and an action refusal are different subjects,
    and a caller that cannot tell them apart is one that will report "you declined
    to send that email" when the calendar was never granted.

- **Nothing else.** No change to `Reader`, `SourceReading`, `ActionPolicy`,
  `ActionRequest`, `PermissionRuling`, `PermissionDecision`, `AuditTrail`,
  `Provenance`, `Attestation`, `CurrentContext`, `ContextFacet`, `MemoryWriter` or
  `AssistantEngine`. No new `Settings` figure is owed, which is a consequence of
  §8 rather than an omission: a grant has no configuration.

**What the triad lane owes, as one change (`CONTRIBUTING.md` → "Adding a
Protocol"); both Protocols' triads are that one change, not two:**

1. The two Protocols and both types, with `source` documented under §1's Tier 2
   obligation in the form `Attestation.reported_by`'s docstring already uses, and
   `scope` documented with its non-empty, no-duplicate, declaration-order rule.

   > **Normative.** `SourceGrant`'s own tests pin the `scope` invariants at
   > **construction**, independently of any store: an empty `scope` is refused, a
   > `scope` with a repeated member is refused, a granting record with a valid
   > `scope` is accepted, and an accepted `scope`'s order survives
   > `model_dump`/`model_validate` unchanged.

   **Stated because the store suite cannot reach it.** A plain
   `tuple[GrantScope, ...]` accepts `()` and duplicates unless the model validates
   them, and every clause in the suite below starts from a *valid* recorded grant
   — so an implementation that shipped the type without the validators would pass
   the whole suite while admitting an empty "grant" that authorises nothing and
   still occupies §4's one-live-grant-per-source slot, blocking the real one. The
   round-trip assertion is there because §10 chose a tuple over a `frozenset`
   precisely so ADR-0087's canonical encoding has an order to encode, and an
   invariant nothing serialises is one nothing checks.

2. **The shared conformance suites** — the clauses that bind **every**
   implementation, which are the ones expressible without a backing technology.
   `SourceGrants` owes the **first two** clauses below; `SourceGrantStore` owes all
   of them. Each maps to a ruling above:
   - A recorded grant is returned by `live` for **each** use in its scope, and not
     for a use outside it (§2).
   - **`live` returns a detached snapshot**, and the case is written as a mutation:
     mutating the returned grant's `__dict__` — `scope` in particular — leaves the
     next `live` answering exactly as it did before (§4).

     **This binds the narrow seam and not only the store, which is where it would
     have been missed.** `live` is the *only* member of `SourceGrants`, so a
     query-only implementation that handed back its own object would satisfy a
     detachment rule written over "queries on the store" while leaking the one
     value in the system that decides whether a source may be read. The concrete
     bypass is worth naming because `frozen=True` does not close it: a caller
     granted `FACET` alone mutates `scope` on the object `live` returned to include
     `INGEST`, and the driver's next check authorises ingestion the user never
     granted. That is §5's gate defeated through its own answer.
   - Recording a second grant for a source with a live one raises
     `InvalidGrantError`; after a revocation, a new grant for that source is
     accepted (§4).
   - After a revoking record, `live` returns `None` for every use of that source,
     and the revoked grant is **still** returned by `recent` and `export` (§4, §6).
   - A revocation naming an absent grant, an already-revoked grant, another
     revocation, a different `source`, or a different `scope`, raises
     `InvalidGrantError` (§4). Five cases, enumerated so a lane writes all five
     rather than the one easiest to provoke.
   - **A revocation timestamped *before* the grant it revokes is accepted**, and
     `live` returns `None` for that source afterwards (§4). The inverse of the
     clause above and written as its own case, because it is the one a lane copying
     `AuditTrail`'s shape will get backwards — and getting it backwards is what
     makes a grant unrevokable across a clock correction.
   - `record` is write-once: a duplicate id raises rather than overwriting (§4).
   - Every query returns a **detached** snapshot, ADR-0018 §3's rule applied to a
     third store and for ADR-0021 §4's reason — a caller holding a store's own
     object could rewrite the record of what was granted.
   - **`record` detaches its input too, and the case is written from the write
     side**: after a successful `record`, mutating the caller's object through
     `__dict__` — `source`, `scope` and `revokes` each in turn — leaves every later
     `live`, `recent` and `export` returning the record as it was appended (§4).
     Written separately from the query clause because query detachment does not
     repair state the store already shares, which is the window ADR-0021 §4 says
     detaching on reads alone leaves open.
   - `record` **revalidates**: a `SourceGrant` corrupted past its own model is
     refused with `InvalidGrantError` rather than stored (§4).
   - `recent` refuses a non-positive `limit` and returns at most `limit` records,
     newest first with ties broken by id ascending.
   - `clear` empties the store and returns the count removed.
   - Input observation (ADR-0065) and cancellation (ADR-0060), as every seam owes.
3. **Two canonical fakes in `ai_assistant.testing`** — `FakeSourceGrants` and
   `FakeSourceGrantStore`, the names
   `tests/core/test_protocol_triad.py` requires. Each is scriptable to hold a live
   grant, to hold a revoked grant, to raise `GrantError` **from `live()`**, and —
   for the store — to have `record` raise: the states a driver's §5 gate must be
   tested against, so a consumer can test its own refusal paths.

   **The raising `live()` is required of both fakes and is not decoration.** §5a's
   fail-closed clause is otherwise untestable: without it a driver's `GrantError`
   branch is unreachable from any test, and an implementation that caught the error
   and carried on with the earlier lookup would pass everything while writing
   beliefs after its authorisation stopped being checkable. That is the same class
   of vacuous pass ADR-0093 §10 refused when it required its own fake's suspension
   gate.

   > **Normative.** The `SourceGrants` conformance suite is bound against **both**
   > fakes. `FakeSourceGrantStore` is the wider seam's fake and satisfies the
   > narrow one structurally, so binding it there costs one class and turns §3's
   > "one implementation satisfies both" from an assertion into a test.

   **A further capability is required of `FakeSourceGrants`, and it is what makes
   §5a's second clause testable at all:** it can be scripted to **revoke between
   `live()` calls** — the first call answers with a grant and a later one with
   `None`, without the test having to record anything, which the query seam has no
   method to do. Without it a driver's discard path is unreachable from a test and
   the clause would report as held while nothing exercised it. This is the same
   reasoning ADR-0093 §10 used to require the suspension gate on its own fake: a
   test that cannot reach the code a clause forbids is worse than no test.

**Two rulings above are deliberately *not* suite clauses**, and putting them there
would be the error. The test is whether a clause is decidable from the store's own
surface:

- **§5's caller-side gate, and §5a's two clauses with it.** All three are
  obligations on `orchestration` and `context/`, not on the store, and no store
  implementation exhibits any of them. They belong to the ingestion stage's and the
  adapter's own tests, alongside the required constructor argument that makes
  omitting the gate a type error.

  > **Normative.** Each driver's own tests cover the five cases §5 and §5a
  > distinguish: no live grant at the check (nothing is opened); a `live()` that
  > raises before the read (nothing is opened); a grant revoked between the check
  > and the return of `read()` (the reading is discarded); a `live()` that raises
  > on the re-check (the reading is discarded); and a grant live throughout (the
  > reading is used). All five are written against the driver, using the canonical
  > fake's scripted revocation and its scripted failure, and none is a store
  > conformance clause.

- **§7's prohibition on citing a grant as `authorised_by`.** A statement about
  what a *different* subsystem may not do; nothing in this store's return values
  exhibits it. It is an `ActionPolicy` review obligation and is stated here so its
  absence from this suite does not read as its absence from the contract.
- **§9's rule that a `source` must name a reader the hub holds.** A store cannot
  check it — `permissions/` may not import `ai_assistant.readers` (ADR-0093 §2) —
  and `Identifier` only refuses a blank string, so nothing in `core` can either.

  > **Normative.** The grant operation's own tests pin it: a `source` that is a
  > filesystem path, an email address, or any string that is not a held reader's
  > declared `name` is refused, no `SourceGrant` is constructed, and the value
  > never reaches `recent` or `export`.

**What later lanes owe, and this ADR does not:** the `permissions/` implementation
and its schema; the two caller-side gates, their required `SourceGrants`
constructor arguments, and **all five** of the driver cases §5 and §5a name — no
live grant, a raising `live()` before the read, a revocation between the check and
the return, a raising `live()` on the re-check, and a grant live throughout; the
client surface ADR §9 names, the CLI commands behind it, and §9's
source-must-name-a-held-reader check with its own tests; and the operator log line
§8 requires.

### 11. This ADR classified under ADR-0070 §1 and ADR-0082 §1

ADR-0082 §1 requires the judgement to be made in the later ADR's text. It is made
here, clause by clause, and the answer is that **no earlier ADR's status line
changes**. The places where the opposite reading is available:

- **ADR-0093 §7 and §11.** §7 rules that configuration is not a grant and §11
  defers the grant model with a firing condition. This ADR *meets* that condition
  and decides the deferred thing. §7's clause is not narrowed — §8 applies it —
  and §11's deferring sentence stays true of ADR-0093. A reader holding only
  ADR-0093 would act no differently: they would still not treat a `Settings` field
  as consent. Answering a deferral is ADR-0083 §15's carve-out, not an amendment.
- **ADR-0093 §7a's enablement matrix.** §7a enumerates four states of
  `calendar_reader_path` × `calendar_reader_interval` and refuses one at load. This
  ADR adds no fifth row and edits no cell: the grant is a **third axis**, and it is
  not configuration — §7's own clause says so — so the table continues to describe
  exactly what it describes, which is a configuration. What changes is that a
  configured, enabled source may now also be ungranted, which is a state §7a never
  claimed to enumerate because the thing that creates it did not exist. Not an
  amendment.
- **ADR-0096 §4.** Its second clause forbids `CurrentContext` reporting "a
  source's configuration or enablement state". §5 above adds a third prohibited
  state rather than editing the clause, and ADR-0096's text stays true as written:
  a reader holding only ADR-0096 is obliged to exactly what it obliged them to
  before. A new obligation added beside a ratified one is an addition, which is
  ADR-0070 §1's test unmet. **ADR-0096 stands `Proposed` and this ADR does not
  touch it** — not its text, not its status; #633's sequencing is its own lane's.
- **ADR-0021 §3, §5 and §6.** §3 defers "gating direct Tier 0/1 data access" and,
  in the same section, names the shape it should take. This ADR builds that shape
  for one subject — a connected source — and answers neither of §3's stated
  blockers: #74 is untouched, and no union parameter is introduced. §5's floor is
  neither relaxed nor satisfied (§7). §6's standing grants stay deferred, and its
  named precondition stays unspent. A reader holding only ADR-0021 would act no
  differently: `decide` still returns `authorised_by is None`, and the deferrals
  they were told about are still deferred. Not an amendment. Under ADR-0082 §1
  this ADR's additions are **stacked additions** on it, recorded here and nowhere
  else.
- **ADR-0045 §4 and ADR-0080 §1.** §6 above examines the window-closing mechanism
  and declines to use it. Declining to invoke a clause is not amending it, and
  nothing here changes what `SUPERSEDE` does or what a clamp is. This is the
  ADR-0083 §15 pattern — examine a clause and state what it does — applied to a
  mechanism this ADR deliberately does not reach for.
- **ADR-0004 §7.** This ADR builds the half of its sentence that was never built.
  Implementing a ratified obligation is not amending it.
- **ADR-0092 §3 and §10.** §3's `reported_by` acquires a second consumer and is
  neither narrowed nor widened; §10's "grant surface … its own decision, next
  wave" is that decision arriving. Not an amendment.
- **ADR-0085.** No method is added to `AssistantEngine` here, and §9 routes the
  addition through its own ADR rather than through this one. Nothing in its closed
  graph moves.

### 12. Deferred, by name, each with the condition that fires it

- **Content-level scope** — which entries, which fields, which of several
  calendars. Fires when a surface can express a sub-source selector at all: the
  nearest candidate is ADR-0096 §10's first deferral, the calendar facet's
  entries, and ADR-0093 §11's source registry is the other. It lands as an
  optional field on `SourceGrant` under ADR-0008 §1's additive pattern.
- **A lapsing grant** — "read my calendar for the next hour". Fires with the first
  use case for temporary access; it is an optional `expires_at` on `SourceGrant`,
  the shape `PermissionDecision.expires_at` already carries (ADR-0059 §1), and
  §5's `live` check is where it would bite. Declined now for having no consumer.
- **An audit record of each *read***, which #629 asks for alongside the grant.
  Today the record of what a source said is the beliefs it produced, each carrying
  `reported_by` and `reported_at`, and a per-read row would be an unbounded Tier 1
  store with no reader. Fires when something needs to know about a read that
  produced no belief — the first candidate is a source whose reads can partially
  fail, which ADR-0093 §11 already sends to its own decision.
- **"Revoke and forget everything this source told me" as one act** (§6). Fires
  with the first user who asks; it needs an enumeration of beliefs by
  `reported_by`, which is a `MemoryStore` read surface ADR-0092 §10 declined to add
  and filed as **#631**'s neighbour.
- **Standing grants for actions** (ADR-0021 §6), unchanged, unnarrowed, and with
  ADR-0021 §3's precondition still owed by whoever takes them (§7).
- **Gating direct Tier 0/1 data access in general, and #74's
  model-provider-credential question.** §3's shape is now built for one subject;
  whether a credential is a permission subject at all is still what #74 settles.
- **Per-belief grant attribution** — pinning a stored belief to the *particular*
  grant record its read ran under, which §1 rules is not available and states the
  residual for. It needs a pointer field on `Attestation`, which ADR-0092 §10 has
  just declined to add a third field to for the reason ADR-0045 §1 and ADR-0028 §7
  give. Fires with the first surface that asks "under which authorisation was this
  written" — the likeliest is the belief inspection surface ADR-0073 §4 governs, if
  it ever renders more than the band and the source.
- **A mechanism linearising the grant check with the source's acquisition**, which
  would shrink §5a's residual from "a read already in flight completes" to "no byte
  is read after a revocation". It needs a new seam on `Reader` — a lease, a
  cancellation handle, or an acquisition callback — which is a `core/protocols.py`
  change owing its own ADR and reopening ADR-0093 §7's no-lifecycle-method ruling.
  Fires when a source arrives whose *read itself* has an effect the user would care
  about having happened — a fetch that marks messages seen, a source that bills per
  read — because today the residual act is bytes read and dropped.
- **A total order over grant records** — a monotonic sequence beside
  `decided_at`, so `recent` cannot show a revocation above the grant it revokes
  after a clock correction. Refused as a mechanism today in §4, where liveness is
  derived from the `revokes` relation and nothing compares two instants. Fires
  when a consumer needs a total order for something other than display, which
  would also be the first thing in this system to need one.
- **Who granted.** No user identity exists (#113, ADR-0036 §3). Fires with the
  first multi-user deployment, as an optional field.
- **A grant for something that is not a `Reader`** — a spoke reporting beliefs
  across the process boundary (ADR-0094). Fires when such a producer exists; §1
  keys on a reader's declared identity, and whether a spoke's identity is the same
  kind of thing is that lane's question.
- **Everything ADR-0093 §11 defers other than the grant model**, unchanged and not
  re-listed.

## Consequences

- **Leg 6's exit test becomes evaluable against its own wording.** "From a source
  the user granted" names a record that exists, that the user made, and that the
  read is checked against.
- **Enablement and grant become two acts, which is what ADR-0093 §7 said they
  must be.** Configuration says *where* and *how often*; the grant says *whether*
  and *for what*. Neither can be mistaken for the other, and a deployment where
  they disagree says so out loud (§5).
- **The permission layer gets the second half it was chartered with.**
  ADR-0004 §7 gated two things and only tool calls were ever built; source access
  now has a contract, in the shape ADR-0021 §3 predicted it would take.
- **Revocation is honest about what it does.** It stops the reading. It does not
  quietly retire a year of beliefs, and it does not pretend the source retracted
  anything (#639 stays a separate question about a separate fact).
- **What gets harder:** every site that drives a reader now needs a
  `SourceGrants` to be constructed at all; the corpus gains two Protocols and two
  triads where one would have done (§3); and an existing deployment stops reading
  until its user grants (§8). All three are deliberate — the first makes the gate
  impossible to forget, the second makes "only a user act creates a grant" a type
  rather than a promise, and the third is the only way the first grant is a
  decision rather than an inheritance.
- **A visible cost is created and named:** a revoked-but-still-configured source
  logs a refusal on every scheduler tick until the operator unsets the interval.
  That is configuration and consent disagreeing, and making it quiet would make it
  invisible.
- **Two residuals are named rather than closed, and each is bounded in the way it
  can be.** The gate guarantees a read is authorised *when it starts*, not that no
  byte is read after a revocation lands: ADR-0093 §7 puts the whole read on a
  worker nothing can stop, so a read already in flight completes — **at most one
  per source**, with everything it produces discarded, and with **no duration
  bound**, because §7's deadline abandons a stalled worker rather than ending it
  (§5a). And a belief
  resolves to its source's grant history, not to the one grant it was read under
  (§1) — the price of not adding a field to a ratified `core` type for a question
  no surface asks. Both are stated as boundaries so that no later lane claims the
  stronger property this ADR does not deliver.
- **Two lanes are unblocked and one is created.** The triad and the `permissions/`
  implementation can start; the `context/` adapter and the ingestion gate know what
  they must hold; and the client surface (§9) is a new contract ADR that did not
  exist before this one.
- **Revisit when** a second source exists — which is also ADR-0093 §7's registry
  trigger and §12's scope trigger — or when a producer that is not a `Reader` wants
  to be granted.

## Alternatives considered

- **Put source grants on `ActionPolicy`, as a second request shape or a union.**
  Rejected in §3 on ADR-0021 §3's own ruling that widening `decide` is breaking
  while a second Protocol is additive, and on the deeper ground that `decide` is
  contractually a pure function while a grant is durable state — the property
  ADR-0021 §6 named when it said "a store, not a field".
- **Record grants as `PermissionDecision`s in the existing `AuditTrail`.**
  Rejected in §4: `PermissionDecision.tool` is a required `ToolDefinition` and a
  grant has no declaration, so this buys reuse by putting a synthesised record into
  the one store whose premise is that its records are not synthesised.
- **Make the grant a `Settings` field — `calendar_reader_granted: bool`.** The
  cheapest possible change and the one ADR-0093 §7 forbids in as many words: it
  cannot be revoked by the user through the assistant, cannot be scoped, and leaves
  no record. It would discharge #629 in form while leaving every property
  `VISION.md` promises unmet.
- **Gate enablement instead of the read** — refuse to *construct* a reader without
  a grant. Rejected: grants are revocable at runtime and the composition root runs
  once, so the check has to be at the read or it is a check about the past. The
  constructor argument in §5 keeps the structural half of the idea, which is the
  half that was worth having.
- **Read the source but propose nothing when ungranted.** Rejected in §5: opening
  the file is the act being permitted, so this performs the harm and then declines
  the benefit — on a schedule.
- **Close the validity window of every belief from a revoked source.** Rejected in
  §6 on two independent grounds: mechanically there is no operation to do it with
  short of a `MemoryWriter` change this ADR does not own, and substantively a
  permission event is not a statement about when a belief was true.
- **Delete the beliefs on revocation.** Rejected in §6 as the asymmetry that
  cannot be undone: `forget` already exists for the user who wants it, and fusing
  the two acts takes the choice away from the one who does not.
- **Mint a grant from existing configuration on upgrade, so nothing breaks.**
  Rejected in §8. It is configuration passing for consent, performed once and
  invisibly, which is the single way ADR-0093 §7 says the decision must not be
  made.
- **One Protocol carrying both the query and the writes, injected everywhere.**
  The first draft of this ADR did exactly that, and adversarial review showed it
  defeats §1's central clause: the ingestion stage runs on a timer and would have
  held `record`, so a scheduler job could mint its own authorisation and nothing
  in the resulting record would look wrong. Rejected in §3 — the capability is
  removed from the type the driver names, on ADR-0077 §1's "Here it is a type" —
  at the cost of a second triad, which §3 states rather than discovers.
- **A source-scoped lease held from the grant check to the end of the read**, so
  the check and the read are linearised against revocation. Rejected in §5a: it
  makes a revocation block for the reader's deadline or fail while a read is in
  flight, which is a permission withdrawal waiting on the thing it withdraws. The
  cheaper pair — no `await` between the check and the start of the read, and
  discard the reading if the grant has gone — gives the revocation its full effect
  where it matters and costs a contract nothing.
- **One record type per act — a `SourceGrant` and a `GrantRevocation`.** Rejected
  in §10: it makes every query return a union that ADR-0096 §5 would then require
  to be explicitly discriminated on the wire, to buy a distinction
  `PermissionDecision.resolves` already shows the corpus does not need.
