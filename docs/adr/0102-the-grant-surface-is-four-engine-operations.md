# 102. The grant surface is four engine operations, and the source is chosen from what the hub holds

- Status: Proposed
- Date: 2026-08-04
- **Decides the client-facing surface ADR-0097 §9 names as owed.**
  `AssistantEngine` gains **four** methods — `grantable_sources`, `grant`,
  `revoke` and `recent_grants` — `core/types.py` gains **one** type,
  `GrantableSource`, and `core/errors.py` gains **one** class,
  `UngrantableSourceError`. It also rules where the store is opened, which
  closes #684. No code ships with it.
- **Flagged as a breaking change under golden rule 5.** The implementing lane
  changes `core/protocols.py` (four methods on a Protocol every structural
  implementation must then carry), `core/types.py` and `core/errors.py`. Its ADR
  is therefore ratified and merged as its own PR before anything implements
  against it (ADR-0015 §5).
- **Required review set: adversarial *and* architecture.** `ship.sh` gates the
  architecture lens on `core/protocols.py` or `core/types.py` changing, and the
  PR carrying this ADR touches neither — it is prose only. The set is taken
  anyway because the *decision* is `core` surface, which is what ADR-0093
  through ADR-0101 each declared it for, and this one extends the engine
  Protocol ADR-0085 promoted. Reviewed while `Proposed` and ratified only after,
  in a separate lane (`CONTRIBUTING.md` → "Contract ADRs land before their
  implementation"; #633 records why the flip cannot ride in the PR that carries
  it).
- **Discharges ADR-0097 §9's last clause**, which reads "The `AssistantEngine`
  method signatures for these operations, the promoted result types, and their
  wire frames are **not decided here**. They are owed as their own contract ADR,
  on ADR-0084 §5's step-1/step-2 split, and land before any client implements
  them." It also discharges the one question ADR-0097 §9a hands over by name:
  **which** response carries a source's current configured location.
- **Every reference below to a neighbouring ADR is to its text as merged on
  2026-08-04, not to its status on any later day.** ADR-0101 stood `Proposed`
  when this ADR was written and a separate lane ratifies it; nothing below turns
  on that, and no clause here is written in the present tense about another
  ADR's `Status`.
- **Amends no earlier ADR and supersedes none.** §13 applies ADR-0070 §1's test
  and ADR-0082 §1's record rule to the six places where the opposite reading is
  available — ADR-0085 §1's "and nothing else", ADR-0085 §5's closure, ADR-0083
  ruling 4's count, ADR-0097 §9 and §9a, ADR-0097 §10's error set, and ADR-0084
  §5's sequence.
- **It records three findings about the tree, and two of them change what the
  implementing lane owes.** The wire is derived from the Protocol rather than
  transcribed, so four methods and one error class cost `wire/` nothing (§10);
  the grant store makes a **sixth** database in a directory seven modules and
  three test modules describe as holding five (§12); and #675's lane-3 second
  bullet — "whether granting and revoking are audited" — was already answered by
  ADR-0097 §4 and is stale rather than open (§11).

## Context

### What ADR-0097 left, and what it already fixed

ADR-0097 §9 is normative that granting, revoking and listing grants are hub
operations reached by a client, that the state lives hub-side under
`Settings.data_dir`, that the hub's grant operations are the **only** holder of
a `SourceGrantStore`, and that a `source` is admitted **only** when it equals
the declared `name` of a `Reader` the hub holds. It also requires the surface to
answer what the grantable sources are, "so a client offers a choice among
declared identities rather than a free-text field", and requires a refusal to
name no path and echo no caller-supplied string beyond what the client already
sent.

What it deliberately did not decide is the shape: the method signatures, the
result types and the wire frames, which its last clause routes here on ADR-0084
§5's step-1/step-2 split. ADR-0097 §9a adds one more, stated as an obligation
over a property rather than over an operation: a source's **current configured
location** must reach the user transiently at the moment of granting, and must
come to rest nowhere — "**which** one — a separate operation, a field on an
existing one, or part of a confirmation exchange — is the surface ADR's to
decide".

### The tree, read rather than assumed

At `9f1832a`:

- `AssistantEngine` exists in `core/protocols.py` with **fifteen** methods, and
  `core/types.py` carries the twenty-four promoted types under its
  "the promoted engine surface" comment. ADR-0084 §5's steps 3 and 4 have both
  landed: the hub serves, `HubEngineClient` is what `interfaces/cli.py`'s
  `_open_engine` returns, and the CLI opens no database.
- `SourceGrant`, `GrantScope`, `SourceGrants` and `SourceGrantStore` all exist,
  and `permissions/grants.py` carries `SqliteSourceGrantStore`, whose `path` is
  a required keyword-only argument with no default.
- **Nothing outside `tests/permissions/test_grants.py` constructs it.**
  `build_engine` takes `grants: SourceGrants | None = None` and, when it is
  `None`, wires neither `CalendarContextSource` nor `IngestionStage`; its one
  production caller, `Hub` in `service/hub.py`, passes no `grants` at all.

So no deployment can record a grant, no deployment reads a configured calendar
(#684), and leg 6's exit test — "the assistant knows something true about the
user's day it was never told, from a source the user granted" — is reachable by
a test with an injected fake and not by a user. `docs/roadmap.md` is explicit
that a gap closes when a user can exercise the capability.

### The three constraints the surface has to satisfy, and one that turns out not to bind

`AssistantEngine` is not an ordinary Protocol. ADR-0085 fixed fifteen methods
and twenty-four types with a **complete transitive closure** that terminates in
`core` (§5), a size limit that is a contract clause rather than a transport
property (§8c: the whole serialised payload at `hub_max_frame_bytes - 512`), and
a per-method wire mapping (§10) over the canonical encoding ADR-0087 ratified.
Anything added here is measured against all three.

The constraint that turns out **not** to bind is the one that looks most
expensive. `wire/surface.py` derives `METHODS` by reflection over
`AssistantEngine` and dispatches with `getattr`, and `wire/errors.py` uses "the
exception type's own class name" as the error code, resolved with `getattr` over
`core.errors`. Both were written to make the mapping "total by construction
rather than by a registry someone maintains". So four methods and one error
class cost the `wire` package nothing, and this ADR can spend its budget on
shapes rather than on plumbing.

### The knot: a check that cannot live where the data lives

ADR-0097 §9's admission rule needs to know which reader identities exist.
ADR-0093 §2 rules that no subsystem may import the reader package, and
`lint-imports` holds it, so a `permissions/` store cannot answer. ADR-0097 §9
draws the conclusion — "The hub's grant operation is the one place that holds
the readers by injection and can answer" — and §10 excludes the rule from the
store's conformance suite for the same reason, leaving it to "the grant
operation's own tests". Where that operation lives, and what it holds, is
therefore this ADR's to fix rather than the lane's to infer.

### An honest statement of what this ADR is not allowed to settle

- **Person identity.** ADR-0099 §1 rules one hub, one principal, and names the
  owner as the person "whose grants ADR-0097 records". Nothing here scopes a
  grant to a person, and person identity, enrolment and speaker attribution are
  tracked at **#691**.
- **`Reader`'s surface.** No member is added to it. ADR-0097 §9 declined the
  same widening for the same reason: it is a ratified Protocol with a built
  implementation, and golden rule 5 puts it in its own ADR.
- **Content-level scope, lapsing grants, per-belief attribution, and everything
  else ADR-0097 §12 defers.** Unchanged and not re-listed.
- **The memory export surface.** ADR-0101 §7 records that ADR-0004 §6's export
  right has no user surface at all, and defers the question jointly with the
  subject-scoped erasure. §14 keeps the grant store's `export` and `clear` in
  that lane rather than inventing a second answer here.

## Decision

We will put four operations on `AssistantEngine` — one that says what may be
granted, one that grants, one that revokes, and one that lists what was granted
and withdrawn — with the source admitted only when it names a reader the hub
holds, the record minted hub-side, and the source's configured location carried
by exactly one response and stored by none.

### 1. Four operations, and four is the floor rather than a preference

> **Normative.** The client surface for grants is exactly four methods on
> `AssistantEngine`: `grantable_sources`, `grant`, `revoke` and `recent_grants`,
> with §2's signatures. No other operation on any surface creates, revokes, or
> reports a `SourceGrant`.

**The count is derived from ADR-0097 §9 rather than chosen.** Its first clause
names three acts — "Granting, revoking and listing grants are **hub operations
reached by a client**" — and its third requires a fourth: "The surface also
answers what the grantable sources are." Three of the four are the acts; the
fourth is the enumeration that makes the third clause's "choice among declared
identities" something a client can offer.

**They are `AssistantEngine` methods because nothing else is reachable by a
client.** ADR-0084 §3 makes the envelope's `method` member "the
`AssistantEngine` method name", and `wire/surface.py` derives the legal set from
the Protocol itself. A hub operation that is not on that Protocol is not
addressable over the socket without a protocol version bump, so "a hub operation
reached by a client" and "an `AssistantEngine` method" are the same thing in
this tree.

**Nothing is folded, and each fold was tested.** `grantable_sources` and
`recent_grants` answer different questions — what *may* be granted, and what
*was* granted and withdrawn — and §3 shows why a client must not derive the
first from the second. `revoke` cannot be `grant` with an empty scope, because
ADR-0097 §2 refuses an empty scope at construction. And a compound
"change the scope" operation is refused in §5: ADR-0097 §2 already ruled that
changing a grant's scope is a revocation followed by a new grant, "and both
records are kept".

### 2. The four signatures

**Every annotation is spelled out**, in ADR-0085 §3's form and under its §2
convention: the subject of a call is positional and every other argument is
keyword-only. `Identifier`, `EncodableText` and `DEFAULT_PAGE_SIZE` are
`core/types.py`'s existing names.

```python
async def grantable_sources(self) -> tuple[GrantableSource, ...]: ...


async def grant(
    self, source: Identifier, *, scope: Sequence[GrantScope]
) -> SourceGrant: ...


async def revoke(self, source: Identifier) -> SourceGrant | None: ...


async def recent_grants(
    self, *, limit: int = DEFAULT_PAGE_SIZE
) -> tuple[SourceGrant, ...]: ...
```

**Docstrings are omitted here and are not optional in the Protocol**, exactly as
ADR-0085 §3 states for its own block.

**The two names avoid two collisions that would have been silent.**
`recent_grants` rather than `grants` — because `build_engine` already has a
`grants` parameter and every driver has a `grants` attribute, and because a
`grant`/`grants` pair differing by one letter is a typo that reads as valid
code. It also matches `recent_conversations` and the store member it is built
on, `SourceGrantStore.recent`. `grantable_sources` rather than `sources` —
because `source` is already taken at least twice on the memory surface
(`Provenance.source`, `SourceReading.source`), and because the longer name says
which question it answers.

**Both new names are shorter than the longest method name on the surface**, so
ADR-0085 §8b's envelope worst case is untouched: `grantable_sources` is 17
bytes against `interrupted_questions` at 21, and the 512-byte reserve is
recomputed from the same worst case it always was.

### 3. One new promoted type, and liveness is stated rather than derived

> **Normative.** `core/types.py` gains one type, `GrantableSource`: a frozen
> pydantic model (ADR-0068 §1) with `extra="forbid"` and exactly three fields —
> `source: Identifier`, the reader's declared identity; `location:
> EncodableText | None`, the source's current configured location (§6); and
> `live: SourceGrant | None`, the grant covering that source at the moment the
> response was computed, or `None`. It carries no other field.

> **Normative.** `GrantableSource.live` is computed hub-side, from the store.
> No client may derive a grant's liveness from `recent_grants`, and no surface
> may present a record `recent_grants` returned as live or as withdrawn on its
> own.

**The second clause exists because the derivation is unsound, not merely
redundant.** ADR-0097 §4 derives liveness from the `revokes` relation alone and
is emphatic that "**a revocation is never refused for its timestamp** —
including one that predates the grant it revokes". `recent` is ordered newest
first by `decided_at`, so after a clock correction a revoking record can sort
*below* the grant it revokes and fall outside a page that contains it. A client
walking a page would then report a withdrawn grant as live — the one answer this
whole contract exists to get right — and it would do so only on the deployment
where a clock moved, which is the failure that never shows up in a test.

**Three fields and no fourth, and the fourth that was considered is named.** An
earlier draft carried `grantable: bool` so that a reader whose declared `name`
is not admissible (§4) could be listed as unavailable rather than absent. It is
refused as surface with no consumer, the refusal ADR-0045 §1, ADR-0028 §7 and
ADR-0092 §10 each made: a non-admissible declared name is a defect in a reader,
not a state a user can act on, and every user-visible consequence of it is
already carried — the enumeration omits it, and §4's refusal names it. §12 puts
the diagnosis where an operator looks, which is the log.

**The closure stays closed, and that is the property ADR-0085 §5 actually
fixed.** Walking `GrantableSource`'s declared field types: `Identifier` and
`EncodableText` are `core` aliases; `SourceGrant` is a `core` model whose own
fields reach `DurableIdentifier`, `Identifier`, `GrantScope` and `UtcInstant`,
all `core`. The walk terminates in `core` on every branch, so this addition
preserves ADR-0085 §5's boundary exactly — nothing new leaves `core`, and
`lint-imports` sees no new edge.

### 4. The source is admitted, never trusted — and a revocation is never admitted away

> **Normative.** `grant` admits a `source` **only** when it equals, exactly, the
> declared `name` of a reader the hub holds **and** that name validates as
> `Identifier` and equals its own `str.strip()`. Any other value raises
> `UngrantableSourceError`, no `SourceGrant` is constructed from it, and the
> value reaches no store and no log.

> **Normative.** `revoke` applies no such admission check. A revocation is
> refused for no property of the source's name, and in particular is not refused
> because no reader currently declares it.

> **Normative.** No refusal raised by any of the four operations carries a
> filesystem path, and none writes a caller-supplied `source` value to a log.
> An `UngrantableSourceError` raised because a *held* reader's declared name is
> inadmissible names that reader; one raised because no held reader declares the
> value names no value at all.

**The first clause is ADR-0097 §9's, with one condition added and nothing
narrowed.** §9 makes canonical form a *necessary* condition for grantability;
adding "validates as `Identifier`" is a second necessary condition, so §9's
sentence stays true as written and the admissible set only shrinks. It is worth
the words because without it the failure is undeclared rather than absent:
`SourceGrant.source` is `Identifier`, which refuses a blank and — since
`Identifier` is `Annotated[EncodableText, …]` — refuses a string with no UTF-8
encoding, so a reader declaring one would make `grant` raise a `ValidationError`
from inside the operation. `wire/server.py` converts an `AssistantError` into an
error frame and lets anything else close the connection, so an undeclared
`ValidationError` reaches a client as a dropped socket. One clause turns that
into a typed refusal.

**The second clause is the one that would have been got wrong, and ADR-0097 §4
supplies the argument in its own words.** ADR-0097 §9 records that "A grant
whose reader later disappears is not a defect": an operator who unsets
`calendar_reader_path` leaves a stored grant naming a source nothing drives.
If `revoke` applied the admission check, that user could no longer withdraw
their own live grant — a configuration edit would have made a grant
**permanently unrevokable**, which is precisely the failure ADR-0097 §4 refused
when it declined `AuditTrail`'s timestamp invariant: "the one property
`VISION.md` names that this ADR exists to deliver, defeated by an invariant that
was protecting nothing". Revocation is the user's whole remedy under ADR-0097
§6, and nothing may stand between them and it.

**Nothing leaks through the opening this leaves.** A `revoke` naming a value no
reader declares finds no live grant, constructs nothing, records nothing and
returns `None` (§5), so the free-text route into the store that ADR-0097 §1 and
§9 exist to close stays closed on the revoking path too — not by refusing the
value, but by there being nothing for it to reach.

**The third clause is ADR-0097 §9's refusal rule read at the two ends it has.**
§9 forbids a refusal echoing "no caller-supplied string beyond what the client
already sent", and its stated reason is "so a mistyped value cannot reach the
log (ADR-0004 §5)". Returning nothing rather than the value to the sender is
strictly stronger than that and costs a client nothing it needs: a client that
sent the value still has it, and the useful remedy is `grantable_sources`, not
an echo.

### 5. Who mints, who reads the clock, and why the store is the arbiter

> **Normative.** The hub's grant operations mint each record's `id` from an
> injected factory and read `decided_at` from an injected clock. No client
> supplies either, and no client supplies `revokes`. A request payload for
> `grant` carries exactly `source` and `scope`; one for `revoke` carries exactly
> `source`.

> **Normative.** `revoke` resolves the live grant by querying
> `SourceGrants.live` for **every** member of `GrantScope` and taking the first
> answer, which is total because ADR-0097 §2 makes a grant's scope non-empty. It
> constructs a revoking record transcribing that grant's `source` and `scope`
> verbatim. Where no member answers, it records nothing and returns `None`.

> **Normative.** Neither `grant` nor `revoke` treats its own lookup as the
> authority. `grant` performs no liveness pre-check; the store's atomic
> one-live-grant rule refuses a second, and the resulting `InvalidGrantError`
> propagates rather than being retried or converted into a success.

**The request payload is two members and not a `SourceGrant`, and the
alternative is worse in three separate ways.** A client that sent a whole record
would set `decided_at` from its own clock — backdating a user act in a store
whose entire value (ADR-0097 §4) is that it says what actually happened — would
mint an id into a write-once store, and could set `revokes` to point at a record
it never read, which is the transcription invariant defeated from outside.
Sending two members leaves the record's construction where `Settings`, the
clock and the readers already are.

**The `GrantScope` sweep is stated rather than left to be inferred, because the
wrong version passes every test that exists.** `SourceGrants.live` takes a
`use`, so an implementation that queried only `FACET` would resolve a
`FACET`-scoped grant and silently fail to find an `INGEST`-only one — leaving
that grant unrevokable while the operation reported success by returning `None`.
The sweep is total today because `GrantScope` has two members and a scope is
non-empty; it stays total as the enum grows because it is written over the enum
rather than over its members.

**"The store is the arbiter" is what keeps this free of a check-then-use race.**
ADR-0021 §4's observation that "an `await` between a check and a write is an
interleaving point" applies here as much as it does to the read gate: the
operations run on the hub's one event loop and two clients can be connected at
once. ADR-0097 §10 makes `record` "atomic over the duplicate check, the
live-grant check, the revocation invariants and the append", so a lost race
produces a typed `InvalidGrantError` and never a second live grant. Adding a
pre-check would narrow the window and not close it, while inviting a reader to
believe it had.

**A concurrent revoke that loses is therefore a refusal and not a silent
success**, and that is the right answer: the client re-reads
`grantable_sources` and sees the source is no longer granted, which is what it
wanted.

### 6. The configured location: carried by one response, settling in none

> **Normative.** `GrantableSource.location` is the only place in this system
> that carries a source's configured location. It is computed per call, never
> written to a `SourceGrant`, never returned by `recent_grants`, never written
> to a log record, and never persisted by the hub.

> **Normative.** Where a source's configured location has no UTF-8 encoding,
> `location` is `None`. Enumeration is not refused for it.

> **Normative.** A client renders `location` to the user, and takes an explicit
> act from the user, before it sends `grant`. A client that cannot show the user
> the location does not send `grant`.

**This is ADR-0097 §9a's question answered with "a field on an existing
operation", and the two rejected shapes are the ones §9a named.** A separate
preview operation would be a fifth method whose only content is one string, on a
surface whose size is a contract clause. A confirmation exchange would need
server-side state keyed by a token — the shape ADR-0084 §7 shows costs a table,
an eviction policy and a typed refusal for a token from a previous process
life — bought to carry a value the client is about to be handed anyway.

**Putting it beside a live grant does not make it settle, and that distinction
is §9a's own.** §9a's second clause enumerates where the location may not come
to rest: "not in a log, not on any `SourceGrant`, not in a grant listing, not in
`recent` and not in `export`". Every entry on that list is durable or is a read
of durable state. The grant listing it names is `recent_grants`, which returns
`SourceGrant` records and nothing else. `grantable_sources` is a source listing
computed per call and held by nobody, which is exactly the "transiently, at the
moment of granting" carrier §9a's *first* clause requires some response to be.

**Why passing it at all is admissible is ADR-0097 §9a's argument unchanged**:
reading the user's own configuration back to the user over ADR-0084 §1's `0600`
Unix socket discloses it to nobody.

**The encoding clause is a real case rather than a defensive one.** Linux
pathnames are bytes, and Python surfaces an undecodable one through
`surrogateescape`, so `str(path)` can hold a lone surrogate that `EncodableText`
refuses and ADR-0087's encoder cannot express. Without this clause a deployment
with such a path would find `grantable_sources` raising a `ValidationError` from
inside the operation — enumeration broken by a path the user cannot see and did
not ask about. Degrading to `None` costs the disclosure for that one source and
keeps the surface working, which is ADR-0096 §4's single-absence treatment
applied to a value rather than to a facet.

**The third clause is an obligation the hub cannot enforce, and saying so is
part of stating it.** Nothing on the wire distinguishes a client that rendered
the location from one that did not; ADR-0098 §5's discipline is that a bound
this system cannot obtain is not a weaker rule but an unenforceable one. What
the hub enforces is that the value is *available* and that it settles nowhere.
What the clause obliges is the client, and it is testable in the client's own
tests.

**"Does not send `grant`" rather than "prompts on a terminal" is deliberate.**
The property is that the user saw what they are authorising; the mechanism is
the client's. Stated as a property it also answers the case a TTY test would
get wrong — a spoke with no display — by refusing rather than by granting
unseen, which is ADR-0097 §8's posture: nothing mints a grant from what is
already configured, and a grant nobody was shown is one step from that.

### 7. Where the operations live, and who opens the store

> **Normative.** The four operations are implemented in `orchestration`, in one
> object that holds the `SourceGrantStore`, the declared identities and
> configured locations of the readers the composition root built, an id factory
> and a clock. `Engine` delegates to it. No other object in the system holds a
> `SourceGrantStore`.

> **Normative.** `build_engine` opens the grant store, under `Settings.data_dir`
> and owner-only, and passes the same object twice: as a `SourceGrantStore` to
> the grant operations and as a `SourceGrants` to every driver. Its `grants`
> parameter is removed. No production path may build an engine with the store
> unopened.

> **Normative.** The identities and locations the grant operations hold are
> supplied by the composition root, each identity read from the reader object it
> built. Entries are keyed by declared identity and deduplicated, so several
> instances of one source contribute one entry. No member is added to `Reader`,
> and no component reads a source's identity from anything but a `Reader`.

**`orchestration` is forced rather than chosen.** The operations are
`AssistantEngine` methods (§1), `AssistantEngine` is provided by `orchestration`
and consumed by `interfaces` (ADR-0085 §1), and `service/` holds no engine
method — `Listener` is handed an `AssistantEngine` and `wire/server.py`
dispatches onto it. There is nowhere else for them to be.

**Holding the readers by injection is what makes ADR-0097 §9's check
expressible.** ADR-0093 §2 forbids any subsystem importing the reader package,
and `orchestration` does not import it either: it names the `Reader` Protocol
from `core/protocols.py` and receives instances, which is golden rule 1 and is
what `IngestionStage` already does. So the check lives at the one place that can
see both the store and the identities, and the store stays unable to know either
— which is the placement ADR-0097 §9 argued for and §10 excluded from the
store's conformance suite.

**`build_engine` opens the store, and #684's third checkbox reads otherwise.**
That checkbox assigns the wiring to "`build_engine`'s caller — the hub, and the
CLI through it", and it is superseded by this clause for two reasons the issue
predates. The CLI is no longer a caller at all: `_open_engine` returns a
`HubEngineClient` and ADR-0084 §6's `interfaces → app` contract makes building
an engine there a build failure. And every other Tier 1 store in this system is
opened by `build_engine` — the memory store, the audit trail, the plan store,
the conversation store and the deferral queue all appear in its `closers` list —
so putting the sixth somewhere else would be a second wiring convention bought
for nothing.

**It does not make the composition root a "holder" in ADR-0097 §9's sense.**
§9's clause is about which *component* may record a grant, and ADR-0097 §3
already contemplates exactly this wiring in its own words: "Structural typing
means the concrete store satisfies `SourceGrants`, so a composition root passes
one object to both; what the driver cannot do is *name* `record`." The narrowing
is the annotation on the driver's constructor, and it is unchanged.

**Removing the parameter rather than defaulting it is the point.** A parameter
whose production caller never fills it is exactly the state #684 records, and a
default that silently wires nothing is how a configured reader came to be
unreachable without anything failing. After this, an engine either has a grant
store or does not build.

**A source that is not configured is not grantable, and that is two acts working
as ADR-0093 §7 intended.** `build_engine` builds no calendar reader when
`calendar_reader_path` is unset, so `grantable_sources` returns nothing for it
and `grant` refuses. Configuration says where; the grant says whether. Neither
can be mistaken for the other, which is ADR-0097's own Consequences.

### 8. The four prohibitions, and the two that the import graph already holds

> **Normative.** No `ToolDefinition` binds any of the four operations, no plan
> step may reach one, and no model-authored value may become an argument to
> `grant` or `revoke`. A grant is created only by an explicit user act through a
> client (ADR-0097 §1).

> **Normative.** This surface adds no `Settings` field and defines no file the
> user is asked to edit.

**Two of ADR-0097 §9's four prohibitions are held mechanically, and it is worth
recording which.** "Never a tool a model may invoke" and "never a step a plan
may execute" both reduce to the same question — can anything a model steers
reach an `AssistantEngine` method? — and the answer is no by the boundaries
`lint-imports` already enforces: `tools/` is a subsystem, subsystems never
import `orchestration`, and subsystems never import one another, so a tool
implementation can reach neither the engine nor `permissions/`. The clause is
written anyway, because it is the load-bearing one and because a boundary that
happens to hold is not the same as an obligation that is stated: ADR-0005 §3's
"The model proposes; a deterministic policy disposes" is what would be inverted,
and ADR-0098 §3 rules that imperative text inside ingested content is data and
never an instruction.

**The other two are held by construction and are restated for completeness.**
ADR-0097 §10 already ruled that "No new `Settings` figure is owed, which is a
consequence of §8 rather than an omission: a grant has no configuration", and
nothing in the four operations reads or writes a file the user edits.

### 9. Revocation, a read in flight, and what a client may say about it

> **Normative.** `revoke` returns when the revoking record is durably appended.
> It does not wait for, cancel, or report a read already in flight, and no
> client may present a revocation as having stopped one.

**This is ADR-0097 §5a's boundary restated where a user reads it.** §5a is
explicit that the gate guarantees every read is "authorised at the instant it
starts" and that it is "**not** a guarantee that no byte of a source is read
after a revocation is recorded: a read already in flight completes". The residual
is bounded to at most one already-started read per source, everything it
produces is discarded, and §5a records that it has no duration bound because
ADR-0093 §7's deadline abandons a stalled worker rather than ending it.

**A client is where that boundary would be overstated**, because "your calendar
is no longer being read" is the sentence a person writes. What is true is that
no *further* read starts and nothing an in-flight read produces is used, and a
surface that promised more would be making a claim the corpus explicitly
declines to make.

**The `None` return is not silence about this.** `revoke` returning `None` means
the source had no live grant at the moment the operation ran; it says nothing
about reads, and a client that rendered it as "nothing was happening" would be
inventing the same overclaim from the other side.

### 10. The frame, the reserve, and the paging convention

ADR-0085 §8c bounds the whole serialised payload at `hub_max_frame_bytes - 512`,
which `Settings` defaults to 16 MiB with a floor of 1024 bytes (ADR-0085 §8d).
The arithmetic is stated because §8f states it for the belief page and because
the answers differ between these four.

- **`grant` and `revoke` fit the floor.** A `SourceGrant` encodes to on the
  order of 150 to 200 bytes — two identifiers, a short declared source, at most
  two enum values and an instant, in ADR-0087 §2's forms — against the 512-byte
  payload budget a 1024-byte frame leaves. So a user can grant and withdraw
  consent on any frame size the configuration admits, which is the property
  worth having.
- **`recent_grants` is bounded by `limit` exactly as the other paging methods
  are**, and busts a 1024-byte frame at the default page for the same reason
  they do. ADR-0085 §8e's answer applies unchanged: a declared
  `OversizedValueError`, whose `field` is `None` because the payload is a bare
  array.
- **`grantable_sources` grows with the number of held readers and with path
  length**, and the path is the only unbounded factor. With the tree's one
  source it is one row; at the 1024-byte floor a long configured path can exceed
  the budget, and the declared failure is the answer there too.

> **Normative.** The lane that introduces a source registry (ADR-0093 §11) owes
> a re-derivation of `grantable_sources`' worst case in the same change, because
> its payload grows with the number of held readers and this ADR bounds it only
> at the count the tree has.

**`recent_grants` takes `limit` and no `offset`, which departs from the four
existing paging signatures deliberately.** `SourceGrantStore.recent` has no
offset (ADR-0097 §10), so an `offset` here would be either a store change this
ADR does not own or an engine-side over-fetch-and-slice — a paging surface that
lies about its cost, and one whose cost grows with the page it is skipping. A
keyword-only `offset` is additive the day the store gains one.

> **Normative.** `recent_grants` refuses a `limit` that is not strictly
> positive, locally and before any I/O, in every implementation.

**Stated because the two contracts disagree about zero.** ADR-0085 §9 admits a
page argument in `[0, 2**63)` and `SourceGrantStore.recent` requires a strictly
positive `limit`, so `recent_grants(limit=0)` is well-formed under the surface
rule and refused by the store. Refusing it locally in both implementations is
ADR-0085 §9's own clause — "so both implementations refuse the same values
without a round trip and neither is silently more permissive" — applied to the
one argument where the surface's range and the store's do not coincide.

### 11. Auditing: answered by ADR-0097 §4, and #675's bullet is stale

**#675's lane-3 second bullet asks "whether granting and revoking are audited,
and where those records sit relative to `AuditTrail`". It is not an open
question, and this ADR records that rather than re-deciding it.** ADR-0097 §4
answers both halves in ratified text. On the first: "This answers 'are granting
and revoking audited' by construction rather than by adding a log. The record
*is* the audit record: a store in which the only writes are appends, in which
revocation is an append, and in which nothing may be edited or selectively
removed, cannot hold a history that differs from what happened." On the second,
under "Why not record grants in the existing `AuditTrail`, which is the obvious
reuse": `PermissionDecision.tool` is a required `ToolDefinition`, a grant has no
declaration, and recording one would mean "putting a fabricated record into the
one store whose entire premise is that its records are not fabricated". It is
listed again in ADR-0097's Alternatives considered.

> **Normative.** No grant or revocation is written to an `AuditTrail`, and no
> `PermissionDecision` is synthesised for one. `recent_grants` is the surface
> that discharges ADR-0097 §4's audit property.

**The bullet is older than the answer**, which is the ordinary way an issue goes
stale: #675 was written to dispatch the lane, ADR-0097 was ratified with §4 in
it, and nothing edited the issue. Recording it here rather than silently
skipping it is what stops the next reader re-deriving it — and it is the one
place where following the brief would have produced a second, weaker decision
beside a ratified one.

### 12. What the implementing lanes owe

**The contract lane**, as one change (`CONTRIBUTING.md` → "Adding a Protocol",
read as the Protocol *change* it is rather than a new triad):

1. The four methods on `AssistantEngine`, `GrantableSource` in `core/types.py`,
   and `UngrantableSourceError` in `core/errors.py`. The `AssistantEngine`
   docstring's "all fifteen methods" becomes nineteen, `core/types.py`'s
   promoted-surface comment's "twenty-four types" becomes twenty-five, and
   `wire/surface.py`'s "fifteen methods and twenty-five parameters" becomes
   nineteen and twenty-nine.
2. **The `AssistantEngine` conformance suite gains a clause per ruling above
   that a store cannot exhibit**, which is the whole of §4, §5 and §10's
   local-refusal clause: an inadmissible `source` raises
   `UngrantableSourceError` and constructs nothing; a `revoke` naming a value no
   reader declares is not refused for that; `grant` on a source with a live
   grant raises `InvalidGrantError`; `revoke` with no live grant returns `None`;
   a revocation transcribes the revoked grant's `source` and `scope`; an
   `INGEST`-only grant is revocable; `recent_grants` refuses a non-positive
   `limit` before any I/O; and `GrantableSource.location` is absent rather than
   fatal for a location with no UTF-8 encoding.
3. **The canonical fake gains the four methods**, scriptable to hold grantable
   sources with and without a location and with and without a live grant, so a
   client's own refusal paths are reachable from a test.
4. **`wire/` needs no change.** `METHODS` is derived from the Protocol,
   arguments and results are validated from the annotations, and an error code
   is the exception class's own name resolved over `core.errors`. This is
   recorded so the lane does not go looking for a table to update, and so a
   reviewer can check the claim.

**The wiring lane** (#684): `build_engine` opens the store and passes one object
to both seams, its `grants` parameter goes, and the grant operations are
constructed with the identities and locations of the readers it built.

**The client lane**: the CLI commands behind the four operations — illustratively
`assistant sources`, `assistant grant`, `assistant revoke` and
`assistant grants`, spellings the lane's under ADR-0073 §1's form — with §6's
third clause as a client-side test.

> **Normative.** The grant store is the **sixth** SQLite database under
> `Settings.data_dir`. The lane that opens it corrects every live claim in `src/`
> and `tests/` that this tree holds five stores, in the same change.

**The sites are enumerated because a count claim fails silently.** At `9f1832a`
the claim appears in seven modules under `src/` — `core/config.py`'s `data_dir`
field description, `interfaces/cli.py`'s `_open_engine`, `memory/sqlite_store.py`'s
module docstring, `orchestration/engine.py`'s `Engine._drain` prose about ADR-0054,
`service/datadir.py` (its module docstring and `_check_leaf`'s message),
`service/lock.py`, and `wire/address.py` — and in three test modules,
`tests/service/test_datadir.py`, `tests/service/test_hub.py` and
`tests/wire/test_address.py`. `docs/roadmap.md`
carries it too and is the coordinator's. The same figure in ADR-0042, ADR-0083,
ADR-0084 and ADR-0085 is **not** corrected: an ADR is dated, so a count in one
is history and stays correct as history (`CONTRIBUTING.md` → "No state claims in
living documents", whose ADR exemption says so in as many words).

**ADR-0083's exclusivity needs nothing.** The sixth database lives inside the
directory the instance lock already covers, is opened by the same process, and
is closed in the same ordered shutdown; ruling 4's decision is ownership and
exclusivity, and the sixth store obeys it.

### 13. This ADR classified under ADR-0070 §1 and ADR-0082 §1

**It amends nothing and supersedes nothing.** ADR-0082 §1 requires the judgement
in this ADR's text, clause by clause, against ADR-0070 §1's test: *would a
reader holding only the earlier ADR now act differently, or read one of its
clauses more widely than it now holds?* Applied to the six places where the
opposite reading is available.

**ADR-0085 §1's "and nothing else" — not owed, and this is the closest of the
six.** §1 reads "**We will add one Protocol, `AssistantEngine`, to
`core/protocols.py`**, carrying the fifteen request methods below and nothing
else."

*The case for a record, at its strongest*: unlike an incomplete signature, "and
nothing else" is an **exclusion**, and after this ADR the Protocol carries
nineteen. An exclusion that no longer holds looks false rather than incomplete,
which is the distinction ADR-0101 §11 leaned on when it ruled ADR-0007 §1's
signature block merely incomplete.

*The case against, which governs.* Three showings, and each is sufficient.

First, **what the exclusion excludes is named in the paragraphs it introduces**,
and it is lifecycle: §1's very next paragraph is "**Lifecycle is off the
surface.** `start()` and `aclose()` stay on the concrete class the composition
root builds", and its Context's "The engine's surface is fifteen methods, not
nineteen" is a correction of ADR-0084 §5's estimate. The sentence is an account
of *what ADR-0085 promotes*, made against two live alternatives — promoting
lifecycle, and promoting the tree's larger public surface — and both remain
excluded. Nothing in ADR-0085 says the set may not later grow, and a reader
holding only ADR-0085 is told what that document promoted, which stays exactly
true of that document.

Second, **the corpus has already ratified that a later ADR adds to this
Protocol, and did so in the document this one discharges.** ADR-0097 §9's last
clause routes these signatures to "their own contract ADR", and ADR-0097 §11
classifies that routing against ADR-0085 itself, concluding: "No method is added
to `AssistantEngine` here, and §9 routes **the addition** through its own ADR
rather than through this one. Nothing in its closed graph moves." Were "and
nothing else" a bar on later methods, ADR-0097 §9 would have been ratifying an
instruction to breach ADR-0085 and its own §11 would have had to record a
supersession. It did not, and it was reviewed by both lenses.

Third, **"one closed graph" is the title's claim, and it is about types rather
than about the method count.** ADR-0085 §5 is where the phrase is cashed out —
"Where the walk stops, and why that is a closed boundary and not a hopeful one …
The walk terminates because `core` is already closed under its own field graph"
— and §3 above shows the walk from `GrantableSource` terminating in `core` on
every branch. The property the title names is *preserved*, not moved.

**Addition.** A reviewer who still reads the test the other way is invited to
name the sentence of ADR-0085 that becomes false or over-wide, which is the
showing ADR-0082 §1 requires — and to weigh it against ADR-0086 §6, which added
`get_many` to a Protocol ADR-0007 §1 had enumerated and recorded nothing, a
treatment ADR-0101 §11 examined and upheld.

**ADR-0085 §5's closure and §8b's reserve — not owed, and both are checked
rather than asserted.** The closure walk terminates in `core` after this
addition (§3). §8b's envelope worst case is computed from the longest method
name, `interrupted_questions` at 21 bytes, and the longest name added here is
`grantable_sources` at 17, so the 110-byte figure and the 512-byte reserve are
untouched. §8c's payload bound is applied, not changed (§10).

**ADR-0083 ruling 4's "the five SQLite databases" — not owed.** The decision is
that the hub owns them exclusively and that the API is the only door, and both
are obeyed by a sixth store opened by the same process inside the same locked
directory (§12). The number is a dated observation in a dated document, which
`CONTRIBUTING.md` exempts by name. A reader holding only ADR-0083 acts
identically: they keep every database in that directory under one process behind
one door. Nor is this ADR the change that creates the sixth store — ADR-0097
§4's clause put it under `Settings.data_dir` — so even on the contrary reading
the falsifying decision is not here, which is where ADR-0070 §1 puts a record.

**ADR-0097 §9 and §9a — not owed.** §9's last clause names this ADR and defers
these signatures to it; §9a names it again for the location's carrier and says
in as many words that "the shape that carries it is the other lane's".
Discharging a deferral by the route the deferral itself specified is the
mechanism working (ADR-0100 §11), and every sentence of both stays true. §4's
added admission condition narrows the grantable set under a clause §9 states as
a necessary condition, so §9's sentence stays true as written; §4's revocation
clause adds a rule where §9 stated none, since §9's admission clause is written
about "the grant operation" and §9's own reasoning — a grant whose reader
disappears "is history and stays readable" — is what this ADR follows rather
than departs from.

**ADR-0097 §10's error set — not owed.** §10 enumerates three classes and states
what each means; this ADR adds a fourth for a refusal none of the three
describes, which is an addition beside them rather than a re-reading of any.
`GrantError`, `InvalidGrantError` and `SourceNotGrantedError` keep their stated
subjects exactly, and §10's reasoning for one `InvalidGrantError` rather than
three — "because the caller's recourse is identical in all three" — is the
reasoning this ADR applies to keep its own new class single rather than split.
Likewise §10's "Nothing else. No change to … `AssistantEngine`" is a statement
about what *ADR-0097* changes, immediately beside §9's clause routing the
`AssistantEngine` change here; reading it as a bar would put the same document
in contradiction with itself two sections apart.

**ADR-0084 §5's four-change sequence — not owed.** This ADR is a contract
decision in §5's step-2 territory arriving after steps 3 and 4 landed, which is
ADR-0087 §6's own situation stated from the other side: it "declines to order
itself against" its neighbour and records that neither is a prerequisite of the
other. This ADR enumerates no sequence and states no position, so §5's
enumeration of changes is untouched. What it does state is a **prerequisite**,
in the form ADR-0084 §11 and ADR-0085 §11a both use: the wiring lane is not
ready before this decision merges. A prerequisite is a fact about a lane's
readiness, not a claim about when anything merges, and it orders no ADRs.

**No ADR's decision text, header or `Status` line is edited by this lane**, and
neither `VISION.md`, `CLAUDE.md`, `CONTRIBUTING.md` nor `docs/roadmap.md` is
touched.

### 14. Deferred, by name, each with the condition that fires it

- **A grant export and a wholesale grant erasure.** `SourceGrantStore.export`
  and `clear` exist and reach no surface. ADR-0101 §7 records that ADR-0004 §6's
  export right has **no user surface at all** and defers the whole question with
  two firing conditions; this deferral rides on that one rather than inventing a
  second answer for one store. Fires with the lane that gives the export right a
  surface — which owes the grant store's rows in the same change, since ADR-0021
  §4's "the user may burn the book" applies to this book too.
- **`offset` on `recent_grants`.** Fires when `SourceGrantStore` gains an
  offset, and lands as a keyword-only argument under ADR-0008 §1's additive
  pattern (§10).
- **Reporting liveness for a source no held reader declares.** A grant whose
  reader has been unconfigured is visible in `recent_grants` and is revocable
  (§4), and no operation reports whether it is live. ADR-0097 §9 rules the state
  itself benign — "the record is history and stays readable … Nothing needs to
  reconcile the two" — and the user's remedy does not need the answer, since
  `revoke` on it either withdraws it or returns `None` harmlessly. Fires with
  ADR-0093 §11's source registry, or earlier with the first deployment that
  removes a reader while a grant stands and needs to say so.
- **A two-step grant exchange on the wire**, so that a client which cannot
  render a path can still discharge §6's third clause. Refused today as
  server-side state bought for one string. Fires with the first client that
  cannot show the user a location — a voice spoke under ADR-0094 is the nearest
  candidate — because §6's clause then refuses every grant from it rather than
  degrading.
- **A grant naming anything but a source**, and **who granted**. ADR-0097 §12's,
  unchanged; the second is #691's and ADR-0099 §1's, and nothing on this surface
  carries a principal.
- **Everything ADR-0097 §12 defers**, unchanged and not re-listed.

## Consequences

- **Leg 6's exit test becomes reachable by a user rather than by a fake.** With
  the four operations and §7's wiring, a person can grant a configured calendar
  and the drivers that #681 gated on `live()` start passing their gate. #684
  closes.
- **The engine surface grows by a quarter and the wire by nothing.** Fifteen
  methods become nineteen and twenty-four promoted types become twenty-five; the
  `wire` package needs no edit at all, because `METHODS`, the argument and
  result adapters and the error code are all derived from the contract. That
  asymmetry is the payoff of two decisions made earlier, and it is worth
  recording as evidence they were right.
- **A grant is chosen rather than typed, and the store gains no free-text
  route.** The admissible set is the set of declared constants, which is
  ADR-0093 §7's property one layer up, and no path or address can enter a
  durable, exportable, user-rendered record.
- **A user can always withdraw.** Granting is refused for a dozen reasons;
  revoking is refused for none of them (§4), fits the smallest frame the
  configuration admits (§10), and never waits on the read it is withdrawing
  (§9).
- **The data directory holds six databases, and ten modules say five.** Named in
  §12 so the correction is a checklist item rather than a discovery.
- **What gets harder:** four methods are four conformance-suite obligations,
  four fake behaviours and four more shapes every future spoke must implement to
  be substitutable; and `build_engine` gains a store it must open, so a test
  that built an engine with a fake `SourceGrants` now gets a real one under its
  temporary data directory. Both are the cost of the surface being real.
- **One residual is named rather than closed.** The hub cannot tell whether a
  client showed the user what it was granting (§6). What is enforced is that the
  value is available and settles nowhere; the rest is the client's, tested in
  the client's tests, and stated as unenforceable rather than claimed.
- **Revisit when** a second source exists — ADR-0093 §11's registry, which owes
  §10's re-derivation and §14's liveness question in the same change — or when a
  client arrives that cannot render a location.

## Alternatives considered

- **A single `set_grant(source, scope)` that revokes and re-grants in one act.**
  Rejected in §1: ADR-0097 §2 already ruled that changing a scope is a
  revocation followed by a new grant "and both records are kept", and a compound
  operation would either hide the two records behind one word or invent a third
  act the store has no shape for.
- **`revoke(grant_id)` rather than `revoke(source)`.** Rejected in §5. Keying on
  the id forces a client to read the grant first, which is a check-then-use
  window on the one operation that must not have one, and it puts the
  transcription of `source` and `scope` — an invariant the store verifies — in
  the client's hands. ADR-0097 §10 also declined `get(id)` on the store, so
  there is no way to resolve an id to a record anyway.
- **The client constructs and sends a whole `SourceGrant`.** Rejected in §5 on
  three grounds: a client clock backdating a user act, a client minting ids into
  a write-once store, and a client setting `revokes` to a record it never read.
- **A separate `source_location(source)` operation, or a confirmation exchange
  with a token.** Rejected in §6. Both are shapes ADR-0097 §9a explicitly left
  open, and each costs more than the field does: a fifth method on a surface
  whose size is a contract clause, or server-side state with an eviction policy
  and a typed refusal for a token from a previous process life (ADR-0084 §7).
- **`grantable: bool` on `GrantableSource`, so an inadmissible reader is listed
  rather than omitted.** Rejected in §3 as surface with no consumer: a
  non-canonical declared name is a defect in a reader, not a state a user can
  act on. The diagnosis goes to the operator log, where ADR-0097 §8's refusal
  line already goes.
- **Let a client compute liveness from `recent_grants`, and drop
  `GrantableSource.live`.** Rejected in §3, and it is the one rejection with a
  concrete failure rather than a principle: ADR-0097 §4 permits a revocation
  timestamped before the grant it revokes, `recent` orders by `decided_at`, so a
  clock correction puts the revoking record outside the page and the client
  reports a withdrawn grant as live.
- **Put the grant operations in `service/` rather than `orchestration`.**
  Rejected in §7: they must be `AssistantEngine` methods to be addressable over
  the socket, and `AssistantEngine` is provided by `orchestration` (ADR-0085
  §1). `service/` holds the listener, not the surface.
- **Keep `build_engine`'s `grants` parameter and let the hub fill it.**
  Rejected in §7. The CLI is no longer a caller, every other Tier 1 store is
  opened by `build_engine`, and a parameter no production caller fills is the
  precise state #684 exists to record.
- **Reuse `InvalidGrantError` for an inadmissible source.** Rejected in §4 and
  §13: ADR-0097 §10 scopes that class to "the store **refused** the record", and
  the admission check refuses before a record exists. It would also give a
  caller a recourse that does not apply — construct a different record — when
  the actual remedy is to pick a different source.
- **Record grants in the `AuditTrail` as well, so one store answers "what has
  the user permitted".** Rejected in ADR-0097 §4 and not reopened here (§11).
