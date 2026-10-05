# The conversation channel

**The question.** How does the most basic channel for talking with the user work, text
in and text out, under the rethought channel model (ADR-0292,
[#2682](https://github.com/leonapivato/ai-assistant/pull/2682))?

This applies ADR-0292 to one channel: the hub's chat. ADR-0292 fixes the general model
(spokes, channels, places, hosted media, authors, push and pull, audience, window,
activations side by side, what retires). This proposal decides what the chat is, what its
conversations keep, how a message gets in and out, and what is built first. How a device's
connection carries it is the device session's; stopping an activation is its own proposal.

Rulings the owner made on earlier drafts of this proposal (2026-10-04) carry over and are
marked *(owner)*.

## Baseline

Wiki pages, read at wiki revision
[`b95617b`](https://github.com/leonapivato/ai-assistant/wiki/Channels/b95617b24abc2f1bbef5997ecf4b36eb6056bbc6):
[Channels](https://github.com/leonapivato/ai-assistant/wiki/Channels),
[Channel window](https://github.com/leonapivato/ai-assistant/wiki/Channel-window) and
[Episodes](https://github.com/leonapivato/ai-assistant/wiki/Episodes). ADR-0292 replaces
much of what the Channels pages describe.

| ADR | What it decides today | What this proposal would do |
| --- | --- | --- |
| ADR-0274 §2–§6 | A `ChannelInput` names its channel (`conversation`, the conversation id as instance) and the reply it accepts; the reply returns on the request; the caller may supply history and a replied-to item. | Supersede for the conversation: a message is an act in the hosted chat space, names no channel, and supplies no history; the assistant's output is a message written into a conversation. "Replies to entry X" stays, as a reference into the transcript. |
| ADR-0276 §3:1–§3:2 | The conversation's window is its tail as read from episodes; *"no per-channel history table"*. | Supersede for the conversation: its window is its recent transcript, brought in by the chat's sensor (ADR-0292's window rule). |
| ADR-0283 §4:1, §8:1 | A conversation's history is the episodes on its channel; deleting a conversation destroys them. | Supersede: its history is its transcript; deleting a conversation deletes the transcript; forgetting is memory's command (§2). |
| ADR-0283 §1 (as amended by ADR-0292) | Episodes indexed by channel and place. | Applied: the chat's episodes are indexed by (the chat, the conversation). |
| ADR-0074 | A conversation is a first-class entity; the store mints its id. | Kept: a conversation is a place in the chat space, with that id. |
| ADR-0286 §2, §7 | An episode opens at admission and is frozen at its end; a restart closes an open episode as interrupted. | Kept. A restart sends nothing into the conversation (§10). |
| ADR-0280 §4, row 11 | `reply_owed`: a conversation turn with no composed reply makes `compose` due. | Not amended here; the kind's description says it expects a reply (§8), and the row's rewording waits for the milestone where an event reaches a reply ([#2598](https://github.com/leonapivato/ai-assistant/issues/2598) item 3). |
| ADR-0170 | A reply is not a tool; the turn composes its answer. | Not decided here ([#2593](https://github.com/leonapivato/ai-assistant/issues/2593)). The chat's actuator writes a message; until the phases call it, today's compose stage does (§11). |

Unchanged: the spoken path, quarantined until voice returns as its own channels;
informational events (`receive`), until ADR-0292's per-source channels replace them; every
other query and command of the engine surface.

## The change

### 1. The chat

| | The chat |
| --- | --- |
| **Channel** | `conversation`, one, built in |
| **Medium** | The hub's chat space, a hosted medium |
| **Places** | Conversations, each with its ADR-0074 id |
| **Spokes** | In the hub: a reader (sensor) and a writer (actuator) |
| **Push** | A new message or feedback by the user starts an activation |
| **Pull** | Earlier messages, in any conversation |

The chat space exists whether or not any device is connected and outlives every device.
It carries **text only**.

### 2. Conversations and what can be done with them

| Operation | Route (ADR-0292) | What it does |
| --- | --- | --- |
| Start a conversation | Act in the medium | Creates an empty conversation. No longer a side effect of the first message. |
| Choose a conversation's devices | Act in the medium | Sets which of the user's devices show it and can write in it (§3). |
| Write a message; give feedback | Act in the medium | §4 |
| List conversations; read one after a cursor | Read of the medium | As `recent_conversations` and `conversation` today, plus the current state (§9) |
| Delete a message | Act in the medium | Deletes that entry alone (§5) |
| Delete a conversation | Act in the medium | Deletes its transcript. Forgets nothing. |
| Forget a conversation | Command | Forgets the episodes on that place. Leaves the transcript. |

**No single operation deletes and forgets** *(owner)*; an interface may offer both side by
side. Who may start a conversation, and which device becomes its first, is the device
session's.

### 3. Devices

A conversation is shown on the devices the user chose for it, and each is the user's end
of it. ADR-0292's rules apply as they stand:

- **Choosing a device is the user's statement that its screen is private**, whatever the
  device *(owner)*. The assistant has no action that adds a device.
- **A device may write, read, or both**: a watch may only read.
- **A device carries a label** it declares ("iPhone", "laptop browser"), shown to the user;
  it grants nothing.
- A device may be an end of many conversations, and a conversation may have many devices.

### 4. A message in

A message is an act in the medium from one of the conversation's devices. It carries its
text and a **message id the device chose**.

- **Sending is safe to repeat.** A message sent again with the same id is the same
  message: one entry, one activation. A deleted message keeps its id, so a late repeat is
  still recognized and does not come back.
- **Received is the answer to the send.** Once the chat space has recorded the entry, it
  answers with the entry's position. That lets a device stop showing *sending*; its absence
  tells the device to send again. *Received* means in the conversation, not yet understood.
- **A reply reference.** A message may name one earlier entry it replies to.
- **Size.** A message over the bound is refused, with the error on the send, and not
  recorded.
- **Its author** is the user, established, and it is sent as an instruction, so it can
  carry the user's authority (ADR-0292 §5).

**Feedback** is the same kind of act: the user marks an assistant entry (a correction, a
thumbs-down with words) and it is recorded against that entry. Withdrawing it is another
act. Feedback is input the assistant perceives (§6), which is how `learn` is replaced.

### 5. The transcript

Each conversation keeps a **transcript**, the chat space's own ordered record of what was
said in it, under ADR-0292's rules for a hosted medium.

| Entry | Holds |
| --- | --- |
| A user message | Text, message id, the device it came from, the entry it replies to |
| An assistant message | Text, the entry it replies to; a question carries its options (§7) |
| A cut-off assistant message | The text streamed before it was cut off (§7) |
| Couldn't finish | The fixed message sent when an activation ended without writing one (§10) |
| Feedback | The entry it is about, its text, the device it came from |

- **Order.** Every entry gets a sequence number increasing across the whole chat space. A
  device following any set of conversations keeps **one cursor**, and catching up is one
  request for everything after it. A cursor too old to replay is answered with a
  **snapshot** of each conversation's recent entries, then new entries from there.
- **Kept until deleted**, an entry or the whole conversation at a time, and purged with
  the user's data.
- **Not memory.** An activation's episode still records what the assistant perceived and
  did, so a message's text is in both; the two are never kept in step.
- **Forgetting does not reach it.** The interface says so plainly: forgetting a
  conversation stops the assistant recalling it anywhere else, but it still reads the
  conversation while the user keeps talking there; only deleting removes it *(owner)*.
- **Deleting a message deletes that entry alone.** The assistant's reply to it stays, and
  its reference then names a deleted entry, shown as such *(owner)*.

### 6. Taking messages in

The chat's sensor notices new **user messages and feedback** and brings them in as a push.
The assistant's own entries never start an activation.

**One activation at a time per conversation, for now** (ADR-0292 §11's interim). A message
written while an activation started from that conversation is running lands in the
transcript at once and waits. When the activation ends, everything waiting is taken in
together as **one input**, which starts the next activation. Nothing is refused or queued
out of sight: the transcript shows what was written and when, so the next activation can
tell a message was written before the reply it follows. In the end state each message is
taken in at once and activations run side by side; that changes only when the sensor takes
messages in.

**The window** is the conversation's recent transcript, brought in by the sensor with the
new input. Each entry keeps its author, so the window informs and never authorizes. The
kind declares how many entries it holds.

**Processing bookkeeping.** The chat keeps, per conversation, which entries have been taken
in and by which activation. It is not a record of what was said and holds no text.
- An entry is marked taken in when its activation is admitted.
- After a restart, entries already taken in by an interrupted activation are **not** taken
  in again, since the activation may have acted on them. Entries never taken in are taken
  in as usual.

### 7. A message out

The chat's actuator writes an assistant message into a conversation: *send a message*.

- **Planning chooses the conversation** *(owner)*. Replying where the input came from is the
  usual case, not a rule. Any activation may send, including one not started from a
  conversation, such as a timer's; that is how the assistant writes first, and how
  notifications become messages (ADR-0292 §7).
- **Sent means recorded.** The message is sent once the chat space has recorded it, whatever
  devices are showing the conversation; devices get it as it is recorded or when they catch
  up.
- **Several messages per activation** are allowed: "looking into it", then the answer.
- **A message may reply to an entry**, and **a question** may carry its options, so a
  device can show them as buttons. A user message answering a question names the question
  entry and, for a button, the option. What an answer authorizes, and that it is used once,
  are authorizing's; the conversation only keeps the binding exact.
- **Streaming.** A device that takes pieces is sent them as they are produced. Only the
  finished message enters the transcript; one cut off is recorded as cut off, with what was
  sent.
- **A stopped activation writes no new output** into a conversation.

### 8. What the kind declares

- **Description**, given to planning: a private text conversation with the user, whose own
  messages carry their authority, which expects a reply, a question or a notice to each.
- **The medium's rules**, enforced by the hub as host: only a conversation's devices write in
  it; a message has a size bound.
- **The channel's rules**, enforced at the actuator: text only; a size bound. **Audience** is
  read from the conversation's devices, bounded by the user's choice, and what may be said
  for it is ADR-0199's, withheld at supply.
- **Its window size**, and that **an entry or a conversation may be deleted**.

### 9. Current state

Whether an activation started from a conversation is running is the conversation's
**current state**: derived from what is running, never written into the transcript
*(owner)*. It is read with the conversation and pushed to its devices when it changes, as a
"working…" indicator. It is informational: the user's input stays open (§6).

### 10. Endings

- **An activation started from a conversation that ends having written nothing** writes
  the fixed *couldn't finish* entry, listing any effects that did happen.
- **A restart writes nothing.** It closes the open episode as interrupted (ADR-0286 §7),
  which keeps the record of what happened; the conversation's state is idle again. Writing
  the fixed message on restart is left for later.

### 11. Until the phases send messages

Planning choosing *send a message*, authorizing checking it and acting running it are not
built, and whether a reply is delivered as an action is open (#2593). So the first build
uses an **adapter**: the reply today's compose stage produces is written as one assistant
message into the conversation the input came from, and the adapter writes *couldn't
finish* when a pass ends without one. The controller work replaces the adapter without
changing the chat. Sending into another conversation, and sending from an activation not
started from one, arrive with the phases; the kind permits them from the start.

### 12. What the engine surface becomes

- `converse` and `converse_streaming` are replaced, for the conversation, by the acts in the
  medium (start, choose devices, write, feedback, delete) and reading after a cursor. How
  they travel to a device is the device session's.
- `recent_conversations` and `conversation` remain reads; reading a conversation gains its
  current state.
- `forget_conversation` becomes memory-only: it forgets the conversation's episodes and no
  longer deletes the conversation.
- `learn` retires once feedback entries are built; `answer` retires once question entries and
  their answers are built (ADR-0292 §13). Both are in this proposal's scope.

These change `AssistantEngine` and the conversation store's Protocol, which gains the
transcript and the processing bookkeeping, so the ADR is a contract change: its triad
lands with the transcript's primary implementation (ADR-0137 §2).

### 13. Moving today's conversations

Today's conversations hold their history in episodes and have no transcript. The cutover
either seeds each transcript once from its episodes, or starts on a fresh data directory.
The lean is a fresh data directory, as the recent milestones' cutovers did; the
implementation decides.

## Options considered

**Refuse a message sent while the assistant works** (this proposal's earlier turn rule).
Declined (owner, 2026-10-04): it has the assistant's state block a shared medium, and the
later takeover needs a correction to land.

**History read from episodes, with a text-less log pointing into them** (the first draft).
Declined: the conversation is a hosted medium and keeps its own text (ADR-0292 §3).

**Turn state as transcript entries.** Declined (owner): it is current state, not history.

**Delete-and-forget as one command.** Declined (owner): different acts, and a combined
command makes one quietly imply the other.

**Deleting a message takes its reply with it.** Declined (owner): the user deletes exactly
what they pick.

**Send only into the activation's own conversation.** Declined (owner): the assistant may
write into any conversation.

**One cursor per conversation.** Declined: a device following ten conversations would keep
ten cursors and make ten catch-up requests.

**Keep the reply on the request.** Declined: the reply would reach only the sending device,
and the assistant could not write first.

## Out of scope

- Receipts beyond *received*; *shown* and *read* are deferred *(owner)*.
- Writing the fixed message on restart.
- Voice; interrupting or cancelling with words.
- Editing a message; composing offline; typing indicators.
- More than one person in a conversation; a native phone app and OS push notifications.
- [#2520](https://github.com/leonapivato/ai-assistant/issues/2520)'s separate versus
  continuous conversations.
- Activations side by side and takeover: the concurrency milestone.

**Sequencing.** Under the interim of §6, a correction waits for the running activation to
end, so it cannot prevent the action it corrects. Stopping an activation (its own
proposal) therefore ships with this channel's milestone, as the way to halt work before it
acts.

## What it leaves open

- **Snapshot size.**
- **What a device sees of a running activation** beyond the "working…" indicator; the lean
  is nothing more for now.
- **Who may start a conversation and choose its devices**: the device session's.
- **What an answer authorizes and that it is used once**: authorizing's (§7 keeps only the
  binding).
