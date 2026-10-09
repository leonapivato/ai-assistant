# 300. A story keeps a page of notes, and where its matter stands is worked out from records

- Status: Partially superseded by ADR-0301 (§6:7's resolution, in the addition alone; §6:8's *or to a channel item*, for a stored episode the pass admitted) and ADR-0302 (§3:10's page write, §5:2's reads, §5:6's instruction and §9:3's matters pass, each in the addition alone) and ADR-0303 (the page's citations, safety-net entries, supersession marks and owner-note rules; how notes move; the page's mark and privacy; the place window's candidates and labels; understanding's flag; planning's further story calls; each as ADR-0303's header scopes it)
- Date: 2026-10-08
- Scope: what the assistant keeps about a matter: a story's page and its tidy-up, understanding linking an activation to stories, recall bringing the stories of what it finds, the views, the matters pass and the story commands. Its own milestone, built before the phases after understanding ([#2723](https://github.com/leonapivato/ai-assistant/pull/2723)) and live with them.
- Dependency: ADR-0289, ADR-0276, ADR-0280, ADR-0281 and ADR-0282, all implemented at `04df86c0`.
- Authorization: the owner walked the design in passes on 2026-10-06 and 2026-10-07, reviewed it on 2026-10-08, and accepted proposal #2747 the same day ("lets build 2747 now then"). The dispatcher assigned 0300. This ADR is that proposal converted under `docs/proposals/README.md` → "When it is decided". That authorizes drafting and numbering, not ratification or implementation.
- Partially superseded: 2026-10-08 by ADR-0301 — two scopes. §6:7's resolution, in
  the addition alone: an `H` label naming a channel-window item that is a stored
  episode the pass admitted, a record of the conversation tail or one exchange with an
  episode of the episode window, also resolves to that episode's activation as an
  activation member, as a `P` label naming it does. §6:8's *or to a channel item*, for
  those items alone: such a label is not a label defect, and an `H` label naming any
  other channel item still is. Every other clause stands, §6:1, §6:6, §6:9 and §6:12
  included. These scoped replacements take effect on ratification of ADR-0301. This
  reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082;
  the ratified body below is preserved.
- Partially superseded: 2026-10-08 by ADR-0302 — four scopes, each in the addition
  alone. §3:10's page write is also refused where a safety-net note rests on an
  activation the story does not hold, or the write takes in an episode or a note the
  story does not hold. §5:2's reads: a tidy-up also reads the decisions recorded for its
  story. §5:6's instruction also states that a decided flag is raised
  again only where what the run takes in bears on it. §9:3's matters pass records each
  decision as a `decided` line in the change log of the stories the flag concerns,
  decides only flags no such line answers, and is shown the decisions already
  recorded. Every other clause stands. These scoped replacements take effect on
  ratification of ADR-0302. This reciprocal header record accompanies the numbered
  draft under ADR-0070 and ADR-0082; the ratified body below is preserved.
- Partially superseded: 2026-10-08 by ADR-0303 — the scopes its header lists. A
  page's lines cite nothing and carry no mark; the page carries one mark, set by rule
  where its run read a marked note, an outside episode or a marked page, and is shown
  only where everything any version took in may be (replacing §3:6, §3:7's citations,
  §4:3, §4:4 and §11:1). A note records the activation it was written during as
  history no rule reads (§3:1, §3:3, §10:2). Safety-net entries, supersession marks
  and every rule special to the user's own notes retire (§3:5, §3:17's second
  sentence, §5:5–§5:7, §5:9). A split or a move carries exactly the notes it names,
  and a merge still carries every note (§3:13, §3:14, §9:5). The place window's stories are the first candidates and
  a label naming an item that links to no activation is dropped without a repair
  (§6:1, §6:7, §6:8). Understanding raises no flag (§9:2's second sentence).
  Planning gains unlink, move, merge, split and group (§9:1, §10:3, §10:5). The
  interim tidy-up starts when the episode is frozen (§5:12), and §10:8's *and no
  other record holds them* goes. Every other clause stands. These scoped
  replacements take effect on ratification of ADR-0303. This reciprocal header
  record accompanies the numbered draft under ADR-0070 and ADR-0082; prior
  supersessions and the ratified body below are preserved.
- **Partially supersedes** [ADR-0289](0289-a-story-store-holds-which-experiences-belong-to-the-same-matter.md) — **four scopes.** **§2:1's *"It carries no title, summary, state, owner or text of any kind"*, for the page alone**: a story has a page, whose entries and current page hold text (§3 below); the story's header carries what §2:1 lists and nothing more, and §2:7 stands, so no field of a story, a view entry or a log line holds free text. **§3:14's *"five reads and no others"*, in the additions alone**: the store also answers the page's reads (§3 below). **§4:4, for the writes the hub makes outside the engine surface**: understanding's links and the stories it starts carry the actor `understanding` and the activation as trigger (§6 below), the matters pass's changes carry `matters_pass` (§9 below), and planning's, once the phases build it, `planning` (§10 below); every write through the engine surface still carries `owner` and no trigger. **§4:6, whole**: understanding, recall, the story-links stage, the tidy-up and the matters pass read or write stories, and the tidy-up's, understanding's and the matters pass's prompts include them (§§5–9 below). Every other clause stands, §2:6 included: its own last sentence provides for the actor members this ADR adds.
- **Partially supersedes** [ADR-0276](0276-an-activation-is-understood-before-it-is-associated-and-the-understanding-is-retained-with-its-episode.md) — **three scopes.** **§1:5's *"and nothing else"*, §3:7's last sentence and §6:1's *"from the input and the two windows"*, for the candidate stories alone**: the stage also reads, and its prompt renders, the short views of the candidate stories (§6 below), which are assembled by lookup and are not the retrieval or episode search §3:7 forbids. **§2:1's field sets, in the additions alone**: `ProposedActivationUnderstanding` gains `story_labels` and `ActivationUnderstanding` gains `story_links` (§6 below). **§3:3's label scheme, in the addition alone**: a fourth sequence, `S`, for the candidate stories. §1:4 stands: the stage still holds an injected `ModelProvider` and nothing else, and every other clause stands.
- **Partially supersedes** [ADR-0281](0281-recall-runs-before-understanding-and-understanding-reads-what-it-found.md) — **three scopes.** **§1:3's *"and nothing else"*, in the addition alone**: recall also looks up the stories the episodes it keeps belong to, by identity and never by search (§7 below). **§6:1's `RecalledItem`, in the addition alone**: it gains `stories`. **§7:1's *"or memory from any other read"*, for the candidate stories alone**: understanding also receives the latest episodes of each candidate story (§6 below). Every other clause stands.
- **Partially supersedes** [ADR-0282](0282-phases-read-and-write-the-working-episode-and-recall-searches-past-the-windows.md) — **two scopes.** **§2:5's *"and only those"*, for recall alone**: recall's reads also include the story store's lookup of the stories each episode it keeps belongs to (§7 below). **§2:4's *"and fetches no other record"* and §5:1's single `MemoryStore.get_many`, for the candidate stories alone**: before understanding renders, the understanding phase looks up the stories of the episode window's episodes, reads each candidate's short view from the story store, and fetches the records of each candidate's latest episodes, under §2:6–§2:8 otherwise (§6 below). Every other clause stands.
- **Partially supersedes** [ADR-0280](0280-an-activation-controller-runs-the-stages-by-rules-and-records-every-choice-with-the-episode.md) — **one scope.** **§3:5's working set and §4:1–§4:3's enums and table, in the additions alone**: the working set gains the story-links decision, and §4:1–§4:3 gain the stage `story_links`, the rule `story_links_unrecorded` and its row immediately after `not_understood` (§6 below); no other member, row or order changes. Every other clause stands.
- **Partially supersedes** [ADR-0292](0292-a-channel-is-the-spokes-facing-one-thing-and-the-assistants-edge-is-its-own.md) — **one scope.** **§12:1's and §12:2's reach, for the story changes the hub makes outside planning**: the membership the hub records from understanding's links and the stories §6's rule starts (§6 below), the matters pass's changes (§9 below), and, until the phases replace the turn loop, the engine's tidy-up run by rule (§5 below) are bookkeeping and background maintenance of the assistant's records, not actions: planning does not choose them and authorizing does not check them, and they still run directly on no channel. The story calls planning makes (§10 below) are inside actions under §12:1–§12:2 as written, starting a story, writing a note and tidying a page joining §12:1's examples; every other clause stands.

## Context

**The question.** When the assistant comes back to a matter, such as a camping trip
planned over weeks, what does it have at hand about that matter, where is it kept, and
how does it stay true as the matter changes?

**Words.** A *matter* is the situation in the world: the camping trip. A *story* is the
assistant's memory of it: which episodes belong to that matter and, under this decision,
its page. Everything the assistant keeps is said of the story.

**The baseline.** The wiki's [Stories](https://github.com/leonapivato/ai-assistant/wiki/Stories)
page, read at wiki revision `fba378d`, describes a story as the memory of which
experiences belong to the same matter. It holds no text, no state and no authority; what
the matter is about is read from its episodes; what is learned about it is kept as
knowledge outside it; and a summary of a story is a belief about it, formed by the
observer. ADR-0289 built the store that way: a story "carries no title, summary, state,
owner or text of any kind" (§2:1), and no field of a story, a view entry or a log line
holds free text (§2:7).

Nothing produces knowledge about a story at `04df86c0`. The observer that would form a
summary was retired (ADR-0285), and a belief cannot yet name a story as its subject
(ADR-0289, *What stays open*). Nothing links an activation to a story either: ADR-0289
§4:6 forbids every stage, phase, rule and prompt from reading or writing one, and the
store's only writer is the owner through the engine surface (§4:4).

**The owner's rulings,** from the walk-throughs of 2026-10-06 to 2026-10-08:

- Matters are invisible to the user, and shown on request.
- The assistant may reorganise its stories freely: start, merge and split.
- There is no straight line between a matter and a one-off, for people or for the
  assistant.
- No single summary ("gist"), and no record of typed fields: the answer to messy
  conversation is not to carry more and more fields. Structure only what a rule reads.
- A story has a **page of notes** that anything working on the matter can write into,
  with anything written. The user can read and write it directly; the main way notes
  arrive is through conversation and ordinary activations.
- Notes are written **during** the activation, as actions; the page is tidied when
  planning chooses to, in parallel, never making the user wait.
- Outside content on the page is handled with the care a human assistant would take, not
  made trick-proof: *"a good goal to have for outside content and getting tricked is not
  to have it trick proof, but for it to be reasonable defensible, similar to that as if a
  human assistant were given the same task"* (owner, 2026-10-07).
- Forgetting and privacy can wait.
- This work comes **before the phases** (#2723): this decision declares what the phases
  are to do with stories, and the phases build it. It goes live **together** with them,
  in one cutover.

**The code at `04df86c0`.**

- `StoryStore` in `core/protocols.py` is implemented by a SQLite store on `stories.db`,
  with its triad (ADR-0289 §1). Its reads include `StoryStore.stories_of`, the stories a
  member belongs to directly. `core/types.py` already spends two names this decision's
  words would reach for: `StoryEntry` is a member in a story's clean view, and
  `StoryPage` is a page of the list of stories.
- The controller runs the windows stage, `RecallStage` (`orchestration/recall.py`) and
  `UnderstandingStage` (`orchestration/understanding.py`) in that order, each reading and
  writing its own part of the working episode (ADR-0282 §2). The understanding phase
  fetches the window's and recall's records before the stage renders (ADR-0282 §5:1).
- An episode is open while its activation runs and frozen when it ends (ADR-0286).

**The phases are a proposal.** #2723 at `3f738644` describes planning, authorizing,
acting and digesting, and the capabilities whose declarations every rule reads (its
§5). It decides nothing until it is converted. This decision states what the phases are
to build for stories (§10 below) as obligations on the decision that builds them. Where
#2723's text at that revision differs (it adds the tidy-up to every round by rule, and
points effects at the story), it predates the owner's rulings of 2026-10-07 and
2026-10-08 recorded here.

## Decision

We will give each story a page of notes, written during activations and tidied when
planning chooses; work out where a matter stands from records instead of storing it;
have understanding link each activation to its stories, with recall bringing the
candidates; and keep reorganising stories cheap and invisible. Every clause below stands
alongside ADR-0289, ADR-0276, ADR-0280, ADR-0281 and ADR-0282 except where this
decision's header names a scope it replaces.

### 1. Status and scope

> **Normative.** This document remains `Proposed` until the reviews
> `CONTRIBUTING.md` → "Finishing an ADR PR" requires have returned green on one tree
> and the owner's authorization to ratify stands; an assigned number or a green review
> alone does not change its status.

> **Normative.** No implementation, canonical fake included, implements this decision
> until this numbered ADR has merged `Accepted` under ADR-0015 §5.

> **Normative.** Where this decision states what the phases build (§10), it binds the
> decision that converts #2723, and binds no lane before that decision is ratified.

### 2. Three homes for what is known about a matter

| What | Example | Home |
| --- | --- | --- |
| What the matter is, and anything about it that matters while it lasts | "A camping trip to Riverside in mid-October"; "you're leaning against Saturday"; "you'll call the campground yourself"; "waiting on your answer about the canoe"; "next: check the dog policy" | **The story's page** (§3) |
| Where the matter stands, from records | Booked Sunday; confirmation unknown; the timeline; the larger matter it is part of | **Worked out by rule**, never stored (§8) |
| What is true beyond the matter | "Prefers lakeside sites"; "Sister has a dog" | **Beliefs**, as for any lasting knowledge |

**The test** between the page and beliefs: *would it still be true and useful if the
matter ended, or were forgotten?* If yes, a belief; if no, the page.

> **Normative.** No record stores where a matter stands. What was done, when things
> happened and which matters are related are assembled by rule from the records each
> time a reader needs them (§8).

> **Normative.** Planning's instruction states three precedences: for this matter, the
> page over a general belief, with both given to planning; a record over the page, since
> a note is an account and the record is what happened; and the episodes over the page
> that cites them, since the page is an index of the matter and never its account.

> **Normative.** The tidy-up's instruction states that the page does not repeat the
> records: a line that only restates what the records already show is dropped, and
> what belongs on the page about progress is what the records cannot show,
> such as what the user or others will do, why something was decided, what the assistant
> is waiting on and what comes next.

> **Normative.** The page's records carry the fields §3 lists and no others. How firm
> something is, who said it, whether the assistant inferred it and what kind of thing it
> is are written in the note's words, and no field, enumeration or validator classifies
> them.

### 3. The page

A story's page is two records the story store keeps beside the story: its **entries**
and its **current page**, with a **version log** recording the current page's history by
identity.

**Entries.**

| Field | Why a rule needs it |
| --- | --- |
| **Text**, within a size bound, anything at all | — |
| **Who wrote it**: planning, the tidy-up, or the user directly | The tidy-up never rewords or drops the user's own notes |
| **What it rests on**: exactly one activation's episode, or, for a note the user wrote directly, nothing but itself | Splitting sends each entry with its episode; the privacy default reads it |
| **Whether outside content fed it** | It is shown marked as such, never as the user's words, and counts as outside content for whoever reads it (§4) |
| **When it was written** | The order of a story's entries; which of them a version has taken in is the version log's |

> **Normative.** An entry carries its text, within a bound on its length; who wrote it;
> what it rests on; whether outside content fed it; and the store's clock reading when it
> was written. None of these changes once it is written, and no entry is removed.

> **Normative.** Who wrote an entry is a closed enumeration, added to and never renamed,
> whose members are `planning`, `tidy_up` and `owner`, `owner` being the user writing
> directly, by the name ADR-0289 §2:6 gives the user's actor.

> **Normative.** An entry rests on exactly one activation, named by its activation id,
> except an entry the user wrote directly, which rests on nothing but itself. An entry
> `owner` wrote rests on nothing, and every other entry rests on an activation.

> **Normative.** An entry the user wrote directly is never marked as fed by outside
> content.

> **Normative.** A **supersession mark** says that an entry the user wrote has been
> replaced by the user's own later words. It names the entry and the episode whose words
> replaced it, it is written only by a tidy-up (§5), and it is recorded with the version
> that made it, so the entry itself is never rewritten. An entry is superseded from that
> version on.

**The current page.**

> **Normative.** The **current page** is a first line saying what the matter is, then
> short lines. Each line carries its text, the entries it came from by identity, and
> whether it is marked as resting on outside content. Only the current page is kept as
> text: writing a new one discards the old one's text.

> **Normative.** The **version log** is append-only, and holds identities and instants
> only. Each version records when it was written; the entries each line cited; the
> safety-net entries it added; the entries and the episodes it took in; the supersession
> marks it made; and the flags it raised (§9). No field of it holds free text.

> **Normative.** An entry or a member episode is **pending** on a story until a version
> of that story's page records taking it in. A version takes in exactly the pending
> entries and episodes its run read: one that becomes pending while the run is out stays
> pending after the run's write, whatever the instants say. An entry or an episode that a
> merge, a split or a move brings into a story is pending there until a version of that
> story takes it in, whatever any other story's version took in.

> **Normative.** The current page has a size cap. What falls outside it stays in the
> entries and in their episodes.

Lines carry their nuance in their words: "You're leaning against Saturday, not
decided." "Probably not Friday: the kids have school (my inference)." "Sister would
prefer Saturday (her message, not your decision)." "Waiting on your answer about the
canoe." "Next: check the forecast on Thursday."

**The store.**

> **Normative.** `StoryStore` gains the page: appending an entry; writing a new current
> page together with its safety-net entries and its version, in one transaction, refused
> where the version it was built on is no longer the current one; and reading the
> current page with its pending entries, a story's entries page by page, and its
> version log page by page. A refused page write writes nothing.

> **Normative.** The page's types take names that `core/types.py` does not already
> spend. `StoryEntry` and `StoryPage` keep the meanings ADR-0289 gave them.

> **Normative.** A merge moves the absorbed story's entries to the story it is merged
> into, in the merge's transaction. The next tidy-up of that story writes one page from
> them.

> **Normative.** A split moves to the new story every entry resting on an activation the
> split moves, and the entries the user wrote directly that the split names; every other
> entry stays. Each part's next tidy-up writes its page.

> **Normative.** `StoryStore` gains a **move** of activation members from one story to
> another, which removes them from the first, adds them to the second, and moves every
> entry resting on a moved activation, in one transaction, logged on each story as a
> removal and an addition.

> **Normative.** `StoryActor` gains the members `understanding`, `planning` and
> `matters_pass`, under ADR-0289 §2:6.

> **Normative.** The change ships as a triad under `CONTRIBUTING.md` → "Adding a
> Protocol": the `StoryStore` change, its conformance suite and its canonical fake, with
> the SQLite store in `memory/` that implements it, as one change (ADR-0137 §2). The
> story store still reads no other store (ADR-0289 §1:3).

> **Normative.** The entry's length bound and the current page's cap are constants the
> lane that builds them sets, recording in its PR what it chose them from. Until the open
> question of the user's own notes against the cap is decided, the cap binds the lines
> that are not the user's own notes.

### 4. Outside content, and authority, on the page

The mark of outside content travels with what is written, by the care a human assistant
would take rather than by construction.

> **Normative.** No entry's text is taken from raw outside content. A web page or an
> email cannot write to a page; only what understanding or a digest made of it can
> reach one, marked.

> **Normative.** An entry planning writes is marked when its activation read outside
> content, and the mark comes from the hub's record of what the activation read, never
> from planning's judgment.

> **Normative.** A safety-net entry is marked when the episode it rests on is outside
> content, its trigger's `origin` being `outside` (ADR-0284), or when the hub's record of
> what its activation read shows outside content.

> **Normative.** A line citing a marked entry is marked. The tidy-up is instructed not to
> blend sources in one line, and the hub checks the marks (§5).

> **Normative.** A marked line or entry that planning reads counts as outside content in
> that activation's record of what it read, the way a human assistant remembers "the
> email said…".

> **Normative.** Every line and entry reaches a model as quoted source data under
> ADR-0098 §2, attributed by its record (who wrote it, and whether it is marked) and
> never by its text, and a marked one is shown as outside content and never as the
> user's words.

> **Normative.** A page never authorizes. A line or entry saying that the user approved
> something is text: nothing reads it as the user's instruction or approval, and it
> carries no authority under ADR-0292 §5.

So an address an email supplied on Monday is not emailed on Thursday as if it were known
fact.

### 5. The tidy-up

An operation on the assistant's own records: it writes a new current page, whose content
one model call produces (a model call is processing, ADR-0292 §12:4).

> **Normative.** The tidy-up is an orchestration-local operation holding an injected
> `ModelProvider`, `StoryStore` and `MemoryStore`. It is not a Protocol, and
> `core/protocols.py` gains no member for it.

> **Normative.** A tidy-up of a story reads its current page, its pending entries, and its
> pending member episodes that are frozen. An open episode is not read, and stays pending
> for a later run.

> **Normative.** The tidy-up renders an episode with the user's own input as written
> where its author is the user, established (ADR-0292 §5), any other input only through
> its latest understanding's meaning, and the assistant's reply as recorded. It never
> renders an outside episode's raw input.

> **Normative.** The tidy-up makes exactly one completion through its provider. It
> produces safety-net entries, a new current page, supersession marks and flags, and
> nothing else.

> **Normative.** A **safety-net entry** records something settled in an episode the run
> took in that no entry captured, including from an activation that never reached
> planning. It is written by `tidy_up` and rests on that episode.

> **Normative.** The tidy-up's instruction states: a contradiction goes to the user's
> newer statement ("Saturday's fine now" replaces "no Saturdays"); a next step that is
> done, and a question that has been answered, drop off; and the user's own notes are
> never reworded or dropped.

> **Normative.** The hub checks the output by rule before writing it: every line cites
> at least one of this story's entries, its new safety-net entries included; every entry
> the user wrote directly that is not superseded appears as a line with its text
> unchanged, citing it; a supersession mark names an entry the user wrote and an episode
> the run took in whose input's author is the user, established; a line citing a marked
> entry is marked; and each safety-net entry rests on an episode the run took in.

> **Normative.** An output that fails to parse or fails any check is refused whole and
> writes nothing, and the page stays as it was. There is no second completion.

> **Normative.** A tidy-up marks an entry superseded only on the user's own later, clear
> statement, and its instruction states that a vague later remark leaves the note
> standing.

> **Normative.** At most one tidy-up runs on a story at a time. A run asked for while one
> is running on the same story does not start, and what becomes pending meanwhile is
> taken in by a later run (§3).

> **Normative.** Nobody waits for a tidy-up: the activation that started it does not wait
> for it, and its finishing starts nothing.

A tidy-up skipped or late loses nothing: every reader of the page is given the current
page plus everything pending on it, which is the same information the tidy-up folds in;
it only grows the next reader's input.

> **Normative — before the phases.** Until the phases replace the turn loop, the engine
> starts a tidy-up by rule, without waiting for it, for each story into which the
> story-links stage (§6) links an activation and on whose page anything is pending.
> This run is scaffolding for the test hub, is not an action under ADR-0292 §12:1–§12:2
> in the scope this decision's header gives, and is removed at the cutover; it is never
> the phases' route to the tidy-up.

### 6. Understanding links an activation to stories

**The candidates.**

> **Normative.** Before the understanding stage renders, the understanding phase
> assembles up to `UNDERSTANDING_STORY_CANDIDATES` candidate stories, a composition-root
> constant with initial value **5**: first the stories the episode window's episodes
> belong to, looked up with `StoryStore.stories_of` in the window's order, then the
> stories recall's kept episodes belong to (§7), the item with the higher recorded search
> score first. A story already a candidate is not repeated.

> **Normative.** Each candidate is rendered as a **short view**: the first lines of its
> current page, its newest pending entries, and the meanings of its latest
> episodes, each episode rendered with ADR-0276 §4's projection. The numbers of each are
> composition-root constants the lane that builds them sets, at most two entries and two
> episodes.

> **Normative.** A candidate's latest episodes are fetched with `MemoryStore.get_many`
> under ADR-0282 §2:6–§2:8, so an episode not admitted to understanding for the pass is
> neither fetched nor rendered. Its lines and entries are shown under §11's default.

> **Normative.** A story-store read that raises `StoryStoreError` leaves understanding
> with no candidates. The section then states that the stories could not be read, and
> the stage proceeds.

**The call.**

> **Normative.** The candidates are rendered in a fourth section of the prompt,
> `stories`, each under the label `S` followed by its 1-based index in that section in
> decimal with no padding, on ADR-0276 §3:3's scheme. No label survives the call and none
> is persisted. The episodes inside a short view take no label.

> **Normative.** `ProposedActivationUnderstanding` gains `story_labels:
> tuple[EncodableText, ...] = ()`: the labels of the candidate stories, and of earlier
> episodes, that the input belongs with as one matter.

> **Normative.** `ActivationUnderstanding` gains `story_links: tuple[StoryMember, ...] =
> ()`, in proposal order with no member twice: an `S` label resolves to its story as a
> story member, and a `P` or `M` label naming an episode resolves to that episode's
> activation as an activation member.

> **Normative.** A story label that resolves to nothing, or to a channel item or a
> semantic record, is a label defect under ADR-0276 §6:2 and §6:4: it takes part in the
> one repair completion, and if it remains it is dropped and counted in
> `grounding_dropped`.

> **Normative.** The instruction states that a link says the input belongs to that
> matter and nothing more, that one input may belong to several matters, and that an
> input that belongs to none is linked to none.

**The story-links stage.**

> **Normative.** `ControllerStage` gains the member `story_links` and `ControllerRule`
> the member `story_links_unrecorded`, on ADR-0280 §4:8's rule. The working episode gains
> the **story-links decision**: present once the stage has made it.

> **Normative.** ADR-0280 §4:3's table gains one row immediately after `not_understood`:
> `story_links_unrecorded` answers when *the story-links stage is wired, the
> understanding outcome is a recorded version, and there is no story-links decision*,
> and makes `story_links` due. No other row's order changes.

> **Normative.** The stage reads the latest recorded understanding's `story_links` and
> writes them to the story store with the actor `understanding` and the activation as
> trigger: the activation is linked into each linked story, following a story merged
> since to the story it was merged into; it is linked into every story a linked earlier
> episode belongs to by then; and the earlier episodes that belong to no story by then
> start one new story, holding them and the activation.

> **Normative.** The story-links stage is failure-tolerant under ADR-0281 §5: a
> `StoryStoreError` records the decision as `failed` and the pass goes on.

> **Normative.** Membership the hub records from understanding's links, or by rule, is
> bookkeeping, as the hub records understanding's own record. It is not an action under
> ADR-0292 §12:1–§12:2, in the scope this decision's header gives, and planning does not
> choose it.

So "my running" becomes a story the second time it comes up, whether or not planning
runs.

### 7. Recall brings the stories of what it finds

> **Normative.** `RecallStage` holds an injected `StoryStore` beside its `MemoryStore`.
> For each episode it keeps whose stored id is an activation's episode, it reads
> `StoryStore.stories_of` for that activation, a lookup by identity and never a search.

> **Normative.** `RecalledItem` gains `stories: tuple[Identifier, ...] = ()`: the stories
> the item's episode belongs to directly, in the order the store returns them. A
> semantic item carries none, enforced by validator.

> **Normative.** The lookups run within recall's budget (ADR-0281 §5:4), and a
> `StoryStoreError` is handled as recall handles a `MemoryStoreError`.

### 8. Where the matter stands, and what each reader is shown

**Where the matter stands, worked out.**

> **Normative.** When a reader needs where a matter stands, the hub assembles it from the
> records: what was done, from the effect records of the story's current episodes, unknown
> first, then not done, then done; when things happened, as a short timeline from the
> members' times and understood meanings and the effects, recent first, older ones
> summarised as counts; and the related matters, from the stories it is part of and the
> stories it contains.

> **Normative.** An effect record points at the activation that made it, never at a
> story, so a split, a merge, a move and a corrected link carry effects with their
> episodes.

Effect records come with the phases' acting; until then what was done is empty. Timers
and watches pointing at a story join the list when they are built. A matter that is
related but separate ("the trip depends on the car repair") is a note on the page, not a
link. What is open (questions waiting on the user, next steps, who is doing what) is on
the page, because whether a question has been answered is a judgment.

**What each reader is shown.** Assembled by the hub per reader; nothing is stored per
view.

| Reader | Shown |
| --- | --- |
| **Understanding**, judging whether input belongs | The candidates' short views (§6). |
| **Planning** | For each story the activation belongs to: the full page, its pending entries and episodes, when it was last tidied and how many are pending, the short views of the stories it is part of (marked as inherited), where the matter stands, and the latest episodes (§10). |
| **The user** | Mostly through conversation ("where are we with the trip?"), which planning answers. Directly through the story commands: the page, where the matter stands, and adding a note. |

> **Normative.** `AssistantEngine` gains the **story commands**: reading a story's page,
> with its pending entries and when it was last tidied; reading where its matter
> stands; adding a note, written by `owner`, resting on nothing, unmarked; and moving
> activation members between stories. Each names its story by id. They are added to
> `Engine`, the canonical fake engine and the wire client, and the change advances
> `PROTOCOL_VERSION`.

> **Normative.** The CLI's `story` group gains the story commands, under ADR-0289 §5:1.
> No browser or gateway surface carries them under this decision, and ADR-0289 §5:4
> stands.

> **Normative.** Lines and entries resting on outside content are shown marked in every
> view.

### 9. Starting and reorganising stories

There is no straight line between a matter and a one-off, so a story starts by judgment
as well as by rule, and mistakes are cheap because reorganising is free and invisible.

> **Normative.** A note never starts a story. Planning starts one only by its start call
> (§10), understanding only by §6's rule, and the matters pass only by a split or by
> grouping stories under a larger one.

> **Normative.** A tidy-up raises a **flag** when the page looks like two matters, or like
> another story, by naming that story; the flag is recorded by identity in its version.
> Understanding linking one input to two stories is a flag as well, and its record is the
> change log's lines.

> **Normative.** A background **matters pass**, run on the schedule of the background
> memory work, consolidation, decides each flag: merge, split, move members, group
> stories under a larger one, or leave them. It writes through the store with the actor
> `matters_pass`, and its prompt renders pages under §4's rules. Its changes are
> background maintenance, not actions under ADR-0292 §12:1–§12:2, in the scope this
> decision's header gives.

> **Normative.** No story is dissolved by rule. A story left with no members stays, as
> ADR-0289 §3:3 decides.

> **Normative.** A wrong link is fixed by whoever notices it: the user through the story
> commands, or the matters pass. The moved episode's entries go with it (§3), and its
> effects with it (§8).

> **Normative.** No story change is shown to the user unless asked. Each is in the
> story's change log, and the story commands show it on request.

Matters inside matters are links between stories, which ADR-0289 already supports:
planning's start call can name the story the new one sits inside when the user frames it
so ("plan our summer: camping and visiting Mum"), and the matters pass can group stories
under a larger one. Results that arrive later, such as a reply to an email the assistant
sent, are a watch, built with the timers and watches milestone; until then planning
starts a story whose notes say what it is waiting on ("waiting on the campground's
reply"), and understanding links the reply.

### 10. What the phases build for stories

> **Normative.** Planning's scratch notes for an activation stay in its rounds and are
> never written to a page.

> **Normative.** A note for a story is a **note call** naming a story that exists, one of
> the activation's stories or any story by id, which acting writes as an entry by
> `planning` resting on the activation's episode, with the mark §4 gives it.

> **Normative.** Planning starts a story with one **start call** carrying the story's
> first notes and, optionally, the story it sits inside; the activation's episode joins
> it. Several new stories are several start calls. Linking an activation or a story to a
> story is its own call.

> **Normative.** The tidy-up is a call planning chooses. For each story it is given,
> planning sees when the page was last tidied and how many entries and episodes are
> pending on it, and nothing adds the call to a round by rule.

> **Normative.** The story calls are inside actions under ADR-0292 §12:1–§12:2: planning
> chooses them, authorizing checks them, and acting runs them. Each one's effect is the
> assistant's own records, it leaves no channel, it returns no result except the page
> read, and its outcome is never unknown.

| Call | Takes | Safe to repeat |
| --- | --- | --- |
| **Start a story** | Its first notes; optionally the story it sits inside | No: a second identical start in one activation is refused as already done |
| **Note on a story's page** | A story that exists, by id, and the note | Yes |
| **Link to a story** | A story and the activation, or two stories | Yes |
| **Tidy a story's page** | A story | Yes |
| **Read a story's page** | A story | Yes |

> **Normative.** Each call is declared as the table states, in the declaration form the
> phases' decision gives capabilities. A read of a story's page returns no outside text:
> its lines are the user's or the assistant's words, and a marked line counts as outside
> content for the reader under §4.

> **Normative.** Planning is given, for each story its activation belongs to, the view
> §8's table lists, and may read any other story's page as a direct read of the
> assistant's own records (ADR-0292 §12:3).

> **Normative.** Open questions, next steps and who is doing what are planning's notes
> on the page, and no other record holds them.

### 11. Privacy, for now

> **Normative.** Until privacy is designed, an entry is shown to a reader only where the
> episode it rests on may be shown to that reader, and an entry the user wrote directly
> only where a record placed for the owner alone may be shown. A line is shown only where
> every entry it cites may be shown, so a line copying the user's direct note carries
> that note's restriction.

### 12. The wire and the episode record

> **Normative.** `story_links`, `stories` and the two enum members of §6 change the
> shape of `EpisodicMemory.processing_record`, so each change adding one advances
> `PROTOCOL_VERSION` on ADR-0280 §7:4's rule. Each added field defaults to empty, so a
> record written before it validates unchanged: no `schema_version` changes and the
> episode-record format marker does not advance, as for ADR-0282 §6:1.

> **Normative.** Every other change that alters a shape the wire carries, the story
> types the engine's story methods return and `StoryActor`'s new members included,
> advances `PROTOCOL_VERSION` in that change, on ADR-0124 §9's rule.

> **Normative.** Nothing the understanding phase assembles for the candidates, and no
> story-links decision, is saved with the episode. The links are kept in the
> understanding record and in the story store's change log.

### 13. Delivery

This section is guidance for the lanes, not a ruling. The milestone is built before the
phases, in this order, each lane merging as it lands:

1. **The story store's page** (`core` with `memory`): §3's `StoryStore` change as a
   triad with the SQLite store.
2. **Understanding's links and the rule start** (`core` with `orchestration`): §6's
   fields, labels, the candidates from the episode window with their short views, the
   story-links stage, its rule and row.
3. **Recall's stories** (`orchestration`): §7, and recall's candidates joining §6's.
4. **The tidy-up operation and the engine's test-hub run** (`orchestration`): §5.
5. **The views**: where the matter stands, the timeline and related matters (§8).
6. **The matters pass** (§9).
7. **The story commands** (`orchestration`, `wire`, `interfaces`): §8's engine surface
   and the CLI.

**It goes live with the phases** (owner, 2026-10-07): built first, merged as it lands,
and deployed in the same cutover as the phases and the authority milestone. Until then
it runs on a test hub, where the engine's interim run of the tidy-up is what exercises
it. §10 is built by the phases.

### 14. Relationship to earlier decisions

| Earlier decision | What changes |
| --- | --- |
| ADR-0289 §2:1, §3:14, §4:4, §4:6 | As this ADR's header states |
| ADR-0289 §2:6 | Nothing: its last sentence provides for the actor members §3 adds |
| ADR-0289 §5:1, §5:4 | Nothing: the story commands join the CLI group, and no browser or gateway surface carries them |
| ADR-0276 §1:5, §2:1, §3:3, §3:7, §6:1 | As this ADR's header states |
| ADR-0281 §1:3, §6:1, §7:1 | As this ADR's header states |
| ADR-0282 §2:4, §2:5, §5:1 | As this ADR's header states |
| ADR-0280 §3:5, §4:1–§4:3 | As this ADR's header states |
| ADR-0292 §12:1, §12:2 | As this ADR's header states. Otherwise §12:1's list of inside actions is examples, and starting a story with its first notes, writing a note and tidying a page are more of the same class |

> **Normative.** This numbered draft records its replacements on the status line and in
> a dated header note of ADR-0289, ADR-0276, ADR-0281, ADR-0282, ADR-0280 and ADR-0292,
> atomically
> with this ADR under ADR-0070 and ADR-0082, preserving their ratified bodies. The
> replacements take effect on this ADR's ratification.

## Consequences

**What becomes possible.** A matter carries what was settled weeks ago, in the words it
was said, without a field for each kind of thing. Understanding can link a follow-up days
later to its matter, through the window or through recall, and a second mention starts a
story. Where a matter stands is never stale, because it is never stored. Notes keep their
provenance, so outside content stays marked wherever it travels, and the citations are
in place for forgetting and privacy to be designed against.

**What it costs.** A larger `StoryStore` contract and a triad to land; a model call per
tidy-up; two new fields on records that cross the wire, and a controller stage; and a
test-hub-only run of the tidy-up that is thrown away at the cutover. The live hub gets
none of it until the phases are ready.

**What stays open.**

- **Forgetting**, all of it: what forgetting an episode or a story does to entries, lines
  and the version log. The citations are kept so it can be designed.
- **Privacy** beyond §11's default.
- **Outside text crafted to be laundered** through the tidy-up's citations: an accepted
  risk, as the privacy default rests on the same citations.
- **Facts that become past** rather than false ("the trip is Oct 14" on Oct 15); with
  them, the user's own notes against the page's cap, since the tidy-up may not drop them,
  and the user's own next steps that are done but can be superseded only by the user's
  later words. Whether the user's later direct note, rather than an episode, can
  supersede an earlier one belongs here too.
- **How lasting knowledge reaches beliefs**: observation and consolidation are not
  designed yet, and that design must read the user's direct notes as well as episodes,
  or what is written through the story commands never becomes a belief.
- **Small stories cluttering** understanding's candidates or the views: if the test hub
  shows it, add a rule then, or rank the candidates better.
- **The numbers**: the page's cap, an entry's bound, the candidates' count, the lines in
  a short view.
- **Very long matters** ("my health", "the house"): whether the page's lines need ranking
  once it reaches its cap.
- **Which surface carries the story commands for the user** beyond the CLI. A browser or
  gateway surface needs a decision that replaces ADR-0289 §5:4.
- **How a later understanding corrects a wrong link** ("no, that was about the other
  trip"): its record gains links and nothing that removes one, so until that is decided
  the user and the matters pass fix wrong links.
- **What an unlink with no destination does** to the entries resting on the unlinked
  episode; until then they stay.
- **Whether outside content linked to an earlier episode starts a story.** The wiki's
  Stories page records the owner's 2026-10-03 direction that outside content never
  starts one; this decision's rule start does not distinguish it.
- **If the test hub shows planning forgetting to tidy**, a rule can be added then.

## Alternatives considered

- **One summary per story (a gist)**, as a belief or in the story. It must stay short, so
  old constraints fall out; it mixes moments of different privacy into one text; it goes
  stale.
- **A record of typed items** (what it is, who is in it, settled, deadlines…). Every new
  kind of conversation needs another field, and real speech still does not fit.
- **Everything as beliefs about the story.** A matter's working notes are not lasting
  knowledge and would fill memory with facts that die with it.
- **No page, only the latest episodes.** Enough to recognise a matter; what was settled
  weeks ago falls out of view.
- **A stored state ("booked, waiting for email").** It duplicates the records and goes
  stale.
- **Keeping the page's old versions as text.** A forgotten episode's content would
  survive in them; the identity-only log keeps what was cited when without that.
- **A tidy-up added by rule**, in the background after each activation, or before each
  read. Background work outside the phases, a model call the user waits on, or an action
  planning never chose; a call planning chooses is none of them. The engine's interim run
  is scaffolding for the test hub only.
- **A note starting a story where there is none.** Two notes in one round, whose calls
  run in parallel, would start two stories; one start call carrying the first notes
  cannot.
- **Dissolving small stories by rule.** It removes nothing, since ADR-0289 keeps a story
  with no members; the matters pass already undoes wrong groupings.
- **A capability declaring that its result answers later.** That is a watch, and belongs
  to the timers and watches milestone.
- **Understanding writing its own links.** The stage holds a `ModelProvider` and nothing
  else (ADR-0276 §1:4); a stage of its own records the links, and fails without failing
  the activation.
- **Recall searching for stories.** A story is found by what belongs, not by what is
  similar; a lookup from each episode recall found is exact and costs no model call.
