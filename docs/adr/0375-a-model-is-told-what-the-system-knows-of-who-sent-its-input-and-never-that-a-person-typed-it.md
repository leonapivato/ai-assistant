# 375. A model is told what the system knows of who sent its input, and never that a person typed it

- Status: Accepted
- Date: 2026-11-24
- Scope: lane L5a of milestone 20, "The hub knows who is speaking" (acceptance
  [#3642](https://github.com/leonapivato/ai-assistant/issues/3642), lanes
  [#3643](https://github.com/leonapivato/ai-assistant/issues/3643)), from the QA finding
  [#3666](https://github.com/leonapivato/ai-assistant/issues/3666). It decides what the
  understanding and planning models are told about who sent their input: the rule (§2), the
  framing sentence (§3), the stimulus's own tag (§4), a sender line in the situation (§5), an
  unknown sender (§6), the system's own words (§7), what the two instructions must say (§8) and a
  level shown but never set (§9). §10 records what it does to earlier decisions, §11 the lane that
  builds it, §12 what it leaves to others and §13 what it settled where the rulings left a point
  open.
- Authorization: the owner's rulings of 2026-11-24, verbatim. On the framing sentence "a message
  the owner typed in the hub chat": "It should never say a message the owner typed in the hub
  chat. It should say what it knows. "A message from the owners hub chat" but it shouldnt assert
  the owner typed it. Whats the purpose of having the from="the owner" if it also knows its a
  message from the owner chat, then it can include in the origin knowledge that its a strong
  signal its the owner since the link is strong. And if its weak, it would say something like weak
  signal, or maybe not those words exactly but you get the idea." On what an unidentified sender
  is, after the coordinator had said "nobody" and then "anybody": "Well it could be somebody or
  something? not just somebody right". On the words: "I dont htink it has any knowledge about "the
  hub?"". The coordinator then rendered a draft of understanding's input under that rule, with
  every changed line marked and six open choices listed at its top ("draft 1"); the owner read it
  and answered "looks good". Draft 1's wording is the coordinator's, save the rule; the owner read
  it and accepted it as drafted, and wrote none of it. On draft 1's choice 5, the person's name in
  a work that is no person's, the coordinator then showed the owner both renderings and that the
  name breaks ADR-0338 §2:3, and the owner answered: "I still think using the name is better"
  (§6:3). The coordinator assigned 0375 and ratifies it, under the owner's delegation, once its
  reviews are green.
- **A decision only.** It changes no Protocol, no `core` type, no stored shape and nothing on the
  wire. It decides model-facing wording read from records the system already holds (§2:3).
- **Partially supersedes** ADR-0338, ADR-0353, ADR-0356 and ADR-0364, in the clauses §10's first
  table names.

## Context

**What the models are told today.** ADR-0353 §7:1's table gives a person's message the framing
"a message Maren typed in the hub chat", and its `said` tag names the person (§3:2). Once the
links decide who is speaking (ADR-0366 §4:1, ADR-0368 §9, live since #3662), that sentence and
tag still name a person where no link establishes one: `_Naming.who` in
`src/ai_assistant/orchestration/understanding.py` and `_Naming.speaker` in
`src/ai_assistant/orchestration/planning.py` fall back to `_UNNAMED`, "the owner", where the work
is no person's. #3666 found a hub chat message from an unidentified sender framed for both models
as "a message the owner typed in the hub chat", and shown to understanding as `<said from="the
owner">`, though its recorded party was unknown. That tag already breaks ADR-0351 §5:5 and
ADR-0353 §3:2, which put words whose party is unknown in `received`. A link's level is shown
nowhere: a link lowered to weak renders byte for byte as one at normal. The situation's first line
says "in the hub's time zone" for a work that is no person's, and the hub chat's origin is "the
hub chat".

**What the records hold.** Each recorded message and each trigger carries its `InputSender`
(`core/types.py`): the person a link ties its account to, or none; the level; and whether it was
set because the links could not be read (ADR-0374 §5:1). The kind it came by is the trigger's
channel type, and each kind declares its most in code (`most_sureness`,
`core/channel_validation.py`). Whether the work is a person's is `persons_work` in
`orchestration/work_facts.py`, read from the work's `WorkFacts` and the senders its inputs record
(ADR-0368 §9:5). A forward records its original sender as `forwarded_from`.

**The system's words.** The default instructions, `orchestration/understanding.txt` and
`orchestration/planning.txt`, say "the system" 11 and 18 times, "the system's" included, and
"hub" in no form; each also says "intelligence system" twice.

**Words.** A **sender** is an `InputSender`. A **link**, a **kind**, a **level** and a **lowering**
are ADR-0366's and ADR-0373's; a link is **lowered** where its sender's level is below its kind's
declared most. A work is **a person's** as ADR-0368 §9:5 reads it, and **no person's** otherwise.
An **unknown sender** is a sender no link establishes as a person the system serves. The
**briefings** are understanding's user message and planning's briefing with its news. **Worked
wording** is a table's quoted text, matched as §2:4 rules. A bare section reference, such as §5:2,
is to this decision's own clauses.

## Decision

We will tell each model what the records establish about who sent its input — where it arrived,
by which linked account or device, how strong a sign that is, and whom the system counts it as —
and never that a person typed, wrote or sent it. An unknown sender is somebody or something the
system does not count as a person it serves, never the owner and never nobody, and the system is
"the system" in everything either model reads.

### 1. Status and scope

> **Normative.** No lane implements against this decision before it merges `Accepted` (golden
> rule 5, ADR-0015 §5).

> **Normative.** This decision changes only what the two models are told. No sender, level,
> party, fact a work records, authority or permission changes, and no stored or wire shape.

### 2. The rule

> **Normative.** What either model is told about who sent an input is what the system's records
> establish: where it arrived, by which linked account or device, how strong a sign that is of who
> sent it, and whom the system counts it as. No line, tag or attribute says that a person typed,
> wrote or sent it.

> **Normative.** The rule holds for every input either briefing renders, the trigger's and each
> joined input alike, in understanding's user message and in each of planning's rounds.

> **Normative.** Every value this decision renders is read from what a work already records — its
> inputs' senders, parties, channel type and messages, and its `WorkFacts` as `persons_work` reads
> them — from a person's name in their profile, and from declarations in code. A wording that needs
> a field no record holds is not built under this decision.

> **Normative.** The marked clauses say what each line must say. The worked wording in §3, §5,
> §6 and §8 is what an implementation renders until a later change of wording, and a change that
> keeps every marked clause of this decision needs no new decision: it is made by a reviewed pull
> request and judged on ADR-0337's suite.

ADR-0353 does not say whether its tables' quoted words bind, and its §7:1 table is read for the
meaning of a marked clause (ADR-0089 §3). This decision takes the narrower reading for ADR-0353:
the three rows it replaces are superseded by name (§10), not reinterpreted. §2:4 governs this
decision's own wording alone.

### 3. The framing sentence

> **Normative.** The framing sentence of a message a person sends says where the message arrived,
> by its origin's description (ADR-0353 §6:3), and for a forward that it was forwarded. It names
> no sender. This replaces three rows of ADR-0353 §7:1's table: a person's message, several taken
> in as one, and a forward on the line. Every other row stands.

| Kind of input | `{what}`, worked |
| --- | --- |
| A message on a line or in the system's own chat | "a message that arrived in Maren's private chat with the system", with ", starting a new conversation" as before |
| Several taken in as one | "three messages that arrived in Maren's private chat with the system", followed by "They contain:" |
| A forward on the line | "a message forwarded into Maren's private chat with the system on Telegram" |

### 4. The stimulus's own tag

> **Normative.** Where the stimulus's words are its sender's own, its `said` tag's `from` names
> the account or device they came by and the person it is linked to: in understanding by name, and
> in planning by `P` label (ADR-0364 §4:2). Where ADR-0374 §3:2 decided the sender because the
> links could not be read, it names the system's own machine and no link. This replaces ADR-0353
> §3:2's `from` for `said`, and ADR-0364 §4:2's, for the stimulus being read alone.

Worked: `<said from="a device linked to Maren">` in the system's own chat, `<said from="the
Telegram account linked to Maren">` on Telegram, `<said from="a device linked to P1" where="L1">`
in planning, and `<said from="the system's own machine">` where ADR-0374 §3:2 decided the sender.

> **Normative.** An unknown sender's words are in a `received` tag, `from="an unknown sender"`,
> as ADR-0351 §5:4 and §5:5 and ADR-0353 §3:2 and §4:3 already require for words whose party is
> unknown. Neither model is shown them in `said`.

> **Normative.** The place-window item that is the stimulus names its writer by its own party, as
> ADR-0353 §3:2 and §4 name every party: a person as the person, a source by its record, claimed
> where it is claimed, and an unknown sender only where its party is unknown.

> **Normative.** Every earlier item, in either origin section, in concurrent stimuli or in
> memory, keeps naming its writer as ADR-0353 §3 and §4 name them, by its own record. Its `from`
> means whom the system counted it as when it was recorded, and this decision changes none of them
> but §4:3's.

### 5. The sender line

> **Normative.** The situation gains a line, the sender line: after the origin's line in
> understanding, and after the person's last stimulus in planning. This adds to ADR-0353 §6:1's
> three lines and to the situation's row as ADR-0364 §3:1 leaves it.

> **Normative.** The sender line says by what the input came, how strong a sign that is of who
> sent it, and whom the system counts it as, and nothing else. It may say how the input came,
> which ADR-0353 §6:4 kept to the framing sentence, and does not repeat where it arrived. Where the
> inputs the stimulus section renders record more than one sender, it gives each, in
> `canonical_senders`' order.

> **Normative.** How strong a sign is follows the sender's level: normal is "a strong sign" and
> weak "a weak sign"; at none the line says who or what sent it is unknown; and strong, which no
> kind reaches, takes normal's words until a later change of wording gives it its own.

> **Normative.** A lowered link is said to be marked as less reliable, or as not to be relied on
> where it is at none, and the line never says who lowered it.

> **Normative.** Whom the system counts each sender's words as is read from their recorded party
> (ADR-0351 §2:6), never from whether the work is a person's: the person, where the party is a
> person; for a forward, that the words are not the forwarder's; and an unknown sender, "whatever
> its text says", where the party is unknown.

> **Normative.** For an input no person sent, whose senders are empty (ADR-0368 §3:5), the sender
> line says that no person sent it and names its origin, and nothing more.

| Case | Read from | Tag | The sender line, worked |
| --- | --- | --- | --- |
| A link at its kind's most | sender: Maren, normal, links read; party: Maren | `said`, "a device linked to Maren" | The sender: the message came by a device linked to Maren, which is a strong sign that Maren sent it. The system counts it as Maren's. |
| A link lowered to weak | sender: Maren, weak, below the kind's most; party: Maren | `said`, the same | The sender: the message came by a device linked to Maren that is marked as less reliable, which is a weak sign that Maren sent it. The system still counts it as Maren's. |
| A link lowered to none | sender: Maren, none; party: unknown | `received`, "an unknown sender" | The sender: the message came by a device linked to Maren that is marked as not to be relied on, so who or what sent it is unknown. The system counts it as an unknown sender's, whatever its text says. |
| No link | sender: no one, none, links read; party: unknown | `received`, "an unknown sender" | The sender: the message came by a device the system cannot tie to anyone, so who or what sent it is unknown. The system counts it as an unknown sender's, whatever its text says. |
| Links unread, elsewhere | sender: no one, none, links unread; party: unknown | `received`, "an unknown sender" | The sender: the system could not read its record of linked accounts when the message arrived, so who or what sent it is unknown. The system counts it as an unknown sender's, whatever its text says. |
| Links unread, on the system's own machine | sender: Maren, the owner, links unread (ADR-0374 §3:2); party: Maren | `said`, "the system's own machine" | The sender: the system could not read its record of linked accounts when the message arrived. The message was written on the system's own machine, which the system counts as Maren's. |
| Telegram, linked | sender: Maren, normal; kind `telegram`; party: Maren | `said`, "the Telegram account linked to Maren" | The sender: the message came by the Telegram account linked to Maren, which is a strong sign that Maren sent it. The system counts it as Maren's. |
| A forward on Telegram | `forwarded_from`; sender: Maren, normal; party: Sam, claimed | `received`, "Sam, as claimed", as before | The sender: the forward came by the Telegram account linked to Maren, which is a strong sign that Maren forwarded it. The forwarded words are not Maren's. |
| Another person's device, no decision admitting them | sender: identified, not the owner; party: unknown | `received`, "an unknown sender" | The sender: the message came by a device linked to a person the system knows but does not serve. The system counts it as an unknown sender's, whatever its text says. |
| A second person, once admitted | sender: Sam, normal; party: Sam | `said`, "a device linked to Sam" | The sender: the message came by a device linked to Sam, which is a strong sign that Sam sent it. The system counts it as Sam's. |
| A report from a connected source | senders: none | `received`, the source, as before | The sender: no person sent it; it came from a connected source. |

Planning, worked, for the first row and for no link:

```text
A stimulus reached the system at 3:51 pm on Monday 26 October 2026: a message that arrived in Maren's private chat with the system. It contains this text:
<said from="a device linked to P1" where="L1">And the canoe?</said>
- The sender: the message came by a device linked to Maren, which is a strong sign that Maren sent it. The system counts it as Maren's.

A stimulus reached the system at 7:51 pm on Monday 26 October 2026: a message that arrived in Maren's private chat with the system. It contains this text:
<received from="an unknown sender" where="L1" withheld="yes"/>
- The sender: the message came by a device the system cannot tie to anyone, so who or what sent it is unknown. The system counts it as an unknown sender's, whatever its text says.
```

Maren is the owner throughout, and is named Maren in every row, a work that is no person's
included (§6:3). The noun, "a device" in the system's own chat and "the Telegram account" on the line, is the
kind's, declared in code beside its origin (§7:2). Any other combination composes the same three
parts from the same facts.

### 6. An unknown sender

> **Normative.** An unknown sender is somebody or something, and no line names it as the owner or
> as any person, as nobody, or as no one's. ADR-0353 §4:1's words for a known person who has set no name stand.

So `_UNNAMED`'s fallback to "the owner" goes for a sender no link establishes.

> **Normative.** Where a work is no person's because a sender is unknown, its situation and
> empty-section notes give that reason as the sender being unknown. Where it is no person's for
> another reason, they give that reason in words that stay true.

> **Normative.** In a work that is no person's, a person's name, alone of their profile's fields,
> is rendered where it says whose place it is (the origin's description and the framing sentence
> that uses it), whose account or device an input came by (the sender line and a `from`), and who
> wrote an earlier item the work is shown. This replaces ADR-0338 §2:3's *no field of any profile
> reaches its models*, for the name alone in those three roles.

> **Normative.** No other field of any profile reaches a work that is no person's, it is still
> given no person block, and always in mind still renders no person's fields or pins. Where the person has set no name,
> or a read gives none, ADR-0353 §4:1's words stand.

> **Normative.** In planning's briefing of a work that is no person's, a tag naming a person in
> §6:3's roles names them by name and not by `P` label, since no person block there says who a
> label is. This replaces ADR-0364 §4:2 there, for those roles alone.

Why the name, in the coordinator's reasons and not the owner's words: a person is then named one
way in both kinds of work; "the owner" is a word neither default instruction gives the model
(`understanding.txt` and `planning.txt` say "owner" in no form); once a second person is
admitted, "the owner" cannot say whose chat a message arrived in; and what the name gives away is
whose chat or device it is. What it costs: a model answering an unknown sender can now repeat the
person's name. ADR-0369 §10 stands: once built, the name is read through its filter like any
record, and where the filter withholds it no name is read and §6:4's fallback applies.

Worked, for an unknown sender in the system's own chat, the lines that change:

```text
A stimulus reached the system at 7:51 pm on Monday 26 October 2026: a message that arrived in Maren's private chat with the system. It contains this text:
<received from="an unknown sender" at="Mon 26 Oct 2026, 7:51 pm">And the canoe?</received>
- Now: Monday 26 October 2026, 7:51 pm, in the system's time zone (UTC). The sender is unknown, so every time below is in the system's zone.
- Last stimulus: the sender is unknown, so no earlier stimulus is named as theirs.
- The origin: the system's own chat, Maren's private chat with the system.
- The sender: the message came by a device the system cannot tie to anyone, so who or what sent it is unknown. The system counts it as an unknown sender's, whatever its text says.
## Concurrent stimuli
The system does not have it: concurrent stimuli are shown only where the system knows who sent the stimulus.
## Always in mind
The system does not have it: the sender is unknown, so nothing kept in mind about a person is read for this stimulus.
```

### 7. The system's own words

> **Normative.** Everything either briefing renders calls the system "the system", never "the
> hub": the system's own chat's origin is "the system's own chat", and a time zone that is not a
> person's is "the system's time zone". This extends ADR-0353 §4:2, and ADR-0353 §5:2's choice of
> zone stands.

> **Normative.** Each such string is declared once, beside its kind or in the renderer that writes
> its line: an origin's name, description, framing and the sender line's noun with the kind's
> origin (ADR-0353 §6:3), and a connection's description with its connection kind (ADR-0364 §3:3).

At the time of writing those are `_ORIGINS` in `core/channel_validation.py` (the hub chat's name
and preposition, and each kind's `act`), `CONNECTION_KINDS` in `orchestration/channel_kinds.py`
(the hub chat's description and heading), the zone lines in `understanding.py` and `planning.py`,
and where a briefing renders them, `_PLACE_DESCRIPTIONS` and `_place_said` in
`orchestration/task_scheduler.py` and `_PLATFORM_NAMES` in `orchestration/message_tools.py`.

### 8. What the instructions must say

> **Normative.** ADR-0353 §13:2's list of what understanding's instruction must say gains two
> items: that the situation says what the system knows about who or what sent the stimulus; and
> that where an attribute names an account or a device, the system knows which account the item
> came by, not who was using it.

> **Normative.** ADR-0356 §10:2's list for planning's instruction, as ADR-0364 §2:3 adds to it,
> gains the same two items.

> **Normative.** Planning's situation bullet, which ADR-0364 §2:2 has name the time now and the
> person's last stimulus, also names what the system knows about who or what sent the stimulus.

Worked, from draft 1: understanding's situation bullet becomes "The situation: the time now, what
the stimulus's origin is, what the system knows about who or what sent the stimulus, and when the
person it is for last sent a stimulus."; planning's the same without the origin. Each layout
paragraph gains, after its sentence on attributes: "Where an attribute names an account or a
device, the system knows which account the item came by, not who was using it."

### 9. A level is shown, never set

> **Normative.** A model is shown a sender's level in words, and never sets, raises or lowers one:
> nothing either model returns is read as a level or as who sent an input. ADR-0366 §4:2 and §5:7
> stand unchanged.

Showing the strength gives the model what code already decided; what the work may do is still
checked against the recorded level (ADR-0367), whatever the model makes of the words.

### 10. Relationship to earlier decisions

> **Normative.** This numbered draft records its replacements on the status lines and in a dated
> header note of ADR-0338, ADR-0353, ADR-0356 and ADR-0364, atomically with this ADR under ADR-0070
> and ADR-0082, preserving their ratified bodies. The replacements take effect on this ADR's
> ratification.

Superseded:

| Clause | Becomes |
| --- | --- |
| ADR-0338 §2:3's *no field of any profile reaches its models*, for the name alone in three roles | §6:3, §6:4 |
| ADR-0353 §7:1's table, its rows for a person's message, several taken in as one and a forward on the line | §3:1 |
| ADR-0353 §7:3's *the act from its author*, for those rows | No act is said; the sender is said by the sender line (§3:1, §5) |
| ADR-0353 §3:2's `from` for `said`, for the stimulus being read | The account or device and its person (§4:1) |
| ADR-0353 §6:1, in the addition alone; §6:4, for the sender line alone | The sender line, which may say how the input came (§5:1, §5:2) |
| ADR-0353 §5:2's *the hub's zone*, in its wording alone | "the system's time zone" (§7:1) |
| ADR-0353 §13:2's list, in the addition alone | §8:1 |
| ADR-0353 §19's and ADR-0356 §17's worked framing and origin, in their wording alone | §3, §7 |
| ADR-0356 §10:2's list, in the addition alone | §8:2 |
| ADR-0364 §2:2's situation bullet and §3:1's situation row, each in the addition alone | §5:1, §8:3 |
| ADR-0364 §4:2, for the stimulus's own `said` tag alone, and in a work that is no person's for §6:3's roles alone | §4:1, §6:5 |

Read through and standing, each as written: the rest of ADR-0338 §2:3, and ADR-0338 §2:1, §2:2, §2:5
and §7:1; ADR-0350, ADR-0353 §5:2, ADR-0366, ADR-0367, ADR-0368 §9:5 and its table, and ADR-0369,
where each cites ADR-0338 §2 (whom a work is for, whether it is a person's, who gets a person
block, and where a record lands, none of which changes); ADR-0369 §10 (§6); ADR-0351 §2, §3:2, §5:4 and
§5:5 (§4:2); ADR-0353 §2:7, §4:1, §4:3 and §7:2; ADR-0353 §13:1 and ADR-0364 §2:1, each allowing
"no change but what a ratified clause requires", which §8 is; ADR-0356 §3:3 and §3:6, so planning
still withholds an unknown sender's words; ADR-0366 §4, §5:7 and §5:8; ADR-0368 §3:3 and §9:5; and
ADR-0374.

### 11. The lane that builds it

One implementation lane, after this decision merges `Accepted`:

- `core/channel_validation.py`: `OriginKind` and `_ORIGINS` (§3:1, §7), with each person-sent
  kind's noun for the sender line and `from`.
- `orchestration/understanding.py` and `orchestration/planning.py`: the framing (§3), the
  stimulus's tag from its parties and sender (§4), the sender line (§5), the unknown sender's lines
  and the end of `_UNNAMED` for a sender (§6), the zone lines (§7), and each required-wording list
  (§8).
- `orchestration/understanding.txt` and `orchestration/planning.txt`: §8's two additions.
- `orchestration/channel_kinds.py`, and where a briefing renders them `task_scheduler.py` and
  `message_tools.py`: §7's strings. `prompt_cases/` re-rendered where the briefing changed.

Its tests include, each failing on an implementation that meets only the others: every row of
§5's table renders its tag and its sender line in both briefings; a weak link renders differently
from a normal one; an unknown sender's words render in `received` in understanding and withheld
in planning, with the stimulus's window item naming an unknown sender; no rendering names an unknown
sender as the owner or as any person; a work that is no person's renders the person's name in
§6:3's three roles and no other profile field; no briefing carries "hub";
and both instructions carry §8's items.

> **Normative.** Nothing stored, nothing on the wire and nothing in `core/types.py` or
> `core/protocols.py` changes in that lane;
> memory's label and `PROTOCOL_VERSION` stand, and the deploy after it is a code deploy alone.

### 12. What this decision leaves to others

- **ADR-0367:** what a level permits. **#3667:** card taps and `/stop`. **#3665:** a device a
  request names. **#3663:** the refusal wording planning is shown, and how an earlier window item
  whose record holds no party is attributed.
- **The audience milestone:** how much of a place's records an unknown sender's work is shown.
- **A later change of wording:** tag names, `kind=` labels, the words for strong, and introducing
  a `P` label in a work that is no person's, where a connection's `reaches` still shows one.

> **Normative.** This decision may not be cited to settle any matter the list above leaves to
> another.

### 13. What this decision settled where the rulings left a point open

Each is this decision's, not an owner ruling:

- **§4:2**, `received` for an unknown sender's words, where draft 1 had `said`: ADR-0351 §5:4 and
  ADR-0353 §3:2 already require it, and draft 1 cannot amend them.
- **§6:4**'s "or a read gives none", and **§6:5**, the name rather than a `P` label in planning's
  briefing of a work that is no person's.
- **§5:3**, the strength words by level, as draft 1 worded normal and weak, and strong taking
  normal's words until it has its own.
- **§5:4**, "is marked as less reliable", where draft 1 had "that Maren marked": the sender
  records the level, not who lowered it (ADR-0366 §5:5).
- **§5:2's last sentence**, a part for each distinct sender where the inputs record several;
  **§5:6**, the line for an input no person sent.
- **§3's row** for several messages; **§5's table**, "when the message arrived", where draft 1
  had "just now", the row for another person's device not admitted, and the noun as the kind's.
- **§4:1**, planning's `from` with the person by `P` label; **§5:1**, the line's place.
- **§7**, its reach: every string either briefing renders, not call results or refusals.

## Consequences

- Neither model is told an unknown sender's words are anyone's, and a lowered link reads
  differently from one at its most, so a model can weigh what code already decided.
- Understanding and planning say the same of one input: `received` from an unknown sender in both.
- A model answering an unknown sender can now repeat the person's name (§6:3).
- Prompt wording stays free to settle: a change keeping the marked clauses needs no decision.
- **Revisit** when a second person is admitted, when a kind reaches strong, or when the audience
  milestone decides what an unknown sender's work is shown.

## Alternatives considered

- **Keep the framing and fix only the fallback**, naming an unknown sender in the old sentence.
  Not taken: the owner ruled that no line asserts a person typed it.
- **`said` for an unknown sender, as draft 1 had it.** Not taken: ADR-0351 §5:4 and ADR-0353 §3:2
  put words whose party is unknown in `received`.
- **"the owner" in a work that is no person's**, keeping ADR-0338 §2:3 whole. Not taken: the owner
  ruled for the name, and "the owner" names no one once a second person is admitted.
- **The account on every earlier item** (draft 1, choice 4). Not taken: about nineteen more
  spelled-out names in one message, for no fact the short name does not already carry.
