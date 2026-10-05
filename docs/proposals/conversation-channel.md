# The conversation channel

**The question.** How does the most basic channel for talking with the user work, text
in and text out, under the rethought channel model (ADR-0292,
[#2682](https://github.com/leonapivato/ai-assistant/pull/2682))?

This applies ADR-0292 to one channel: the hub's chat. ADR-0292 fixes the general model
(spokes, channels, places, hosted media, authors, push and pull, audience, window,
activations side by side, what retires). This proposal decides what the chat is, what its
conversations keep, how a message gets in and out, and what is built first. How a device's
connection carries it in the end is the device session's; stopping an activation is its
own proposal.

The owner walked this proposal through section by section on 2026-10-04. Their rulings are
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
| ADR-0274 §2–§6 | A `ChannelInput` names its channel (`conversation`, the conversation id as instance) and the reply it accepts; the reply returns on the request; the caller may supply history and a replied-to item. | Supersede for the conversation: a message is an act in the hosted chat space, names no channel and supplies no history; the assistant's output is a message written into a conversation. "Replies to entry X" stays, as a reference into the transcript. |
| ADR-0276 §3:1–§3:2 | The conversation's window is its tail as read from episodes; *"no per-channel history table"*. | Supersede for the conversation: its window is its recent transcript, brought in by the chat's reader (ADR-0292's window rule). |
| ADR-0283 §4:1, §8:1 | A conversation's history is the episodes on its channel; deleting a conversation destroys them. | Supersede: its history is its transcript; deleting a conversation deletes the transcript; forgetting is memory's command (§2). |
| ADR-0283 §1 (as amended by ADR-0292) | Episodes indexed by channel and place. | Applied: the chat's episodes are indexed by (the chat, the conversation). |
| ADR-0074 | A conversation is a first-class entity; the store mints its id. | Kept: a conversation is a place in the chat space, with that id. |
| ADR-0286 §2, §7 | An episode opens at admission and is frozen at its end; a restart closes an open episode as interrupted. | Kept. A restart writes nothing into the conversation (§9). |
| ADR-0280 §4, row 11 | `reply_owed`: a conversation turn with no composed reply makes `compose` due. | Not amended here; the kind's description says it expects a reply (§7), and the row's rewording waits for the milestone where an event reaches a reply ([#2598](https://github.com/leonapivato/ai-assistant/issues/2598) item 3). |
| ADR-0170 | A reply is not a tool; the turn composes its answer. | Not decided here ([#2593](https://github.com/leonapivato/ai-assistant/issues/2593)). The chat's writer adds a message; until the phases call it, today's compose stage does (§10). |

Unchanged: the spoken path, quarantined until voice returns as its own channels;
informational events (`receive`), until ADR-0292's per-source channels replace them; the
notification route, until the assistant can start conversations (§6); every other query and
command of the engine surface.

## The change

### 1. The chat

| | The chat |
| --- | --- |
| **Channel** | `conversation`, one, built in |
| **Medium** | The hub's chat space, a hosted medium |
| **Places** | Conversations, each with its ADR-0074 id |
| **Spokes** | In the hub: a reader (sensor) and a writer (actuator) |
| **Push** | A new message from the user starts an activation |
| **Pull** | Earlier messages, in any conversation |

The chat space exists whether or not any device is connected and outlives every device.
It carries **text only**.

What belongs where *(owner)*:

| Belongs to | What |
| --- | --- |
| **The conversation**, the medium | The transcript and its messages; message ids; *received*; deleting; which devices are its ends; the order, and the stream of changes to devices |
| **The chat channel and its spokes** | The reader noticing new messages and bringing in the window; the writer adding the assistant's messages; the reader's bookkeeping of what it has taken in |
| **The assistant** | Activations and episodes; "working…" and how the last activation ended; what it remembers and forgets |

### 2. Conversations and what can be done with them

| Operation | Route (ADR-0292) | What it does |
| --- | --- | --- |
| Start a conversation | Act in the medium | Creates an empty conversation, shown on "my devices" (§3). No longer a side effect of the first message. |
| Set "my devices"; choose a conversation's devices | Act in the medium | §3 |
| Write a message | Act in the medium | §4 |
| List conversations; read one after a cursor | Read of the medium | As `recent_conversations` and `conversation` today, plus the current state (§8) |
| Delete a message | Act in the medium | Deletes that message alone (§5) |
| Delete a conversation | Act in the medium | Deletes its transcript. Forgets nothing. |
| Forget a conversation | Command | Forgets the episodes on that place, as `forget_conversation` does today. Leaves the transcript. |

- **No single operation deletes and forgets** *(owner)*; an interface may offer both side by
  side.
- **Forgetting reaches the episodes alone** *(owner)*, as today. Whether forgetting should
  also reach what was derived from what is forgotten is memory's question
  ([#2683](https://github.com/leonapivato/ai-assistant/issues/2683)).
- **Who may start a conversation or change devices** is the device session's.

### 3. Devices

Each device a conversation is shown on is the user's end of it.

- **"My devices"** is a set the user keeps on the chat space as a whole *(owner)*. A new
  conversation is shown on all of them. Adding a device to it is the user's statement that
  the device's screen is private, whatever the device.
- **A conversation's devices can be changed** from that default, such as a conversation
  kept off a shared tablet. Choosing a device for one conversation is the same statement,
  for that conversation.
- **The assistant has no action that adds a device**, to the set or to a conversation.
- **A device may write, read, or both**: a watch may only read.
- **A device carries a label** it declares ("iPhone", "laptop browser"), shown to the user;
  it grants nothing.

### 4. A message in

A message is an act in the medium from one of the conversation's devices. It carries its
text and a **message id the device chose**, unique per device *(owner)*.

- **Sending is safe to repeat.** A message sent again by the same device with the same id is
  the same message: one entry, one activation. A deleted message leaves a marker (§5), so a
  late repeat is still recognized and does not come back.
- **Received is the answer to the send.** Once the conversation has recorded the message, it
  answers with the message's position. That lets a device stop showing *sending*; its absence
  tells the device to send again. *Received* means in the conversation, not yet understood.
- **A reply reference.** A message may name one earlier message it replies to. A reply is
  also how the user corrects the assistant: "wrong campsite, I meant Pinecrest", replying to
  the assistant's message, is how `learn` is replaced *(owner)*.
- **Answering a question.** A message answering a question names the question and, for a
  button, the option (§6).
- **Size.** A message over the bound is refused, with the error on the send, and not
  recorded.
- **Its author** is the user, established, and it is sent as an instruction, so it can carry
  the user's authority (ADR-0292 §5).

### 5. The transcript

Each conversation keeps a **transcript**, the ordered record of what was said in it, under
ADR-0292's rules for a hosted medium. Every entry is a **message** *(owner)*, with these
properties:

| Property | Values | What depends on it |
| --- | --- | --- |
| **Author** | The user, or the assistant | Only the user's messages start activations and can carry authority |
| **Text** | | |
| **Replies to** | An earlier message, optional | Answering and correcting |
| **Options** | For a question, optional | Devices show them as buttons; an answer names one |
| **Cut off** | Yes or no; only the assistant's | A cut-off message is never read as a complete answer (§6) |
| **Message id, device** | The user's messages only | Safe resending; which device it came from |

A property exists only where something behaves differently because of it. The *couldn't
finish* message (§9) is an assistant message whose text is fixed rather than composed.

- **Kept until deleted**, a message or a whole conversation at a time, and purged with the
  user's data.
- **Not memory.** An activation's episode still records what the assistant perceived and
  did, so a message's text is in both; the two are never kept in step.
- **Forgetting does not reach it.** The interface says so plainly: forgetting a conversation
  stops the assistant recalling it anywhere else, but it still reads the conversation while
  the user keeps talking there; only deleting removes it *(owner)*.
- **Deleting a message deletes it alone.** A reply to it stays, and its reference names a
  deleted message, shown as such *(owner)*. Either party's messages can be deleted by the
  user; the assistant deletes nothing.

**How devices stay in step** *(owner)*:

- Every **change** to the chat space gets a sequence number, increasing across all its
  conversations: a message added, a message deleted, a conversation started or deleted, a
  device added or removed.
- A device keeps **one cursor**, and catching up is one request for every change after it.
- A deleted message leaves a **marker**: its id and that it was deleted, no text. Devices
  remove it on seeing the marker.
- A device far behind, or new, gets a **snapshot** of each conversation's recent messages, and
  loads older ones as the user scrolls back.

### 6. The assistant's side: reading and writing

**The reader** notices new user messages and brings them in as a push. The assistant's own
messages never start an activation.

**One activation at a time per conversation, for now** (ADR-0292 §11's interim). A message
written while an activation started from that conversation is running lands in the
transcript at once and waits. When the activation ends, everything waiting is taken in
together as **one input**. Nothing is refused: the transcript shows what was written and
when, so the next activation can tell a message was written before the reply it follows.
In the end state each message is taken in at once and activations run side by side.

**The window** is the conversation's recent transcript, brought in by the reader with the new
input. Each message keeps its author, so the window informs and never authorizes. The kind
declares how many messages it holds.

**The reader's bookkeeping** *(owner)*. The reader records which messages it has taken in, and
by which activation. It holds no text, and it is the reader's, not the conversation's: the
conversation does not know whether the assistant has read it.
- A message is marked taken in when its activation is admitted.
- After a restart, messages an interrupted activation already took in are **not** taken in
  again, since it may have acted on them. Messages never taken in are taken in as usual.

**The writer** adds assistant messages: *send a message*.

- **Planning chooses the conversation** *(owner)*. Replying where the input came from is the
  usual case, not a rule. Any activation may write, including one a timer started.
- **The assistant may start a conversation** *(owner)*, with its first message, when nothing
  existing fits: "your Friday booking moved". It is shown on "my devices". This is how
  notifications become messages (ADR-0292 §7).
- **Sent means recorded**, whatever devices are showing the conversation; devices get the
  message live or when they catch up.
- **Several messages per activation** are allowed: "looking into it", then the answer.
- **A question carries its options**, and an answer names the question and the option, so the
  binding is exact. What an answer authorizes, and that it is used once, are authorizing's.
- **Streaming.** A device that takes pieces is sent them as they are produced. Only the
  finished message is recorded; one cut off is recorded with what was sent, marked cut off.
- **A stopped activation writes no new message.**

### 7. What the kind declares

- **Description**, given to planning: a private text conversation with the user, whose own
  messages carry their authority, and which expects a reply, a question or a notice to each.
- **The conversation's rules**, enforced by the hub as host: only a conversation's devices
  write in it; a message has a size bound.
- **The writer's rules**, enforced at the actuator: text only; a size bound. **Audience** is
  read from the conversation's devices, bounded by the user's choice, and what may be said
  for it is ADR-0199's, withheld at supply.
- **Its window size**, and that **a message or a conversation may be deleted**.

### 8. Current state

What the conversation's devices are shown about the assistant, read with the conversation
and pushed when it changes, and never written into the transcript *(owner)*:

- **"Working…"** while an activation started from the conversation is running. It is
  informational: the user's input stays open (§6).
- **How the last one ended**: done, couldn't finish, or interrupted *(owner)*. After a restart
  a device can show "interrupted; send again?" instead of a reply that never comes.

### 9. Endings

- **An activation started from a conversation that ends having written nothing** writes the
  fixed *couldn't finish* message, listing any effects that did happen. It stays in the
  window, so the next activation knows it failed.
- **A restart writes nothing.** It closes the open episode as interrupted (ADR-0286 §7), and
  the current state shows *interrupted* (§8) *(owner)*. Writing a message on restart is left
  for later.

### 10. Until the phases send messages

Planning choosing *send a message*, authorizing checking it and acting running it are not
built, and whether a reply is delivered as an action is open (#2593). So the first build
uses an **adapter**: the reply today's compose stage produces is written as one assistant
message into the conversation the input came from, and the adapter writes *couldn't finish*
when a pass ends without one. The controller work replaces the adapter without changing the
chat.

Writing into another conversation, writing from an activation not started from one, and the
assistant starting a conversation need planning to choose where, so they arrive with the
phases; the kind permits them from the start. Until then the notification route keeps
working.

### 11. The first build

**On today's wire** *(owner)*. The acts in the medium are requests, and devices fetch the
change stream after their cursor through the existing delivery poll (`_dispatch_poll`). The
device session later replaces the transport with one connection per device; catching up is
"every change after my cursor" either way, so the chat does not change.

**What the engine surface becomes:**

- `converse` and `converse_streaming` are replaced, for the conversation, by the acts in the
  medium (start, set devices, write, delete) and reading changes after a cursor.
- `recent_conversations` and `conversation` remain reads; reading a conversation gains its
  current state.
- `forget_conversation` becomes memory-only: it forgets the conversation's episodes and no
  longer deletes the conversation.
- `learn` retires: a reply is its replacement. `answer` retires once question messages and
  their answers are built, in this proposal's scope (ADR-0292 §13).

These change `AssistantEngine` and the conversation store's Protocol, which gains the
transcript, the change stream and the reader's bookkeeping, so the ADR is a contract change:
its triad lands with the transcript's primary implementation (ADR-0137 §2).

**Sequencing.** Under the interim of §6, a correction waits for the running activation to
end, so it cannot prevent the action it corrects. Stopping an activation (its own proposal)
therefore ships with this channel's milestone, as the way to halt work before it acts.

**Today's conversations** hold their history in episodes and have no transcript. The lean is
a fresh data directory at the cutover, as the recent milestones' cutovers did, over seeding
each transcript from its episodes; the implementation decides.

## Options considered

**Refuse a message sent while the assistant works** (this proposal's earlier turn rule).
Declined (owner, 2026-10-04): it has the assistant's state block a shared medium, and the
later takeover needs a correction to land.

**Separate entry types** (user message, assistant message, cut-off, couldn't finish,
feedback). Declined (owner): they mixed who wrote a message with what state it is in. One
message with properties says the same with less.

**Feedback as its own entry.** Declined (owner): a reply carries the same, and reactions
without words are out of scope.

**Choosing devices per conversation only.** Declined (owner): a new conversation would show
on one device until its devices were picked. "My devices" is chosen once.

**One built-in notices conversation.** Declined (owner): separate topics stay separate when
the assistant may start a conversation.

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

**Wait for the device session before building.** Declined (owner): the chat does not depend
on the transport, so the first build runs on today's wire.

## Out of scope

- Receipts beyond *received*; *shown* and *read* are deferred *(owner)*.
- Reactions without words *(owner)*.
- Writing a message on restart.
- Voice; interrupting or cancelling with words.
- Editing a message; composing offline; typing indicators.
- More than one person in a conversation; a native phone app and OS push notifications.
- [#2520](https://github.com/leonapivato/ai-assistant/issues/2520)'s separate versus
  continuous conversations.
- Activations side by side and takeover: the concurrency milestone.

## What it leaves open

- **Snapshot size.**
- **What a device sees of a running activation** beyond §8; the lean is nothing more for now.
- **Who may start a conversation and change devices**: the device session's.
- **What an answer authorizes and that it is used once**: authorizing's (§6 keeps only the
  binding).
