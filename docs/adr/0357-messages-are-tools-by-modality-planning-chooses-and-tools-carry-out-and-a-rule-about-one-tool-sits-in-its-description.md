# 357. Messages are tools by modality, planning chooses and tools carry out, and a rule about one tool sits in its description

- Status: Partially superseded by ADR-0361 (§2:2's `asks`; §2:11's *the person's yes to that exact call*; §3:1's *with the exact lines*; §4:4, whole; §7:2's last row; §8, whole) and ADR-0364 (§2:1's and §7:2's names; §2:2–§2:5's `to` and `via`; §2:6's person recipient and `attachments`; §2:7 and §2:8; §2:10; §2:11, made unconditional; §2:13; §3:1 and §3:2, in what the result shows planning; §4:2 and §4:3's `exact`; §5:4, where the tool used a described default; §5:9's line; §6:3's *goes back as needing them*; §7:2's human row; §10:1's `exact` and email tests)
- Date: 2026-10-30
- Scope: planning's tools, the second of the three decisions the planning proposal ([#3526](https://github.com/leonapivato/ai-assistant/pull/3526)) converts into. It decides the message tools, their arguments and what they return (§§2–4); one rule for how every tool divides a call between planning's choices and the tool's own work (§5), and what a tool does when it cannot carry a call out (§6); which rules move out of planning's instruction into which tool's description (§7); how a question names the calls it asks about, now that a message is a call (§8); where the place list renders (§2:13); and how the proposal's core sits in the set ADR-0356 offers on every round (§9). It is the proposal's changes 4, 5 and 9, with the asking message that approvals need. ADR-0356 decides the exchange, and the third, the memory decision, decides memory and the look-ups.
- Dependency: [ADR-0356](0356-the-system-briefs-planning-in-one-continuing-exchange-plannings-text-is-its-notes-and-an-episode-is-shown-by-its-short-view.md), Accepted and merged at `f9e68f725`: the exchange, which makes text outside a call planning's notes and a message a call (§7), offers every capability on every round (§4:3), and takes `asks` out of `RoundResponse` (§7:5). It leaves to this decision the message tools, the asking message, where a message call names its place, where the place list renders and the moved rules (ADR-0356 §15).
- Authorization: the owner accepted the planning proposal on 2026-10-30, at `06018f611`, verbatim: "accept it, convert to the ADRs". The acceptance comment on #3526 records the three-way split and that approvals take option a for now. The owner's rulings on the message tools, given the same day, are recorded in the proposal's change 4 and in "What it leaves open". The coordinator assigned 0357 and ratifies it once its reviews are green. The argument names of §2, the one-asking-message rule of §8:3, the lanes of §10, and putting `asks` on `text` alone (§8:1) are this lane's choices, not owner rulings.
- **Not a contract-surface decision.** No Protocol and no `core` type changes. A message call's result is the call's own result, which the call's episode entry holds as ADR-0356 §8:4 has it (§3); the calls a question asks about stay recorded in `PlanningRound.asked`, keyed by `QuestionPart`'s round and part, because a round has at most one asking message (§8:3); and every argument this decision names is in a capability's parameters schema, which `ToolDefinition` already carries. The place list's line in the briefing (§2:13) is rendered text. `PROTOCOL_VERSION` does not move under it.
- **Partially supersedes**, in the clauses §11's first table names: ADR-0321, ADR-0329, ADR-0349, ADR-0350, ADR-0352 and ADR-0356.
- Partially superseded: 2026-10-31 by [ADR-0361](0361-approvals-are-cards-the-person-taps-and-a-yes-is-a-one-time-ticket-for-the-exact-call.md) — §2:2's `asks`: `text` takes none. §2:11's *the person's yes to that exact call*: a ticket for it (ADR-0361 §5). §3:1's *with the exact lines (§8:2)*, and §4:4, whole: a message carries no exact lines. §7:2's last row: how approval works is said in `request_approval`'s description (ADR-0361 §2:10). §8, whole: a yes is asked for by `request_approval`, never by a message (ADR-0361 §2, §8:5). Every other clause stands. This replacement takes effect on ratification of ADR-0361. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-11-01 by [ADR-0364](0364-tools-describe-themselves-in-four-parts-every-result-opens-with-its-outcome-and-connections-replace-the-place-list.md) — §2:1's and §7:2's names: the tools are renamed as ADR-0364 §8:1 gives, `send_text` and `send_email` among them. §2:2–§2:5's `to` and `via`: `send_text` takes `connection` and `words` (ADR-0364 §9:1–§9:3). §2:6's person recipient and `attachments`, and §2:7 and §2:8, retired: every recipient is an address, and nothing is attached (ADR-0364 §9:13–§9:14). §2:10: `from` is a required `L` label naming an email account (ADR-0364 §9:11). §2:11, made unconditional: every email needs approval (ADR-0364 §9:12). §2:13: Connections replaces the place list (ADR-0364 §3:1). §3:1 and §3:2, in what the result shows planning: the outcome alone (ADR-0364 §9:5). §4:2 and §4:3's `exact`: exact parts are marked in the words (ADR-0364 §9:6–§9:9). §5:4, where the tool used the default its argument's description names (ADR-0364 §6:8). §5:9's line: the effects line (ADR-0364 §7). §6:3's *goes back as needing them*: refused (ADR-0364 §6:3). §7:2's row on never claiming to be human (ADR-0364 §9:10). §10:1's `exact` and email tests (ADR-0364 §14:4). Every other clause stands. This replacement takes effect on ratification of ADR-0364. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.

## Context

In this document a bare section reference, such as §5:2, is to this decision's own clauses.
Every other ADR's are written with its number, such as ADR-0321 §2:5.

### Saying something is planning's text, and its rules are planning's instruction

**What planning says is its round's text.** A round's message is the text of its response
(`RoundResponse.text`, ADR-0307 §3), delivered into the place the input came from (ADR-0306
§4:7) or, for an activation the Task Scheduler started, into the place on its place list
that the message names by its `L` label (ADR-0350 §6:7). The calls a question asks about
ride a reserved tool, `planning_round`, beside the episode notes (`ROUND_TOOL` in
`models/tool_calling.py`, ADR-0315 §3:3, ADR-0321 §2:3), and code appends one exact line for
each of them to the message (ADR-0321 §2:5). ADR-0356 replaces this: saying something to
anyone is a call, text outside a call is planning's notes, and `asks` leaves the response.
What the calls that say something look like is this decision.

**Email is a separate capability with its own shape.** `send_email` (`tools/send_email.py`)
sends from a connected account, the person's own, with `to`, `cc`, `bcc`, `subject` and
`body`. Its recipients are addresses, and a name that is not an address is refused rather
than looked up (ADR-0148 §5). It has no attachments.

**Rules about one tool live in planning's instruction.** Six decisions have planning's
instruction carry a line about a single tool:

| Rule | Where it is ruled |
| --- | --- |
| When to record a candidate, and what to say about it | ADR-0329 §6:1–§6:5 |
| When to note reliance on a memory | ADR-0329 §6:8 |
| When to take an offer | ADR-0349 §7:19 |
| Replacing, cancelling and snoozing reminders | ADR-0350 §9:3 |
| A stop or a cancel reaches only what the words cover | ADR-0352 §3:8 |
| How approval works, and explaining what a question asks | ADR-0321 §2:4, §2:9 |

Others are not in any ADR and are the instruction's own lines, such as when to start, note
or link a matter. ADR-0338 §5:6 has the instruction say that the assistant never claims to be
human, which ADR-0356 §10:6 moves into the message tools' descriptions with the rest of
ADR-0338's instruction lines. Every one of these
lines is in front of planning on every round, whatever the stimulus, and each matters only
when its tool is called. The proposal's principle is that the instruction carries only what
applies to every stimulus, and that a rule about one tool sits beside that tool.

**A tool's arguments mix choices with mechanics.** `send_email` takes addresses, which are how
a message is sent rather than to whom. Nothing says which of a tool's arguments planning must
always choose, what a tool does with one left out, or what it does when the arguments it was
given cannot be carried out together. Some tools refuse, some fill a default without saying
so, and planning cannot always tell from the result what was done.

### Approvals are stopped

ADR-0321 decided approvals: a question shows each call it asks about on an exact line, an
answer's understanding recorded a pointer to the question, and authorizing checked three facts
before letting the approved call run. ADR-0353 §11 stopped that until a later decision
redesigns approvals: understanding records no pointer, so no yes approves anything, and every
call that needs the person goes back to planning as needing them. The owner chose option a
for the redesign, for now: today's shape, with recognising the yes as understanding's ordinary
work. This decision carries the asking half of that shape across to message calls. It does not
make the redesign that lets a yes approve again (§12).

## Decision

We will make every message a call to a tool chosen by its modality, `text`, `email` and later
`speak`, which returns what was actually delivered, where and how it went; hold every tool to
one rule, in which planning names the choices and the tool carries out the rest and says what
it used, or comes back with what it needs; move each rule about one tool out of planning's
instruction into that tool's description; and have a question name the calls it asks about in
an argument of the `text` call that asks it.

### 1. Status, scope and delivery

> **Normative.** This document remains `Proposed` until the reviews `CONTRIBUTING.md` →
> "Finishing an ADR PR" requires have returned green on one tree and the authorization to
> ratify stands. An assigned number or a green review alone does not change its status.

> **Normative.** No lane implements this decision before it merges `Accepted` (ADR-0015 §5).

> **Normative.** The implementation is the lanes §10 sets out, and each keeps the gate green.

> **Normative.** Nothing in this decision widens where the assistant may send a message, who
> it may send one to, or what any call is allowed to do. Which places a message may go into
> and how a message call is checked, claimed and recorded are ADR-0356 §7:7–§7:10's; whether
> a call needs the person is the policy's.

### 2. The message tools

> **Normative.** Saying something to someone is a call to one of the message tools, chosen by
> the modality the person would name: `text` for a short written message, `email` for an
> email, and `speak` for voice.

> **Normative.** `text` is one capability for every platform a short written message can go
> by: the hub chat and Telegram as built, and iMessage, WhatsApp or another platform when each
> is built. Its arguments are `to`, who it is for, and `words`, what to say, both required;
> and `via`, where it goes, `exact` (§4) and `asks` (§8), each optional.

> **Normative.** `to` names a person as planning was shown them. Resolving the person to an
> address on the platform is the tool's, and a name that fits no one, or more than one person,
> comes back with who it could be (§6), never a guess.

> **Normative.** `via` names where the message goes: a place on the activation's place list,
> by its `L` label (ADR-0350 §5:13), or a platform by name. Left out, the tool chooses, and
> the result says what it chose (§3:1): the place the input came from; or, for an activation
> the Task Scheduler started, the one place its task suggests, or the line's chat where it
> suggests none. Where no such place is on the list, or the task suggests more than one, the
> call runs nothing and comes back with the places it may name (§6:2).

> **Normative.** A `text` naming a place or platform that the message place check (ADR-0306
> §4:1) does not allow runs nothing and comes back with the places it may use.

> **Normative.** `email` is today's `send_email` capability, renamed and reshaped. Its
> arguments are `to`, the recipients, `subject` and `words`, required; and `cc`, `bcc`,
> `attachments`, `from` and `exact`, optional. Each recipient is a person as planning was
> shown them or an address.

> **Normative.** `email` resolves a person to an address only from a source ADR-0148 §5:2
> allows, and before the call is authorized, so the ruling and the exact line cover the
> address the email goes to (ADR-0148 §1). Where no address is known, the call runs nothing
> and comes back saying that an address is needed (§6).

> **Normative.** An `attachments` item names a thing planning was shown. What can be attached
> is the email tool's, and an item it cannot attach comes back (§6) and sends nothing.

> **Normative.** `text` and `speak` are always sent as the assistant, in its own voice, and
> neither takes an argument naming whose voice. Sending a text or speaking in the person's
> name is a later decision.

> **Normative.** `email` is sent from the assistant's own address or from the person's, as
> `from` says. Left out, it is sent from the assistant's address where one is connected; where
> none is, the call runs nothing and comes back saying that only the person's address is
> available, so that sending in their name is always named.

> **Normative.** An email from the person's address never runs without the person's yes to
> that exact call (ADR-0321), whatever allows an email from the assistant's address.

> **Normative.** `speak` is not offered until a voice interface exists. The decision that
> builds it gives it this section's shape, with a person or a room in place of `via`, the
> device as the tool's mechanics, and coming back when others are present as its safe default
> (§5:8).

> **Normative.** The place list (ADR-0350 §5:10) renders in the situation section of
> planning's briefing (ADR-0356 §3:2), after the origin's line: its places under their channel
> headings, each carrying its `L` label as the attribute `label` (ADR-0356 §3:5), so that
> `via` can name one. It renders on every briefing, since spawn is offered on every round
> (ADR-0356 §4:3).

### 3. What a message call returns

> **Normative.** Every message call's result says: the text delivered, after any rewording
> (§4) and with the exact lines (§8:2); where it went, the platform and the place, by its
> label where it has one; and how it went: *sent*, *delivered*, *read*, *failed* or *unknown*,
> with the reason for a failure or an unknown.

> **Normative.** *Delivered* and *read* are reported only where the medium reports them by
> the time the call returns. Otherwise the result says *sent*.

> **Normative.** *Sent*, *delivered* and *read* are the call's *done*, *failed* its *not
> done* and *unknown* its *unknown* (ADR-0306 §5:1). An unknown is never reported as sent, and
> is never retried (ADR-0306 §5:13).

> **Normative.** The call's episode entry holds what §3:1 says, as ADR-0356 §8:4 has it, and
> this decision adds no `core` type for the result.

### 4. Rephrased by default, exact on request

> **Normative.** A message call's words are what planning means to say, written by planning
> in the call (ADR-0307 §3:3). Once the decision §4:5 names builds it, a wording step renders
> them by default for the person and the medium before they are sent: their preferences, the
> assistant's personality, written or spoken.

> **Normative.** With `exact`, the words are sent exactly as written, for a quote, a relayed
> message, an address or anything else where the wording itself matters.

> **Normative.** Until the wording step is built, every message's words are sent unchanged,
> `exact` or not, and `exact` is accepted and changes nothing.

> **Normative.** The wording step never changes the exact lines a question carries: code
> appends them after it (§8:2).

> **Normative.** How the wording step is built, which model it uses, how preferences and
> personality reach it and what it may never change, is a later decision, and no lane builds
> it under this one.

### 5. Planning chooses, tools carry out

> **Normative.** This section holds for every capability planning is offered.

> **Normative.** A **choice** is anything that changes what the action means or what it leads
> to, such as who, what, where, when or how much: anything the person could care which way it
> went. Every choice a capability has is one of its arguments, so planning can name any choice
> that matters.

> **Normative.** A capability's required arguments are the choices that cannot be left to the
> tool, and its parameters schema says which they are. Every other choice is an optional
> argument.

> **Normative.** An optional argument left out is the tool's to decide, by a default, by the
> person's known preferences, by asking a model, or by coming back (§6), and the result says
> what was used for each one, such as "sent by Telegram" or "the terrace table".

> **Normative.** **Mechanics** are never arguments: addresses where a person can be named,
> APIs, protocols, formats and retries are the tool's.

> **Normative.** A parameters schema states only which arguments are always required. A
> requirement that depends on other arguments, such as an amount for paying a person but not
> for paying a named invoice, a contact number for a large booking, or an address for an
> email to someone with none known, is the tool's check when called, and is never encoded in
> the schema by `if`/`then`/`else`, `dependentRequired`, `dependentSchemas`, or a `oneOf` or
> `anyOf` that varies which properties are required.

> **Normative.** A capability's description names the common cases of its conditional
> requirements.

> **Normative.** A condition planning states in the call, such as "only if she's alone", is an
> optional argument of the tool whose outcome turns on it. Without one, the tool takes the
> safe default its description names.

> **Normative.** Each capability's description says whether it is safe to repeat, as its
> declaration does (ADR-0306 §2:1). The hub writes that line from the declaration, so the two
> cannot disagree.

> **Normative.** The capabilities built before this decision are brought into line with this
> section in lane T2 (§10). One that already conforms is left unchanged.

### 6. Act, or come back with what's needed

> **Normative.** Where a tool can carry a call out, it acts and reports what it did. Where it
> finds, before it acts, that it cannot, it does nothing: it changes nothing and sends nothing,
> and its result is *not done*, saying why and what is needed to call it again, such as the
> valid options or the live facts.

> **Normative.** Once a tool has begun to act, a failure is reported as ADR-0306 §5:1 reports
> it, and an outcome it cannot establish, such as a send whose acknowledgement was lost, is
> *unknown*, never *not done*, and is never retried (ADR-0306 §5:13).

> **Normative.** A tool comes back in each of these cases: an argument that is missing, wrong,
> or needed because of the others, which it never guesses; values that cannot go together; a
> choice left to it that it has no way to decide; a condition the call states that fails; a
> person who cannot be reached. A call that needs the person's yes goes back as needing them,
> as ADR-0306 §4:8 and ADR-0321 §2:10 decide.

> **Normative.** A call to a capability that is not safe to repeat, whose values match an
> earlier effect, is refused as *already done* exactly where ADR-0306 §5:9–§5:11 refuse it,
> and passes where they let a deliberate repeat through. The result says which.

### 7. Rules beside their tools

> **Normative.** A rule about one tool is said in that tool's description, and not in
> planning's instruction. A rule that applies to every stimulus stays in the instruction,
> which ADR-0356 decides.

> **Normative.** The rules this table names move into the descriptions it names:
>
> | Rule | Into the description of |
> | --- | --- |
> | When to take or decline an offer (ADR-0349 §7:19), and to answer it in the round it comes | `answer_offer` |
> | Replacing, cancelling and snoozing reminders, and asking which where the words could mean more than one (ADR-0350 §9:3) | `spawn`, `cancel_task` and `list_tasks`, each the part about it |
> | A stop or a cancel reaches only what the person's words cover (ADR-0352 §3:8) | `stop_activation` and `cancel_task` |
> | When and how to start, note, link, unlink, move, merge, split or group matters, and the page-or-memory test (ADR-0300 §10, ADR-0303 §9, ADR-0307 §5:3–§5:5, ADR-0329 §6:1) | the matter calls, `start_story`, `note_story`, `link_story`, `unlink_story`, `move_story`, `merge_stories`, `split_story` and `group_stories`, each the part about it |
> | When to tidy a matter, and that a tidy-up brings no round (ADR-0307 §7, ADR-0356 §10:4) | `tidy_story` |
> | When to remember, what `confirm` is for, and what to say about it (ADR-0329 §5:1, §6:1–§6:5) | `remember` |
> | When to note the memories relied on (ADR-0329 §6:8) | `note_reliance` |
> | How messages behave: whose voice, rephrased unless `exact`, and what the result reports | `text` and `email` |
> | That the assistant never claims to be human (ADR-0356 §10:6) | `text`, `email` and, when built, `speak` |
> | That a suggestion is raised only where it bears on what is being done, and only by asking (ADR-0356 §10:7) | `set_profile` and `pin` |
> | How approval works, and to explain in the message's own words each action it asks about and the arguments that matter (ADR-0321 §2:4, §2:9) | `text`'s `asks` argument |

> **Normative.** What a moved rule says is the deciding ADR's as its status line leaves it.
> This decision moves where it is said, and changes what it says only as §§2–8 do.

> **Normative.** The descriptions §7:2 names ship in ADR-0356's P3 pull request (ADR-0356
> §14:10), so that every rule leaves the instruction in the change that puts it in its
> description, and no build carries neither.

> **Normative.** The exact words of each description are not decided here. The lane that
> builds them ships the words the coordinator routes from the owner's prompts front.

### 8. The asking message

> **Normative.** A question names the calls it asks about in the `asks` argument of the
> `text` call that asks it, each by the reference planning was shown it under, since no part
> of a response names them (ADR-0356 §7:5). `email` takes
> no `asks`, because an email's yes approves nothing (ADR-0323 §4:7), and `speak`'s is its
> own decision's.

> **Normative.** Code appends ADR-0321 §2:5's exact lines to the asking `text` call's words
> after any rewording, numbered as ADR-0321 §2:6 numbers them, and the delivered text the
> result returns carries them.

> **Normative.** A round has at most one asking message. A second `text` call in the round
> that carries `asks`, in the order the model returned them, runs nothing and comes back
> saying that the round's question is already asked.

> **Normative.** The round records the calls its asking message asks about as ADR-0321 §2:8
> decides, so a question's part stays the asking round's id and the part number (ADR-0321
> §4:9).

> **Normative.** A name in `asks` that resolves to no call needing the person is dropped, and
> the message is sent without a line for it.

> **Normative.** Invoking an approved call fills in exactly the values the question showed, as
> ADR-0321 §4:2 decides, and nothing planning sends beside its label changes them.

> **Normative.** Recognising a reply as a yes takes no path of its own. Understanding reads a
> reply as it reads any input, and is shown no question mark and no `Q` label (ADR-0353
> §11:1).

### 9. The core tool set

> **Normative.** The core the planning proposal names, the message tools, the look-ups the
> memory decision settles, `answer_offer`, `remember` and the reminder calls, is part of the
> set ADR-0356 §4:3 offers on every round, which holds every capability planning may call.
> `speak` joins it when built, and `email` where an account is configured.

> **Normative.** No capability leaves that set except by the decision that builds `use_tool`
> (§12).

### 10. Delivery

The lanes, each after this decision merges `Accepted`:

1. **T1, the message tools** (§§2–4, §8): `text` and `email` as calls, their arguments and
   results, the pass-through wording step, `asks` on `text` with the exact lines appended
   after it, and the place list in the situation (§2:13). It merges before ADR-0356's P1
   reaches a hub (ADR-0356 §14:11).
2. **T2, every tool under one rule** (§§5–6): bringing the capabilities built before this
   decision into line, the safe-to-repeat line written from each declaration, and §5:6's
   schema test.
3. **The moved rules** (§7) are not a lane of their own: they ship in ADR-0356's P3 (§7:4).

> **Normative.** Tests check: that a `text` with `exact` delivers its words unchanged apart
> from the exact lines; that the exact lines follow any rewording and are never reworded; that
> a second asking message in a round runs nothing; that an email from the person's address
> never runs without their yes; that a call that comes back changed and sent nothing; that a
> send whose acknowledgement is lost is reported *unknown*; that an accidental repeat is
> refused as *already done* and a deliberate repeat ADR-0306 §5:9 allows runs; that each
> message call's result carries the delivered text, where it went and how; that no offered
> capability's parameters schema encodes a conditional requirement; and that each offered
> capability's description says whether it is safe to repeat, matching its declaration.

### 11. Relationship to earlier decisions

Superseded in part. Every clause the middle column does not name stands:

| Earlier decision | What it replaces | By |
| --- | --- | --- |
| ADR-0321 | §2:3, in where the calls are named alone, ADR-0356 §7:5 having taken the response's carrying of the naming: the calls are named in the `asks` argument of the round's asking `text` call. §2:4's *its instruction tells it*, and §2:9's *Planning's standing instructions say*, each in where it is said alone: `text`'s `asks` argument's description says it. §2:5's *Code appends to the message*: to the asking `text` call's words, after any rewording. §2:8's *its message*: the round's one asking message | §7:2, §8:1–§8:4 |
| ADR-0329 | §6:1–§6:5 and §6:8, each in where the line is said alone: in the descriptions of `remember`, of the story calls for §6:1's story note, and of `note_reliance`, not in planning's instruction | §7:1–§7:3 |
| ADR-0349 | §7:19's *Planning's instruction says, in one line*, in where it is said alone: `answer_offer`'s description says it | §7:1–§7:3 |
| ADR-0350 | §9:3's *Planning's instruction says four things*, in where they are said alone: the descriptions of `spawn`, `cancel_task` and `list_tasks` say them | §7:1–§7:3 |
| ADR-0352 | §3:8's *Planning's instruction says, in one line*, in where it is said alone: the descriptions of `stop_activation` and `cancel_task` say it | §7:1–§7:3 |
| ADR-0356 | §3:2's table, its situation row, in the addition alone: the situation also renders the place list, each place with its `L` label | §2:13 |

Read through and not superseded, each a stacked addition under ADR-0082 §1 or no change:

| Earlier decision | What changes |
| --- | --- |
| ADR-0306 §2, §5:1, §5:9 | Nothing: §5 and §6 add rules beside the declaration's, and no sentence of ADR-0306 becomes false. The safe-to-repeat line is written from the declaration (§5:9); coming back is ADR-0306's *not done* with its reason (§6:1), an outcome not established after acting stays *unknown* (§6:2), and the repeat check is §5:9–§5:11's, deliberate repeat included (§6:4). A tool that asks a model to decide a choice (§5:4) is no model in acting, as a tidy-up's call is not (ADR-0300 §10:4) |
| ADR-0306 §4, ADR-0350 §6:7–§6:8, ADR-0349 §7:18, ADR-0356 §7:7–§7:10 | Nothing: no place is widened (§1:4). `via` is how a message call names where it goes, under the same list and the same check, as ADR-0356's record on ADR-0350 §6:7 leaves to this decision (§2:4) |
| ADR-0307 §3:3 | Nothing: planning writes a message's words, in the call, and no compose step runs until the decision on the wording step (§4:1, §4:5) |
| ADR-0148 §1, §5 | Nothing: an email's address is resolved from a source §5 allows, before the ruling (§2:7) |
| ADR-0323 §4:7, §6 | Nothing: the line's writer is the route `text` takes to Telegram, and an email's yes still approves nothing (§8:1) |
| ADR-0300 §10, ADR-0303 §9, ADR-0307 §5:3–§5:5, §7 | Nothing: no clause has planning's instruction carry a story call's rule. The instruction's lines about them, which ADR-0356 §10's table sends here, move into the matter calls' descriptions (§7:2) |
| ADR-0321 §2:6, §2:12, §4 | Nothing: the exact lines are numbered as before, a question is an ordinary message call, and authorizing's approval rules stand |
| ADR-0338 §5:6, §7:8, ADR-0356 §10:6, §10:7 | Nothing: ADR-0356 replaced the instruction's lines, and the descriptions they name say them (§7:2) |
| ADR-0356 §4:3–§4:6 | Nothing: every capability stays offered on every round (§9) |
| ADR-0353 §11 | Nothing: no yes approves anything until the decision §12 names |

> **Normative.** This numbered draft records its replacements on the status lines and in a
> dated header note of ADR-0321, ADR-0329, ADR-0349, ADR-0350, ADR-0352 and ADR-0356,
> atomically with
> this ADR under ADR-0070 and ADR-0082, preserving their ratified bodies. The replacements take
> effect on this ADR's ratification.

### 12. What this decision does not decide

| Not decided here | Where it goes |
| --- | --- |
| A recognised yes approving the call again: what authorizing reads in place of ADR-0321 §3:1's pointer, now that understanding records none (ADR-0353 §11:3), and where approved actions render (ADR-0356 §15) | The authority decision that redesigns approvals, under option a |
| How the wording step is built (§4:5) | A decision of its own |
| `speak`: presence, and whether private content may be spoken where others are present | The decision that builds voice, with the audience and privacy work |
| Texting or speaking in the person's name (§2:9) | A later decision |
| Messaging a place or person beyond those ADR-0356 §7:7 and §7:10 allow | A decision on where the assistant may speak |
| `use_tool(name, arguments)` with tool search, for tools beyond the core | The decision on tools and skills held in memory, which is direction only |
| *Delivered* and *read* arriving after the call returns | A later decision, as news under ADR-0356 |

> **Normative.** Each item the table names takes a decision of its own before any lane builds
> it.

## Consequences

- Planning's instruction loses every rule about one tool, and each tool carries its own rules
  where planning reads them at the moment it considers the call.
- A message is an action with a result: planning sees what was delivered, where and how, can
  check that rewording kept its meaning, and can report a failure truthfully.
- Planning can choose the medium: a quick text, a formal email, and later speech.
- A tool author decides, through the schema, what planning must always choose. Tools can get
  smarter at filling the rest without planning changing, because the result always says what
  was used.
- Schemas stay simple for models and for providers' strict modes. A missed conditional
  requirement costs one round, not a mistake.
- An email from the person's address always waits on their yes, and while approvals are
  stopped (ADR-0353 §11) no such email runs at all.
- A round can ask only one question. Two questions the person must answer go in one message,
  with numbered parts.
- Moving a rule and removing it from the instruction ship together, in ADR-0356's P3.

## Alternatives considered

- **One wide `say` tool** with who, where and in whose name as arguments. Rejected by the
  owner: "in whose name" changes the stakes, the permission and the style, so it is a
  different act. Tools by modality match how people think and let planning choose the medium.
- **A person, with code choosing how to reach them.** Rejected by the owner: planning names
  who and where. `via` is optional only so the tool can use how the person likes to be
  reached, and the result says what it used.
- **Fixed rules for which choices a tool may make,** such as filling a missing choice only
  from known preferences. Rejected: planning names any choice that matters and leaves an
  optional one to the tool, however it decides, as long as the result says what was used.
- **Conditional requirements encoded in the schema** (`if`/`then`, `oneOf`). Rejected: models
  fill complex schemas less reliably, and providers' strict modes support only part of it.
- **`asks` on every message tool.** Not taken: an email's yes approves nothing (ADR-0323
  §4:7), so an email cannot carry a question, and voice's authority is voice's own decision.
- **Several asking messages in one round,** with each question keyed by its message call.
  Not taken: it changes `QuestionPart` and the delivery fact authorizing checks, a `core`
  change for a case one numbered question already covers.
- **Rules kept in the instruction, beside the tools' descriptions.** Rejected: every rule is
  then in front of planning on every stimulus, and the instruction grows with every tool.
