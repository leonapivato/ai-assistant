# 191. Reaching the world is an injected capability, and a subsystem handed none has no route

- Status: Proposed
- Date: 2026-08-24
- **Partially supersedes ADR-0017 §8** — its deferral of the injected transport
  capability, and that scope only. §8's three grounds stay legible as the record of
  why it was deferred; §1's rule, §2's boundaries, §3's fourteen conditions, §4's
  argument and §9's open list are all untouched, as is ADR-0154 §1's designation of
  `ai_assistant.tools.egress`.
- **This ADR authorises no byte.** It decides a contract. Nothing transmits, no
  tool is registered and no destination is approved by ratifying it, and the seam
  keeps transmitting exactly what it transmits today.
- Refs #85, #1427, #1544, #1545, #1548.

## Context

### What ADR-0017 §8 deferred, and which of its grounds have expired

ADR-0017 §8 is titled "Rejected alternative: a dedicated injected egress
capability", and it names the shape precisely:

> The stronger enforcement is an outbound-transport capability in `core`, injected
> into the boundaries allowed to use it, so a subsystem never handed it cannot
> connect regardless of what it imports — testable, contract-based, and squarely
> golden rule 1. Deferred, not dismissed.

Its three grounds, read against the tree as it stands:

- **"It does not fit `models/`."** Still true, and §5 below keeps it rather than
  working around it. Provider SDKs open their own sockets; a capability that
  covered `models/` would have to be HTTP-shaped or would have to reimplement
  each vendor's client, and the first of those is the shape §2 rejects for
  reasons of its own.
- **"Its shape depends on the invocation contract that does not exist."**
  Expired. ADR-0029 ratified invocation, ADR-0148 authorises an egress call as one
  whole, ADR-0152 derives the binding at one seam, and ADR-0154 designated
  `ai_assistant.tools.egress` and attested ADR-0017 §3's fourteen conditions in
  code. There is now an implementation for the capability's shape to be *shaped
  by*, which is the thing §8 was waiting for and the reason ADR-0147 §3 could
  apply the same shape at one boundary while declining to ratify it generally.
- **"The decisions are independent."** Still true, and it is what lets this ADR be
  written without reopening ADR-0017 §1. Which boundaries may transmit is settled;
  this is only about what enforces it.

#85 adds a third question §8 does not: "whether it is worth the indirection before
there is a second boundary actually transmitting." That is answered from outside
this ADR. Milestone 25's exit test (#1427) is stated over the instrument rather
than over the number of boundaries — "a tool that tries to reach the world outside
the seam cannot, and the test that proves it is the fake transport, not a grep" —
and there is no fake transport to write that test against.

### What the tree holds, checked rather than remembered

**Transport is already injected one level down, and only for tests.**
`SmtpEgressTransport.__init__` takes a `connect` parameter whose default is
`open_smtp_channel`, the one function in `tools/` that opens a socket.
`build_send_email_integration` takes `connect` as an optional keyword and, when it
is absent, constructs the transport without passing anything — leaving the
default. `app/composition.py` passes nothing. The single occurrence of `connect=`
anywhere under `src/ai_assistant` is inside `build_send_email_integration` itself.

So **production reaches the world through a default argument.** The mechanism
#85 asks for is three-quarters built; what is missing is that nothing is ever
*handed* anything. A test does not reach the network because the test remembers to
pass a double, and "remembers to" is the whole distance between the tree and the
property. That distance is why §3 below is the load-bearing section of this ADR
rather than §1.

**Two Protocols, both inside `tools/`.** `ByteChannel` in `ai_assistant.tools.egress`
is a duplex byte stream to one pinned endpoint — `is_secure`, `read_line`, `write`,
`start_tls`, `close` — and its own docstring already states this ADR's subject:

> That is the shape ADR-0017 §8 wants generally — an injected transport
> capability — applied at one boundary rather than ratified across `core`, which
> is the move ADR-0147 §3 records itself making.

`BoundTransport` in `ai_assistant.tools.send_email` is a different thing one layer
up: one method, `transmit`, taking an `EgressBinding` and the call's arguments. It
is about an *authorised egress call*, not about reaching the world.

**There is no canonical fake, and there are two test-local doubles.**
`ai_assistant.testing` holds no implementation of either Protocol. What exists is
`ScriptedChannel` in `tests/tools/egress_transport_harness.py` and `Connector` in
`tests/world/m23_harness.py` — the latter described in its own docstring as "a
connector that records every attempt and opens nothing". Milestone 23's harness
already measures attack-success-rate-past-gate off a transport double, and it can
do so only because that test passes `connect=connector` by hand. A per-test double
is not the instrument #1427's exit names, and it cannot become one: a fake for a
`tools/`-private Protocol cannot live in `ai_assistant.testing`, which imports
`core` and nothing else.

**Two nets, and a hole between them.** The import contract `network transports are
confined to the tools egress seam` enumerates modules; the source-reading tests in
`tests/tools/test_egress_seam.py` read names, reaching the subprocess routes no
import contract can express. Between them they miss `asyncio.open_connection`:
`asyncio` is deliberately absent from the contract's forbidden list because
`tools/invocation.py` imports it for ADR-0029 §4's deadline; the source net does
follow `asyncio`'s attributes, but its `FORBIDDEN_NAMES` carries only that
package's *subprocess* surface; and the one check that names `open_connection` —
`test_exactly_one_place_in_the_seam_opens_a_connection` — is scoped to the seam and
says nothing about any other module. A `tools/` module calling
`asyncio.open_connection` today passes both nets and the whole gate, by the same
route `open_smtp_channel` itself uses. Issue #1545, filed by this lane.

That is #85's third bullet — "an internal wrapper that imports the client on its
behalf" — found in this repository rather than argued from the general case.

### What a capability can buy, and what it cannot

Nothing in Python stops a module importing `asyncio` and opening a connection. A
capability is an *injection discipline*, not a sandbox, and #85's own phrasing —
"converts 'we forbade the known client libraries' into 'the capability is
unreachable'" — overstates what the language gives. This ADR does not adopt that
phrasing and §7 states the limit plainly.

What the capability does buy is exactly what #1427's exit asks for and what no
arrangement of nets can give: **the property becomes assertable at runtime over a
real composition.** Today the strongest available proof is a syntax-tree walk whose
own module docstring calls it "a net and not a proof". After this ADR, a test builds
the deployment the composition root builds, hands it one fake, drives a tool at the
world, and reads whether an attempt was recorded. That is a statement about the
running system rather than about its source text, and it is the difference between
ADR-0017 §4's honest accounting and a measurement.

## Decision

### 1. The capability is an injected opener, and it is `core` surface

> **Normative.** The outbound-transport capability ADR-0017 §8 describes is a
> Protocol `OutboundTransport` in `core/protocols.py`, with one method that takes
> an endpoint and returns an open duplex channel. The channel it returns is a
> second Protocol, `ByteChannel`, in `core/protocols.py`. The endpoint it takes is
> a pydantic model `TransportEndpoint` in `core/types.py`.

> **Normative.** `TransportEndpoint` carries a host, a port and whether TLS is
> established before the first byte, and nothing else — no scheme, no path, no
> query, no fragment, no userinfo, no credential and no recipient. An
> implementation is handed one already parsed and parses no string of its own.

> **Normative.** Every I/O-bearing method on both Protocols is `async`. A
> synchronous opener or read would block the one event loop the system composes on
> (`CLAUDE.md`, "I/O-bound methods are `async`") and would put the call outside the
> reach of ADR-0029 §4's deadline, which is the only bound §2 leaves on it.

> **Normative.** `ByteChannel` carries six operations and no others: a bounded read
> of one terminated line; a bounded read of at most a caller-stated number of
> octets; a write; a TLS upgrade; a query of whether TLS has completed; and a
> close. The raw read is required because §2 rests on a protocol being buildable
> over the channel, and a line-only channel cannot consume a body that carries no
> terminator.

The shape those clauses fix, shown rather than imposed — the marked clauses above
and in §4 are the obligations, and this block is display:

```python
class OutboundTransport(Protocol):
    async def open_channel(self, endpoint: TransportEndpoint) -> ByteChannel: ...


class ByteChannel(Protocol):
    @property
    def is_secure(self) -> bool: ...
    async def read_line(self) -> bytes: ...
    async def read(self, limit: int, /) -> bytes: ...
    async def write(self, data: bytes, /) -> None: ...
    async def start_tls(self) -> None: ...
    async def close(self) -> None: ...
```

**The capability is the opener, not the channel, because opening is the act
being governed.** #85's property is that "a subsystem that was never handed the
transport cannot open a connection". A channel is the *result* of an opening; a
subsystem that holds one already has a connection. So the thing that must be
scarce, and therefore the thing that must be injected, is the ability to obtain a
channel at all. The channel is contracted alongside it because it is the opener's
return type and therefore crosses the same seam.

**Both Protocols are `core` surface rather than `tools/`-private, and this is the
part of §1 with a real alternative.** The narrower move — delete the default
argument, keep `ByteChannel` where it is, and let `app/composition.py` hand in
`open_smtp_channel` — closes today's hole at a fraction of the cost, and it is
worth saying why it is not enough:

- **The canonical fake could not exist.** `ai_assistant.testing` imports `core` and
  nothing else, and `lint-imports` holds it there. A fake for a Protocol defined in
  `ai_assistant.tools.egress` cannot live there, so it stays what `Connector` and
  `ScriptedChannel` are: per-test doubles, each one somebody's arrangement.
  #1427's exit is stated over *the* fake transport, and a shared instrument is the
  thing being asked for.
- **The triad machinery only guards `core/protocols.py`.**
  `tests/core/test_protocol_triad.py` reads that module, so a contract whose entire
  value is that every holder behaves identically would be the one contract with no
  conformance suite enforcing it.
- **A second designated boundary would decide transport again.** ADR-0154 §1
  already says a module added beside the seam "is not designated by proximity" and
  needs its own ADR. What it should not also need is its own transport shape,
  its own fake and its own idea of what an endpoint is.

**What it costs is that `core` acquires a byte-level contract.** `core` otherwise
holds domain contracts — `MemoryStore`, `ModelProvider`, `AuditTrail` — and a
duplex byte stream sits visibly below them. That is the honest cost, and §2 argues
the level is not an accident but the point: a *higher*-level egress contract in
`core` would have to encode who may send what, and that is `permissions/`'s
question and the seam's, already answered by ADR-0148 and ADR-0152.

### 2. It is a byte channel, and deliberately not an HTTP client

> **Normative.** `OutboundTransport` and `ByteChannel` carry no URL, no request or
> response model, no redirect handling and no notion of a method or a header. A
> protocol — SMTP, HTTP, JSON-RPC or anything else — is built on the channel by
> the module that holds it, never inside the capability.

> **Normative.** Neither Protocol carries a timeout, a deadline or a retry
> parameter. What bounds a call that hangs in the transport is ADR-0029 §4's
> invocation deadline, which already bounds the whole invocation.

#85 leaves this open — "whether it is HTTP-shaped or lower-level" — and the answer
follows from what the shape makes *impossible*.

**A URL-shaped capability hands its holder the world.** Its argument names a host,
so a holder that can build a string can reach any host, and #83's whole subject is
a credential reaching the wrong one. It also has to decide about redirects, and a
capability that can follow one is a capability that can be pointed elsewhere after
the pin was checked — the failure ADR-0017 §3's transport-pinning condition names
and ADR-0154 attested against. A byte channel to a host and port that were handed
in has no second host to reach and no instruction it could receive that would give
it one.

**Composition runs the right way at this level.** SMTP is already driven over
`ByteChannel` inside the seam, and ADR-0147 §3 decided the same layering for MCP —
protocol handling "receives a connected channel from the seam and never constructs
one". An HTTP-shaped capability would invert that: the protocol would be inside the
capability and every consumer would inherit whatever it decided about redirects,
proxies and connection reuse.

**The one runtime that hands transport in agrees with the level.** A survey of
five agent runtimes (#1548) found MCP the only one whose components receive
transport rather than construct it, and it is stream-shaped: a server is handed a
read stream and a write stream and builds no client of its own. That is what
ADR-0147 §3 already anticipated for the MCP consumer — protocol handling "receives
a connected channel from the seam and never constructs one" — so choosing a channel
here is not a shape a future MCP integration would have to fight. The survey's
caveat applies unchanged: it is a reading of published code and documentation, not
a measurement of ours.

**The cost is named.** A future integration that speaks HTTP will build or import
an HTTP client over the channel, and doing that well is not free. It is still the
right trade: that work is confined to the designated seam, where ADR-0147 §3 and
ADR-0154 §1 already require transport to live, instead of being distributed into a
`core` contract every subsystem can see.

The timeout clause is a decision and not an omission. A bound on the open and a
bound on the invocation are two places a call can be cut, they would disagree the
first time either is tuned, and ADR-0029 §4 already owns the one that covers the
whole call.

### 3. There is no default, no fallback, and no ambient holder

> **Normative.** The one production implementation of `OutboundTransport` that
> reaches the network lives in `ai_assistant.tools.egress`, which ADR-0154 §1
> designates, and in no other module under `src/ai_assistant`.

> **Normative.** Every constructor and factory that needs a transport takes it as a
> **required** argument, with no default value and no `None`-means-the-real-one
> fallback. The implementing lane removes `SmtpEgressTransport.__init__`'s default
> and `build_send_email_integration`'s optional keyword, so an object that was
> handed no transport cannot be constructed rather than being constructed with the
> real one.

> **Normative.** No module-level instance, no accessor function, no registry entry
> and no import-time construction of a transport exists anywhere. The only way to
> hold the capability is to have been handed it.

> **Normative.** `app/composition.py` is the only place in `src/ai_assistant` that
> constructs the real implementation and the only place that hands it out. Holding
> it does not make `app/` an egress boundary: it opens nothing, and no lane reads
> this ADR as designating one under ADR-0017 §1.

> **Normative.** A channel is opened per call and closed by the holder that opened
> it. Neither Protocol carries a pool, a cache or a keep-alive, so no subsystem
> retains a route to the world between calls.

> **Normative.** There is no parameter, setting, environment variable, fallback or
> retry by which a component that was not handed the capability obtains one. This
> holds in tests as well as in production: a test receives the fake by the same
> route the composition root hands the real implementation, and no test-only
> back door exists for obtaining either.

> **Normative.** A deployment that configures no integration builds no transport
> and hands out none. Absence of configuration never selects a default
> implementation.

**This is the section #85 is actually about, and it is the one the tree fails
today.** A default argument is an ambient capability wearing an injection's
clothes: the signature says the transport is supplied, and production supplies
nothing. The property "a subsystem handed no capability has no route to the world"
is not true of `SmtpEgressTransport` as it stands, because it is handed no
capability and has a route.

**Removing the default is what makes the exit arm's assertion mean anything.** With
the default in place, a test that builds a composition and asserts no attempt was
recorded is asserting that the code path was not reached — the real connector is
still sitting there, one call away. With it removed, the same assertion says the
route does not exist, because the object holding the seam is holding the fake and
there is nothing else to hold.

**The escape-hatch clause is written against a documented failure, not an
imagined one.** The survey at #1548 records that Claude Code's sandbox — the
strongest confinement it found, enforced by the operating system — documents two
ways past itself: a `dangerouslyDisableSandbox` retry the model may attempt, and an
`excludedCommands` list with, in its own docs' words, "no equivalent managed-only
lockdown". Both are honest, and both are exactly what a capability claiming to
close a route by construction cannot have. The clause also reaches tests on
purpose: a back door added "only for tests" is a back door in the shipped object,
and the fake existing at all is what makes one unnecessary.

**"Absent means nothing transmits" is the default worth keeping.** The same survey
notes MCP's `TransportSecuritySettings` is disabled when the caller passes nothing —
a confinement most deployments therefore lack. This tree already has the opposite
default: `app/composition.py` builds no integration at all unless the operator
names both a connection and an endpoint, so a deployment that configures nothing
registers no tool and opens nothing. Removing the connector default extends that
property one level down rather than introducing a new one.

**The per-call clause matters more than it looks.** A pooled capability is a
long-lived connection owned by whoever opened it, and a subsystem that keeps one
across calls has a route that outlives the authorisation that produced it —
which is the fact ADR-0148 §4 protects by binding every element of a call to one
ruling. Nothing here changes that rule; the clause keeps the transport from
quietly creating a second, unbound way to reach the same endpoint.

### 4. What the capability pins by its shape

> **Normative.** An implementation opens a connection to the host and port of the
> `TransportEndpoint` it was handed, performs no name resolution beyond that host,
> follows no redirect or referral, and offers no way to reach a second host on one
> call.

> **Normative.** An implementation that establishes TLS — before the greeting or
> at the upgrade — verifies the peer's certificate chain and verifies the hostname
> against the endpoint's host. Neither Protocol exposes a verification-disabling
> option, a caller-supplied trust configuration, or a way to name a second host for
> the certificate, so no holder can obtain a TLS connection that was not verified
> against the endpoint it asked for.

> **Normative.** Where the endpoint's TLS mode is the upgrade one, the channel is
> cleartext until the upgrade completes, and the capability neither performs the
> upgrade nor can compel it. The obligation is the holder's: no credential and no
> user data is written to a channel whose TLS state reads false.
> `ai_assistant.tools.egress` already refuses on exactly that read before
> presenting a credential, and refuses a far end that does not offer the upgrade
> its scheme requires. That refusal is the property; the endpoint's TLS mode is
> not.

> **Normative.** `ByteChannel.read_line` bounds what it will buffer for one line
> and refuses beyond that bound rather than growing to whatever the far end sends.

> **Normative.** An `OutboundTransport` and a `ByteChannel` report what happened
> to the connection and assert nothing about whether a payload was delivered.
> Which outcome a channel failure produces is the holder's judgement, made from
> where in its own protocol the failure landed, and this ADR moves none of that
> judgement into the capability.

> **Normative.** `ai_assistant.tools.egress` therefore continues to convert a
> channel failure raised after a payload and its terminator were written into
> `IndeterminateTransmissionError`, as `_SmtpSession.data` does today. Nothing here
> narrows that window, widens it, or permits such a failure to be recorded as a
> refusal that transmitted nothing.

These are the properties `open_smtp_channel`, `_tls_context` and `_StreamChannel`
hold today, restated as obligations on the contract so that they survive the move.
It would be easy to lose them: a Protocol is a shape, and a shape with a
`verify: bool` on it is a shape somebody eventually passes `False` to. The point
of stating them here is that the capability becomes the place #83's pinning
property is *enforced* rather than a place it has to be re-checked — the seam
still compares the binding's endpoint text against the registration's before
parsing, exactly as ADR-0148 §6 orders it and ADR-0154's condition 5 attests, and
this ADR adds nothing to and removes nothing from that comparison.

**The outcome clauses are a division of labour, and this ADR's first draft had
them backwards.** It said a capability refusal is "never converted into an
indeterminate transmission" — which reads well and is false here. `_SmtpSession.data`
catches exactly that conversion and must: once the terminator is on the wire, a
failed read says only that this end stopped listening, which is not evidence about
what the far end did with the octets. ADR-0148 §9 maps
`IndeterminateTransmissionError` onto the step's `INDETERMINATE` outcome and
ADR-0014 §4's recovery scan reconciles it, so a rule forbidding the conversion
would have had an unknown disclosure recorded as one that did not happen — the
precise confusion that window exists to prevent. What is true is narrower, and is
what the clauses now say: the capability is not the party that knows, so it is not
the party that decides. `TransportPinError` stays in
`ai_assistant.tools.egress` and is not re-rooted: it names refusals about a
*binding* as well as about a connection, and only the second half is the
capability's.

### 5. `models/` stays out, and so do the third and fourth boundaries

> **Normative.** `ai_assistant.models` does not come under this capability. It
> continues to transmit under ADR-0004 §2's permission as ADR-0017 §2 records it,
> covered by the provider-SDK import contract, and nothing in this ADR adds a
> condition to it, discharges one, or bears on #83's `models/` half, #74 or #89.

> **Normative.** The trigger for revisiting that is named and does not need a
> further ADR to fire: the day a module under `ai_assistant.models` opens a
> connection by any route other than a provider SDK's own client, that route comes
> under this capability.

> **Normative.** ADR-0124 §1's boundary — the hub's remote transport in both
> halves — and ADR-0174 §1's — the gateway's browser leg in both halves — are out
> of this capability's scope. Nothing here weakens, discharges or substitutes for
> anything either requires, and no lane cites this ADR toward either. A later ADR
> may bring them under it; this one neither authorises nor forbids that.

> **Normative.** The capability's subject is a connection opened **off the
> device**. A loopback connection and a local IPC socket are not egress under
> ADR-0017 §1 and are not brought under it here.

**`models/` is the one boundary the capability cannot honestly cover, and ADR-0017
§8 said so first.** A provider SDK constructs its own client and opens its own
sockets. Bringing it in would mean either an HTTP-shaped capability — refused by §2
— or handing each vendor client a caller-supplied HTTP transport, which relocates
the SDK's connection pool without removing its ability to build another. A rule
enforced at one boundary and not the other is, in §8's own words, "roughly what
import contracts already give"; what changes that calculus is not that the rule
became universal but that at the `tools/` boundary it became *testable*, which is
milestone 25's exit and not a claim about `models/`.

**The third and fourth boundaries are out for a structural reason, not a
scheduling one.** This capability opens outbound connections. ADR-0124's listener
half and ADR-0174's gateway accept inbound ones, so half of each boundary has
nothing for an opener to govern, and bringing in the client halves alone would
leave the same asymmetry inside one boundary that §8 objected to across two. Both
already carry the property this capability buys, in their own form: ADR-0124 §1
requires the client half to obtain "its destination from configuration and never
from a discovery mechanism, a redirect, or anything a peer tells it", and ADR-0174
§2 takes that posture whole. Nothing is unguarded by their exclusion.

**The off-device clause keeps this from becoming a general socket permission.** The
hub listens on loopback, the gateway serves a browser, and `secret_store/` reaches
a keyring over D-Bus. None of those is data leaving the device, none is what
ADR-0017 §1 governs, and a capability that had to mediate them would be an
operating-system feature rather than an egress control. The nets remain what covers
that ground, and §7 says so.

### 6. `BoundTransport` stays where it is, as the tool's own contract

> **Normative.** `BoundTransport` in `ai_assistant.tools.send_email` is neither
> re-rooted into `core` nor subsumed by `OutboundTransport`. It stays a `tools/`
> Protocol, unchanged in meaning, and is a consumer of the injected capability
> rather than a layer of it.

The two are at different levels and answer different questions. `BoundTransport`
asks "send this authorised call, or refuse it": its argument is an `EgressBinding`,
its refusals are about a ruling, and both of its sides — `SendEmail` and
`SmtpEgressTransport` — live inside `tools/`. That is the case ADR-0149 §3's
reasoning covers, kept as a structural Protocol because the subsystem holds both
ends. `OutboundTransport` asks "give me a channel to this host", knows nothing
about bindings, authorisations or recipients, and is handed across a subsystem
boundary by the composition root. Merging them would put egress *authorisation*
semantics into `core`'s transport contract and would make every future holder of
the capability inherit `send_email`'s idea of a call.

### 7. The nets stay, one of them is extended, and the limit is stated

> **Normative.** The `import-linter` contract `network transports are confined to
> the tools egress seam` and the source-reading tests in
> `tests/tools/test_egress_seam.py` are kept. No lane retires, narrows or weakens
> either on the ground that this capability exists.

> **Normative.** The implementing lane extends the source-reading net's forbidden
> names with `asyncio`'s connection openers — at minimum `open_connection` and
> `open_unix_connection` — so that the net which already follows `asyncio`'s
> attributes covers its connection surface as well as its launch surface (#1545).

> **Normative.** No lane states or implies that this ADR makes egress from an
> undesignated place impossible. It makes the route this system hands out the only
> route this system hands out; the ambient reach of the language is unchanged, and
> ADR-0017 §4's "an import contract is a net, not a proof" stands exactly as
> ratified.

#85 asks for both — "Import contracts remain worthwhile as defence in depth …
They are just not a proof" — and the two catch disjoint failures. The capability
catches the honest case: a subsystem that asks the system for a way to reach the
world and is not given one. The nets catch the case the capability cannot see: a
module that never asks, and reaches for `socket` or `asyncio.open_connection`
directly. Retiring either would leave one of those two uncovered, and #1545 is
present-tense evidence that the second is not hypothetical.

The third clause is deliberately a prohibition on *claims*. A document that says
"closed by construction" is a document a later reader will cite as a guarantee, and
the guarantee is not available. ADR-0098 §3 records this repository making exactly
that error twice — stating a bound over something the check could not obtain —
before a reviewer caught it, and ADR-0147 §3 splits its universal prohibition from
its enumerated contract for the same reason. What is closed by construction is the
*handout*, and the exit arm in §9 measures precisely that.

### 8. Two Protocols, two triads, and what the fakes record

> **Normative.** `OutboundTransport` and `ByteChannel` are two Protocols and owe
> two triads — Protocol, shared `…Contract` conformance suite, canonical `Fake…`
> in `ai_assistant.testing` and the concrete `Test…Contract` subclass that runs
> one through the other. No exemption is available for either, and neither triad
> is split (ADR-0137 §3).

> **Normative.** Both triads land in one lane with `ai_assistant.tools.egress` as
> the primary production implementation, under ADR-0137 §2. The composition root's
> wiring rides with it as adaptation, not as a second subsystem's machinery, and
> every further consumer is a follow-on lane under ADR-0137 §4.

> **Normative.** `FakeOutboundTransport` opens nothing and imports no
> transport-bearing module. It records every attempt to open a channel, in order,
> with the `TransportEndpoint` each attempt named and whether it was served or
> refused; it can be armed to refuse, so a connection failure is exercisable
> without a network.

> **Normative.** The attempt record carries no payload and no credential. What was
> written to a channel is held by `FakeByteChannel`, which replays a scripted reply
> sequence and records the octets written to it; those octets are never persisted,
> and neither `FakeByteChannel.__repr__` nor any assertion message the conformance
> suite generates renders them.

**Two Protocols means two triads, and the corpus has already refused to bargain
over this**: ADR-0021's Consequences record that "Two Protocols mean **two
triads** in the implementation PR … for which no exemption is available". Naming it
here forecloses the obvious economy of contracting only the opener and leaving the
channel untested, which would leave the more dangerous of the two — the object that
holds an open connection — with no conformance suite at all.

**The fakes have a seed in the tree and a precedent outside it.**
`ScriptedChannel` in `tests/tools/egress_transport_harness.py` is already a
`ByteChannel` that replays an SMTP script and opens nothing; what it lacks is a
home `ai_assistant.testing` can hold and a conformance suite holding it to a
contract. The survey at #1548 records MCP shipping exactly this — an in-memory
stream pair satisfying the same interface as its real transports, used by that
SDK's own test suite — which is the same instrument one layer of packaging up.
The implementing lane promotes rather than invents.

**Recording refusals as well as successes is the clause the milestone depends
on.** "Did not reach the world" and "was never asked" are different facts, and an
exit arm that cannot tell them apart cannot distinguish a system that refused from
a system whose code path was never entered. `Connector` in `tests/world/m23_harness.py`
already has the right instinct — it increments its count *before* it refuses, so
"a transmission this system began is recorded whether or not any byte could have
left" — and this clause makes that shape the canonical one rather than one
harness's arrangement.

**The payload clause is a Tier 0 clause, not tidiness.** An SMTP exchange carries
an `AUTH` line, so a double that recorded and printed everything written would put
a credential into pytest output and into whatever a failing CI run keeps. The
octets still have to be recordable — the seam's own protocol tests assert on the
exact exchange — so the rule is about where they live and what renders them, not
about whether they are captured.

### 9. The exit arm asserts on the fake, and carries its own positive control

> **Normative.** Milestone 25's exit arm under `tests/world/` builds a composition
> through the production composition root, handing `FakeOutboundTransport` as the
> only transport in it, drives a tool that is not the designated seam at the world,
> and asserts that the fake recorded **no** attempt.

> **Normative.** That assertion is over the **handout**, and is read as nothing
> wider: an undesignated tool was handed no capability, so it had none to reach. No
> lane reads the arm as establishing that such a tool could not have opened a
> connection by some other route.

> **Normative.** The arm also instruments the process's connection-creating
> boundary for its whole duration — the running event loop's `create_connection`,
> through which both `asyncio.open_connection` and a direct call on the loop pass —
> so that an attempt made from inside the arm fails and is recorded, and asserts
> that none occurred at any point in it, the positive control included. It does not
> reach a raw `socket`, which stays the nets' ground and #1545's stated residue.

> **Normative.** The same arm, over the same fake in the same composition, drives
> the designated seam to a bound call and asserts the fake recorded exactly one
> attempt, to the configured endpoint. A zero that is not accompanied by that
> positive control does not discharge the exit. The control is an attempt recorded
> by the fake, which opens nothing, so it moves the connection instrument above by
> nothing.

> **Normative.** Every assertion in that arm reads a record the arm's own
> instruments made — the fake's, or the connection instrument's. No assertion in it
> is a source scan, an import-graph check or a text search.

**The negative assertion measures the handout, and the arm now says so in its own
text.** Adversarial review of this ADR's first round showed why the wider reading
had to be closed off rather than left implied: a non-seam tool calling
`create_connection` off the running loop bypasses the fake entirely, so the fake
reads zero, the positive control reads one, and every assertion passes while the
connection succeeded. That is #1545's residue arriving inside the exit test. The
answer is both halves — say what the fake measures, and instrument the boundary the
fake does not sit on — and neither half alone is honest. §7's third clause governs
what may be claimed from the result either way.

**The positive control is not ceremony.** An assertion that a recorder saw nothing
is satisfied by a recorder nothing could ever reach, and a harness that mis-wires
its own composition passes it perfectly. #1427 states the exit as "a tool that
tries to reach the world outside the seam **cannot**", and "tries" is doing work in
that sentence: the arm has to demonstrate that the instrument is live in the very
composition where the zero was measured. `tests/world/m23_harness.py` already holds
the precedent — `test_the_instrument_can_see_a_transmission` drives a transmission
on purpose so the arms that measure zero mean something.

The third clause is what makes this ADR's implementation answer the exit rather
than restate it. #1427 says the proof is "the fake transport, not a grep", and
`tests/tools/test_egress_seam.py` is the grep — an excellent one, kept by §7, and
not the thing being asked for here.

### 10. What this partially supersedes, and what it leaves standing

> **Normative.** This ADR partially supersedes ADR-0017 §8, in the scope of its
> deferral of the injected transport capability and in that scope only. §8's three
> grounds, §4's argument, §3's fourteen conditions, §2's account of the two
> boundaries, §1's rule and §9's open list are unreplaced and stand as ratified.

> **Normative.** ADR-0154 §1's designation of `ai_assistant.tools.egress` is
> unchanged. The capability is *how* the designated seam reaches the world, not a
> second seam, and this ADR designates nothing, widens no enumeration of egress
> boundaries and authorises no byte.

**This is a supersession and not an amendment, under ADR-0070 §1's own test.** A
reader holding only ADR-0017 §8 today reads "Deferred, not dismissed" and does not
build the capability; after this ADR they build it. That is a reader acting
differently, which is the line §1 draws, and §3 makes partial supersession the
sanctioned instrument rather than a discouraged one. It is deliberately *not* the
move ADR-0154 made against §3: there, conditions written to be met were *satisfied*
and nothing was replaced. Here a decision not to adopt is replaced by a decision to
adopt, and calling that satisfaction would be the mis-declaration ADR-0082 §1 warns
about — "a later ADR that calls its change an amendment … has mis-declared it, and
the record is wrong however the declaration reads".

**The record on ADR-0017 goes on its `Status` line and in an appended dated note.**
That line already leads with `Partially superseded by ADR-0124 (…)`, and the second
pair is added on the same line in the form the ADR template fixes. ADR-0082 §2
keeps *amendment qualifiers* off a leading-token line; a supersession target is
what that line is for, and ADR-0070 §4's invariant that every `ADR-NNNN` after the
leading token is a target stays true. No ratified text of ADR-0017 is rewritten,
§8 included: it stays legible as the record of a decision that was examined and
deferred with reasons, one of which has since expired.

### 11. What this does not decide

- **The budget ceiling on what the world may cost.** It needs an execution record
  to decrement, which does not exist; ADR-0021 §6 defers spend accumulation to
  "invocation reporting what was actually spent", and batch #1544 sequences that
  ADR behind the invocation record's.
- **The invocation record and consume-on-execution**, proposed beside this ADR as
  batch #1544's second lane. ADR-0017 §8's second ground was that the capability's
  shape "depends on the invocation contract"; the contract that ground meant is
  ADR-0029's, which exists. Nothing here depends on that sibling's content — it is
  named by its lane rather than by a number, because no such ADR exists as this one
  is written and a citation to an unissued number is a defect
  `tests/scripts/test_adr_citations_corpus.py` refuses.
- **The standing recipient policy** (#68), proposed beside this ADR as batch
  #1544's third lane. Who may receive is orthogonal to what opens the connection.
- **`models/`'s three open controls** — #83's `models/` half, #74, #89 — which §5
  leaves exactly where ADR-0017 §2 put them.
- **MCP's transport.** ADR-0147 §3 and §4 own it, and §12 there leaves the library
  choice to the implementing lane. When that lane lands, the capability is what it
  receives a channel from, which is what §3 there already describes.
- **A second designated module.** ADR-0154 §1 requires an ADR for one, and holding
  this capability is not designation.

## Consequences

- **New `core` surface:** two Protocols in `core/protocols.py`
  (`OutboundTransport`, `ByteChannel`), one pydantic model in `core/types.py`
  (`TransportEndpoint`), and an error in `core/errors.py` for what the capability
  refuses. Two Protocols mean **two triads** in the implementing lane, and
  `tests/core/test_protocol_triad.py` enforces that mechanically.
- **A Protocol change is a breaking change** (golden rule 5). This ADR is ratified
  and merged as its own PR before anything implements against it (ADR-0015 §5), and
  the implementation is one lane pairing both triads with `ai_assistant.tools.egress`
  under ADR-0137 §2.
- **`SmtpEgressTransport` and `build_send_email_integration` change signature.**
  The default connector and the optional keyword both go. Every construction site —
  `app/composition.py`, `tests/tools/egress_transport_harness.py`,
  `tests/world/m23_harness.py` — passes a transport explicitly, and the two
  test-local doubles are replaced by the canonical fakes or rebuilt on them.
- **`ai_assistant.testing` gains a transport fake for the first time**, which is
  what makes #1427's exit writable at all. Milestone 23's `Connector` becomes an
  arrangement over `FakeOutboundTransport` rather than a parallel implementation,
  so the ASR-past-gate instrument and the milestone-25 arm read the same record.
- **`ai_assistant.tools.egress` keeps its designation and keeps every property
  ADR-0154 §4 attested.** What moves is where the opener's *type* is declared, not
  where the socket is opened: the one function in `tools/` that opens one still
  lives in the designated module, and `test_exactly_one_place_in_the_seam_opens_a_connection`
  still has exactly one function to find.
- **The egress nets grow rather than shrink**, and #1545 closes with the
  implementing lane.
- **What would trigger revisiting this.** A boundary in `models/` that transmits
  without a vendor SDK (§5's named trigger, which fires without a further ADR); a
  designated integration that needs HTTP, which will test §2's claim that building
  a client over a byte channel inside the seam is the cheaper side of the trade; or
  a second designated module, which needs its own ADR under ADR-0154 §1 and would
  be the first real test of whether one capability serves two boundaries.
