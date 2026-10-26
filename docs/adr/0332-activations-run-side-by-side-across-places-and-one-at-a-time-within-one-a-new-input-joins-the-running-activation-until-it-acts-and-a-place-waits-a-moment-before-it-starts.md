# 332. Activations run side by side across places and one at a time within one, a new input joins the running activation until it acts, and a place waits a moment before it starts

- Status: Partially superseded by ADR-0341 (§3:1, whole: a pure read is a call whose capability declares an empty `writes`, its effect as none or as the assistant's own records, and that it does not leave the hub) and ADR-0343 (§3:5, §3:6, §3:18 and §4:6, each in the addition alone: a join is taken pending its reader's marking, and every route out of running settles it first) and ADR-0349 (§2:3–§2:5, §3:3–§3:8, §3:15, §3:18, §4:1–§4:4, §4:6, §6:5, §7:3 and §7:4, whole; §3:9, §5:1, §5:3, §5:5 and §8:4, each in the addition alone; §4:8, for a named activation that has committed; §7:6, in the takeover decision's content: every input on every place starts its own activation, the newest absorbs the older activations it continues before they act, and after one acts it is offered the newer input or waited on)
- Date: 2026-10-21
- Scope: how the hub takes in several inputs at once. Activations run side by side across places and across people, and one at a time within a place. A new input joins an activation on its place that has not yet acted, and the same person's other places see that activation and may take it over before it acts. A messaging place waits a moment before it starts, which the hub chat's *composing* signal extends. The line takes `/stop`. These are picks 1 to 3 of proposal [#3257](https://github.com/leonapivato/ai-assistant/pull/3257), with the walk's answers 1 to 4 and 9. Its modes and background work are named in §9 as not decided here.
- Dependency: [ADR-0280](0280-an-activation-controller-runs-the-stages-by-rules-and-records-every-choice-with-the-episode.md), [ADR-0292](0292-a-channel-is-the-spokes-facing-one-thing-and-the-assistants-edge-is-its-own.md), [ADR-0293](0293-the-hubs-chat-is-a-hosted-medium-and-a-conversation-keeps-its-own-transcript.md), [ADR-0295](0295-stopping-an-activation-is-a-command-that-starts-nothing-new-and-cuts-off-nothing-already-sent.md), [ADR-0306](0306-a-capability-declares-what-its-calls-do-every-call-is-checked-by-rule-and-acting-claims-and-records-what-it-does.md), [ADR-0308](0308-recall-runs-again-on-what-understanding-found-and-outside-content-reaches-planning-only-as-a-digests-evidence.md), [ADR-0309](0309-the-phases-are-built-beside-the-old-path-and-one-cutover-switches-the-controller-over-deletes-the-old-path-and-goes-live-in-one-deploy.md), [ADR-0323](0323-a-telegram-chat-with-the-owners-bot-is-a-line-to-the-assistant-and-connecting-it-approves-what-the-line-carries.md), [ADR-0330](0330-a-hubs-telegram-line-may-run-through-a-relay-on-the-box-which-serves-it-the-bot-api-for-one-linked-account-and-the-hub-trusts-it-by-a-certificate-configured-at-setup.md) and [ADR-0326](0326-a-persons-memory-carries-across-every-upgrade-each-schema-change-ships-its-migration-and-a-fresh-data-directory-is-the-owners-ruling.md), as their status lines leave them.
- Authorization: the owner set the direction on 2026-10-21 (Context). The coordinator walked proposal #3257 the same day under the owner's standing delegation, and the walk record on #3257 holds the answers this decision converts. The owner's words on that delegation, verbatim: "Dont draw the line who ratifies what, Ill just check in and if I see something wrong I'll give input to you." Answer 1 changes the end state the owner walked on 2026-10-04, and is marked on the walk record as the owner's to object to. The dispatcher assigned 0332, and ratifies it under that delegation.
- **Changes `core`, so it is a contract-surface decision, and adds a `Protocol` member: a breaking change under golden rule 5.** `AssistantEngine` gains `composing` (§5:9), and `TelegramIntakeRecord.claim_reply`'s documented contract widens to a stop command (§8:6). `core/types.py` gains `JoinedInput`, a field on `EpisodeProcessingRecord`, a field on each of `ProposedActivationUnderstanding` and `ActivationUnderstanding`, a field on `TelegramMessage`, and a member on each of `ControllerStage` and `ControllerRule` (§7). `Settings` gains five fields (§6). The wire carries the new method and the changed record, so `PROTOCOL_VERSION` advances.
- **Partially supersedes**, in the clauses §10's first table names: ADR-0276, ADR-0280, ADR-0286, ADR-0292, ADR-0293, ADR-0295, ADR-0298, ADR-0306, ADR-0309, ADR-0323 and ADR-0330.
- Partially superseded: 2026-10-21 by ADR-0341 — §3:1, whole: a pure read is a call whose capability declares an empty `writes`, declares its effect as `CapabilityEffect.NONE` or `CapabilityEffect.OWN_RECORDS`, and does not leave the hub, decided from the picked tool's declaration alone (ADR-0341 §2:1–§2:3). So a look-up of the assistant's own records, which writes nothing, no longer commits an activation. §3:2's committed mark and §3:5's commitment step read the term as ADR-0341 defines it, a write to the hub's own records and a call that leaves the hub still commit, and every other clause stands. This replacement takes effect on ratification of ADR-0341. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; the ratified body below is preserved.
- Partially superseded: 2026-10-21 by ADR-0343 — §3:5, §3:6, §3:18 and §4:6, each in the addition alone: §3:6's step appends the input as a join pending the reader's marking (§3:18), which counts toward `join_limit` and is no part of the activation's input until the marking confirms it for exactly the messages the store marked, and is released, its input waiting, where the store marked none (ADR-0343 §2). The commitment step (§3:5) and a takeover (§4:6) first wait until no join is pending, inside the pass's deadline; the controller after each stage, the episode's freeze and a shutdown's cancellation settle a pending join too, and a stop's mark stays immediate (ADR-0343 §§3–4). Every other clause stands. This replacement takes effect on ratification of ADR-0343. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; the ratified body below is preserved.
- Partially superseded: 2026-10-25 by ADR-0349 — §2:3–§2:5, §3:3–§3:8, §3:15, §3:18, §4:1–§4:4, §4:6, §6:5, §7:3 and §7:4, whole; §3:9, §5:1, §5:3, §5:5 and §8:4, each in the addition alone; §4:8, for a named activation that has committed; §7:6, in the takeover decision's content. Every input on every place starts its own activation, after the start wait, whatever runs, and no kind runs one activation at a time or holds an input back for running work. No input joins by code. Understanding is shown every activation running for the same person on any place, spawned ones included, and names in `continues` those whose work its input corrects, completes, cancels or changes. The takeover stage absorbs each older, uncommitted one it continues, following an absorbed one forward, under `held_input_limit` in place of `join_limit`. A committed one it continues is, within one place, offered its input, which it takes, the newer then stopped, or declines; where it declines, or across places, the newer plans its own work only once the older has ended. Before its first act an activation waits once for newer input from the same person, started or held in a start wait, to be understood, and a takeover first waits for older activations' takeover decisions (ADR-0349 §§4, 5, 7–10). Every other clause stands. This replacement takes effect on ratification of ADR-0349. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.

## Context

**The owner's direction, 2026-10-21.**

- *"I can text it on one platform, finish my thought on another, and have someone else
  talking to it all at the same time. While it's doing research for me."*
- Activations should connect with others already in flight, for example by reacting when
  the user is typing.

`VISION.md` Principle 8 has the assistant behind every interface, where two people may be
talking to it, or one person on two devices, while long-running work continues: *"Each has
its own context, and none blocks the others."* The test the walk applied is Principle 3's:
what a trusted human assistant would do. Such an assistant does one thing at a time in one
conversation and folds in "oh, and also…" until it actually does something. It can be on
the phone and answering a text at once. It waits while it sees you are still typing.

**What the code does today, at `e8e39388`.**

- Each admitted input is its own task (`Engine._activation_task`), with its own
  `ActivationState` and its own controller pass. Nothing serializes activations across
  places. The hub chat's conversations and the line's chat already run side by side.
- Within one place, one activation runs at a time (ADR-0292 §11:5).
  - The hub chat's `ChatReader` keeps one read per conversation (ADR-0293 §6:2–§6:3).
  - The line's `TelegramReader` asks Telegram for nothing while an activation from its chat
    runs (ADR-0323 §5:5, §5:7).
  - A message that arrives meanwhile waits, and is taken in, with everything else waiting,
    when the running activation ends.
- **A correction a second after "book Riverside" therefore waits** until the first activation
  has asked its question for the wrong day. The next activation then corrects it.
- **The shared writers already serialize or detect conflicts.**
  - The observer is memory's one writer (ADR-0329).
  - The story-links stage writes under one in-process lock.
  - A story summary's write is refused as `summary_moved_on` when another write landed
    first.
  - The spend ceiling reserves inside one process (ADR-0194 §3).
- **Nothing on another place is visible to understanding.** ADR-0292 §10:4 shows a running
  activation beside its own place's window. Under one at a time per place there is never
  another one there.
- **Telegram gives a bot no event when the user is typing.** The Bot API's `Update` object
  (Bot API 10.3, 2026-08-24) carries no user chat action. `sendChatAction` sets only the
  bot's own status, *"when you need to tell the user that something is happening on the
  bot's side"*. The line renews it every `TYPING_RENEWAL` (ADR-0323 §6:8). So the hub can
  know you are typing only on the hub chat, whose page is ours.

**The walk's answers this decision converts** (#3257, the walk record):

1. One activation at a time within a place, with joining. ADR-0292 §11:1's
   every-message-its-own-activation stays the direction across places only.
2. The join window closes when acting commits to its first call that is not a pure read, or
   to its message.
3. The line takes `/stop`, as a command typed directly in the person's own chat: never a
   forwarded one, and never text that merely mentions it.
4. Composing extends only the start wait.
9. In a shared place, one activation runs at a time across authors, and only the same
   author's input joins. This is revisited with the household design.

## Decision

We will keep activations side by side across places and one at a time within a place. A
new input from the same author joins the running activation on its place until that
activation commits to its first act. The same person's other places see the activation
running, and can take it over before it acts. Each messaging place waits a moment before it
starts. On the hub chat the person's typing extends that wait. On the line, `/stop` stops
the running activation.

### 1. Status, scope and delivery

> **Normative.** This document remains `Proposed` until the reviews `CONTRIBUTING.md` →
> "Finishing an ADR PR" requires have returned green on one tree and the authorization to
> ratify stands. An assigned number or a green review alone does not change its status.

> **Normative.** No lane implements this decision before it merges `Accepted`.

> **Normative.** The implementation ships as separate pull requests in this order.
>
> 1. **`core`, `wire`, `testing`, `memory` and `tools`, permitted expressly here as one
>    unit.** §7's types, §6's settings, `AssistantEngine.composing` with its wire method,
>    its canonical fake and its conformance case, §5:11's row, the `PROTOCOL_VERSION`
>    advance, the episode store's upgrade under ADR-0326 §4:1–§4:2 for §7's record field,
>    `TelegramIntakeRecord.claim_reply`'s contract widened to a stop command (§8:6), and
>    `TelegramMessage.command` (§7:9) with its parsing in `tools/egress.py`, the Telegram
>    fake's and the client's conformance cases.
> 2. **`orchestration`, the activation:** §3's rules, the join's entry point and the
>    commitment step, §4's visibility and takeover, and the record.
> 3. **`orchestration`, the readers:** §2's per-place rule as the kinds declare it, §3's
>    joining and §5's waits in `ChatReader` and `TelegramReader`, and §8's `/stop`.
> 4. **`interfaces`:** §5:10's gateway route and the hub chat page's sender.
>
> Step 2 depends on step 1, step 3 on step 2, and step 4 on step 1.

> **Normative.** The tests of the step that builds each include these cases:
> - a stop while understanding runs, then a message, then the stage's end: the message
>   joins nothing, waits, and is taken in when the stopped activation ends;
> - a full page of waiting updates on the line, then `/stop`: it is acted on once a poll
>   returns it (§8:4);
> - two messages on the line whose text is `/stop` and which differ only in the
>   `bot_command` entity: one is a stop and the other a message;
> - two takeovers in one pass, one per understanding version, and a takeover refused at a
>   `join_limit` of 0 and at an exhausted one.

### 2. Side by side, and one at a time within a place

> **Normative.** Each activation has its own context: its own `ActivationState`, its own
> window and its own episode. No activation reads or writes another's state, except as §3
> and §4 state.

> **Normative.** Activations on different places run side by side, as do activations whose
> inputs have different authors.

> **Normative.** A kind declares whether each of its places runs one activation at a time.
> The conversation kind and the line declare that they do. On such a place, an activation
> is admitted only where none started from that place is running.

> **Normative.** On a place that runs one activation at a time, an input that arrives while
> one runs joins it where §3 allows. Otherwise it waits, is never refused, and is taken in,
> with everything else waiting, when the running activation ends (as ADR-0293 §6:3 and
> ADR-0323 §5:5 take it in).

> **Normative.** That holds across authors. Where a place's inputs may have more than one
> author, one activation still runs at a time on it, and only an input from the running
> activation's author can join.

> **Normative.** Shared state changes only through the writers that own it. Memory changes
> only through the observer (ADR-0329), stories only through the story store's operations,
> and effects only through acting's claims and records (ADR-0306 §5). No activation is a
> writer of another's.

ADR-0292 §11:1's end state, in which every message starts its own activation, stays the
direction **across** places. Within a place, the walk chose joining (answer 1). Long work
leaves the place as background work, which a later decision designs, so one at a time
within a place costs little.

### 3. Joining

**The boundary.** An activation folds in new input until it commits to something it cannot
take back.

> **Normative.** A **pure read** is a call whose capability declares `CapabilityEffect.NONE`
> and does not leave the hub.

> **Normative.** An activation has **committed** once acting has committed to its first
> call that is not a pure read, or to the round's message.

So a write to the hub's own records commits it, even one safe to repeat that gets no effect
record (`gets_effect_record` in `orchestration/acting.py`), such as noting on a story. A
call that leaves the hub, such as a web search, commits it, as does writing a reply or a
question into the place.

> **Normative.** A new input on a place that runs one activation at a time joins the
> activation running there where all of these hold:
> - the activation has not committed;
> - the activation's stop mark (ADR-0297) is unset;
> - the input's author is the running activation's input's author, established in the same
>   way, and the input carries the same authority (ADR-0292 §5:5) and the same origin
>   (ADR-0284 §2:2);
> - no earlier input on the place is waiting;
> - the activation has taken fewer joins than `join_limit` (§6:5).

> **Normative.** An input that does not join waits under §2:4.

A forward on the line, whose author is claimed (ADR-0323 §4:10), therefore never joins a
user's activation. A user's message never joins one a forward started. Because no input
joins past one that is waiting, the place's messages are understood in the order they
arrived. A message sent after a stop joins nothing: it waits, and is taken in when the
stopped activation ends, so the stop holds none back (ADR-0295 §3:6). An input that joined
before the stop is the stopped activation's input, as its trigger is.

**The commitment step.**

> **Normative.** Before acting dispatches any call of a round that is not a pure read, or
> the round's message, it checks for joined input that the understanding the round was
> planned from does not cover. Where there is none, it marks the activation committed.
> The check and the mark are one step with no await between, on the hub's one event loop.

> **Normative.** A join is taken only where the activation's committed mark and its stop
> mark are both unset, in one step with no await between that check and appending the
> input to the activation's state.

> **Normative.** Where the commitment step finds joined input not covered, acting
> dispatches none of the round's calls and not its message, by any path. Its acting
> decision for the round is present and records that a join set the round aside.

> **Normative.** A call or message dispatched before the join finishes, as everything
> claimed finishes (ADR-0306 §5:2).

The step sits before every claim path: an effect record's claim (ADR-0306 §5:4), an
invocation's (ADR-0306 §5:7) and a write to own records. So it changes neither the plan
store's claim nor the invocation ledger, and nothing committed is overtaken by a join.

**What a join makes due again.** The joined input is input no understanding covers yet, so
the rules start it over from understanding and planning, and from nothing else. The rules
below read the latest understanding version rather than the pass, which is ADR-0280 §4:5's
own principle: rules read decisions, not history.

> **Normative.** `not_understood` answers where understanding is wired and no understanding
> decision covers every input the activation holds. ADR-0280 §4:6's guard is scoped to the
> number of inputs the activation holds, so understanding runs at most once for each.

> **Normative.** Understanding, run again, reads the activation's whole input, the trigger's
> messages and every joined one, each kept apart and dated. It records a new version
> (ADR-0276 §7:3).

> **Normative.** A join makes neither recall's second run (ADR-0308 §2:9), nor recall's
> digest (ADR-0308 §4:4–§4:6), nor the story-links decision (ADR-0300 §6:10) due again.
> Each runs at most once on the pass, as its row states, and reads the understanding
> version that is latest when it runs.

So the record's single slots stand as they are: `recall_second_run` takes its value once
(ADR-0308 §7), and a field that carries a value keeps it (ADR-0286 §3:3). Each of the
three that has not yet run when a join arrives reads the version that covers it, since
`not_understood` sits above their rows. Where one has already run, the joined input's
new matter gets nothing from it on that pass, whether a second recall run, a digest of
its own or story links. Planning for the new version is shown what the pass already recalled
and digested. §9 names the measurement that would reopen it.

> **Normative.** Planning starts over for each understanding version. `first_round_due`
> answers where no round has been planned from the latest version. `round_due` and
> `round_limit_reached` count the rounds planned from the latest version.

> **Normative.** Rounds planned from an earlier version stay in the record, and their
> results stay on the episode for the new rounds.

> **Normative.** A join does not extend the activation's deadline.

`join_limit` bounds the restarts, the deadline bounds the pass, and the round limit bounds
each version's rounds.

**Withdrawing.**

> **Normative.** Before an activation commits, a typed "wait, not that" or "stop" joins like
> any message, and understanding reads it.

After it has committed, the hub chat's stop control stops the activation at once (ADR-0295),
and so does the line's `/stop` (§8). Typed text is still a message and never a stop
(ADR-0295 §1:5), so it waits.

**The record.**

> **Normative.** The episode records each joined input as a `JoinedInput` on
> `EpisodeProcessingRecord.joined`, in the order it joined: when it joined, its messages
> kept apart and dated, and the place it came from.

> **Normative.** A `JoinedInput` that a takeover brought (§4) also names the activation it
> was taken from.

> **Normative.** The readers mark a joined message as taken in by the activation it joined,
> as at admission (ADR-0293 §6:8, ADR-0323 §5:8).

### 4. A person's places see each other's running work

> **Normative.** Understanding is shown, beside the window, every activation that is
> running for the same person on another of that person's places: its input and whether
> it has committed. The same person means that both inputs' authors are established as that
> person.

> **Normative.** A running activation on another place is shown only where
> `admitted_to_understanding` (in `orchestration/disclosure.py`, ADR-0276 §4) would admit an
> episode of that place to this pass.

> **Normative.** A running activation is never shown to an input whose author is another
> person, and never one whose author is not established.

> **Normative.** Understanding's reply may name one shown running activation that this input
> continues: completes, corrects or adds to. That is `continues`, by its label (§7:3).

> **Normative.** `ControllerStage` gains `takeover`, and `ControllerRule` gains
> `takeover_undecided`. `takeover_undecided` answers where the latest understanding names an
> activation it continues and there is no takeover decision for that version, and makes
> `takeover` due. Its row sits immediately after `story_links_unrecorded`. ADR-0280 §4:6's
> guard is scoped to the understanding version for `takeover`, so the stage runs at most
> once for each.

> **Normative.** The takeover stage, in one step with no await between, reads whether the
> named activation is still running, uncommitted and without its stop mark, and whether its
> input carries the same authority and the same origin as this activation's (as §3:3
> requires of a join), and whether this activation has taken fewer joins than
> `join_limit` (§6:5).
> - Where all of these hold, the stage sets that activation's stop mark (ADR-0297) and its
>   committed mark, so it can neither commit nor take a join.
>   A takeover counts as one of this activation's joins. It appends that activation's input to
>   this one as a `JoinedInput` naming it, and records the decision *taken over*.
> - Otherwise it records *not taken*.

> **Normative.** A taken-over activation is stopped under ADR-0295 §5:1 and carries every
> guarantee of ADR-0295 §§2–4. It writes nothing new into its place.

> **Normative.** Where the named activation has committed, been stopped or ended, nothing is
> stopped or taken over. This activation goes on, and sees in what it was shown how far
> the older got.

A takeover is §3's join across places. The older one's input becomes the newer one's
joined input, so `not_understood` answers again, and understanding reads both messages
together as its own input, with the authority each carries. This is ADR-0292 §11:2–§11:3's
one mechanism for merging and taking over, drawn at the same commitment line as a join.
Which place hears where the matter went is #2588's.

### 5. The short wait, and composing

**The start wait.** People text in bursts. A messaging place waits a moment after an input,
before it starts, and takes in together what arrived meanwhile.

> **Normative.** On the hub chat, when a message arrives in a conversation where nothing is
> running, the reader takes the waiting messages in once `chat_start_wait` (§6:1) has
> passed since the latest of them and no composing signal is live for that conversation.

> **Normative.** That wait ends no later than `chat_composing_cap` (§6:3) after the first
> waiting message, whatever the composing signal says.

> **Normative.** On the line, when a message arrives in its chat where nothing is running,
> the reader takes in what has arrived once `telegram_start_wait` (§6:4) has passed since
> that first message.

The line's wait is fixed because Telegram tells a bot nothing about typing (Context).
Anything that arrives after the wait joins the running activation under §3, until it
commits.

> **Normative.** The start wait applies only where no activation started from the place is
> running. While one runs, an input joins or waits under §3.

**Composing, on the hub chat.**

> **Normative.** The hub chat page sends a composing signal for a conversation while the
> person types into that conversation's composer, no more often than once a second.

> **Normative.** A composing signal is live for `chat_composing_lapse` (§6:2) after it
> arrives.

> **Normative.** A composing signal only extends a start wait already running for its
> conversation (§5:1). It starts no read and no wait, and does nothing where no wait is
> running.

> **Normative.** A composing signal is not input. It starts no activation, joins nothing,
> and holds no act. It is never written into the transcript, any store or any episode.

The walk kept composing to the start wait (answer 4). A reply that crosses a follow-up does
no harm, because the next activation sees it.

> **Normative.** `AssistantEngine` gains `composing(conversation_id)`, an act in the medium
> that writes nothing into it. It hands the signal to the chat's reader and answers nothing.

> **Normative.** The wire carries `composing` as a method of the promoted surface. The
> gateway serves it at `POST /chat/composing`, naming the conversation in its body, as it
> serves `write_message` at `/chat/message/write`.

> **Normative.** ADR-0298 §5:1's table classifies `composing` in its **Writing** row: the
> requesting device must be the named conversation's end for writing.

### 6. The numbers

> **Normative.** `Settings` gains `chat_start_wait`, a duration, default **1.5 seconds**,
> strictly positive.

> **Normative.** `Settings` gains `chat_composing_lapse`, a duration, default **3 seconds**,
> strictly positive.

> **Normative.** `Settings` gains `chat_composing_cap`, a duration, default **10 seconds**,
> no shorter than `chat_start_wait` or `chat_composing_lapse`.

> **Normative.** `Settings` gains `telegram_start_wait`, a duration, default **2 seconds**,
> strictly positive.

> **Normative.** `Settings` gains `join_limit`, an integer, default **3**, at least 0. 0
> turns joining off, and takeover with it (§4:6).

> **Normative.** [#2589](https://github.com/leonapivato/ai-assistant/issues/2589) tunes these
> defaults by measurement, without a new decision.

The starting values are guesses, to be measured. The episodes already date every message
(ADR-0323 §5:4, and the hub chat's transcript). The gaps between consecutive messages that
no reply separated give the burst distribution, and the wait is a percentile of it.

### 7. The code it binds

> **Normative.** `core/types.py` gains `JoinedInput`, frozen with `extra="forbid"`, with
> exactly these fields:
> - `joined_at: UtcInstant`;
> - `channel: ChannelIdentity`, the place it came from;
> - `messages: tuple[RecordedInputMessage, ...]`, non-empty;
> - `taken_over_from: Identifier | None = None`, the activation a takeover stopped.

> **Normative.** `EpisodeProcessingRecord` gains `joined: tuple[JoinedInput, ...] = ()`.

> **Normative.** `ProposedActivationUnderstanding` gains `continues: EncodableText | None =
> None`. It is the label of a running activation shown beside the window, under a new label
> kind, `R`, of ADR-0276 §3:3's scheme.

> **Normative.** `ActivationUnderstanding` gains `continues: Identifier | None = None`, the
> activation that label resolved to. A label that resolves to no shown activation is dropped
> as a grounding defect (ADR-0276 §6), never a parse failure.

> **Normative.** `ControllerStage` gains `takeover`, and `ControllerRule` gains
> `takeover_undecided` (§4:5), under ADR-0280 §4:8.

> **Normative.** The working set gains, per understanding version, the takeover decision.
> Per round, acting's decision may record that a join set the round aside (§3:7).

> **Normative.** Each change that alters a shape the wire carries advances `PROTOCOL_VERSION`
> in that change, under ADR-0124 §9:2, with the wire surface and type closure, and the memory
> and engine conformance suites, extended to the shape.

> **Normative.** §7:2's field is a schema change under ADR-0326 §2:3, and ships ADR-0326
> §4:1–§4:2's upgrade and its test in the same pull request.

> **Normative.** `TelegramMessage` gains `command: EncodableText | None = None`: the part of
> the message's text that a `bot_command` entity starting at its first character covers, by
> the entity's offset and length; `None` where the message has no such entity. An
> `entities` member not in the shape the Bot API documents leaves `command` `None` and the
> rest of the message read as it is. It never drops the message and never makes one a
> command.

> **Normative.** The client reads `command` in both of its modes (ADR-0330 §3). A relay
> hands a message's `entities` unaltered, among the members ADR-0330 §4:3 names.

A line whose relay withheld the member would read every `/stop` as an ordinary message,
which is the safe side of the predicate (§8:1).

### 8. The line's `/stop`

> **Normative.** On the line, a message is a stop command where all of these hold:
> - it is the user's, established, under ADR-0323 §4:1: from the configured account, in its
>   private chat with the bot, and not forwarded;
> - its whole text is `/stop`;
> - its `command` (§7:9) is `/stop`: Telegram marked that text as a `bot_command` entity
>   starting at its first character.

> **Normative.** Nothing else is a stop. A forward, a reply quoting `/stop`, `/stop@`
> followed by any name, `/stop` without the entity, and text that mentions `/stop` anywhere
> but as its whole text are messages like any other.

The addressed form `/stop@name` is for group chats, where several bots may read one chat.
In a private chat Telegram's clients send the bare command, and the line reads no group
(ADR-0323 §5:2), so the predicate needs no bot identity.

> **Normative.** A stop command is not input. It starts no activation and joins none.

> **Normative.** The reader acts on a stop command as soon as a poll returns it. Where an
> activation started from the line's chat is running, it stops that activation as
> `AssistantEngine.stop_activation` does (ADR-0295, ADR-0297). A poll returns it only while
> it is within the one page of updates Telegram returns past the confirmed offset (§8:7).
> Behind a full page of updates left waiting, it waits with them, and the reader acts on it
> when a poll first returns it.

> **Normative.** The line answers a stop command with one fixed line by rule, from the
> writer and never from the activation: "Stopped." where it stopped one, and "Nothing was
> running." where none ran.

> **Normative.** The reader records a stop command in the intake record as an update it
> answered, as it records a non-text message it answered (ADR-0323 §5:8,
> `TelegramIntakeRecord.claim_reply`), before it acts on it. A poll that returns it again,
> as one does while the updates before it wait unconfirmed, neither stops anything nor
> answers it again (ADR-0323 §5:9).

> **Normative.** While an activation started from the line's chat runs, the reader keeps
> polling, so that it sees joins and stop commands within the page Telegram returns. An
> update it does not take in is left unconfirmed, so it waits in Telegram (ADR-0323 §5:6),
> and a poll returns at most one page of updates past the confirmed offset.

> **Normative.** The reader paces those polls so that updates left unconfirmed never make it
> poll in a loop. How it paces them is the implementation's.

A stop command typed in the person's own chat is a structured act, marked by Telegram's
own entity and read by rule, never words a model interprets. It is the line's equivalent
of the hub chat's stop control. Telegram has no current state to show *stopped* in, so the
fixed line plays that part, as ADR-0323 §6:10's line does after a restart.

### 9. What this decision does not decide

| Not decided here | Where it goes |
| --- | --- |
| **Modes:** a phase path chosen per activation (#3257's pick 4, the walk's answers 5 to 7) | Its own decision, after this one merges, since both amend ADR-0280's working set and record |
| **Background work** and its report back (#3257's pick 5, the walk's answers 8 and 10) | The timers and proactivity milestone |
| Whether a typed "scratch that" can halt an activation that has committed | ADR-0292 §11:2's end state across places; #2515 |
| The lock and recheck on what is acted on, for two places' activations acting on one thing | [#2586](https://github.com/leonapivato/ai-assistant/issues/2586) |
| Write-ahead and unknown outcomes around a stop during an act | [#2584](https://github.com/leonapivato/ai-assistant/issues/2584) |
| What a taken-over place hears about where the matter went | [#2588](https://github.com/leonapivato/ai-assistant/issues/2588) |
| The audience at delivery when a reply leaves on another channel | [#2590](https://github.com/leonapivato/ai-assistant/issues/2590) |
| Showing the person's composing to their other devices | Nothing needs it yet |
| Shared places with several authors | The household design (the walk's answer 9) |
| The values of §6 | #2589 (§6:6) |
| A durable store of pending input, so the line can confirm the updates waiting behind a running activation and see a `/stop` past a full page of them | Its own decision, since it amends ADR-0323 §5:8's *holding no message text*; [#3267](https://github.com/leonapivato/ai-assistant/issues/3267) |
| Recall again per understanding version, if measurement shows joined inputs missing memory context (§3:11) | #2589's measurements first, then its own decision, with a per-version recall history and its upgrade under ADR-0326; [#3268](https://github.com/leonapivato/ai-assistant/issues/3268) |

> **Normative.** Each item the table names takes a decision of its own before any lane
> builds it.

### 10. Relationship to earlier decisions

Superseded in part; every clause the middle column does not name stands:

| Earlier decision | What it replaces | By |
| --- | --- | --- |
| ADR-0280 | §4:3's row `not_understood`, as ADR-0309 §3:1 keeps it: it answers where no understanding decision covers every input held; §4:6's loop guard, for understanding: once per input held, and for `takeover`: once per understanding version; §7:1's record, in the addition alone: `joined` | §3:9, §3:16, §4:5, §7:2 |
| ADR-0276 | §2:1's `ProposedActivationUnderstanding` and `ActivationUnderstanding` field sets, in the additions alone: `continues`; §3:3's label scheme, in the addition alone: the kind `R` | §7:3, §7:4 |
| ADR-0286 | §3:3, in the addition alone: a revision may extend `joined`; §3:8, in the addition alone: `joined` is a field of the record, not a stage's result | §3:16, §7:2 |
| ADR-0292 | §6:10, in the addition alone: an input that joins a running activation is part of its input; §10:4, in the addition alone: the same person's running activations on their other places are visible beside the window; §11:1, within a place: one activation at a time with joining, the end state staying the direction across places; §11:2's *the older is stopped*, across places, only where the older has not committed; §11:5, whole: its interim becomes §2's rule; §11:6, whole: the change reaches the controller and the readers; §12:5 and §12:6, each in the addition alone: the line's `/stop` | §2:3–§2:5, §3:3, §4:1, §4:6–§4:8, §8:1 |
| ADR-0293 | §6:1, in the addition alone: the reader waits before taking in; §6:2 and §6:3: a message joins where §3 allows, and otherwise waits; §6:8, in the addition alone: a message is marked taken in when it joins | §2:4, §3:3, §3:18, §5:1 |
| ADR-0295 | §1:4 and §1:5, each in the addition alone: the line's `/stop` is a stop; §3:3, in the addition alone: the line's fixed answer to it | §8:1, §8:4, §8:5 |
| ADR-0298 | §5:1's table, in the addition alone: `composing` in the Writing row | §5:11 |
| ADR-0306 | §5:1, in the addition alone: a round set aside by a join runs none of its calls | §3:5, §3:7 |
| ADR-0309 | §3:1's table, in the addition alone: the row `takeover_undecided`; and its rows `first_round_due`, `round_limit_reached` and `round_due`, read per understanding version | §3:12, §4:5 |
| ADR-0323 | §5:1, in the addition alone: a stop command is not input; §5:8, in the addition alone: a stop command is recorded as answered; §5:5: a message joins where §3 allows, the start wait included; §5:7, whole: the reader polls while an activation runs; §6:11, in the addition alone: the line's fixed answer to `/stop`; §8:1, whole: the line takes `/stop` | §3:3, §5:3, §8:1–§8:8 |
| ADR-0330 | §4:3, in the addition alone: a message's `entities` are among the members a relay hands unaltered | §7:10 |

Read through and not superseded:

| Earlier decision | What changes |
| --- | --- |
| ADR-0276 §7:3, §7:4 | Nothing: a join adds a version, and `join_limit`'s default keeps an activation inside the version bound |
| ADR-0295 §1:5, ADR-0292 §12:6 | Nothing for the hub chat: typed text is a message and never a stop |
| ADR-0297 | Nothing: the stop mark is read as it is, a join and a takeover read it, and a takeover sets it |
| ADR-0306 §5:2–§5:13 | Nothing: everything claimed finishes, and the commitment step sits before every claim |
| ADR-0300 §6:10–§6:11, ADR-0308 §2:9–§2:10, §4:4–§4:6 and §7 | Nothing: the story-links decision, recall's second run and its digest stay once per pass, in their single slots (§3:11) |
| ADR-0307 §8:6 | Nothing: planning's first round for a version follows that version's understanding, and recall's second run, which ran once on the pass |
| ADR-0323 §4 | Nothing: the line's authors are as it establishes them, and §3:3 joins only the same author and authority |
| ADR-0329 | Nothing: the observer stays memory's one writer |

> **Normative.** This numbered draft records its replacements on the status lines and in a
> dated header note of ADR-0276, ADR-0280, ADR-0286, ADR-0292, ADR-0293, ADR-0295, ADR-0298,
> ADR-0306, ADR-0309, ADR-0323 and ADR-0330, atomically with this ADR under
> ADR-0070 and ADR-0082, preserving their ratified bodies. The replacements take effect on
> this ADR's ratification.

## Consequences

**What becomes possible.**

- A correction a second after a request changes the first answer instead of chasing it.
- A burst of messages gets one reply.
- On the hub chat, the assistant waits while you type.
- A thought begun on Telegram and finished on the web is one activation, provided the first
  had not yet acted.
- `/stop` on the line works while work is running, unless a full page of messages is
  waiting before it.
- Every join and takeover is on the episode, so the viewer shows why an answer covered
  two messages.

**What it costs.**

- A `Protocol` member and a wire method.
- Fields in `core/types.py` and a schema change to the episode store, with its upgrade.
- Five settings.
- A second understanding call for each join, and the planning rounds that follow it.
- A joined input that arrives after the story links, recall's second run or its digest
  has run gets nothing from that stage on that pass (§3:11).
- On the line, a `/stop` behind a full page of waiting messages waits with them (§8:4).
- A start wait of a second or two before any reply on a messaging place.
- The line polls while an activation runs, which ADR-0323 had it avoid.
- A taken-over activation's messages appear in two episodes, the stopped one and the one
  that took it over. The latter's `JoinedInput` names the former, so a reader of both can
  tell.

**What it deliberately leaves.** Everything §9 names, modes and background work first.

**What would reopen it.**

- The household design, for shared places with several authors.
- A need for a typed message to halt committed work.
- #2589's measurements, if no wait helps.

## Alternatives considered

- **ADR-0292 §11:1's end state within a place too**, where every message starts its own
  activation and understanding judges how each relates to the running ones. Rejected by the
  walk (answer 1). Every message pays a judgment of its relation to running work, and it
  needs the lock key, waiting before an action and a stopped activation never writing all
  in place first. A burst would also produce understandings that a takeover throws away.
- **No joining, today's interim.** Rejected: a correction waits until the first activation
  has acted on the uncorrected request.
- **Joining by restart:** stop the running activation and start a fresh one over both
  inputs. Rejected within a place: it costs a second episode and an ending the user never
  asked for, for one exchange, and it needs the first message un-taken-in. It is §4's
  mechanism across places, where the two inputs are on different places.
- **The join window closing as soon as acting begins.** Rejected (answer 2): looking
  something up is not acting.
- **Composing also holding the first act.** Rejected (answer 4): a reply that crosses a
  follow-up does no harm.
- **No start wait, joining only.** Rejected: most bursts would pay a second understanding,
  and a quick reply can commit inside the burst and answer half a thought.
- **A typed "stop" on the line as the stop.** Rejected: ADR-0292 §12:6 keeps words from
  becoming commands. `/stop` is Telegram's own structured command, marked by its entity.
