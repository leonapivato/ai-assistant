# 349. A place is only what caused an activation, a stop is reached three ways, running work is shared by reading it, and the newest absorbs what it continues

- Status: Proposed
- Date: 2026-10-25
- Scope: the operations between activations that run at the same time. A place is only what caused an activation (§2). The operations are spawn, stop, share and merge (§3). A stop is reached by a command from outside, by a merge, or by words on another place (§4). Running work is shared through an in-progress section, a look-up of one activation's findings and ADR-0350's list pull, which read open episodes through one read function (§5, §6). The newest activation absorbs the older ones its input continues, until they act (§7), and a conversation waits only once something running in it has acted (§8). This is Part A (§§1–5) of proposal [#3384](https://github.com/leonapivato/ai-assistant/pull/3384) at `86152e7a8`, converted. Its Part B, the Task Scheduler and the Task Manager, is ADR-0350's, and spawning is decided there (§3).
- Dependency: [ADR-0292](0292-a-channel-is-the-spokes-facing-one-thing-and-the-assistants-edge-is-its-own.md), [ADR-0295](0295-stopping-an-activation-is-a-command-that-starts-nothing-new-and-cuts-off-nothing-already-sent.md), [ADR-0297](0297-a-stop-is-marked-on-the-activation-and-recorded-where-claims-are-decided.md), [ADR-0332](0332-activations-run-side-by-side-across-places-and-one-at-a-time-within-one-a-new-input-joins-the-running-activation-until-it-acts-and-a-place-waits-a-moment-before-it-starts.md), [ADR-0341](0341-a-pure-read-is-a-call-that-writes-nothing-and-does-not-leave-the-hub-so-looking-something-up-in-the-assistants-own-records-does-not-commit-an-activation.md), [ADR-0343](0343-a-join-is-taken-pending-its-readers-marking-and-every-route-by-which-an-activation-leaves-running-settles-it-first.md), [ADR-0286](0286-an-episode-is-open-while-its-activation-runs-and-frozen-when-it-ends.md), [ADR-0306](0306-a-capability-declares-what-its-calls-do-every-call-is-checked-by-rule-and-acting-claims-and-records-what-it-does.md) and [ADR-0307](0307-a-planning-round-is-one-model-response-that-writes-its-own-message-keeps-episode-notes-and-names-what-it-was-shown-by-label.md), as their status lines leave them; and ADR-0350 (Proposed, #3419), the Task Scheduler and the Task Manager, which merges first (§1:3).
- Authorization: the owner ruled every part of this decision in the design walk of 2026-10-21 to 2026-10-24, recorded in proposal #3384's Part A, which this converts. On the two ADRs the walk produced, the owner's words, verbatim: "just finish adrs A and B. And dont ratify them. Ill review when they are done." Ratification is the owner's, after their own review. The dispatcher assigned 0349.
- **Changes `core`, so it is a contract-surface decision. No `Protocol` changes.** `ProposedActivationUnderstanding` and `ActivationUnderstanding` gain `cancels`, and their `continues` becomes a sequence. `ConversationState` names every running activation, not one. `Settings` loses `join_limit` and gains `held_input_limit` and `in_progress_limit` (§9, §10). Understanding is stored with the episode, and the episode and the conversation's state both cross the wire, so the episode store ships an upgrade and `PROTOCOL_VERSION` advances.
- **Partially supersedes**, in the clauses §12's first table names: ADR-0276, ADR-0286, ADR-0292, ADR-0295, ADR-0307, ADR-0332 and ADR-0343.

## Context

In this document a bare section reference, such as §7:5, is to this decision's own clauses.
Every other ADR's are written with its number, such as ADR-0332 §3:2.

**The owner's question, 2026-10-21.** *"What if there was some basic operations that can be
done in parallel activations, such as merging … Or do these operations merge, fork, split,
cover, essentially anything that could happen?"* The walk that followed, from 2026-10-21 to
2026-10-24 on proposal #3384, narrowed that to three operations, spawn, stop and share,
with merge as a share and a stop in one step. Along the way the owner set the principles the
rest follows:

- **Spawned work is ordinary.** *"Things like the reminder or background task are just normal
  activations that might have spawned from a certain conversation, but they don't live
  there."*
- **A place ties an activation to nothing.** It is only what caused the activation. An
  earlier draft gave each activation a home place, for its window, its "working…" and its
  stop. The owner dropped it.
- **The newest decides.** *"The newest activation has the most up-to-date information, and
  therefore it should be the choice of the newest activation."*
- **Do the simple version.** *"For now, do a simple design that works. Don't worry much about
  who and what and privacy. That stuff will be addressed later."*

**What it assumes.** Outside content, disclosure (who may see what) and authority (approvals)
are other designs, and this decision assumes they work. Whatever crosses between activations
carries its author, its authority and its marks. The gaps those designs must close are named
in §11. The owner: *"Just note that the gaps need to be closed."*

**What the code does today, at `82d03b61`.**

- **One activation at a time within a place, with joining** (ADR-0332 §2:3–§2:5, §3). A new
  input on a place joins the activation running there until it commits
  (`Engine._join_running`, `orchestration/joining.py`), pending the reader's marking
  (ADR-0343). Anything else waits.
- **A takeover across places** (ADR-0332 §4). Understanding is shown the same person's
  running activations on their *other* places, under `R` labels, and may name one it
  `continues`. The takeover stage (`Engine._takeover_stage`) stops that one and takes
  its input, where it has not committed.
- **One stop** (ADR-0295, ADR-0297). The hub chat's stop control reaches
  `AssistantEngine.stop_activation`, and the line's `/stop` reaches the same engine step
  through its reader (`orchestration/telegram.py`). A conversation's current state names one
  running activation (`ConversationState.activation_id`).
- **Planning never sees running work.** Its episode window skips every open episode
  (`orchestration/planning.py`, `_Request._episodes`), and no model reads an open episode
  (ADR-0286 §6:4).

**What this reverses.** The controller walk's answer 1 on #3257, which ADR-0332 converted,
chose one activation at a time within a place. The owner reverses it here: a conversation
needs to hold a message back only once something running in it has acted (§8), and before
that every message starts its own activation and the newest decides (§7). That answer is a
walk record, not an ADR, so it is stated here rather than superseded.

**What ADR-0292 already owes.** ADR-0292 §11:2–§11:3 put understanding in charge of how a new
activation relates to running work, with merging and taking over as one mechanism. ADR-0292
§11:4 says the end state owes, before it runs, "waiting once, before an action, for the
user's inputs not yet understood". Without that wait the newest cannot decide: an older
activation could act on "book Saturday" before the newer "actually Sunday" was understood.
§7:12–§7:14 build it.

## Decision

We will treat a place as only what caused an activation. Activations act on each other by
four operations: spawn, which ADR-0350 decides; stop; share; and merge, which is a share and
a stop in one step. A stop is reached from outside, by a merge, or by words on another place
that understanding reads as cancelling running work. Every running activation for a person
is shown to understanding and, fresh at every round, to planning. Planning can look up a
running activation's findings, and ADR-0350's list pull lists what is running. Each of these
reads open episodes through one read function. Every message starts its own activation, the newest absorbs the older
ones it continues before they act, and an older one about to act first waits for newer input
to be understood. A conversation holds a message back only once something running in it has
acted.

### 1. Status, scope and delivery

> **Normative.** This document remains `Proposed` until the reviews `CONTRIBUTING.md` →
> "Finishing an ADR PR" requires have returned green on one tree and the owner has ratified
> it after their own review. An assigned number or a green review alone does not change its
> status.

> **Normative.** No lane implements this decision before it merges `Accepted`.

> **Normative.** This decision merges only after ADR-0350 has merged.

> **Normative.** The implementation ships as separate pull requests in this order.
>
> 1. **`core`, `wire`, `testing` and `memory`, permitted expressly here as one unit.** §10's
>    types and §9's settings; the one read function (§6:7) in `core/episode_encoding.py`;
>    the `PROTOCOL_VERSION` advance with the wire surface and type closure; and the episode
>    store's upgrade under ADR-0326 §4:1–§4:2 for §10:7's change.
> 2. **`orchestration`, the activation:** understanding's `continues` and `cancels`; the
>    in-progress section for understanding and planning (§5); the findings look-up and its
>    declaration, and the running part of ADR-0350's list pull (§6); the takeover stage as
>    §4:6 and §7 restate it; the waits before a takeover and before the first act, and the
>    commitment step (§7:12–§7:16); and the removal of joining by code.
> 3. **`orchestration`, the readers:** the conversation's rule (§8) in `ChatReader` and
>    `TelegramReader`, the start wait as §8:7 places it, what the readers hold in it for the
>    first act's wait (§7:12), and the line's `/stop` for every running activation (§4:3).
> 4. **`interfaces`:** the hub chat page's stop control for every activation its
>    conversation's state names (§4:3).
>
> Step 2 depends on step 1, step 3 on step 2, and step 4 on step 1.

> **Normative.** The tests of the step that builds each include these cases:
> - two newer activations name the same older one, with the newer of the two finishing its
>   understanding first and then last: in both orders the older of the two absorbs it
>   first, and the newer follows forward and absorbs that one, where it has not committed;
> - an older activation reaches its first act while a newer one for the same person has not
>   recorded its understanding: it waits, the newer absorbs it, and it dispatches nothing;
> - an older activation reaches its first act while the correction is still held in its
>   place's start wait: it waits for the correction's activation, which absorbs it;
> - an input names in `cancels` an activation that a middle one absorbs while the input's
>   takeover waits: the cancel follows forward and stops the middle one;
> - an activation that failed before its first round and wrote *couldn't finish*: a
>   findings look-up shows that fixed line with its outcome, and nothing else it did;
> - two older activations on different places, neither yet understood, and a newer input
>   continuing one of them: the in-progress entries show each one's input, and only the
>   one named is absorbed;
> - an input naming a committed activation in `cancels` stops it, and the same input without
>   the user's authority stops nothing;
> - in a conversation, a message while nothing running has committed starts its own
>   activation, and a message while one has committed waits until it ends;
> - an absorption refused at `held_input_limit`, at a limit of 1 and at an exhausted one;
> - the read function shows no stage in progress, no dispatched-but-unfinished call, and
>   nothing the activation read from another.

### 2. A place is only what caused an activation

> **Normative.** An activation's place is the place its input came from (ADR-0292 §5:1), and
> it ties the activation to nothing else. No activation has a home place.

> **Normative.** An activation's context is its windows, recall, its stories and the
> in-progress section (§5). Another place's recent messages reach it only by a pull of that
> place (ADR-0292 §6:3), where the place's kind declares one; this decision declares none.

> **Normative.** Whether a place shows running work and offers a stop is its kind's
> declaration (§4:10), and not part of the general model.

> **Normative.** Admission, waiting and the reply a conversation expects stay the rules of
> the kind of the place that caused the activation (§8).

Speaking into a place other than the input's is an act like any other call, and that is
decision C's, its own track (§11). Until it lands, ADR-0306 §4:7 stands: the round's own
message goes only into the place the input came from.

### 3. The operations

| Operation | What it is |
| --- | --- |
| **Spawn** | An activation sets up another, to start now, later or after other tasks end. ADR-0350 decides it. |
| **Stop** | ADR-0295's stop, unchanged: nothing new starts, what is in flight finishes and is recorded, nothing new is written, and nothing is abandoned or undone (§4) |
| **Share** | An activation sees what the others are doing, and can fetch what they found (§5, §6) |
| **Merge** | A share and a stop as one step: the newest takes in an older one's input and findings, and the older is stopped (§7) |

> **Normative.** One activation acts on another only by the four operations the table names.

> **Normative.** Spawning is ADR-0350's, and this decision decides nothing of it.

> **Normative.** Start is not an operation. Every activation begins from an input its place's
> sensor took in and admission admitted, whether a message, an email or a scheduled task
> coming due, and no activation begins another except by spawning.

> **Normative.** Once an activation has committed, nothing merges into it. What comes after
> is a new activation, which reads the records.

> **Normative.** For every rule of this decision, an activation has **acted** exactly when
> acting has committed it under ADR-0332 §3:2, a pure read being what ADR-0341 §2:1 defines.
> The committed mark an absorption sets (§7:7) is not an act.

That is how a correction after a reply works today, and it stays so. Fork, split, suspend
and "kill" were considered and are not operations (Alternatives).

### 4. Stop

**One operation.**

> **Normative.** Every route in this section stops an activation by ADR-0295's stop, as
> ADR-0297 records it: it names exactly one activation, sets its stop mark and then writes
> its stop record (ADR-0297 §3:3–§3:4), and the stopped activation carries every guarantee
> of ADR-0295 §§2–4.

**From outside.**

> **Normative.** From outside, a stop is the Task Manager's stop command, which ADR-0350
> decides.

> **Normative.** The hub chat's stop control sends a stop for each activation its
> conversation's current state names as running, and the line's `/stop` stops each
> activation started from the line's chat that is running. Each is a shortcut to the one
> stop.

> **Normative.** A conversation's current state names every running activation started
> from it whose id is known (§10:4).

**By a merge.** The older activation is stopped (§7:7, ADR-0295 §5:1).

**By words, across places.** "Never mind the booking," said on Telegram after the web
activation has booked.

> **Normative.** Understanding's reply may name, in `cancels`, shown running activations
> whose work its input asks to stop.

> **Normative.** In the takeover stage's one step (§7:4), the stage stops each activation it
> reached from the latest understanding version's `cancels` where all of these hold:
> - the activation reached is running and its stop mark is unset;
> - this activation's input carries the user's authority (ADR-0292 §5:5);
> - the activation reached is running for the person this input's author is established as
>   (§5:3).
>
> It stops it whether or not it has committed.

> **Normative.** An activation named in both `cancels` and `continues` that §7 absorbs is
> stopped by the absorption, once.

> **Normative.** Where a condition of §4:6 fails, nothing is stopped, and the stage records
> that it did not stop that activation.

> **Normative.** Planning of an activation whose `cancels` stopped another is shown that
> activation's finished work through §6's read function, so that its message can say what
> had finished.

The message stays input, and becomes no command (ADR-0292 §12:5–§12:6 hold). The stop is
ADR-0292 §11:2's rule acting on understanding's judgment, which is what a rule acting on
`continues` already does. A forward, a reminder or a message whose author is not established
carries no user's authority, so it cancels nothing. "Go on" afterwards takes it back, because
a stop abandons no goal (ADR-0295 §4:1). This is the item ADR-0332 §9 left to #2515.

Within one conversation, words after something has acted wait (§8:3), so they stop nothing.
The stop control stops it there.

**What a place shows.**

> **Normative.** A kind declares whether its places show running work and offer a stop. The
> conversation kind declares "working…" and the stop control (ADR-0293 §8:2, ADR-0295 §1:2);
> the line declares typing (ADR-0323 §6:8) and `/stop` (ADR-0332 §8); the Task Scheduler's
> declaration is ADR-0350's.

> **Normative.** A place shows running work, and offers a stop, only for the activations it
> caused.

So a spawned activation speaking into a conversation was caused by the Task Scheduler, and it
is stopped by words or through the Task Manager. Whether an activation is running is still
never written into the medium (ADR-0292 §11:7).

### 5. Share: the in-progress section

**No supervisor.** An earlier draft had rules that pushed findings between activations: the
same story, the same person, lineage. The walk replaced them with what follows, built mostly
from what exists.

> **Normative.** No rule pushes one activation's findings into another's. One activation
> learns of another's work only through §5's section, §6's look-up and list pull, and what
> §4:9 and §7:10 show.

> **Normative.** Understanding and planning are each shown, beside their windows, an
> **in-progress section**: one entry for each activation running for the same person whose
> stop mark is unset, other than this one, on any place, the activations ADR-0350's Task
> Scheduler started included.

> **Normative.** The same person means that both inputs' authors are established as that
> person (ADR-0332 §4:1). For an activation the Task Scheduler started, its person is the one
> its scheduled task is for, as ADR-0350 records it.

> **Normative.** An activation is entered in the section only where
> `admitted_to_understanding` (in `orchestration/disclosure.py`, ADR-0276 §4) would admit an
> episode of its place to this pass.

> **Normative.** No activation is entered in the section of an input whose author is another
> person or is not established.

> **Normative.** Each entry shows exactly, in version 1:
> - a label;
> - what caused it: its channel and its place;
> - what it took in, in brief, through §6's read function, so that outside input never
>   appears raw;
> - whether it has acted.

> **Normative.** Understanding labels the entries with `R` labels (ADR-0332 §7:3). Planning
> labels each with the episode label of the activation's episode (ADR-0307 §5:1).

> **Normative.** Understanding is shown the section as it stands when its call is rendered.
> Planning is shown it read fresh at the start of every round.

> **Normative.** In planning's request, the section comes after every part that is the same
> across the rounds of one activation, so that a section changing each round never splits
> the part a prompt cache can hold (#3084).

> **Normative.** The section shows at most `in_progress_limit` entries (§9:3), newest first,
> and says how many more are running. ADR-0350's list pull (§6:2) lists the rest.

A running activation learns of a newer one at its next round. "My budget's $400 now," said on
Telegram, reaches the running flight search before its next round, and the search adapts.
Every activation sees the others, so it works in both directions.

### 6. Share: the look-up, the list and the one read function

**The look-up and the list.** For anything more than the section shows, planning looks it
up.

> **Normative.** Planning may look up the findings of a running activation, by the label of
> its entry in the in-progress section: "what has the flight search found?"

> **Normative.** The list of what is running is ADR-0350's list pull: "what are you doing
> right now?" Its running part lists each activation the section would enter (§5:2–§5:5),
> each as §5:6's entry shows it, without §5:10's limit.

> **Normative.** What is scheduled and what ran lately reach planning as ADR-0350's list
> pull decides, and this decision adds nothing to them.

> **Normative.** The findings look-up's capability declares its effect as the assistant's own
> records, that it does not leave the hub, a result with no outside text, an outcome that is
> never unknown, that it is safe to repeat, and an empty `writes`, as reading a story does
> (ADR-0306 §3:1). It is a pure read (ADR-0341 §2:1) and commits nothing.

> **Normative.** A findings look-up naming a label that is not an in-progress entry's is
> refused whole, with the reason, and runs nothing, as ADR-0307 §5:3 refuses a label never
> shown.

> **Normative.** Where the named activation has ended since it was shown, the look-up shows
> its finished work and says that it has ended.

**The one read function.**

> **Normative.** One read function renders every model-facing read of an episode: it is
> `project_episode` in `core/episode_encoding.py` (ADR-0284 §8:1), extended with a **peer
> view**. The in-progress entries, the findings look-up, the running part of ADR-0350's list
> pull, an absorbed activation's findings (§7:10) and a cancelled one's (§4:9) read the peer
> view (§6:8–§6:10). Recall's rendering keeps its projection, as ADR-0284 §8:1 and ADR-0308
> §3:1 rule it.

> **Normative.** The peer view is computed from two records alone: the activation's episode
> as stored, open or frozen, and its effect records, which orchestration reads from the
> plan store (`PlanStore.activation_effects`, ADR-0306 §6) and hands to the pure function.
> Of an open episode it shows only what its stages appended when they ended (ADR-0286
> §3:1), and of the effect records only those whose outcome is written: never a stage or
> round in progress, and never a call or message not yet finished.

> **Normative.** Of another activation's work, the peer view shows only that activation's
> own work:
> - what it took in: its input, as `project_episode` renders it with `admit_outside_input`
>   false, cut to its excerpt bound, so that outside input is withheld (ADR-0284 §8:1);
> - what it is doing: its latest understanding's meaning, rendered as provisional
>   (ADR-0276 §4:6), where one is recorded;
> - what it found: its rounds' episode notes (ADR-0307 §4) and its digests' answers with
>   their evidence, each item with its mark (ADR-0308 §5:5);
> - what it did: each of its effect records (ADR-0306 §5:3) whose outcome is done or
>   unknown, each with that outcome: a call shown by its capability; a message by the
>   message of the round the record names; and the *couldn't finish* message, whose record
>   names no round (ADR-0307 §10), as a fixed line saying the activation could not finish.

> **Normative.** The peer view never shows another activation's recall results, story
> links, failed calls, drafts or approvals, nor anything that activation read from another:
> its own in-progress section, its look-ups and list pulls of others, and the findings it
> absorbed or a cancel showed it.

> **Normative.** No call's result is added to an episode for a share. A result that was not
> digested reaches another activation only as the episode notes of the activation that
> called it record it (ADR-0307 §4:2).

> **Normative.** Nothing a share shows authorizes anything. It reaches the reader as
> information carrying no authority, no approval is shown, and an approval is used only by
> its yes's activation (ADR-0321 §4:1).

> **Normative.** Planning is shown every activation a share shows it under that activation's
> episode label (§5:7), and an outside episode (ADR-0303 §3:2) shown so counts in the
> reader's record of what it read, as any episode planning is shown under a label counts for
> ADR-0306 §4:5. So an activation shown another that has read outside content has read
> outside content, and ADR-0306 §4:4's stand-in applies to it.

Because a peer is shown only its own work, nothing echoes back and no reads chain. The
authorizing boundary holds across a share by §6:13, and the episode notes and evidence the
view shows carry their marks as recall shows them. One read function means the gaps §11
still names are closed in one place when they are closed.

### 7. Merge: the newest absorbs

> **Normative.** A merge is a share and a stop in one step: the newest activation takes in
> an older one's input and finished findings, and the older is stopped. Only a newer
> activation absorbs an older one.

> **Normative.** Every input starts its own activation, after its place's start wait
> (ADR-0332 §5), subject to its kind's rule (§8).

> **Normative.** Understanding's reply may name, in `continues`, the shown running
> activations its input continues: whose work it **corrects, completes, cancels or changes**.
> An input that asks for separate work on the same matter continues none.

The newest's understanding sees the older ones in the in-progress section, and, within one
conversation, their messages in its place window too. "What's the weather there?" while a
hotel search runs is separate work: kept separate, the weather comes back first, each runs on
its own, a failure stays contained, each reply lands where it was asked, and the two still
see each other in the section.

> **Normative.** The takeover stage, once for each understanding version that names any
> activation in `continues` or `cancels` (§10:9), first waits as §7:15 states. Then, in one
> step with no await between, it follows each activation named in either forward, while it
> has been absorbed, to the activation that absorbed it; absorbs those it reached from
> `continues` under §7:5–§7:7; and stops those it reached from `cancels` under §4:6.

> **Normative.** In that step the stage absorbs each activation it reached from `continues`
> where all of these hold:
> - it started before this one;
> - it is running, it has not committed, and its stop mark is unset;
> - its input's author is this input's author, established in the same way, and its input
>   carries the same authority (ADR-0292 §5:5) and the same origin (ADR-0284 §2:2).

> **Normative.** Where absorbing every activation that qualifies under §7:5 would bring the
> inputs this activation holds above `held_input_limit` (§9:2), the stage absorbs none of
> them and records the decision *not taken*.

> **Normative.** To absorb an activation, the stage, in that one step, sets its stop mark and
> its committed mark, so that it can neither commit nor be absorbed by another; records that
> this activation absorbed it; and appends every input it holds to this activation as a
> `JoinedInput` naming it. It writes the absorbed activation's stop record after the step,
> as a stop does (ADR-0297 §3:4).

> **Normative.** The stage records, for the version, each activation named and whether it
> was absorbed.

> **Normative.** The understanding version that named an activation in `continues` covers
> every input absorbing it brought, so `not_understood` (ADR-0332 §3:9) does not answer for
> them.

> **Normative.** Planning of the absorbing activation is shown, at every round, each absorbed
> activation's finished findings, read fresh through §6's read function from that
> activation's episode.

> **Normative.** A merge does not extend the absorbing activation's deadline.

A look-up in the hub's own records is not acting, so an older activation may have done real
work before it is absorbed, and the merge keeps it. Work it had started finishes after the
stop and is recorded on its own episode (ADR-0297 §4:9), which is why §7:10 reads it fresh.
Only the newer absorbs the older, so there are no cycles. "Joining" and "takeover" stop being
two mechanisms: within a conversation and across places, the newest absorbs.

**The older waits for the newest.** The newest can decide only if the older does not act
first.

> **Normative.** Before acting dispatches any call of a round that is not a pure read, or the
> round's message, and before the activation has committed, it waits, once, for each
> activation that started after it, is running for the same person, and whose input has this
> input's author, authority and origin, and for each such input that a reader of one of
> that person's places holds in its start wait. It waits until each activation, and each
> held input's activation once admitted, has ended, or has recorded its first understanding
> version or its omission and, where that version names any activation in `continues` or
> `cancels`, the takeover stage's decision for it; and until each held input not taken in
> is released. What it waits for is what runs, and what is held, when the wait begins.

> **Normative.** That wait is bounded by the pass's deadline. Where it reaches the deadline,
> acting dispatches none of the round's calls and not its message, and ends as a stage whose
> deadline expired during it (ADR-0280 §5:1).

> **Normative.** The commitment step follows the wait with no await between the wait's end
> and it. In one step, where the activation's stop mark is set, acting dispatches none of the
> round's calls that are not pure reads and not its message; otherwise it marks the
> activation committed.

This is ADR-0292 §11:4's "waiting once, before an action, for the user's inputs not yet
understood". A reader holds an input in its start wait for a second or two, so the wait
covers a correction typed just before the act, not only one already started.

**Takeover decisions are made oldest first.** Two newer activations may continue the same
older one, and the newest may finish its understanding first. Were it to absorb first, the
middle one would follow forward to an activation newer than itself, which it cannot
absorb, and both would go on to act on one matter.

> **Normative.** Before its step (§7:4), the takeover stage waits, once, for each older
> activation running for the same person whose input has this input's author, authority
> and origin, until each has ended, or has recorded its first understanding version or its
> omission and, where that version names any activation in `continues` or `cancels`, the
> takeover stage's decision for it. What it waits for is what runs when the wait begins.

> **Normative.** That wait is bounded by the pass's deadline. Where it reaches the deadline,
> nothing is absorbed or stopped, and the stage ends as a stage whose deadline expired
> during it (ADR-0280 §5:1).

So whoever absorbed a named activation is older than the activation following it forward,
and the newest still absorbs last. No two wait for each other. A takeover waits only on
older activations' takeover decisions, which each records before it plans, so before its
first act. A first act waits only on newer ones. A takeover never waits on an act.

### 8. The conversation's rule

> **Normative.** The conversation kind and the line each declare §8:2–§8:5 for their places,
> in place of running one activation at a time.

> **Normative.** On such a place, a message starts its own activation, after the place's
> start wait, wherever no running activation started from that place has acted.

> **Normative.** Where a running activation started from that place has acted, a message
> waits. It is never refused, and it keeps its authority (ADR-0292 §5:7).

> **Normative.** Once no running activation started from the place has acted, everything
> waiting there is taken in together as one input (ADR-0292 §6:10).

> **Normative.** §8:2–§8:4 hold across authors. Only absorbing requires the same author
> (§7:5).

> **Normative.** Across places there is no wait: a message on one place starts its activation
> whatever runs on another (ADR-0332 §2:2).

> **Normative.** The start wait (ADR-0332 §5:1, §5:3) runs for every message that would start
> an activation under §8:2, whether or not something runs on the place, and for no message
> that waits under §8:3.

> **Normative.** A reader marks a message taken in by the activation that admitted it, as at
> admission (ADR-0293 §6:8, ADR-0323 §5:8). Absorbing marks nothing again.

Running beside work that has acted would mean acting on a half-finished picture, such as
rebooking while the first booking is still in flight. Waiting there, the next activation sees
the finished result in the records. Across places, a newer related activation sees "has
acted" in the section, and can cancel the older (§4:6) or carry on after it. A true race
between two acts on one thing is the lock and recheck's (#2586).

**Replies out of order.** With several activations in one conversation, replies arrive in the
order the work finishes. Saying which message a reply answers, by a native reply, a
"replying to…" display or a fixed prefix, is decision C's (§11).

### 9. The numbers

> **Normative.** `Settings` loses `join_limit` (ADR-0332 §6:5).

> **Normative.** `Settings` gains `held_input_limit`, an integer, default **4**, at least 1:
> the most inputs one activation holds, its own with every one it absorbed. 1 turns absorbing
> off.

> **Normative.** `Settings` gains `in_progress_limit`, an integer, default **5**, at least 1:
> the most entries the in-progress section shows (§5:10).

> **Normative.** [#2589](https://github.com/leonapivato/ai-assistant/issues/2589) tunes these
> defaults by measurement, without a new decision.

`held_input_limit`'s default is ADR-0332's `join_limit` of 3 with the activation's own input.
ADR-0332 §6's four waits stand as they are. The starting values are guesses, to be measured.

### 10. The code it binds

> **Normative.** `ProposedActivationUnderstanding.continues` becomes
> `tuple[EncodableText, ...] = ()`, each element the `R` label of an in-progress entry
> (ADR-0332 §7:3).

> **Normative.** `ProposedActivationUnderstanding` gains `cancels:
> tuple[EncodableText, ...] = ()`, each element the `R` label of an in-progress entry.

> **Normative.** `ActivationUnderstanding.continues` becomes `tuple[Identifier, ...] = ()`,
> and `ActivationUnderstanding` gains `cancels: tuple[Identifier, ...] = ()`: the activations
> the proposal's labels resolved to, in the proposal's order, each once. A label that
> resolves to no shown activation is dropped as a grounding defect (ADR-0276 §6), never a
> parse failure.

> **Normative.** `ConversationState.activation_id` becomes `activation_ids:
> tuple[Identifier, ...] = ()`: every running activation started from the conversation whose
> id is known, and empty unless the state is working.

> **Normative.** The working set's takeover decision, per understanding version (ADR-0332
> §7:6), records each activation named in `continues` or `cancels`, and whether it was
> absorbed, stopped, or neither.

> **Normative.** Each change that alters a shape the wire carries advances
> `PROTOCOL_VERSION` in that change, under ADR-0124 §9:2, with the wire surface and type
> closure, and the memory and engine conformance suites, extended to the shape.

> **Normative.** §10:3's change to the stored understanding is a schema change under
> ADR-0326 §2:3, and ships ADR-0326 §4:1–§4:2's upgrade and its test in the same pull
> request. A stored `continues` naming one activation becomes a one-element sequence, an
> absent one an empty sequence, and `cancels` is empty.

> **Normative.** `JoinedInput` keeps its shape. Each one this decision appends names, in
> `taken_over_from`, the activation it was absorbed from.

> **Normative.** `ControllerRule.TAKEOVER_UNDECIDED` answers where the latest understanding
> version names any activation in `continues` or `cancels` and there is no takeover decision
> for that version, and makes the takeover stage due, which absorbs (§7) and cancels (§4:6).

> **Normative.** `ControllerStage.TAKEOVER` and `ControllerRule.TAKEOVER_UNDECIDED` keep
> their names, and the rule keeps its row (ADR-0332 §4:5).

No `Protocol` changes: `AssistantEngine.stop_activation` is the one stop every route
reaches.

### 11. What this decision does not decide

| Not decided here | Where it goes |
| --- | --- |
| The Task Scheduler, scheduled tasks, spawning, the sensor, and the Task Manager's operations and view | ADR-0350 |
| **Decision C, calls onto channels:** every channel the same shape; speaking as a say-call into any place; *in reply to* and replies out of order; a conversation's expected reply as its kind's requirement; and its supersession of ADR-0170 ([#2593](https://github.com/leonapivato/ai-assistant/issues/2593)) | Its own track |
| **Modes:** quick, normal, deliberate, "just blurt" | Its own decision, next on this front |
| **The gap for outside content:** marks travelling on every read of another activation's episode, through the one read function (§6:7), beyond authorizing's count (§6:13): to understanding's in-progress section, and to what a reader's own notes and messages then rest on | The outside-content design |
| **The gap for privacy:** shares and merges stay within one person (§5:3, §7:5) until the household design | The household design |
| **The gap for forgetting:** every read is fresh each round, so a forget or a deletion is honored (cf. [#3319](https://github.com/leonapivato/ai-assistant/issues/3319)) | The privacy and forgetting design |
| **The gap for the audience:** the audience where a message lands ([#2590](https://github.com/leonapivato/ai-assistant/issues/2590)) | The audience design |
| What a place whose activation was absorbed hears about where the matter went | [#2588](https://github.com/leonapivato/ai-assistant/issues/2588) |
| The lock and recheck for two acts on one thing | [#2586](https://github.com/leonapivato/ai-assistant/issues/2586) |
| Batching unrelated messages into one activation, if two messages ever feel chatty | Measurement first |
| The values of §9, and the in-progress section's size | #2589 (§9:4) |
| A pull of another place's recent messages, as a capability (§2:2) | The kind that declares it |

> **Normative.** Each item the table names takes a decision of its own before any lane builds
> it.

### 12. Relationship to earlier decisions

Superseded in part; every clause the middle column does not name stands:

| Earlier decision | What it replaces | By |
| --- | --- | --- |
| ADR-0332 | §2:3, for the conversation kind and the line, and §2:4–§2:5, whole: they declare §8's rule in place of one activation at a time; §3:3–§3:8, §3:15 and §3:18, whole: no input joins by code, and before its first act an activation waits once for newer input to be understood (§7:12–§7:14); §3:9, in the addition alone: a version covers the inputs its absorption brought; §4:1–§4:4, whole: the in-progress section on every place, spawned activations included, and `continues` narrowed and joined by `cancels`; §4:5, in the addition alone: `takeover_undecided` also answers for `cancels`; §4:6, whole: the newest absorbs, following forward, under the held-inputs limit; §4:8, in the addition alone: a committed activation named in `cancels` is stopped; §5:1, §5:3 and §5:5, each in the addition alone: the start wait runs whether or not something runs on the place; §6:5, whole: `held_input_limit` replaces `join_limit`; §7:3 and §7:4, whole; §7:6, in the takeover decision's content; §8:4, in the addition alone: `/stop` stops every running activation started from the chat | §4:3, §4:6, §5:2–§5:7, §7:3–§7:7, §7:9, §7:12–§7:16, §8:1–§8:8, §9:1–§9:2, §10:1–§10:5, §10:9–§10:10 |
| ADR-0343 | §2:1–§4:3, whole: no join is taken by code, so none is pending, and no route waits for one | §7:12–§7:14, §8:8 |
| ADR-0292 | §11:2, as ADR-0332 left it, in two parts: input that adds separate work to running work stops nothing, and an activation named in `cancels` is stopped whether or not it has committed; §11:7, in the addition alone: running work is shown only where the place's kind declares it, and only for the activations it caused | §4:6, §4:10–§4:11, §7:3 |
| ADR-0295 | §1:1, §1:4 and §1:5, each in the addition alone: a stop is also reached by understanding's `cancels` and §4:6's rule; §1:2, in the addition alone: the conversation's state names every running activation, and its stop control stops each | §4:3–§4:6, §10:4 |
| ADR-0286 | §6:4, in the addition alone: the in-progress section, the findings look-up, the running part of ADR-0350's list pull, and the reads of absorbed and cancelled work read another activation's open episode through the one read function | §5:6, §6:7–§6:8 |
| ADR-0276 | §2:1's `ProposedActivationUnderstanding` and `ActivationUnderstanding` field sets, in the additions alone: `cancels`, and `continues` as a sequence | §10:1–§10:3 |
| ADR-0307 | §6:1, in the addition alone: planning is given the in-progress section and absorbed findings, read fresh each round; §6:6, in the addition alone: planning may look up a running activation's findings | §5:2, §5:8, §6:1, §7:10 |

Read through and not superseded:

| Earlier decision | What changes |
| --- | --- |
| ADR-0292 §11:1, §11:5 | Nothing on their lines: ADR-0332 replaced §11:1 within a place and §11:5 whole, and this decision replaces ADR-0332's clauses. A conversation now starts every message's activation until something in it acts (§8:2), by §8's rule and not by reviving §11:1 |
| ADR-0292 §11:4 | Nothing: §7:12 builds its wait once before an action, and ADR-0295 §3:3 its stopped activation writing nothing; its lock and recheck stays #2586's, as ADR-0332 §9 left it |
| ADR-0292 §10:4, §12:5–§12:6 | Nothing: a running activation on the place is shown beside the window, in the section, and a message never becomes a command, `cancels` being §11:2's rule |
| ADR-0295 §§2–5, ADR-0297 | Nothing: every route reaches the one stop, and the stop mark is read and set as before. A stop holds no waiting message back (ADR-0295 §3:6): what waits is taken in once §8:4 holds |
| ADR-0306 §4:7, §5:2 | Nothing: the round's message goes only into the input's place until decision C, and everything claimed finishes |
| ADR-0321 §4:1 | Nothing: an approval is used only by its yes's activation, and no share shows one |
| ADR-0341 | Nothing: a pure read is as it defines it, and the findings look-up is one |
| ADR-0350 | Nothing in its words: its list pull showed a running activation as ADR-0332 §4:1–§4:3 did, which §5:2–§5:6 replace, so its running part shows the in-progress entries (§6:2); and its stop shortcuts send the Task Manager's stop for each activation their place shows (§4:3, §4:11) |
| ADR-0276 §4, ADR-0286 §6:1 | Nothing: the episode window holds what it held, and no search returns an open episode; the in-progress section is beside the window, not in it |
| ADR-0303 §7 | Nothing: a place-window item links to the activation that took it in, an absorbed one included |
| ADR-0284 §8:1, ADR-0308 §3:1, §5:5 | Nothing: recall's projection stays as they rule it, and the peer view is a second view of the same function, whose evidence carries its marks as recall's does |
| ADR-0303 §3:2, ADR-0306 §4:4–§4:6 | Nothing: an activation a share shows planning is an episode shown under a label, and an outside one counts in the reader's record as any does (§6:13) |
| ADR-0332 §2:1–§2:2, §2:6, §3:1–§3:2, §3:10–§3:14, §3:16–§3:17, §4:7, §5:2, §5:4, §5:6–§5:11, §6:1–§6:4, §6:6, §7:1–§7:2, §7:5, §7:7–§7:10, the rest of §8 | Nothing in their words: an absorption's inputs are recorded as `JoinedInput`s naming their activation, an absorbed activation is stopped as a taken-over one was, and the waits and `/stop` stand |

> **Normative.** This numbered draft records its replacements on the status lines and in a
> dated header note of ADR-0276, ADR-0286, ADR-0292, ADR-0295, ADR-0307, ADR-0332 and
> ADR-0343, atomically with this ADR under ADR-0070 and ADR-0082, preserving their ratified
> bodies. The replacements take effect on this ADR's ratification.

## Situations

| Situation | What happens |
| --- | --- |
| Three quick messages in one chat, before any reply | The newest absorbs the older two: one reply |
| "Actually Sunday," a second after "book Saturday," before it acts | The older waits for the newer's understanding, and the newest absorbs it: Saturday is never booked |
| "Actually Sunday" after it booked Saturday | It waits for that activation to end, sees the booking, and changes it as a new request |
| "Actually Sunday" on Telegram, before the web booking acts | The newest absorbs across places: one Sunday booking, and the reply comes on Telegram |
| "Never mind the booking" on Telegram, after the web one acted | Understanding names what it cancels, a rule stops it, and the reply says what finished |
| "Also, what's the weather there?" while a hotel search runs | Separate activations: the weather answers first |
| "My budget's $400 now" while a flight search runs | The search sees it in the in-progress section at its next round and adapts |
| "What's the cheapest so far?" from another device | Planning looks up the search's findings and answers |
| "What are you doing right now?" | Planning pulls ADR-0350's list, whose running part shows the in-progress entries |
| Two newer activations name the same older one at once | The first absorbs it; the second follows forward and absorbs the first, if it hasn't acted |

## Consequences

**What becomes possible.**

- A correction a second after a request changes the first answer, on any of the person's
  places, before the first acts.
- "Never mind" on another device stops work that has already acted.
- Every running activation sees the others' finished work each round, and can fetch more.
- A burst of messages gets one reply, and separate questions get separate ones.
- Joining and takeover become one mechanism, and the record names, on each absorbed input,
  where it came from.

**What it costs.**

- Fields in `core/types.py`, a schema change to the episode store with its upgrade, and a
  `PROTOCOL_VERSION` advance.
- Two settings in place of one.
- Every message in a conversation where nothing has acted pays its own understanding, where
  joining paid one for a burst past the start wait.
- An activation about to act first waits for newer input from the same person to be
  understood, when there is any.
- Planning's request grows by the section each round, after its cached part.
- Two activations in one conversation that are separate work may both act before either
  ends. Two acts on one thing is #2586's.
- An absorbed activation's messages appear in two episodes, the stopped one and the absorber,
  whose `JoinedInput` names the former.
- Until the gaps of §11 close, a peer's marks reach authorizing (§6:13) but not every reader,
  and shares stay within one person.
- A takeover decision may wait for an older one's understanding, and a call result planning
  did not digest or note reaches no other activation.

**The cut, for the dispatcher.** Four lanes, in §1:4's order, after ADR-0350 and this
decision merge. Step 2 removes ADR-0332's joining by code and ADR-0343's pending join with
it. ADR-0340 (#3271) is rewritten on top of ADR-0350, and is no lane of this decision.

**What would reopen it.** The household design, for shares and merges across people. The
outside-content design, for marks on peer reads. #2589's measurements, if a message's own
understanding costs too much where nothing has acted.

## Alternatives considered

- **Fork, a running copy.** Rejected: it doubles the model calls, and the copy could act
  twice. Kept from acting, a copy is just a share.
- **Split into equal parts.** Rejected: a person answers a two-part message once and hands
  off the long part, which is a spawn.
- **Suspend and resume.** Rejected: it doesn't survive a restart. Ending and being continued
  does the same job.
- **"Kill."** Rejected: too abrupt for ADR-0295's graceful stop, and "stop" already names the
  mechanism.
- **A home place**, for each activation's window, "working…" and stop. Rejected: a place is
  only what caused an activation (§2).
- **A supervisor with share rules** (the same story, the same person, lineage). Rejected:
  the section refreshed every round, with the look-up and the list, does the same job with less, and the
  automatic flow carries no findings.
- **Joining by code, with a separate takeover** (ADR-0332 §3, §4). Rejected: one rule, the
  newest absorbs, covers both.
- **The newest able to push itself into the older.** Rejected: it gains nothing, and the
  older's findings move with a merge anyway.
- **One activation at a time per conversation** (ADR-0332 §2:3). Rejected: it is needed only
  after something has acted (§8).
- **No wait before the first act.** Rejected: an older activation could act on a request the
  newer input corrects, before the newer was understood, and the newest would not decide
  (ADR-0292 §11:4).
- **A new planning label kind for running activations.** Rejected: each has an open episode,
  and its episode label holds once it ends.
