# 292. A channel is the spokes facing one thing, and the assistant's edge is its own

- Status: Partially superseded by ADR-0294 (§Decision:2's and §13:1's hold on readers' scheduled ingestion) and ADR-0296 (§4:8's one connection per device, §4:9's closing of that connection, and §4:10's gate as it reaches a browser device)
- Date: 2026-10-04
- Scope: [#2578](https://github.com/leonapivato/ai-assistant/issues/2578), the channel redesign, rethought: the model the conversation channel ([#2680](https://github.com/leonapivato/ai-assistant/pull/2680)), the device session and stopping an activation apply, in place of ADR-0290 and ADR-0291.
- Authorization: the owner accepted proposal #2682 on 2026-10-04, at `36031075`, after walking the model through item by item the same day, and the dispatcher assigned 0292. This ADR is that proposal converted under `docs/proposals/README.md` → "When it is decided".
- **Supersedes** [ADR-0290](0290-a-channel-is-needed-exactly-where-something-crosses-the-hubs-edge.md) — **whole.** The edge becomes the assistant's (§1), a channel becomes the group of spokes facing one thing (§2), and the activating and service sorts give way to push and pull per input (§6). What survives is restated in §5 and §12. Its earlier partial supersession by ADR-0291 stays on its status line as history.
- **Supersedes** [ADR-0291](0291-a-channels-record-is-its-own-and-what-it-keeps-is-its-kinds-choice.md) — **whole.** Channels keep nothing; a hosted medium keeps its own content, and ADR-0291's rules for a channel's record move onto it (§3).
- **Partially supersedes** [ADR-0283](0283-a-channels-history-is-its-episodes-and-the-turn-index-is-retired.md) — **one scope.** **§1's index, in what an episode is indexed by, and §1:2's order, read as channel and place**: an episode is indexed by its channel and its place, and records the spokes its input came through; the `ChannelIdentity` that §1:3 indexes and §1:2 orders is a channel together with a place, a conversation's (`conversation`, id) being (the chat, that conversation) (§10 below). Under that mapping §1:3's columns, §3's reads and §8's deletion and reclaim read exactly what they read today, scoped to the place. ADR-0291's scope on §1:2 has nothing left to reach once no channel keeps a record (§3 below): §1:2 orders every place's episodes and every channel's across its places, and a hosted medium's content is ordered as its kind declares. §4:1's history read and §8:1's deletion stay in force under the Decision's opening clause until the conversation channel's ADR replaces them for the chat. Every other clause stands.
- Partially superseded: 2026-10-04 by ADR-0294 — one scope. §Decision:2's and
  §13:1's hold on the table's last row: readers' scheduled ingestion into memory
  retires when ADR-0294's implementation lands, before its replacement is built, on
  the owner's ruling of 2026-10-04. §13:2 binds that replacement when it is built,
  and §13:3, the rest of the table and every other clause stand. This replacement
  takes effect on ratification of ADR-0294. This reciprocal header record
  accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions
  and the ratified body below are preserved.
- Partially superseded: 2026-10-04 by ADR-0296 — one scope. §4:8's *one connection per
  device*, §4:9's *closes its connection*, and §4:10's gate, as it reaches a browser
  device: one session per device carries all its routes and may use several physical
  connections, revoking a device ends its session, and a browser device is admitted by
  its gateway rather than by ADR-0124's two facts (ADR-0296 §1, §3). §4:9's removal as
  an end of every place and its unreachable spokes stand, and so does every other
  clause. This replacement takes effect on ratification of ADR-0296. This reciprocal
  header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior
  supersessions and the ratified body below are preserved.

## Context

**The question.** What is a channel, once it stops being both the medium the
assistant meets and the assistant's line to it; and what follows for spokes,
devices, input, output, audience, history and the routes that exist today?

ADR-0290 and ADR-0291, both decided on 2026-10-04, drew a channel as the medium
itself (a chat, held by the hub) and gave it the jobs of the assistant's line to it
as well. Reviewing the conversation channel
([#2680](https://github.com/leonapivato/ai-assistant/pull/2680)) with the owner the
same day showed that the two cannot be one thing: a camera's medium is a room the
hub cannot hold, two microphones in one kitchen are one exchange, and the user's
phone in a chat is the user's end of it, not the assistant's. The owner then walked
the model through item by item and accepted the result (proposal #2682). This ADR
records that model in full, so that nothing here depends on a text that can change
after it. It replaces ADR-0290 and ADR-0291 whole, restating what survives of them,
and it is the model the conversation channel, the device session and stopping an
activation then apply.

The owner's direction was read, as of the proposal, from the wiki pages
[Channels](https://github.com/leonapivato/ai-assistant/wiki/Channels),
[Channel window](https://github.com/leonapivato/ai-assistant/wiki/Channel-window),
[Sensors](https://github.com/leonapivato/ai-assistant/wiki/Sensors),
[External sensors](https://github.com/leonapivato/ai-assistant/wiki/External-sensors),
[Internal sensors](https://github.com/leonapivato/ai-assistant/wiki/Internal-sensors),
[Push](https://github.com/leonapivato/ai-assistant/wiki/Push),
[Actuators](https://github.com/leonapivato/ai-assistant/wiki/Actuators),
[Concurrent activations](https://github.com/leonapivato/ai-assistant/wiki/Concurrent-activations),
[Controller](https://github.com/leonapivato/ai-assistant/wiki/Controller) and
[Authorizing](https://github.com/leonapivato/ai-assistant/wiki/Authorizing), at
wiki revision
[`b95617b`](https://github.com/leonapivato/ai-assistant/wiki/Channels/b95617b24abc2f1bbef5997ecf4b36eb6056bbc6).
Where this ADR and those pages differ, this ADR governs.

**The ADRs this touches**, as they stand on `main`:

| ADR | What it decides today | How this decision relates |
| --- | --- | --- |
| ADR-0290 | A channel is the medium, held by the hub, needed exactly where something crosses the hub's edge; kinds are activating or service; inside actions, reads of the hub's own records and hub operations are direct. | Superseded whole. The edge becomes the assistant's (§1); a channel becomes a group of spokes (§2); the sorts become per input (§6). What survives is restated (§5, §12). |
| ADR-0291 | A channel's record is its own; what it keeps is its kind's choice; forgetting never reaches it; deleting from it is the user's command; it is the user's data. | Superseded whole. Channels keep nothing; a **hosted medium** keeps its own content, and ADR-0291's rules move onto it (§3). |
| ADR-0283 §1, §§3–4, §8 | Episodes are numbered and indexed by channel (`ChannelIdentity`, a type and an instance); ADR-0291 limited §1:2's order to a channel's episodes. A conversation's history and deletion read its channel's episodes. | Partially superseded: episodes are indexed by channel and place, and record the spokes the input came through; reads are scoped to a place (§10). For every channel today the mapping leaves the columns and reads as they are. |
| ADR-0274 §2–§4, §7 | The caller names the channel and the reply rides the request; informational events from any admitted caller. | Retire when the conversation channel's ADR and per-source channels replace them (§13); until then in force. |
| ADR-0094 §1, §5 | A spoke is an attachment across the process boundary (§1:1), and a producer inside the hub is not one (§1:2); push, doorbell and pull are an attachment's capabilities (§1:3); the hub decides the band and a submission never raises its own (§5:1). | Kept. Every ADR-0094 obligation binds a device's spokes unchanged. This ADR's "spoke" also names a set of sensors and actuators in the hub, which is not a spoke in ADR-0094's sense (§2:13); which word names both is left open. |
| ADR-0199 §1 | Audience is the output channel's; undeclared is unbounded (§1:2); never derived from admission (§1:4). | Kept, and placed: audience is read from the channel or the place, declared by the user, and narrowed but never widened by a spoke (§9). |
| ADR-0052, ADR-0078, ADR-0022, ADR-0280 §1:4 | Durable resume of parked work; a question answered by id; feedback by `AssistantEngine.learn`, the closed learning loop; resume's own path outside the controller. | Retire as mechanisms when their replacements are built; their functions are kept by the model (§13). |
| ADR-0131 | A notification travels to a device as an answer it asked for, through `AssistantEngine.next_notification`. | Retires when writing into a place replaces it (§7, §13). |
| ADR-0093, ADR-0140, ADR-0132 | Calendar and email readers feed a context facet and a scheduled ingestion into memory; ADR-0140's email source is a local file of envelopes; an upcoming-event producer notices start instants. | The reader is an in-hub sensor on its channel. The facet becomes a pull and the producer a push; scheduled ingestion retires (§13). |
| ADR-0276 §3:1–§3:2 | The conversation's channel window is its tail as `ConversationLifecycle.history` reads it; any other channel's is the context its submitter attached. | Ruled against by §10, and in force under the Decision's opening clause until each kind's ADR replaces it. |

**What exists.** No code implements ADR-0290 or ADR-0291. The conversation is
carried by ADR-0274's receiver and the conversation methods of `AssistantEngine`,
with the reply returned on the request; its history and window are read from its
episodes (ADR-0283 §4:1, ADR-0276 §3:1). Informational events arrive from any
admitted caller. Readers ingest on a schedule into memory, notifications reach a
device through `next_notification`, and `resume`, `answer` and `learn` are
operations of their own.

## Decision

We will treat the assistant's own edge, not the hub's, as where it meets the world:
it perceives and acts only through sensors and actuators, each reaching it on a
channel that groups the spokes facing one thing, and everything it reads and changes
of its own records it does directly.

> **Normative.** §§1–13 govern every channel, spoke, hosted medium, device route and
> kind an ADR decides or an implementation builds from this ADR on.

> **Normative.** A route that exists on `main` when this ADR is ratified and that
> §§1–13 rule against, including each mechanism §13 names, ADR-0276 §3:1–§3:2's
> channel windows and ADR-0283 §4:1's and §8:1's conversation history and deletion,
> stays in force exactly as its own ADR decides it until a later ADR that builds its
> replacement supersedes that ADR's clause.

### 1. The assistant's edge

The edge that matters is the **assistant's**, not the hub's machine. The hub runs
things that are not the assistant: the clock, and any medium it hosts, such as the
conversations.

> **Normative.** The assistant perceives only through its sensors and acts on the
> world only through its actuators, and each sensor and actuator reaches it on a
> channel.

> **Normative.** What the assistant reads and changes of its own records, it does
> directly, with no channel, sensor or actuator (§12).

> **Normative.** The user can operate on the assistant directly, by command or query
> (§4), and the assistant does not perceive a command or a query.

The crossing happens at the sensor or actuator, where perceiving and acting happen.
The channel is behind it, on the assistant's side.

### 2. Spokes, channels and places

| Concept | Is | Holds |
| --- | --- | --- |
| **Spoke** | A set of sensors and actuators that face one thing, on a device or in the hub | Capture and release, rendering, what its hardware can do, whether it is reachable, its own state |
| **Channel** | The group of spokes facing one thing: the kitchen, the hub's chat space, a mailbox | Source, authority, audience, window, history, permission; merging what its spokes picked up |
| **Place** | An address within what a channel faces: a conversation, an email thread | The place's own rules: its devices, deleting it |

> **Normative.** A **spoke** is a set of sensors and actuators that face one thing,
> on a device or in the hub. A **channel** is the group of spokes facing one thing.
> A **place** is an address within what a channel faces.

> **Normative.** A spoke attaches to exactly one channel, and a channel may have many
> spokes.

> **Normative.** Where more than one of a channel's spokes picks up the same input,
> the channel takes it in once.

Two microphones in one kitchen are two spokes on one channel, and the channel takes a
sentence both heard in once.

> **Normative.** A device whose sensors and actuators face different things connects
> them as separate spokes, one for each thing faced.

Earbuds face the user's ear and the phone's speaker the room, so they are two spokes
on two channels.

> **Normative.** A channel's identity is what the user named it ("the kitchen",
> "alice@… mail"), or is built in (the hub's chat space, the clock).

> **Normative.** A channel exists because it is built in or because the user
> connected it. Connecting an account creates its channel.

> **Normative.** A spoke attaches to a channel only because the user placed it facing
> that channel's thing, and only where the channel's kind takes its sort of sensor or
> actuator. A spoke cannot attach itself.

> **Normative.** A channel persists when its spokes go: it is unreachable until one
> returns, and its history continues.

> **Normative.** Planning is told that an unreachable channel is unavailable.

> **Normative.** The assistant never creates a channel and never attaches a spoke.

It cannot widen what it senses or where it speaks.

> **Normative.** A kind declares what spokes it takes, and so its directions: a
> sensor for in, an actuator for out. A direction declared need not be used.

> **Normative.** Every channel of one kind follows the same rules.

> **Normative.** A spoke on a device is a spoke in ADR-0094 §1:1's sense, and every
> obligation of ADR-0094 binds it. A spoke in the hub is a producer inside the hub
> under ADR-0094 §1:2, and no clause of ADR-0094 binds it; where ADR-0094 says
> "spoke", it means a spoke on a device.

### 3. Hosted media

A **hosted medium** is a medium the hub holds itself, so that both the assistant
and another party read and write it there. The hub's chat space is the first: each
conversation is a place in it. A shared shopping list would be another.

> **Normative.** The hub's chat space is a hosted medium, and each conversation is a
> place in it.

> **Normative.** A channel keeps no record of what it carried.

Everything a channel record would hold is already held: a conversation's text by the
hosted medium, what the assistant perceived and did by its episodes, an email by the
mail server. "Channels keep nothing" means no record of what was carried; it does not
forbid the bookkeeping of which inputs were taken in, which is left open (What stays
open).

> **Normative.** A hosted medium keeps its own content, held inside the hub and
> separate from the assistant's memory. Recall does not search it, and consolidation
> does not read it.

> **Normative.** A hosted medium's content and the assistant's memory are
> independent: neither is derived from the other, and neither is kept in step with
> the other.

A message can be in the conversation and in an episode; the two are never reconciled.

> **Normative.** What a hosted medium holds is its kind's: each kind declares the
> shape, order and retention of its content, and what may be deleted from it.

> **Normative.** Forgetting is the assistant's act on its own memory, and it never
> reaches a hosted medium's content.

Forgotten content can come back through the window (§10), as a person who forgot a
night can still find the texts they sent. The owner accepted that cost.

> **Normative.** Where forgotten content can come back through a window, the
> interface shows that to the user, and says plainly that only deleting removes it.

> **Normative.** Deleting from a hosted medium is the user's act in the medium (§4),
> available only where its kind allows it.

> **Normative.** The assistant has no action that deletes from a hosted medium.

> **Normative.** Deleting from a hosted medium does not forget. Whatever the assistant
> remembers of what was deleted stays in memory until it is forgotten there.

> **Normative.** A hosted medium's content is the user's data: Tier 1 under ADR-0004
> §1, viewable, exportable and deletable under ADR-0004 §6, and purged whole when the
> user's data is deleted, whatever its kind's retention.

### 4. Devices and their routes

A device can be three things at once, each assigned by the user:

| Role | Example | Assigned by |
| --- | --- | --- |
| The user's **end of places** in a hosted medium | The phone in conversations 7 and 9 | Choosing the device for each conversation |
| **Host of spokes** | The kitchen speaker; the phone's microphone, if allowed | Placing each spoke facing a channel's thing |
| **Source of commands and queries** | The phone and laptop | The user, after pairing |

> **Normative.** Each of a device's roles, the user's end of a place, host of a spoke,
> and source of commands and queries, is assigned by the user. Pairing admits a device
> and gives it no role.

What a device sends travels one of three routes:

| Route | What it is | Reaches the assistant |
| --- | --- | --- |
| **Spoke traffic** | The assistant's sensors and actuators at work | On their channel |
| **An act in a medium** | A party doing something in a hosted medium: writing a message, starting or deleting a conversation | Only when the channel's sensor notices it |
| **A command or query** | The user operating on the assistant, or reading its records | Never perceived; carried out by rule |

> **Normative.** Everything a device sends travels one of three routes, spoke
> traffic, an act in a medium, or a command or query, and the hub tells them apart by
> the structured kind of the message, never by its content.

> **Normative.** Spoke traffic reaches the assistant on its spoke's channel, and an
> act in a medium reaches the assistant only when the channel's sensor notices it.

> **Normative.** A command or query is not input to the assistant: it crosses no
> channel, no model reads it, it starts no activation, and the hub carries it out by
> rule.

The test between the last two is what changes. An act in a medium changes the
medium: deleting a conversation removes it from the chat. A command changes the
assistant: forgetting a conversation removes its episodes and leaves the chat as it
was.

> **Normative.** An act in a medium is a structured act, from a device that is the
> user's end of that place, and needs the same bar as a command. The hub, as host,
> applies the medium's rules to it, and no model is involved.

> **Normative.** Writing into a hosted medium and perceiving it are two steps. The
> medium accepts a message, records it and answers *received* with its position;
> then the channel's sensor takes it in. A message lands even when the assistant
> cannot take it in at once.

> **Normative.** The assistant's own messages are written into the medium by its
> actuator, and the user's devices read them there.

> **Normative.** One connection per device carries all three routes.

> **Normative.** Revoking a device closes its connection, removes it as an end of
> every place and makes its spokes unreachable.

> **Normative.** ADR-0124's admission stays the gate in front of a device's
> connection.

### 5. Input: source, author and authority

> **Normative.** Every input arrives with its channel, its place and its author, all
> stated by the hub and never by its content.

> **Normative.** The spokes an input came through are recorded as how it arrived.

An **author** is:

| Part | Values |
| --- | --- |
| **Who** | The user; a known person; an unidentified person; a service; the assistant |
| **How sure** | Established; claimed, recording who it claims to be; unknown |
| **When written** | Usually as it arrived; earlier for something written in advance |

> **Normative.** An author is a who, a how sure and a when written, each taking a
> value the table above lists.

> **Normative.** Each kind declares how it establishes authors.

In a conversation only the user's ends can write, so a message is the user's,
established; in a kitchen anyone could speak, so the speaker is unknown; an email's
sender is claimed; a reminder's author is whoever set it, at the time they set it.

> **Normative.** Input carries the user's authority only when its author is
> established as the user and the user sent it as an instruction. Everything else
> informs and cannot authorize.

> **Normative.** A reminder the user set informs the activation it starts and
> authorizes nothing: the user wrote it for later, not as an instruction to act on
> when it comes due.

> **Normative.** A message the user sent as an instruction keeps the user's authority
> when it waited before being taken in.

> **Normative.** Content never establishes, or counts toward establishing, an input's
> author.

> **Normative.** A channel's identity grants nothing.

> **Normative.** A spoke's evidence, such as a face unlock or a voice match, counts
> toward establishing the user only where the kind allows it and the user set it up,
> such as by enrolling a voice. Nothing a spoke reports raises authority by itself
> (ADR-0094 §5:1).

### 6. Push, pull and doorbell

> **Normative.** Whether input starts an activation is decided per input, not per
> kind.

> **Normative.** A **push** is input nobody asked for: a message, new mail, a reminder
> coming due. On its channel it starts an activation, subject to the kind's filter.

> **Normative.** A **pull** is the assistant asking and the far side answering within
> that request: a forecast, a calendar lookup, earlier messages in a conversation. The
> answer returns to the activation that asked.

> **Normative.** A **doorbell** says something is waiting without saying what. It is a
> push, and the activation it starts pulls the content (ADR-0094 §1:3).

> **Normative.** A kind declares whether it can be pulled and whether it pushes.

Email does both, so does a calendar, so does the conversation; search is pulled, and
only its late answers push; a timer only pushes.

> **Normative.** A pull's answer returns only while the asker waits. A different
> answer arriving after the asker ended is a push, and starts an activation of its
> own; a repeat of the same answer is a duplicate.

> **Normative.** A person's reply is never a pull's answer. A question to the user is
> output, and the user's answer is a push, carrying the user's authority as §5 states
> it.

> **Normative.** The assistant's own writing never starts an activation.

> **Normative.** A kind declares which events in its medium are input. For the
> conversation, they are a new message and feedback on an entry, by a party other
> than the assistant; starting or deleting a conversation is not input.

> **Normative.** One input starts one activation. Duplicates are merged by the
> channel, speech is cut at the edge, and inputs waiting together are taken in as one
> (§11).

> **Normative.** A kind may filter pushes by rule, never by a model, and nothing
> filtered is lost.

Reminders activating only during working hours is such a filter.

> **Normative.** What a sensor notices by checking its medium periodically for
> changes is a push.

That is how an in-hub sensor watches a calendar file.

### 7. Output

> **Normative.** An actuator puts output on a channel, toward a place where the
> channel has places.

> **Normative.** Planning chooses the channel and the place of an output. Replying
> where the input came from is the usual case, not a rule.

**Proactivity needs nothing of its own.** A push from an in-hub sensor, such as a
timer coming due, starts an activation, and the activation writes into a place
through an actuator.

> **Normative.** Proactive output, notifications included, is written into a place
> through an actuator: the related conversation, or one kept for the assistant's
> notices. The user's devices tell the user about new entries by their settings, and
> no separate notification route is built.

> **Normative.** What counts as *sent* is the kind's. For the conversation, a message
> is sent once the medium has recorded it, whatever devices are showing the
> conversation.

### 8. Description and requirements

> **Normative.** A kind's description is given to planning, with what the user said
> when setting the channel up ("the kitchen; the kids are often around").

A kind's **requirements** are of three sorts, each enforced in one place:

| Requirement | About | Enforced |
| --- | --- | --- |
| **The medium's rules** | What a party may do in a hosted medium | By the hub as host, when a party acts |
| **The channel's rules** | What the assistant may send on the channel: text only, quiet hours | By the hub at the actuator, before anything leaves |
| **A spoke's limits** | What its hardware can do: streamed pieces, screen size | Reported by the spoke; facts, never permission |

> **Normative.** A hosted medium's rules are enforced by the hub, as host, when a
> party acts in it.

> **Normative.** A channel's rules are enforced by the hub at the actuator, before
> anything leaves, whatever a model produced.

> **Normative.** A spoke's limits are reported by the spoke, and are facts about what
> its hardware can do, never permission.

### 9. Audience

> **Normative.** The audience of an output is everyone who can perceive any surface
> that renders it, and the widest of them decides what may be said.

> **Normative.** What may be said for that audience is ADR-0199's: withheld at supply,
> before composing, never cut out afterwards. Where ADR-0199 speaks of an output
> channel, it reads, for output on the assistant's spokes, their channel, and for
> output into a hosted medium, the place.

> **Normative.** On the assistant's spokes, the audience is read from the channel:
> every spoke on a channel faces the same thing, so they share an audience.

The kitchen speaker's audience is whoever is in the kitchen, unbounded.

> **Normative.** In a hosted medium, the audience is read from the place. A place is
> shown on the devices the user chose for it, and choosing a device is the user's
> statement that its screen is private, whatever the device.

> **Normative.** A place's audience is its own record, never derived from admission
> (ADR-0199 §1:4).

> **Normative.** The user declares every bounded audience, by choosing a place's
> devices or by setting a channel up as private ("these are my earbuds"). An
> undeclared audience is unbounded (ADR-0199 §1:2).

> **Normative.** A spoke's rendering may make output more private than its audience
> requires, never less.

A notification on a lock screen shows no content unless the user chose previews, and
choosing previews is the user's declaration that the lock screen is private enough.

### 10. Window and history

> **Normative.** Understanding's "what came before" is what the sensor brings in from
> the medium with the new input, wherever the medium holds a history. Where it holds
> none, it is read from the episodes on that channel and place.

| Channel and place | Window |
| --- | --- |
| Conversation 7 | Its recent messages, from the hosted medium |
| The kitchen | Recent episodes in the kitchen |

A networked mailbox, where a thread's history could be pulled, is a future kind
needing its own ADR; today's email source is ADR-0140's local file of envelopes.

> **Normative.** The window belongs to the place, and a kind declares how much its
> window holds.

> **Normative.** A window's entries keep their authors, so the window informs and
> never authorizes: only the new input, sent as an instruction, can.

> **Normative.** An activation still running on the place is visible beside the
> window, not in it.

> **Normative.** Episodes are indexed by channel and place, and record the spokes the
> input came through.

> **Normative.** A channel's history is its episodes across its places, and a place's
> history is its own.

> **Normative.** Reads, deleting and forgetting are scoped to a place unless they say
> channel-wide.

> **Normative.** For the conversation, today's channel identity (`conversation`, id)
> is the place (the chat, that conversation), and every other channel identity today
> is a channel with no place.

### 11. Activations side by side

**The end state has no turns**, as the Concurrent activations direction already has
it.

> **Normative.** In the end state, every message is taken in when it lands and starts
> its own activation, and activations run side by side.

> **Normative.** Understanding judges how a new activation relates to one running,
> and a rule acts on the judgment. Unrelated, both continue. If the new one changes,
> cancels or adds to the running work, the older is stopped and the newer carries on,
> seeing the older's progress.

> **Normative.** Merging and taking over are one mechanism.

> **Normative.** The end state owes, before it runs: a lock and recheck on what is
> acted on ([#2586](https://github.com/leonapivato/ai-assistant/issues/2586)); waiting
> once, before an action, for the user's inputs not yet understood; and a stopped
> activation never writing new output into a place.

> **Normative.** Until the end state is built, a conversation runs one activation at a
> time. A message sent while one runs lands in the medium and waits, and is never
> refused; everything waiting is taken in as one input when the running activation
> ends.

> **Normative.** Moving from that interim to the end state changes only when the
> sensor takes messages in.

> **Normative.** Whether an activation is running on a place is the assistant's
> current state, shown to the place's devices and never written into the medium.

### 12. What stays from ADR-0290

These stand as ADR-0290 decided them, with "the assistant" for "the hub". ADR-0290's
rules that the input never names its channel and that a channel's identity grants
nothing are restated in §5.

> **Normative.** An **inside action**, one whose effect changes only the assistant's
> own records (writing or forgetting a memory, linking a story, setting a timer,
> abandoning a goal), runs directly, with no channel and no actuator.

> **Normative.** An inside action is still an action: planning chooses it,
> authorizing checks it, acting runs it, and its effect is recorded.

> **Normative.** Every read of the assistant's own records, recall and the current
> time included, is direct and travels on no channel. A record is read with the
> provenance it was stored with.

> **Normative.** A call to a language model or an embedder is processing, not output.
> It is not an action, it has no channel and no actuator, and it stays under the
> egress rule ADR-0174 §1 states for `models/`.

> **Normative.** A command's authority is the user's explicit act: a structured act on
> a device that may send commands, naming one operation, never words a model
> interprets.

> **Normative.** A message never becomes a command. The same operation asked for in
> words is input like any other.

### 13. What retires

| Mechanism | Function kept by |
| --- | --- |
| Activating and service as kinds' sorts (ADR-0290 §1:6) | Push and pull per input (§6) |
| The caller naming the channel; the reply on the request (ADR-0274 §2–§4) | The conversation channel |
| `receive`, informational events from any admitted caller (ADR-0274 §7) | A spoke on a channel the user set up, per source |
| `answer`, a question answered by id (ADR-0078) | A reply in the place where the assistant asked |
| `learn`, feedback by command (ADR-0022) | Feedback on the entry it is about, an act in the medium the assistant perceives |
| `resume` and its own path (ADR-0052, ADR-0280 §1:4) | What was waited for arriving as a push, linked to the parked work through its story |
| The notification route and its preferences (`next_notification`, ADR-0131) | Writing into a place (§7) |
| Readers' scheduled ingestion into memory (ADR-0093) | Pulls when relevant and pushes for changes; memory keeps what activations conclude |

> **Normative.** Each mechanism the table names retires when its replacement is
> built, not before, and until then it keeps working as its own ADR decides it. The
> activating and service sorts, which nothing built, retire with ADR-0290.

> **Normative.** Each mechanism's replacement keeps the function the table names for
> it.

> **Normative.** A reader's context facet becomes a pull, and the upcoming-event
> producer (ADR-0132) a push, on the reader's channel.

### 14. Relationship to earlier decisions

> **Normative.** This ADR supersedes ADR-0290 and ADR-0291 whole, and ADR-0283 in the
> one scope its header names. It supersedes no clause of any other ADR: every other
> route §§1–13 rule against stays in force under the Decision's opening clause.

> **Normative.** This numbered draft records its replacements on the status line and
> in a dated header note of ADR-0290, ADR-0291 and ADR-0283, atomically with this ADR
> under ADR-0070 and ADR-0082, preserving their ratified bodies. The replacements take
> effect on this ADR's ratification.

| Earlier decision | Where it goes |
| --- | --- |
| ADR-0290 §1 (a channel held by the hub; kinds, identity, window; the sorts) | §2, §6, §10; the sorts retire |
| ADR-0290 §1:4–§1:5 (the input never names its channel; identity grants nothing) | §5 |
| ADR-0290 §1:7 (description and requirements) | §8 |
| ADR-0290 §§2–4 (crossings of the hub's edge; sensors; actuators) | §1, §4, §6, §7, §8, the edge being the assistant's. §4:4's report by the actuator is not restated: what counts as sent is the kind's (§7) |
| ADR-0290 §4:5 (model calls), §5 (inside actions), §6 (direct reads), §7:2–§7:4 (commands) | §12 |
| ADR-0290 §7:1 (hub operations by rule) | §4 |
| ADR-0291 §§1–6 (a channel's record) | §3, on a hosted medium's content; channels keep nothing |
| ADR-0291 §7 (the kinds that exist today) | The Decision's opening clause |
| ADR-0283 §1 | §10, as the header states |

## Consequences

**What becomes clear.** Every channel decision after this one has one model to
apply. A camera, a speaker and two kitchen microphones fit it as well as a chat does,
because the channel is the assistant's group of spokes rather than the medium. The
user's phone in a conversation is the user's end of it, so the assistant's line and
the shared medium no longer compete for one concept. Authority rests on an author the
hub establishes, so a reminder, a forwarded email or pasted text cannot pass as the
user's instruction. Proactivity and notifications need no route of their own:
anything that starts an activation can write into a place.

How it goes, worked through:

| Situation | How it goes |
| --- | --- |
| The user types "book the campsite" | An act in the medium; the chat's sensor takes it in; a push, author the user, established, now; an activation starts with the conversation's recent messages as its window. |
| Then "for Saturday", while that runs | Lands in the conversation. In the end state it starts its own activation, which understanding judges to add to the booking, so it takes over; until then it waits and is taken in when the first ends. |
| "What's on Friday?" | A pull on the calendar channel; the answer returns to the asking activation. |
| The booking service answers after a timeout | The asker has ended, so it is a push and starts an activation of its own. |
| The assistant asks "Saturday or Sunday?" | Output into the conversation. The user's "Sunday" is a push carrying their authority. |
| A reminder set on Monday comes due | A push from the timer; author the user, written Monday; it informs and authorizes nothing. |
| "Add milk" said in the kitchen | Speech released at the edge; a push, author unknown; quarantined unless a voice match the user set up establishes them. |
| A meeting moves | The calendar's sensor notices the change; a push; the activation may write a warning into a place. |

**What it costs.** Nothing changes in code now. The mechanisms §13 names, today's
channel windows and the conversation's history and deletion stand in tension with
§§1–13 until each is replaced, and each replacement is its own ADR. One message can
be held twice, in the conversation and in an episode, by design, and forgotten
content can come back through a window; the user's remedy is deleting from the
medium, where its kind allows it.

**What follows from it.**

1. **The conversation channel** ([#2680](https://github.com/leonapivato/ai-assistant/pull/2680)),
   rewritten on this model: the hub's chat space as a hosted medium, conversations
   as places, the transcript, acts in the medium, and §11's interim. It owes the
   supersession, for the chat, of ADR-0276 §3:1–§3:2's conversation window and of
   ADR-0283 §4:1's history read and §8:1's deletion.
2. **The device session**: roles, one connection per device, the three routes,
   catching up.
3. **Stopping an activation**: the command, and the stop takeover uses.
4. **Activations side by side**: the concurrency milestone.
5. **The retirements of §13**, each with its replacement.

**What stays open.** None of these is decided here, and each names where it lands.

- **A word for in-hub sensors and actuators.** ADR-0094 §1:1 calls a spoke an
  *attachment* across the process boundary, and §1:2 rules that an in-hub producer
  is not one. Either "attachment" names both, with "spoke" kept for the device kind,
  or ADR-0094 §1 is amended.
- **Placed and carried channels.** A room the user names, with devices placed into
  it, against a phone's microphone that faces whatever is around the user. Voice's.
- **Merging what several spokes picked up**, beyond taking a duplicate in once.
  Voice's.
- **The lock key** for activations side by side
  ([#2586](https://github.com/leonapivato/ai-assistant/issues/2586)).
- **Transport**: how one connection per device is built, WebSocket or the existing
  delivery poll. The device session's.
- **Each kind's push filter**, decided with the kind.
- **More than one person in a medium**, where each message carries its own author.
- **What may take over running work.** The concurrency milestone's; the Concurrent
  activations direction's limits stand meanwhile.
- **Binding an answer to its question.** The conversation channel's and
  authorizing's.
- **Processing bookkeeping**: which inputs were taken in, and by which activation.
  "Channels keep nothing" means no record of what was carried, not no bookkeeping.
  The conversation channel's.
- **Existing permissions**: the source grants and notification preferences, mapped
  by each retirement's ADR.
- **Correcting a running action before takeover exists.** The conversation
  milestone's sequencing.
- **Who can start a conversation.** The device session's.
- **ADR-0290's two other open questions**, which this decision does not touch:
  whether a reply is delivered as an action
  ([#2593](https://github.com/leonapivato/ai-assistant/issues/2593)), and which
  commands a device confirms first.

## Alternatives considered

- **The channel is the medium** (ADR-0290 and ADR-0291). It works where the hub
  holds the medium, and nowhere else.
- **The channel is one-to-one with a spoke, and the medium a separate entity
  grouping them.** Considered on 2026-10-04: it keeps a channel concrete, but needs a
  third concept for what the spokes face. Declined for the owner's rule that a spoke
  attaches to one channel, which makes the channel that grouping.
- **Sensors and actuators always run in the hub.** Declined: a camera is the
  assistant's eye and a speaker its mouth.
- **Activating and service as kinds' sorts.** Declined: email, a calendar and the
  conversation each both push and answer pulls. The owner's 2026-09-28 analogy for
  the sorts, a watch glanced at and an alarm going off, was already push and pull.
- **Refusing a message sent while the assistant works** (the conversation proposal's
  earlier turn rule). Declined: it has the assistant's state block a shared medium,
  and takeover needs the correction to land.
- **Live steering by injection**, feeding a new message into the running activation.
  Declined: it breaks one input per activation and an episode per input, and leaves
  the authorization of a changed request inside a running activation.
- **Readers ingesting into memory, with or without an activation per item.**
  Declined: the calendar and mailbox already hold their history, and a copy in memory
  goes stale.
