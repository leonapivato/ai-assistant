# 389. A store bound to the owner's sight holds the devices of what it holds, so a device's listing and the chat's changes read through it as today

- Status: Accepted
- Date: 2026-11-26
- Scope: an amendment to decisions D1 and D3 of milestone 22, "Every record has a home"
  (acceptance [#3709](https://github.com/leonapivato/ai-assistant/issues/3709), batch
  [#3711](https://github.com/leonapivato/ai-assistant/issues/3711)). It settles what the reads that
  join device rows to records of a home answer an owner's act: which device rows a conversation
  store bound to the owner's sight holds (§2), the home of a conversation's deletion, which
  outlives its row (§3), what stays as it is (§4), and what each read then answers (§5). §6 records what it amends,
  §7 what building it needs.
- Authorization: the coordinator's proposal under the owner's delegation of ratification, and
  not an owner ruling. The owner's only words here are #3709's record: on 2026-11-26, "Yes,
  agreed", to the milestone's scope. The owner has ruled nothing in this decision. The
  coordinator assigned 0389, shows the owner the draft, and ratifies it once its reviews are
  green.
- **Contract-surface decision; a decision only.** It changes no Protocol, type or code. It
  names a change to `ConversationStore.bound`'s contract, its conformance suite and the conversation
  store's format (§7), so it takes the adversarial and the architecture review. Building it is a breaking change under
  golden rule 5.
- **Partially supersedes**
  [ADR-0383](0383-each-record-carries-its-home-and-every-read-a-work-a-producer-or-a-run-makes-is-of-a-store-bound-to-one-sight-which-answers-as-though-it-held-only-what-that-sight-sees.md)
  (§3's conversations row, in the addition alone; §3:3, in its reach; §7:2 and §9:3, each in the
  addition alone), as §6 records.

## Context

ADR-0383 §3 gives a conversation and each message a home, and device rows none: "my devices", a
conversation's devices, and the sets the change stream records with them. Its §3:3: "A record of
a store or kind the table marks as carrying none is given back, counted and named by no member of
a bound store (§7)". ADR-0385 §3:2 has an owner's act read "my devices" and a conversation's
devices "as it does today", and §4:1 has each seeing member give back "only what the owner's sight
from none sees" of the records of a home.

Three members of `ConversationStore` give back both in one answer, and no clause says what they
answer an owner's act. Bound to any sight, `ConversationStore.bound`'s contract has
`device_conversations` give an empty page, since each entry carries the device row's access;
`changes` give no change to a set of devices, each start with no devices, and no deletion of a
conversation since dropped; and `device_changes` give no change, since a change reaches a device
only through a set of devices. They are read by a device's `recent_conversations`, by
`chat_changes` from the hub's own machine and from a device, and by `follow_chat`'s pages and a
device's listing of its conversations (`orchestration/change_stream.py`, `conversations.py`). Lane
B10e ([#3777](https://github.com/leonapivato/ai-assistant/pull/3777)) left them unbound and listed
in ADR-0383 §9:1's named test under B10g: bound, the owner's phone would list no conversation and
follow no change; unbound, they give back conversations and messages of every home.

**A conversation's deletion** (`memory/conversation_store.py`). `stamp_deleted` keeps the
conversation's row, its home with it, clears its messages, devices and changes, and records one
`conversation_deleted` change holding the conversation's id and every device that ever read it.
`drop_if_eligible` removes the row after the grace (`conversation_tombstone_grace`, an hour by
default), and leaves that change. A reclaim, where a retention is set, records the change and
removes the row in one step. A change row holds `seq`, `kind`, `conversation_id`, `position` and
`devices`, and no home, so once the row is gone nothing in the store's file holds the home the
deletion was of.

**Words.** The **owner's sight** and an **owner's act** are ADR-0385's; a **home**, a **sight** and a
**bound store** are ADR-0383's. A **device row** is a member of "my devices", of a conversation's
devices, or of a set the change stream records (ADR-0293 §3, ADR-0296 §4:5). A bare section
reference, such as §2:1, is to this decision's own clauses.

## Decision

We will have a conversation store bound to the owner's sight hold "my devices" and the device rows
of each conversation it holds, as the unbound store holds them, so a device's listing, the chat's
changes and the change stream's pages read through it and give back what the owner reads today;
a store bound to any other sight holds no device row, as now; and have a conversation's deletion
keep its home, so every bound store gives it back by that home after the conversation's row is
gone.

### 1. Status and scope

> **Normative.** No lane implements against this decision before it merges `Accepted` (golden
> rule 5, ADR-0015 §5).

> **Normative.** This decision rules the hub ADR-0383 §1:2 rules, and only the reads above. It
> changes nothing a store bound to a work's, a producer's or a run's sight answers, save §3:2's
> deletion of a conversation whose row is dropped.

### 2. The device rows the owner's sight holds

> **Normative.** A conversation store bound to a sight `Sight.of_owners_act` made holds, beside the
> records that sight sees, "my devices" and, for each conversation it holds, that conversation's
> devices and each set the change stream recorded for it, as the unbound store holds them. It holds
> no device row of a conversation it does not hold.

> **Normative.** Of the change stream it holds every change to "my devices"; a conversation's
> start, with its devices, and each change setting its devices, where it holds the conversation; a
> message's addition or deletion where it holds the message; and a conversation's deletion where its
> sight sees the deletion's home (§3:2), with the devices the deletion records.

> **Normative.** It answers every member over what §2:1 and §2:2 have it hold, as ADR-0383 §7:2 has
> a bound store answer over the records it holds, the sight applied before it orders, limits,
> pages or counts: `my_devices` the set; `conversation_devices` the set of a conversation it holds
> and `None` for one it does not; `device_conversations` the conversations it holds that the device
> reads, each with its access, ordered and paged as `recent`; `changes` the changes it holds,
> restricted to `conversation_ids` as today; and `device_changes` the changes it holds that reach
> the device by ADR-0298 §7:4, judged against the sets as recorded, each change adding the device
> as a reader with a snapshot of the newest `CHAT_SNAPSHOT_ENTRIES` messages it holds at or below
> that change, a deleted one as its marker.

> **Normative.** What counts writes answers alike bound or not (ADR-0383 §8:5): a page's `as_of`
> and, where a page is not full, `next_after` are the change stream's head. Its writes are the
> writes a bound store makes now.

This is an amendment, not a reading ADR-0385 §3:2 already makes: ADR-0383 §3:3 binds every bound
store, ADR-0385 §10 records no supersession of it, and §3:2 is met by an unbound read, as B10e
reads `my_devices`. No device row gains a home. The owner's sight holds them because the owner's
act already reads them as today, and a read that joins them to records of a home then gives back
both from one store, as the owner reads them now.

### 3. A conversation's deletion once its row is dropped

> **Normative.** A conversation's deletion in the change stream carries its conversation's home,
> written in the step that records the deletion, by a stamp and by a reclaim alike, and never
> changed (ADR-0383 §3:2, §4:6). It is stored in the conversation store's file alone:
> `ConversationDeletedChange` gains no field, and nothing on the wire moves.

> **Normative.** A bound store gives back a conversation's deletion where its sight sees the
> deletion's home, whether or not the conversation's row still stands, and withholds it where its
> sight does not; no bound store reads the home of a deletion from the conversation's row.

> **Normative.** The upgrade that adds the home writes into each deletion the file holds its
> conversation's home where the conversation's row still stands, and the owner's domain where it
> does not, as ADR-0383 §5:1 writes the owner's domain into a record whatever its facts say. No
> other change row gains a home: a start's, a message's and a set's are read as §2:2 and ADR-0383
> §3:3 have them.

> **Normative.** A stored deletion with no home, or with one the store cannot read, is held by no
> bound store (ADR-0383 §5:3).

Without §3:1, a device that missed a deletion while the conversation's row stood, offline past the
grace or after any reclaim, would list the conversation for good, against ADR-0298 §7:5; and a
deletion given to the owner whatever its home would name another person's dropped conversation to
the owner once another person is admitted. The home is stored whole on the same ground as ADR-0383
§2:2: naming another person later changes no stored shape. A file at the earlier label may hold a
deletion of a shared things' conversation since dropped, whose home nothing in the file recalls;
§3:3 makes it the owner's, which changes nothing the owner's sight from none is given, since it
sees both, and no other sight reads the change stream today.

### 4. What stays as it is

> **Normative.** A store bound to a work's, a producer's or a run's sight holds no device row, as
> ADR-0383 §3:3 has it, and counts each as having no home, as now.

> **Normative.** No export holds a device row (ADR-0385 §6:4, §6:6), bound or not: a
> `ConversationExport` carries none.

> **Normative.** No bound store holds a record with no home (ADR-0383 §5:3), nor the device rows of
> a conversation with none.

> **Normative.** `DeviceChecks` and ADR-0298 §5's checks read device rows as they do today,
> unbound (ADR-0383 §7:8, §10:5; ADR-0385 §3:2, §5:3), and so does the change stream's check that a
> device reads a conversation when a change is sent (ADR-0298 §7:5).

> **Normative.** A store bound to the owner's sight writes no count event (ADR-0385 §3:5).

### 5. What the reads answer

> **Normative.** A device's `recent_conversations`, `chat_changes` from the hub's own machine and
> from a device, and `follow_chat`'s pages and a device's listing of its conversations, each read
> through the conversation store bound to the owner's sight from none, made for that read.

| Member, caller | Store member | It gives back |
| --- | --- | --- |
| `recent_conversations`, a device | `device_conversations` | The conversations the device reads that the sight sees |
| `chat_changes`, the hub's own machine | `changes` | Every change §2:2 has the store hold |
| `chat_changes`, a device | `device_changes`, restricted as today | Those of them that reach the device |
| `follow_chat`, the hub's own machine | `changes`; `recent` for its listing | As `chat_changes`, sent as each happens |
| `follow_chat`, a device | `device_changes`; `device_conversations` for its listing | As `chat_changes`, each change adding the device with its snapshot |

In this milestone every conversation and message is the owner's or the shared things' (ADR-0383
§2:3, §5:1), both of which the owner's sight from none sees, so each read gives back what it gives
back today, a conversation's deletion after its row is dropped included (§3), save a stored
record with no home, which is withheld (ADR-0383 §5:3). Nothing the owner's devices show changes.

### 6. Relationship to earlier decisions

> **Normative.** This decision partially supersedes ADR-0383 §3:3, in its reach: it does not reach
> a conversation store bound to the owner's sight, which holds the device rows §2:1 names; and
> ADR-0383 §7:2 and §9:3, each in the addition alone: what such a store holds, and the store its
> answers are compared with, include those device rows. Every other clause stands.

> **Normative.** This decision partially supersedes ADR-0383 §3's table, its conversations row, in
> the addition alone: a conversation's deletion in the change stream also carries one, its
> conversation's, in the store's file (§3:1). Every other row stands.

> **Normative.** This numbered draft records its replacements on ADR-0383's status line and in a
> dated header note there, atomically with this ADR under ADR-0070 and ADR-0082, preserving its
> ratified body. They take effect on its ratification.

| Clause | How it stands |
| --- | --- |
| ADR-0383 §5:1, §5:3, §7:8, §8:5, §10:5 | Stand (§3:3, §3:4, §4:3, §4:4, §2:4) |
| ADR-0383 §5:4 | Stands: it binds the `core` models a home is a field of, and §3:1 adds none |
| ADR-0326 §4:1, §5:3 | Bind §3:3's upgrade |
| ADR-0385 §3:2, §3:5, §5:3, §6:4, §6:6 | Stand (§4) |
| ADR-0385 §4:1 | Stands: `chat_changes` gives back records of a home and is a seeing member it binds, though §4's table of the members of its day leaves it out |
| ADR-0298 §5, §7:4, §7:5; ADR-0296 §4:5 to §4:8 | Stand, read over what §2 and §3 have the store hold |

### 7. What building it needs

Lane B10g builds it.

- **`core/protocols.py`:** `ConversationStore.bound`'s docstring states §2 and §4:1, its bullet on
  device rows narrowed to the other sights. The conformance suite
  (`tests/memory/conversation_store_contract.py`) gains, for a store bound to the owner's sight:
  `my_devices` as unbound; `conversation_devices` as unbound for a conversation it holds and `None`
  for one it does not; `device_conversations`, `changes` and `device_changes` each equal to the
  same store holding only what §2:1 and §2:2 name, pages and snapshots included. The cases for the
  other sights stand. For every sight, it gains: a stamped conversation's deletion given back where
  the sight sees its home and withheld where it does not, both before and after `drop_if_eligible`
  removes the row; the same for a reclaimed conversation's deletion, which the reclaim records and
  drops in one step (a store built with a retention); and, bound to the owner's sight, that
  deletion reaching through `device_changes` every device that ever read the conversation, after
  the drop.
- **`core/types.py`:** nothing owed. `Sight.reader` already tells the owner's sight
  (`SightReader.OWNERS_ACT`).
- **Stores:** `SqliteConversationStore` and `FakeConversationStore` alike, in `my_devices`,
  `conversation_devices`, `device_conversations`, `device_changes` and the change stream's
  condition and start rows. Both write the conversation's home on its deletion, in
  `stamp_deleted` and in `drop_if_eligible`'s reclaim, and read a deletion's home from it, for
  withholding and for ADR-0383 §11:1's count alike.
- **Format:** `chat_changes` gains `home_kind` and `home_id`, nullable as SQLite adds a column,
  set on a `conversation_deleted` row alone. `CONVERSATION_RECORD_FORMAT` advances 15 → 16, with
  ADR-0326 §4:1's upgrade: from 15, add the two columns where they are missing, a fresh file
  included, so there is one shape; write into every `conversation_deleted` row its conversation
  row's home where that row stands, and the owner's domain where it does not;
  leave every other byte. A build that serves 15 refuses a file at 16 (ADR-0326 §5:3). An upgrade
  test opens a file at 15 holding the deletion of an owner's and of a shared things' conversation,
  each with its row standing, and one whose row is dropped, and reads the first two by their
  conversations' homes and the third as the owner's; another holds a deletion with no home after
  the upgrade and finds it held by no bound store.
- **Orchestration:** the engine's `_recent_conversations` for a device and `_chat_changes` for both
  callers read through the store bound to the owner's sight from none, the device's page through
  `device_checks.device_changes` over it; `ChangeStream._page` and `_read_conversations` read
  through `seen_chat`; `ConversationLifecycle.device_conversations`, `device_changes` and `changes`
  take that store as B10e's other acts do, and leave `_KEPT_UNBOUND`. `ChangeStream` and
  `ConversationLifecycle` leave ADR-0383 §9:1's list for its named exemptions, and `_LANES` loses
  B10g.
- **Wire:** none. `ConversationDeletedChange`, `ChatChanges`, `DeviceChanges` and
  `DeviceConversation` keep their shapes, `ConversationExport` holds no change, and
  `PROTOCOL_VERSION` stays.

## Consequences

- The owner's devices list and follow their conversations through the owner's sight, and see what
  they see today.
- No read an owner's act makes of the conversation store is unbound but the device checks and the
  writes and sweeps the merged decisions name.
- A work, a producer and a run still see no device row.
- A deleted conversation leaves every device that read it, whenever the device catches up, and the
  conversation store's format moves once for it.
- **Revisit** when a second person or a group is admitted: whose a device is, and what its rows
  then show the owner of another person's conversations.

## Alternatives considered

- **Filter in `orchestration/` over an unbound read.** Set aside: it is the seam above the store
  ADR-0383 §7 set aside, whose pages come short or read on past the limit, and a snapshot inside
  `device_changes` cannot be filtered from outside the store.
- **Leave the reads unbound under ADR-0385 §3:2.** Set aside: they give back conversations and
  messages, which have a home, of every home, against ADR-0385 §4:1.
- **Give device rows the owner's home.** Set aside: it moves the format for every set of devices,
  and decides, before another person is admitted, whose a device is.
- **A dropped conversation's deletion given to the owner's sight whatever its home, or to no
  sight.** Set aside (§3): the first would name another person's conversation to the owner once
  another person is admitted; the second leaves a deleted conversation listed on a device for good.
- **Hold device rows for every sight.** Set aside: a work would read devices, which ADR-0383 §3
  keeps from every reader.
