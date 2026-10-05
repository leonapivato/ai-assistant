# The device session

**The question.** How does a device stay connected to the hub: how is it known, what may it
do, and how do the routes of ADR-0292 and the conversation's change stream (ADR-0293) reach
it?

This is the third proposal of the channel redesign
([#2578](https://github.com/leonapivato/ai-assistant/issues/2578)). ADR-0292 §4 gave each
device user-assigned roles, three routes and "one connection per device". The conversation
channel's first build runs on today's wire with polling; this proposal decides what replaces
the polling and what "connection" means. It rests on a transport evaluation of 2026-10-04
(the gateway, the hub's wire, ADR-0175, and the candidate WebSocket libraries).

## Baseline

| ADR | What it decides today | What this proposal would do |
| --- | --- | --- |
| ADR-0084 §3, §7 | The local API: a framed, versioned envelope; a connection carries one request at a time; the client is stateless and opens a connection per call. | Kept. The change stream is one more streaming method on a connection of its own (§4). |
| ADR-0124 | A device is admitted to the hub by two independent facts: its overlay identity and an enrolled credential. | Kept, for **hub devices** (§1). |
| ADR-0168 §3, ADR-0174 §3 | A browser is served by a gateway; a browser session carries the gateway device's whole authority; a remote browser's overlay identity is obtained from the overlay agent. | Amend §3's "whole authority": a browser acts as its own device, with its own roles (§1, §2). |
| ADR-0131 | A notification travels as an answer the device asked for, on a connection kept for that alone, under a lease the device acknowledges. | Kept for notifications until they become messages (ADR-0292 §7). The change stream uses no lease (§4). |
| ADR-0175 | A browser stream is a response body on the request the browser made; the gateway serves no WebSocket. | Kept. The browser's change stream is such a stream (§5). |
| ADR-0292 §4 | Devices have three user-assigned roles; three routes; one connection per device; admission by ADR-0124. | Amend: "one connection" is one **session**, and a browser is admitted by its gateway (§1, §3). |

## The change

### 1. What a device is

A **device** is a machine the user admitted. There are two kinds, and both are devices in
ADR-0292's sense, with roles of their own:

| Kind | Admitted by | Example |
| --- | --- | --- |
| **A hub device** | The hub, by ADR-0124's two facts | The machine running a gateway; a laptop using the command line remotely |
| **A browser device** | A gateway, by the overlay identity it obtains (ADR-0174 §3) | A phone's browser |

- **Listing a machine at a gateway registers it** at the hub as a browser device under that
  gateway, with no roles *(owner, 2026-10-04)*. The listing ADR-0174 already has is the
  registration; there is no second enrolment.
- **A browser device is registered at the hub under its gateway.** The gateway names it on
  every request it relays, and the hub accepts the name only for a browser device registered
  under that gateway. The gateway is trusted to tell its browsers apart, as it already is to
  admit them; it is not trusted to act as any other device.
- **The device is the machine, not the browser tab or the process.** Tabs and processes come
  and go; roles, labels and a conversation's devices name the machine. A browser on the
  gateway's own machine (ADR-0168 §2) is that machine's hub device, with its roles
  *(owner)*.
- **The hub's own machine**, through the local socket (ADR-0084, `0600`), is the user at the
  machine and holds every role. It is how the first device is given its roles.

### 2. Roles

ADR-0292 §4's roles, each assigned by the user after pairing; pairing admits a device and
gives it none.

| Role | Allows |
| --- | --- |
| **In "my devices"** | Being an end of new conversations (ADR-0293); starting a conversation, which it is then an end of; writing and reading in conversations it is an end of |
| **Source of commands and queries** | Commands and queries; changing "my devices" and a conversation's devices; assigning roles |
| **Host of spokes** | Hosting the assistant's sensors and actuators, placed on channels (ADR-0292 §2). None exists yet. |

- Changing who sees a conversation is a statement about audience, so it needs the command
  role, not just being an end.
- **Whether a device writes and reads, or only reads**, is set with its "my devices"
  membership, and with its membership of a conversation where that differs *(owner)*: a
  watch is added read-only.
- **Every request is checked against the device's roles**, by the hub, by rule. A role is
  never inferred from what a device can reach.
- **This replaces a browser carrying its gateway's whole authority** (ADR-0168 §3): a phone's
  browser gets the roles the user gave the phone, and a newly admitted browser can do nothing
  until given roles *(owner)*.

### 3. A session, not a socket

> One **session** per device carries all its routes. A session may use several physical
> connections; what makes it one is the device it belongs to, its roles, and its cursor.

| Route | How it travels |
| --- | --- |
| **Acts in a medium** (write, start, delete, set devices) | A request |
| **Commands and queries** | A request |
| **The change stream** | A stream the device opens with its cursor (§4) |
| **Spoke traffic** | Not built; decided with the first device-hosted spoke |

Each request and each change carries a **kind**, a structured field that says which route it
is on. The hub tells routes apart by kind, never by content.

**Revoking a device** ends its session: open streams close, requests are refused, and it is
removed as an end of every conversation. Revoking a browser device is done at the hub, and the
gateway closes that browser's streams.

### 4. The change stream

The hub serves the conversation's change stream (ADR-0293 §5) as **one streaming method on
the existing wire**: the device asks for every change after its cursor and the hub keeps the
answer open, sending each change as it happens, in sequence order.

- **No new protocol and no new dependency.** It is a streaming request like the ones ADR-0173
  already allows, on a connection of its own, so ADR-0084's one-request-per-connection rule
  stands.
- **The device's cursor is its acknowledgement.** There is no lease. A device that drops
  reconnects with the last sequence number it applied.
- **Only what the device may see**: changes in conversations it is an end of, and changes to
  its own roles and devices. Sequence numbers run across the whole chat space, so a device
  sees gaps; its cursor is the last number it applied *(owner)*.
- **Gaining or losing a conversation.** When a device becomes an end of a conversation, its
  stream sends that conversation's snapshot, as a new device gets one; when it stops being
  one, its stream says so and the device drops the conversation *(owner)*.
- **Current state** ("working…", how the last activation ended) is pushed on the same stream
  when it changes, and read with a conversation on catch-up. It carries no sequence number,
  because it is not history.
- **Received** stays the answer to the write request, with the message's position.
- **Keepalive**: the stream carries a periodic heartbeat, so a dead connection is noticed by
  both ends.

This replaces the first build's polling. Notifications keep ADR-0131's leased delivery until
they become messages.

### 5. The browser

The browser leg needs nothing new:

- The change stream reaches the browser as a **response-body stream** on a request carrying
  its cursor, the shape ADR-0175 already uses for deliveries. The gateway relays the hub's
  stream for that browser device, change for change; it authors nothing.
- Acts, commands and queries are ordinary requests.
- Admission is unchanged: the overlay identity or loopback, then the web session's two halves
  (ADR-0168 §6, ADR-0174).

**WebSocket is not used now.** A browser cannot set the session header on a WebSocket
handshake, which is ADR-0175's reason, and nothing here needs one literal two-way socket. It
becomes the voice milestone's decision, because live microphone upload is the one thing a
browser can only do over a socket on the gateway's HTTP/1.1. The evaluation's choice for that
day is `websockets` (sans-I/O, inside the existing gateway), with `wsproto` as fallback.

### 6. Command line

The command line opens the change stream when it follows a conversation (`assistant chat`)
and makes ordinary requests otherwise. It stays stateless between calls except for the cursor
it is following. As a hub device it has its machine's roles: every role on the hub's own
machine, the laptop's roles on a laptop.

## Options considered

**One physical socket per device**, WebSocket for the browser. Declined (owner, 2026-10-04):
it needs a superseding ADR for ADR-0175 and ADR-0168 §6, a new dependency and socket rules,
for nothing a session does not already give; it is deferred to voice.

**A multiplexed hub connection**, relaxing ADR-0084 §3. Not needed: the stream sits on its own
connection. Revisit only if connection counts become a problem.

**Keep leased delivery for the change stream.** Declined: a cursor already says what the
device has, and a lease on select forces polling only while someone is watching.

**A browser with its gateway's whole authority**, as today. Declined: the phone's browser and
the laptop that runs the gateway are different machines, and the user gives them different
roles.

**Browsers enrolled at the hub directly.** Declined: the gateway already admits them, and a
second enrolment would be a second credential for the same machine.

## Out of scope

- WebSocket, live audio upload, and spoke traffic over the session: the voice milestone.
- Native apps and OS push notifications.
- Notifications moving onto the change stream: when they become messages.

## What it leaves open

- **How a gateway fans one hub stream out to several tabs of one browser device**, or opens one
  per tab: the implementation's.
- **Heartbeat interval and dead-peer timeout.**
- **The message vocabulary in detail**: the kinds of requests and changes, their fields and
  size bounds, decided with the first implementation.
