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
candidate story as its latest few episodes, which is enough to recognise a matter but
loses what was settled about it weeks ago, and gives planning a notepad that lives in each
plan.

The owner's rulings this proposal builds on, from the walk-through of 2026-10-06:

- Matters are invisible to the user, and shown on request.
- The assistant may reorganise its matters freely: start, merge, split and dissolve.
- There is no straight line between a matter and a one-off, for people or for the
  assistant.
- A single summary ("gist") is the wrong shape, and so is a record of typed fields: the
  answer to messy conversation is not to carry more and more fields.
- A story has a **page of notes** that anything working on the matter can write into,
  with anything written. The user can read and write it directly, but the main way notes
  arrive is through conversation and ordinary activations.
- The plan's notepad becomes the story's page; a plan with no story keeps its own notes.
- What is on the page is revisited each time it changes.
- The details are the assistant's to decide; privacy can wait.

## The design

### Three homes for what is known about a matter

| What | Example | Home |
| --- | --- | --- |
| What the matter is, and anything about it that matters while it lasts | "A camping trip to Riverside in mid-October"; "you're leaning against Saturday"; "you'll call the campground yourself"; "next: check the dog policy" | **The story's page** |
| Where the matter stands | Booked Sunday; confirmation unknown; asked about a canoe, no answer yet | **Worked out by rule** from records that already exist, never stored |
| What is true beyond the matter | "Prefers lakeside sites"; "Sister has a dog" | **Beliefs**, as for any lasting knowledge |

The test between the first and last rows: *would it still be true and useful if the
matter ended, or were forgotten?* If yes, it is a belief; if no, it belongs on the page.
When the two disagree for this matter, such as "budget $100 for the trip" on the page
against a belief that the user usually spends about $200, **the page wins for this
matter**; planning is given both.

**One principle throughout: structure only what a rule reads.** Every nuance of real
conversation (how firm something is, who said it, whether the assistant inferred it,
what kind of thing it is) is written in the note's words, which the models reading the
page understand. The page's structure is only what forgetting, privacy, tidying and
reading by rule need.

### The page

A story's page has two layers.

**Entries**, append-only. Every note ever written to the page, each carrying:

| Field | Why a rule needs it |
| --- | --- |
| **Its text**, any length within a bound, anything at all | — |
| **Who wrote it**: planning, the tidy-up, or the user directly | The tidy-up never rewrites the user's own notes |
| **What it rests on**: the episodes it came from; for a note the user wrote directly, that act | Forgetting, privacy, and splitting a story follow it |
| **Whether outside content fed it** | It is shown marked as such, never as the user's words |
| **When it was written** | Ordering, and which entries are newer than the current page |

**The current page**, rewritten by the tidy-up (below) whenever entries change: a first
line saying what the matter is, then short lines, each citing the entries it came from.
It is what readers read first. It has a size cap; what falls outside it stays in the
entries and their episodes. Each rewrite is a new version, so what the assistant held
about the matter at any time stays inspectable.

Examples of lines, nuance in the words:

- "You're leaning against Saturday, not decided."
- "Probably not Friday: the kids have school (my inference)."
- "Sister would prefer Saturday (her message, not your decision)."
- "You'll call the campground yourself about dogs."
- "Next: check the forecast on Thursday."

### Who writes

- **Planning**, during an activation, writes notes about its own work: what it found,
  what it decided, what comes next. This is the notepad of the phases proposal: when the
  activation belongs to a story, its notes are entries on that story's page, each naming
  the story it concerns if the activation belongs to several.
- **The tidy-up**, after an activation, writes what the matter gained from the episodes
  that joined it: what the user settled, changed or said they would do. It is the only
  writer of the current page.
- **The user**, directly: "note on the trip: Sister's allergic to pollen". These notes
  stand as written until the user changes them.
- **Never raw outside content.** A web page or an email cannot write to the page; only
  what understanding or digesting made of it can reach it, through planning or the
  tidy-up, marked as outside content.

**A plan with no story** (a one-off question, or a task finished in one activation with
nothing pending) keeps its notes in its plan, in its episode. **When a story starts
during an activation**, the notes written so far become the first entries on the new
page. **When a story is started later by judgment** and takes in an earlier episode, the
first tidy-up reads that episode, plan notes included.

**The page never authorizes.** A line saying the user approved something is text.
Authority comes only from the user's own messages, through the authority milestone.

Lasting knowledge is not written here: the background memory process (consolidation)
proposes beliefs from episodes as it does today. The two never compete: the page holds
the matter, beliefs hold what outlives it.

### The tidy-up

One model call, in the background after the activation that caused it, never while the
user waits.

- **It runs when** new entries arrive, an episode joins or leaves the story, an episode is
  forgotten, or the story is merged or split.
- **It reads** the current page, the new entries, and the episodes that changed, through
  their understanding, never their raw input.
- **It writes** new entries for what the episodes added (above), then a new current page:
  lines kept, reworded, merged or dropped, each citing its entries. Contradictions are
  resolved in favour of the newer statement by the user ("Saturday's fine now" replaces
  "no Saturdays"); a next step that is done drops off.
- **It may not** reword or drop the user's own notes; they appear on the page as written.
- **The hub checks** every line's citations against the page's entries before the version
  is written.

**Nothing is hidden while a tidy-up is pending.** Readers get the current page together
with any entries and member episodes newer than it.

### Forgetting, splitting and merging

- **Forgetting an episode** removes every entry that rests only on it; entries resting on
  it and others are kept, and the tidy-up rewrites every line citing what changed. A
  user's direct note is forgotten only when the user forgets it.
- **Splitting** a story sends each entry with the episodes it rests on; an entry resting on
  episodes in both parts goes to both. Each part gets a tidy-up.
- **Merging** combines the entries, and one tidy-up writes the merged page.

### Where the matter stands, worked out

No stored state. When a reader needs it, the hub assembles it by rule:

- **What was done**: the effect records pointing at the story, done, not done and unknown,
  unknown first.
- **What is open**: questions the assistant asked in the story with no answer linked, and,
  once they exist, timers and watches pointing at it.
- **When things happened**: a short timeline from the members and effects.
- **Related matters**: the stories it is part of or contains, from its links.

### What each reader is shown

Assembled by the hub per reader; nothing is stored per view.

| Reader | Shown |
| --- | --- |
| **Understanding**, judging whether input belongs | Each candidate story's current page, capped short (its first line and first few lines), and its latest one or two episodes' meanings |
| **Planning** | The current page in full, entries and episodes newer than it, the pages of stories it is part of (marked as inherited), where the matter stands, and the latest episodes |
| **The user, on request** | "What are you keeping track of?" lists matters by their first line; "show me the trip" gives the page and where it stands; the user can add a note |

### Starting and reorganising matters

There is no straight line between a matter and a one-off, so a story is started by
judgment as well as by rule, and mistakes are cheap because reorganising is free and
invisible:

- **By rule**, when something is left pending: a plan asks the user a question, or starts
  an action whose result comes back later, and starts a story for it.
- **By judgment**, when a moment is found to belong with an earlier one that is in no
  story: understanding links the new input to that earlier episode, and a story is
  started holding both. ("My running" becomes a matter the second time it comes up.)
- **Tidying matters, in the background**: the assistant merges stories found to be one
  matter, splits one found to be two, and dissolves a story left with one member, nothing
  pending and nothing on its page. Each change is in the story's log, and none is shown
  unless asked.

### Privacy, for now

Designed later. Until then, one default that falls out of citations: a line or entry is
shown only where every episode it rests on may be shown, and a user's direct note only
where the user's private records may be.

## What it would change

- **ADR-0289 §2**: a story gains its page, whose entries and versions hold text; the
  story's header, view and log stay text-free.
- **The wiki's Stories page**: "holds no text, no state" becomes "holds no state"; "a
  summary is a belief about it" gives way to the page.
- **#2723**: piece 1's notepad becomes notes on the story's page when there is a story;
  piece 3 gains starting a story by judgment; understanding's candidates are shown
  through their pages as well as their latest episodes.
- A belief naming a story as its subject (ADR-0289, *What stays open*) is no longer
  needed for this.

## Options considered

- **One summary per story (a gist)**, as a belief or in the story. It must stay short, so
  old constraints fall out; it mixes moments of different privacy into one text; and it
  goes stale with every change.
- **A record of typed items** (what it is, who is in it, settled, deadlines…). Every new
  kind of conversation needs a new field, and real speech still does not fit; models read
  the words anyway.
- **Everything as beliefs about the story.** What a matter is and its working notes are
  not lasting knowledge, and would fill memory with facts that die with the matter.
- **No page, only the latest episodes.** Enough to recognise a matter, but what was
  settled weeks ago falls out of view on a long matter.
- **A stored state ("booked, waiting for email").** It duplicates the effect records and
  goes stale; worked out by rule it is always current.

## What it leaves open

- **Privacy** beyond the citation default above.
- **Facts that become past** rather than false ("the trip is Oct 14" on Oct 15): how
  readers weigh time.
- **The numbers**: the page's size cap, an entry's size bound, how many lines and episodes
  each view shows.
- **Long-lived matters** ("my health", "the house"): whether readers need the page's lines
  ranked by relevance once it reaches its cap.
- **When it is built**: inside the phases milestone or after it. The phases work without
  it, through the latest episodes and per-plan notes; the page makes them better on long
  matters.
