# 293. The hub's chat is a hosted medium, and a conversation keeps its own transcript

- Status: Proposed
- Date: 2026-10-04
- Scope: [#2578](https://github.com/leonapivato/ai-assistant/issues/2578), the channel redesign: the conversation channel, the first channel ADR-0292's model is applied to.
- Authorization: the owner accepted proposal #2680 on 2026-10-04, at `f21aeb7b`, after walking it through section by section the same day, and the dispatcher assigned 0293. This ADR is that proposal converted under `docs/proposals/README.md` → "When it is decided".
- **Partially supersedes** [ADR-0274](0274-channel-input-and-reply-contract.md) — **one scope.** **§2–§6, in so far as they govern a typed text input to the conversation and its reply**: such an input is a message written into a conversation as an act in the medium (§4 below); it names no channel, supplies no history and no replied-to item, and its reply is not returned on the request but written into a conversation by the chat's writer (§6 below). A replied-to entry survives as a message's reference into the transcript (§4 below). The spoken combination, informational events and every other clause stand. These mechanisms keep working until the first build replaces them (§11 below, ADR-0292 §13:1).
- **Partially supersedes** [ADR-0276](0276-an-activation-is-understood-before-it-is-associated-and-the-understanding-is-retained-with-its-episode.md) — **one scope.** **§3:1's and §3:2's conversation-channel window, for every input but the quarantined spoken path's**: the conversation's window is its recent transcript, brought in by the chat's reader with the new input, its size declared by the kind (§6, §7 below); §3:2's *no per-channel history table* does not reach the transcript, which is the hosted medium's content (ADR-0292 §3:3). The quarantined spoken path keeps both clauses as they stand. Every other clause stands.
- **Partially supersedes** [ADR-0283](0283-a-channels-history-is-its-episodes-and-the-turn-index-is-retired.md) — **three scopes.** **§4:1, for every read but the quarantined spoken path's**: a conversation's history is its transcript (§5 below). **§8:1, in what deleting a conversation removes**: its transcript, and none of the episodes on its place; deleting those episodes is forgetting the conversation, a command that leaves the conversation and its transcript (§2 below). **§8:2's condition**: reclaim also spares a conversation that holds a message, since a transcript is kept until the user deletes it (§5 below). Every other clause stands.
- **Partially supersedes** [ADR-0022](0022-the-closed-learning-loop.md) — **one scope.** **§1's `learn`, as the route by which the user's feedback reaches the assistant**: the user corrects the assistant by a message replying to the message it corrects (§4 below), which the chat's reader brings in as a push. `learn` retires when the first build replaces it (§11 below, ADR-0292 §13:1). Every other clause stands.
- **Partially supersedes** [ADR-0078](0078-a-deferred-memory-decision-is-a-durable-question.md) — **one scope, which takes effect when built.** **§8's answering call, `answer(question_id, *, accept)`, as the route by which the user answers a question**: the user answers by a message naming the question and, for a button, the option (§4, §6 below). Until question messages and their answers are built, `answer` keeps working exactly as ADR-0078 decides it (ADR-0292 §13:1). What an answer authorizes, and that it is used once, are not decided here, and every other clause stands.

## Context

**The question.** How does the most basic channel for talking with the user work, text
in and text out, under the channel model ADR-0292 decided?

ADR-0292 fixes the general model: spokes, channels, places, hosted media, authors, push
and pull, audience, window, activations side by side, and what retires. This decision
applies it to one channel, the hub's chat: what the chat is, what its conversations
keep, how a message gets in and out, and what is built first. How a device's connection
carries it in the end is the device session's, and stopping an activation is its own
decision.

The owner walked the proposal (#2680) through section by section on 2026-10-04 and
ruled on these points, each recorded below as the owner's ruling of that date: what
belongs to the conversation, the channel and the assistant (§1); that no single
operation deletes and forgets, and that forgetting reaches the episodes alone (§2); "my
devices" as one set kept on the chat space (§3); the device-chosen message id, and a
reply as the replacement for `learn` (§4); every transcript entry being a message, that
forgetting does not reach the transcript, that deleting a message deletes it alone, and
how devices stay in step (§5); the reader's bookkeeping, that planning chooses the
conversation written into, and that the assistant may start a conversation (§6); the
current state and how the last activation ended (§8); a restart writing nothing (§9);
and the first build on today's wire (§11).

The owner's direction was read, as of the proposal, from the wiki pages
[Channels](https://github.com/leonapivato/ai-assistant/wiki/Channels),
[Channel window](https://github.com/leonapivato/ai-assistant/wiki/Channel-window) and
[Episodes](https://github.com/leonapivato/ai-assistant/wiki/Episodes), at wiki revision
[`b95617b`](https://github.com/leonapivato/ai-assistant/wiki/Channels/b95617b24abc2f1bbef5997ecf4b36eb6056bbc6).
ADR-0292 replaces much of what the Channels pages describe. Where this ADR and those
pages differ, this ADR governs.

**The ADRs this touches**, as they stand on `main`:

| ADR | What it decides today | How this decision relates |
| --- | --- | --- |
| ADR-0274 §2–§6 | A `ChannelInput` names its channel (`conversation`, the conversation id as instance) and the reply it accepts; the reply returns on the request; the caller may supply history and a replied-to item. | Partially superseded for a typed text input to the conversation: a message is an act in the hosted chat space, names no channel and supplies no history; the assistant's output is a message written into a conversation. "Replies to entry X" stays, as a reference into the transcript. |
| ADR-0276 §3:1–§3:2 | The conversation's window is its tail as read from episodes; *"no per-channel history table"*. | Partially superseded for the conversation: its window is its recent transcript, brought in by the chat's reader (ADR-0292 §10:1). The quarantined spoken path keeps them. |
| ADR-0283 §4:1, §8:1, §8:2 | A conversation's history is the episodes on its channel; deleting a conversation destroys them; reclaim drops an idle conversation whose episodes are gone. | Partially superseded: its history is its transcript; deleting a conversation deletes the transcript; forgetting is a command of its own (§2); reclaim spares a conversation that holds a message. |
| ADR-0283 §1, as ADR-0292 reads it | Episodes indexed by channel and place. | Applied: the chat's episodes are indexed by (the chat, the conversation). |
| ADR-0022 §1 | `learn`, feedback by its own call. | Partially superseded: a reply is its replacement (§4). |
| ADR-0078 §8 | `answer`, a question answered by id. | Partially superseded when question messages and their answers are built (§6). |
| ADR-0074 | A conversation is a first-class entity; the store mints its id. | Kept: a conversation is a place in the chat space, with that id. |
| ADR-0286 §2, §7 | An episode is written at admission and frozen at its end; a restart closes an open episode as interrupted. | Kept. A restart writes nothing into the conversation (§9). |
| ADR-0280 §4, row 11 | `reply_owed`: a conversation turn with no composed reply makes `compose` due. | Not amended. The kind's description says it expects a reply (§7), and the row's rewording waits for the milestone where an event reaches a reply ([#2598](https://github.com/leonapivato/ai-assistant/issues/2598) item 3). |
| ADR-0170 | A reply is not a tool; the turn composes its answer. | Not decided here ([#2593](https://github.com/leonapivato/ai-assistant/issues/2593)). The chat's writer adds a message, and until the phases call it today's compose stage does (§10). |

Unchanged: the spoken path, quarantined until voice returns as its own channels;
informational events (`receive`), until ADR-0292's per-source channels replace them;
the notification route, until the assistant can start conversations (§6, §10); and every
other query and command of the engine surface.

**What exists.** The conversation is carried by `converse` and `converse_streaming`, and
by `receive` and `receive_streaming`'s text conversational combination, with the reply
returned on the request (ADR-0274). A conversation is created by the first message sent
without an id. Its history and window are read from its episodes (ADR-0283 §4:1,
ADR-0276 §3:1), and `forget_conversation` destroys the conversation together with the
episodes on it (ADR-0283 §8:1). Feedback is `learn`, and a parked question is answered
by `answer`. Nothing keeps the conversation's text apart from the episodes.

## Decision

We will make the hub's chat space a hosted medium in which each conversation is a
place keeping its own transcript of messages; a message gets in as the user's act in
that medium and reaches the assistant only through the chat's reader, and the assistant
answers by writing a message through the chat's writer.

> **Normative.** §§1–11 govern the conversation channel, its medium, its spokes and
> every route an implementation builds for it from this ADR on.

> **Normative.** Until the first build (§11) replaces them, the routes this ADR
> supersedes keep working as they do on `main` when it is ratified, and ADR-0078 §8's
> `answer` keeps working until question messages and their answers are built.

### 1. The chat

| | The chat |
| --- | --- |
| **Channel** | `conversation`, one, built in |
| **Medium** | The hub's chat space, a hosted medium |
| **Places** | Conversations, each with its ADR-0074 id |
| **Spokes** | In the hub: a reader (sensor) and a writer (actuator) |
| **Push** | A new message from the user starts an activation |
| **Pull** | Earlier messages, in any conversation |

> **Normative.** The conversation channel is one built-in channel, `conversation`,
> whose medium is the hub's chat space and whose places are conversations, each
> identified by its ADR-0074 id.

> **Normative.** The chat's spokes are in the hub: a reader, which is its sensor, and
> a writer, which is its actuator.

> **Normative.** A new message from the user is a push, and earlier messages, in any
> conversation, are a pull.

> **Normative.** The chat space exists whether or not any device is connected, and
> outlives every device.

> **Normative.** The chat space carries text only.

What belongs where, as the owner ruled it:

| Belongs to | What |
| --- | --- |
| **The conversation**, the medium | The transcript and its messages; message ids; *received*; deleting; which devices are its ends; the order, and the stream of changes to devices |
| **The chat channel and its spokes** | The reader noticing new messages and bringing in the window; the writer adding the assistant's messages; the reader's bookkeeping of what it has taken in |
| **The assistant** | Activations and episodes; "working…" and how the last activation ended; what it remembers and forgets |

> **Normative.** Each item of the table above is held by the party its row names, and
> by no other.

### 2. Conversations and what can be done with them

| Operation | Route (ADR-0292 §4) | What it does |
| --- | --- | --- |
| Start a conversation | Act in the medium | Creates an empty conversation, shown on "my devices" (§3) |
| Set "my devices"; choose a conversation's devices | Act in the medium | §3 |
| Write a message | Act in the medium | §4 |
| List conversations; read one after a cursor | Read of the medium | As `recent_conversations` and `conversation` today, plus the current state (§8) |
| Delete a message | Act in the medium | Deletes that message alone (§5) |
| Delete a conversation | Act in the medium | Deletes its transcript, and forgets nothing |
| Forget a conversation | Command | Forgets the episodes on that place, as `forget_conversation` does today, and leaves the transcript |

> **Normative.** Starting a conversation is an act in the medium that creates an empty
> conversation, shown on "my devices" (§3).

> **Normative.** A conversation is never created as a side effect of a message.

> **Normative.** Deleting a conversation is an act in the medium that deletes the
> conversation and its transcript, and forgets nothing.

> **Normative.** Forgetting a conversation is a command that forgets the episodes on
> that place, and leaves the conversation and its transcript as they were.

> **Normative.** Forgetting a conversation reaches the episodes on its place whether
> or not the conversation still stands in the medium.

> **Normative.** No single operation both deletes and forgets. An interface may offer
> the two side by side.

> **Normative.** Forgetting a conversation reaches its episodes alone.

Whether forgetting should also reach what was derived from what is forgotten is
memory's question ([#2683](https://github.com/leonapivato/ai-assistant/issues/2683)).
Who may start a conversation or change devices is the device session's.

### 3. Devices

Each device a conversation is shown on is the user's end of it (ADR-0292 §4).

> **Normative.** "My devices" is one set the user keeps on the chat space as a whole,
> and a new conversation is shown on every device in it.

> **Normative.** Adding a device to "my devices" is the user's statement that the
> device's screen is private, whatever the device.

> **Normative.** A conversation's devices can be changed from that default, and
> choosing a device for one conversation is the same statement, for that conversation.

A conversation kept off a shared tablet is such a change.

> **Normative.** The assistant has no action that adds a device, to "my devices" or to
> a conversation.

> **Normative.** A device may be a conversation's end for writing, for reading, or for
> both.

A watch may only read.

> **Normative.** A device carries a label it declares, such as "iPhone" or "laptop
> browser", which is shown to the user and grants nothing.

### 4. A message in

> **Normative.** A message is an act in the medium from one of the conversation's
> devices, and carries its text and a message id the device chose, unique per device.

> **Normative.** Sending is safe to repeat: a message sent again by the same device
> with the same id is the same message, recorded as one entry and starting one
> activation.

> **Normative.** A deleted message leaves a marker (§5), so a late repeat of it is
> still recognized and does not come back.

> **Normative.** Once the conversation has recorded a message, it answers the send
> with the message's position, which is *received*.

*Received* lets a device stop showing *sending*, and its absence tells the device to
send again. It means in the conversation, not yet understood (ADR-0292 §4:6).

> **Normative.** A message may name one earlier message it replies to.

A reply is also how the user corrects the assistant: "wrong campsite, I meant
Pinecrest", replying to the assistant's message, is how `learn` is replaced. This is
ADR-0292 §6:9's *feedback on an entry*: a new message replying to the entry it is
about.

> **Normative.** A message answering a question names the question and, for a button,
> the option (§6).

> **Normative.** A message over the size bound is refused, with the error on the send,
> and is not recorded.

> **Normative.** A message's author is the user, established, and it is sent as an
> instruction, so it can carry the user's authority (ADR-0292 §5:5).

### 5. The transcript

> **Normative.** Each conversation keeps a transcript, the ordered record of what was
> said in it, as a hosted medium's content under ADR-0292 §3.

> **Normative.** Every entry of a transcript is a message with exactly the properties
> the table below lists, and each property means what its row says.

| Property | Values | What depends on it |
| --- | --- | --- |
| **Author** | The user, or the assistant | Only the user's messages start activations and can carry authority |
| **Text** | | |
| **Replies to** | An earlier message, optional | Answering and correcting |
| **Options** | For a question, optional | Devices show them as buttons; an answer names one |
| **Cut off** | Yes or no; only the assistant's | A cut-off message is never read as a complete answer (§6) |
| **Message id, device** | The user's messages only | Safe resending; which device it came from |

A property exists only where something behaves differently because of it. The
*couldn't finish* message (§9) is an assistant message whose text is fixed rather than
composed.

> **Normative.** A transcript is kept until the user deletes it, a message or a whole
> conversation at a time, and is purged with the user's data (ADR-0292 §3:11).

> **Normative.** Reclaim never drops a conversation that holds a message.

> **Normative.** A transcript is not memory: an activation's episode still records what
> the assistant perceived and did, so a message's text is in both, and the two are
> never kept in step (ADR-0292 §3:4).

> **Normative.** Forgetting does not reach a transcript.

> **Normative.** An interface offering to forget a conversation says plainly that
> forgetting stops the assistant recalling it anywhere else, that the assistant still
> reads the conversation while the user keeps talking there, and that only deleting
> removes it (ADR-0292 §3:7).

> **Normative.** Deleting a message deletes it alone: a reply to it stays, and its
> reference names a deleted message, shown as such.

> **Normative.** The user can delete a message of either author, and the assistant
> deletes nothing (ADR-0292 §3:9).

**How devices stay in step.**

> **Normative.** Every change to the chat space gets a sequence number, increasing
> across all its conversations: a message added, a message deleted, a conversation
> started or deleted, a device added or removed.

> **Normative.** A device keeps one cursor for the chat space, and catching up is one
> request for every change after it.

> **Normative.** A deleted message leaves a marker, its id and that it was deleted,
> with no text, and devices remove the message on seeing the marker.

> **Normative.** A device far behind, or new, gets a snapshot of each conversation's
> recent messages, and loads older ones as the user scrolls back.

### 6. The assistant's side: reading and writing

> **Normative.** The reader notices new user messages and brings them in as a push,
> and the assistant's own messages never start an activation (ADR-0292 §6:8).

**One activation at a time per conversation, for now** (ADR-0292 §11:5's interim).

> **Normative.** A message written while an activation started from that conversation
> is running lands in the transcript at once and waits, and is never refused.

> **Normative.** When the activation ends, every message waiting in that conversation
> is taken in together as one input.

The transcript shows what was written and when, so the next activation can tell that a
message was written before the reply it follows. In the end state each message is
taken in at once and activations run side by side (ADR-0292 §11:1).

> **Normative.** The window is the conversation's recent transcript, brought in by the
> reader with the new input (ADR-0292 §10:1).

> **Normative.** Each message in the window keeps its author, so the window informs and
> never authorizes (ADR-0292 §10:3).

**The reader's bookkeeping**, as the owner ruled it.

> **Normative.** The reader records which messages it has taken in, and by which
> activation, holding no text.

> **Normative.** The bookkeeping is the reader's, not the conversation's: the
> conversation does not know whether the assistant has read it.

> **Normative.** A message is marked taken in when its activation is admitted.

> **Normative.** After a restart, messages an interrupted activation already took in
> are not taken in again, since it may have acted on them, and messages never taken in
> are taken in as usual.

**The writer** adds the assistant's messages: *send a message*.

> **Normative.** Planning chooses the conversation an output is written into (ADR-0292
> §7:2), and any activation may write, including one a timer started.

> **Normative.** The assistant may start a conversation, with its first message, when
> nothing existing fits, and that conversation is shown on "my devices".

"Your Friday booking moved" is such a message. This is how notifications become
messages (ADR-0292 §7:3).

> **Normative.** A message the writer sends is *sent* once the conversation has
> recorded it, whatever devices are showing the conversation, and devices get it live
> or when they catch up (ADR-0292 §7:4).

> **Normative.** An activation may write several messages.

"Looking into it", then the answer, is such a pair.

> **Normative.** A question carries its options, and an answer names the question and
> the option, so that the answer is bound to that question exactly.

What an answer authorizes, and that it is used once, are authorizing's.

> **Normative.** A device that takes pieces of a message is sent them as they are
> produced, and only the finished message is recorded.

> **Normative.** A message cut off before it finished is recorded with what was sent,
> marked cut off.

> **Normative.** A stopped activation writes no new message.

### 7. What the kind declares

> **Normative.** The kind's description, given to planning, is a private text
> conversation with the user, whose own messages carry their authority, and which
> expects a reply, a question or a notice to each.

> **Normative.** The conversation's rules, enforced by the hub as host (ADR-0292 §8:2),
> are that only a conversation's devices write in it and that a message has a size
> bound.

> **Normative.** The writer's rules, enforced at the actuator (ADR-0292 §8:3), are text
> only and a size bound.

> **Normative.** The audience of a message written into a conversation is read from the
> conversation's devices, bounded by the user's choice of them (§3, ADR-0292 §9:4), and
> what may be said for it is ADR-0199's, withheld at supply.

> **Normative.** The kind declares its window size, and that a message or a
> conversation may be deleted.

### 8. Current state

> **Normative.** What the conversation's devices are shown about the assistant is read
> with the conversation, pushed when it changes, and never written into the transcript.

> **Normative.** The current state shows "working…" while an activation started from
> the conversation is running, and that is informational: the user's input stays open
> (§6).

> **Normative.** The current state shows how the last activation started from the
> conversation ended: done, couldn't finish, or interrupted.

After a restart a device can show "interrupted; send again?" instead of a reply that
never comes.

### 9. Endings

> **Normative.** An activation started from a conversation that ends having written
> nothing writes the fixed *couldn't finish* message, listing any effects that did
> happen.

That message stays in the window, so the next activation knows the last one failed.

> **Normative.** A restart writes nothing into a conversation: it closes the open
> episode as interrupted (ADR-0286 §7), and the current state shows *interrupted* (§8).

Writing a message on restart is left for later.

### 10. Until the phases send messages

Planning choosing *send a message*, authorizing checking it and acting running it are
not built, and whether a reply is delivered as an action is open (#2593).

> **Normative.** Until the phases send messages, the reply today's compose stage
> produces is written, by an adapter, as one assistant message into the conversation
> the input came from.

> **Normative.** The adapter writes *couldn't finish* when a pass ends without a reply.

> **Normative.** The controller work replaces the adapter without changing the chat.

> **Normative.** Writing into another conversation, writing from an activation not
> started from one, and the assistant starting a conversation arrive with the phases,
> and the kind permits them from the start.

They need planning to choose where. Until then the notification route keeps working.

### 11. The first build

> **Normative.** The first build runs on today's wire: the acts in the medium are
> requests, and devices fetch the change stream after their cursor through the existing
> delivery poll (`wire/server.py`, `_dispatch_poll`).

The device session later replaces the transport with one connection per device
(ADR-0292 §4:8); catching up is "every change after my cursor" either way, so the chat
does not change.

**What the engine surface becomes.**

> **Normative.** For the conversation, `converse`, `converse_streaming`, and the text
> conversational combination of `receive` and `receive_streaming`, are replaced by the
> acts in the medium (start, set devices, write, delete) and a read of the changes
> after a cursor.

> **Normative.** `recent_conversations` and `conversation` remain reads, and reading a
> conversation gains its current state (§8).

> **Normative.** `forget_conversation` becomes memory-only: it forgets the episodes on
> the conversation's place and no longer deletes the conversation.

> **Normative.** `learn` retires, a reply (§4) being its replacement.

> **Normative.** `answer` retires once question messages and their answers (§6) are
> built.

> **Normative.** The conversation store's Protocol gains the transcript, the change
> stream and the reader's bookkeeping, and the change to it and to `AssistantEngine`,
> with their conformance coverage and canonical fakes, lands with the transcript's
> primary implementation as one unit (ADR-0137 §2:1).

**Sequencing.** Under §6's interim a correction waits for the running activation to
end, so it cannot prevent the action it corrects.

> **Normative.** Stopping an activation, decided on its own, ships with this channel's
> milestone, as the way to halt work before it acts.

**Today's conversations** hold their history in episodes and have no transcript. The
lean is a fresh data directory at the cutover, as the recent milestones' cutovers did,
over seeding each transcript from its episodes; the implementation decides.

### 12. Relationship to earlier decisions

> **Normative.** This ADR supersedes ADR-0274, ADR-0276, ADR-0283, ADR-0022 and
> ADR-0078 in the scopes its header names, and no clause of any other ADR.

> **Normative.** This numbered draft records its replacements on the status line and in
> a dated header note of each ADR it supersedes in part, atomically with this ADR under
> ADR-0070 and ADR-0082, preserving their ratified bodies. Each replacement takes
> effect on this ADR's ratification, except ADR-0078's, which takes effect when
> question messages and their answers are built.

| Earlier decision | Where it goes |
| --- | --- |
| ADR-0274 §2–§6, for a typed text input to the conversation | §4 (a message in), §6 (the writer), §11 (the engine surface) |
| ADR-0276 §3:1–§3:2, for the conversation | §6 (the window) |
| ADR-0283 §4:1 | §5 (the transcript) |
| ADR-0283 §8:1, §8:2 | §2 (delete and forget), §5 (kept until deleted) |
| ADR-0022 §1's `learn` | §4 (a reply), §11 |
| ADR-0078 §8's `answer` | §4, §6 (a question and its answer), §11 |

## Consequences

**What becomes clear.** The conversation is one place with one record of what was said
in it, which every device reads and catches up on the same way, and which outlives any
device. Sending is safe to repeat, and *received* tells a device whether to send again.
Correcting the assistant is replying to the message it got wrong, so feedback needs no
command of its own. Deleting and forgetting are two acts the user can tell apart: one
changes the chat, the other changes the assistant. A message written while the
assistant works is never lost or refused, and the state of the assistant is shown
beside the conversation rather than written into it.

**What it costs.** The first build changes `AssistantEngine` and the conversation
store's Protocol, so it is a contract change landing as one unit (§11). A message's
text is held twice, in the transcript and in an episode, by design, and forgotten
content comes back through the window for as long as the user keeps talking in that
conversation; the user's remedy is deleting. Under the interim a correction waits for
the running activation, which is why stopping an activation ships with this milestone.
Today's conversations have no transcript, so the cutover either starts a fresh data
directory or seeds transcripts from episodes.

**What follows from it.**

1. **The first build** (§11): the transcript, the change stream and the reader's
   bookkeeping in the conversation store; the acts in the medium on today's wire; the
   reader, the writer and the adapter (§10); `forget_conversation` made memory-only and
   `learn` retired.
2. **Stopping an activation**, its own decision, in the same milestone.
3. **The phases sending messages**: writing into another conversation, from an
   activation not started from one, and starting a conversation (§10), which retire
   the notification route.
4. **Question messages and their answers**, with authorizing's decision on what an
   answer authorizes, which retire `answer`.
5. **The device session**: one connection per device, who may start a conversation and
   change devices.

**What stays open.** None of these is decided here.

- **Snapshot size.**
- **What a device sees of a running activation** beyond §8. The lean is nothing more,
  for now.
- **Who may start a conversation and change devices.** The device session's.
- **What an answer authorizes, and that it is used once.** Authorizing's; §6 keeps
  only the binding.
- **Whether forgetting reaches what was derived from what is forgotten.** Memory's
  ([#2683](https://github.com/leonapivato/ai-assistant/issues/2683)).

**Out of scope.**

- Receipts beyond *received*; *shown* and *read* are deferred, as the owner ruled.
- Reactions without words, as the owner ruled.
- Writing a message on restart.
- Voice; interrupting or cancelling with words.
- Editing a message; composing offline; typing indicators.
- More than one person in a conversation; a native phone app and OS push
  notifications.
- [#2520](https://github.com/leonapivato/ai-assistant/issues/2520)'s separate versus
  continuous conversations.
- Activations side by side and takeover: the concurrency milestone.

## Alternatives considered

- **Refuse a message sent while the assistant works** (the proposal's earlier turn
  rule). Declined by the owner on 2026-10-04: it has the assistant's state block a
  shared medium, and the later takeover needs a correction to land.
- **Separate entry types** (user message, assistant message, cut-off, couldn't
  finish, feedback). Declined by the owner: they mixed who wrote a message with what
  state it is in. One message with properties says the same with less.
- **Feedback as its own entry.** Declined by the owner: a reply carries the same, and
  reactions without words are out of scope.
- **Choosing devices per conversation only.** Declined by the owner: a new
  conversation would show on one device until its devices were picked. "My devices" is
  chosen once.
- **One built-in notices conversation.** Declined by the owner: separate topics stay
  separate when the assistant may start a conversation.
- **History read from episodes, with a text-less log pointing into them** (the first
  draft). Declined: the conversation is a hosted medium and keeps its own text
  (ADR-0292 §3:3).
- **Turn state as transcript entries.** Declined by the owner: it is current state, not
  history.
- **Delete-and-forget as one command.** Declined by the owner: they are different acts,
  and a combined command makes one quietly imply the other.
- **Deleting a message takes its replies with it.** Declined by the owner: the user
  deletes exactly what they pick.
- **Send only into the activation's own conversation.** Declined by the owner: the
  assistant may write into any conversation.
- **One cursor per conversation.** Declined: a device following ten conversations
  would keep ten cursors and make ten catch-up requests.
- **Wait for the device session before building.** Declined by the owner: the chat
  does not depend on the transport, so the first build runs on today's wire.
