# 186. The audit trail reaches the user as a bounded listing and an unbounded export, and a row states what was decided rather than what happened

- Status: Proposed
- Date: 2026-08-23

- **Decides `core/protocols.py` surface.** Two methods on the `AssistantEngine`
  Protocol — one bounded listing, one whole-trail export — with the paging shape,
  the ordering, the transports that carry them and the rendering floor every surface
  that reads them owes. It adds no Protocol, no `core/types.py` model, no enum and no
  error class, and it changes no signature on `AuditTrail`, `ActionPolicy` or any
  other contract. Golden rule 5 and ADR-0015 §5 put it in its own PR, ratified before
  anything implements against it.
- **Required review set: adversarial *and* architecture.** Compelled, not declared:
  `CONTRIBUTING.md` → "Stop when the required reviews are green" makes a change
  contract-surface when it is "the ADR deciding that surface", and §1 below decides
  two members of `core/protocols.py`'s promoted `AssistantEngine`.
- **Supersedes nothing and amends one ADR, by a count rather than by a rule.**
  ADR-0177 §1's third clause calls `learn` "the one operation of the promoted surface
  that is neither in the enumeration above nor the gateway's own". §6 below adds two
  more such operations and states in terms that no browser request resolves to them,
  so every obligation that clause imposes binds unchanged; §13 classifies it and
  places the dated note on the change that makes the count false, which is the
  contract lane rather than this document.
- **Refs:** #1485 (the gap this closes), #1484 (the milestone-23 QA run that found
  it), #1427 (track:world, milestone 24), #1501 (the batch), #1017 (the read-record
  ADR, being decided in parallel — §10), #747 (authorised cloud egress in the trail),
  #108 (the trail's deferred retention). **Filed by this lane:** #1502 (ADR-0004 §6's
  composed export reaches no user either, and `DataExport` has no consumer at all),
  #1503 (the trail bounds rulings, not invocations, and milestone 24's exit wording
  says "egress").

## Context

### What is ruled, and what a user can actually reach

ADR-0021 §4 gives the audit trail five reads. ADR-0184 §5 rules what four of them
answer over a row recorded before ADR-0181 §3 existed: `get`, `recent`, `export` and
`resolution_of` return such a decision carrying an `OriginUnrecordedBinding` "as
history, rather than raising", and ADR-0184 §2 states the value the user is meant to
get from it — "the connected account, every occurrence …, the payload description and
the transport endpoint … and exactly one thing more, that the origin of this call was
never recorded". ADR-0021 §4 states what `export` is for: it "matches
`MemoryStore.export` and `PlanStore.export` and **discharges ADR-0004 §6's
portability obligation for this store**".

#1485 records what the milestone-23 QA run found when it drove those five over a real
`SqliteAuditTrail`: every one of them answers exactly as ruled, **and nothing a user
can drive reaches four of them**. `AuditTrail.get` has one production consumer,
`StepRunner._recorded`, on the resume path. `recent`, `export` and `resolution_of`
have none in `src/`. ADR-0184's own Context says so before the fact — "`resolution_of`,
`recent` and `export` have none in `src/`" — and names the harm as being "to the
contract's own disclosure and portability guarantees and to every surface that will
render history".

So the position this decision starts from is not a defect in any lane. It is a
correct value with no reader. Read at `2ae4f190`: the `AssistantEngine` Protocol
carries thirty-two methods and none of them is about the trail, the command roster runs `version`,
`gateway`, `ask`, `conversations`, … `connection-log`, `device` and touches
`audit.db` nowhere, and `ai-assistant-measures` reads `traces.db`. Milestone 24's
pre-registered exit — "every read of a source and every egress is reconstructible
from the audit trail alone, origin included" — is unmeasurable until something can be
driven to read it.

### There is no export surface anywhere to follow, which is worth knowing before designing one

The obvious move is to copy whatever the other stores' exports do at the user's edge.
They do nothing. `MemoryStore.export` has exactly one caller in `src/` —
`ConversationLifecycle.export`, which composes it with `ConversationStore.export` into
a `DataExport` and is itself called by nothing, in `src/` or in `tests/`. That stage is
ADR-0074 §9's ruling implemented and unreached, and it is filed as #1502 rather than
absorbed here. No `AssistantEngine` method exports anything, no `assistant`
subcommand does, and the CLI's own help text repeatedly tells a user that a record
"stays in your export", or that a deletion removes it from one, for an artifact that
has no producer.

Two consequences follow and both shape the decision below. There is no house pattern
for an export at this surface, so §3 has to decide the shape rather than inherit it.
And the audit trail's export is a **per-store** obligation in ADR-0021 §4's own words,
so it can be discharged for this store without waiting for the composed artifact —
which is exactly the split ADR-0074 §9 already made between a store's own snapshot and
the composition one level up.

### Three things about the transports, read rather than remembered

**The promoted surface is derived, not transcribed.** `wire/surface.METHODS` is built
by reflection over `AssistantEngine`, so a method the Protocol grows is a method the
wire already carries — argument adapters, result adapter and error mapping included.
Nothing under `wire/` has to be edited for a new method; `PROTOCOL_VERSION` has to
move, under ADR-0124 §9's first limb ("any change to the promoted surface's method
set"), and it stands at **11** where ADR-0181's implementation left it.

**One listener restriction exists, and it is not a general one.** `wire/server.py`
holds `CONNECTION_METHODS` — the five connection operations ADR-0151 §13 keeps off
every transport but ADR-0084 §1's loopback socket, "until a ratified decision rules
the credential's hop from an enrolled device to the hub". The module's own comment is
explicit that this is "the one place this module departs from `wire/surface.py`'s
reflection", that the reason is ADR-0151 §1's decision rather than any property of a
signature, and that the discriminator is `admission`, which is `None` on the loopback
listener. Every other promoted method is served on both listeners because admission is
decided **per device** (ADR-0124 §5) and not per method.

**The browser's enumeration is closed and does not grow by reflection.** ADR-0177 §1
admits "exactly these **thirty** operations of the promoted engine surface and no
others", with `next_notification` the gateway's own and `learn` left out by name. A
method added to the Protocol is therefore outside that enumeration until an ADR puts
it inside, which is the property ADR-0168 §6 wanted when it chose to name what may
appear rather than what may not.

### A history row is not a question, and the difference is the whole of the rendering floor

ADR-0178 §7 states what a surface owes when it renders a `Confirmation` whose `egress`
is present, and ADR-0181 §6 extends it by one fact. Both are written about the instant
**before the user's answer is collected** — the account identity, every occurrence
whole, both destination forms, the canonical set as `core` derived it, the payload
description, and the call's origin in both of its states, all so that the user can
decide.

A history row is the same facts after the fact, and the temptation is to reuse the
card. It cannot be reused, for a reason ADR-0184 §5 already draws in the store: "a
park is a question put to the user, and answering it composes a `Confirmation` the
user acts on; a history read states what was recorded." A surface that rendered a row
as a card would offer an answer to a question that is closed — and for the one row
class this milestone exists for it could not compose the card at all, because ADR-0184
§8 forbids a `ConfirmationEgress` for an unrecorded origin and `ConfirmationEgress`'s
own `planned_with_external_content` is required with no default.

So the floor below is stated over a **decision**, borrows ADR-0178 §7's content
obligations because the facts are the same facts, and adds the two clauses a record
needs that a question does not: a third origin state, and a bar on presenting a ruling
as an event.

## Decision

We will put the trail on the promoted engine surface as **two operations** — a bounded
listing and the whole-trail export ADR-0021 §4 already names — carry both on the
transports that carry every other Tier 1 read, give a row a rendering floor that says
what the row says and no more, and leave the browser and the read record to the
decisions that own them.

### 1. Two operations, and they are two because the store's reads are two

> **Normative.** `AssistantEngine` gains exactly two methods.
> `recent_decisions(*, limit: int = DEFAULT_PAGE_SIZE) -> tuple[PermissionDecision, ...]`
> is the bounded listing and reads `AuditTrail.recent`.
> `export_decisions() -> tuple[PermissionDecision, ...]` is the whole-trail read and
> reads `AuditTrail.export`. Neither composes, filters, projects, enriches or
> summarises what the trail returns, and neither reads any other store.

> **Normative.** Nothing else is promoted by this ADR. No third method, no argument
> beyond `limit`, no filter by tool, by outcome or by window, no `core/types.py` model
> and no error class. A consumer that wants a subset selects it from what these
> return.

**Two rather than one, because a single method cannot be both bounded and complete.**
ADR-0021 §4 fixes the store's two reads against each other in terms: `recent` "is
bounded by default because the realistic query is 'what has the assistant just done',
and an unbounded read of a Tier 1 store by default is a shape worth not offering",
while `export` is the deliberate unbounded read that discharges a portability
obligation. Collapsing them into one method whose `limit` may be omitted to mean
"everything" would make the unbounded read of a Tier 1 store the *default* shape of the
listing, which is the sentence above read backwards, and would hide a data-rights act
inside a page query.

**The engine relays and does not compose, which is what keeps the two answers
comparable.** ADR-0139 §1's rule that "neither answer is derivable from the other and
no surface may present one as the other" is about two questions; here there is one
question at two extents, and the property worth protecting is that the listing is a
**prefix** of the export under §2's order. An engine that filtered or enriched either
one would break that without any surface being able to tell.

**Naming.** `recent_decisions` follows `recent_grants`, `recent_connection_acts` and
`recent_conversations`; `export_decisions` names its store's own method. On this
Protocol "decision" has one referent — `PermissionDecision` — and nothing else on the
surface competes for the word. The longer `recent_permission_decisions` is weighed and
rejected in Alternatives.

### 2. One total order describes the whole surface, and the engine owes the sort

> **Normative.** Both operations return decisions ordered by `decided_at`
> **descending**, ties broken by `id` **ascending** — `AuditTrail.recent`'s total order
> (ADR-0021 §4), applied to both. `recent_decisions(limit=n)` returns the first `n` of
> the sequence `export_decisions()` returns over the same trail state.

> **Normative.** The order is guaranteed by the **engine operation**. `AuditTrail.export`
> states no order and this ADR adds none to it; an implementation relaying a store read
> that arrives unordered owes the sort, over a list it has already materialised.

> **Normative.** No surface presents this order as a claim about when anything was
> *done*. It orders the instant a ruling was made, which ADR-0021 §4 chose over
> insertion order precisely because they disagree, and it is the whole of what a
> position means.

**Stating it here rather than on `AuditTrail.export` is the narrower change and it is
deliberate.** Adding an ordering clause to the store's contract would re-open a
ratified ADR-0021 §4 method, move its conformance suite and bind every implementation
for a guarantee only this surface currently needs. Stating it on the operation that
promises a user an artifact costs a sort and leaves the store's contract where it is;
it is additive onto the store the day a second consumer needs it (ADR-0008 §1).

**Determinism is not tidiness here, it is what the exit test is measured on.**
Milestone 24 asks whether a history is *reconstructible* from the trail alone. Two
implementations handing back the same rows in different orders satisfy every other
clause of this ADR while giving two users two different accounts of the same events,
and a resolution appearing above or below the `CONFIRM` it answers is exactly the
"internally consistent and chronologically false" reading ADR-0021 §4 wrote its
ordering rule against.

### 3. The listing's bound, and the export's ceiling stated with its number

> **Normative.** `recent_decisions` takes `limit` and **no `offset`**. `limit` is
> refused when it is not an integer, when it is a `bool`, and when it is outside
> `[1, 2**63)` — **locally and before any I/O, in every implementation**. Zero is
> refused, which is stricter than ADR-0085 §9's `[0, 2**63)` and is what
> `AuditTrail.recent` itself requires.

> **Normative.** `export_decisions` takes no argument, is bounded by nothing at the
> contract, and is subject to ADR-0085 §8c's payload limit exactly as every other
> unbounded read on this surface is: a trail whose canonical encoding exceeds the limit
> raises `OversizedValueError`, carrying the limit and the measured size. No
> implementation truncates the artifact, samples it, or returns a partial export
> without saying so.

**Zero follows ADR-0151 §2a and not ADR-0102 §10, and the disagreement it avoids is
already documented in this tree.** `recent_grants`' own contract records that "the two
contracts disagree about zero" — the surface rule admits it, `SourceGrantStore.recent`
refuses it — and that neither implementation may be silently more permissive. That
disagreement is a live wart on one method; reproducing it here would make it two.
`recent_connection_acts` took the other path for the same reason and this follows it.
There is no `offset` for ADR-0102 §10's reason, unchanged: the store has none, so an
offset would be either a store change this ADR does not own or an engine-side
over-fetch-and-slice — a paging surface that lies about its cost.

**The export's ceiling is real and is stated with a measured figure rather than
waved at.** ADR-0085 §8c makes the contract limit `hub_max_frame_bytes` less a
512-byte envelope reserve, and `core/config.py` defaults that setting to 16 MiB.
Measured in this tree on 2026-08-23, against the pinned pydantic and through a
`TypeAdapter` of the operation's own return annotation, one `PermissionDecision`
carrying a whole `ToolDefinition` and an egress binding encodes to **858 bytes** — so
the default ceiling holds a trail of the order of nineteen thousand rulings, and an
operator who needs more raises the setting the connect reply already carries to the
client. That is a ceiling and not a bound, the trail has no retention rule (#108), and
this ADR does not mint one.

**A cursor was the alternative and it is rejected here rather than deferred
vaguely.** Paging the export would require a cursor on `AuditTrail.export`, which is a
change to a ratified store contract, its conformance suite and every implementation,
in service of a trail size nobody has yet observed — and it would replace one honest
failure with a surface on which a user assembles their own artifact from N frames and
has no way to know whether the assembly is complete. The trigger for revisiting is
stated in Consequences: a real trail that does not fit, which fires #108's retention
question at the same moment.

### 4. `get`, `resolution_of`, `record` and `clear` are not promoted, each for its own reason

> **Normative.** `AuditTrail.get`, `resolution_of`, `record` and `clear` gain no
> counterpart on the promoted surface, and no lane adds one on the strength of this
> ADR.

**`resolution_of` answers a question the user cannot ask.** It is keyed on an
`(execution_id, step_id)` binding, exists "so a step stranded `AWAITING_APPROVAL` …
can be driven to the disposition already decided" (its own contract, ADR-0044 §2), and
every row it can return is a row `export_decisions` returns. Promoting it would offer a
user a lookup by a key they do not hold, for an answer they already have.

**`get` is deferred with its trigger rather than refused.** A single-row read is worth
minting when a surface needs to deep-link one row — from a confirmation, from a
notification, from the browser's own history view — and none of those exists. Every row
it would return is in the export, so nothing is unreachable without it, and it is
additive the day a consumer arrives (ADR-0008 §1). ADR-0021 §4's warning is the reason
for waiting: "adding a query method is additive, and guessing at filters now is how a
contract acquires methods nobody calls."

**`record` is not a surface operation at all.** The trail is written by the permission
layer as it rules; a promoted `record` would let a client append to the audit record of
what was permitted, which is the fabrication ADR-0184 §4 closed the last route to.

**`clear` is refused, and the user keeps the right it discharges.** ADR-0021 §4 gives
the user wholesale erasure — "the user may burn the book" — and this ADR neither
removes nor narrows it: ADR-0126 §2's whole-installation delete is the act that
carries it today. What is refused is putting an irreversible destruction of the record
of everything ever permitted **one request away on a transport an enrolled device
reaches** (§5) and a browser might later reach (§6). An ADR that wants trail-only
erasure decides its own confirmation shape and its own transport; it does not inherit
one from a listing.

### 5. Both listeners carry both operations, and neither is a connection method

> **Normative.** `recent_decisions` and `export_decisions` are served on the hub's
> loopback listener **and** on its remote listener. Neither joins
> `CONNECTION_METHODS`, and neither calls `wire/client.py`'s `_refuse_off_loopback`.
> No lane adds a per-listener restriction for them.

> **Normative.** `PROTOCOL_VERSION` moves for this decision, under ADR-0124 §9's first
> limb, and the obligation falls on the change that adds the methods, in that same
> change (§11).

> **Normative.** `HubClient` gains a forwarding method for each operation, refusing
> `limit` on §3's terms **locally and before any frame is sent**. Nothing else under
> `wire/` changes: `METHODS`, `STREAMING_METHODS`, the argument and result adapters and
> the error mapping are all derived from the Protocol.

**The client's two methods are named because the client is hand-written where the
server is reflected, and an earlier draft of the clause above said "nothing else under
`wire/` changes" without them.** Adversarial review found it. `wire/surface.py` reads
the Protocol, so `wire/server.py`'s dispatch and both adapters are total by
construction — but `wire/client.py` exposes each promoted method as its own `async def`
relaying through `_call`, so a client that grew no methods would raise `AttributeError`
before a frame was ever sent, and §5's first clause would be satisfied by a hub nothing
could ask. ADR-0151 §11 states the precedent in exactly this form — "Nothing in `wire/`
changes but the client's five methods" — and this is that sentence with the right
number in it. The **local** refusal is not optional either: `AssistantEngineContract`
asserts that "a malformed page argument and a blank identifier are refused locally
(§9), so neither implementation is silently more permissive", and a client that shipped
`limit=0` to the hub would be exactly that.

**The withheld five are withheld for a reason that does not reach a history read.**
ADR-0151 §13 keeps the connection operations on the loopback socket because they carry
a **Tier 0 credential** and "ADR-0124 §3's accepted-disclosure list does not include"
one. A `PermissionDecision` carries no credential and no payload: `tool` is a
`ToolDefinition`, which is Tier 2 configuration declared by code; `parameters_digest`
exists precisely to "bind the payload without storing it"; and the binding carries the
account identity, the occurrences and the payload description — every one of which
**already crosses the remote listener today** inside a `Confirmation`'s
`ConfirmationEgress`, on `TurnOutcome.step.confirmation` and as the element type of
`pending_confirmations`. So no new class of data reaches the hop, and ADR-0124 §1
already authorises the hop for the class that does.

**What is new is quantity, and it is named rather than glossed.** An export is the
largest single payload this surface can produce and it concentrates a whole history in
one frame, where a confirmation concentrates one call. That is bounded by the posture
ADR-0124 already ratified — overlay-only reachability (§2), an identity the transport
attests and a credential the owner minted (§4, §7) — and by §3's ceiling. It is not
bounded by withholding the method, which would mean a user on their own second machine
cannot read their own audit trail: the deployment with the most history is exactly the
one where that would bite.

**Verified in this tree rather than reasoned about.** A `PermissionDecision` whose
`egress_binding` is an `OriginUnrecordedBinding`, dumped and re-validated through a
`TypeAdapter` of `tuple[PermissionDecision, ...]` — the shape ADR-0085 §10 builds from
the return annotation — round-trips **equal**, and the decoded value carries no
`planned_with_external_content` key anywhere under `egress_binding`. ADR-0184 §3's
`extra="forbid"` discrimination is therefore total on the client side too, with no
discriminator member and nothing transcribed into a wire-side schema: the third origin
state survives the wire because the union re-discriminates structurally at the far end.

### 6. The browser gets no route here, and ADR-0177 §1 stays closed at thirty

> **Normative.** Neither operation is one of ADR-0177 §1's thirty. No browser request
> resolves to either, no browser argument reaches either, and the gateway makes neither
> call of its own. ADR-0177 §1's enumeration binds unchanged and this ADR does not
> widen it.

> **Normative.** A browser history view is a **later consumer lane** with its own
> ratified decision, which widens ADR-0177 §1's enumeration in its own text — the route
> ADR-0177 §1's third clause fixes for `learn` and ADR-0175 §6's third clause fixes
> generally. It inherits §7's floor and §8's bars without restating them.

**Later rather than now, and the reason is sequencing rather than doubt.** The CLI is
the surface the milestone-23 QA run drove and the one #1485 was filed against; it is
where the exit test can be measured with no gateway in the loop. ADR-0177 §8's
precedent is the shape — a browser surface blocked until the thing it must render is
decided — and ADR-0178 §10 records the CONFIRM card's own browser deferral as still
held by #1404. A history view landing beside that work would collide with it in the
same assets for no gain this milestone can measure.

### 7. What a row renders as

> **Normative.** A surface rendering a decision this operation returned renders, for
> every row: the ruling's outcome, its reason, the instant it was decided, and the
> recorded `ToolDefinition`'s own identifier and capability — read from the row, never
> from a registry, because ADR-0021 §1 embeds the declaration verbatim so that "the
> trail stays readable without the registry".

> **Normative.** Where the row's `egress_binding` is an `EgressBinding` or an
> `OriginUnrecordedBinding`, the surface renders ADR-0178 §7's content obligations over
> it, unchanged and in full: the `account_identity`; every occurrence the `spans` carry,
> each by the argument it was selected by, its position, its provenance and its extent,
> and its tier where it states one — whole, none omitted, none truncated silently and
> none ordered so as to hide one; both destination forms for the
> occurrences that carry a destination and for those only; the canonical destination set
> **as `core` derived it**, never inferred by the surface and never accepted from the
> wire as a materialised value; and the payload description. Where the set is the
> account — every span carrying no destination — the surface names the account as the
> destination rather than showing no recipients.

> **Normative.** The call's origin is rendered in **three** states, each distinct from
> the other two on the surface and none rendered as any other: it did rest on recorded
> external content, it did not, and — where the binding is an `OriginUnrecordedBinding`
> — **it was never recorded** (ADR-0184 §2). No surface renders the third state as
> `False`, as "no", as an empty value, as an omission, or as anything a reader could
> mistake for either of the first two. It is rendered in all three states for ADR-0181
> §6's reason: a fact shown only when it is alarming is one a user learns to read as an
> alarm, and its absence as clearance.

> **Normative.** Where the row's `egress_binding` is `None` the surface renders no
> recipient, no account and no origin, and asserts nothing about any of the three.
> `None` means the request was not an egress call (ADR-0150 §1) and continues to mean
> exactly that.

> **Normative.** The resolution relation is rendered from the rows themselves: a
> decision whose `resolves` is set names the `CONFIRM` it answers, and a `CONFIRM` is
> rendered as a question that was asked. No surface renders an unresolved `CONFIRM` as
> denied, as allowed, as expired, or as awaiting anything — a resolution may lie outside
> a bounded page, and its absence from a page is a fact about the page.

> **Normative.** No surface omits, truncates, summarises, samples or counts in place of
> any part of what it renders. A surface that cannot render a row whole renders **fewer
> rows**, not partial ones.

> **Normative.** Every value rendered is inserted into the surface's output as **data**,
> neutralised for that target on render (ADR-0042 §4, ADR-0178 §7's seventh clause).
> Being read from an append-only store relaxes nothing: `reason` is policy-authored
> text, a `supplied` destination form is a string a model produced, and `argument` is a
> caller-influenced key (ADR-0150 §13).

**Borrowing ADR-0178 §7 rather than restating it is the point.** The facts in a
recorded binding are the same facts the card was ruled over — ADR-0178 §5 builds a
`ConfirmationEgress` from the recorded decision — so a second, differently worded floor
would be a second vocabulary to keep in step with the first, and the failure would be a
history that renders a disclosure the card showed, or shows one it did not. What §7
adds is the third origin state, which no confirmation can carry (ADR-0184 §8), and the
resolution clause, which no confirmation needs.

**The third state has to be a rendered state and not a rendered absence**, which is
ADR-0184 §2's second test read at the surface. The whole reason `OriginUnrecordedBinding`
carries the account, the occurrences and the payload description instead of being a
marker is that the row's facts are the user's to read; a surface that then showed the
origin column blank would have thrown away the one thing the value was minted to say.

### 8. What no surface may do with a row

> **Normative.** No surface derives liveness from history. A row states that a ruling
> was made, never that it still stands, that a grant is current, that an account is
> connected, or that a definition is still registered under the identifier the row
> records. This is ADR-0102 §3's clause and ADR-0151 §9's, read one store over.

> **Normative.** No surface derives authorisation from history. No surface computes,
> displays or implies `PermissionDecision.authorises`, and none presents a row as a
> permission that covers any request other than the one it names.

> **Normative.** No surface presents a decision as a transmission. The trail bounds
> resolutions and not executions (ADR-0021 §4), so a resolved `ALLOW` says a call was
> permitted and says nothing about whether, or how many times, it ran. No surface
> renders a row as "sent", "read", "delivered" or any other word for an event. #1503
> carries the consequence for milestone 24's exit wording.

> **Normative.** No surface renders content the row does not carry. `parameters_digest`
> is a digest and is never rendered as, labelled as, or expanded into the payload; a
> span states an argument, a position, a provenance and an extent and holds no content
> (ADR-0178 §7's sixth clause).

> **Normative.** No surface renders `reads`, `writes` or `discloses` as a measure of
> what a call did. They are ceilings on what a tool *may* reach, not per-call
> measurements (ADR-0016 §3), and the per-call facts are the binding's. A surface that
> presented a tier reach beside a recipient list as though both described the same call
> would be asserting the measurement ADR-0016 §3 declines to offer.

> **Normative.** No surface presents `planned_with_external_content` as a detection, a
> score, a risk level or a warning that a call was malicious, and none suppresses,
> reorders or de-emphasises any part of §7 on the strength of it (ADR-0181 §7).

> **Normative.** No surface renders a row as a confirmation. It composes no
> `Confirmation`, offers no answer or approval control on a history row, and routes no
> answer through this surface: `pending_confirmations` and `resume` are where a question
> is answered, and ADR-0184 §8's bar on a confirmation shape for an unrecorded origin
> binds here as it binds everywhere.

**Each of these is a failure a plausible implementation reaches for**, which is why
they are written as bars rather than left to taste. A history view that shows a green
tick beside an `ALLOW` has claimed a transmission; one that shows `discloses=(PERSONAL,)`
beside a recipient has claimed a measurement; one that puts an "Approve" button on an
unresolved `CONFIRM` has built a second answer path around ADR-0042 §4's rule that an
adapter may not author a permission outcome. None of them would fail a type check.

### 9. The command-line surface

> **Normative.** `interfaces/cli.py` gains two commands. `assistant decisions` renders
> `recent_decisions` under §7's floor, taking `--limit` with the same refusal §3 states
> and defaulting as the Protocol defaults. `assistant export-decisions` writes the
> artifact `export_decisions` returns.

> **Normative.** The export is **one JSON document written to standard output**: the
> array of `model_dump(mode="json")` projections of the decisions, in §2's order, and
> nothing else on that stream. Diagnostics, progress and errors go to standard error.
> The command writes no file, takes no path and applies no overwrite policy.

> **Normative.** The artifact is a **faithful copy**. No key is added, removed,
> renamed, reordered for presentation or annotated; a row whose binding is an
> `OriginUnrecordedBinding` carries **no** `planned_with_external_content` key anywhere
> under `egress_binding`, and the absence is the state (ADR-0184 §3, §10's round-trip
> clause). The rendering of that state in words is `assistant decisions`' job under §7,
> not the artifact's.

> **Normative.** The bare name `export` is **reserved** on this CLI for ADR-0004 §6's
> whole-installation artifact, which this ADR does not discharge (#1502). No lane names
> a single-store export `assistant export`.

**Standard output rather than a file keeps the adapter thin, which is golden rule 3
and not a style preference.** A `--output PATH` would put path validation, an overwrite
policy and a partial-write story into `interfaces/`, and every one of those is a
decision about the user's data made in an adapter. A stream composes with the shell the
user already has, and it is the one shape whose test asserts bytes rather than a
filesystem.

**Faithful rather than annotated, and the round-trip is the deciding argument.** An
artifact carrying a friendly `"origin": "not recorded"` marker beside the members would
fail re-validation against `PermissionDecision`, whose models set `extra="forbid"` — so
the export would no longer be an export. The user reading rendered history gets the
words; the user reading the artifact gets the row, and ADR-0184 §3 makes the absence of
that one member total and unambiguous.

### 10. How the read record joins later

> **Normative.** This surface returns permission decisions and states nothing about
> reads. No lane presents `recent_decisions` or `export_decisions` as an answer to what
> was read from a source, and the CLI's existing `assistant granted` sentence — that
> "whether anything was actually read is a question nothing here answers yet" — stays
> true until the read-record decision lands.

> **Normative.** The read record joins **additively**: as its own operation or
> operations on this Protocol, or as a composed artifact one level up in the sense
> ADR-0074 §9 already fixed, decided by the read-record ADR (#1017) in its own text. It
> does not join by widening `PermissionDecision`, by adding a member to it, or by
> reshaping either operation this ADR mints.

**The composition point is the one ADR-0074 §9 already chose, and it is why neither
operation returns a wrapper type.** That section split a store's own snapshot from the
composed user-facing artifact — "`ConversationStore.export` returns the store's own
snapshot … the `orchestration` stage composes the user-facing export" — and put the
composition in the layer that holds both stores. An operation named for decisions
returning decisions is correctly named at that split; a `PermissionDecision` tuple is
what every other enumerating operation on this surface returns; and the artifact that
one day carries decisions *and* reads is the composed thing, which is a different name
for a different value and is #1502's territory as much as #1017's.

**Nothing here pre-empts the read record's shape**, deliberately. Whether a read is a
`PermissionDecision` with a new ruling, a new `core` type in a new store, or an entry
in the same store is exactly what that ADR decides, and this one is written so that
every answer it could give leaves §1 through §9 standing.

### 11. Two lanes, and what each owes

> **Normative.** The **contract lane** is the two Protocol methods, the shared
> conformance cases below, their implementation in `orchestration/engine.py`, the
> canonical fake in `ai_assistant.testing`, `HubClient`'s two forwarding methods, and
> the `PROTOCOL_VERSION` bump — one change under ADR-0137 §2, with `orchestration` the
> primary production implementation and every other site adaptation in ADR-0137 §1's
> sense.

> **Normative.** §9's two commands are a **follow-on consumer lane** under ADR-0137 §4,
> briefed only after the contract lane has merged, with the merged contract text as that
> brief's authority. No lane carries them into the contract lane.

> **Normative.** The contract lane moves `PROTOCOL_VERSION` from 11 to 12 and records
> the reason beside the constant in `wire/envelope.py`'s own form, citing ADR-0124 §9's
> first limb. It ships a test pinning the new value.

> **Normative.** The contract lane appends the dated note §13 places on ADR-0177,
> because that change is the one that makes ADR-0177 §1's count false.

**The shared conformance suite is where §2 and §3 are made checkable, and an earlier
draft of this section said no suite case was owed.** Both review lenses found it, and
they were right twice over. `AssistantEngineContract` is the shared suite for **this**
Protocol — `AuditTrailContract` is a different suite and is indeed untouched — and it is
subclassed by the concrete engine, by the canonical fake **and** by `HubClient`, which is
what makes it the only place a clause binds all three. It is also the precedent: ADR-0102
§12 item 2 put "a clause per ruling above that a store cannot exhibit" here for exactly
this reason. And it settles where `HubClient`'s methods land — the suite runs against the
client, so the client's two methods cannot be deferred to a later lane without the suite
going red the day it lands.

> **Normative.** `AssistantEngineContract` gains, for both operations: §2's **order**,
> asserted over rows sharing a `decided_at` so the `id` tie-break is exercised rather
> than assumed, and over a trail whose insertion order differs from its `decided_at`
> order; §2's **prefix** property, `recent_decisions(limit=n)` equal to the first `n` of
> `export_decisions()` over a trail of more than `n` rows; §3's **local refusal** of
> `limit` for a `bool`, for a non-integer, for zero, for a negative value and at
> `2**63`, each before any I/O; and §3's **oversized result**, refused coming back
> exactly as an oversized argument is refused going in, which is the suite's own fifth
> clause applied to the largest result this surface can produce.

**The prefix case is the one nothing else would catch.** An implementation that sorted
its listing and relayed an unordered export would pass every construction test, every
rendering test and every transport test, and would hand two conforming implementations'
users two different accounts of one history — which is the failure the suite's own
preamble says it exists for, "a way two implementations could answer the same call
differently while both looking correct".

> **Normative.** The contract lane ships reader tests over a trail holding **one**
> origin-unrecorded row among **several** ordinary ones — the shape ADR-0184 §10
> requires and for its reason: `recent_decisions` and `export_decisions` each return
> every row including it, and a test whose trail holds only the legacy row does not
> satisfy this clause. These are the implementation's own, not the suite's, for ADR-0049
> §5's reason: the row is seeded by writing JSON into a `SqliteAuditTrail`'s `data`
> column, and a fake holding objects has no bytes for a shared case to seed.

> **Normative.** The contract lane ships a transport test that both methods are served
> on the remote listener — that neither is in `CONNECTION_METHODS`, asserted against
> the frozen set rather than by absence from a hand-written list — and a gateway test
> that a browser request naming either is refused, which pins §6 against ADR-0177 §1.

> **Normative.** The consumer lane ships a round-trip test at the surface: the JSON
> `assistant export-decisions` writes re-validates as `tuple[PermissionDecision, ...]`
> and compares equal to what the engine returned, with the legacy row's
> `planned_with_external_content` key absent in both directions.

> **Normative.** The consumer lane ships rendering tests for the three origin states
> over three rows in one listing, asserting that the third state's rendering is distinct
> from the `False` state's rather than merely present; for a non-egress row, that no
> recipient, account or origin is rendered; and for an unresolved `CONFIRM`, that it is
> rendered as neither allowed nor denied.

> **Normative.** The consumer lane ships a rendering test for §7's first two clauses
> over **one** row whose binding carries, together: a span with a destination, a span
> with **none**, a span stating a `tier`, and two spans naming one recipient by two
> arguments. It asserts, by enumeration rather than by sampling — the row's outcome, its
> reason, the instant it was decided, and the recorded `ToolDefinition`'s identifier
> **and** its capability; the `account_identity`; for **every** span its `argument`, its
> `index`, its `provenance` and its `extent`, and its `tier` for the span that states
> one; both destination forms for the span that carries a destination and **neither**
> form for the span that does not; the `core`-derived canonical set, read from the value
> rather than recomputed; and the payload description. It asserts in the opposite
> direction too: that a value carrying markup for the target is neutralised on render
> (ADR-0042 §4).

**The enumeration is written out because the two rounds that produced it each found one
more member.** A listing rendering only the deduplicated destination set passes an
origin-state test, a non-egress test and an export round-trip; one rendering every span
but not its `tier`, or the tool's identifier but not its `capability`, passes a test
that names the members it happens to check. Naming every member §7's first two clauses
require is what makes the obligation checkable by reading the clause against the
assertions rather than by judging whether enough was asserted.

- **#1485 closes against the consumer lane**, because that is where the trail first
  becomes drivable by a user, which is the gap the issue records.

### 12. The pre-registered exit measurement for this surface

> **Normative.** Milestone 24's QA drives this surface over a real `SqliteAuditTrail`
> seeded with, at least: an ordinary egress decision whose origin is `True`, one whose
> origin is `False`, an origin-unrecorded row written by putting the JSON into the
> `data` column directly (ADR-0184 §4 makes it unproducible through `record`), a
> non-egress decision, and a `CONFIRM` with its resolving `ALLOW`.

Pre-registered so the exit ruling is measured rather than argued, in #1427's own form:

1. `assistant decisions` lists every seeded row, newest first, and the
   origin-unrecorded row renders its state distinctly from the `False` row's — checked
   by reading the two lines, not by checking that a column is non-empty.
2. `assistant export-decisions` emits one JSON document carrying **every** row
   including the legacy one, and re-validating it against `PermissionDecision` succeeds
   with the legacy row's `egress_binding` carrying no `planned_with_external_content`
   key. This is the portability obligation ADR-0021 §4 names, driven end to end.
3. `recent_decisions(limit=n)` over the same trail is the first `n` rows of the export.
4. No payload appears on either surface; the digest is rendered as a digest.
5. The unresolved-`CONFIRM` case renders as a question asked, and the resolved pair
   renders the relation, with no page containing one and claiming the other's absence.
6. The same two commands run from an enrolled second device answer identically to the
   loopback run, and a browser request naming either operation is refused.
7. The gap #1503 names is stated in the ruling rather than measured away: what these
   surfaces reconstruct is every egress **decision**, origin included.

### 13. This ADR classified under ADR-0070 §1 and ADR-0082 §1

**ADR-0177 is amended, in one clause, by a count.** §1's third clause reads that
`learn` "is the one operation of the promoted surface that is neither in the
enumeration above nor the gateway's own". After §1 above there are three such
operations. Under ADR-0070 §1's test a reader acts **identically**: the obligation that
clause imposes is that no lane puts `learn` in a browser without its own ratified
decision, which is untouched; §1's *first* clause is an explicit closed enumeration —
"exactly these thirty … and no others" — which governs any method it does not name, and
§6 above states the same conclusion for these two in terms. So it is an amendment,
recorded as a dated header note.

**The note is placed on the contract lane and not on this document, which is a
departure from ADR-0184 §11 and is argued rather than assumed.** ADR-0184 wrote its
records in its authoring commit because "a record and the clause it records are one
judgement" — its §2 changed what a type *is*, so ADR-0150's sentence became false the
instant ADR-0184 merged. ADR-0177's sentence is a different kind: it counts the methods
on the promoted surface, and it stays **true** until a method lands. Writing the note
when this document merges would make ADR-0177 disclaim a state of the world that had
not happened yet — a note that is false on the day it lands and true only later, which
is a worse record than no note at all. §11's clause is what makes the placement an
obligation rather than an intention; ADR-0184 §11's own reasoning is followed and not
contradicted, because it turns on whether the record and the clause it records are one
judgement, and here they are two.

**No record is owed on ADR-0021, ADR-0184, ADR-0181, ADR-0178, ADR-0151, ADR-0175 or
ADR-0004.** ADR-0021 §4's five reads are *used* here and none is narrowed — §2 states an
order for an engine operation and adds no clause to `AuditTrail.export`; §4 declines to
promote `clear` and leaves the user's erasure right exactly where ADR-0021 §4 and
ADR-0126 §2 put it. ADR-0184 §5's readers are the readers these operations call, and §8's
`PROTOCOL_VERSION` clause — "does not move **for this decision**" — is about ADR-0184's
own change and is not a bar on any later one; §5 above moves it for a different reason
under a different limb. ADR-0181 §6 and §7 and ADR-0178 §7 are cited and extended to a
second kind of surface, which is the form ADR-0178 §7 chose when it stated its floor over
"a surface" so that "the third adapter inherits it without a third decision". ADR-0151
§13's five stay five. ADR-0175 §6's third clause is the route §6 above uses rather than
one it changes. ADR-0004 §6 gains a discharge for one store and keeps every other
obligation open (#1502). ADR-0082 §1 forecloses the rest: a record may be demanded only
by naming a sentence this change falsifies, and none of these carries one.

## Consequences

**What becomes easier.** The audit trail becomes readable by the person it is kept for.
A user can list what was ruled and export the whole record, an
origin-unrecorded row renders as its own state instead of denying the user every other
row, and the portability obligation ADR-0021 §4 assigns to `export` is discharged to
somebody for the first time. Milestone 24's exit acquires something to drive: five of
its seven measurements above are impossible today because no command reaches the store.
Every surface that renders decision history from now on — the browser's view, whatever
#747's cloud-egress rows become, whatever #1017's read record joins as — inherits §7's
floor and §8's bars without a second decision, which is what stating them over "a
surface" buys.

**What becomes harder.** The promoted surface grows by two, so `PROTOCOL_VERSION` moves
to 12 and hub and clients upgrade together — one redeployment, the cost ADR-0178 §6
names rather than minimises, and a half-finished upgrade now shows as the handshake
refusal naming both versions rather than a dropped socket. Anything that renders a
decision owes §7 in full, which is a longer row than a listing naturally wants to
print, and §7's last-but-one clause means a narrow terminal shows fewer rows rather
than shorter ones. The export's ceiling is the frame's, so a trail that outgrows it
fails loudly and the fix is an operator setting until #108 rules on retention. And a
user reading the JSON artifact learns the third origin state from the *absence* of a
member — legible to a schema, silent to a human — which §9 accepts as the price of an
artifact that re-validates.

**What would trigger revisiting this.** A real trail that does not fit the contract
limit fires §3's cursor question and #108's retention question together, and they should
be answered together. A consumer that needs one row by id fires §4's deferred `get`. The
read-record decision (#1017) may make a composed artifact the right shape, at which
point §10's second clause is the seam it lands on. And #1503's question — whether
milestone 24's "every egress" means the decision or the invocation — is the owner's at
the exit ruling; if it means the invocation, the invocation contract (ADR-0016 §7,
ADR-0014 §7's exactly-once debt) owes a record and this surface renders it under the
same floor.

## Alternatives considered

**One operation with an optional `limit` meaning "everything".** Rejected. It makes an
unbounded read of a Tier 1 store the default shape of the listing, which ADR-0021 §4
declines in terms, and it hides a data-rights act inside a page query — a user who
omits an argument should not thereby exercise a portability right. It also destroys §2's
prefix property, since one method cannot be both a page and the whole.

**A cursor on the export.** Rejected in §3. It changes a ratified store contract, its
conformance suite and every implementation for a trail size nobody has observed, and it
replaces one honest `OversizedValueError` with an assembly the user cannot verify is
complete.

**An export written to a file, or produced by a hub-local console script beside
`ai-assistant-backup`.** Rejected. A file path in `interfaces/` is an adapter making
decisions about the user's data (golden rule 3), and a hub-local script is unreachable
from the enrolled second device that ADR-0124 exists to serve — the machine the user is
actually sitting at is the one that cannot then read their trail. The offline family is
right for acts that need the instance lock or a stopped hub; a read needs neither.

**A `core` wrapper type for the export — an `AuditTrailExport` beside `PlanExport` and
`ConversationExport`.** Rejected, and it is the closest call here. Those two exist
because a store's export carries *several* collections that need naming together; this
one carries a single homogeneous sequence, and every other enumerating operation on this
surface returns a bare tuple. The wrapper's real attraction is somewhere for #1017's read
record to join, and §10 places that join at ADR-0074 §9's composition point instead —
where the same argument already put the memory-and-conversation artifact.

**Promoting all five of `AuditTrail`'s reads.** Rejected in §4. `resolution_of` is keyed
on a binding a user does not hold, `record` would let a client append to the audit
record, and `clear` would put an irreversible destruction of the whole record one
request away on a remote transport. `get` alone is deferred rather than refused,
with its trigger.

**Restating ADR-0178 §7's content obligations in this ADR's own words.** Rejected. A
second wording is a second vocabulary to keep in step with the first, and the divergence
would surface as a history that shows a disclosure the confirmation did not, or hides
one it did — over the same binding, rendered by the same process. §7 cites and extends
instead, which is the form ADR-0181 §6 used on the same floor.

**Rendering a history row as a confirmation card, reusing the shipped renderer.**
Rejected twice over. It offers an answer to a closed question and builds a second
approval path around ADR-0042 §4, and for the one row class this milestone exists for it
is not merely wrong but unbuildable: ADR-0184 §8 forbids a `ConfirmationEgress` for an
unrecorded origin, and that model's `planned_with_external_content` is required with no
default, so composing the card would demand the fabrication ADR-0184 exists to avoid.

**Waiting for the read record (#1017) and deciding one surface for both.** Rejected.
The two are on different critical paths — this one closes a gap that exists today over
rows that exist today, and that one mints a record nothing yet writes — and §10 is
written so that every shape #1017 could choose leaves this surface standing. Coupling
them would hold a discharged portability obligation hostage to an undesigned one, and
would put both in one lane against golden rule 5's grain.
