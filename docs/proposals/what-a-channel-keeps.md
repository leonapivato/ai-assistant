# What a channel keeps

**The question.** Does a channel keep its own record of what it carried, separate
from the assistant's memory, and if so, who decides what that record holds and
what forgetting and deleting do to it?

This sits between the first proposal of the channel redesign
([#2578](https://github.com/leonapivato/ai-assistant/issues/2578)), accepted as
ADR-0290, and the second, the text chat channel
([#2680](https://github.com/leonapivato/ai-assistant/pull/2680)). ADR-0290 says
what a channel is and where one is needed. This proposal says what any channel
may keep. The text chat proposal is then rewritten to apply it to one kind.

It changes no code. No kind keeps a record of its own today, so nothing behaves
differently on the day it is decided; the first kind to keep one is the text chat.

## Baseline

Wiki pages, read at wiki revision
[`9a979ef`](https://github.com/leonapivato/ai-assistant/wiki/Channels/9a979ef6c46adff551e4f787e6bd7fc099284dd4):
[Channels](https://github.com/leonapivato/ai-assistant/wiki/Channels),
[Channel window](https://github.com/leonapivato/ai-assistant/wiki/Channel-window)
and [Episodes](https://github.com/leonapivato/ai-assistant/wiki/Episodes).

| ADR | What it decides today | What this proposal would do |
| --- | --- | --- |
| ADR-0290 §1 | *"Every channel has a kind, an identity the hub states, a window of what it recently carried, and what its kind declares."* | Partially supersede, in its window part alone: whether a channel has a window is its kind's choice (§3 below). Kind, identity and declarations stand. |
| ADR-0283 (its title's rule) | *"A channel's history is its episodes"*: the channel is an index over the assistant's episodes, with no record of its own. | Retire as a general rule: a channel's record, where its kind keeps one, is its own (§2 below). §1's numbering and channel index of episodes stand. ADR-0283's conversation-specific clauses (§4's history read, §6's store, §8's deletion sweep) are untouched here; the text chat proposal decides them for the chat. |
| ADR-0004 §6 | The user can view, export and delete their data; deleting the user's data purges Tier 0 and Tier 1 together. | Kept, and stated to reach channel records (§6 below). |
| ADR-0286 | An episode records one activation, opened at admission and frozen at its end. | Kept. Episodes stay the assistant's experience; nothing here changes what they hold. |

## The change

### 1. A channel is a medium, tied to neither end

ADR-0290 §1 already holds the first half: a channel is held by the hub, and a
device that reaches it holds no channel of its own. The other half: a channel is
not the assistant's either. What the channel carried is a fact about the channel,
not a part of what the assistant remembers. A conversation is the plain case: the
messages are on the conversation, whoever later remembers or forgets them.

### 2. A channel's record is its own, separate from memory

Where a kind keeps a record, it is **the channel's own**, held inside the hub and
**separate from the assistant's memory**. The two are independent: neither is
derived from the other, and neither is kept in step with the other.

- **Episodes** are the assistant's experience of an activation: what it perceived,
  did and concluded. They are memory, and recall, consolidation and forgetting act
  on them.
- **A channel's record** is what crossed the channel, as the kind keeps it. It is
  not memory: recall does not search it, and consolidation does not read it.

One event may appear in both: a message is on the chat, and the activation it
started has an episode. That is not one event recorded twice in the sense ADR-0283
retired. ADR-0283 retired the turn index because it was a *second copy of the same
history* that had to be kept consistent with the first. Here the two records answer
different questions, are kept by different owners, and are never reconciled, so
there is no consistency to keep.

### 3. What a channel keeps is its kind's choice

There is no generic channel record. Each kind declares what it keeps, alongside
its description and requirements (ADR-0290 §1):

- **whether** it keeps a record at all; a kind may keep nothing;
- **what** the record holds, for example messages, receipts, or nothing but a count;
- **whether** it is ordered, and by what;
- **how long** it is kept;
- **whether** it offers a window, and what the window is read from.

The hub still knows the order in which it received activations, whatever a
channel keeps; a kind that keeps no order loses nothing the hub needs.

Where a kind offers a window, understanding's "what came before on this channel"
is read from the channel's record, not rebuilt from episodes. A kind that keeps no
record has no window.

### 4. Forgetting acts on memory alone

Forgetting is the assistant's act on its own memory. It **never reaches a channel's
record**. If the assistant forgets something that was said on a chat, the message
stays on the chat.

This is accepted on purpose. Forgotten content can come back to the assistant
through a channel's window, the way a person who forgot a night can still find the
texts they sent. The interface makes that visible rather than hiding it, and where
the kind allows it, the user can delete the message (§5).

### 5. Deleting from a channel is the channel's operation

Deleting something a channel carried is an **operation on that channel**, not
forgetting, and is a property of its kind:

- A kind declares whether its record allows deletion, and of what. Not every kind
  will: not every act is reversible.
- Deletion is a **hub command by the user** (ADR-0290 §7). The assistant has no
  delete action on a channel's record.
- Deleting from a channel does not forget. Whatever the assistant remembers of it
  stays in memory until it is forgotten there.

### 6. A channel's record is the user's data

A channel's record is Tier 1 data under ADR-0004 §6. The user can view and export
it, and **deleting the user's data purges every channel's record** along with
memory. A kind's own retention never outlasts that purge, and a kind that offers no
deletion of single items is still purged whole.

A record inherits its kind's requirements: a kind whose output is owner-only keeps
an owner-only record.

### 7. The kinds that exist today

Informational events and the quarantined spoken path keep **no record** and offer
**no window** until their own designs say otherwise. That is what they do today.
The conversation keeps reading its history from its episodes (ADR-0283) until the
text chat proposal replaces that for the chat.

## Options considered

- **The channel's history is its episodes (ADR-0283, kept).** One record, no second
  copy. Rejected: it ties the channel to the assistant's memory, so forgetting
  rewrites what a conversation shows, and a channel cannot keep anything that is
  not an activation, such as a receipt.
- **Two records, with forgetting cascading into the channel.** Keeps them in step.
  Rejected: it is the consistency problem ADR-0283 retired, and it makes a channel's
  contents depend on what the assistant chose to remember.
- **A generic channel record every kind uses.** One store, shared rules for order,
  facts and retention. Rejected by the owner on 2026-10-04: what a channel keeps
  depends on the kind, and a shared shape would force order and facts on kinds that
  want neither.
- **Independent records, forgetting never reaching the channel (this proposal).**
  Accepted cost: forgotten content can return through a window. Chosen by the owner
  on 2026-10-04, with deletion as the user's remedy where the kind allows it.

## What it leaves open

- **The assistant deleting its own output** from a channel: an outgoing action
  through the channel's actuator. Not offered now.
- **Whether the assistant may read a channel's record beyond its window**, for
  example searching an old chat on request, and with what provenance.
- **Each kind's storage**: where its record lives and its shape are its own design,
  starting with the text chat.
