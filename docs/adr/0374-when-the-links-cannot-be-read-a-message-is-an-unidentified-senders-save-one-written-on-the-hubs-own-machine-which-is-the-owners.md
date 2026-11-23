# 374. When the links cannot be read a message is an unidentified sender's, save one written on the hub's own machine, which is the owner's

- Status: Proposed
- Date: 2026-11-23
- Scope: lane L3b of milestone 20, "The hub knows who is speaking" (acceptance
  [#3642](https://github.com/leonapivato/ai-assistant/issues/3642), lanes
  [#3643](https://github.com/leonapivato/ai-assistant/issues/3643)). It decides what a message is
  when the hub cannot read the account links
  [ADR-0366](0366-a-person-is-one-identity-the-hub-links-accounts-to-code-decides-who-sent-an-input-and-how-sure-it-is-and-a-persons-label-holds-for-one-work.md)
  §4:1 and §5:6 decide its sender from: when that is (§2), the one exception for the hub's own
  machine (§3), how the exception meets the owner's lowering (§4), and what is recorded and shown
  (§5). §6 records what it does to earlier decisions, §7 names the contract change it would need,
  §8 what it leaves to others, and §9 what it settled where the ruling left a point open.
- Authorization: the owner's ruling of 2026-11-23. The coordinator put it to the owner that if the
  hub cannot read the account links, the pick is to "stay strict everywhere except the hub's own
  machine, which always counts as you, so you can always get in and repair it"; the alternative
  offered was to fall back to the old rule (everything on the owner's chat and Telegram is the
  owner) while the store is down. The owner asked "why would this be the case?"; the coordinator
  listed wrong file permissions, disk trouble, a bad upgrade and a passing read failure, and said a
  missing file is made again at start. The owner then answered: "go with your pick". That answer
  accepted the pick and nothing more. The coordinator assigned 0374 and ratifies it, under the
  owner's delegation, once its reviews are green.
- **Contract-surface decision; a decision only.** This document changes no Protocol, type, field
  or code. It decides how code sets a recorded input's sender, which bounds a `core` type the
  switch lane changes (§7), so it takes the adversarial and the architecture review.
- **Partially supersedes** ADR-0366 (§4:1 and §5:6, each for a message whose link cannot be
  read), as §6 records.

## Context

ADR-0366 §4:1 has code decide who sent an input "from the account it arrived by: the person whose
identity a link ties that account to, and no identified person where no link does", and §5:6 sets
its level "from the link it arrived by". "An input that arrived by no link is at none." Neither
says what a message is when the hub **cannot read** the links: a fault of the identity store, not
an account no link ties.

**The code today.** `sender_of` in `src/ai_assistant/orchestration/work_facts.py` asks the
identity store for the link holding a message's account. Where the store raises, any other fault
occurs, or no store is wired, it logs `input_sender_unread` and records the message as arriving by
no link. Nothing reads
the sender yet (ADR-0368 §1:3). Once lane L4 of #3643 makes the link decide, that answer would
make every message of the owner's an unidentified sender's while one small file cannot be read.

**The hub's own machine.** ADR-0298 §3:1 makes it the device `hub`, holding every role on the
local socket with no `acting_for` or as a caller inside the hub's own process (§3:2). A browser on
a gateway's loopback listener there is the same device, with its roles (ADR-0296 §1:8; ADR-0298
§2:9, §8:2), and no gateway may name `hub` (ADR-0298 §3:3). The hub chat's transcript records
the device each of the user's messages came from (ADR-0293 §5:2). The identity store links the account (`conversation`, `hub`)
to the owner from the hub's configuration at every start (`configured_accounts` in
`src/ai_assistant/app/composition.py`, under ADR-0373 §6:2), no member undoes a link (ADR-0373
§6:1), and the owner may lower it like any link (ADR-0366 §5:5, ADR-0373 §2:3). The hub's own
machine reaches `linked_accounts` and `withdraw_lowering` whatever any level is (ADR-0373 §5:1).

**Words.** A **link**, a **kind**, a **level** and a **lowering** are ADR-0366's and ADR-0373's.
The **store** is the identity store ADR-0366 §11 names. A **message** is one message an input
takes in, whose sender is read by the account it arrived by (ADR-0368 §2:6), or the input itself
where it records no messages. A bare section reference, such as §3:2, is to this decision's
own clauses.

## Decision

We will treat a message whose link cannot be read as an unidentified sender's, at none, with one
exception: while the links cannot be read, a message written on the hub's own machine is the
owner's, at the hub chat's declared most. A fault is never read as a link, and is recorded on the
message so an inspected work says the links could not be read.

### 1. Status and scope

> **Normative.** No lane implements against this decision before it merges `Accepted` (golden
> rule 5, ADR-0015 §5).

> **Normative.** This decision admits no one, and gives no person other than the owner any act or
> standing.

Lane L4 of #3643 builds it, with the switch that makes the link decide.

### 2. When the links cannot be read

> **Normative.** The links cannot be read for a message where code asked the store for the link
> holding the account the message arrived by and got no answer: the store raised, the read failed
> in any other way, or no store is wired. A message that names no account, and an answer that no
> link holds its account, are not such a case; each arrived by no link (ADR-0366 §5:6).

> **Normative.** A message whose link cannot be read is from no identified person, at none, save
> as §3:2 rules for the hub's own machine.

> **Normative.** No fault is read as a link, and nothing stands in for the link that could not be
> read: not the kind the message came by, not its device being enrolled or registered, and not a
> link read before.

> **Normative.** The author of a message whose link cannot be read is not established under
> ADR-0292 §5:3, whatever its kind declares under ADR-0292 §5:4, save as §3:2 rules.

Its input then starts or joins a work as ADR-0368 §3:3, §3:4 and §2:5 rule for an unidentified
sender's: for whoever its connection belongs to, carrying what anyone holds there, at none. ADR-0368
§9:4 already puts an author at none outside the established; §2:4 holds that against a kind's
declaration too, which L4 removes as the deciding rule.

### 3. The hub's own machine

> **Normative.** For this decision, a message is written on the hub's own machine where the hub
> chat's transcript records it as coming from the device `hub` (ADR-0293 §5:2, ADR-0298 §3:1),
> one a browser wrote through a gateway's loopback listener on that machine included (ADR-0296
> §1:8, ADR-0298 §2:9). No other message is: not one from a browser a gateway names on its remote
> listener, not one from the web door's hosted device, and none of any kind but the hub chat.

> **Normative.** While the links cannot be read for it, a message written on the hub's own
> machine is from the owner's identity (ADR-0366 §2:5), its author established as the owner, at
> the most the hub chat's kind declares in the running build (ADR-0366 §5:2).

> **Normative.** The exception holds only while the links cannot be read for the message. Where
> they can, the hub's own machine's messages are decided by their link, as every account's are
> (ADR-0366 §4:1, §5:6).

> **Normative.** Code applies the exception from the device the transcript records, and from
> nothing a message says; no model takes part in it (ADR-0366 §4:2, §5:7).

This is not a model or a message's words deciding a sender. The device is the requesting device
the wire server set for the request that wrote the message, never an argument the request carries
(ADR-0298 §2:1, §2:2), and no gateway may name `hub` (§3:3). So it is decided by code from the
account the message arrived by, as ADR-0366 §4:1 has it, and the person it names is the one the
configured link names whenever the store can be read: the exception supplies what the fault hides,
from the hub's configuration rather than the store. Whoever writes from that machine, at the
command line or in a browser on a gateway's loopback listener, already holds every role there
(ADR-0296 §1:8, §1:9; ADR-0298 §3:2, §8:2). On a hosted hub, what
keeps the operator who holds the box from acting as its person stays the operator's terms
(ADR-0327 §13); the configured link already makes the hub's own machine the owner's there.

### 4. Beside the owner's lowering

> **Normative.** While the links can be read, a lowering standing on the hub's own machine's link
> lowers its messages as any lowering lowers its link's (ADR-0366 §5:3, §5:6), and a lowering to
> none makes them an unidentified sender's.

> **Normative.** While the links cannot be read, no lowering lowers a message written on the hub's
> own machine: §3:2's level stands, and nothing a lowering set is remembered from an earlier read.

A lowering of that link restrains no one the exception lets in: whoever writes on the hub's own
machine holds every role there (ADR-0298 §3:2, §8:2), and its command line withdraws any lowering
whatever any level is (ADR-0373 §4:5, §5:1). It is the owner's choice of how
the hub reads that machine's chat, honoured whenever the store can be read, and the command line
is the way back from a lowering to none.

### 5. What is recorded and shown

> **Normative.** Code records on each message's sender, beside its person and level, whether it
> was set because the links could not be read, and the record is fixed on the episode as the
> sender is (ADR-0368 §2:6).

> **Normative.** Where several senders are combined into one, as an input's are, the combined
> sender records that the links could not be read where any of them does.

> **Normative.** Inspecting a work shows, for each input any of whose senders is recorded so, that
> the links could not be read for it.

> **Normative.** Each read that gets no answer is logged under one fixed event name, with the
> reader that asked and the reason, and without an account's or a person's identifier.

### 6. Relationship to earlier decisions

> **Normative.** This numbered draft records its replacement on ADR-0366's status line and in a
> dated header note, atomically with this ADR under ADR-0070 and ADR-0082, preserving ADR-0366's
> ratified body. The replacement takes effect on this ADR's ratification.

Superseded:

| Clause | Becomes |
| --- | --- |
| ADR-0366 §4:1, for a message whose link cannot be read | No identified person (§2:2), save the owner for the hub's own machine (§3:2) |
| ADR-0366 §5:6, for a message whose link cannot be read | None (§2:2), save the hub chat's declared most for the hub's own machine, no lowering read (§3:2, §4:2) |

Read through and standing, each as written: ADR-0366 §5:3 and §5:5 (a link's level, and the
lowering, are unchanged); ADR-0368 §2:5, §3:3, §3:4 and §9:4; ADR-0292 §5:3 and §5:4, as ADR-0368
§9:4 reads them; ADR-0298 §3; and ADR-0373 §2:9, §4:5, §5:1, §6:1 and §6:2.

### 7. The contract change building it would need

Named so the build is scoped, and made by none of this decision.

- **`InputSender`** (`core/types.py`) gains one field: whether the sender was set because the
  links could not be read (§5:1), kept by `canonical_senders` as §5:2 rules. It is stored with the
  episode and carried wherever `InputSender` is on the wire, so it is a stored and a wire-carried
  shape change, under ADR-0326 and ADR-0124 §9:2. A sender recorded before the field exists
  reads as one whose links were read: nothing read a sender then (ADR-0368 §1:3), and the log is
  the only record of a fault from that time. No Protocol changes.

### 8. What this decision leaves to others

- **ADR-0367 and the decisions it waits on:** what a level, none included, permits.
- **The build, or a later decision:** retrying a read, repairing the store, alerting the owner to
  a fault, and whether the hub starts when the store cannot be opened.
- **A later decision:** a second person's machine, and any machine but the hub's own.
- **Lane L4 of #3643:** the switch, and in which release the field §7 names ships.

> **Normative.** This decision may not be cited to settle any matter the list above leaves to
> another.

### 9. What this decision settled where the ruling left a point open

Each is this decision's, not an owner ruling:

- **§2:1**, what "cannot be read" covers: any failed read and an unwired store, but not an account
  no link holds or a message naming no account.
- **§2:3's last limb**, that no link read before stands in for one, so no last answer is kept.
- **§3:1**, the hub's own machine as the device `hub` on the hub chat alone, a browser on a
  gateway's loopback listener there included, as ADR-0298 §2:9 names it.
- **§3:2's level**, the hub chat's declared most, the level its link has with no lowering.
- **§3:3**, that the exception holds only while the links cannot be read. The owner's words were
  "always counts as you", put to them about a fault; while the store can be read the link already
  makes that machine the owner's, so "always" adds only an override of the owner's own lowering,
  and the least that honours the words leaves that lowering standing.
- **§4:2**, that a lowering on that link does not bear during a fault.
- **§5**, the record on the sender, its combination, and the log without identifiers.

## Consequences

- A fault of the identity store never makes anyone the owner, or anyone surer, save on the hub's
  own machine, so the owner can still use the hub chat there and repair the store.
- While the store cannot be read, the owner's Telegram messages, and their browsers' and enrolled
  devices' chat, count as an unidentified sender's, at none: what the owner accepted with the pick.
- An inspected work says when its sender was set this way, so a fault is visible after the fact.
- The field §7 names is a stored-shape change, so ADR-0326 §5:4 governs undoing the release that
  carries it.
- **Revisit** when a second person has a machine of their own, or when a level comes to bear on
  what the hub's own machine may do.

## Alternatives considered

- **Fall back to the channel-type rule while the store is down.** Offered to the owner and not
  picked: a fault would then decide who is speaking.
- **The exception always, whatever the store says.** Set aside: it adds nothing while the link can
  be read, save overriding the owner's own lowering of it.
- **Keep the last link read, and use it during a fault.** Set aside: a fault would be read as a
  link, and a withdrawn lowering or an ended link could outlive its act.
- **The hub's own machine at weak during a fault.** Set aside: weak means a sender that can be
  faked, which the local socket's is not, and a lowering is not a guard there (§4).
