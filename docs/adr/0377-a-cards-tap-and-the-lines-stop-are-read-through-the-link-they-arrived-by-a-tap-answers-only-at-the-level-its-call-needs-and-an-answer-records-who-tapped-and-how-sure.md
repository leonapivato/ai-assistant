# 377. A card's tap and the line's `/stop` are read through the link they arrived by, a tap answers only at the level its call needs, and an answer records who tapped and how sure

- Status: Partially superseded by ADR-0378 (§2:4, for a tap that came through a device other than its requesting device)
- Date: 2026-11-24
- Scope: decision D2 of milestone 21, "Every call checked" (acceptance
  [#3678](https://github.com/leonapivato/ai-assistant/issues/3678), lanes
  [#3679](https://github.com/leonapivato/ai-assistant/issues/3679)), closing
  [#3667](https://github.com/leonapivato/ai-assistant/issues/3667) and the approval half of
  [#113](https://github.com/leonapivato/ai-assistant/issues/113). It decides how a tap on an
  approval card is read (§2), when a tap answers (§3), what an answer records (§4), how the line's
  `/stop` is read (§5), and that the system's own stop is unchanged (§6). §7 records what it does to
  earlier decisions, §8 the contract changes it would need, §9 what it leaves to others, and §10
  what it settled where the rulings left a point open.
- Authorization: the owner's words, verbatim, all of 2026-11-24. "Yes, accept it", to "Do you
  accept milestone 20 as done, with #3667 moved to the next milestone?" (recorded on
  [#3642](https://github.com/leonapivato/ai-assistant/issues/3642)). "yes agreed, but its milestone
  21 right, not 2", to milestone 21's scope as #3678 records it, put with six picks of the
  coordinator's; the one this decision rests on was put as "`/stop` needs an identified account
  (weak or above), so it does not work at none", and another kept the levels as merged (none, weak,
  normal, strong). "Yes, go", to "Shall I post the batch issue and start D1, D2, D3 and B1". The
  answers accepted the picks as put and nothing more. The coordinator assigned 0377 and ratifies it,
  under the owner's delegation, once its reviews are green.
- **Contract-surface decision; a decision only.** This document changes no Protocol, type, field or
  code. It decides what an answered card records, a `core` type the wire carries, so it takes the
  adversarial and the architecture review. Building it is a breaking change under golden rule 5,
  through the changes §8 names, none of which is made here.
- **Partially supersedes**
  [ADR-0332](0332-activations-run-side-by-side-across-places-and-one-at-a-time-within-one-a-new-input-joins-the-running-activation-until-it-acts-and-a-place-waits-a-moment-before-it-starts.md)
  (§8:1, §8:4, §8:5 and §8:6) and
  [ADR-0361](0361-approvals-are-cards-the-person-taps-and-a-yes-is-a-one-time-ticket-for-the-exact-call.md)
  (§4:8 and §4:9), each in the scope §7 names.
- Partially superseded: 2026-11-24 by [ADR-0378](0378-only-a-gateway-the-owner-marked-names-a-device-a-naming-reaches-only-a-browser-device-and-makes-no-link-and-nothing-is-surer-than-the-device-it-came-through.md) — §2:4, for a tap on the hub page whose request came through a device other than its requesting device: it is read from both devices' hub chat accounts, as ADR-0378 reads such a message, the identity both links tie at the lower level, and no identified person, at none, otherwise (ADR-0378 §4:7). Every other clause stands. This replacement takes effect on ratification of ADR-0378. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; the ratified body below is preserved.

## Context

ADR-0366 had code decide who sent an input from the link of the account it arrived by, at that
link's level (ADR-0366 §4:1, §5:6), and milestone 20 built it: the owner can lower the Telegram
link, and a message that arrives by a link at none is an unidentified sender's. ADR-0367 then made
a shortfall's card answerable only by a tap that establishes its person at the grant's bar (§5:4),
checked the call run under a ticket "for the person whose tap approved it, at the level that tap
came by" (§5:5), and had a tap record the person who tapped (§10:4). Its §16 names "a tap records
its person and the level its surface established" as a change the build makes.

**The defect** (#3667, found by milestone 20's QA run). A tap and `/stop` do not read the link. On
`origin/main` at `4784219fe`: `TelegramReader._tapped` in `orchestration/telegram.py` carries a tap
out where the tapper is the configured account, no bot, in its private chat, as ADR-0361 §4:8 has
it ("on the line by ADR-0323 §4:1's test"); `TelegramCards._resolved` compares the request's person
with a person the composition root fixes (`TelegramCards(person=OWNER_PERSON_ID)` in
`app/composition.py`); `Engine.tap_approval` passes `OWNER_PERSON_ID`; and `/stop` runs through
`is_stop_command` and `TelegramReader._stopping` to `Engine._stop_line`, as ADR-0332 §8:1 has it
("the user's, established, under ADR-0323 §4:1"). None of them reads the identity store. So with the
Telegram link lowered to none, that account's messages are an unidentified sender's, yet its taps
approve cards and its `/stop` stops work. And an answer records `ApprovalTap`: its surface's
`ApprovalGiver` and an instant, not who tapped or how surely (#113).

**What already gates each act.** The line reads only the configured account's private chat (ADR-0323
§5:1, §5:2), and that stays. On the hub page, the panel's tap and `stop_activation` are in ADR-0298
§5:1's command-or-query row, reached only by the hub's own machine or a device the owner gave the
command role. The engine reads a request's device from ADR-0298 §2:2's context value, and a message
written from a device arrives by the hub chat's account for that device. ADR-0373 §4:5 keeps every
level off its three members, and its §5 notes that a device holding the command role reaches
`withdraw_lowering` whatever its own link's level.

**Words.** A **link**, a **level** and **identified** are ADR-0366's and ADR-0368's: identified is
weak or above (ADR-0368 §9:4). A **card**, a **tap**, a **request** and its **person** are
ADR-0361's; a **line**, a **grant**, a **bar** and **the check** are ADR-0367's. The **line's gate**
is ADR-0361 §4:8's test as written: the configured account, no bot, in its private chat. A **stop
command** is a message in ADR-0332 §8:1's form. A bare section reference, such as §3:2, is to this
decision's own clauses.

## Decision

We will read a tap and the line's `/stop` through the link of the account they arrived by, as a
message from it is read; let a tap answer a card only where it establishes the request's person at
the level the request's call needs; record on every answer who tapped and at what level; and leave
the system's own stop as it is.

### 1. Status, scope and delivery

> **Normative.** No lane implements against this decision before it merges `Accepted` (golden rule
> 5, ADR-0015 §5).

> **Normative.** Until it is built, nothing in this decision changes what the running hub allows,
> asks or answers.

> **Normative.** §3 is built only once the check decides calls (ADR-0367 §4:1), since the level a
> call needs is read from the lines.

> **Normative.** Until §3 is built, a tap is carried out under ADR-0361 §4:8 as written, and §4's
> record, where it is built, is written for it all the same.

> **Normative.** This decision admits no one, and gives no person other than the owner any act.

Whose cards a person may answer, and a shared card, stay ADR-0367 §10's.

### 2. A tap is read through the link it arrived by

> **Normative.** Who tapped, and at what level, are read from the account the tap arrived by,
> exactly as a message arriving by that account when the hub deals with the tap would be read
> (ADR-0366 §4:1, §5:6), and as ADR-0374 reads one whose link cannot be read.

> **Normative.** On the line, the account is the Telegram account the callback names as its
> sender.

> **Normative.** The line's gate stays in front of the link: a tap that fails it is dealt with as
> ADR-0323 §5:2 deals with an update from another account, and its link is not read.

> **Normative.** On the hub page, the account is the hub chat's account for the requesting device
> (ADR-0298 §2:1), the one a message written from that device arrives by.

> **Normative.** No model, and nothing a tap, its callback or its card says, counts toward who
> tapped or the level.

The command-or-query row still gates the panel's tap before any of this (ADR-0298 §5:1).

### 3. When a tap answers

> **Normative.** A tap answers a request, approving or denying it, only where §2 reads its tapper as
> the request's person, at or above the level the request's call needs.

> **Normative.** The level a call needs is, for a shortfall's card, the grant's bar ADR-0367 §5:4
> names. For every other card it is the least level at which the check, as the lines stand when the
> tap lands, finds a grant covering the request's call for the request's person (ADR-0367 §5:1),
> counting one that allows with approval; and weak where that level is none or no grant covers it.

> **Normative.** A tap that does not answer changes nothing: the request stays as it was, nothing is
> recorded on it, and no card is edited (ADR-0367 §5:4).

> **Normative.** A tap that does not answer, where §2 reads its tapper as the request's person, is
> told so: on the line by one fixed text of code's saying only that the tap did not answer the
> request, and on the hub page by an outcome of its own, beside the request as the panel shows it.

> **Normative.** Every other tap that does not answer is dealt with as its surface deals with a tap
> from anyone else (ADR-0361 §4:8): on the line as ADR-0323 §5:2 deals with an update from another
> account, and on the hub page as a request that is not the person's.

One rule covers every card: one for a call the policy ruled to need the person (ADR-0361 §2:4), one
for a call a rule always sends to approval, such as ADR-0367 §4:6's disclosing call under a default
grant, and a shortfall's (ADR-0367 §5:3). Each asks of a tap the level at which the check would let
its call through. So the ticket a tap grants is not refused for its level when ADR-0367 §5:5 checks
its call at the level the tap came by, unless the lines changed in between, which that check still
catches. Under the default grants #3678 records, at weak a tap answers a card whose call's bar is
weak, such as a `remember` sent for a yes because outside content was read, and does not answer one
whose bar is normal, such as an email, which is answered at the hub page or on a line not lowered.
At none a tap is an unidentified sender's: it answers nothing, and on the line nothing answers it.

### 4. What a tap records

> **Normative.** A tap carried out records, in ADR-0361 §4:9's plan-store step and beside its
> surface's `ApprovalGiver` and its instant, the person §2 read, or no person where §2 read
> none, and the level §2 read.

> **Normative.** The level a tap came by, wherever a later check reads it (ADR-0367 §5:5, ADR-0368
> §7's last note), is the level §4:1 recorded.

> **Normative.** An answer recorded before §4:1 is built reads as the request's person's, since
> ADR-0361 §4:8 carried out a tap from no one else, and its level as not recorded, never as a level.

> **Normative.** Where a check reads the level of an answer whose level is not recorded, it reads
> none.

The change that builds §4:1 ships the plan store's upgrade and its test, as ADR-0326 §4:1 and §4:2
require of every schema change. An answer that old holds a ticket only within ADR-0361 §3:5's 24
hours, so §4:4 is a backstop rather than a path.

### 5. The line's `/stop`

> **Normative.** Who sent a stop command, and at what level, are read as §2:1 reads a tap's, from
> the Telegram account that sent it.

> **Normative.** A stop command is carried out only where its sender is identified, at weak or
> above.

> **Normative.** A stop command carried out stops each running activation started from the line's
> chat, whoever's work it is (ADR-0349 §4:3).

> **Normative.** A stop command not carried out stops nothing, is not input, is recorded nowhere,
> and is not answered: it is dealt with as ADR-0323 §5:2 deals with an update from another account.

> **Normative.** No record gains who sent a stop command or its level.

A stop command's form, and that it is not input (ADR-0332 §8:1 to §8:3), are unchanged: what
changes is who it is read as. One carried out is recorded and answered as ADR-0332 §8:5 and §8:6
rule, and on a one-person hub the work it stops is the owner's or an unidentified sender's on the
owner's connection. A stop only takes away, so it needs no level beyond identified; at
none the owner's ruling makes it do nothing, and the account at none still reaches the assistant
as an unidentified sender, whose work answers in its place (ADR-0368 §3:4). The level is read when
the reader deals with the command, as it is for a message: a `/stop` that waited in Telegram is
read at the level that stands when a poll returns it.

### 6. The system's own stop

> **Normative.** `stop_activation`, and every stop a device reaches through ADR-0298 §5:1's
> command-or-query row, is unchanged: the row alone admits it, and no level or link gates it.

#3667's reasoning is that the line has no gate but the configured account, so lowering that
account's link left its commands untouched. A device's commands have a gate of their own: the
command role, which the owner gives and removes at the hub (ADR-0298 §4:14). Reading a device's
stop through its link would add nothing, since a device holding the command role reaches
`withdraw_lowering` whatever its own link's level (ADR-0373 §5). The panel's tap reads its device's
link for another reason: what a yes approves is checked at the level it came by (ADR-0367 §5:5),
so a tap needs a level, and a stop does not.

### 7. Relationship to earlier decisions

> **Normative.** This numbered draft records its replacements on the status lines of ADR-0332 and
> ADR-0361 and in a dated header note on each, atomically with this ADR under ADR-0070 and ADR-0082,
> preserving their ratified bodies. The replacements take effect on this ADR's ratification.

Superseded:

| Clause | Becomes |
| --- | --- |
| ADR-0361 §4:8's *established as its surface establishes them: on the line by ADR-0323 §4:1's test, as ADR-0332 §8:1 applies it to `/stop`; on the hub page, from a device admitted under ADR-0124* | Read through the link the tap arrived by (§2:1); the line's gate stays in front of it (§2:3), and the command-or-query row gates the panel's tap as before |
| ADR-0361 §4:8, in when a tap is carried out, beside what ADR-0367 §5:4 adds for a shortfall | For every card, only at the level its call needs (§3:1, §3:2), with what a tap that does not answer gets (§3:3 to §3:5) |
| ADR-0361 §4:9's *with who answered, as the `ApprovalGiver` of its surface*, in the addition alone | Also the level the tap came by (§4:1), and how an earlier answer reads (§4:3, §4:4) |
| ADR-0332 §8:1's first bullet, *the user's, established, under ADR-0323 §4:1* | In who sent it alone: read through the link (§5:1). The form it names stands |
| ADR-0332 §8:4, §8:5 and §8:6, each in the addition alone | Each holds only for a stop command carried out (§5:2, §5:3); one not carried out is §5:4's |

Taken, with nothing superseded:

| Clause | What this decision takes |
| --- | --- |
| ADR-0367 §5:4 | §3:2 reads its bar for a shortfall's card and adds the level every other card needs |
| ADR-0367 §10:4, and §16's *a tap records its person and the level its surface established* | §4:1 |
| ADR-0366 §5:8's *what a level permits*, for a tap and a stop | §3 and §5:2 |

Read through and standing, each as written:

| Clause | Why it stands |
| --- | --- |
| ADR-0323 §5:1 and §5:2 | The line reads only the configured account's private chat; this decision changes who a tap or a `/stop` from it is read as (§2:3) |
| ADR-0362 §4:2 and §4:4 | An answer goes only to a tap from the request's person, now read under §2, and carries a fixed text of code's (§3:4) |
| ADR-0298 §2 and §5:1 | The panel's device is the requesting device, and the row gates the tap and every stop (§2:4, §6:1) |
| ADR-0373 §4:5 | Its three members stay ungated by any level; §2:4 bears on the panel's tap alone |
| ADR-0367 §5:5 and ADR-0368 §7 | A ticket's call is checked for its tapper at the level §4:1 recorded (§4:2) |
| ADR-0349 §4:3 | Whose work a `/stop` stops (§5:3) |

### 8. The contract changes building it would need

Named so the build is scoped, and made by none of this decision.

- **The answer:** `ApprovalTap` gains the person who tapped and the level, each optional so an
  earlier answer reads as §4:3 says; the plan store's upgrade and its test; and
  `PROTOCOL_VERSION` advanced where the wire carries the changed type (ADR-0124 §9).
- **The panel's outcome:** `ApprovalPanelTapAnswer` gains a member for a tap that did not answer
  (§3:4), on the wire.
- **No `AssistantEngine` member gains an argument:** the engine reads the requesting device from
  ADR-0298 §2:2's context value. The line's reader and `TelegramCards` read the identity store, in
  place of the person `app/composition.py` fixes.

### 9. What this decision leaves to others

- **ADR-0367 and the lanes building it:** the check, the lines, and what a level permits beyond a
  tap and a `/stop`.
- **Where a card is posted or shown**, a shortfall's included (ADR-0367 §5:4, ADR-0361 §4:2): a line
  lowered to none still shows cards its taps cannot answer.
- **Milestone 5:** whose cards a person may answer, shared cards (ADR-0367 §10), and whose work a
  `/stop` may stop on a hub of several people.
- **Device naming** ([#3665](https://github.com/leonapivato/ai-assistant/issues/3665)): which device
  a request is from, read here as ADR-0298 §2:1 and the decisions after it leave it.
- **The build:** the words of §3:4's fixed text and of the panel's outcome.
- **ADR-0323 §4:1 for a message:** what it says of a message from the configured account, which
  this decision does not read.

> **Normative.** This decision may not be cited to settle any matter the list above leaves to
> another.

### 10. What this decision settled where the rulings left a point open

Each is this decision's, not an owner ruling:

- **§2:1**, that a tap is read as a message by its account would be, at the moment it is dealt
  with, ADR-0374's case included; **§2:3**, that the line's gate stays in front of the link.
- **§3:1 and §3:2**, the one rule for every card, and the level a card other than a shortfall's
  needs; that a Deny needs the same level as an Approve.
- **§3:4 and §3:5**, what a tap that does not answer gets on each surface.
- **§4:3 and §4:4**, that an earlier answer reads as its request's person's at no recorded level,
  and that the check reads that as none.
- **§5:3 to §5:5**, whose work a `/stop` stops, that one not carried out is dealt with silently,
  and that nothing new records a stop.
- **§6**, that the system's own stop is unchanged.

## Consequences

- Lowering the Telegram link binds what the account taps and stops, not only what it says. At weak
  its taps answer only cards whose call needs no more than weak; at none they answer nothing and its
  `/stop` does nothing, silently.
- A device's link lowered to none makes its panel taps answer nothing, though a device holding the
  command role can withdraw that lowering itself (ADR-0373 §5); removing the role is what binds it.
- An answered card says who tapped and how sure the hub was, so a ticket's call is checked at a
  recorded level, and #113's approval half closes.
- Where the identity store cannot be read, a tap and a `/stop` on the line do nothing; the hub's own
  machine still taps and stops, as the owner (ADR-0374 §3).
- **Revisit** when a second person may tap or stop, or when a device's commands are to be read
  through its link.

## Alternatives considered

- **A tap answers wherever its tapper is identified, and ADR-0367 §5:5 refuses the ticket's call.** Set
  aside: a tap at weak would grant a ticket whose call then falls short and asks again on a new
  card, a round trip the tapper cannot tell from success.
- **A Deny at any identified level.** Set aside: an unsure account could deny every card, and
  ADR-0367 §5:4 already makes a tap below the bar change nothing, whichever button.
- **The line's `/stop` at none answered with a fixed line.** Set aside: the owner's pick was that it
  does not work at none, and a tap at none already goes unanswered (ADR-0362 §4:4), so the line
  treats its two commands alike.
- **The system's stop read through the device's link.** Set aside in §6: the command role is that
  act's gate, and a commanding device can lift its own lowering.
