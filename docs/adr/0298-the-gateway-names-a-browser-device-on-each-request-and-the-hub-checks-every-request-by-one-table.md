# 298. The gateway names a browser device on each request, and the hub checks every request by one table

- Status: Partially superseded by ADR-0302 (§5:1's table, in the addition alone)
- Date: 2026-10-05
- Scope: [#2578](https://github.com/leonapivato/ai-assistant/issues/2578), the channel redesign: how the device session ADR-0296 decides is built — the browser device's name on the wire, the requesting device inside the hub, registration, the route table, the refusal, the change stream's membership and heartbeat, the trust boundary and the cutover.
- Dependency: ADR-0296, ratified.
- Authorization: the dispatcher, under the owner's standing direction that mechanism design is the lanes' (ADR-0296 decides what a device session is; this ADR decides how it is built). The dispatcher assigned 0298.
- Partially superseded: 2026-10-08 by ADR-0302 — one scope. §5:1's table, in the
  addition alone: its command-or-query row also names `story_page`,
  `story_standing`, `add_story_note` and `move_story_members`, the story commands
  ADR-0300 §8:3 adds to `AssistantEngine`. No other row changes, and every other
  clause stands. This scoped replacement takes effect on ratification of ADR-0302.
  This reciprocal header record accompanies the numbered draft under ADR-0070 and
  ADR-0082; the ratified body below is preserved.
- **Partially supersedes** [ADR-0296](0296-a-device-has-one-session-and-a-browser-is-a-device-of-its-own.md) — **one scope.** **§1:5's *"the hub accepts the name only for a browser device registered under that gateway"*, read with the sentence under it that the gateway "is not trusted to act as any other device", as they reach a machine a gateway names for the first time**: that naming is the listing reaching the hub and registers the machine under that gateway (§4 below), so the hub refuses a gateway's name only for a registration the owner revoked under it, for the hub's own machine, or beyond the gateway's bound; and a gateway is trusted for its listing, so it can act as any device it names that the hub accepts, with that device's roles (§8 below). §1:3 and §1:4, the owner's rulings, stand as written, as does every other clause.
- **Partially supersedes** [ADR-0085](0085-the-promoted-engine-surface.md) — **one scope.** **§8a's *"these members, and no others"*, in the addition alone**: a `request` frame may carry one more member, `acting_for`, the name of the browser device the request is relayed for (§1 below); and §8b's worst case, which that member raises from 110 bytes to 261 inside the unchanged 512-byte reserve. §8a's correlation-id bound, §8b's reserve, §8c's limit and §8d's floor stand, and every earlier partial supersession stands.

## Context

**The question.** ADR-0296 decides what a device session is: a device is a machine the
user admitted, a hub device or a browser device; each has roles of its own; the hub
checks every request against them; one session carries all of a device's routes; and
the change stream is one streaming method on the existing wire. It leaves the
mechanism open. A read-only survey of `main` at `7c054184` found the places where an
implementation cannot start without a decision, and this ADR takes them in turn.

**What the tree has.**

- The remote listener admits a connection by ADR-0124's two facts, and
  `ai_assistant.wire.server.Admission.device` gives the connecting device's overlay
  identity, taken from the hub's own overlay agent and never from the peer. The local
  socket has no `Admission` (`admission is None` in
  `ai_assistant.wire.server._serve_requests`): it is the user at the machine (ADR-0084
  §1).
- The envelope has the members ADR-0085 §8a fixes, and
  `ai_assistant.wire.envelope.decode_envelope` refuses any other. The connect payload
  is bounded at `CONNECT_PAYLOAD_BYTES` (256) and is decided once per connection.
- An overlay identity is at most `MAX_OVERLAY_IDENTITY_BYTES` (128) bytes
  (`ai_assistant.service.overlay`).
- `ai_assistant.service.enrolment.EnrolmentStore` keeps enrolments in
  `<data_dir>/devices.db` and knows no kind, no role and no gateway;
  `ai-assistant-device` reaches it over `<data_dir>/admin.sock`, which is bound only
  where the remote listener is configured.
- A gateway holds one `AssistantEngine` client; nothing about a browser reaches the
  hub (ADR-0168 §3:3, superseded as it reaches a browser device by ADR-0296).
- The promoted surface has 68 methods (`ai_assistant.wire.surface.METHODS`); the
  conversation's surface (ADR-0293's lane B, PR #2696) adds nine more, among them
  `write_message`, whose `UserMessage.device_id` the peer asserts.
- `ai_assistant.core.protocols.ConversationStore.changes` filters by conversation ids
  its caller supplies; nothing reads "the conversations this device reads", and
  nothing removes a device from every set.
- A streamed chunk is recognised by `isinstance` against one class the Protocol's
  annotation names (`ai_assistant.wire.server._dispatch_stream`), and the client
  reads a stream with no idle deadline (`HubClient._stream_call` passes `idle=None`).

**What ADR-0296 leaves open, and where each is settled.**

| Open point | Settled in |
| --- | --- |
| How the gateway names a browser device on a request (§1:5) | §1 |
| How the requesting device reaches the checks that depend on a request's arguments | §2 |
| What the hub's own machine is called where it has no overlay identity | §3 |
| How listing reaches the hub as registration (§1:3), and revocation (§3:6–§3:7) | §4 |
| Which role each request needs (§2:4, §3:5) | §5 |
| What a refused request receives | §6 |
| What the change stream carries for membership and roles, and its heartbeat (§4:5–§4:11, "What stays open") | §7 |
| What a gateway may do, stated plainly | §8 |
| How enforcement starts when no device has a role yet | §9 |
| What reaches `core` | §10 |

## Decision

We will name a browser device in one bounded envelope member, carry the requesting
device through each request in a context value set by the wire server, check each
request against one table of methods, refuse with one new error, and build the change
stream's membership rules on the chat space's own sequence.

> **Normative.** §§1–10 govern every implementation of ADR-0296's device session.

### 1. The browser device's name on the wire

> **Normative.** A gateway names the browser device a request comes from in the
> `request` frame's `acting_for` member, and in no other place.

> **Normative.** `acting_for` appears on a `request` frame only, and is absent where
> the request is the connecting device's own.

> **Normative.** `acting_for` is text that is non-blank, equal to itself stripped of
> surrounding space, at most `MAX_OVERLAY_IDENTITY_BYTES` bytes encoded as UTF-8, and
> holds no character the codec escapes (`"`, `\`, U+0000–U+001F); a frame breaking
> any of these is undecodable and takes ADR-0084 §3's close.

The last condition makes the member's encoded size its UTF-8 size, so the reserve
arithmetic holds: counted as ADR-0085 §8b counts, the longest `kind` (11), the longest
method name on `main` (`set_notification_preferences`, 28), the correlation id (36),
the name (128) and 58 bytes of punctuation and member names come to 261 bytes, inside
the 512-byte reserve.

> **Normative.** The change that adds `acting_for` advances `PROTOCOL_VERSION`
> (ADR-0124 §9), because an older peer refuses a frame carrying it.

> **Normative.** A gateway names the browser device of a call it relays by setting an
> outbound context value around that `AssistantEngine` call — for a streamed call,
> around the whole iteration — and the wire client writes the value it holds when it
> writes the request frame into that frame's `acting_for`; no `AssistantEngine` method
> gains an argument for it.

> **Normative.** The outbound value lives in the same `core` module as the requesting
> device's context value (§2) and is distinct from it: the wire client reads the outbound
> value and never the requesting device, and the wire server reads `acting_for` and never
> the outbound value.

So the gateway keeps reaching the hub through `AssistantEngine` alone (ADR-0168 §1:2),
and a value set inside the hub can never leak onto an outbound frame, nor the reverse.

The connect frame is not used: it is bounded at 256 bytes and decided once per
connection, so a gateway would need a connection per browser device, and a request
is where ADR-0296 §1:5 puts the name.

### 2. The requesting device

> **Normative.** The wire server decides the **requesting device** of every request
> before dispatching it: the device `acting_for` names where the request carries the
> member and the hub accepts the name (§4), and otherwise the connecting device —
> the overlay identity `Admission.device` gives on the remote listener, and the hub's
> own machine (§3) on the local socket.

> **Normative.** The wire server sets the requesting device in a context value that
> lasts for the request — for a streamed request, the whole stream — and the engine
> reads it there, so no `AssistantEngine` method gains a device argument.

> **Normative.** The value is a frozen `RequestingDevice` in `core/types.py` carrying
> the device's id and the roles §4 records for it at dispatch.

> **Normative.** The context value, with its reader and its setter, lives in a `core`
> module of its own, and only the wire server sets it.

> **Normative.** Where nothing has set the context value — a caller inside the hub's
> own process — the requesting device is the hub's own machine.

> **Normative.** Work a request starts that outlives the request, an activation a
> message starts included, does not run as the requesting device: it is started with
> the context value unset.

Without this, a background task copies the context it was created in, and the
assistant's own work would be checked as the phone that wrote the message.

> **Normative.** Where the requesting device is not `hub`, the engine binds
> `UserMessage.device_id` to it: a message naming another device is refused (§6).

> **Normative.** Where the requesting device is `hub`, a message keeps the device it
> names.

> **Normative.** A peer writing a message names in `UserMessage.device_id` the id its
> device has under §§3–4 — its overlay identity, or `hub` for the hub's own machine and
> a browser on a gateway's loopback listener there — before the cutover (§9) as after
> it.

`UserMessage.device_id` is required on the conversation's surface as lane B builds it.
The local socket is the user at the machine, and until the cutover every request is
`hub`'s, so a message is recorded under the id its peer gives; because that is already
the id the hub will bind after the cutover, a repeat sent across it is the same
message (ADR-0293 §4:2).

ADR-0293 §4:1 makes a message id unique per device and ADR-0292 §5:1 states an author
by the hub, never by content; the conversation's surface as lane B builds it takes the
id from the peer, and this clause is the binding a later lane adds.

### 3. The hub's own machine

> **Normative.** The hub's own machine is the device whose id is `hub`, in every
> configuration, whether or not the hub has an overlay identity.

A stable id means "my devices" and a conversation's devices do not change when the
remote listener is turned on or off.

> **Normative.** The hub's own machine holds every role only as the requesting device
> of a request on the local socket with no `acting_for`, or of a caller inside the
> hub's own process, and on such a request it passes every check §5 lists, every end
> of every conversation included.

> **Normative.** No gateway may name `hub`, nor the hub's own overlay identity where the
> hub has one: such a name is refused (§6), so the hub's own machine reaches the hub
> through the local socket and its browsers through a gateway's loopback listener
> (ADR-0296 §1:8), and through nothing else.

> **Normative.** `hub` is never enrolled, registered or revoked, and the hub refuses
> it, and its own overlay identity where it has one, as the identity of an enrolment.

### 4. Registration and revocation

> **Normative.** The hub keeps a **device roster** in the enrolment record's file
> (`<data_dir>/devices.db`): each device's id, its kind, the roles of source of
> commands and queries and host of spokes it holds, and each registration of it as a
> browser device under a gateway.

The user's end of conversations is not a roster entry: it is a device's membership of
"my devices" and of conversations, which the conversation store keeps (ADR-0293 §3).
Keeping the roster beside the enrolments means ADR-0126's deletion takes it with the
enrolment record, first.

> **Normative.** A gateway's naming of a browser device is that listing reaching the
> hub (ADR-0296 §1:3): the first request on which a gateway names a machine registers
> it under that gateway, and no wire method or act at the hub is added for it.

The gateway names only what the owner listed there (ADR-0174 §4:3), and the hub cannot
see the gateway's configuration, so the request is the listing's one route to the hub.

> **Normative.** A registration of a machine that is not yet a device makes it a
> browser device with no role; a registration of a machine that is already a device
> leaves its roles as they are (ADR-0296 §1:4).

> **Normative.** The gateway of a registration is the connecting device of the request
> that made it: an enrolled hub device on the remote listener, and `hub` for a gateway
> on the local socket.

> **Normative.** The hub records each registration with its gateway and when it was
> made, logs it, and `ai-assistant-device` lists the registrations, so the owner can
> see every machine each gateway has named.

> **Normative.** The hub bounds the live registrations under one gateway at a figure
> the implementing change names, and refuses a naming beyond it (§6).

> **Normative.** Un-listing a machine at a gateway revokes nothing at the hub.

> **Normative.** The owner revokes, at the hub with `ai-assistant-device`, either one
> registration or a whole device.

> **Normative.** A revoked registration stays revoked: a gateway naming it again is
> refused (§6) and does not register it again, and only the owner's act at the hub
> restores it.

This is how a revoked enrolment already behaves (ADR-0124 §6), and it is what makes
ADR-0296 §1:5's "registered under that gateway" a check rather than a formality.

> **Normative.** Revoking a device revokes its enrolment, if it has one, and every
> registration of it; clears its roles; removes it from "my devices" and from every
> conversation's devices; and ends its open change streams (§7).

> **Normative.** A device re-admitted after revocation, by re-enrolment or by a
> restored registration, holds no role until the user gives it one (ADR-0296 §2:6).

> **Normative.** Revoking a gateway's device does not revoke the registrations of other
> devices under it; no connection can use them while the gateway is revoked.

> **Normative.** A device id may be added to "my devices" or to a conversation's
> devices only if the hub knows it as a device: `hub`, an enrolled hub device whose
> enrolment is live, or a browser device with a live registration.

> **Normative.** Roles are assigned in the first build only by `ai-assistant-device`
> on the hub's own machine; assignment by a device holding the command role is a
> later change.

> **Normative.** `<data_dir>/admin.sock`, and the roster acts it carries, are bound
> wherever the hub runs, not only where the remote listener is configured.

A gateway on the hub's own machine serves listed browsers whether or not the hub has a
remote listener, and those browser devices need roles.

### 5. The route table

> **Normative.** Every method on the promoted surface is classified in exactly one row
> of the table below — except `receive` and `receive_streaming`, which the kind of the
> input's target places in one of two — and the request needs what its row requires
> of the requesting device.

| Class | The requesting device must | Methods |
| --- | --- | --- |
| **Command or query** | hold the role of source of commands and queries | `abandon_goal`, `activation_stories`, `belief`, `beliefs`, `cancel_read`, `connect_account`, `connected_accounts`, `create_story`, `disconnect_account`, `dismiss_notification`, `episode_chunk`, `episodes`, `establish_destination_trust`, `establish_recipient_grant`, `export_decisions`, `export_invocations`, `export_reads`, `forget`, `forget_notification`, `forget_question`, `goals`, `grant`, `grantable_decisions`, `grantable_sources`, `guard`, `interrupted_questions`, `link_story`, `merge_stories`, `my_devices`, `notification_preferences`, `notifications`, `pending_confirmations`, `questions`, `recent_connection_acts`, `recent_decisions`, `recent_grants`, `recent_invocations`, `recent_reads`, `recent_recipient_grants`, `reprovision_account`, `resume`, `revoke`, `revoke_authorization`, `revoke_destination_trust`, `revoke_recipient_grant`, `set_notification_preferences`, `spend_totals`, `split_story`, `standing_authorizations`, `standing_destination_trust`, `standing_grants`, `standing_recipient_grants`, `stop_activation`, `stories`, `story`, `story_log`, `unguard`, `unlink_story`, `withdraw_clarification` |
| **Setting devices** | hold the command role, and name only devices the hub knows (§4) | `set_my_devices`, `set_conversation_devices` |
| **Forgetting a conversation** | hold the command role and, while the method still deletes the conversation (until ADR-0293 §11:4 is built), be its end for writing | `forget_conversation` |
| **Starting** | be in "my devices" | `start_conversation` |
| **Writing** | be the named conversation's end for writing | `write_message`, `delete_message`, `delete_conversation` |
| **Reading one** | be the named conversation's end for reading | `transcript`, `conversation` |
| **Reading many** | hold a role; the answer holds only conversations the device reads (§7) | `recent_conversations`, `chat_changes`, the change stream |
| **A legacy turn** | where the call names an existing conversation, be its end for writing and for reading; otherwise be in "my devices" for writing and for reading | `converse`, `converse_streaming`, `converse_spoken`, `answer`, `learn`, and `receive` and `receive_streaming` whose input's target is a `NewConversation`, or a `ChannelIdentity` whose `channel_type` is `conversation` |
| **Spoke traffic** | hold the role of host of spokes, which no device holds until the first device-hosted spoke (ADR-0296 §3:4) | `receive` and `receive_streaming` whose input's target is any other channel, an informational event included |
| **Notification poll** | be in "my devices" for reading, as the connecting device | `next_notification` |

The methods the conversation's surface adds are named as lane B names them; a method
renamed before it merges keeps its row.

A legacy turn is ADR-0293 §11:2's "for the conversation" and §11:5–§11:6's retiring
routes: input to the assistant, which a command never is (ADR-0292 §4:4), so it needs
the user's end rather than the command role, and both ends because it answers with the
assistant's reply. `resume` answers a parked confirmation with the user's authority
and stays a command until question messages are built (ADR-0293 §6). `stop_activation` is a command because ADR-0295 §1:4 accepts a stop only from a device
that may send commands.

> **Normative.** A request's kind (ADR-0296 §3:5) is its envelope `method`, and for
> `receive` and `receive_streaming` also the input's target — its `kind`, and a
> channel's `channel_type` — as validated; no row is chosen by any other part of a
> request.

ADR-0274 gives conversational text and an informational event the same payload
(`modality="text"`); what tells them apart is the target, which is a structured field.

> **Normative.** A method in no row is refused for every requesting device but `hub`.

> **Normative.** A test fails while any member of `METHODS` is in no row, or in more
> rows than the table above allows it.

> **Normative.** `next_notification` is the connecting device's own: a poll carrying
> `acting_for` is refused (§6), so its role check and ADR-0131's delivery slot key on
> the same device.

> **Normative.** The wire server checks the rows that need only the roster — the
> command role, the role of host of spokes, a known device and the notification
> poll's connecting device — before dispatch, and the engine checks every row that
> depends on membership of "my devices" or of a conversation, reading the requesting
> device (§2).

> **Normative.** A conversation's ends for this table are its devices as the
> conversation store holds them, and a conversation started before "my devices" was
> set keeps the devices it was started with.

> **Normative.** ADR-0151 §13 still keeps the connection operations off the remote
> listener, whatever the requesting device's roles.

A browser device reaches the connection operations only through a gateway on the
hub's own machine, and ADR-0177 keeps a credential to a loopback origin.

### 6. The refusal

> **Normative.** A request refused under this ADR fails with `DeviceRefusedError`, a new
> `AssistantError` subclass in `core/errors.py`, before its operation has changed
> anything; a registration §4 makes on that request, and its record, stand.

> **Normative.** `DeviceRefusedError` carries, as a public attribute, one of three
> reasons: the device named is not accepted under that gateway (a revoked registration,
> `hub`, the hub's own overlay identity, or a naming beyond §4's bound); the device holds
> no role; or its roles do not allow the request.

The owner can then tell "this phone was revoked" from "this phone has no role yet" from
"this phone has no role for that", and a device can tell when to drop what it holds
(§7).

ADR-0085 §10a makes the code the class name and the details its public attributes,
so the error crosses the wire with no table to keep.

> **Normative.** The change that adds `DeviceRefusedError` advances `PROTOCOL_VERSION`
> (ADR-0124 §9).

A refusal leaves the connection open: the gateway's connection serves other devices,
and ADR-0124 §8's close stays the answer to a revoked *connecting* device.

### 7. The change stream

> **Normative.** The change stream's sequenced changes are the chat space's changes
> (ADR-0293 §5:10), a device added to or removed from "my devices" or a conversation
> included, each with its sequence number.

> **Normative.** The change stream's unsequenced chunks are the current state (ADR-0296
> §4:9), the device's own roles, and the heartbeat.

ADR-0296 §4:3 lists a change, the current state and a heartbeat; §4:5 requires the
stream to carry the device's own roles too, and this ADR reads the two clauses together.
A device's roles are not a change to the chat space, so they take no sequence number, as
the current state takes none. A snapshot (ADR-0296 §4:7) travels inside the change that
calls for it, below.

> **Normative.** Each chunk of the change stream is one concrete class in
> `core/types.py` holding exactly one of those, so that
> `ai_assistant.wire.server._dispatch_stream` tells a chunk from the terminal value as
> it does for a reply stream.

> **Normative.** A change in a conversation reaches a device only if the device was that
> conversation's end for reading as the conversation's devices stood when the change
> was recorded, and a change that sets a conversation's devices, or "my devices",
> reaches every device in the set before it or after it.

> **Normative.** For a conversation the device does not read when the stream sends to
> it, the stream sends only the change that removed the device and the conversation's
> deletion, a deletion reaching every device that ever read the conversation, and never
> a message, snapshot or current state of it.

So a device sees the change that removed it (ADR-0296 §4:8), and a conversation's
devices are the user's statement of which screens may see it (ADR-0293 §3:3), which
holds against a device that was offline when the user made it: catching up from an old
cursor, a device gets a conversation it no longer reads as a removal or a deletion,
with none of the content from when it did read it.

> **Normative.** The change that makes a device a conversation's end for reading, where
> the stream sends it, reaches that device in the same chunk as the conversation's
> snapshot, so a device that has
> applied the change, and moved its cursor past it, has the snapshot.

> **Normative.** That snapshot is the conversation as it stood at that change: the
> messages recorded at or before its sequence number, a message deleted since shown as
> its marker (ADR-0293 §5:12), and nothing recorded after it.

> **Normative.** The snapshot holds the newest of those messages that fit, with the
> change, within the contract limit (ADR-0085 §8c), shortened from its oldest end and
> to none if need be, and the device loads older messages by reading the transcript
> (ADR-0293 §5:13).

So the chunk always fits, and a cursor never stops on a snapshot too large to send.

A device catching up from far behind therefore receives, for each interval in which it
read a conversation, the snapshot at the interval's start, the changes inside it, and
the change that ended it, and nothing recorded while it was not an end. A device whose
connection drops between the change and its snapshot cannot exist, because they are
one chunk.

> **Normative.** The stream sends the device's roles when it opens and whenever they
> change.

> **Normative.** The device's roles and the heartbeat are written by the hub's session
> layer — the wire server over the roster — and the changes, with their snapshots, and
> the current state by the engine.

> **Normative.** The heartbeat interval is 15 seconds and the dead-peer timeout 45
> seconds, fixed in `wire` and not configurable, so that changing either is a protocol
> change.

Hub and client speak one `PROTOCOL_VERSION` exactly (ADR-0084 §3), so a constant both
read cannot disagree, where two settings on two machines could. That is ADR-0175 §8's
reason for one figure rather than two, applied across the hop.

> **Normative.** The hub writes a heartbeat on a change stream whenever 15 seconds pass
> without a chunk.

> **Normative.** The client reads a change stream with the dead-peer timeout as its idle
> deadline, closes it when that passes with no frame, and reconnects with its cursor.

> **Normative.** The hub abandons a change stream whose write does not drain within the
> dead-peer timeout, and on a TCP connection it sets the socket's user timeout to that
> figure where the platform offers one.

A heartbeat leaves unacknowledged data whenever the peer is gone, so the user timeout
turns a silent peer into a closed connection within the timeout; on the local socket
the kernel reports a closed peer at once.

> **Normative.** Revoking a hub device closes its connections with no further frame,
> its change streams' among them, as ADR-0124 §8 rules.

> **Normative.** Revoking a browser device ends each of its change streams on a
> gateway's connection that is still admitted with `DeviceRefusedError`, and the
> gateway ends that browser device's streams (ADR-0296 §3:7).

> **Normative.** A device refused the change stream or `chat_changes` with the reason that
> it holds no role drops every conversation it holds, as if it had seen the change that removed it
> from each (ADR-0296 §4:8).

So a device that lost its last role while disconnected still drops what it held, and
§2:6's "can do nothing until given roles" holds for it.

> **Normative.** A change stream already open filters each change as this section
> rules and is ended only by revocation, by the dead-peer timeout or by its device.

### 8. The trust boundary

> **Normative.** A gateway naming a browser device acts with that device's roles, and a
> request that names none acts with the gateway's own device's roles.

> **Normative.** A gateway acts with every role only where it is on the hub's own
> machine, on the local socket, for a browser on its loopback listener.

What a gateway can do follows, and this ADR states it rather than leaving it to be
discovered, and records it as the partial supersession of ADR-0296 §1:5 its header
names. The hub cannot see a gateway's listing, so a gateway's naming is the listing
(§4), and a machine already a device keeps its roles when listed (ADR-0296 §1:4, the
owner's ruling). **A compromised gateway can therefore act as any device it names that the hub
accepts — every device except `hub`, the hub's own overlay identity, and devices whose
registration under that gateway the owner has revoked — with that device's roles.**
It is not limited to the machines its owner listed there, because no record at the hub
says which those are. It cannot act as the hub's own machine, and it cannot assign a
role (§4). This is no wider than today's, where every browser a gateway admits carries
the gateway's device's whole authority and every enrolled device reaches the whole
surface; the registration log and listing (§4) are how the owner sees a gateway naming
a machine it was not given.

### 9. The cutover

> **Normative.** No device's roles are checked until one change switches enforcement
> on, and that change lands after the roster, its acts on `ai-assistant-device`, the
> wire server's checks and the engine's checks (§5, and §2's binding of
> `UserMessage.device_id`) have all merged.

> **Normative.** Until that change, the requesting device of every request is `hub`, so
> the wire server's and the engine's checks are built and tested but refuse nothing.

> **Normative.** The change that switches enforcement on is the one that makes the wire
> server set a requesting device other than `hub`.

> **Normative.** At the cutover every enrolled device and every registered browser
> device holds no role, because a role is never inferred from what a device could reach
> before (ADR-0296 §2:5).

> **Normative.** The cutover's operating procedure gives the roles from the hub's own
> machine: the roles of source of commands and queries and host of spokes with
> `ai-assistant-device`, and "my devices" and conversations' devices through the local
> socket, which holds every role.

So remote command lines, remote gateways and their browsers are refused from the
moment enforcement is deployed until the owner gives them roles, and the hub's own
machine keeps working throughout. A browser device is registered by its first refused
request, so it is known, and can be added to "my devices", once it has tried once.

### 10. What reaches `core`

> **Normative.** `core/types.py` gains `RequestingDevice` (§2), the roles the roster
> holds as one enum, and the change stream's chunk class (§7).

> **Normative.** A `core` module of its own gains the two context values, the requesting
> device's (§2) and the outbound name a gateway sets (§1), each with its reader and
> setter.

> **Normative.** `core/errors.py` gains `DeviceRefusedError` (§6).

> **Normative.** `ConversationStore` gains three operations: the changes after a cursor
> that one device may see under §7, each adding change with its snapshot as of that
> change, the conversations one device reads, and the
> removal of one device from "my devices" and every conversation's devices with each
> change recorded.

> **Normative.** `AssistantEngine` gains the change stream as one streaming method
> (ADR-0296 §4:1), whose name and signature the change that adds it decides.

> **Normative.** Each `Protocol` change above lands as a unit with its conformance
> coverage, its canonical fake and its primary implementation (ADR-0137 §2:1).

> **Normative.** The seam between the wire server and the roster is a local `Protocol`
> in `wire`, implemented in `service`, as `Admission` is, and not `core/protocols.py`
> surface.

### 11. Relationship to earlier decisions

> **Normative.** This ADR supersedes ADR-0296 and ADR-0085 in the scopes its header
> names, and no clause of any other ADR.

> **Normative.** This numbered draft records its replacements on each superseded ADR's
> status line and in a dated header note, atomically with this ADR under ADR-0070 and
> ADR-0082, preserving their ratified bodies; each replacement takes effect on this
> ADR's ratification.

ADR-0124 §4:1 is untouched: `acting_for` names the device a request is for, never the
connecting device, whose identity still comes only from the hub's overlay agent.
ADR-0131 §4's bar on a device argument to `next_notification` is kept by §5's refusal
of `acting_for` there. Apart from §1:5, ADR-0296 is read, not amended: §3 and §8 read
its §1:9, §7 reads its §4:3 with §4:5, and §4 reads its §1:3 as the request carrying the
listing.

## Consequences

**What becomes clear.** Every request has one requesting device, decided by the wire
server from a member the hub bounds and a registration the hub keeps; one table says
what each method needs; one error says why a request was refused; and the change
stream's membership rule is the chat space's own sequence read as of each change. No
`AssistantEngine` signature gains a device argument.

**What it costs.** Two protocol versions, one for the envelope member and the error and
one for the change stream. A roster beside the enrolments, and an admin socket on every
hub. A table to keep in step with the surface, held by a closure test. An outage for
every remote device at the cutover, until the owner gives roles. A gateway's naming is
trusted (§8).

**Lane order, as guidance and not a rule.**

1. **Roster** (`service/`): kinds, registrations, the two roster roles, revocation, the
   admin socket's acts and its binding everywhere.
2. **Device-scoped reads** (`memory/`, with the `ConversationStore` triad): the changes
   a device may see as of each change, the conversations a device reads, removing a
   device from every set. After lane B merges, since both widen the Protocol.
3. **Wire session seam and gate** (`wire/`, `core/`): `acting_for`, the requesting
   device and its context value, the route table and its closure test, the local seam
   `Protocol`, `DeviceRefusedError`, the version.
4. **Orchestration checks** (`orchestration/`): the membership rows of §5, binding
   `UserMessage.device_id`, starting outliving work with no requesting device — inert
   until the cutover, since every request is still `hub`'s.
5. **Enforcement** (`service/`, `wire/`): the seam's implementation on both listeners,
   refusal by registration, revocation ending sessions and removing memberships, and the
   wire server setting the real requesting device — the cutover.
6. **The change stream** (`core/`, `orchestration/`, `wire/`): the streaming method,
   its chunk class, the heartbeat and the client's idle deadline; the version, and the
   engine-side filter over `ConversationStore.device_changes`, whose as-of membership
   stays as merged, that keeps a conversation the device no longer reads to its removal
   and deletion notices.
7. **The gateway's relay** (`interfaces/gateway/`): naming browser devices, relaying the
   stream change for change, fanning a notification only to browser devices in "my
   devices" for reading.
8. **The command line following a conversation** (`interfaces/`).

**What stays open.** How a gateway fans one hub stream to several tabs of one browser
device; how a gateway learns which browser devices may receive a notification it
fans out, until notifications become messages; the bound on registrations per gateway;
and every name this ADR leaves to the change that adds it.

## Alternatives considered

- **The name in the connect frame.** Declined: 256 bytes, decided per connection, so a
  gateway would hold a connection per browser device, and ADR-0296 §1:5 names it per
  request.
- **A device argument on every method.** Declined: some eighty signatures, a Protocol
  change for each, and a value a peer asserts in a payload, which ADR-0124 §4 refuses
  for the connecting device's identity and this ADR keeps out of payloads too.
- **A wire method by which a gateway reports its listing.** Declined: it buys nothing a
  first naming does not — the hub cannot check the report any more than it can check a
  naming — and it is one more method on the promoted surface.
- **A registration the owner confirms at the hub**, for every machine or only for one
  that is already a device. Declined: ADR-0296 §1:3, the owner's ruling, makes the
  listing the whole of a browser device's registration, with no second enrolment, and
  §1:4 keeps an existing device's roles when it is listed. It is the one mechanism that
  would hold a compromised gateway to the machines its owner listed, and adopting it is
  a change to those rulings.
- **Naming an existing device needs the gateway to hold the command role.** Declined
  for the same reason: it makes a listing at such a gateway register nothing, which
  §1:3–§1:4 do not allow.
- **Giving every existing enrolment every role at the cutover.** Declined: that infers
  a role from what a device could reach, which ADR-0296 §2:5 forbids.
- **The hub's machine named by its overlay identity.** Declined: its id would change
  when the remote listener is turned on or off, and a hub with no overlay would have
  none.
- **Heartbeat and timeout as settings.** Declined: they are read on both ends of a hop,
  possibly on two machines, and only a protocol constant cannot disagree with itself.
