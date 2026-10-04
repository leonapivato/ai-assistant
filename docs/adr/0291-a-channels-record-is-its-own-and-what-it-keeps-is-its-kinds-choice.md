# 291. A channel's record is its own, separate from memory, and what it keeps is its kind's choice

- Status: Accepted
- Date: 2026-10-04
- Scope: [#2578](https://github.com/leonapivato/ai-assistant/issues/2578), the channel redesign: what any channel may keep, between ADR-0290 (what a channel is and where one is needed) and the text chat channel ([#2680](https://github.com/leonapivato/ai-assistant/pull/2680)), which applies this decision to one kind.
- Authorization: the owner accepted proposal #2681 on 2026-10-04, at `440f15a0`, and the dispatcher assigned 0291. This ADR is that proposal converted under `docs/proposals/README.md` → "When it is decided".
- **Partially supersedes** [ADR-0290](0290-a-channel-is-needed-exactly-where-something-crosses-the-hubs-edge.md) — **one scope.** **§1:3, in its *a window of what it recently carried* part alone**: a channel has a window only where its kind offers one, and the window is read from the channel's record (§3 below). A channel's kind, the identity the hub states and what its kind declares stand, and so does every other clause.
- **Partially supersedes** [ADR-0283](0283-a-channels-history-is-its-episodes-and-the-turn-index-is-retired.md) — **one scope.** **§1:2, as a general rule about a channel**, *"A channel's order is its episodes' numbers, ascending. No reader orders a channel's history by timestamp or by id."*: it orders a channel's episodes, and binds no channel's own record, whose order is its kind's choice (§3 below). §1's numbering and channel index of episodes, ordering a channel's episodes by number, and the conversation-specific §4, §6 and §8 stand, and so does every other clause.

## Context

**The question.** Does a channel keep its own record of what it carried, separate
from the assistant's memory? If it does, who decides what that record holds, and
what do forgetting and deleting do to it?

ADR-0290 says what a channel is and where one is needed. This decision says what any
channel may keep. The text chat channel's decision then applies it to one kind. No
kind keeps a record of its own today, so nothing behaves differently on the day this
is decided; the first kind to keep one is the text chat.

**The owner's rulings of 2026-10-04**, which this ADR records in full so that nothing
here depends on a text that can change after it:

- a channel is a medium, tied to neither the device that reaches it nor the
  assistant;
- what a channel keeps is its kind's choice, and there is no generic channel record;
- a channel's record and the assistant's memory are independent, and forgetting
  never reaches the channel's record, at the accepted cost that forgotten content can
  come back through a channel's window;
- deleting from a channel is the user's remedy, where the kind allows it.

**The ADRs this touches**, as they stand on `main`:

| ADR | What it decides today | How this decision relates |
| --- | --- | --- |
| ADR-0290 §1:3 | *"Every channel has a kind, an identity the hub states, a window of what it recently carried, and what its kind declares."* | Partially superseded, in its window part alone: whether a channel has a window is its kind's choice (§3). Kind, identity and declarations stand. |
| ADR-0283 §1:2, and its title | Its title's rule, *"A channel's history is its episodes"*: the channel is an index over the assistant's episodes, with no record of its own. §1:2 states it as a rule: *"A channel's order is its episodes' numbers, ascending. No reader orders a channel's history by timestamp or by id."* | Retired as a general rule: a channel's record, where its kind keeps one, is its own (§2), ordered as its kind declares (§3). §1:2 keeps ordering a channel's episodes. §1's numbering and channel index of episodes stand. |
| ADR-0283 §4:1, §6, §8:1 | The conversation's history is read from its channel's episodes by `ConversationLifecycle.history`; the conversation store keeps the conversation; deleting a conversation deletes its channel's episodes. | Unchanged. They are conversation-specific, and stay in force under the Decision's opening clause until the text chat channel's ADR decides them for the chat. |
| ADR-0276 §3:1–§3:2 | The **channel window** of an activation: for the conversation, its tail as `ConversationLifecycle.history` reads it; for any other channel, exactly the context the submitter attached, `ChannelInput.context.history` followed by `ChannelInput.context.reply_to`. *"The assistant keeps no per-channel history table and no per-channel count."* | Unchanged. Neither window is read from a channel's own record, so §3 rules against both, and both stay in force under the Decision's opening clause until the ADR that builds a kind's record and window supersedes them for that kind. |
| ADR-0004 §1, §6 | Tier 1 is personal data. The user can view, export and delete their data, and deleting the user's data purges Tier 0 and Tier 1 together. | Kept, and stated to reach channel records (§6). |
| ADR-0286 | An episode records one activation, opened at admission and frozen at its end. | Unchanged. Episodes stay the assistant's experience; nothing here changes what they hold. |

**What exists.** No channel kind keeps a record of its own. The conversation channel
reads its history and its window from its episodes (ADR-0283 §4:1, ADR-0276 §3:1).
The spoken turn runs on the conversation channel, quarantined at its edge
(ADR-0280 §2:2), and takes the same tail with no episode window (ADR-0276 §4:13).
Informational events get, as their window, whatever context the submitter attached
to the input (ADR-0276 §3:1), which `orchestration/understanding.py` renders as items
the channel supplied.

## Decision

We will treat what a channel carried as the channel's own, kept, where its kind keeps
it, separately from the assistant's memory, with each kind choosing what it keeps.

> **Normative.** §§1–7 govern every channel kind an ADR decides or an implementation
> builds from this ADR on. A route that exists on `main` when this ADR is ratified and
> that §§1–7 rule against, including ADR-0276 §3:1–§3:2's channel windows and
> ADR-0283 §4:1's and §8:1's conversation history and deletion, stays in force exactly
> as its own ADR decides it until a later ADR that builds its replacement supersedes
> that ADR's clause.

### 1. A channel is a medium, tied to neither end

ADR-0290 §1:1 already holds the first half: a channel is held by the hub, and a
device that reaches it holds no channel of its own. This is the other half.

> **Normative.** A channel is not the assistant's. What a channel carried is a fact
> about the channel, and not part of what the assistant remembers.

A conversation is the plain case: the messages are on the conversation, whoever later
remembers or forgets them.

### 2. A channel's record is its own, separate from memory

> **Normative.** Where a channel's kind keeps a record, the record is the channel's
> own, held inside the hub and separate from the assistant's memory.

> **Normative.** A channel's record and the assistant's memory are independent:
> neither is derived from the other, and neither is kept in step with the other.

> **Normative.** A channel's record is not memory. Recall does not search it, and
> consolidation does not read it.

- **Episodes** are the assistant's experience of an activation: what it perceived,
  did and concluded. They are memory, and recall, consolidation and forgetting act on
  them.
- **A channel's record** is what crossed the channel, as the kind keeps it.

One event may appear in both: a message is on the chat, and the activation it started
has an episode. That is not one event recorded twice in the sense ADR-0283 retired.
ADR-0283 retired the turn index because it was a *second copy of the same history*
that had to be kept consistent with the first. Here the two records answer different
questions, are kept by different owners, and are never reconciled, so there is no
consistency to keep.

### 3. What a channel keeps is its kind's choice

> **Normative.** There is no generic channel record: no record that every kind uses,
> and no shape, order or retention that every kind's record must take.

> **Normative.** Each channel kind declares what it keeps, alongside its description
> and requirements (ADR-0290 §1:7): whether it keeps a record at all; what the record
> holds; whether it is ordered, and by what; how long it is kept; and whether it
> offers a window, and what the window is read from.

A kind may keep nothing. A record may hold messages, receipts, or nothing but a
count. The hub still knows the order in which it received activations, whatever a
channel keeps, so a kind that keeps no order loses nothing the hub needs.

> **Normative.** Where a kind offers a window, understanding's "what came before on
> this channel" is read from the channel's record, and is not rebuilt from episodes.

> **Normative.** A kind that keeps no record offers no window.

### 4. Forgetting acts on memory alone

> **Normative.** Forgetting is the assistant's act on its own memory, and it never
> reaches a channel's record.

If the assistant forgets something that was said on a chat, the message stays on the
chat. This is accepted on purpose (owner, 2026-10-04): forgotten content can come back
to the assistant through a channel's window, the way a person who forgot a night can
still find the texts they sent.

> **Normative.** Where forgotten content can come back through a channel's window,
> the interface makes that visible to the user rather than hiding it.

Where the kind allows it, the user can delete the message (§5).

### 5. Deleting from a channel is the channel's operation

> **Normative.** Deleting something a channel carried is an operation on that
> channel, and is not forgetting.

> **Normative.** A kind declares whether its record allows deletion, and of what.

Not every kind will allow it: not every act is reversible.

> **Normative.** Deleting from a channel's record is a hub command by the user
> (ADR-0290 §7).

> **Normative.** The assistant has no action that deletes from a channel's record.

> **Normative.** Deleting from a channel does not forget. Whatever the assistant
> remembers of what was deleted stays in memory until it is forgotten there.

### 6. A channel's record is the user's data

> **Normative.** A channel's record is Tier 1 data under ADR-0004 §1, and the user can
> view, export and delete it under ADR-0004 §6.

> **Normative.** Deleting the user's data purges every channel's record along with
> memory. A kind's own retention never outlasts that purge, and a kind that offers no
> deletion of single items is still purged whole.

> **Normative.** A channel's record inherits its kind's requirements: a kind whose
> output is owner-only keeps an owner-only record.

### 7. The kinds that exist today

> **Normative.** Informational events and the quarantined spoken path keep no record
> of their own and offer no window read from one, until an ADR deciding their kind
> says otherwise.

> **Normative.** The conversation keeps reading its history from its episodes
> (ADR-0283 §4:1) until the text chat channel's ADR replaces that for the chat.

The windows these kinds are given today are not read from a record of their own:
the conversation's tail and the spoken turn's come from episodes, and an informational
event's is the context its submitter attached (ADR-0276 §3:1). They stand under the
Decision's opening clause until each kind's ADR replaces them.

## Consequences

**What becomes clear.** A channel and the assistant's memory are two things with two
owners. Forgetting changes what the assistant knows and never what a conversation
shows; deleting from a channel changes what it shows and never what the assistant
knows. Each kind decides what it keeps, so a kind that keeps nothing pays for nothing,
and a kind that keeps receipts, which are not activations, can keep them. The user's
right to view, export and delete their data reaches every channel's record.

**What it costs.**

- One event can be held twice, on the channel and in an episode, by design. Nothing
  reconciles them, so neither can be used to repair the other.
- Forgotten content can come back to the assistant through a window. The user's
  remedy is deletion from the channel, where the kind allows it.
- Every kind that keeps a record owes its own design for it: its storage, shape,
  order, retention and deletion.
- Nothing changes in code now. The routes the Decision's opening clause keeps stand
  in tension with §3 until each is replaced.

**What follows from it.** The text chat channel's ADR is the first kind to keep a
record. Building the chat's record and window, it owes the supersession, for the
chat, of ADR-0276 §3:1–§3:2's conversation window and *"no per-channel history
table"*, and of ADR-0283 §4:1's history read and §8:1's deletion of the channel's
episodes.

**What stays open.** None of these is decided here.

- **The assistant deleting its own output** from a channel: an outgoing action
  through the channel's actuator. Not offered now; offering it would supersede §5's
  rule that the assistant has no delete action.
- **Whether the assistant may read a channel's record beyond its window**, for
  example searching an old chat on request, and with what provenance.
- **Each kind's storage**: where its record lives and its shape are its own design,
  starting with the text chat.

## Alternatives considered

- **The channel's history is its episodes (ADR-0283, kept).** One record, no second
  copy. Rejected: it ties the channel to the assistant's memory, so forgetting
  rewrites what a conversation shows, and a channel cannot keep anything that is not
  an activation, such as a receipt.
- **Two records, with forgetting cascading into the channel.** Keeps them in step.
  Rejected: it is the consistency problem ADR-0283 retired, and it makes a channel's
  contents depend on what the assistant chose to remember.
- **A generic channel record every kind uses.** One store, shared rules for order,
  facts and retention. Rejected by the owner on 2026-10-04: what a channel keeps
  depends on the kind, and a shared shape would force order and facts on kinds that
  want neither.
- **Independent records, forgetting never reaching the channel (this decision).**
  Accepted cost: forgotten content can return through a window. Chosen by the owner
  on 2026-10-04, with deletion as the user's remedy where the kind allows it.
