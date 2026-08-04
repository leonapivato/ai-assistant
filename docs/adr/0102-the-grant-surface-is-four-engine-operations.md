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
  transcribed, so four methods and one error class cost the wire's server half
  and its error registry nothing and cost its client four thin methods (§12);
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
class cost the wire's server half and its error registry nothing. What they do
cost is four methods on `HubEngineClient`, which implements the fifteen
explicitly, and that cost is unavoidable rather than overlooked: a client is the
second implementation ADR-0042 §1's trigger named, and `tests/wire/test_client_contract.py`
binds it to the shared `AssistantEngineContract`, so a Protocol method it lacks
is a red gate rather than a deferrable follow-up. The budget this ADR does not
have to spend is on plumbing.

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
keyword-only. `NonBlankEncodableText`, `EncodableText` and `DEFAULT_PAGE_SIZE`
are `core/types.py`'s existing names.

```python
async def grantable_sources(self) -> tuple[GrantableSource, ...]: ...


async def grant(
    self, source: NonBlankEncodableText, *, scope: Sequence[GrantScope]
) -> SourceGrant: ...


async def revoke(self, source: NonBlankEncodableText) -> SourceGrant | None: ...


async def recent_grants(
    self, *, limit: int = DEFAULT_PAGE_SIZE
) -> tuple[SourceGrant, ...]: ...
```

**Docstrings are omitted here and are not optional in the Protocol**, exactly as
ADR-0085 §3 states for its own block.

> **Normative.** The `source` argument of `grant` and `revoke` is
> `NonBlankEncodableText`, which rejects a blank value and normalises nothing.
> No implementation of these operations may strip, case-fold or otherwise
> normalise a caller-supplied `source` at any point before it is compared.

**`Identifier` is the wrong type here, and it is the type an author reaches for
first.** ADR-0085 §3c rules that "Every id argument is `Identifier`", and a
source name looks like an id. But `Identifier`'s validator "Reject[s] a blank
identifier, **returning it stripped**" — ADR-0097 §9 quotes that line for its own
reasons — and `wire/surface.py`'s `argument_adapter` validates each argument
against the Protocol's own annotation before `wire/server.py` dispatches. So a
wire call `grant(" calendar ")` would arrive at the operation as `"calendar"`
and be **matched** against a held reader named `"calendar"`, where ADR-0097 §10
requires in as many words that "a source differing from a held reader's `name`
only by surrounding whitespace is refused rather than matched". The normalisation
would happen one layer below the comparison, where no clause about the
comparison can reach it, and the in-process engine — which is handed the string
unvalidated — would refuse the same call the wire accepted. That is ADR-0084
§4's substitutability failure arriving through an annotation.

**ADR-0085 §3c is applied at its stated scope rather than stretched.** Its
subject is the *id* arguments — `record_id`, `question_id`, `conversation_id` —
and its argument is that a client "must be comparing values of the same type" as
the field it addresses. A `source` is not one of those: it is a value whose whole
contract is exact comparison against a declared constant, and the strengthening
§3c buys for an id is the exact property that breaks it here.

**`NonBlankEncodableText` is the type the corpus already made for this, and it
was made for the same hazard one field away.** ADR-0096 §2 needed "the rejecting
half of `_non_blank` without its normalising half" so that a facet's `source`
stays a faithful copy of a reading's, and drew the general rule from it: "a
faithful copy takes the type of the field it copies, and may tighten only in ways
that reject", because "Tightening by *normalising* is how two spellings of one
value drift, silently, until something compares them." A grant's `source`
argument is compared rather than copied, which wants the same property for a
sharper reason.

**The result field stays `Identifier` and nothing about it moves.**
`SourceGrant.source` and `GrantableSource.source` are constructed hub-side from
a reader's declared `name` that §4 has already required to equal its own
`str.strip()`, so the normalising validator is a no-op on every value that can
reach them.

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

#### 2a. The declared failures, and the one new error class

ADR-0085 §9 makes the per-method failures part of the contract, on the ground
that "A Protocol whose methods raise unnamed exceptions is not a contract a
conformance suite can hold anyone to". So they are declared here rather than left
to the lane, and `OversizedValueError` is assumed throughout in §9's own form —
it is declared by every method on this surface and is not repeated per row.

> **Normative.** The four operations declare exactly these failures, plus
> `OversizedValueError` on every one of them:
>
> | Method | Declares |
> | --- | --- |
> | `grantable_sources` | `GrantError` |
> | `grant` | `ValueError`, `UngrantableSourceError`, `GrantError`, `InvalidGrantError` |
> | `revoke` | `ValueError`, `GrantError`, `InvalidGrantError` |
> | `recent_grants` | `ValueError`, `GrantError` |

> **Normative.** `UngrantableSourceError` is a direct subclass of
> `AssistantError` in `core/errors.py`. It defines no `__init__` and carries a
> message and no structured state, and its message names no caller-supplied
> value and no filesystem path (§4).

**What each declaration covers.** `GrantError` is ADR-0097 §10's — the store
could not be read or written — and every operation here reads or writes it.
`InvalidGrantError` is also §10's, and reaches `grant` when the store refuses a
second live grant or a duplicate id, and `revoke` when the record it built lost a
race to another revocation (§5). `ValueError` is ADR-0085 §9's, kept as a caller
programming error rather than a condition of the system: a blank or unwritable
`source` on `grant` and `revoke`, an empty or duplicated `scope` on `grant`, and
a `limit` that is not strictly positive on `recent_grants` (§10). ADR-0085 §9's
clause applies to all of them unchanged — an implementation refuses these
locally, before any I/O, so both implementations refuse the same values without a
round trip.

**One new class rather than two, on ADR-0097 §10's own reasoning.** §10 declined
to split `InvalidGrantError` three ways "because the caller's recourse is
identical in all three — read the store and construct a different record". The
same test decides this one: whether no held reader declares the value or a held
reader declares it inadmissibly, the caller's recourse is to call
`grantable_sources` and pick from what it returns.

**Not a subclass of `GrantError`, and not `SourceNotGrantedError`.**
`GrantError`'s stated subject is a store that could not be read or written, and
this refusal never touches the store. `SourceNotGrantedError` is ADR-0097 §10's
driver-side refusal — "the user has not granted this source for this use" — and a
caller that could not tell it from "there is no such source" is one that will
tell a user to grant something the hub cannot offer. The names are also
deliberately not near-neighbours: `UngrantableSourceError` rather than a second
`SourceNotGrant*Error`, so the two are not confusable at a glance.

**Carrying a message and nothing else is what makes it survive the wire.**
`wire/errors.py` uses "the exception type's own class name" as the error code and
reconstructs by resolving that name over `core.errors`, refusing rather than
guessing where "the hub's details do not fit its own constructor". A class with
no `__init__` reconstructs from its message alone, which ADR-0085 §10a names as
the shape that always round-trips — and it is the shape §4's refusal rule wants
anyway, since there is nothing this refusal may carry.

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

> **Normative.** Argument validation and admission are two steps in that order,
> and neither substitutes for the other. §2's `NonBlankEncodableText` refuses a
> blank or unwritable `source` as `ValueError` (§2a), on `grant` and `revoke`
> alike, before either applies any rule in this section; every clause below
> governs only a `source` that has passed it.

> **Normative.** `grant` admits a validated `source` **only** when it equals,
> exactly, the declared `name` of a reader the hub holds **and** that name
> validates as `Identifier` and equals its own `str.strip()`. Any other
> validated value raises `UngrantableSourceError`, no `SourceGrant` is
> constructed from it, and the value reaches no store and no log.

> **Normative.** `revoke` applies no admission check. Beyond the argument
> validation above, a revocation is refused for no property of the source's
> name, and in particular is not refused because no reader currently declares
> it.

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

> **Normative.** `GrantableSource.location` is `None` only where the source has
> **no** configured location at all.

> **Normative.** A source whose configured location exists and has no UTF-8
> encoding is **not grantable**: `grantable_sources` omits it, `grant` refuses it
> with `UngrantableSourceError`, and enumeration is not refused for it. The
> refusal and the operator log line name the reader and carry no path (§4).

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

**The encoding clauses are a real case rather than a defensive one.** Linux
pathnames are bytes, and Python surfaces an undecodable one through
`surrogateescape`, so `str(path)` can hold a lone surrogate that `EncodableText`
refuses and ADR-0087's encoder cannot express. Without a rule a deployment with
such a path would find `grantable_sources` raising a `ValidationError` from
inside the operation — enumeration broken by a path the user cannot see and did
not ask about.

**Refusing grantability is the answer, and degrading `location` to `None` was
the wrong one.** An earlier draft of this section did exactly that, and it made
the two halves of §9a contradict each other: the source would be listed as
grantable while no conforming client could ever grant it under the third clause
below, and a client that ignored that clause could mint precisely the uninformed
grant §9a exists to prevent. So the two cases are separated. **No configured
location at all** makes §9a's obligation vacuous — there is nothing to show — and
the source is grantable with `location` absent. **A configured location that
cannot be shown** is the hazard itself, and it fails closed: nothing is offered
and nothing is granted, which is ADR-0097 §8's posture rather than ADR-0096 §4's
single-absence one. The remedy is an operator act on the operator's own
filesystem, and the log line is what points at it.

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
> built, and entries are keyed by that identity and deduplicated — so several
> instances of one source contribute one entry.

> **Normative.** Several readers declaring one identity carry one configured
> location. A composition supplying two that differ is a configuration error and
> the engine does not build.

> **Normative.** No member is added to `Reader`, and no component reads a
> source's identity from anything but a `Reader`.

**The equal-locations clause is what keeps deduplication honest, and the obvious
alternative is unavailable.** `build_engine` builds two `CalendarReader`
instances today — ADR-0096 §5 requires the separate instances, since ADR-0093 §7
bounds a reader at one outstanding worker per instance — and both are configured
from `calendar_reader_path`, so they agree by construction. Nothing said so,
though, and two conforming readers named `calendar` at different paths would
produce one entry showing one location while a grant on that identity authorised
reads of both, which is §6's informed-consent property defeated by a wiring
detail. Refusing to build is the cheap half of the fix. Giving each instance its
own grantable identity is the other candidate and it is **foreclosed**: ADR-0093
§7 makes an identity declared rather than configured, and ADR-0097 §9a places a
named precondition on ADR-0093 §11's registry lane that "A second instance of one
source type may not become grantable before that rule exists." So the only move
available here is to refuse the state, and §14 leaves the rest where that
precondition already put it.

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

- **`grant` and `revoke` fit the floor on the tree's own figures, and that is a
  measurement rather than a guarantee.** A `SourceGrant` whose `source` is
  `CALENDAR_READER_NAME` and whose ids are UUID strings encodes to on the order
  of 150 to 200 bytes — two identifiers, a short declared source, at most two
  enum values and an instant, in ADR-0087 §2's forms — against the 512-byte
  payload budget a 1024-byte frame leaves. So neither *result* is what limits
  granting on any frame size the configuration admits — but the third bullet
  below is, and the claim is confined to the results for that reason.

  **It is not promised for every conforming input, and stating it as a promise
  would be false.** `Identifier` and `DurableIdentifier` carry no maximum
  length, so a reader declaring a very long identity or a factory minting a very
  long id produces a valid `SourceGrant` that exceeds the floor. That is
  ADR-0085 §9's own observation about the existing surface — "`Identifier`
  carries no maximum length, so even `forget(record_id=…)` can be handed an
  oversized argument" — and its answer is the one taken here: `OversizedValueError`
  is declared by these two operations like every other (§2a), and no clause in
  this ADR exempts them from ADR-0085 §8c's bound. Bounding either alias is a
  change to a ratified `core` type that this ADR does not own.
- **`recent_grants` is bounded by `limit` exactly as the other paging methods
  are**, and busts a 1024-byte frame at the default page for the same reason
  they do. ADR-0085 §8e's answer applies unchanged: a declared
  `OversizedValueError`, whose `field` is `None` because the payload is a bare
  array.
- **`grantable_sources` grows with the number of held readers and with path
  length**, and the path is the only unbounded factor. With the tree's one
  source it is one row; at the 1024-byte floor a long configured path can exceed
  the budget, and the declared failure is the answer there too.

  **This is the one place a frame size decides whether a source can be granted
  at all, and it is worth stating rather than leaving to be met.**
  `grantable_sources` is the carrier of §6's disclosure, and §6's third clause
  forbids a client that cannot show the location from sending `grant`. So a
  deployment whose configured path does not fit its configured frame has a
  source it can enumerate nothing about and therefore may not grant, even though
  `grant`'s own request and result would fit.

  > **Normative.** A source whose disclosure does not fit the configured frame
  > is not grantable through a conforming client, and no client may grant it by
  > skipping the disclosure. Raising `hub_max_frame_bytes` is the operator's
  > remedy and the only one this ADR offers.

  **The blast radius is the whole response, not the one row.** ADR-0085 §8c
  bounds the payload rather than a value, so an oversized `grantable_sources`
  result refuses the *call*: no source is enumerated, not merely the one with
  the long path. Today that is a distinction without a difference — the tree
  holds one source — and it stops being one the moment a second exists, which is
  a further reason the registry lane owes the re-derivation the clause above
  requires of it.

  **Fail-closed is the right direction here and the alternative is the one §6
  already refused.** Granting without the disclosure is the uninformed grant
  ADR-0097 §9a exists to prevent, arriving through a size limit instead of
  through an encoding; refusing the configuration outright at load would put a
  frame-size arithmetic in `Settings` validation, where it would have to know a
  path length it is not given. What is left is a legible failure with a setting
  that fixes it, and `hub_max_frame_bytes` defaults to 16 MiB — four orders of
  magnitude above any pathname — so the reachable population is an operator who
  deliberately configured the floor.

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

1. The four methods on `AssistantEngine` with §2a's declared failures in their
   docstrings, `GrantableSource` in `core/types.py`, and
   `UngrantableSourceError` in `core/errors.py`. The `AssistantEngine`
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
   `limit` before any I/O; a source whose configured location has no UTF-8
   encoding is neither enumerated nor granted, and enumeration of the others is
   unaffected by it; and a `source` differing from a held reader's `name` only by
   surrounding whitespace is refused rather than matched — written against the
   **wire** implementation as well, since that is the one the argument annotation
   could have normalised (§2).

   > **Normative.** The suite pins §3's second clause with the case that
   > distinguishes a stated liveness from a derived one: a grant recorded at one
   > instant and revoked by a record whose `decided_at` is **earlier** than the
   > grant's leaves `grantable_sources` answering `live=None` for that source,
   > while `recent_grants` still returns both records.

   **That case is the whole of §3's second clause and nothing else reaches
   it.** ADR-0097 §4 permits a revocation timestamped before the grant it
   revokes and derives liveness from `revokes` alone, so an implementation that
   computed `live` by walking a `recent_grants` page ordered by `decided_at`
   would return the revoked grant as live — and would pass every other clause in
   this list, because every other clause is about admission, refusal or paging.
   Written as a required case rather than left to the prose above for the reason
   ADR-0097 §10 required its own fakes to be scriptable: a test that cannot reach
   the code a clause forbids is worse than no test.
3. **The canonical fake gains the four methods**, scriptable to hold grantable
   sources with and without a location and with and without a live grant, so a
   client's own refusal paths are reachable from a test.
4. **Four methods on `HubEngineClient`, in the same change**, each a `_call`
   plus the local refusals ADR-0085 §9 requires — §2a's `ValueError` cases and
   §10's `limit` rule — so the client refuses what the hub would and never sends
   a call it knows is malformed. They land with the Protocol rather than after
   it, because `tests/wire/test_client_contract.py` binds `HubEngineClient` to
   `AssistantEngineContract` and a missing method is a red gate.
5. **Nothing else in `wire/` changes**, and this is recorded so the lane does not
   go looking for a table to update and so a reviewer can check the claim:
   `METHODS` is derived from the Protocol by reflection, arguments and results
   are validated from the annotations, and an error code is the exception
   class's own name resolved over `core.errors`. The server half and the error
   registry are total by construction.

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
- **A revocability guarantee that survives an unbounded source identity.**
  `Identifier` has no maximum length, so `revoke`'s request payload is bounded
  only by the identity a reader declares, and a long enough one exceeds a small
  configured frame (§10). Today the admissible identities are the declared
  constants of the readers the hub holds — one of them, eight bytes — so the
  exposure is an operator declaring a very long name in their own code, whose
  remedy is `hub_max_frame_bytes`. Fires with the first bound on `Identifier`, or
  with ADR-0093 §11's registry, where identities stop being a handful of literals
  a reviewer can read; and closing it means either a length bound on a ratified
  `core` alias or a revocation shape that carries no identity, both of which are
  contract changes this ADR does not own.
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
  wire's server half and its error registry need no edit at all, because
  `METHODS`, the argument and result adapters and the error code are all derived
  from the contract; only `HubEngineClient`, which spells its methods out, gains
  four. That asymmetry is the payoff of two decisions made earlier, and it is
  worth recording as evidence they were right.
- **A grant is chosen rather than typed, and the store gains no free-text
  route.** The admissible set is the set of declared constants, which is
  ADR-0093 §7's property one layer up, and no path or address can enter a
  durable, exportable, user-rendered record.
- **Withdrawal is the operation this surface protects.** Revoking is refused for
  none of the reasons granting is (§4), never waits on the read it is
  withdrawing (§9), and on this tree's figures fits the smallest frame the
  configuration admits (§10). The last is a measurement and not a guarantee:
  `Identifier` carries no maximum length, so a sufficiently long reader identity
  makes a `revoke` request payload exceed a small frame and raise
  `OversizedValueError` like any other. Bounding it is a `core` change this ADR
  does not own, the operator's remedy is `hub_max_frame_bytes`, and §14 records
  what would fire a contract that survives both without one.
- **Granting is asymmetric with withdrawing, and the asymmetry runs the safe
  way.** Withdrawing needs one request and one small result; granting needs the
  disclosure first, so a frame too small to carry a configured path takes the
  whole enumeration down and leaves every source unenumerable and ungrantable
  (§10), while the same frame still lets the user withdraw what they already
  granted. A surface that failed the other way round would be one that could
  take consent it could not give back.
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
- **Degrade `location` to `None` when the configured path has no UTF-8 encoding,
  and grant anyway.** The first draft of §6 did this, and it makes §9a's two
  halves contradict each other: the source is offered while no conforming client
  may grant it, and a client that ignored §6's third clause would mint the
  uninformed grant §9a exists to prevent. Rejected in §6 for a fail-closed
  refusal.
- **Give each configured reader instance its own grantable identity, so two
  same-named readers at two paths are two grants.** Not available rather than
  rejected: ADR-0093 §7 makes an identity declared rather than configured, and
  ADR-0097 §9a places a named precondition on ADR-0093 §11's registry lane that a
  second instance of one source type may not become grantable before that lane
  rules on it. §7 refuses the state instead.
- **Put the grant operations in `service/` rather than `orchestration`.**
  Rejected in §7: they must be `AssistantEngine` methods to be addressable over
  the socket, and `AssistantEngine` is provided by `orchestration` (ADR-0085
  §1). `service/` holds the listener, not the surface.
- **Keep `build_engine`'s `grants` parameter and let the hub fill it.**
  Rejected in §7. The CLI is no longer a caller, every other Tier 1 store is
  opened by `build_engine`, and a parameter no production caller fills is the
  precise state #684 exists to record.
- **Annotate the `source` argument `Identifier`, as every id argument on this
  surface is.** Rejected in §2, and it is the rejection with the sharpest
  mechanism: `Identifier` strips, `wire/surface.py` validates each argument
  against the Protocol's annotation before dispatch, so the wire would silently
  match a source ADR-0097 §10 requires to be refused — and the in-process engine,
  handed the string unvalidated, would refuse what the wire accepted.
- **Reuse `InvalidGrantError` for an inadmissible source.** Rejected in §2a, §4 and
  §13: ADR-0097 §10 scopes that class to "the store **refused** the record", and
  the admission check refuses before a record exists. It would also give a
  caller a recourse that does not apply — construct a different record — when
  the actual remedy is to pick a different source.
- **Record grants in the `AuditTrail` as well, so one store answers "what has
  the user permitted".** Rejected in ADR-0097 §4 and not reopened here (§11).
