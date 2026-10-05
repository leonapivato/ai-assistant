# Channels, rethought

**The question.** What is a channel, once it stops being both the medium the assistant
meets and the assistant's line to it; and what follows for spokes, devices, input,
output, audience, history and the routes that exist today?

ADR-0290 and ADR-0291, both decided on 2026-10-04, drew a channel as the medium itself
(a chat, held by the hub) and gave it the jobs of the assistant's line to it as well.
Reviewing the conversation channel
([#2680](https://github.com/leonapivato/ai-assistant/pull/2680)) with the owner the same
day showed that the two cannot be one thing: a camera's medium is a room the hub cannot
hold, two microphones in one kitchen are one exchange, and the user's phone in a chat is
the user's end of it, not the assistant's. The owner then walked the model through item
by item. This proposal records the result. It would **supersede ADR-0290 and ADR-0291 in
full**, restating what survives (§12), and it is the model the conversation channel, the
device session and stopping an activation then apply.

## Baseline

Wiki pages, read at wiki revision
[`b95617b`](https://github.com/leonapivato/ai-assistant/wiki/Channels/b95617b24abc2f1bbef5997ecf4b36eb6056bbc6):
[Channels](https://github.com/leonapivato/ai-assistant/wiki/Channels),
[Channel window](https://github.com/leonapivato/ai-assistant/wiki/Channel-window),
[Sensors](https://github.com/leonapivato/ai-assistant/wiki/Sensors),
[External sensors](https://github.com/leonapivato/ai-assistant/wiki/External-sensors),
[Internal sensors](https://github.com/leonapivato/ai-assistant/wiki/Internal-sensors),
[Push](https://github.com/leonapivato/ai-assistant/wiki/Push),
[Actuators](https://github.com/leonapivato/ai-assistant/wiki/Actuators),
[Concurrent activations](https://github.com/leonapivato/ai-assistant/wiki/Concurrent-activations),
[Controller](https://github.com/leonapivato/ai-assistant/wiki/Controller) and
[Authorizing](https://github.com/leonapivato/ai-assistant/wiki/Authorizing).

| ADR | What it decides today | What this proposal would do |
| --- | --- | --- |
| ADR-0290 | A channel is the medium, held by the hub, needed exactly where something crosses the hub's edge; kinds are activating or service; inside actions, own-record reads and hub operations are direct. | Supersede in full. The edge becomes the assistant's (§1); a channel becomes a group of spokes (§2); the sorts become per input (§6). What survives is restated (§12). |
| ADR-0291 | A channel's record is its own; what it keeps is its kind's choice; forgetting never reaches it; deleting from it is the user's command; it is the user's data. | Supersede in full. Channels keep nothing; a **hosted medium** keeps its own content, and ADR-0291's rules move onto it (§3). |
| ADR-0283 §1 | Episodes are numbered and indexed by channel (type and instance); ADR-0291 limited §1:2's order to a channel's episodes. | Amend: episodes are indexed by channel and place, and record the spokes the input came through (§10). |
| ADR-0274 | The caller names the channel and the reply rides the request; informational events from any admitted caller. | Retire, when the conversation channel's ADR and per-source channels replace them (§13). |
| ADR-0094 | A spoke is an *attachment* across the process boundary; "client", "sensor" and "actuator" are profile names; the edge dials out, releases before sending, detects but does not distil; the hub decides the band. | Kept. Every obligation binds a device's spokes unchanged. The profile names line up: a party's end of a medium is a client, and the assistant's sensors and actuators on a device are spokes on a channel. In-hub sensors and actuators are attachments that are not spokes in ADR-0094's sense (open, below). |
| ADR-0199 §1 | Audience is the output channel's; undeclared is unbounded; never derived from admission. | Kept, and placed: audience is read from the channel or the place, declared by the user, and narrowed but never widened by a spoke (§9). |
| ADR-0052, ADR-0078, ADR-0073/0077, ADR-0280 §1 (resume) | Durable resume, questions answered by id, feedback by command, resume's own path. | Retire as mechanisms; their functions are kept by the model (§13). |
| ADR-0093, ADR-0140, ADR-0132 | Calendar and email readers feed a context facet, a scheduled ingestion into memory, and an upcoming-event producer. | The reader is an in-hub sensor on its channel. The facet becomes a pull and the producer a push; scheduled ingestion retires (§13). |

## The model

### 1. The assistant's edge

The edge that matters is the **assistant's**, not the hub's machine. The hub runs things
that are not the assistant: the clock, and any medium it hosts, such as the
conversations.

> The assistant perceives and acts only through its sensors and actuators, and each
> reaches it on a channel. What it reads and changes of its own records, it does
> directly. The user can also operate on it directly, by command, which it does not
> perceive.

The crossing happens at the sensor or actuator, where perceiving and acting happen. The
channel is behind it, on the assistant's side.

### 2. Spokes, channels and places

| Concept | Is | Holds |
| --- | --- | --- |
| **Spoke** | A set of sensors and actuators that face one thing, on a device or in the hub | Capture and release, rendering, what its hardware can do, whether it is reachable, its own state |
| **Channel** | The group of spokes facing one thing: the kitchen, the hub's chat space, a mailbox | Source, authority, audience, window, history, permission; merging what its spokes picked up |
| **Place** | An address within what a channel faces: a conversation, an email thread | The place's own rules: its devices, deleting it |

- **A spoke attaches to exactly one channel. A channel has many spokes.** Two
  microphones in one kitchen are two spokes on one channel, and the channel takes a
  sentence both heard in once.
- **A device whose sensors and actuators face different things connects as separate
  spokes**: earbuds face the user's ear and the phone's speaker the room, so they are two
  spokes on two channels.
- **A channel's identity is what the user named it** ("the kitchen", "alice@… mail"), or
  is built in (the hub's chat space, the clock). It exists because it is built in or
  because the user connected it; connecting an account creates its channel.
- **A spoke attaches because the user placed it facing that channel's thing**, and only
  if the channel's kind takes its sort of sensor or actuator. A spoke cannot attach
  itself.
- **A channel persists when its spokes go**: it is unreachable until one returns, and its
  history continues. Planning is told an unreachable channel is unavailable.
- **The assistant never creates a channel or attaches a spoke.** It cannot widen what it
  senses or where it speaks.
- **A kind declares what spokes it takes, and so its directions**: a sensor for in, an
  actuator for out. Every channel of a kind follows the same rules, and a direction
  declared need not be used.

### 3. Hosted media

A **hosted medium** is a medium the hub holds itself, so that both the assistant and
another party read and write it there. The hub's chat space is the first: each
conversation is a place in it. A shared shopping list would be another.

**Channels keep nothing.** Everything a channel record would hold is already held: a
conversation's text by the hosted medium, what the assistant perceived and did by its
episodes, an email by the mail server. A hosted medium keeps its own content, under the
rules ADR-0291 gave a channel's record:

- **Separate from memory.** Recall does not search it and consolidation does not read
  it. A message can be in the conversation and in an episode; the two are never kept in
  step.
- **What it holds is its kind's**: shape, order, retention, and what may be deleted.
- **Forgetting never reaches it.** Forgotten content can come back through the window
  (§10), as a person who forgot a night can still find the texts they sent; the
  interface shows that, and says plainly that only deleting removes it.
- **Deleting from it is the user's act in the medium** (§4), where its kind allows it.
  The assistant has no action that deletes. Deleting does not forget.
- **It is the user's data**: Tier 1 under ADR-0004 §1, viewable, exportable and
  deletable under §6, purged whole when the user's data is deleted.

### 4. Devices and their routes

A device can be three things at once, each assigned by the user:

| Role | Example | Assigned by |
| --- | --- | --- |
| The user's **end of places** in a hosted medium | The phone in conversations 7 and 9 | Choosing the device for each conversation |
| **Host of spokes** | The kitchen speaker; the phone's microphone, if allowed | Placing each spoke facing a channel's thing |
| **Source of commands and queries** | The phone and laptop | Pairing; a newly paired device has no role until given one |

What a device sends travels one of three routes, told apart by the structured kind of
the message and never by its content:

| Route | What it is | Reaches the assistant |
| --- | --- | --- |
| **Spoke traffic** | The assistant's sensors and actuators at work | On their channel |
| **An act in a medium** | A party doing something in a hosted medium: writing a message, starting or deleting a conversation | Only when the channel's sensor notices it |
| **A command or query** | The user operating on the assistant, or reading its records | Never perceived; carried out by rule |

The test between the last two is what changes: an act in a medium changes the medium
(deleting a conversation removes it from the chat), a command changes the assistant
(forgetting a conversation removes its episodes and leaves the chat as it was). An act in
a medium needs the same bar as a command: a structured act, from a device that is the
user's end of that place. The hub, as host, applies the medium's rules; no model is
involved.

**Writing and perceiving are two steps.** The medium accepts a message, records it and
answers *received* with its position; then the channel's sensor takes it in. A message
lands even when the assistant cannot take it in at once. The assistant's own messages
go the other way: its actuator writes into the medium, and the user's devices read them
there.

One connection per device carries all three routes. Revoking a device closes it, removes
it as an end of every place and makes its spokes unreachable; ADR-0124's admission stays
the gate in front of it.

### 5. Input: source, author and authority

> Every input arrives with its **channel**, its **place** and its **author**, all stated
> by the hub and never by its content. The spokes it came through are recorded as how it
> arrived.

An **author** is:

| Part | Values |
| --- | --- |
| **Who** | The user; a known person; an unidentified person; a service; the assistant |
| **How sure** | Established; claimed, recording who it claims to be; unknown |
| **When written** | Usually as it arrived; earlier for something written in advance |

Each kind declares how it establishes authors: in a conversation, only the user's ends
can write, so a message is the user's, established; in a kitchen anyone could speak, so
the speaker is unknown; an email's sender is claimed; a reminder's author is whoever set
it, at the time they set it.

> Input carries the user's authority only when its author is established as the user,
> writing now. Everything else informs and cannot authorize.

- A reminder the user set informs the activation it starts and authorizes nothing: the
  user wrote it then, not now.
- Content never claims authorship, and a channel's identity grants nothing.
- A spoke's evidence (a face unlock, a voice match) counts toward establishing the user
  only where the kind allows it and the user set it up, such as by enrolling a voice.
  Nothing a spoke reports raises authority by itself (ADR-0094 §5).

### 6. Push, pull and doorbell

Whether input starts an activation is decided per input, not per kind:

- A **push** is input nobody asked for: a message, new mail, a reminder coming due. On
  its channel it starts an activation, subject to the kind's filter.
- A **pull** is the assistant asking and the far side answering within that request: a
  forecast, a mailbox search, earlier messages in a conversation. The answer returns to
  the activation that asked.
- A **doorbell** says something is waiting without saying what. It is a push, and the
  activation it starts pulls the content (ADR-0094 §1:3).

A kind declares whether it can be pulled and whether it pushes. Email does both, so does
a calendar, so does the conversation; search only answers pulls; a timer only pushes.

- **A pull's answer returns only while the asker waits.** One arriving after the asker
  ended, or a second time, is a push, and starts an activation of its own.
- **A person's reply is never a pull's answer.** A question to the user is output; the
  user's answer is a push that carries their authority.
- **The assistant's own writing never starts an activation**, and a kind declares which
  events in its medium are input: for the conversation, a new message by a party other
  than the assistant. Starting or deleting a conversation is not input.
- **One input starts one activation.** Duplicates are merged by the channel, speech is
  cut at the edge, and inputs waiting together are taken in as one (§11).
- **A kind may filter pushes by rule, never by a model**, such as mail from known
  contacts activating and the rest staying in the mailbox. Nothing filtered is lost.

A sensor may check its medium periodically to notice what changed; what it notices is a
push. That is how an in-hub sensor watches a calendar file.

### 7. Output

An actuator puts output on a channel, toward a place where the channel has places:
"send this into conversation 9". Planning chooses the channel and place; replying where
the input came from is the usual case, not a rule.

**Proactivity needs nothing of its own.** A push from an in-hub sensor, such as a timer
coming due, starts an activation, and the activation writes into a place through an
actuator. **Notifications are the same**: proactive output is written into a place, the
related conversation or one kept for the assistant's notices, and the user's devices tell
the user about new entries by their settings. The separate notification route retires.

What counts as *sent* is the kind's. For the conversation, a message is sent once the
medium has recorded it, whatever devices are showing the conversation.

### 8. Description and requirements

A kind's **description** is given to planning, with what the user said when setting the
channel up ("the kitchen; the kids are often around").

Its **requirements** are of three sorts, each enforced in one place:

| Requirement | About | Enforced |
| --- | --- | --- |
| **The medium's rules** | What a party may do in a hosted medium | By the hub as host, when a party acts |
| **The channel's rules** | What the assistant may send on the channel: audience, text only, quiet hours | By the hub at the actuator, before anything leaves |
| **A spoke's limits** | What its hardware can do: streamed pieces, screen size | Reported by the spoke; facts, never permission |

### 9. Audience

> The audience of an output is everyone who can perceive any surface that renders it,
> and the widest of them decides what may be said (ADR-0199).

- **On the assistant's spokes, it is read from the channel.** Every spoke on a channel
  faces the same thing, so they share an audience: the kitchen speaker's is whoever is in
  the kitchen, unbounded.
- **In a hosted medium, it is read from the place.** A conversation is shown on the
  devices the user chose for it, and **choosing a device is the user's statement that its
  screen is private** (owner, 2026-10-04), whatever the device. It is its own record,
  never derived from admission (ADR-0199 §1:4).
- **The user declares every bounded audience**, by choosing a conversation's devices or
  by setting a channel up as private ("these are my earbuds"). Undeclared is unbounded.
- **A spoke can only narrow.** Its rendering may make output more private, never less: a
  notification on a lock screen shows no content unless the user chose previews.

### 10. Window and history

> Understanding's "what came before" is what the sensor brings in from the medium with
> the new input, wherever the medium holds a history. Where it holds none, it is read
> from the episodes on that channel and place.

| Channel and place | Window |
| --- | --- |
| Conversation 7 | Its recent messages, from the hosted medium |
| An email thread | The earlier mail in the thread, pulled from the mail server |
| The kitchen | Recent episodes in the kitchen |

The window belongs to the place. Its entries keep their authors, so it informs and never
authorizes: only the new input, written now, can. An activation still running on the
place is visible beside the window, not in it. A kind declares how much its window
holds.

**Episodes are indexed by channel and place**, and record the spokes the input came
through. A channel's history is its episodes across its places; a place's history is its
own. For the conversation this is a rename of today's (`conversation`, id).

### 11. Activations side by side

**The end state has no turns.** Every message is taken in at once and starts its own
activation, and activations run side by side, as the Concurrent activations direction
already has it:

- **Understanding judges how a new activation relates to one running**; a rule acts on
  the judgment. Unrelated, both continue. If it changes, cancels or adds to the running
  work, the older is stopped and the newer carries on, seeing the older's progress.
  Merging and taking over are one mechanism.
- **Still owed**: a lock and recheck on what is acted on
  ([#2586](https://github.com/leonapivato/ai-assistant/issues/2586)), waiting once before
  an action for the user's inputs not yet understood, and a stopped activation never
  writing.
- **Until that is built**, a conversation runs one activation at a time: a message sent
  while one runs lands in the medium and waits, never refused, and everything waiting is
  taken in as one input when it ends. Changing to the end state changes only when the
  sensor takes messages in.

Whether an activation is running on a place is the assistant's current state, shown to
the place's devices and never written into the medium.

### 12. What stays from ADR-0290

With "the assistant" for "the hub", these stand as ADR-0290 decided them:

- A channel's identity grants nothing; the input never names its channel (§5).
- An **inside action**, one whose effect changes only the assistant's own records
  (writing or forgetting a memory, linking a story, setting a timer, abandoning a goal),
  runs directly, with no channel and no actuator, and is still planned, authorized,
  acted and recorded.
- Every read of the assistant's own records, recall and the current time included, is
  direct. A record is read with the provenance it was stored with.
- A call to a language model or an embedder is processing, not output, under ADR-0174
  §1.
- A **command**'s authority is the user's explicit act: a structured act on a device that
  may send commands, naming one operation, never words a model interprets. A message never
  becomes a command; the same operation asked for in words is input like any other.

### 13. What retires

Each retires when its replacement is built, not before; until then it keeps working.

| Mechanism | Function kept by |
| --- | --- |
| Activating and service as kinds' sorts | Push and pull per input (§6) |
| The caller naming the channel; the reply on the request (ADR-0274) | The conversation channel |
| `receive`, informational events from any admitted caller | A spoke on a channel the user set up, per source |
| `answer`, a question answered by id (ADR-0078) | A reply in the place where the assistant asked |
| `learn`, feedback by command | Feedback on the entry it is about, an act in the medium the assistant perceives |
| `resume` and its own path (ADR-0052, ADR-0280 §1) | What was waited for arriving as a push, linked to the parked work through its story |
| The notification route and its preferences | Writing into a place (§7) |
| Readers' scheduled ingestion into memory (ADR-0093) | Pulls when relevant, pushes for changes; memory keeps what activations conclude |

The reader's context facet becomes a pull and the upcoming-event producer (ADR-0132) a
push, on the reader's channel.

## Examples

| Situation | How it goes |
| --- | --- |
| The user types "book the campsite" | An act in the medium; the chat's sensor takes it in; a push, author the user, established, now; an activation starts with the conversation's recent messages as its window. |
| Then "for Saturday", while that runs | Lands in the conversation. In the end state it starts its own activation, which understanding judges to add to the booking, so it takes over; until then it waits and is taken in when the first ends. |
| "Did the campground confirm?" | A pull on the email channel; the answer returns to the asking activation. |
| The booking service answers after a timeout | The asker has ended, so it is a push and starts an activation of its own. |
| The assistant asks "Saturday or Sunday?" | Output into the conversation. The user's "Sunday" is a push carrying their authority. |
| A reminder set on Monday comes due | A push from the timer; author the user, written Monday; it informs and authorizes nothing. |
| "Add milk" said in the kitchen | Speech released at the edge; a push, author unknown; quarantined unless a voice match the user set up establishes them. |
| A meeting moves | The calendar's sensor notices the change; a push; the activation may write a warning into a place. |

## Options considered

**The channel is the medium** (ADR-0290 and ADR-0291). It works where the hub holds the
medium, and nowhere else.

**The channel is one-to-one with a spoke, and the medium a separate entity grouping
them.** Considered on 2026-10-04: it keeps a channel concrete, but needs a third concept
for what the spokes face. Declined for the owner's rule that a spoke attaches to one
channel, which makes the channel that grouping.

**Sensors and actuators always run in the hub.** Declined: a camera is the assistant's
eye and a speaker its mouth.

**Activating and service as kinds' sorts.** Declined: email, a calendar and the
conversation each both push and answer pulls. The owner's 2026-09-28 analogy for the
sorts, a watch glanced at and an alarm going off, was already push and pull.

**Refusing a message sent while the assistant works** (the conversation proposal's
earlier turn rule). Declined: it has the assistant's state block a shared medium, and
takeover needs the correction to land.

**Live steering by injection**, feeding a new message into the running activation.
Declined: it breaks one input per activation and an episode per input, and leaves the
authorization of a changed request inside a running activation.

**Readers ingesting into memory, with or without an activation per item.** Declined:
the calendar and mailbox already hold their history, and a copy in memory goes stale.

## What it leaves open

- **A word for in-hub sensors and actuators.** ADR-0094 §1 calls a spoke an
  *attachment* across the process boundary and rules that an in-hub producer is not one.
  Either "attachment" names both, with "spoke" kept for the device kind, or ADR-0094 §1 is
  amended.
- **Placed and carried channels.** A room the user names, with devices placed into it,
  against a phone's microphone that faces whatever is around the user. Voice's.
- **Merging what several spokes picked up**, beyond taking a duplicate in once. Voice's.
- **The lock key** for activations side by side ([#2586](https://github.com/leonapivato/ai-assistant/issues/2586)).
- **Transport**: how one connection per device is built, WebSocket or the existing
  delivery poll. The device session's.
- **Each kind's push filter**, decided with the kind.
- **More than one person in a medium**, where each message carries its own author.

## What follows

1. **The conversation channel** ([#2680](https://github.com/leonapivato/ai-assistant/pull/2680)),
   rewritten on this model: the hub's chat space as a hosted medium, conversations as
   places, the transcript, acts in the medium, the interim of §11.
2. **The device session**: roles, one connection per device, the three routes, catching
   up.
3. **Stopping an activation**: the command, and the stop takeover uses.
4. **Activations side by side**: the concurrency milestone.
5. **The retirements of §13**, each with its replacement.
