# What the assistant keeps about a matter

**The question.** When the assistant comes back to a matter, such as a camping trip
planned over weeks, what does it have at hand about that matter, where is it kept, and
how does it stay true as the matter changes?

## The baseline

The wiki's [Stories](https://github.com/leonapivato/ai-assistant/wiki/Stories) page at
`fba378d`: a story is the memory of which experiences belong to the same matter; it
holds no text, no state and no authority; what the matter is about is read from its
episodes; what is learned about it is kept as knowledge outside it; and a summary of a
story is a belief about it, formed by the observer. ADR-0289 §2 builds the store that
way: a story "carries no title, summary, state, owner or text of any kind", and no field
of a story, a view entry or a log line holds free text.

Nothing produces knowledge about a story today: the observer that would form a summary
was retired (ADR-0285), and a belief cannot yet name a story as its subject (ADR-0289,
*What stays open*). The phases proposal
([#2723](https://github.com/leonapivato/ai-assistant/pull/2723)) shows understanding each
candidate story as its latest few episodes, which works for recognising a matter but
loses what was settled about it weeks ago.

The owner's rulings this proposal builds on, from the interview of 2026-10-06:

- Matters are invisible to the user, and shown on request.
- The assistant may reorganise its matters freely: start, merge, split and dissolve.
- There is no straight line between a matter and a one-off, for people or for the
  assistant.
- A single summary ("gist") is the wrong shape. Not everything about a matter deserves
  to be a belief; what the matter is and what the user settled about it belong in the
  story; working state is worked out, not stored.
- The story's knowledge is revisited each time it changes.
- The details are the assistant's to decide; privacy can wait.

## The design

### Three homes for what is known about a matter

| What | Example | Home |
| --- | --- | --- |
| What the matter is, who is in it, what the user settled, its deadlines | "A camping trip to Riverside in mid-October"; "Sister is coming"; "no Saturdays"; "book by Friday" | **The story's record** (below) |
| Where the matter stands | Booked Sunday; confirmation unknown; asked about a canoe, no answer yet; next, check the dog policy | **Worked out by rule** from records that already exist, never stored |
| What is true beyond the matter | "Prefers lakeside sites"; "Sister has a dog" | **Beliefs**, as for any lasting knowledge |

The test for the last row: *would it still be true and useful if the matter ended, or
were forgotten?* If yes, it is a belief; if no, it belongs to the matter.

### The story's record

A story gains a small record of its own, a list of items:

| Item kind | What it holds |
| --- | --- |
| **What it is** | The matter in a sentence. One item. |
| **Who is in it** | The people, places and things this matter concerns, as they figure in it. |
| **Settled** | The user's constraints and decisions about the matter. |
| **Deadlines** | Dates the matter must meet. |

Each item carries:

- **Its text**, short.
- **What it rests on**: the episodes it was drawn from, at least one.
- **As of**: the latest member episode it was checked against.
- **Who set it**: the assistant's reading, or the user's own correction.

The record stays small: a replaced or removed item leaves it, and a size cap holds the
rest; what falls outside the cap stays reachable through the episodes it rested on.

**What the record is not:** not the matter's state (that is worked out), not a list of
work (pending things are questions, timers and watches, which point at the story), not
authority (it grants nothing; whether a constraint is ever checked by rule is the
authority milestone's question), and not a place for lasting knowledge (that is beliefs).

### Keeping it true: the revisit

The record is **revisited whenever the story's membership changes**: an episode joins,
leaves, is forgotten or is unlinked, or the story is merged or split.

- **What a revisit is.** One model call, in the background after the activation that
  caused it, never while the user waits. It reads the record and the episodes that
  changed, through their understanding (never raw outside content), and returns, for
  each item, keep, replace or remove, plus any new items. The hub checks every item's
  citations against the story's members before writing.
- **What it may not touch.** An item the user set stands until the user changes it.
  A revisit may replace it only from the user's own later words, never from its own
  reading.
- **When an episode leaves.** Every item resting on it is revisited; an item left with
  no support is removed.
- **Split and merge.** On a split, each item goes with the part holding the episodes it
  rests on; an item resting on episodes in both parts goes to both and is revisited in
  each. On a merge, the records are combined and revisited once.
- **Nothing is hidden while a revisit is pending.** Readers are given the record
  together with any member episodes newer than its items' *as of*, so a reader at worst
  sees the newest episode beside an older record.
- **Versions are kept**: each revisit writes a new version, so what the assistant
  believed about the matter at any time stays inspectable.

### Where the matter stands, worked out

No stored state. When a reader needs it, the hub assembles it by rule:

- **What was done**: the effect records pointing at the story, with done, not done and
  unknown, unknown first.
- **What is open**: questions the assistant asked in the story with no answer linked,
  and, once they exist, timers and watches pointing at it.
- **What comes next**: the latest plan's notepad.
- **When things happened**: a short timeline from the members and effects.
- **Related matters**: the stories it is part of or contains, from its links.

### Lasting knowledge

Beliefs, unchanged. The background memory process (consolidation) already reads
episodes; it proposes lasting beliefs from a matter's episodes as from any others. The
revisit proposes none, so the two writers never compete.

### What each reader is shown

The hub assembles a view per reader; nothing is stored per view.

| Reader | Shown |
| --- | --- |
| **Understanding**, judging whether input belongs | Each candidate story's *what it is* and *settled* items, and its latest one or two episodes' meanings. Compact. |
| **Planning** | The full record, constraints inherited from the stories it is part of (marked as inherited), where the matter stands, the latest episodes, and any episodes newer than the record. |
| **The user, on request** | "What are you keeping track of?" lists the matters by what they are; "show me the trip" gives the record and where it stands. The user can correct an item, and the correction is an item the user set. |

### Starting and reorganising matters

There is no straight line between a matter and a one-off, so a story is started by
judgment as well as by rule, and mistakes are cheap because reorganising is free and
invisible:

- **By rule**, when something is left pending: a plan asks the user a question, or starts
  an action whose result comes back later, and starts a story for it.
- **By judgment**, when a moment is found to belong with an earlier one that is in no
  story: understanding links the new input to that earlier episode, and a story is
  started holding both. ("My running" becomes a matter the second time it comes up.)
- **Tidying, in the background**: the assistant merges stories found to be one matter,
  splits one found to be two, and dissolves a story left with one member and nothing
  pending. Each change is in the story's log, and none is shown unless asked.

This revises the phases proposal's "only a plan starts a story" (#2723, piece 3).

### Privacy, for now

Designed later. Until then, one default that falls out of citations: an item is shown
only where every episode it rests on may be shown, so a record never carries a private
moment into a place it could not reach on its own.

## What it would change

- **ADR-0289 §2**: a story gains its record, and the record holds text; its header and
  log stay text-free.
- **The wiki's Stories page**: "holds no text, no state" becomes "holds no state";
  "a summary is a belief about it" gives way to the record.
- **#2723**: piece 3 gains starting a story by judgment, and understanding's candidates
  are shown through the record as well as the latest episodes.
- A belief naming a story as its subject (ADR-0289, *What stays open*) is no longer
  needed for this.

## Options considered

- **One summary per story (a gist)**, as a belief or in the story. Rejected: it must stay
  short, so old constraints fall out; it mixes moments of different privacy into one
  text; and it goes stale with every change.
- **Everything as beliefs about the story.** Rejected: what a matter is and its working
  state are not lasting knowledge, and making them beliefs would fill memory with facts
  that die with the matter.
- **No record, only the latest episodes.** Enough to recognise a matter, but what was
  settled weeks ago falls out of view on a long matter.
- **A stored state ("booked, waiting for email").** Rejected: it duplicates the effect
  records and goes stale; worked out by rule it is always current.

## What it leaves open

- **Privacy** beyond the citation default above.
- **Facts that become past** rather than false ("the trip is Oct 14" on Oct 15): how
  readers weigh time.
- **The numbers**: the record's size cap, how many latest episodes each view shows.
- **Long-lived matters** ("my health", "the house"): whether readers need the record
  ranked by relevance once it reaches its cap.
- **When it is built**: inside the phases milestone or after it. Understanding and
  planning work without it, through the latest episodes; the record makes them better
  on long matters.
