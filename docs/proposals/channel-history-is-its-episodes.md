# A channel's history is its episodes

**The question.** Where does a channel's history come from, so that a
conversation is just one kind of channel and its history is not held twice?

**The answer proposed.** A channel's history is the episodes recorded on it,
read from the episode store in order. The conversation store's turn index, which
holds a second copy of that history, is retired. Every episode is numbered from
one store-wide counter when it is written, and that number is its order on its
channel. An episode's id stops being derived from its conversation and becomes
`activation:<activation_id>` on every channel. The conversation store keeps the
conversation itself.

This is the first of three steps that came out of #2613. The other two are
listed at the end and get their own proposals once this one is implemented.

## Baseline

Wiki, read at `ea98b15`:

- [Channels](https://github.com/leonapivato/ai-assistant/wiki/Channels): the
  channel is the medium, and a conversation is one kind of channel.
- [Episodes](https://github.com/leonapivato/ai-assistant/wiki/Episodes) and
  [Channel window](https://github.com/leonapivato/ai-assistant/wiki/Channel-window).

ADRs, at `5d872812`:

- ADR-0074: a conversation is an entity and every turn is an episode. §3 (the
  episode's id, derived from the turn), §7 (reclaim), §8 (deletion, index
  first), §9 (the `ConversationStore` and its turn index).
- ADR-0275: §3 (the capture unit), §7 (the turn row's `model_eligible` and the
  filtered `turns` read), §8 (index append, archive, episode, then verification),
  §9 (the index fields and history reads).
- ADR-0205: spoken delivery recorded on the turn row.
- ADR-0077: the observer reads turns after a watermark.
- ADR-0225: archive entries are addressed by the turn's address.

Issues: #2613 (one episode, open while the activation runs), #2614 (ADR-0283,
closed unmerged).

## What is wrong today

Every conversational activation writes its episode and also a turn row in the
conversation store. The row is a second history of the same conversation: the
conversation's history, digest and export are read from the rows, and each row
names its episode. Because the two are written separately, every crash and every
deletion between them needs a rule, which is most of what ADR-0283 had to
settle.

The row carries:

- **the ordinal**, the episode's position in the conversation, allocated when
  the row is appended;
- **the episode's id**, which is built from the conversation and the ordinal
  (`conv:<conversation_id>:<ordinal>`), so an episode's identity depends on the
  turn index, and episodes on other channels are named a different way
  (`activation:<activation_id>`);
- **`model_eligible`**, a copy of the flag on the episode, used to filter
  history;
- **the parked binding**, which `turn_of_binding` uses to find the turn a parked
  read belongs to when it resumes;
- **spoken delivery**, a device's report of how much of a spoken reply it
  played;
- **observed marks**, which the observer uses to know which turns it has
  read;
- **what deletion and reclaim enumerate**, through `stamped_conversation_ids`,
  `episodes_to_purge` and `drop_if_eligible`.

The episode already records its channel: a conversational episode is written
with `ChannelIdentity(channel_type="conversation", instance_id=<conversation_id>)`.
So everything the row adds is either a copy, or a fact that can live elsewhere.

## The change

### Episodes are numbered and found by channel

When the memory store writes an episode, it gives it the next number from one
store-wide counter. The number never changes and is never reused. A channel's
history is that channel's episodes in counter order. Timestamps are not used for
order: two episodes can share an instant, and the hub's clock can step back.

The episode's channel and its number become real indexed columns, not values
read out of the record's JSON.

Episodes are still written once, when processing ends, so the numbers follow the
order passes finished in, as ordinals do today.

The memory store gains two reads, a Protocol change:

- the episodes on a channel, in counter order, paged by number;
- the episode whose record links a given parked binding.

`MemoryStore.episodes`, the owner inspection read, is unchanged.

### The episode's id is the activation's

Every episode's id is `activation:<activation_id>`, on every channel. Nothing
about an episode's identity depends on the conversation store.

### History, digest and export read episodes

The conversation's history, its digest and export read the conversation's
episodes by channel. Until a later step retires `model_eligible`, the history
read keeps filtering on the flag on the episode, as it filters on the row today.

A parked read that resumes finds its conversation from the episode linking its
binding, through the new read, instead of `turn_of_binding`.

### The conversation store keeps the conversation

The conversation store keeps each conversation's id, when it started, its last
activity and its deletion tombstone. The turn index and its operations go:
`append`, `turns`, `turns_after`, `turn_of_episode`, `turn_of_binding`,
`record_observed`, `conversations_with_unobserved_turns`, `episodes_to_purge`,
and the turn rows in `export`.

Two small things move rather than go, and are kept to the minimum:

- **Spoken delivery** goes into a table in the conversation store keyed by
  episode id, written when a device's report arrives and read with history. It
  is not believed to work end to end today, and this change does not try to make
  it work.
- **The observer** reads episodes on a channel after a number instead of turns
  after an ordinal, with one watermark per conversation. It is blocked today
  (#2528), and this change does not try to keep or restore its behaviour.

### Deletion and reclaim sweep by channel

Deleting a conversation stamps its tombstone, then deletes the episodes on its
channel, then drops the conversation. There is no index to enumerate first.

An activation still running when its conversation is deleted writes its episode
after the sweep. So the writer keeps today's re-check after the write (ADR-0275
§8:11): if the conversation is stamped or gone, it deletes the episode it wrote.
With no turn row, that is the one compensation left.

Reclaim drops a conversation that has no live episodes and whose last activity
is older than the horizon.

### The archive is addressed by episode id

The transcript archive stays for now. Its entries are addressed by the episode's
id, and the ordinal they carry becomes the episode's number.

### Writing an episode

For a conversational episode, the activation writer writes the episode, then the
archive entry where one is owed, then the deletion re-check. It no longer
appends a row first or waits for an address from the conversation store.

## Cutover

A fresh data directory, as the M39 deploys used. The episode format and the
conversation store schema both change, and nothing is migrated.

## ADRs it would touch

ADR-0074 (§3, §7, §8, §9), ADR-0275 (§3, §7's turn-row flag and filtered read,
§8's write order, §9), ADR-0205 (where delivery is stored), ADR-0077 (what the
observer reads), ADR-0225 (the archive's address).

## Options considered

- **Keep the turn index and fix the write order** (ADR-0283 as accepted). It
  works, but keeps two histories and the crash and deletion rules between them.
- **Order history by timestamp.** No counter needed, but ties and clock steps
  reorder history.
- **A counter per channel.** Gives gap-free positions within a channel, but each
  write must read and lock its channel's last number. One store-wide counter is
  simpler and orders every channel the same way.
- **Put delivery on the episode.** It arrives after the episode is written, and
  episodes are written once, so it needs its own place.

## What it leaves open

The two later steps from #2613, each its own proposal once this one is
implemented:

- **The end entry.** The episode's end is the same on every channel:
  `response_kind` goes (it can be derived: no response, or an informational
  event's summary, or a reply), `model_eligible` is retired, the step verdict
  (`disposition`) moves onto the execution stage's entry, since nothing else on
  the episode records it, and `content` is built the same way on every channel.
- **The one record.** The episode becomes an open, append-only log; episodes are
  kept until forgotten; the transcript archive is retired; other stores hold only
  episode ids; forgetting an episode reaches the beliefs that cite it.

Also open here: whether the channel window (ADR-0276) should read through the new
channel read rather than its own query, which this change does not require.
