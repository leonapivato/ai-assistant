# What the assistant keeps about a matter

**The question.** When the assistant comes back to a matter, such as a camping trip
planned over weeks, what does it have at hand about that matter, where is it kept, and
how does it stay true as the matter changes?

**Words.** A *matter* is the situation in the world: the camping trip. A *story* is the
assistant's memory of it: which episodes belong to that matter, and, with this proposal,
its page. Everything the assistant keeps is said of the story.

## The baseline

The wiki's [Stories](https://github.com/leonapivato/ai-assistant/wiki/Stories) page at
`fba378d`: a story is the memory of which experiences belong to the same matter; it holds
no text, no state and no authority; what the matter is about is read from its episodes;
what is learned about it is kept as knowledge outside it; and a summary of a story is a
belief about it, formed by the observer. ADR-0289 §2 builds the store that way: a story
"carries no title, summary, state, owner or text of any kind", and no field of a story, a
view entry or a log line holds free text.

Nothing produces knowledge about a story today: the observer that would form a summary was
retired (ADR-0285), and a belief cannot yet name a story as its subject (ADR-0289, *What
stays open*). Nothing links an activation to a story either: the store has no producer in
the hub (ADR-0289). The phases proposal
([#2723](https://github.com/leonapivato/ai-assistant/pull/2723)) shows understanding each
candidate story as its latest few episodes, which is enough to recognise a matter but loses
what was settled weeks ago, and gives planning a notepad that lives in each plan.

The owner's rulings, from the walk-through of 2026-10-06 and 2026-10-07:

- Matters are invisible to the user, and shown on request.
- The assistant may reorganise its stories freely: start, merge, split and dissolve.
- There is no straight line between a matter and a one-off, for people or for the
  assistant.
- No single summary ("gist"), and no record of typed fields: the answer to messy
  conversation is not to carry more and more fields. Structure only what a rule reads.
- A story has a **page of notes** that anything working on the matter can write into,
  with anything written. The user can read and write it directly; the main way notes
  arrive is through conversation and ordinary activations.
- Notes are written **during** the activation, as actions; the page is tidied **when
  planning uses it**, in parallel, never making the user wait.
- Forgetting and privacy can wait.
- This work comes **before the phases**: this proposal declares what the phases are to do
  with stories, and the phases build it. It goes live **together** with them, in one cutover.

## The design

### Three homes for what is known about a matter

| What | Example | Home |
| --- | --- | --- |
| What the matter is, and anything about it that matters while it lasts | "A camping trip to Riverside in mid-October"; "you're leaning against Saturday"; "you'll call the campground yourself"; "waiting on your answer about the canoe"; "next: check the dog policy" | **The story's page** |
| Where the matter stands, from records | Booked Sunday; confirmation unknown; the timeline; the larger matter it is part of | **Worked out by rule**, never stored |
| What is true beyond the matter | "Prefers lakeside sites"; "Sister has a dog" | **Beliefs**, as for any lasting knowledge |

**The test** between the page and beliefs: *would it still be true and useful if the matter
ended, or were forgotten?* If yes, a belief; if no, the page.

**When homes disagree:**

| Disagreement | Who wins |
| --- | --- |
| The page against a general belief ("budget $100" against "usually spends about $200") | **The page, for this matter.** Planning is given both. |
| The page against a record ("booked" against an effect whose outcome is unknown) | **The record.** A note is an account; the record is what happened. |
| The page against the episodes it cites | **The episodes.** The page is an index of the matter, never its account. |

**The page does not repeat the records.** Where the matter stands is worked out from the
records; a line that only restates one is dropped. What belongs on the page about progress
is what the records cannot show: what the user or others will do, why something was
decided, what the assistant is waiting on, what comes next.

**Structure only what a rule reads.** How firm something is, who said it, whether the
assistant inferred it, what kind of thing it is: all of it is written in the note's words,
which the models reading the page understand. The page's structure is only what tidying,
splitting, privacy and reading by rule need.

### The page

**Entries**, append-only: every note ever written to the story's page.

| Field | Why a rule needs it |
| --- | --- |
| **Text**, within a size bound, anything at all | — |
| **Who wrote it**: planning, the tidy-up, or the user directly | The tidy-up never rewrites the user's own notes |
| **What it rests on**: exactly one episode, or one direct note from the user | Splitting sends each entry with its episode; the privacy default reads it |
| **Whether outside content fed it** | It is shown marked as such, never as the user's words |
| **When it was written** | Which entries are newer than the current page |
| **Superseded**, for a user's note replaced by the user's own later words | The note stays, marked, and the page shows the newer word |

**The current page**, rewritten by the tidy-up: a first line saying what the matter is,
then short lines, each citing the entries it came from. It has a size cap; what falls
outside it stays in the entries and their episodes. Only the current page is kept as text;
a log records, by identity alone, which entries each version cited.

Lines carry their nuance in their words:

- "You're leaning against Saturday, not decided."
- "Probably not Friday: the kids have school (my inference)."
- "Sister would prefer Saturday (her message, not your decision)."
- "You'll call the campground yourself about dogs."
- "Waiting on your answer about the canoe."
- "Next: check the forecast on Thursday."

**The page never authorizes.** A line saying the user approved something is text.
Authority comes from the user's own messages, through the authority milestone.

### Who writes

- **Planning**, during an activation. Each note it writes is marked either **for this
  activation**, scratch kept in its plan and ending with it, or **for the story**, a
  *note step* in the plan that acting writes onto the story's page as an inside action
  (ADR-0292 §12). Notes for the story cover its own work (what it found, what it decided,
  what comes next, what it is waiting on) and what the conversation settled.
- **The tidy-up**, as a safety net: when it runs, it reads the episodes that joined the
  story since the last tidy-up and adds an entry for anything settled there that no note
  captured, including from activations that never reached planning.
- **The user**, directly, through the story commands ("note on the trip: Sister's allergic
  to pollen"). The main way the user's words reach the page is still conversation.
- **Never raw outside content.** A web page or an email cannot write to the page; only what
  understanding or digesting made of it can reach it, marked as outside content.

Lasting knowledge is not written here: the background memory process (consolidation)
proposes beliefs from episodes as it does today.

### The tidy-up

An operation with one model call, run as an action:

- **When it runs.** Whenever planning is handed a story with changes not yet tidied (new
  entries, or episodes that joined), a tidy-up action is added to that planning round's
  actions **by rule**, not by planning's judgment, and acting runs it **in parallel** with
  the rest of the round. Planning itself works from the current page plus everything newer
  than it, which is the same information the tidy-up folds in, so nobody waits. One tidy-up
  per story at a time; changes that arrive meanwhile are taken in by one more run. A run
  that fails leaves the page as it was.
- **Only planning needs it.** Understanding and the user read the current page plus what is
  newer, untidied. A story nothing plans with stays untidied, harmlessly, until planning
  next uses it.
- **What it reads**: the current page, the entries newer than it, and the episodes that
  joined, through their understanding, never their raw input.
- **What it writes**: safety-net entries (above), then a new current page. Contradictions
  go to the user's newer statement ("Saturday's fine now" replaces "no Saturdays"); a next
  step that is done, and a question that has been answered, drop off; a line that restates
  a record drops off.
- **What it may not do**: reword or drop the user's own notes. It may mark one superseded
  only from the user's own later, clear statement; a vague later remark leaves the note
  standing.
- **What the hub checks, by rule**: every line cites at least one entry on this page; the
  user's notes' text is unchanged; a superseded mark cites an episode the user wrote
  (ADR-0292 §5's author); lines resting on outside content keep the outside mark.

### Splitting and merging

- **Splitting** a story sends each entry with its episode, or with the user's note to the
  part the user's notes concern. Each part's next tidy-up writes its page.
- **Merging** combines the entries; the next tidy-up writes one page.

### Where the matter stands, worked out

No stored state. When a reader needs it, the hub assembles it by rule:

- **What was done**: the effect records pointing at the story, done, not done and unknown,
  unknown first. These records come with the phases' acting.
- **When things happened**: a short timeline from the members' times and understood
  meanings and the effects, recent first, older ones summarised as counts.
- **Related matters**: the stories it is part of or contains, from its links. A matter that
  is related but separate ("the trip depends on the car repair") is a note on the page.
- **Timers and watches** pointing at the story join this list when they are built.

What is open (questions waiting on the user, next steps, who is doing what) is on the page,
because whether a question has been answered is a judgment.

### What each reader is shown

Assembled by the hub per reader; nothing is stored per view.

| Reader | Shown |
| --- | --- |
| **Understanding**, judging whether input belongs | Up to about five candidate stories, those of the episodes in its windows first, then those of the episodes recall found, by closeness. Each as a short view: the first line and the first few lines of its page, and its latest one or two episodes' meanings. |
| **Planning** | For each story the activation belongs to: the full page, the entries and episodes newer than it, the short views of the stories it is part of (marked as inherited), where the matter stands, and the latest episodes. It may also read any other story's page as a direct read of the assistant's own records. |
| **The user** | Mostly through conversation ("where are we with the trip?"), which planning answers. Directly through the story commands: the page, where the matter stands, and adding a note. |

Lines resting on outside content are marked as such in every view.

### Starting and reorganising stories

There is no straight line between a matter and a one-off, so a story starts by judgment as
well as by rule, and mistakes are cheap because reorganising is free and invisible:

- **By planning's mark.** A note marked for the story, written in an activation that
  belongs to no story, starts one; notes for this activation never do. When a story starts
  mid-activation, the notes written so far go onto its page.
- **By understanding's judgment.** Understanding may link the new input to a story among its
  candidates, or to an earlier episode that belongs to no story. In the second case a rule
  right after understanding starts a story holding both, whether or not planning runs.
  ("My running" becomes a story the second time it comes up.)
- **Results that arrive later**, such as a reply to an email the assistant sent, are a
  watch, built with the timers and watches milestone. Until then, planning's mark ("waiting
  on the campground's reply") starts the story, and understanding links the reply.
- **Merging and splitting are judgment.** The tidy-up flags a page that looks like two
  matters, or like another story; understanding linking one input to two lookalike stories
  is another flag. A background **matters pass**, scheduled with the existing background
  memory work, decides. Each change is in the story's log, and none is shown unless asked.
- **Dissolving is a rule**: a story with one member, an empty page, nothing open and no
  activity for a set time dissolves.
- **Wrong links** are fixed by whoever notices: a later understanding ("no, that was about
  the other trip"), the user through the story commands, or the matters pass. The moved
  episode's entries go with it.
- **Matters inside matters**: planning can start a story inside another when the user frames
  it so ("plan our summer: camping and visiting Mum"), and the matters pass can group stories
  under a larger one; both are links between stories, which ADR-0289 already supports.

### Privacy, for now

Designed later. Until then, one default from the citations: a line or entry is shown only
where every episode it rests on may be shown, and a user's direct note only where the user's
private records may be.

## Delivery: before the phases

This is its own milestone, built before the phases after understanding.

**It builds** what needs nothing from the new phases:

- The page in the story store: entries, the current page, the identity-only version log.
- The tidy-up operation. Until the phases exist, the engine runs it whenever an activation
  it processes is linked into a story with changes not yet tidied, in parallel with the rest
  of that activation.
- Understanding linking an activation to stories, and starting a story when it links to an
  earlier episode in none (understanding is built, ADR-0276).
- Recall bringing the stories of the episodes it finds, as candidates (recall is built,
  ADR-0281).
- The views, the timeline and related matters, and the matters pass.
- The story commands: the page, where the matter stands, adding a note.

**It declares, for the phases to build:**

- Planning's notes, each marked for this activation or for the story; a note for the story
  starting a story where there is none.
- Note steps, written by acting as inside actions.
- The tidy-up as an action added by rule when planning is handed an untidied story.
- Planning's view of its stories, and planning reading any story's page.
- Open questions, next steps and who is doing what as planning's notes.
- What was done, from acting's records.

**It goes live with the phases** (owner, 2026-10-07): built first, merged as it lands, and
deployed in the same cutover as the phases and the authority milestone. Until then it runs
on a test hub, where the engine's interim use of the tidy-up operation is what exercises
it.

## What it would change

- **ADR-0289 §2**: a story gains its page, whose entries and current page hold text; the
  story's header, view and log stay text-free.
- **ADR-0276**: understanding's record gains its links to stories.
- **ADR-0281**: recall also returns the stories of the episodes it finds.
- **ADR-0292 §12**: the inside actions gain writing a note on a story's page, and tidying it.
- **The wiki's Stories page**: "holds no text, no state" becomes "holds no state"; "a summary
  is a belief about it" gives way to the page.
- **#2723**: piece 1's notepad splits into scratch notes in the plan and note steps onto the
  story's page; piece 2's understanding links to stories with candidates as above; piece 3's
  stories start by planning's mark and by understanding's judgment; piece 5's acting writes
  notes and runs the tidy-up.
- A belief naming a story as its subject (ADR-0289, *What stays open*) is no longer needed
  for this.

## Options considered

- **One summary per story (a gist)**, as a belief or in the story. It must stay short, so old
  constraints fall out; it mixes moments of different privacy into one text; it goes stale.
- **A record of typed items** (what it is, who is in it, settled, deadlines…). Every new kind
  of conversation needs another field, and real speech still does not fit.
- **Everything as beliefs about the story.** A matter's working notes are not lasting
  knowledge and would fill memory with facts that die with it.
- **No page, only the latest episodes.** Enough to recognise a matter; what was settled weeks
  ago falls out of view.
- **A stored state ("booked, waiting for email").** It duplicates the records and goes stale.
- **Keeping the page's old versions as text.** A forgotten episode's content would survive in
  them; the identity-only log keeps what was cited when without that.
- **A tidy-up in the background after each activation, or before each read.** Background
  work outside the phases, or a model call the user waits on; run by acting when planning
  uses the story, it is neither.
- **A capability declaring that its result answers later.** That is a watch, and belongs to
  the timers and watches milestone.

## What it leaves open

- **Forgetting**, all of it: what forgetting an episode or a story does to entries, lines and
  the version log. The citations are kept so it can be designed.
- **Privacy** beyond the default above.
- **Facts that become past** rather than false ("the trip is Oct 14" on Oct 15).
- **The numbers**: the page's cap, an entry's bound, the five candidates, the lines in a short
  view, a story's idle time before dissolving.
- **Very long matters** ("my health", "the house"): whether the page's lines need ranking
  once it reaches its cap.
