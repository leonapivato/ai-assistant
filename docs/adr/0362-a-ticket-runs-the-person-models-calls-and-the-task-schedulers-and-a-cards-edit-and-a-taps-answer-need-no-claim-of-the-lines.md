# 362. A ticket runs the person model's calls and the Task Scheduler's, and a card's edit and a tap's answer need no claim of the line's

- Status: Proposed
- Date: 2026-11-01
- Scope: closing the contract gap [#3568](https://github.com/leonapivato/ai-assistant/issues/3568) left in ADR-0361, so that a ticket runs every call planning may ask about. A change the person model's calls make under a ticket is recorded naming its request (§2); a spawn's write spends a ticket in its own step, and the Task Scheduler's calls run under one (§3); a card's edit and a callback's answer are exempt from ADR-0323 §13:2's claim (§4); and the approval's input stays the hub's text until a decision of its own makes it structured (§5). The lanes (§6), what it amends (§7) and what it leaves open (§8). Milestone 19, "Approvals by card".
- Dependency: [ADR-0361](0361-approvals-are-cards-the-person-taps-and-a-yes-is-a-one-time-ticket-for-the-exact-call.md), whose gap this closes; [ADR-0338](0338-a-person-sets-their-profile-and-pins-what-aether-always-keeps-in-mind-their-style-is-learned-as-memories-and-each-reaches-the-models-for-that-persons-activations.md); [ADR-0350](0350-every-spawn-is-a-scheduled-task-written-into-the-task-scheduler-whose-sensor-starts-it-when-it-comes-due-and-the-task-manager-is-the-one-way-in-from-outside.md); [ADR-0323](0323-a-telegram-chat-with-the-owners-bot-is-a-line-to-the-assistant-and-connecting-it-approves-what-the-line-carries.md); [ADR-0306](0306-a-capability-declares-what-its-calls-do-every-call-is-checked-by-rule-and-acting-claims-and-records-what-it-does.md); [ADR-0326](0326-a-persons-memory-carries-across-every-upgrade-each-schema-change-ships-its-migration-and-a-fresh-data-directory-is-the-owners-ruling.md); [ADR-0137](0137-the-contract-seam-is-where-a-slice-is-cut.md); and [ADR-0124](0124-the-hop-is-a-third-egress-boundary-and-a-device-is-admitted-by-two-facts.md), all as their status lines leave them.
- Authorization: on 2026-11-01 the coordinator ruled, relaying the owner, to close the gap rather than keep these calls off the card: calls needing a yes go through cards, and planning raising a profile change or a pin by asking is part of the design, and the exclusion comes out before milestone 19 deploys. The same day the coordinator added §4's question, found by AP3, leaning to the exemption "if the reasoning survives review". The coordinator assigned 0362, and ratifies it under the owner's delegation once its reviews are green (§1:1).
- **Contract-surface decision, and a breaking change under golden rule 5.** It changes `core/types.py`: `PersonModelAct` gains a request form (§2:1), and a spawn's write answers a ticket's refusals (§3:1). It changes `core/protocols.py`: `PlanStore.write_scheduled_task` takes an effect claimed under a ticket (§3:1). `PROTOCOL_VERSION` advances in the lane that changes `PersonModelAct` (§2:3).
- **Partially supersedes**, in the clauses §7's first table names: ADR-0323, ADR-0338, ADR-0350 and ADR-0361.

## Context

In this document a bare section reference, such as §3:2, is to this decision's own clauses.

ADR-0361 lets planning ask about any call it is offered (§2:2–§2:3), runs a ticket's call as
the call its ticket holds (§5:4), and spends the ticket in the store step that claims that
call (§5:5). On `origin/main` at `ba50f0efe`, AP1 (#3565) and AP2 (#3566) built that, and two
kinds of call cannot run under it:

- **The person model's calls** (`set_profile`, `pin`, `unpin`, ADR-0338 §8:4). Each change is
  recorded with a `PersonModelAct`, whose `approval` is a `QuestionPart`. Nothing in it can
  name a ticket, so `PersonModelCalls` refuses the call as unapproved after the ticket is spent.
- **The Task Scheduler's calls** (`spawn`, `cancel_task`, `list_tasks`, ADR-0350 §4:1). A
  spawn's runner writes its task and claims its effect record in one step
  (`write_scheduled_task`), which refuses an effect carrying a ticket, and acting refuses a
  ticket for any runner that claims its own record. All three are also *not here* in the
  approval's own activation, whose kind ADR-0350 §3:4 does not admit and whose input carries
  no authority (ADR-0361 §6:1).

So AP2 refuses a `request_approval` naming any of the six (`_NO_TICKET_RUNS` in
`orchestration/planning.py`, "cannot be approved on a card yet").

Two more points came up. ADR-0361 §6:2 has the approval's input hold its outcome "structured",
but no structured payload exists in `core`, so AP2 states it as text with empty parties. And
AP3 found that ADR-0323 §13:2 has every call of the line, other than an activation's message,
claimed first by a durable record of the line's own (`TelegramIntakeRecord`). ADR-0361 gives a
card's edit and a callback's answer no claim kind.

## Decision

We will have a person-model change made under a ticket name its request, have the spawn's
write take and spend a ticket in its one step, run the Task Scheduler's calls under a ticket
as the person's, exempt a card's edit and a callback's answer from the line's claim, and leave
the structured approval input to a decision of its own.

### 1. Status and delivery

> **Normative.** This document remains `Proposed` until the adversarial and architecture
> reviews `CONTRIBUTING.md` → "Finishing an ADR PR" requires have returned green on one tree
> and the coordinator, under the owner's delegation, ratifies it. An assigned number or a
> green review alone does not change its status.

> **Normative.** No lane implements this decision before it merges `Accepted` (golden rule 5,
> ADR-0015 §5). Its lanes are §6's, held by milestone 19 and merged before its deploy.

### 2. The person model's calls under a ticket

> **Normative.** `PersonModelAct` gains a request form beside its question form. Made by a
> yes, an act names exactly one of `approval`, the question part a yes spent, and `request`,
> the approval request whose ticket ran the call, which is the ticket's spending key (ADR-0361
> §5:5). On the request form, `episode_id` is the approval's own episode, where the yes was
> given, whichever work ran the ticket, as ADR-0361 §5:10 places a confirmation support.

> **Normative.** `request` is left out of a dump where it is unset, so an act of every other
> form serialises byte for byte as it did. A stored act validates unchanged: the person-model
> store's upgrade is empty and its label stays, and the lane still ships the test ADR-0326
> §4:2 owes, against a file the previous release wrote.

> **Normative.** The lane that adds the request form advances `PROTOCOL_VERSION`, since the
> change log and the pins cross the wire to the panels (ADR-0124 §9, ADR-0361 §8:7).

> **Normative.** A `set_profile`, `pin` or `unpin` call run under a ticket is the request's
> person's, by that ticket. It is claimed by `claim_ticket_call` (ADR-0361 §5:5), then run
> against the person-model store: a `set_profile` and a `pin` with the request form's act.

> **Normative.** An `unpin` run under a ticket records no act, as none is recorded today: a
> removed pin keeps the act that made it and gains only when it was removed (ADR-0338 §4:1,
> §4:7). Its ticket is on its effect record, keyed by the request.

The work that ran the ticket is not on the act: the request's `spent_by` names the effect
record, which names that work, and the person-model store keeps pointers only (ADR-0338 §10:3).

### 3. The Task Scheduler's calls under a ticket

> **Normative.** `PlanStore.write_scheduled_task` takes an effect record carrying a ticket. In
> its one step it then decides the ticket as `claim_ticket_call` does (ADR-0361 §5:3–§5:5),
> its backstop counting the spawn as a call under an approval, and, where the task is written,
> marks the ticket used by that record. Its answer carries the ticket's refusals, as
> `TicketClaim` names them. Exact names and shapes are the triad's.

> **Normative.** Every other check of that step holds unchanged for a spawn under a ticket:
> the replace, the wait, and ADR-0350 §9:7's chain limit and §9:8's pending limit, decided in
> the same step (§9:9). A refusal of any of them writes nothing, so the ticket stays held. Each
> of ADR-0350 §4:5's refusals is decided at the instant the ticket runs.

> **Normative.** A spawn is the one call whose runner claims its own record that a ticket can
> hold: `request_approval` never needs the person (ADR-0361 §2:8). Acting hands a ticketed
> spawn's record to its runner's write, and refuses no ticket on that ground.

> **Normative.** A ticket's `spawn`, `cancel_task` or `list_tasks` call runs in the work
> holding the ticket's input, the approval's own activation included, though ADR-0350 §3:4
> does not admit that activation's kind: the request was written where the asking activation
> could run it (§3:6).

> **Normative.** For a call run under a ticket, the Task Scheduler's rules that read whether
> the calling activation's input carries the person's authority read it as carried, for that
> call alone: the task's author is the person (ADR-0350 §3:7, which ADR-0340 §4:1's rule
> reads), and the call may replace or cancel any of the person's tasks (§4:4). The person
> approved that exact call, the task it names included, on its card.

> **Normative.** ADR-0361 §2:2's *one planning is offered* is read as one the asking
> activation could run: a call that would come back *not here* where it was asked, such as a
> spawn from an activation ADR-0350 §3:4 does not admit, writes no request.

ADR-0350 §9:7's chain length is counted from the task's parent, the activation that ran the
ticket. Through the approval's own activation, which the Task Scheduler did not start, a chain
starts again at one, as one started by the person's message does. A tap started it, and every
step after it that needs a yes takes another tap. AP2 already reads §2:2 as §3:6 does
(`not_here`).

### 4. A card's edit and a callback's answer

> **Normative.** ADR-0323 §13:2 does not reach a card's edit or the answer to a button's
> callback. Each is sent with an attempt identifier naming the request and the step, and its
> outcome is logged by a code-owned word. No durable record of the line's own claims it.

> **Normative.** The exemption holds only while an edit carries the card's text as its post
> carried it, with only the state line code writes changed, into the message the post
> recorded in the one chat, and a callback's answer carries a fixed text of code's. An edit or
> an answer that would carry more is claimed as ADR-0323 §13:2 decides.

> **Normative.** A card's post is the asking activation's message (ADR-0361 §4:3), so §13:2's
> exemption for an activation's message covers it. Its claim is `request_approval`'s effect
> record, written with the request before the post (ADR-0361 §2:9), and a crash before its
> outcome leaves that record with none, never resolved by guessing (ADR-0306 §5:6).

> **Normative.** In place of the claimed record ADR-0323 §11:3 and §11:4 require before the
> call and before the token is read, each of the two is gated by a plan-store check made before
> the token is read. An edit goes ahead only where the request holds that card at that chat and
> position, as `record_approval_card` recorded it. An answer goes ahead only where the update
> comes from the request's person and its token resolves to a request. The connection record is
> read before the check and again before any byte is sent, and the chat check is unchanged.

> **Normative.** ADR-0017 §3's path for an attempt a crash leaves pending is the request record:
> after a start, the hub re-edits each card on the line to its request's state. A lost answer
> needs none: it is fixed text, and the tap it answers is decided in the plan store (ADR-0361
> §4:9).

ADR-0017 §3's attempt-and-outcome condition exists because, without it, a timeout cannot be told
from a disclosure. An edit or an answer discloses nothing the claimed post did not already send
to the same chat. So a lost outcome costs only the card's display, and a repeat is harmless: an
edit sets the state it shows, and a callback's answer is fixed text. Neither is an act of any
activation (ADR-0361 §4:5). This is AP3's interim, which this decision rules. It needs no lane
of its own.

### 5. The approval's input stays the hub's text, for now

> **Normative.** Until a decision of its own makes it structured, the approval's input is the
> hub's text, stated from the record, naming the outcome and the request, with empty parties
> (ADR-0361 §6:1). The ticket's label is shown where planning is shown the tickets it holds.
> ADR-0361 §6:2's *structured* waits on that decision, and the rest of §6:2 holds.

A structured payload costs far more than §§2–3. It is a new form in `ChannelPayload` and
`RecordedChannelPayload`, and a `Modality` member, both stored and both carried on the wire.
It also changes the episode encoding in `core`, every reader of a recorded input, understanding's
and planning's renderings among them, and the episode store, whose upgrade and test it owes.
Code already holds what the structure would give it: the request's `pushed_to` names the
activation each outcome was pushed to (ADR-0361 §3:4). Nothing in milestone 19 waits on it.

### 6. Delivery

The lanes, each after this decision merges `Accepted`, held by milestone 19 and merged before
its deploy:

1. **AP6, the contract lane, with its primary implementations** (ADR-0137 §2:1): §2:1's request
   form and §3:1's ticket in the spawn's write, in `core`; the conformance suites; the
   canonical fakes of `PersonModelStore` and `PlanStore`; the person-model store with §2:2's
   test; both plan stores in `planning/`; and `PROTOCOL_VERSION` (§2:3).
2. **AP7, the consumer lane,** in `orchestration/`: removing AP2's exclusion and acting's
   refusal of a ticketed spawn (§3:3); the person model's calls under a ticket (§2:4–§2:5); the
   Task Scheduler's calls under a ticket (§3:4–§3:5); and the tests and prompt cases below.

> **Normative.** AP6 may touch `core`, `testing`, `memory/person_model_store.py`, `planning`
> and their tests, permitted expressly here as one unit: its two changes are one seam, a
> ticket's call, cut at the two stores that record it. AP7 may touch `orchestration` and its
> tests, the prompt cases included.

> **Normative.** AP6 merges before AP7, and AP7 is briefed only after AP6 has merged
> (ADR-0137 §4:1).

> **Normative.** The tests include: a `set_profile` and a `pin` each run under a ticket, whose
> act names the request and the approval's episode; an `unpin` run under a ticket, which
> removes the pin and leaves the act that made it unchanged; a stored act of each earlier
> form read back unchanged; a spawn under a ticket that writes its task and spends the ticket
> in one step; a second run of that ticket refused; a spawn under a used, void or expired
> ticket writing nothing; a spawn under a ticket refused by the pending limit, leaving the
> ticket held; a ticketed spawn run in the approval's own activation and after a take, its
> author the person; a ticketed replace and cancel of a task the running work did not spawn;
> and a request for a call the asking activation cannot run, writing nothing.

> **Normative.** AP7 adds synthetic prompt cases (ADR-0337 §3) for at least a profile change
> and a pin asked by `request_approval` and run by `run_approved`.

### 7. Relationship to earlier decisions

Superseded in part. Every clause the middle column does not name stands:

| Earlier decision | What it replaces | By |
| --- | --- | --- |
| ADR-0323 | §11:3 and §11:4, each in the addition alone: a card's edit and a callback's answer are gated by a plan-store check in place of a claimed record; §13:2, in the addition alone: a card's edit and a callback's answer are exempt; §13's table, rows 6 and 12, in the addition alone: an edit is bound to the request and logged by its attempt identifier | §4 |
| ADR-0338 | §3:5's and §4:1's *by a yes, naming the approval and its episode*, in the addition alone: a yes on a card names its request, and the episode is the approval's own; §8:5's *Under a yes the call runs as ADR-0321 §4 decides*, in the addition alone: or under a ticket, as ADR-0361 §5:4 decides | §2 |
| ADR-0350 | §3:3, in the addition alone: the write may spend a ticket; §3:4, in the addition alone: a ticket's call runs in the work holding its input; §3:7 and §4:4, in the addition alone: under a ticket, the input's authority is read as carried | §3 |
| ADR-0361 | §2:2's *one planning is offered*: one the asking activation could run; §6:2's *structured*, until a later decision: the hub's text; §8:1 and §8:2, in the addition alone: `PersonModelAct`'s request form and the spawn's write under a ticket; §9, in the addition alone: AP6 and AP7 | §2, §3, §5, §6 |

Read through and not superseded:

| Earlier decision | What changes |
| --- | --- |
| ADR-0361 §5:5 | Nothing: for a spawn, the step that claims its call is the spawn's write |
| ADR-0350 §3:9 | Nothing: a task carries no authority, and no approval carries over to its activation |
| ADR-0330 §9's row 12 | Nothing: it defers to ADR-0323 §13, so §4 holds on the relayed route too |
| ADR-0326 §4 | Nothing: §2:2's upgrade is the empty one its note names, and the test is owed |

> **Normative.** This numbered draft records its replacements on the status lines and in a
> dated header note of ADR-0323, ADR-0338, ADR-0350 and ADR-0361, atomically with this ADR
> under ADR-0070 and ADR-0082, preserving their ratified bodies. The replacements take effect
> on this ADR's ratification.

### 8. What this decision does not decide

| Not decided here | Where it goes |
| --- | --- |
| The approval's input as a structured payload (§5) | A later decision ([#3570](https://github.com/leonapivato/ai-assistant/issues/3570)) |

> **Normative.** The item the table names takes a decision of its own before any lane builds
> it.

## Consequences

- Every call planning may ask about runs under a ticket, and AP2's *cannot be approved on a
  card yet* goes.
- A profile change or a pin made on a card is logged as the person's, naming the request.
- A tapped spawn is the person's task, and may hold a rule or replace any of their tasks, as
  one they asked for in the chat may.
- Edits and callback answers keep no durable record. A crash mid-edit leaves a card showing
  an older state.
- The approval's input stays text, and making it structured remains owed.

## Alternatives considered

- **Keep these calls off the card.** Rejected by the owner's ruling, relayed by the
  coordinator.
- **A new `PlanStore` member for a spawn under a ticket.** Rejected: it would repeat the
  spawn's write, with its replace, wait and limits, as a second member to keep in step.
- **The work that ran the ticket on the act**, as a confirmation support names it. Rejected:
  `spent_by` already reaches it, and the person-model store keeps pointers only.
- **Claim kinds on `TelegramIntakeRecord` for an edit and an answer.** Rejected: a record and a
  store change, to track a call that discloses nothing new.
- **The structured payload now.** Split out (§5): its cost is several times that of §§2–3.
