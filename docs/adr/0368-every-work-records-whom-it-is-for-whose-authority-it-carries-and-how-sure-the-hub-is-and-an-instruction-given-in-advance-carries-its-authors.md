# 368. Every work records whom it is for, whose authority it carries and how sure the hub is, and an instruction given in advance carries its author's

- Status: Proposed
- Date: 2026-11-22
- Scope: lane 4 of the seven decisions the people, authority, audience and outside content
  proposal ([#3628](https://github.com/leonapivato/ai-assistant/pull/3628)) is cut into
  ([#3629](https://github.com/leonapivato/ai-assistant/issues/3629)), the lane
  [ADR-0365](0365-one-hub-serves-several-people-each-is-the-top-of-their-own-domain-and-separate-households-keep-separate-hubs.md)
  §6 names fourth: whose work it is. It decides the three facts code records on every work
  (§2); how each kind of input starts a work (§3); a work holding several inputs, from several
  senders or from one sender by several connections (§4); that no work acts on another person's
  behalf (§5); that an instruction given in advance is no special case (§6); the person and level
  ADR-0367's check runs for, for each kind of work (§7); and that what a work is shown is filtered
  to its authority (§8). §9 reads the earlier decisions' words for one person in this decision's
  terms, §10 records what it does to earlier decisions, §11 names the contract changes it would
  need, §12 what it leaves to others, and §13 what it settled where the rulings left a point open.
- Authorization: the owner accepted the proposal on 2026-11-22 ("Yes, accepted", to "Is the
  proposal accepted for conversion into ADRs?") and ruled its points in walks with the
  coordinator. Their words, verbatim. On the three facts and the starts: "I think it looks good,
  any gaps you see?" (2026-11-19; §2, §3). On joining: "1. Yes or maybe it can join but take the
  lower permissions, if its 2 groups that have higher perms in 1 area and lower in another, than it
  takes the lower of every. Is it possible an activation starts with more than 1 sender?"
  (2026-11-19; §4:3 to §4:5), and "Yes, shared place only" (2026-11-22; §4:3). On the same person
  from a second place: "in my mind this just takes on the rules we currently have, about least
  privilage" (2026-11-22; §4:1, §4:2). On acting for someone else: "3. Asking for something on
  another persons behalf shouldnt be a thing. In the case you showed, its just you asking to remind
  Sam, with a specific message, thats on your behalf" (2026-11-19; §5). On instructions given in
  advance: "why should instructions given in advance be treated differently than instrucitions
  given right now?", then, to the two recorded points, "yes record both" (2026-11-19; §6). On what
  a work is shown: "yes, it should be filtered" (2026-11-19; §8). The coordinator assigned 0368 and
  ratifies it, under the owner's delegation, once its reviews are green.
- **Contract-surface decision; a decision only.** This document changes no Protocol, type, field
  or code. It decides what every work carries and what ADR-0367's check reads of it, which bounds
  the `core` types the build makes, so it takes the adversarial and the architecture review.
  Building it is a breaking change under golden rule 5, through the `core` changes §11 names, none
  of which is made here. It dispatches no implementation (§1:2).
- **Partially supersedes**
  [ADR-0292](0292-a-channel-is-the-spokes-facing-one-thing-and-the-assistants-edge-is-its-own.md)
  (§5:5, in the addition alone; §5:6, whole),
  [ADR-0323](0323-a-telegram-chat-with-the-owners-bot-is-a-line-to-the-assistant-and-connecting-it-approves-what-the-line-carries.md)
  (§4:5's *only whether the input carries the user's authority*; §4:6, in the addition alone),
  [ADR-0338](0338-a-person-sets-their-profile-and-pins-what-aether-always-keeps-in-mind-their-style-is-learned-as-memories-and-each-reaches-the-models-for-that-persons-activations.md)
  (§2:2, whole),
  [ADR-0350](0350-every-spawn-is-a-scheduled-task-written-into-the-task-scheduler-whose-sensor-starts-it-when-it-comes-due-and-the-task-manager-is-the-one-way-in-from-outside.md)
  (§3:7, in the addition alone; §3:9's first two sentences; §6:2's *and it carries no authority*),
  [ADR-0351](0351-an-input-carries-the-parties-whose-words-it-is-and-outside-content-authority-and-a-supports-holder-follow-from-them.md)
  (§6:1, in the addition alone; §6:4, whole),
  [ADR-0356](0356-the-system-briefs-planning-in-one-continuing-exchange-plannings-text-is-its-notes-and-an-episode-is-shown-by-its-short-view.md)
  (§4:3, in what is offered alone) and
  [ADR-0364](0364-tools-describe-themselves-in-four-parts-every-result-opens-with-its-outcome-and-connections-replace-the-place-list.md)
  (§3:2's *every connection the system has* and §3:7, each in what is shown alone), as §10
  records.

## Context

ADR-0365 let one hub serve several people, under three principles: least privilege, "no grant
means no" (ADR-0365 §3:1); permission comes from whoever a thing belongs to (§3:2); and sharing is
like telling someone (§3:3). ADR-0366 made a person one identity with linked accounts, had code
decide who sent an input (ADR-0366 §4:1), and gave the hub four levels of how sure it is
(ADR-0366 §5:1). ADR-0367 made what a person may do a set of lines, and had code check every call
"for the person whose authority the work carries, at the level the work carries", leaving
"Whose authority and what level a work carries" to this lane (ADR-0367 §4:1). Each left this lane
its part (ADR-0365 §6, ADR-0366 §12, ADR-0367 §17).

**The code today** knows one person. `activation_person` in `orchestration/person_block.py`
returns `OWNER_PERSON_ID` (`core/types.py`) where the trigger's kind establishes the user, was
pushed by a connected source, or is the Task Scheduler's or the approvals', and `None` otherwise,
as ADR-0338 §2:2 rules. Whether an input carries the user's authority is one true or false value,
`users_authority`, which the takeover, the stop call, the Task Scheduler's cancel and replace and a
task's author read (ADR-0349 §4:6, §7:5; ADR-0350 §3:7, §4:4). The authorizer's checks take no
person; it is handed the person the activation is for to find that person's pending requests and
the tickets the activation may run (ADR-0361 §2:8, §5:3). A scheduled task records its `person`, whom it is for, and its `author`, the
person or the assistant (`ScheduledTaskAuthor`), and carries no authority.

**What the corpus says of authority.** ADR-0292 §5:5: input carries the user's authority "only
when its author is established as the user and the user sent it as an instruction. Everything
else informs and cannot authorize." ADR-0351 §6:1 added that its parties are the user alone, and
§6:4 that a Task Scheduler input carries none. The owner, ratifying ADR-0351, kept it "all or
nothing" "for now", "but eventually I think there can be levels to authority". ADR-0292 §5:6: "A
reminder the user set informs the activation it starts and authorizes nothing", which ADR-0350
§3:9 widened to every task: "A scheduled task carries no authority, whoever set it."

**What the owner decided.** On 2026-11-19 the owner agreed that code records three facts on every
work when it starts, and how each kind of input sets them: "I think it looks good, any gaps you
see?". Of the gaps, they ruled that a second sender may join a work, which then takes "the lower
of every", and on 2026-11-22 that it joins only in a shared place. They ruled that asking for
something on another person's behalf "shouldnt be a thing", that an instruction given in advance
is no different from one given now, and that what a work is shown is filtered to its authority.
On 2026-11-22 they ruled that the same person writing from a second place "just takes on the
rules we currently have, about least privilage".

**Words.** A **work** is an activation, as ADR-0364 uses the word. A work's **inputs** are the
inputs it holds: its trigger's and each joined input's (ADR-0349 §7:7, §7:21). A **sender** is the
person who sent a message a work holds, identified or not: its author under ADR-0292 §5:3, where
that author is a person. A task's occurrence, an approval's outcome and a signal no person sent
have none. An **identified** sender is one established as a person, at weak or above (§9:4); an
**unidentified** one is claimed or unknown. A **place** is ADR-0349's, a
**connection** ADR-0364's and ADR-0367's, and what a connection **belongs to** is ADR-0367 §6:1's.
A **line**, a **grant**, a **limit**, a **bar** and **the check** are ADR-0367's (§3:1, §3:2,
§4:1); a **level** is one of ADR-0366 §5:1's. A **task** is a scheduled task (ADR-0350 §3:6). A
**standing rule** is an instruction a person sets in advance that a signal, rather than a time,
brings due; no decision builds one yet. **Upkeep** is what the system does to its own records with
no person asking. **Admits** is ADR-0365's word. A **later decision** is one of lanes 5 to 7 of
#3629, none of which has a number yet. In this document a bare section reference, such as §4:2, is
to this decision's own clauses.

## Decision

We will have code record, on every work when it starts, whom it is for, whose authority it carries
and how sure the hub is; set them from how the work was started and never from what its inputs
say; let a work holding several inputs hold only what holds for every one; give an instruction
given in advance its author's authority, checked when it runs; and show each work only what its
authority could use.

### 1. Status, scope and delivery

> **Normative.** No lane implements against this decision before it merges `Accepted` (golden
> rule 5, ADR-0015 §5).

> **Normative.** This decision dispatches no implementation. What is built from it, and when, is
> the owner's planning call, made after it merges.

> **Normative.** Until the three facts (§2) are built, code reads whom an activation is for and
> whether its input carries the user's authority as it does today, and nothing in this decision
> changes what the running hub allows, asks or shows.

> **Normative.** This decision admits no one. It is one of the later decisions ADR-0367 §1:4 names
> as conditions before a person other than the owner is admitted, and what it rules a second person
> needs built is §2's three facts recorded on every work and read by the check as §7 gives; §6's
> task record, with its end at its author's removal; and §8's filtering of the tool list and the
> Connections section, and of the People section where that is built.

> **Normative.** §4:3 to §4:6 are built before any place two people the hub admits can both write
> into is.

ADR-0365 §1:3 keeps the owner the only person a hub admits until a later decision provides for
admitting another and that provision is built. This decision is part of that provision, not the
whole of it: lanes 5 and 6 of #3629 remain among ADR-0367 §1:4's conditions.

### 2. Three facts on every work

Code records three facts on every work. Lanes 5 to 7 of #3629 build on them, so they are numbered
here and nowhere else.

> **Normative.** **Who it is for**: one person, one group, or no one.

> **Normative.** **Whose authority it carries**: its senders now, each identified or not (§3); a
> person in advance, the author of a task or a standing rule (§6); or none.

> **Normative.** **Its sureness**: one of ADR-0366 §5:1's levels.

> **Normative.** Code records the three facts when the work starts, from its recorded inputs and
> the records they name, and records them again when an input joins it (§4). No model sets or
> changes any of them, and nothing an input says counts toward one (ADR-0292 §5:8).

> **Normative.** An input that joins a work never adds to the authority the work carries and never
> raises its level.

> **Normative.** Code records an input's level, as ADR-0366 §5:6 sets it, on the input beside its
> author, and a recorded message's on the message where its trigger records messages (ADR-0351
> §2:6).

> **Normative.** Where a model is shown whom a work is for or whose authority it carries, it is
> shown them by person and group labels alone (ADR-0366 §8:1, ADR-0367 §13:1), never by a stored
> identifier and never as a line.

Whether a model is shown any of the three, where, and in what words, is the next prompt review's.
The readers of each, as the corpus has them:

| Fact | Read by |
| --- | --- |
| Who it is for | The person block (ADR-0338 §2:3); the observer (ADR-0338 §2:5); a task's person and its work's (ADR-0350 §3:5, §6:4); spawn's offer (ADR-0350 §3:4); an approval request's person (ADR-0361 §2:5, §2:6, §6:1); the running work of the same person and their last stimulus (ADR-0349 §5:3, ADR-0364 §2:2) |
| Whose authority it carries | The check, on every call (ADR-0367 §4:1); the stop call's offer (ADR-0349 §4:6, §4:8); the takeover's conditions (ADR-0349 §7:5, §7:12, §7:15, §7:17); a task's author, and cancel and replace (ADR-0350 §3:7, §4:4); filtering (§8) |
| Its sureness | The check (ADR-0367 §5:1, §5:2); the card when a level falls short (ADR-0367 §5:3, §5:4); a task's record (§6:3) |

The proposal also named recall, notifications and memory as readers. What a work for a person or
a group may read, and where a record lands, are lane 5's; whom a message reaches is lane 6's; and
whether outside content bears on a level is lane 7's. Each reads these facts as it rules.

### 3. How each kind of input starts a work

| Input | Who it is for | Whose authority | Level |
| --- | --- | --- | --- |
| A message from an identified sender | The sender | The sender, where §3:2's conditions hold; none otherwise | The input's |
| A message from an unidentified sender | Whoever its connection belongs to | The unidentified sender: what anyone holds on that connection | None |
| A signal no person sent | Whoever its connection belongs to | None, or a standing rule's author (§3:6) | None, or the rule's (§6:3) |
| A task's occurrence | Whom its task is for (ADR-0350 §6:4) | Its task's author, in advance (§6) | Its task's (§6:3) |
| An approval's outcome | The request's person (ADR-0361 §6:1) | None; the ticket's call is checked as ADR-0367 §5:5 rules | None |
| The system's own upkeep, or a pass no channel admitted | No one | None | None |

> **Normative.** A message whose sender is identified is for that sender.

> **Normative.** An input carries the authority of the person who sent it only where its author is
> established as that person, that person sent it as an instruction, and its parties are that
> person alone. It carries it at the input's level, and every other input from an identified
> sender carries none.

> **Normative.** A message whose sender is unidentified is for whoever the connection it came by
> belongs to (ADR-0367 §6:1).

> **Normative.** A message whose sender is unidentified carries that sender's authority at none:
> only grants to anyone apply to its work (ADR-0367 §2:3, §5:2), and among them only those whose
> conditions the work meets (§4:2), which is what anyone holds on that connection.

> **Normative.** An input no person sent, whose author is a service or that has none, such as a
> doorbell ring or an event a connected source pushes, is for whoever its connection belongs to
> and carries no authority, at none.

> **Normative.** Only a standing rule a person set acts on an input no person sent. Where one
> covers it, its work carries the rule's author's authority, in advance, as a task's work carries
> its author's (§6).

> **Normative.** Where the system's own upkeep runs as a work, it is for no one, carries no
> authority, and makes only the calls code lists for that job, none of which leaves the hub.

ADR-0351 §6:2 and §6:5 stand: a party in what a sender forwards, quotes or relays carries no
authority, and a relayed input carries none, whatever its sender. §3:2 is ADR-0351 §6:1 restated
for several people with a level; it keeps every condition and adds none. How a standing rule
covers a signal, and which place a signal lands in, are for the decision that builds standing
rules and for lane 6. Upkeep the corpus already runs outside planning, such as ADR-0358's tidy-up,
is not a work and is unchanged.

### 4. A work holding several inputs

> **Normative.** A work with senders is at the lowest level among its senders' inputs, and an
> input with no sender, such as an approval's outcome offered to the work that asked (ADR-0361
> §6:4), lowers nothing.

> **Normative.** A grant whose condition names a connection applies to a work's calls only where
> every one of its senders' inputs came by that connection, and in a task's work as §6:4 rules.

> **Normative.** An input whose sender is not already one of a work's senders joins it only where
> it came from the place an input of another of its senders came from. A message from another
> person in a different place starts its own work.

> **Normative.** A work with several senders holds, area by area, only what every one of them
> holds: the check runs for each, as §7:3 rules.

> **Normative.** §4:1 to §4:4 hold alike for a work whose senders' inputs joined it and for one
> whose first input already carries several senders' messages, as one a start wait takes in
> (ADR-0332 §5).

> **Normative.** A work with several senders is for whoever its shared place belongs to: the
> person or group its connection belongs to (ADR-0367 §6:1), until a later decision records a
> place as someone's of its own.

**The same person from a second place** takes no new rule. The owner's words: "in my mind this just
takes on the rules we currently have, about least privilage". A work that holds one sender's inputs
from several connections, as ADR-0349 lets it absorb them today, takes the lowest level of them
(§4:1) and holds only the grants whose conditions hold on every one (§4:2). What it does to the audience mark
is lane 6's.

**Joining, as the corpus has it.** ADR-0349 absorbs and offers an input only where it has the same
author, established in the same way, the same authority and the same origin as the work's
(ADR-0349 §7:5, §7:12, §7:15, §7:17). Those clauses stand, so today no input from a second sender
joins any work. §4:3 bounds where one may, and §4:4 rules what the work then holds, for whichever
decision widens them to let one. A second person's work in another place may tell this one
something through a share, and that authorizes nothing (ADR-0349 §6:12): it makes no one a sender.

### 5. No acting on another person's behalf

> **Normative.** No work carries one person's authority on another person's behalf. A request
> about another person, such as "remind Sam", is its sender's own call, checked for the sender
> (ADR-0367 §4:1).

The owner's words: "its just you asking to remind Sam, with a specific message, thats on your
behalf". Messaging Sam is covered as ADR-0367 §12 rules. A request that depends on Sam's answer is
ADR-0367 §11's grant for one call, and §8:6 says where it appears to Sam's work.

### 6. An instruction given in advance is no special case

The owner asked: "why should instructions given in advance be treated differently than
instrucitions given right now?"

> **Normative.** A task carries the authority the work that set it carried, at that work's level:
> its author's, or, where that work had several senders, each of theirs, checked as §7:3 rules.
> Where that work carried none, the task carries none.

> **Normative.** Each call a task's work makes is checked against its author's lines, or each
> author's, as they stand when the call is checked, never as they stood when the task was set.

> **Normative.** A task records who set it and the level of the work that set it, and no list of
> the actions or calls it may make.

> **Normative.** A grant's condition naming a connection is met in a task's work where it was met
> in the work that set the task.

> **Normative.** A task ends when it is cancelled, at its end date where it has one, or when its
> author is removed.

> **Normative.** Removing a person ends every task they authored, as a cancel ends it, at the
> removal. From then on no call of a work such a task started is allowed, since its author holds
> no line (ADR-0367 §7:11).

> **Normative.** A standing rule is a task in every clause of this section.

Spawn is offered only to a person's work (ADR-0350 §3:4, read by §9:5), so no work for a group
sets a task. An author is the person ADR-0350 §3:7 records, and a task set by a work with several
senders has each of them as an author. "No per-task list of allowed actions" and the end at
removal are the owner's two recorded points ("yes record both"). The level a task records
is its setting work's, and a later lowering of a link (ADR-0366 §5:5) does not change it. No
approval given in the work that set a task carries over to its work (ADR-0350 §3:9's third
sentence, ADR-0321 §4:1).

### 7. The person and level the check runs for

ADR-0367 §4:1 reads them from this decision.

> **Normative.** The check runs for whose authority a work carries (§2:2), at the work's level
> (§2:3), as the table below gives for each kind of work.

> **Normative.** For an unidentified sender, the check runs for a member of anyone alone, so only
> grants to anyone apply (ADR-0367 §5:2).

> **Normative.** For a work with several senders, the check runs for each sender at the work's
> level. A call is not done where the check would not do it for any one of them; otherwise it
> needs a yes where it needs one for any of them, each such yes being the one ADR-0367 §5:3 and
> §5:6 name for that sender; and it is done only where it is allowed for every one.

> **Normative.** A work that carries no authority holds no grant: the check allows none of its
> calls, save a message ADR-0367 §4:7 keeps outside the check, a call run under a ticket, which
> ADR-0367 §5:5 checks for its tapper, and an upkeep job's own calls (§3:7).

| Work | The check runs for | At |
| --- | --- | --- |
| An identified sender's message carrying their authority | That person | The input's level |
| An unidentified sender's message | A member of anyone alone | None |
| Several senders | Each sender; done only where done for every one (§7:3) | The lowest of its senders' inputs' (§4:1) |
| One sender by several connections | That person, with the grants whose conditions hold on every connection (§4:2) | The lowest of its inputs' (§4:1) |
| A task's work, or a standing rule's | Its author, or each of its authors, with their lines as they stand (§6:2) | The level the task records |
| A work that carries none: a signal no rule covers, a forward or relayed input, an approval's outcome, upkeep | No one: no grant applies (§7:4) | None |

A call run under a ticket is checked for the person whose tap approved it, at the level that tap
came by, whatever the work carries (ADR-0367 §5:5).

### 8. Filtered to the work's authority

The owner's words: "yes, it should be filtered". A tool, a connection or a person the work's
authority **could use** is one on which some call of the work could be allowed, at its level, by a
card (ADR-0367 §5:3) or under a ticket it holds (ADR-0367 §5:5), or which the check would not reach
(ADR-0367 §4:7).

> **Normative.** The capabilities offered to a work are only those its authority could use. They
> are fixed when its first round is briefed, in ADR-0356 §4:3's one fixed order, and do not change
> for the rest of the work.

> **Normative.** The Connections section (ADR-0364 §3:1) shows only connections the work's
> authority could use, and `search_connections` (ADR-0364 §3:7) finds only those.

> **Normative.** The People section (ADR-0366 §9:7) shows only people the work's authority could
> use.

> **Normative.** Filtering shows what a work could use and never why: no line or bar is shown in a
> briefing (ADR-0367 §3:7).

> **Normative.** Every call a work makes is still checked, whatever it was offered or shown
> (ADR-0356 §4:7).

> **Normative.** A grant for one call (ADR-0367 §11) appears to the work that may use it only as
> §8:1 to §8:3 show anything: the capability and the thing it covers are offered and shown to that
> work because a line allows them. Nothing else of it is shown until ADR-0367 §11:5's further
> decision says what.

The People section's contents are the next prompt review's, and what a work may read of another
person's domain is lane 5's: §8:3 decides only that the section is filtered. A connection a work's
own input came from is one it could use, since a reply into it is outside the check.

### 9. The earlier decisions' words for one person

> **Normative.** Where an earlier decision reads whether an input or an activation carries the
> user's authority (ADR-0292 §5:5), it reads whether the work carries an identified person's
> authority under §2:2, now or in advance, and where it names the user, it names that person, or
> each of several senders.

> **Normative.** Where an earlier decision compares two inputs' authority, as ADR-0349 §7:5,
> §7:12, §7:15 and §7:17 do, two inputs carry the same authority where they carry that of the same
> person or people, whatever their levels.

> **Normative.** Whether two inputs' authors are established in the same way (ADR-0349 §7:5) is
> read on ADR-0292 §5:3's how sure, not on their levels.

> **Normative.** An author established under ADR-0292 §5:3 is at weak or above, and one claimed or
> unknown is at none. ADR-0292 §5:3's how sure stands, and the level is a fact recorded beside it
> (§2:6).

> **Normative.** Where an earlier decision reads whether an activation is a person's (ADR-0338
> §2:2), as ADR-0338 §2:3, ADR-0350 §3:4, ADR-0356 §4:5 and ADR-0361 §2:5 do, it reads whether the
> work is for a person and its senders, where it has any, are identified.

> **Normative.** A user assertion, as ADR-0099 §4:1 reads ADR-0092 §4's, is the assertion of the
> person an input's author is established as, in an input that is that person's own (ADR-0351
> §5:2), and it is that person's.

> **Normative.** The side planning takes in a household (ADR-0356 §15) is whom its work is for
> (§2:1), within the authority the work carries (§2:2). What protects another person is the check,
> not planning's side (ADR-0365 §5:1).

> **Normative.** This decision is not the decision on a mail channel ADR-0351 §3:3 waits for. A
> mail sender stays claimed until a decision rules how that channel establishes one, and declares
> its kind's most under ADR-0366 §5:2.

§9:5 keeps today's reach: an unidentified sender's work was no person's, and it stays one that is
given no person block, is offered no spawn and calls no `request_approval`, though it is now for
someone. Which beliefs a person's assertion reaches is where a record lands, lane 5's.

### 10. Relationship to earlier decisions

> **Normative.** This numbered draft records its replacements on the status lines of ADR-0292,
> ADR-0323, ADR-0338, ADR-0350, ADR-0351, ADR-0356 and ADR-0364 and in a dated header note on
> each, atomically with this ADR under ADR-0070 and ADR-0082, preserving their ratified bodies. The
> replacements take effect on this ADR's ratification.

Superseded:

| Clause | Becomes |
| --- | --- |
| ADR-0292 §5:5, the user's authority | In the addition alone: an input carries its identified sender's authority at its level (§3:2), an unidentified sender's carries what anyone holds on its connection (§3:4), and a task's work carries its author's (§6:1) |
| ADR-0292 §5:6, a reminder authorizes nothing | Whole: a task carries its author's authority (§6:1) |
| ADR-0323 §4:5's *only whether the input carries the user's authority* | Authorizing reads whose authority the work carries and its level (§7). Its second sentence, that no rule of authorizing names a channel, stands |
| ADR-0323 §4:6, the line's input and the user's authority | In the addition alone: an input whose messages are several identified senders', none a forward, carries what every one of them holds (§4:4) |
| ADR-0338 §2:2, the owner's or no person's | Whole: who a work is for is §2:1, set as §3 and §4:6 rule. Its three cases are §3's first, third and fourth rows, and the owner is whoever the connection belongs to until another person is admitted |
| ADR-0350 §3:7, a task's author | In the addition alone: the author records the person it names, or each of a setting work's several senders, and the level of the work that set the task (§6:1, §6:3) |
| ADR-0350 §3:9's first two sentences, a task carries no authority | A task carries its author's authority (§6:1). Its third sentence, that no approval carries over, stands |
| ADR-0350 §6:2's *and it carries no authority (§3:9)* | Its work carries its task's author's authority (§6:1) |
| ADR-0351 §6:1, the user's authority | In the addition alone: restated for several people with a level (§3:2); its conditions stand |
| ADR-0351 §6:4, a Task Scheduler input carries no authority | Whole: a task's work carries its author's authority, from its task's record and not from its input's parties (§6:1) |
| ADR-0356 §4:3, every capability on every round | In what is offered alone: only what the work's authority could use, fixed for the work (§8:1). The one fixed order stands |
| ADR-0364 §3:2's *every connection the system has*, and §3:7 | In what is shown alone: only connections the work's authority could use (§8:2) |

Taken, with nothing superseded:

| Clause | What this decision takes |
| --- | --- |
| ADR-0367 §4:1, whose authority and what level a work carries | §2:2, §2:3 and §7 |
| ADR-0367 §11, how the answerer's work learns of a grant for one call | §8:6, the least: where it appears. ADR-0367 §11:5's bar stands |
| ADR-0367 §16's *the person and level the check runs for come from wherever lane 4 records them on a work* | §2:4 and §11 |
| ADR-0366 §12's lane 4: what a work carries, how a level bears on ADR-0292 §5:3 and ADR-0351 §3, and filtering | §2, §9:4, §9:8 and §8 |
| ADR-0365 §6's lane 4, including whose assertion ADR-0099 §4:1 reads as the user's | §2 to §7 and §9:6. ADR-0099 §4:1 stands |
| ADR-0356 §15's row *Whose side planning takes in a household* | §9:7. Its condition, the owner holding full control, holds until another person is admitted |

Read through and standing, each as written:

| Clause | Why it stands |
| --- | --- |
| ADR-0338 §2:1 | §1:4 admits no one, and ADR-0366 §2:6 and ADR-0367 §15 keep the bar |
| ADR-0338 §2:3 to §2:5 | Read by §9:5: an unidentified sender's work gets no person block. The observer reads §2:1 |
| ADR-0292 §5:3, §5:7 and §5:10 | §9:4 sets the level beside how sure. A message that waited keeps its authority, read per person (§9:1) |
| ADR-0351 §3:3 | §9:8: it still waits for a decision on a mail channel |
| ADR-0351 §3:6, §6:2, §6:3 and §6:5 | A task's input keeps its parties; a forwarded or relayed party, and a relayed input, carry none (§3) |
| ADR-0349 §5:3, §5:5, §7:5, §7:12, §7:15 and §7:17 | Read by §9:2 and §9:3. No second sender's input joins a work under them today (§4) |
| ADR-0349 §4:6 and §4:8; ADR-0350 §4:4; ADR-0362 §3:5 | Read by §9:1. A task's work now carries its author's authority, so it is offered the stop call and may cancel or replace its author's tasks, once built |
| ADR-0350 §3:4, §3:5 and §6:4; ADR-0361 §2:5, §2:6 and §6:1 | Read by §9:5 and §3's table |
| ADR-0356 §4:4 to §4:7 | A capability still offered is still refused on its condition, and offering still grants nothing |
| ADR-0366 §9:7 and §9:8 | §8:3 filters the People section and decides nothing of its contents or shapes |
| ADR-0367 §5:5 and §10 | A ticket's call is the tapper's, whatever the work carries (§7) |

### 11. The contract changes building it would need

Named so the build is scoped, and made by none of this decision. Each is a `core` change made by
the lane the owner's planning dispatches, under this decision once merged. A new Protocol ships
as a triad.

- **The three facts:** a value for who a work is for (a person, a group or no one), for whose
  authority it carries (senders now, a person in advance, or none) and for its level, on the
  activation's state and its frozen episode, replacing `activation_person`'s owner or no one and
  the true or false `users_authority`. The level's enumeration is ADR-0366 §11's.
- **An input's level:** on `RecordedChannelTrigger` beside its author, and on each
  `RecordedInputMessage` (§2:6).
- **A task's author:** `ScheduledTask` records the person or people its author names, the level of
  the work that set it and what §6:4 needs of where it was set.
- **The check's inputs:** what ADR-0367 §16 has the authorizer read, beside the line a call rests
  on: the person or people and the level of §7, read from the work.
- **Filtering:** the capability set offered per work (§8:1), and the Connections section's and
  `search_connections`' reads filtered (§8:2). The People section's waits on ADR-0366 §9:8's
  further decision.
- **Removal:** the act ADR-0367 §16 names for removing a person ends the tasks they authored
  (§6:6), through the plan store's cancel.

### 12. What this decision leaves to others

Each is left, by ADR-0365 §6's cut or by the owner:

- **Lane 5:** where a record lands and whose it is, so where a work's records land given whom it
  is for; sharing rules; what a work for a person or for a group may read; which beliefs a person's
  assertion reaches.
- **Lane 6:** the audience mark and how it shrinks, including for a work holding one person's
  inputs from several places; which place a signal no person sent lands in.
- **Lane 7:** outside content, including how text read from a source bears on a work's level or
  authority, and sender against source.
- **A further decision:** the machinery of the grant for one call (ADR-0367 §11:5); the shapes for
  resolving mentions (ADR-0366 §9:8); a standing rule and how it covers a signal; a decision that
  lets a second sender's input join a work under ADR-0349; a place recorded as someone's of its own
  (§4:6); how a mail channel establishes a sender (§9:8).
- **The next prompt review:** whether and how a model is shown the three facts; the People
  section's contents and labels.
- **Left out by the owner:** two equal owners; sureness that fades with time; voice and who is
  present in a room ("Several people present: a sureness question, revisited when voice is
  built").

> **Normative.** This decision may not be cited to settle any matter the list above leaves to
> another.

### 13. What this decision settled where the rulings left a point open

Each is this decision's, not an owner ruling:

- **§1:3 to §1:5**: nothing changes until built; what a second person needs built; and that §4's
  rule is built before a place two admitted people can write into.
- **§2:4 to §2:6**: the facts are recorded again when an input joins, a join only narrows, and an
  input records its level beside its author. **§2:7**, that a model is shown who and whose by
  labels alone, leaving to the prompt review whether it is shown them at all.
- **§3:4's reading** of "what anyone holds on that connection" as ADR-0367 §5:2's grants to anyone,
  with their conditions. **§3:5**, that an event a connected source pushes is a signal no person
  sent, as a doorbell ring is, and is for whoever its connection belongs to. **§3:7's** "none of
  which leaves the hub" for "inside the system".
- **§4:1 and §4:2** stated for every work holding several inputs, of which the owner's two cases,
  several senders and one sender by several connections, are both instances.
- **§4:6**, that a work with several senders is for whoever its shared place belongs to, read as
  its connection's person or group until a later decision records a place as someone's.
- **§4's note** that ADR-0349's conditions stand, so no second sender's input joins a work until a
  further decision widens them.
- **§6:1's** author as ADR-0350 §3:7 records it, and a task set by a work with several senders
  carrying each of theirs; **§6:4**, that a task meets a connection condition
  where its setting work did; **§6:6**, that removal ends a task as a cancel does and how it meets
  ADR-0367 §7:11; and that a task's recorded level is not lowered after it is set.
- **§7:3**, how the check combines several senders' outcomes; **§7:4**, that a work carrying none
  holds no grant under ADR-0367 §4:2, with its three exceptions.
- **§8:1's** filtered set fixed for the work at its first round, and the meaning of "could use".
  **§8:6**, that a grant for one call appears only through filtering.
- **§9:1 to §9:5**, the readings of the earlier decisions' words for one person, kept so that today's
  reach is unchanged; **§9:6**, whose assertion is the user's; **§9:7**, whose side planning takes;
  **§9:8**, that ADR-0351 §3:3 still waits.

## Consequences

- Lane 5 can say where a record lands from whom a work is for, lane 6 can build the mark on the
  senders §2:2 records, and lane 7 can say where outside content bears on the level §2:3 records,
  each citing those clauses by number.
- A reminder or a recurring task does what the person who set it could do at the moment it runs,
  without a card on every run, and never more than they hold then.
- Removing a person ends what they set up in advance as well as what they hold.
- Once built, a work no person sent does nothing the check reaches unless a standing rule covers it.
  Events a connected source pushes, which today run on no one's authority with the policy's checks
  alone, then act only through standing rules a person set, and such rules wait on their own
  decision.
- Once built, a work whose input is a forward or relayed holds no grant and can only reply where its
  input came from, until lane 7 rules how outside content bears on authority.
- A work is shown only what its authority could use, so planning's offered set and Connections
  differ between people, and ADR-0356 §4:3's one set for every work no longer holds.
- Nothing changes in the running hub until the owner's planning dispatches the build (§1:3), and no
  second person is admitted until ADR-0367 §1:4's conditions are met.
- **Revisit** once a place two admitted people both write into is built, since §4:6's answer to whom
  such a work is for waits on whose a place is; or if a standing rule needs authority of its own
  beyond its author's.

## Alternatives considered

- **An instruction given in advance carries no authority**, as ADR-0350 §3:9 ruled. Set aside by the
  owner: every recurring task then asks on each run, which trains people to tap yes.
- **A task carries a list of the actions it may take.** Set aside by the owner ("yes record both"):
  the task records who set it and how sure the hub was, and the check reads that person's lines when
  each call is made.
- **A second sender may join a work from any place.** Set aside by the owner: "Yes, shared place
  only". A message from another person in a different place starts its own work.
- **A work with several senders carries the first sender's authority.** Set aside by the owner: it
  takes "the lower of every".
- **A person asks on another person's behalf**, and the work carries the other's authority. Set aside
  by the owner: "Asking for something on another persons behalf shouldnt be a thing".
- **Every work is offered every capability and shown every connection, and the check refuses.** Set
  aside by the owner: "yes, it should be filtered". ADR-0356 §4:3 held one set for every work so that
  each round's tools stayed the same; this keeps them the same within a work (§8:1).
- **A work with several senders is for the first of them.** Set aside here: whom it is for would then
  depend on which input arrived first (§4:6).
