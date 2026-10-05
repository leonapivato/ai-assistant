# 296. A device has one session, and a browser is a device of its own

- Status: Proposed
- Date: 2026-10-04
- Scope: [#2578](https://github.com/leonapivato/ai-assistant/issues/2578), the channel redesign: the device session, how a device is known to the hub, what it may do, and how ADR-0292's routes and ADR-0293's change stream reach it.
- Authorization: the owner accepted proposal #2687 on 2026-10-04, at `099c83da`, which records the rulings of the owner's walkthrough the same day, and the dispatcher assigned 0296. This ADR is that proposal converted under `docs/proposals/README.md` → "When it is decided".
- **Partially supersedes** [ADR-0292](0292-a-channel-is-the-spokes-facing-one-thing-and-the-assistants-edge-is-its-own.md) — **one scope.** **§4:8's *one connection per device*, §4:9's *closes its connection*, and §4:10's gate, as it reaches a browser device**: one session per device carries all its routes and may use several physical connections; revoking a device ends its session; a hub device is admitted by ADR-0124 and a browser device by its gateway (§1, §3 below). Every other clause stands, §4:9's removal as an end of every place and its unreachable spokes included.
- **Partially supersedes** [ADR-0293](0293-the-hubs-chat-is-a-hosted-medium-and-a-conversation-keeps-its-own-transcript.md) — **one scope, which takes effect when built.** **§11:1's delivery poll, as the change stream's transport**: a device follows the change stream as one streaming method on the existing wire, opened with its cursor (§4 below). The acts in the medium stay requests. Until the change stream is built, devices fetch it through the delivery poll exactly as §11:1 decides. Every other clause stands.
- **Partially supersedes** [ADR-0173](0173-an-answer-streams-as-chunks-of-one-reply-and-the-result-frame-is-still-the-answer.md) — **one scope.** **§2:2's *that model is `ReplyChunk`* and §2:3's *no sequence number*, as they reach the change stream's chunk frames**: each carries a change, the current state or a heartbeat, and a change carries its sequence number (§4 below). A reply stream's chunk stays `ReplyChunk` with no sequence number, `FrameKind` gains nothing, §1:4's rule that the hub writes only in answer to an outstanding request binds the change stream, and every other clause stands.
- **Partially supersedes** [ADR-0168](0168-the-gateway-serves-one-devices-browsers-over-loopback-and-a-web-session-dies-with-the-gateway.md) — **one scope.** **§3:3's *no per-browser identifier* and its bar on any member, argument or convention by which a browser identity reaches the hub, and §3:4, as they reach a browser device**: the gateway names the browser device each request comes from, the hub accepts the name only for a browser device registered under that gateway, and the hub conditions a device's roles on it (§1, §2 below). No session identity, session value or session token crosses the wire, the hub's admission of the gateway's own connection stays ADR-0124 §7's two facts, two browsers on one machine stay one device, and every other clause stands.
- **Partially supersedes** [ADR-0174](0174-a-gateway-may-serve-a-browser-on-another-overlay-device-and-that-hop-is-the-fourth-egress-boundary.md) — **two scopes.** **§4:4's bars on keying any rule on the list beyond admission, on citing it toward a device-scoped permission, on recording anything durable or revoking anything, and on any browser identity crossing the wire**: listing a machine at a gateway registers it at the hub under that gateway, as a browser device with no roles where it is not already a device; the hub keeps that registration and revokes it, and checks the device's roles on every request the gateway names it on (§1–§3 below). **§3:3's *and to no other record***: the hub's registration of a browser device may keep the overlay identity that names it (§1 below). A listed device is still no enrolment under ADR-0124 §6, no ADR-0097 grant and no principal, and every other clause stands, §4:3 and §4:5 included.
- **Partially supersedes** [ADR-0175](0175-a-browser-stream-is-a-response-body-on-the-request-the-browser-made-and-one-delivery-fans-out-to-every-open-stream.md) — **one scope.** **§5:4's and §6:4's bars on a per-browser identifier and a per-browser scope, and §6:4's *a browser reaches exactly what the gateway's own device reaches*, as they reach a browser device**: the gateway names the browser device to the hub, and a browser device acts with its own roles (§1, §2 below). No session value crosses the wire, two browsers on one machine stay one device, every browser is still the owner under ADR-0099 §1, and every other clause stands.
- **Partially supersedes** [ADR-0177](0177-the-browsers-control-surface-is-thirty-operations-and-a-credential-is-entered-only-on-a-loopback-origin.md) — **three scopes.** **§1:1's enumeration, which gains the acts in the medium (ADR-0293 §11:2) and the change stream** (§5 below). **§1:5's closed class of what the gateway supplies of its own, which gains the name of the browser device a request comes from** (§1 below). **§1:6's *no per-browser scope* and *a browser reaches exactly what the gateway's own device reaches*, as they reach a browser device**: of the operations a browser reaches, a browser device reaches what its roles allow (§2 below). §1:6's single principal stands, and every other clause stands, §1:3 included.

## Context

**The question.** How does a device stay connected to the hub: how is it known, what
may it do, and how do the routes of ADR-0292 and the conversation's change stream
(ADR-0293) reach it?

This is the third decision of the channel redesign
([#2578](https://github.com/leonapivato/ai-assistant/issues/2578)). ADR-0292 §4 gave
each device user-assigned roles, three routes and "one connection per device"
(§4:8), and left the transport to this decision. ADR-0293 §11:1 runs the conversation
channel's first build on today's wire, with devices fetching the change stream through
the delivery poll. This decision settles what replaces that polling and what
"connection" means. It rests on a transport evaluation of 2026-10-04, which read the
gateway, the hub's wire, ADR-0175 and the candidate WebSocket libraries.

The owner walked the proposal (#2687) through on 2026-10-04 and ruled on these points,
each recorded below as the owner's ruling of that date: that listing a machine at a
gateway registers it at the hub as a browser device with no roles (§1); that a browser
on the gateway's own machine is that machine's hub device (§1); that whether a device
writes and reads, or only reads, is set with its membership (§2); that a browser no
longer carries its gateway's whole authority, and a newly admitted browser can do
nothing until given roles (§2); that a device sees gaps in the sequence and its cursor
is the last number it applied (§4); what a device's stream sends when it gains or loses
a conversation (§4); and declining one physical socket per device (Alternatives).

**The ADRs this touches**, as they stand on `main`:

| ADR | What it decides today | How this decision relates |
| --- | --- | --- |
| ADR-0084 §3, §7 | The local API: a framed, versioned envelope; a connection carries one outstanding request at a time; the client stays stateless. | Kept. The change stream is one more streaming request, on a connection of its own (§4). |
| ADR-0124 | A device is admitted to the hub's remote listener by two independent facts, its overlay identity and an enrolled credential; revoking it closes its connections (§8). | Kept, for hub devices (§1). |
| ADR-0168 §3:3–§3:4 | Nothing about a browser reaches the hub, and no rule is conditioned on the hub telling two browsers apart; so a browser session carries the gateway device's whole authority (§3's heading). | Partially superseded: the gateway names the browser device, and the device acts with its own roles (§1, §2). |
| ADR-0174 §3:3, §4:4 | A remote browser's overlay identity is obtained by the gateway and recorded only on its admission decisions; listing a device admits it and keys nothing else, and no browser identity crosses the wire. | Partially superseded: listing a machine registers it at the hub as a browser device (§1). |
| ADR-0175 §5:4, §6:4 | ADR-0168 §3's prohibition restated for streams; no per-browser scope; a browser reaches what the gateway's device reaches. | Partially superseded with ADR-0168 §3, as it reaches a browser device (§1, §2). |
| ADR-0175 §1 | A browser stream is a response body on the request the browser made; the gateway serves no WebSocket (§1:3). | Kept. The browser's change stream is such a stream (§5). |
| ADR-0177 §1:1, §1:5, §1:6 | The browser reaches a closed enumeration of operations; the gateway supplies only a caller-owned deadline of its own; no per-browser scope. | Partially superseded: the enumeration gains the acts in the medium and the change stream, the gateway supplies the browser device's name, and a browser device reaches what its roles allow (§1, §2, §5). |
| ADR-0173 §1:1, §2:2–§2:3 | A streaming request is chunk frames then one terminal frame; a chunk's payload is `ReplyChunk`, text alone, with no sequence number. | Partially superseded for the change stream's chunks, which carry changes with their sequence numbers (§4). The reply stream is unchanged. |
| ADR-0131 | A notification travels to a device as an answer it asked for, on a connection kept for that alone, under a lease the device acknowledges. | Kept for notifications until they become messages (ADR-0292 §7:3). The change stream uses no lease (§4). |
| ADR-0292 §4:8–§4:10 | Three user-assigned roles; three routes; one connection per device; revoking closes it; admission by ADR-0124. | Partially superseded: "one connection" is one **session**, and a browser device is admitted by its gateway (§1, §3). |
| ADR-0293 §11:1 | The first build's devices fetch the change stream through the delivery poll. | Partially superseded when built: the change stream is one streaming method (§4). |

**What does not move.** ADR-0124 §4:1 obtains the *connecting* device's overlay
identity from the overlay agent and never from the peer; a gateway's connection is
still admitted that way, and the name it gives a browser device is no claim about the
connecting device. ADR-0131 §4:12–§4:13's per-device rules, and their loopback
treatment, govern notification delivery and stand. ADR-0099 §1's single principal
stands: a role is not a principal, and every device is the owner's.

**What exists.** The hub admits a remote client by ADR-0124's two facts and treats
the local socket as the user at the machine (ADR-0084 §1). A gateway admits browsers
on its own machine (ADR-0168) and on devices the owner listed (ADR-0174), and every
browser it admits reaches what the gateway's own device reaches, because nothing about
a browser crosses the wire. Notifications reach a device through a leased poll
(ADR-0131) and a browser through a response-body stream (ADR-0175). No device has a
role yet, and no `assistant chat` command exists.

## Decision

We will know a device as the machine the user admitted, of one of two kinds, check
every request against the roles the user gave that machine, and carry all of a
device's routes on one session, with the change stream as one streaming method on the
existing wire.

> **Normative.** §§1–6 govern every device, session, role and route an implementation
> builds for the hub's devices from this ADR on.

> **Normative.** A route that exists on `main` when this ADR is ratified and that
> §§1–6 rule against, a browser carrying its gateway's device's authority and the
> first build's delivery poll included, keeps working exactly as its own ADR decides
> it until the part of this ADR that replaces it is built.

### 1. What a device is

| Kind | Admitted by | Example |
| --- | --- | --- |
| **A hub device** | The hub, by ADR-0124's two facts | The machine running a gateway; a laptop using the command line remotely |
| **A browser device** | A gateway, by the overlay identity it obtains (ADR-0174 §3) | A phone's browser |

> **Normative.** A **device** is a machine the user admitted, and is a **hub device**,
> admitted by the hub by ADR-0124's two facts, or a **browser device**, admitted by a
> gateway by the overlay identity it obtains (ADR-0174 §3:1).

> **Normative.** Both kinds are devices in ADR-0292's sense, each with roles of its
> own.

As the owner ruled it:

> **Normative.** Listing a machine at a gateway (ADR-0174 §4:3) registers it at the
> hub under that gateway, as a browser device with no roles where it is not already a
> device, and that listing is the whole of its registration: there is no second
> enrolment.

> **Normative.** A machine is one device however many gateways list it and whether
> or not it is also a hub device, and a listing leaves the roles of a machine that is
> already a device as they are.

A laptop enrolled as a hub device and listed at another machine's gateway is that one
device, with the roles the user gave the laptop, which is §1's rule that a device is the
machine applied to a listing.

> **Normative.** The gateway names the browser device on every request it relays for
> it, and the hub accepts the name only for a browser device registered under that
> gateway.

The gateway is trusted to tell its browser devices apart, as it is already trusted to
admit them; it is not trusted to act as any other device.

> **Normative.** No session identity, session value or session token crosses the wire
> to the hub, as ADR-0168 §3:3 rules.

> **Normative.** A device is the machine, not a browser tab or a process: roles,
> labels and a conversation's devices name the machine.

Tabs and processes come and go, and two browsers on one machine are one device, so
ADR-0174 §4:5 stands.

As the owner ruled it:

> **Normative.** A browser on the gateway's own machine (ADR-0168 §2:2) is that
> machine's hub device, with its roles.

> **Normative.** The hub's own machine, through the local socket (ADR-0084 §1), is the
> user at the machine and holds every role.

That is how the first device is given its roles.

### 2. Roles

ADR-0292 §4:1's roles, each assigned by the user after pairing; pairing admits a
device and gives it none.

| Role | Allows |
| --- | --- |
| **The user's end of conversations**: in "my devices" (ADR-0293 §3:1), or chosen for one conversation (ADR-0293 §3:3) | In "my devices": being an end of every new conversation, and starting a conversation, which it is then an end of. In a conversation it is an end of: reading, and, unless it is an end there for reading only, writing, which is sending a message and deleting a message or the conversation (ADR-0292 §4:5) |
| **Source of commands and queries** | Commands and queries; changing "my devices" and a conversation's devices; assigning roles |
| **Host of spokes** | Hosting the assistant's sensors and actuators, placed on channels (ADR-0292 §2:7). None exists yet. |

> **Normative.** Each role allows what its row of the table above lists.

> **Normative.** Changing "my devices" or a conversation's devices needs the role of
> source of commands and queries; being an end of the conversation is not enough.

Changing who sees a conversation is a statement about audience (ADR-0293 §3:2), so it
needs the command role.

As the owner ruled it:

> **Normative.** Whether a device writes and reads, or only reads, is set with its "my
> devices" membership, and with its membership of a conversation where that differs.

A watch is added read-only.

> **Normative.** The hub checks every request against the roles of the device it comes
> from, by rule.

> **Normative.** A role is never inferred from what a device can reach.

As the owner ruled it:

> **Normative.** A browser device acts with its own roles and never with its gateway's:
> a phone's browser has the roles the user gave the phone, and a newly admitted browser
> can do nothing until it is given roles.

### 3. A session, not a socket

> **Normative.** One **session** per device carries all its routes.

> **Normative.** A session may use several physical connections, and what makes it one
> session is the device it belongs to, its roles and its cursor.

| Route | How it travels |
| --- | --- |
| **Acts in a medium** (write, start, delete, set devices) | A request |
| **Commands and queries** | A request |
| **The change stream** | A stream the device opens with its cursor (§4) |
| **Spoke traffic** | Not built; decided with the first device-hosted spoke |

> **Normative.** An act in a medium, a command and a query each travel as a request,
> and the change stream as a stream the device opens with its cursor (§4).

> **Normative.** How spoke traffic travels on a session is decided with the first
> device-hosted spoke.

> **Normative.** Each request and each change carries a **kind**, a structured field
> that says which route it is on, and the hub tells routes apart by kind, never by
> content.

> **Normative.** Revoking a device ends its session: its open streams close, its
> requests are refused, and it is removed as an end of every conversation.

> **Normative.** A browser device is revoked at the hub, and its gateway closes that
> browser device's streams.

### 4. The change stream

> **Normative.** The hub serves the conversation's change stream (ADR-0293 §5:10–§5:13)
> as one streaming method on the existing wire: the device asks for every change after
> its cursor, and the hub keeps the answer open and sends each change as it happens, in
> sequence order.

> **Normative.** The change stream is a streaming request as ADR-0173 §1:1 defines one,
> on a connection of its own, so ADR-0084 §3's one outstanding request per connection
> stands, and it needs no new protocol and no new dependency.

> **Normative.** Each chunk frame of the change stream carries a change, the current
> state or a heartbeat, and a change carries its sequence number; a reply stream's
> chunk stays ADR-0173 §2:2's `ReplyChunk`.

Every frame of the change stream answers the request that carried the cursor, so
ADR-0173 §1:4's rule that the hub writes only in answer to an outstanding request
stands; what moves is the chunk's payload, which ADR-0173 §2:2–§2:3 fixed while the reply
stream was the only stream.

> **Normative.** The device's cursor is its acknowledgement: the change stream holds no
> lease, and a device that drops reconnects with the last sequence number it applied.

> **Normative.** A device's stream carries only what the device may see: changes in
> conversations it is an end of, and changes to its own roles and devices.

As the owner ruled it:

> **Normative.** Sequence numbers run across the whole chat space, so a device sees
> gaps, and its cursor is the last number it applied.

> **Normative.** When a device becomes an end of a conversation, its stream sends that
> conversation's snapshot, as a new device gets one (ADR-0293 §5:13).

> **Normative.** When a device stops being an end of a conversation, its stream says
> so, and the device drops the conversation.

> **Normative.** The current state (ADR-0293 §8), "working…" and how the last
> activation ended, is pushed on the stream when it changes and read with a
> conversation on catch-up, and carries no sequence number, because it is not history.

> **Normative.** *Received* stays the answer to the write request, with the message's
> position (ADR-0293 §4:4).

> **Normative.** The stream carries a periodic heartbeat, so that both ends notice a
> dead connection.

> **Normative.** The change stream replaces the first build's polling (ADR-0293 §11:1),
> and notifications keep ADR-0131's leased delivery until they become messages
> (ADR-0292 §7:3).

### 5. The browser

The browser leg needs nothing new.

> **Normative.** The change stream reaches a browser as a response-body stream
> (ADR-0175 §1:1) on a request carrying its cursor, the shape ADR-0175 §4 uses for
> deliveries.

> **Normative.** The gateway relays the hub's stream for that browser device change
> for change, and authors nothing (ADR-0168 §1:3).

> **Normative.** A browser's acts, commands and queries are ordinary requests, and a
> browser request may resolve to the acts in the medium (ADR-0293 §11:2) and to the
> change stream besides the operations ADR-0177 §1:1 lists.

> **Normative.** A browser's admission is unchanged: the overlay identity or loopback,
> then the web session's two halves (ADR-0168 §6, ADR-0174 §4:1).

> **Normative.** The gateway serves no WebSocket (ADR-0175 §1:3), and whether it ever
> does is the voice milestone's decision.

A browser cannot set the session header on a WebSocket handshake, which is ADR-0175's
reason, and nothing here needs one literal two-way socket. The voice milestone owns the
question because live microphone upload is the one thing a browser can only do over a
socket on the gateway's HTTP/1.1. The evaluation's choice for that day is `websockets`
(sans-I/O, inside the existing gateway), with `wsproto` as the fallback.

### 6. Command line

> **Normative.** The command line opens the change stream when it follows a
> conversation, and makes ordinary requests otherwise.

An `assistant chat` command is that case; it does not exist today.

> **Normative.** The command line stays stateless between calls except for the cursor
> it is following.

> **Normative.** The command line, as a hub device, has its machine's roles: every role
> on the hub's own machine, and the laptop's roles on a laptop.

### 7. Relationship to earlier decisions

> **Normative.** This ADR supersedes ADR-0292, ADR-0293, ADR-0173, ADR-0168, ADR-0174,
> ADR-0175 and ADR-0177 in the scopes its header names, and no clause of any other ADR.

> **Normative.** This numbered draft records its replacements on the status line and in
> a dated header note of each ADR it supersedes in part, atomically with this ADR under
> ADR-0070 and ADR-0082, preserving their ratified bodies. Each replacement takes effect
> on this ADR's ratification, except ADR-0293's, which takes effect when the change
> stream is built.

The bars this ADR lifts take effect on ratification so that the lanes building the
session may build it; what those bars protected keeps working until then, under the
Decision's second clause.

| Earlier decision | Where it goes |
| --- | --- |
| ADR-0292 §4:8–§4:10, one connection per device and its gate | §1 (two kinds of device), §3 (a session) |
| ADR-0293 §11:1's delivery poll | §4 (the change stream) |
| ADR-0173 §2:2–§2:3, for the change stream's chunks | §4 (what a chunk carries) |
| ADR-0168 §3:3–§3:4, as they reach a browser device | §1 (the gateway names it), §2 (its own roles) |
| ADR-0174 §3:3's *no other record*, §4:4's bars | §1 (listing registers), §3 (revoking at the hub) |
| ADR-0175 §5:4, §6:4, as they reach a browser device | §1, §2 |
| ADR-0177 §1:1, §1:5, §1:6 | §1 (the name), §2 (roles), §5 (what a browser reaches) |

## Consequences

**What becomes clear.** A device is one thing whether it runs a command line or a
browser: a machine the user admitted, with roles the user gave it, checked by the hub
on every request. A phone's browser and the laptop running the gateway can be given
different roles, and a watch can be added read-only. One session carries all of a
device's routes without a new protocol or a new dependency: the change stream is a
streaming request like the ones the wire already carries, and the browser receives it
the way it already receives deliveries. A device that drops loses nothing; it
reconnects with its cursor.

**What it costs.** The hub keeps a registration for each browser device and a set of
roles for every device, and every request is checked against them. A gateway relays
the hub's stream for each browser device it serves. The browser's admission and the
gateway's streams are unchanged, so nothing is spent on a socket; WebSocket's cost
moves to the voice milestone. Until the session is built, browsers keep their gateway's
authority and devices keep polling.

**What follows from it.**

1. **Roles and registration**: browser devices registered under their gateway, roles
   assigned from the hub's own machine, and every request checked against them.
2. **The change stream**: the streaming method, the gateway's relay, and the command
   line following a conversation, replacing the first build's polling.
3. **Notifications as messages**, when they become messages (ADR-0292 §7:3), which
   retires ADR-0131's leased delivery.

**What stays open.** None of these is decided here.

- **How a gateway fans one hub stream out to several tabs of one browser device**, or
  opens one per tab: the implementation's.
- **Heartbeat interval and dead-peer timeout.**
- **The message vocabulary in detail**: the kinds of requests and changes, their
  fields and size bounds, decided with the first implementation.

**Out of scope.**

- WebSocket, live audio upload, and spoke traffic over the session: the voice
  milestone.
- Native apps and OS push notifications.
- Notifications moving onto the change stream: when they become messages.

## Alternatives considered

- **One physical socket per device**, WebSocket for the browser. Declined by the owner
  on 2026-10-04: it needs a superseding ADR for ADR-0175 and ADR-0168 §6, a new
  dependency and socket rules, for nothing a session does not already give. It is
  deferred to voice.
- **A multiplexed hub connection**, relaxing ADR-0084 §3. Not needed: the stream sits
  on its own connection. Revisit only if connection counts become a problem.
- **Keep leased delivery for the change stream.** Declined: a cursor already says what
  the device has, and a lease on select forces polling only while someone is watching.
- **A browser with its gateway's whole authority**, as today. Declined: the phone's
  browser and the laptop that runs the gateway are different machines, and the user
  gives them different roles.
- **Browsers enrolled at the hub directly.** Declined: the gateway already admits them,
  and a second enrolment would be a second credential for the same machine.
