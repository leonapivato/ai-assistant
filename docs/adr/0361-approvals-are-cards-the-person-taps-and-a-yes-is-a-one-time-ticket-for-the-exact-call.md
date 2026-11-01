# 361. Approvals are cards the person taps, and a yes is a one-time ticket for the exact call

- Status: Proposed
- Date: 2026-10-31
- Scope: how the assistant asks for a yes and how a yes becomes permission, replacing the conversational yes ADR-0353 §11 stopped. Planning asks by `request_approval` (§2) into a built-in **Approvals** channel (§3); the person answers by tapping a card in the line's chat or on the hub page (§4); a yes gives a one-time ticket that planning runs by `run_approved` (§5); the approval arrives as an ordinary activation tied to the work that asked, and joins it where it still runs (§6), from any place (§7). The code it binds (§8), the lanes (§9), what it leaves open (§10) and what it retires (§11). Milestone 19, "Approvals by card", which the coordinator opens once this merges.
- Dependency: [ADR-0292](0292-a-channel-is-the-spokes-facing-one-thing-and-the-assistants-edge-is-its-own.md), [ADR-0306](0306-a-capability-declares-what-its-calls-do-every-call-is-checked-by-rule-and-acting-claims-and-records-what-it-does.md), [ADR-0321](0321-authority-at-the-deploy-is-your-yes-to-a-question-that-showed-the-call.md), [ADR-0323](0323-a-telegram-chat-with-the-owners-bot-is-a-line-to-the-assistant-and-connecting-it-approves-what-the-line-carries.md), [ADR-0349](0349-a-place-is-only-what-caused-an-activation-a-stop-is-reached-three-ways-running-work-is-shared-by-reading-it-and-the-newest-absorbs-what-it-continues.md), [ADR-0350](0350-every-spawn-is-a-scheduled-task-written-into-the-task-scheduler-whose-sensor-starts-it-when-it-comes-due-and-the-task-manager-is-the-one-way-in-from-outside.md), whose Task Scheduler is this channel's precedent, [ADR-0351](0351-an-input-carries-the-parties-whose-words-it-is-and-outside-content-authority-and-a-supports-holder-follow-from-them.md), [ADR-0353](0353-understanding-reads-its-stimulus-as-tagged-knowledge-then-memory-and-replies-with-what-it-understood-what-it-cites-what-is-unclear-and-where-it-belongs.md), [ADR-0356](0356-the-system-briefs-planning-in-one-continuing-exchange-plannings-text-is-its-notes-and-an-episode-is-shown-by-its-short-view.md) and [ADR-0357](0357-messages-are-tools-by-modality-planning-chooses-and-tools-carry-out-and-a-rule-about-one-tool-sits-in-its-description.md), all Accepted, as their status lines leave them.
- Authorization: the owner ruled the design point by point in chat with the coordinator on 2026-10-31. Their words, verbatim: on asking, "what if instead of holding and labelling anything, it has to call ask(email(same args...) ...)"; on the surface, "some other interface surface only for approvals? Similar to a 2FA push notification", then "yes go with that"; on the Telegram surface, "I dont like have 2 bots"; on joining, "do the wide stance now, let it join from wherever, and when the audience walk happens, it can narrow later"; and on the milestone, "the rest is good". The owner also chose the names `request_approval` and `run_approved`, that a yes runs nothing by itself but grants a ticket, who may use it and when it is void, and the 24 hours (§3:5). The coordinator assigned 0361, and ratifies it under the owner's delegation once its reviews are green (§1:1). What the rulings leave open and this decision settles is named where it is settled.
- **Contract-surface decision, and a breaking change under golden rule 5.** It changes `core/types.py`: an approval request and its enumerations are added, `ApprovalGiver`, `Approval` and `ApprovalEnd` gain a member or a form each, `ActivationEffect`'s spending key names a request, `UserConfirmation` names the request it answers, and the question path's types leave (§8:1, §8:5). It changes `core/protocols.py`: `PlanStore` gains the requests (§8:2), `TelegramBotClient` the card and the tap (§8:3), and `AssistantEngine` the panel's query and command (§8:4). `core`'s register of channel types gains Approvals (§3:6). `PROTOCOL_VERSION` advances in each lane that changes a type the wire carries (§8:6).
- **Partially supersedes**, in the clauses §11's first table names: ADR-0177, ADR-0292, ADR-0306, ADR-0321, ADR-0322, ADR-0323, ADR-0349, ADR-0350, ADR-0351, ADR-0353, ADR-0356 and ADR-0357.

## Context

In this document a bare section reference, such as §5:2, is to this decision's own clauses.

ADR-0321 let a call that needs the person run on their yes in chat: the question showed the
call on an exact line, understanding recorded a pointer from the reply to the question, and
authorizing checked three facts before the call ran in the reply's activation. ADR-0353 §11
stopped that: understanding records no pointer, so no yes approves anything, and every call
that needs the person goes back to planning as needing them. ADR-0357 §8 carried the asking
half across to message calls, as `asks` on `text`, and left the redesign to this decision
(ADR-0357 §12, ADR-0356 §15).

The owner's redesign takes approval out of conversation. Planning asks with one call that
holds the call to approve; code shows it to the person on a card; the person taps Approve or
Deny; the answer arrives as an activation; and a yes grants a ticket that runs the exact call
once. Telling a yes from words is gone, and with it #3547's class of bug. What is asked is what
runs, by construction.

On `origin/main` at `7d4243fab`: `ChannelKind.approval_giver` (`orchestration/channel_kinds.py`)
names who a yes on a kind's places is, and the line and the hub chat each have an
`ApprovalGiver` member. `LabelKind.APPROVED_ACTION` (`A`) is the label ADR-0321 §4:2 shows an
approved action under. The Task Scheduler (`orchestration/task_scheduler.py`) is a built-in
channel with one place, a sensor in the hub and its content in the plan store. An offer
(ADR-0349 §7:17) is made only within one place, because an ordinary activation's message goes
only into the place its input came from: `via` names a place on the place list (ADR-0357
§2:4), and that list holds no other place for such an activation (ADR-0350 §5:11, ADR-0356
§7:7).

## Decision

We will have planning ask for a yes with `request_approval(call, why)`, written as a request
into a built-in Approvals channel and shown on a card in the line's chat and on the hub page;
take the person's tap as a command; start an ordinary activation when a request is answered or
expires, tied by code to the work that asked and joining it where it still runs, from any
place; and have a yes grant a ticket for the exact call, which planning runs once with
`run_approved(label)` or lets lapse.

### 1. Status, scope and delivery

> **Normative.** This document remains `Proposed` until the adversarial and architecture
> reviews `CONTRIBUTING.md` → "Finishing an ADR PR" requires have returned green on one tree
> and the coordinator, under the owner's delegation, ratifies it. An assigned number or a
> green review alone does not change its status.

> **Normative.** No lane implements this decision before it merges `Accepted` (golden rule 5,
> ADR-0015 §5).

> **Normative.** The implementation is the lanes §9 sets out, held by milestone 19.

### 2. Asking

> **Normative.** Planning asks for the person's yes by calling `request_approval`, whose two
> arguments, both required, are `call`, the call to approve as a capability name and its exact
> arguments, and `why`, planning's explanation in its own words.

> **Normative.** Code checks `call` before anything is written: its capability is one planning
> is offered, and its arguments validate against that capability's parameters schema. A call
> that fails comes back *not done*, saying why, and writes nothing (ADR-0357 §6:1).

> **Normative.** The nested call is then ruled as every call is (ADR-0306 §4:1). Where the
> policy denies it, no request is written, and the result says it is not allowed and is not to
> be asked about (ADR-0321 §2:10's second case). Otherwise the request is written, whether or
> not the ruling says it needs the person: planning may narrow what runs freely, never widen it.

> **Normative.** What needs a yes stays the authorizer's (ADR-0306 §4). A direct call ruled to
> need the person runs nothing and comes back saying that it needs the person's yes and is to be
> called through `request_approval` with the same arguments.

> **Normative.** Any activation that is a person's may call `request_approval`, whatever caused
> it. In an activation that is no person's, the call comes back refused (ADR-0356 §4:4).

> **Normative.** A request records: the person it is for, who is the person the asking
> activation is for; the asking activation; the call, as its capability, the values it sends,
> the binding computed for it and its deliberate-repeat mark, as ADR-0321 §2:8 recorded a
> question's call; `why`; when it was written; and when it expires (§3:5).

> **Normative.** `request_approval` is done once the request is written. Its result says that
> the card was sent, each surface it went to and how it went there, and that it waits on the
> person. It holds up no round and waits for no answer.

> **Normative.** A `request_approval` whose call has the same capability, values and binding as
> a pending request for the same person writes nothing and comes back saying that it is already
> waiting, and since when.

> **Normative.** `request_approval` is declared not safe to repeat, and is claimed and recorded
> under ADR-0306 §5 with an effect record naming its request. It is ruled by its nested call
> alone (§2:3): it never needs the person itself, and the outside-content stand-in never
> applies to it.

> **Normative.** The rules for asking are said in `request_approval`'s description (ADR-0357
> §7:1): some actions need the person's yes; ask for one with this call, explaining in `why`
> what it does and the arguments that matter; the person answers on a card, and a yes written
> in a conversation approves nothing; a yes grants a ticket that `run_approved` runs once; the
> assistant never approves on anyone's behalf; and there is no other route. Its exact words are
> the lane's that builds it, as the coordinator routes them from the owner's prompts front.

> **Normative.** A card shows: ADR-0321 §2:5's exact line for the call, written by its one
> generic renderer; `why`; where the asking work came from, its channel and place; a line
> saying so where the asking work has read outside content (ADR-0306 §4:5); when it expires;
> and its state.

### 3. The Approvals channel

> **Normative.** **Approvals** is a built-in channel (ADR-0292 §2:5–§2:6) with exactly one
> place, **the approvals**. It is a medium the hub hosts, in ADR-0292 §1's sense, which the
> assistant reaches only through its sensor and its actuator, and ADR-0292 §3's clauses on a
> hosted medium bind it, as ADR-0350 §2:3 has them bind the Task Scheduler.

> **Normative.** It holds only approval requests, each with its ticket (§5). It is fully
> private: its kind takes no spoke on any device, no device is an end of its place, and a
> person reaches it only by §4's commands and query.

> **Normative.** Its actuator is `request_approval`'s write of a request into the plan store,
> run directly as ADR-0350 §4:3 runs a spawn.

> **Normative.** Its sensor is one loop that the engine starts and stops with the hub, as
> ADR-0350 §7:1's is. It wakes on every write to a request and at the earliest expiry, sleeping
> no longer than ADR-0350 §12:5's recheck interval, and pushes each request answered or expired
> as an input of its own, first marking it pushed, naming the activation it will be admitted
> under, in one plan-store step that refuses where it is already marked (ADR-0350 §7:5).

> **Normative.** A request not answered within **24 hours** of being written ends *expired*,
> and its ticket, where it has one, expires at the same instant. The 24 hours are a constant of
> the composition root (`app/`), not a setting.

> **Normative.** Its kind is declared in code as the Task Scheduler's is (ADR-0350 §2:6): its
> place runs activations side by side, takes no message from a person or from the assistant,
> shows no running work and expects no reply; it pushes and cannot be pulled; it has no window
> and no approval giver; and its audience is private. `core`'s register of channel types gains
> it, establishing no author as the user and declaring its inputs' parties empty (ADR-0351
> §2:4, §3:1).

> **Normative.** A request answered or expired starts one activation, though the assistant
> wrote the request. An outcome marked pushed whose activation was never admitted is pushed
> again after a restart, and one that ended *expired* while the hub was down is pushed at start.

### 4. The surfaces, and the tap

> **Normative.** A surface is a client of the one approvals store, not a place. There are two:
> a card in the line's chat, and a panel on the hub page.

> **Normative.** Where the line is connected, `request_approval` has the line's writer post the
> card, in the same call, into the line's chat as the assistant's own message, with an Approve
> and a Deny button, whatever place the asking work's input came from. There is one bot.

> **Normative.** The card posted is recorded as the asking activation's message: its call entry
> holds what was sent, where and how, as a message call's does (ADR-0356 §8:4), so the line's
> window shows it (ADR-0323 §10).

> **Normative.** A card whose text would be longer than one Telegram message is posted with no
> buttons, saying that the request is answered on the hub page, where the panel shows it whole.

> **Normative.** The hub edits each card in place to show its request's state: approved,
> denied, expired, and after a yes, used or not used. An edit is the hub's own, no message and
> no act of any activation, and an edit that fails changes nothing in the store.

> **Normative.** The panel reads the store by a query, showing the person's pending requests,
> each as its card shows it, and the ones answered most recently with their state, and takes
> taps on Approve and Deny.

> **Normative.** A tap is a command (ADR-0292 §4:3), told apart by structure: on the line a
> button's callback, on the hub page the panel's call. It is never perceived: it starts no
> activation, joins none, and no model reads it.

> **Normative.** A tap is carried out only where it comes from the request's person, established
> as its surface establishes them: on the line by ADR-0323 §4:1's test, as ADR-0332 §8:1 applies
> it to `/stop`; on the hub page, from a device admitted under ADR-0124. A tap from anyone else
> changes nothing, and on the line it is dealt with as ADR-0323 §5:2 deals with an update from
> another account.

> **Normative.** A tap marks a pending request approved or denied, with who answered, as the
> `ApprovalGiver` of its surface, and when, in one plan-store step that refuses where the
> request is no longer pending. The first tap to land wins, and a later one is answered with
> the request's state.

> **Normative.** A button's callback data is an opaque token minted for the card, which names no
> record (ADR-0323 §12:4).

> **Normative.** No input approves anything, whatever it says. A yes written in a conversation,
> on the line or anywhere else, approves nothing, and nothing spoken approves.

> **Normative.** The line's calls ADR-0323 §12:1's approval covers also include posting a
> card, editing it and answering a button's callback, for the one chat the settings name. In
> relayed mode the relay serves them as it serves the line's other calls (ADR-0330 §4:16).

### 5. The ticket

> **Normative.** A yes runs nothing. The approval's input carries a **ticket**: the request's
> exact call, for the request's person, usable once, shown to planning under an approved-action
> label (ADR-0321 §4:2).

> **Normative.** Planning runs a ticket with `run_approved`, whose one argument is the ticket's
> label. Code fills in the values and the binding recorded with the request, rebinding as
> ADR-0321 §4:2 does, and nothing else planning sends changes them.

> **Normative.** `run_approved` is refused, *not done*, saying why, and runs nothing, unless its
> label names a ticket this round was shown, the request was approved by its person, the
> activation calling holds the approval's input (§5:6), the ticket is unused, and it has not
> expired. These checks replace ADR-0321 §4:4's three facts.

> **Normative.** A call that passes is checked, claimed and recorded as the call its ticket
> holds, under that capability's declaration, and names the ticket. ADR-0321 §4:3, §4:7, §4:8,
> §4:10, §4:11, §4:13, §4:15–§4:17, §5 and §6 hold for it as §11 leaves them, with the ticket
> read for the yes and its approval.

> **Normative.** A ticket is spent in the plan-store step that claims its call, keyed by its
> request, and that step refuses it, writing nothing, where a record already carries the key.

> **Normative.** Only the work holding the approval's input can use its ticket: the approval's
> own activation, or the work that input joined by a take (§6:4). The ticket moves with the
> input.

> **Normative.** A ticket is void once the work holding its input ends without running it,
> however that work ends, and once it expires. Running the call after that takes a new request.

> **Normative.** Planning may decline to run a ticket, such as where the situation has changed
> or too long has passed, and may ask again with a new request. Declining is no call: planning
> says why in its notes, and the ticket is void when the work ends.

> **Normative.** A deny grants no ticket, and its input says that the request was denied. An
> expiry grants none, and its input says that the request expired.

### 6. The approval's activation, and its link

> **Normative.** The approval's input's author is the request's person, stated by the hub from
> the record, and its kind establishes no author as the user, so it carries no authority
> (ADR-0292 §5:5, ADR-0351 §6:1). Its parties are empty: it carries no one's words (ADR-0351
> §2:4). Its activation is for the request's person.

> **Normative.** The input holds the outcome, the request as its card shows it, and the
> ticket's label where there is a ticket. It brings with it, as context that is not the input
> (ADR-0351 §2:10), the asking activation: by its episode label and its short view (ADR-0356
> §9) where its episode has frozen, and as running work (ADR-0349 §5:6) where it has not.

> **Normative.** Code records the approval's input as meant for the asking activation, in
> `continues`, and links it to each matter the asking activation is linked to. Understanding
> still reads the input, and what it names in `meant_for` and `belongs_to` for it is not read.

> **Normative.** Where the asking activation, followed forward as ADR-0349 §7:4 follows one, is
> running with its stop mark unset, the takeover step offers it the approval's input under
> ADR-0349 §7:17, whose third condition is not read for this input: its link is code's, and it
> carries no words and no authority. The asking work has acted, since its request was a write.

> **Normative.** Where no offer is made, or one is declined, the approval's own activation
> plans with its input, after any wait ADR-0349 §7:25 sets. Several approvals for one work are
> each offered on their own, under ADR-0349 §7:22's limit.

> **Normative.** An input whose parties are empty is left out of ADR-0351 §8:5's reading of an
> activation's inputs: it neither makes the activation outside nor takes away its authority.

> **Normative.** The approval's activation's place list (ADR-0350 §5:10) holds the line's chat,
> where the line is connected, and the asking work's places, marked suggested: the place its
> input came from where that place takes a message, or, for an activation the Task Scheduler
> started, its task's suggested places. It writes messages into places on that list alone, as
> ADR-0350 §6:7 has a task's activation do.

So nothing about the link rests on the short-term window. A yes to work still running reaches
it as an offer, which its planning takes as ADR-0349 §7:19–§7:21 decide and then runs the
ticket. A yes after the work ended starts its own activation, which sees which episode asked
and why.

### 7. Joining from any place

> **Normative.** An offer is made to running work an input is meant for from any place, within
> one person. ADR-0349 §7:17's *where both were caused by the same place* is lifted, and
> ADR-0349 §7:18 retires.

> **Normative.** After an activation has committed, ADR-0349 §7:12's wait before it acts reaches
> every place, as it does before it commits, since an offer can now come from any of them.

> **Normative.** The place an input taken by a take came from is on the taking activation's
> place list, under its `L` label, where its kind takes a message, and a `text` call may name it
> by `via` (ADR-0357 §2:4).

> **Normative.** No audience check is added for a join from another place, for a message into a
> taken input's place, or for a card. Every place today reaches only the owner, and the audience
> design narrows each of them when it lands ([#2590](https://github.com/leonapivato/ai-assistant/issues/2590)).

ADR-0349 §7:18 gave one reason, that the older's message went only into its own place, and
§7:3 answers it. The other two the coordinator noted are left: understanding of the offered
input read the other place's window, which is minor, and audience, which waits for the audience
walk. Absorbing (ADR-0349 §7:5) already reaches any place and needs no widening.

### 8. The code it binds

> **Normative.** `core/types.py` gains a frozen pydantic model for an approval request, holding
> §2:6's parts, its answer and where its cards went, and closed `StrEnum`s, added to and never
> renamed, for its state (pending, approved, denied, expired) and its ticket's (held, used,
> void). `ApprovalGiver` gains a member for each surface's tap; `Approval` gains a form for a
> tap on a card, covering one request; `ApprovalEnd` gains expiry; `ActivationEffect`'s spending
> key names a request; and `UserConfirmation` names the request it answers. Exact names and
> shapes are the triad's (§9), extending ADR-0321 §4:6's shape rather than replacing it.

> **Normative.** `PlanStore` gains members to: write a request with `request_approval`'s effect
> claim and §2:8's check in one step; read requests by id, and by person and state; record a
> request's cards and their tokens; mark a request answered (§4:9) or expired (§3:5); read the
> outcomes due to be pushed and mark one pushed (§3:4); mark a ticket void (§5:7); and claim a
> call under a ticket (§5:5). `PlanExport` gains the requests, its `schema_version` advances,
> `PlanStore.clear` erases them (ADR-0292 §3:11), and the lane ships the upgrade (ADR-0326 §4:1).

> **Normative.** `TelegramBotClient` gains sending a message with buttons, editing a message and
> answering a button's callback, and `TelegramUpdate` gains a button's callback, all on the
> line's one route (ADR-0323 §11:1).

> **Normative.** `AssistantEngine` gains the panel's query and its tap command, and ADR-0177
> §1:1's enumeration gains both.

> **Normative.** What only the conversational question used leaves: `text`'s `asks` and the
> exact lines a message carries (ADR-0357 §8); a round's asked calls and the types only they
> use, `YesToQuestion`, `QuestionPart` and `AnsweredQuestion` among them, with any upgrade
> ADR-0326 requires; and the question marks the windows still carry (#3495, #3547).

> **Normative.** Each lane whose change alters a type the wire carries advances
> `PROTOCOL_VERSION` in that change (ADR-0124 §9).

### 9. Delivery

The lanes, each after this decision merges `Accepted`, held by milestone 19, which is built
after milestone 18's deploy:

1. **AP1, the `PlanStore` triad with its primary implementation** (ADR-0137 §2:1): §8:1's
   types, §8:2's members, the register entry (§3:6), the conformance suite, the canonical fake,
   and the SQLite plan store in `planning/` with its upgrade.
2. **AP2, the tools and the sensor, with the join,** in `orchestration/` and `app/`: the kind
   (§3:6), `request_approval` and `run_approved` (§2, §5), the outcome that sends a direct call
   to `request_approval` (§2:4), the sensor (§3:4–§3:7), the approval's activation and its link
   (§6), the join and the place lists (§7), and the expiry constant and the wiring in `app/`.
3. **AP3, the card and the tap on the line:** §8:3's members as a triad with their
   implementation in `tools/egress.py`, and in `orchestration/telegram.py` the card's post, its
   edits (§4:2–§4:5) and the callback as a command (§4:7–§4:10).
4. **AP4, the panel:** §8:4's members, the wire operations, the gateway's routes and the hub
   page's panel (§4:6).
5. **AP5, the retirements:** §8:5's removals, and the code of each clause §11 retires.

> **Normative.** AP1 may touch `core`, `testing`, `planning` and their tests, permitted
> expressly here as one unit. AP3 may touch `core`, `testing`, `tools`, `orchestration/telegram.py`
> and their tests, and AP4 `core`, `testing`, `orchestration`, `wire`, `interfaces` and their
> tests, each permitted expressly here as one unit.

> **Normative.** AP1 merges before AP2, and AP2 before AP3, AP4 and AP5, which merge in any
> order. Each is briefed only after the lanes it follows have merged (ADR-0137 §4:1).

> **Normative.** The tests include: a direct call needing a yes that runs nothing and names
> `request_approval`; a nested call whose arguments fail its schema, and one the policy denies,
> each writing no request; a second identical pending request refused; two taps racing, where
> the first wins; a tap from another account changing nothing; a yes to running work offered and
> taken across places, whose ticket then runs once; a yes after the work ended, whose activation
> names the asking episode; a second `run_approved` of one ticket refused; a ticket refused after
> expiry, from other work and after its holder ended; a deny and an expiry, each granting no
> ticket; a restart between the pushed mark and admission; and a card too long for one message.

> **Normative.** AP2 adds synthetic prompt cases (ADR-0337 §3) for at least: an email that needs
> a yes, asked by `request_approval` and never by a question in words; "yes" typed after a card,
> which runs nothing; and a ticket held after the situation changed, which planning declines and
> asks again.

### 10. What this decision does not decide

| Not decided here | Where it goes |
| --- | --- |
| Other commands on the bot: buttons, and slash commands Telegram flags as `bot_command` | A later decision |
| More surfaces: phone push, desktop, a watch | A later decision; each is a client of the store (§4:1) |
| Routing a request to another approver, such as a parent for a household member | The household design ([#691](https://github.com/leonapivato/ai-assistant/issues/691)) |
| The audience of a cross-place join, of a taken input's place and of a card | The audience design (#2590) |
| Several calls in one request, and a ticket handed to work that runs later | A later decision, on evidence |

> **Normative.** Each item the table names takes a decision of its own before any lane builds
> it.

### 11. Relationship to earlier decisions

Superseded in part. Every clause the middle column does not name stands:

| Earlier decision | What it replaces | By |
| --- | --- | --- |
| ADR-0177 | §1:1's enumeration, in the addition alone: the panel's query and its tap command | §8:4 |
| ADR-0292 | §6:8, in the addition alone: a request answered or expired starts an activation, though the assistant wrote it | §3:7 |
| ADR-0306 | §4:7's *the place the input came from*, in the addition alone: or a place an input taken by a take came from | §7:3 |
| ADR-0321 | §2:2's *in a message you could see*: on a card; §2:3, §2:6, §2:8 and §2:12, whole; §2:4's and §2:9's instruction lines: `request_approval`'s description; §2:5's *appends to the message*: the card shows it; §2:10's first case, and its third whole; §3, whole; §4:1: the work holding the input; §4:4–§4:5: §5:3's checks; §4:6, in the addition alone: a tap's form; §4:9's key: the request; §4:12: a pending request; §4:14's pointer and delivery; §5:1's *asks about it*: by `request_approval`; §5:4's *stays answerable*: until it expires; §7:3 and §7:4, whole; §9:1's rows for the question path | §2, §4, §5, §8 |
| ADR-0322 | §3 and §4:3, whole: no question is marked or approved | §4:11, §8:5 |
| ADR-0323 | §4:7 and §4:8, whole; §4:9, in the addition alone: each surface's tap; §6:1's *the chat is the input's place*, for a card: any activation's card goes to the chat; §7:1 and §7:2, whole; §12:2, in the addition alone: the card, its edits and a callback's answer | §4 |
| ADR-0349 | §6:12's *an approval is used only by its yes's activation*: by the work holding its input; §7:12's *After it has committed*, in its own place alone: every place; §7:17's *where both were caused by the same place*, and its third condition for an approval's input; §7:18, whole | §5:6, §6:4, §7:1–§7:2 |
| ADR-0350 | §5:11, in the addition alone: an approval's activation's list, and a taken input's place on any list; §6:7, in the addition alone: an approval's activation speaks as a task's does; §6:8's *planning in every other activation still chooses no place*, in the addition alone: a taken input's place | §6:7, §7:3 |
| ADR-0351 | §3:1's table, in the addition alone: Approvals' row, empty parties; §8:5's reading over all inputs, in the addition alone: an input with empty parties is left out | §3:6, §6:1, §6:6 |
| ADR-0353 | §9:4 and §10:4, each in the addition alone: an approval's input's `continues` and matters are code's; §9:9's *`AnsweredQuestion` stays*; §11:3, whole; §11:4's second sentence | §6:3, §5, §8:5 |
| ADR-0356 | §7:7, in the addition alone: a taken input's place, and an approval's activation's list; §7:10, in the addition alone: §7:3 widens where a message may go | §6:7, §7:3 |
| ADR-0357 | §2:2's `asks`; §2:11's *the person's yes to that exact call*: a ticket for it; §3:1's *with the exact lines (§8:2)*; §4:4, whole; §7:2's last row: `request_approval`'s description; §8, whole | §2:10, §5, §8:5 |

Read through and not superseded:

| Earlier decision | What changes |
| --- | --- |
| ADR-0292 §4:3, §12:5 | Nothing: a tap is a structured act naming one operation, never perceived, as the line's `/stop` is (ADR-0332 §8) |
| ADR-0292 §13's `answer` row | Nothing: a tap answers no question; ordinary questions are still replies in the place |
| ADR-0306 §4:8 | Nothing: a call needing the person still runs nothing, and nothing resumes it; a ticket is a new call |
| ADR-0321 §2:7, §4:2, §4:3, §4:11 | Nothing: the exact line's test, the label, the fresh ruling, and a yes overriding every confirm but never a deny, all hold for a ticket |
| ADR-0349 §7:5 | Nothing: absorbing already reaches any place |
| ADR-0349 §7:19–§7:24 | Nothing: an approval's input is offered, shown, taken and declined as any offer is |
| ADR-0350 §2, §7 | Nothing: the Task Scheduler is the precedent this channel follows |
| ADR-0356 §15 | Nothing: its approvals row is this decision; approved actions render in the input that holds the ticket |

> **Normative.** This numbered draft records its replacements on the status lines and in a dated
> header note of ADR-0177, ADR-0292, ADR-0306, ADR-0321, ADR-0322, ADR-0323, ADR-0349, ADR-0350,
> ADR-0351, ADR-0353, ADR-0356 and ADR-0357, atomically with this ADR under ADR-0070 and
> ADR-0082, preserving their ratified bodies. The replacements take effect on this ADR's
> ratification.

## Consequences

- Approvals work again, and nothing in them turns on reading a reply: the person's tap is the
  only yes, and the ticket is the only thing it grants.
- What runs is exactly what the card showed, once, and only in the work that holds it. A
  stale yes lapses rather than running late.
- The hub sends to the line on its own initiative for the first time, as a card any activation
  of the person's may cause. Approving needs Telegram or the hub page; without the line, a
  request waits on the panel alone.
- Work running in one place can now take in input from another and answer there. Audience is
  not checked for it, which is safe only while every place reaches the owner alone.
- A ticket voided by a restart, or by work ending first, costs the person a second tap.

## Alternatives considered

- **A yes runs the call at once.** Rejected by the owner: a yes given late would run on a
  situation that has changed. The ticket lets planning judge it first.
- **A plain chat yes, checked by code** (the very next message, a bare yes, within a time).
  Rejected: it keeps a model's reading of words in the path, and a tap is simpler and safer.
- **A separate control bot for cards.** Rejected by the owner: "I dont like have 2 bots".
- **Held calls with labels and an approve call.** Rejected for the owner's `ask(...)` shape: a
  round saved, nothing held, and planning can never approve.
- **Joining only within one place.** Rejected by the owner for the wide stance, narrowed later
  by the audience design.
