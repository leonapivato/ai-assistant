# 378. Only a gateway the owner marked names a device, a naming reaches only a browser device and makes no link, and nothing is surer than the device it came through

- Status: Proposed
- Date: 2026-11-24
- Scope: decision D3 of milestone 21, "Every call checked" (acceptance
  [#3678](https://github.com/leonapivato/ai-assistant/issues/3678), lanes
  [#3679](https://github.com/leonapivato/ai-assistant/issues/3679)), closing
  [#3665](https://github.com/leonapivato/ai-assistant/issues/3665). It decides who may name another
  device on a request (§2), which devices a naming reaches (§3), what a named request is read as
  (§4), that no naming makes a link (§5), the hub's own machine (§6), what is recorded (§7), and the
  wire and the stores (§8). §9 records what it does to earlier decisions, §10 the contract changes
  it would need, §11 what it leaves to others, and §12 what it settled where the rulings left a point
  open.
- Authorization: the owner's words of 2026-11-24, verbatim. "yes agreed, but its milestone 21 right,
  not 2" answered the scope as #3678 records it, put with six picks of the coordinator's; the one
  that bears here was put as "#3665 is in: a device cannot be read as another device because a
  request names it. It needs a decision first, amending ADR-0298." "Yes, go" answered "Shall I post
  the batch issue and start D1, D2, D3 and B1". Those answers accepted the outcome #3678 records ("A
  device is itself") and ruled no mechanism: every mechanism here is this decision's (§12). The
  coordinator assigned 0378 and ratifies it, under the owner's delegation, once its reviews are green.
- **Contract-surface decision; a decision only.** This document changes no Protocol, type, field or
  code. It decides which device a request acts as and how a message's sender is read, which bounds
  the `core` types and stored shapes lane B7 of #3679 changes (§10), so it takes the adversarial and
  the architecture review.
- **Partially supersedes** [ADR-0298](0298-the-gateway-names-a-browser-device-on-each-request-and-the-hub-checks-every-request-by-one-table.md)
  (§4:2, §4:3's second limb, §4:4, §6:2's first reason and §7:18, each in the addition alone, and
  §8:1's first limb), [ADR-0296](0296-a-device-has-one-session-and-a-browser-is-a-device-of-its-own.md) (§1:3, as
  it reaches a listing at a device that is no gateway or of a hub device, and §1:4's "whether or not
  it is also a hub device", as it reaches a listing) and
  [ADR-0366](0366-a-person-is-one-identity-the-hub-links-accounts-to-code-decides-who-sent-an-input-and-how-sure-it-is-and-a-persons-label-holds-for-one-work.md)
  (§4:1 and §5:6, each for a hub chat message that came through a device other than the one it is
  written from) and [ADR-0377](0377-a-cards-tap-and-the-lines-stop-are-read-through-the-link-they-arrived-by-a-tap-answers-only-at-the-level-its-call-needs-and-an-answer-records-who-tapped-and-how-sure.md)
  (§2:4, for a tap that came through a device other than its requesting device), as §9 records.

## Context

ADR-0298 lets a gateway name the browser device a request comes from in `acting_for` (§1:1). The
hub cannot see a gateway's listing, so a first naming is the listing and registers the machine
(§4:2), and "a gateway naming a browser device acts with that device's roles" (§8:1). ADR-0298 §8
accepted that a compromised gateway "can act as any device it names that the hub accepts".

**What the tree has at `4784219fe`.** `Gateway._acting_for` in
`src/ai_assistant/interfaces/gateway/server.py` names the hosted browser device on the hosted
listener and the overlay identity of a remote browser otherwise. `HubRoster.requesting_device` in
`src/ai_assistant/service/roster.py` takes the device `acting_for` names through
`DeviceRegistry.accept_naming` in `src/ai_assistant/service/enrolment.py`, which refuses only a
reserved name (`hub`, the hub's own overlay identity), a registration the owner revoked under that
connecting device, and a naming past the per-gateway bound; the roster also refuses while a
revocation is in flight. Nothing asks whether the connecting device is a gateway, or whether the
name is an enrolled device. Every first naming registers the machine, and `DeviceLinks` in
`src/ai_assistant/service/links.py` links each registered machine to the owner by the `device` act.
`DeviceChecks.writing_message` in `src/ai_assistant/orchestration/device_checks.py` binds a
message's device to the requesting device, save where that is `hub` (ADR-0298 §2:7, §2:8). The hub
chat's reader reads each message's sender from the device it is written from alone
(`chat_account`, `sender_of` in `src/ai_assistant/orchestration/work_facts.py`), the only place a
sender is read from a device.

**What #3665 drove on a scratch system.** An enrolled device with no role, its link lowered to none,
named a second enrolled device holding the command role; it then listed the links, withdrew the
lowering of its own link, and wrote a message recorded as the owner's at normal. The same device
named a new id, which registered it and linked it to the owner with no act of the owner's. The only
trace was `device_registered`. Each step is ADR-0298 as ruled; the composition is the defect.

**The readings weighed.** #3665 offered three: the level as the lower of the connecting and the named
device's; naming only by a device the owner marked as a gateway; and no naming of an enrolled device.
The coordinator's reading took the second and third with the first as a floor, and asked that the web
door keep working as it does (ADR-0327). This decision takes all three, each for its own part: the
mark decides who may name (the roles), the bar on enrolled devices decides who may be named, and the
lower level decides how sure a message is. Alone, the level does not close the driven case, because
no level gates the owner's acts on links (ADR-0373 §4:5).

## Decision

We will let only the hub's own machine and an enrolled device the owner has marked as a gateway name
a device, let a naming reach only a browser device, read a message that came through one device for
another as no surer than either device's link, and link a browser device by the owner's act that gives
it a role, never by a naming.

### 1. Status and scope

> **Normative.** No lane implements against this decision before it merges `Accepted` (golden rule
> 5, ADR-0015 §5).

> **Normative.** This decision admits no one, and gives no person other than the owner any act or
> standing.

Lane B7 of #3679 builds it.

### 2. Who may name a device

> **Normative.** A request may carry `acting_for` only where its connecting device is the hub's own
> machine on the local socket, or an enrolled hub device the owner has marked as a **gateway**. The
> hub refuses a request carrying it from any other connecting device with `DeviceRefusedError` and
> the reason that the device named is not accepted (ADR-0298 §6:2), before it registers or dispatches
> anything.

> **Normative.** The owner marks a device as a gateway, and withdraws the mark, only at the hub with
> `ai-assistant-device`, as roles are given (ADR-0298 §4:14). No wire method, request, model, task,
> setting or upgrade marks one.

> **Normative.** Only a hub device whose enrolment is live can be marked. Revoking its enrolment ends
> the mark, and a device enrolled again is no gateway until the owner marks it again.

> **Normative.** Withdrawing a mark refuses the device's later requests that carry `acting_for`, and
> ends each change stream open on its connections for a device it named, with `DeviceRefusedError`, as
> revoking a browser device does (ADR-0298 §7:16). It revokes no registration under the device, and
> none can be used while the device is unmarked.

> **Normative.** `ai-assistant-device` lists which devices are marked as gateways, beside the
> registrations under each (ADR-0298 §4:5).

> **Normative.** The mark is not a role: no row of ADR-0298 §5:1's table reads it, the change stream
> does not carry it, and a marked device's own requests act with its own roles.

Revoking the gateway's device still closes its connections outright (ADR-0298 §4:10, §7:15).

### 3. Which devices a naming reaches

> **Normative.** A naming reaches only a browser device. The hub refuses, as not accepted, a name
> that is `hub` or the hub's own overlay identity (ADR-0298 §3:3) and a name the hub knows as a hub
> device, whether that device's enrolment is live or revoked.

> **Normative.** A refused naming registers nothing, and changes no registration, role or link.

> **Normative.** Once a machine is enrolled, no naming reaches it, its earlier registrations as a
> browser device included.

> **Normative.** Enrolling a machine ends each change stream open for it on a gateway's connection,
> with `DeviceRefusedError`, before the stream sends anything recorded after the enrolment.

> **Normative.** The hub logs each naming it refuses under one fixed event name, with the connecting
> device, the name and why it was refused.

A hub device has a connection and a credential of its own (ADR-0124 §6), so it can always be itself
and never needs another device to speak for it. A browser device has no connection but its gateway's.

### 4. What a named request is read as

> **Normative.** A request that names a browser device, from a connecting device §2:1 admits, acts
> with the named device's roles (ADR-0298 §8:1, ADR-0296 §2:6).

> **Normative.** The hub chat records, on every message, the device it **came through**: the
> connecting device of the request that wrote it, `hub` on the local socket. The device it is written
> from stays the one ADR-0298 §2:7 and §2:8 decide.

> **Normative.** Where a hub chat message came through a device other than the one it is written
> from, its sender is read from both devices' links: the identity both tie, at the lower of the two
> links' levels (ADR-0366 §5:3). Where either device has no standing link, or the two tie different
> identities, the message is from no identified person, at none.

> **Normative.** No signal combined under ADR-0366 §5:4 raises such a message above the level of the
> link of the device it came through.

> **Normative.** Where either read gets no answer, the message is one whose links cannot be read
> (ADR-0374 §2:1), and ADR-0374 rules it as written.

> **Normative.** A message that came through the device it is written from is read as ADR-0366 §4:1
> and §5:6 rule, unchanged.

> **Normative.** A tap on the hub page whose request came through a device other than its requesting
> device is read from both devices' hub chat accounts, as §4:3 to §4:5 read a message: the identity
> both links tie, at the lower level, and otherwise no identified person, at none (ADR-0377 §2:4).

So a lowering of the connecting device's link binds every message recorded, and every tap read,
through it after the lowering (ADR-0373 §2:9). A level is about who wrote a message, not about what a request may do: the
roles a request acts with are bounded by the mark (§2) and by revocation, and no level gates the
owner's acts on links (ADR-0373 §4:5). ADR-0374 §3:1's exception is unchanged: no gateway may name
`hub`, so a message recorded from `hub` always came through `hub`.

### 5. No naming makes a link

> **Normative.** No naming or registration makes, restores or keeps a link, and no member of
> `AssistantEngine` does (ADR-0373 §6:1).

> **Normative.** The act that links a browser device to the owner's identity is the owner's act at the
> hub, with `ai-assistant-device`, that gives it a roster role (ADR-0298 §4:1, §4:14). That link stands
> only while the device has a live registration and holds a roster role (ADR-0373 §6:3).

> **Normative.** At the upgrade, a browser device's standing `device` link stands where §5:2 holds and
> is ended where it does not, with no act of the owner's.

Giving a roster role is the owner's explicit act at the hub's own machine, as enrolment is (ADR-0124
§6:1), under decisions that treat every device as the owner's (ADR-0099 §1, ADR-0296 §2), so it is an
act ADR-0373 §6:2 lets a link be recorded from. A naming is not: the hub cannot tell a listing from a
forged one. An end of "my devices" or of a conversation is set through `AssistantEngine`, which makes
no link, so a browser device that is only such an end writes as an unidentified sender until the
owner gives it a roster role.

### 6. The hub's own machine

> **Normative.** A message written on the local socket with no `acting_for` keeps the device it names
> (ADR-0298 §2:8), and came through `hub` (§4:2), so §4:3 reads it.

The local socket is the owner at the machine and holds every role (ADR-0084 §1, ADR-0298 §3:2), and
it withdraws any lowering (ADR-0373 §5:1), so binding its label would take nothing from anyone who
could misuse it. What the survey found is that the label could lift a message above `hub`'s own link,
or onto a device the owner lowered apart; §4:3 closes both, so a label now only lowers.

### 7. What is recorded and shown

> **Normative.** The episode records, for each hub chat message an input holds, the device it came
> through beside the device it is written from, fixed as its sender is (ADR-0368 §2:6).

> **Normative.** Inspecting a work shows, for each message that came through a device other than the
> one it is written from, the device it came through.

### 8. The wire and the stores

> **Normative.** `acting_for`, the route table and `DeviceRefusedError`'s reasons are unchanged: every
> refusal §2 and §3 add carries the reason that the device named is not accepted.

> **Normative.** The device roster gains the gateway mark, and the hub chat's message record and the
> episode's record of a message gain the device it came through. Each ships its upgrade under
> ADR-0326 §4: a roster from before marks no device, and a message from before reads as having come
> through the device it is written from.

> **Normative.** The change that adds the device a message came through to a type the wire carries
> advances `PROTOCOL_VERSION` in that change (ADR-0124 §9:2).

Inspection reaches the owner over the wire (§7:2), so the wire version moves with B7. The mark is
set and read at the hub alone, through the admin socket, and crosses no promoted method.

### 9. Relationship to earlier decisions

> **Normative.** This numbered draft records its replacements on the status lines of ADR-0298,
> ADR-0296, ADR-0366 and ADR-0377 and in a dated header note on each, atomically with this ADR under ADR-0070
> and ADR-0082, preserving their ratified bodies. Each replacement takes effect on this ADR's
> ratification.

Superseded:

| Clause | Becomes |
| --- | --- |
| ADR-0298 §4:2 | A naming registers a machine only from a connecting device §2:1 admits, and only a machine §3:1 lets a naming reach |
| ADR-0298 §4:3, second limb | A machine already a device is registered only where it is a browser device; a hub device never is (§3:1, §3:3) |
| ADR-0298 §4:4 | The gateway of a registration is `hub` or an enrolled hub device the owner marked (§2:1) |
| ADR-0298 §6:2's first reason, in the addition alone | Its cases also hold a naming from a device that is no gateway and a name that is a hub device (§2:1, §3:1) |
| ADR-0298 §7:18, in the addition alone | An open change stream is also ended by withdrawing the mark of the gateway that named its device, and by enrolling that device (§2:4, §3:4) |
| ADR-0298 §8:1, first limb | Only a connecting device §2:1 admits names a device, and only a browser device (§4:1) |
| ADR-0296 §1:3, as it reaches a listing at a device that is no gateway or of a hub device | Such a listing registers nothing (§2:1, §3:1) |
| ADR-0296 §1:4's "whether or not it is also a hub device", as it reaches a listing | A hub device is reached only through its own connection (§3:1) |
| ADR-0366 §4:1 and §5:6, for a hub chat message that came through a device other than its own | Both links are read; the identity both tie, at the lower level (§4:3, §4:4) |
| ADR-0377 §2:4, for a tap that came through a device other than its requesting device | Both devices' hub chat accounts are read, as for a message (§4:7) |

Taken, with nothing superseded: ADR-0373 §6:2 and §6:3 (the role act links a browser device, §5:2);
ADR-0374 §2:1 and §3:1 (§4:5, §4 prose). Read through and standing, each as written: ADR-0298 §2:1,
§2:7, §2:8, §3, §4:9, §4:12, §4:14 and §7:16; ADR-0296 §1:8 and §2:6; ADR-0327 §10:2, §10:5 and
§10:6; ADR-0373 §4:5 and §6:1; ADR-0124 §4:1.

### 10. The contract changes building it would need

Named so B7 is scoped, and made by none of this decision.

- **`core/types.py`:** the engine learns the connecting device of each request it serves, so it can
  record §4:2 without reading the wire; the likely shape is a field on `RequestingDevice` beside the
  id and roles ADR-0298 §2:3 names, set by the wire server alone (§2:4). The hub chat's message and
  the episode's message record gain the device it came through (§7:1). No Protocol method changes.
- **`service/`:** the roster's mark and its acts on `ai-assistant-device` (§2); `accept_naming`'s two
  refusals and their log (§2:1, §3); `DeviceLinks` following §5:2 instead of the registration.
- **`orchestration/`:** the sender read of §4:3 to §4:5, a tap's read of §4:7, and inspection
  (§7:2).
- **The stores and the wire:** the upgrades and the version of §8:2 and §8:3.

### 11. What this decision leaves to others

- **ADR-0367, ADR-0376 and ADR-0379:** what a level permits, the check, lines and grants.
- **ADR-0377:** taps and `/stop`, save which links a tap through a named device is read from (§4:7).
- **#3649 and #3658:** the durable admission generation, and the order of a first link's write.
- **Milestone 5:** enrolling a second person's devices, and what a gateway one of them runs may name.
- **A later decision:** marking a gateway from anywhere but the hub, and the web door's sign-in.

> **Normative.** This decision may not be cited to settle any matter the list above leaves to another.

### 12. What this decision settled where the rulings left a point open

Each is this decision's, not an owner ruling:

- **§2**, that naming needs the owner's mark at the hub; that `hub` names without one; that the mark is
  not a role and ends with the enrolment; and that withdrawing it, or enrolling a named machine, ends
  the streams opened by naming it (§2:4, §3:4).
- **§3:1**, that a naming never reaches a hub device, live or revoked. This takes from ADR-0296 §1:4,
  an owner's ruling of 2026-10-04, the case of an enrolled machine's browser served by another
  machine's gateway: such a browser now reaches the hub through its own machine's gateway or not at all.
- **§4:3**, the lower of the two levels, and no identified person where the links disagree; and
  **§4:7**, the same for a tap on the hub page.
- **§5:2**, that a browser device's link rests on a roster role the owner gave it at the hub, and not
  on a membership, which `AssistantEngine` sets.
- **§6**, that the local socket's label stands and is bounded by `hub`'s link rather than bound.
- **§8**, that no refusal reason is added, and that the wire version moves for the record.

## Consequences

- #3665's first case is refused at its first request, since the device is no gateway (§2:1); were it
  one, naming an enrolled device is refused too (§3:1). Its second case registers nothing (§3:2); a
  marked gateway's first naming registers an inert device with no link (§5).
- The web door is unchanged where its gateway runs on the hub's machine: it connects as `hub`, which
  needs no mark; the hosted device holds the roster role ADR-0327 §10:6 has the owner give it at the
  hub, so it stays linked (§5:3), and its
  messages are the owner's at the lower of its link and `hub`'s. Lowering `hub`'s link now lowers the
  web door too. A door whose gateway connects over the remote listener needs that device marked.
- A gateway on another machine stops naming at the upgrade until the owner marks its device, so the
  deploy that carries B7 lists the enrolled devices holding registrations for the owner to mark.
- A compromised marked gateway can still act as any browser device it names, with that device's roles
  (ADR-0298 §8), but never as a hub device, and nothing it writes is surer than its own link.
- **Revisit** when a second person's devices are enrolled, or when a gateway is marked from a surface
  other than the hub.

## Alternatives considered

- **The lower level alone (#3665's first option).** Declined as the whole answer: it leaves the roles,
  and the driven device withdrew its own lowering by a command no level gates (ADR-0373 §4:5).
- **The mark alone.** Declined as the whole answer: a lowering of a marked gateway would not bind what
  it names, against "a lowering binds the device that connected" (#3678).
- **Keeping ADR-0296 §1:4 for enrolled machines under a marked gateway.** Declined: a hub device can
  always connect as itself, so the case buys little and leaves every enrolled device's roles open to
  any marked gateway.
- **No link for any browser device, read from the gateway's link alone.** Declined: the owner could no
  longer lower one browser device, and the web door's link would vanish from the listing.
- **Linking by any role, memberships included.** Declined: a membership is set through
  `AssistantEngine`, and no member of it makes a link (ADR-0373 §6:1).
- **A link the owner makes for each browser device by a new act.** Declined: it is a second enrolment
  (ADR-0296 §1:3), and the role the owner already gives is that act.
