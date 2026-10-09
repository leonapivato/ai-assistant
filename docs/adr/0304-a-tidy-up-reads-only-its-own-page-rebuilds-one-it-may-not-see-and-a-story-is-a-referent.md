# 304. A tidy-up reads only its own page, rebuilds one it may not see, and a story is a referent

- Status: Proposed
- Date: 2026-10-09
- Scope: [M42](https://github.com/leonapivato/ai-assistant/milestone/9), after its second acceptance run [#2792](https://github.com/leonapivato/ai-assistant/issues/2792): what a tidy-up's run reads, what stands behind a page, the tidy-up as a reader of a page with forgotten content behind it, what the *looks like another story* flag is shown and told, and what an `S` label resolves to outside `story_labels`. It decides [#2794](https://github.com/leonapivato/ai-assistant/issues/2794), [#2793](https://github.com/leonapivato/ai-assistant/issues/2793), [#2796](https://github.com/leonapivato/ai-assistant/issues/2796) and [#2795](https://github.com/leonapivato/ai-assistant/issues/2795).
- Dependency: ADR-0303, implemented at `5b0b094b`.
- Authorization: the owner ruled on 2026-10-09 on #2794 and #2793 (option A, with #2796 folded in), and the same day on #2795 (a story is a referent). The dispatcher assigned 0304. That authorizes drafting and numbering, not ratification or implementation.
- **Changes a `core` surface.** `StoryPageDraft` and `StoryPageVersion` gain `rebuilt`, and `StoryStore.write_page` takes in what a rebuilt draft names whether or not it was pending (§5 below); `UnderstandingReferent.kind` gains `story` (§7 below). A Protocol change under golden rule 5, merged ratified before anything implements it.
- **Partially supersedes** [ADR-0303](0303-a-storys-page-is-free-notes-rewritten-whole-and-the-place-window-links-each-item-to-its-activation.md) — **five scopes.** **§3:3, whole**: a run reads only the page it replaces, and a rebuild reads none (§2 below). **§3:10, whole**: what stands behind a page follows its own story's log back to the newest rebuild and no other story's page (§3 below). **§4:1's and §4:3's fields, in the additions alone**: a page write and its version also carry whether the page was rebuilt (§5 below). **§5:1's reads, for a rebuild alone**: a rebuild reads every note and held, frozen member episode, and no current page (§4 below). **§5:7's last sentence, whole**: a story shown for the flag is not a page the run read, and nothing of its version is recorded (§6 below). Every other clause stands, §3:4, §3:7, §3:11, §3:12, §4:2, §5:8, §8:1 and §8:3 included.
- **Partially supersedes** [ADR-0300](0300-a-story-keeps-a-page-of-notes-and-where-its-matter-stands-is-worked-out-from-records.md) — **two scopes.** **§3:8's second sentence, for a rebuilt version alone**: it takes in every note and episode its run read, pending or not (§5 below). **§5:2, for a rebuild alone**: it reads no current page, and reads every note and every frozen member episode the store holds (§4 below). Every other clause stands, §3:8's first and last sentences and §6:7 included.
- **Partially supersedes** [ADR-0276](0276-an-activation-is-understood-before-it-is-associated-and-the-understanding-is-retained-with-its-episode.md) — **one scope.** **§2:5's referent kinds, in the addition alone**: a fourth kind, `story` (§7 below). Every other clause stands, §3:4, §6:2 and §6:4 included.

## Context

**The run.** M42's second acceptance run (#2792) drove ADR-0303 on a scratch test hub at
`5b0b094b` and found the page's privacy and its mark working as ruled and doing what no
one meant.

- **The mark and the withholding spread through the lookalike display** (#2794). Under
  ADR-0303 §5:7 a story shown for the *looks like another story* flag is a page the run
  read; under §3:4 a page is marked where its run read a marked page; and under §3:10
  everything behind every page a run read stands behind the page it writes, *"however
  many stories that reaches"*. On a nine-story hub, one parks notice linked into the
  camping story marked five of the six stories with a page within about 35 minutes, an
  empty page about a cancelled fishing trip among them. Forgetting one three-turn
  conversation then withheld every page, and because what stands behind a page is
  cumulative, every page those stories would ever write.
- **Forgotten content reached the tidy-up's model and was written forward** (#2793). After
  `assistant forget-conversation`, the owner's view and understanding's short views
  withheld the fishing story's page, as §3:11 and §3:12 rule; the tidy-up was shown it
  whole, wrote both lines back unchanged as the next version, and showed its first line
  to another story's tidy-up. `story_privacy.py` names its readers as understanding's
  short views and the owner's page view; the tidy-up applies no `PageVisibility`.
- **Sharing an episode brought back the flag pair ADR-0303 §8:1 removed** (#2796). One
  input linked into the camping and the half-marathon stories raised no flag, as §8:1
  rules; the two tidy-ups that followed each raised `like_another` naming the other,
  each shown the other only because *"an episode read here also belongs to it"*, and the
  matters pass spent two completions deciding both `left`.
- **A third of understanding passes paid the repair for an `S` label** (#2795). Fourteen
  of thirty-nine passes made ADR-0276 §6:2's second completion, every one because the
  model cited an `S` label in `references` or `relationships`, where it resolves to
  nothing: ADR-0276 §2:5 and ADR-0281 §7:5 give no referent a story could resolve to.
  The instruction already says an `S` label is cited in `story_labels` alone.

**The owner's rulings, 2026-10-09.** This decision records them and settles only what
they leave open.

- **A. A page shown only for the lookalike flag is not read.** A run reads only the page
  it replaces. Another story's first line shown for the flag is shown to judge the flag,
  not as material for this page: it spreads no mark and nothing behind it, its version
  is not recorded as read, and the instruction says so. A story whose page would be
  withheld is not shown. The ground is the owner's standing test for outside content: a
  careful human assistant who glances at another folder's label to see whether it is a
  duplicate has not taken material from it. Provenance travels where content flows.
- **B. Rebuild, don't read.** The tidy-up is a reader under ADR-0303 §3:11 and §3:12.
  Where its current page would be withheld from it, it does not read that page: it
  rebuilds the page from what the story still holds, its notes and its member episodes,
  within its existing bounds and not only what is pending. The rebuilt version has
  behind it only what it took in, so the forgotten content drops off and the page can be
  shown again. Until the story's next tidy-up the page stays withheld. An immediate
  rebuild on forgetting, and the rest of forgetting, belong to the learning design
  (ADR-0300's *"forgetting and privacy can wait"*).
- **C. Sharing an episode is not resemblance** (#2796). The instruction says that sharing
  an episode is not by itself a reason to flag: the flag is for a separate story that
  looks like the same matter.
- **D. A story is a referent** (#2795). An `S` label cited in a reference or a
  relationship resolves to that story, as an `M` label resolves to a recalled memory.
  "Change of plan for Riverside": what "Riverside" refers to is the story shown as `S1`.
  The rule against citing it fought the model's natural reading and threw away what the
  phases' planning will want. The owner chose to remove the rule, not to enforce it more
  cheaply.

**The code at `5b0b094b`.** `StoryPageVersion.read_pages` records the other stories' page
versions a run was shown, and `story_privacy.behind` follows them. `StoryStore.write_page`
takes in exactly the named notes and episodes that were pending at `as_of`, and records
any other name the story holds as nothing. The tidy-up's `_Reading.outside()` counts a
marked other story's page toward the mark. Its instruction introduces the other stories
right after the flag, with why each is shown. The understanding stage resolves no `S`
label outside `story_labels`, and its instruction and repair statement carry
`_S_LABEL_CITED`. `UnderstandingReferent.kind` is `input`, `channel_item`, `episode` or
`memory`.

## Decision

We will have a tidy-up read only the page it replaces; follow what stands behind a page
through its own story's log alone, back to the newest rebuild; make the tidy-up a reader
of its own page, rebuilding from the story's records a page it may not see; show the
lookalike flag only stories whose pages it may see, as material for the flag and nothing
else; and let an `S` label resolve to its story wherever a label may be cited. Every
clause below stands alongside ADR-0303, ADR-0300 and ADR-0276 except where this
decision's header names a scope it replaces.

### 1. Status and scope

> **Normative.** This document remains `Proposed` until the reviews
> `CONTRIBUTING.md` → "Finishing an ADR PR" requires have returned green on one tree
> and the owner's authorization to ratify stands; an assigned number or a green review
> alone does not change its status.

> **Normative.** No implementation, canonical fake included, implements this decision
> until this numbered ADR has merged `Accepted` under ADR-0015 §5.

### 2. What a run reads

> **Normative.** The only page a tidy-up's run **reads** is the current page it
> replaces, as the version that wrote it, and a rebuild (§4) reads none.

> **Normative.** Another story shown to a run for its *looks like another story* flag
> (§6) is not a page the run read: it marks nothing under ADR-0303 §3:4, nothing behind
> it stands behind the page the run writes, and the run records nothing of it.

So the page's mark comes from the page the run replaces, the notes and the episodes it
reads, as ADR-0303 §3:4 states, and never from a story it was shown for a flag.

### 3. What stands behind a page

> **Normative.** What stands **behind** a page version is every note and every episode
> it took in, and, unless it is rebuilt (§4), everything behind the version before it
> on its story's version log. No other story's page version stands behind it.

The test stays ADR-0303 §3:11's and §3:12's, read from the version log alone. It is
cumulative over a story's own versions because each run reads the page it replaces, and
it stops at a rebuild because a rebuild read no page. It no longer leaves the story, so
its cost is one story's log at most.

### 4. The tidy-up is a reader, and rebuilds a page it may not see

> **Normative.** The tidy-up is a reader of a story's page under ADR-0303 §3:11 and
> §3:12, for its own story's page and for every page it is shown for its flag.

> **Normative.** The tidy-up may be shown every note, and every frozen episode the
> memory store holds. A page is withheld from it where an episode behind the page is not
> one of those, or where a version the walk reaches cannot be read.

That is the rule the tidy-up already reads its own material by: every note pending on
the story, and the pending member episodes that are frozen and held (ADR-0300 §5:2). It
gives the verdict the owner's page view gives for every page, since the owner's view
admits further only an open episode, and no version takes one in.

> **Normative.** Where the story's current page would be withheld from the tidy-up, the
> run does not read it and **rebuilds** the page instead.

> **Normative.** A rebuild reads every note the story holds and every activation
> member's episode that is frozen and that the memory store holds, pending or not, under
> the bounds a run already reads its episodes by. It reads what any run reads besides:
> the decisions recorded for the story, and the other stories §6 shows.

> **Normative.** A rebuild's instruction states that no current page is shown and that
> the page is written anew from the notes and the episodes.

> **Normative.** A rebuild's output is checked and written as any run's (ADR-0303 §5:6),
> as a rebuilt version that takes in every note and every episode the run read.

> **Normative.** Until a rebuild is written, the page stays withheld from every reader
> it is withheld from.

> **Normative.** A rebuild happens only in a tidy-up that starts under the rules that
> start one today, and no forgetting starts one.

A rebuilt page is marked under ADR-0303 §3:4 where a note or an episode it read is: it
read no page, so a mark that came only from a page whose content has dropped off drops
off with it. The run starts, and passes over a story to which only outside content has
come, exactly as before (ADR-0303 §5:8, §5:9).

### 5. The store

> **Normative.** `StoryPageDraft` and `StoryPageVersion` each gain `rebuilt`, a strict
> boolean defaulting to false: the run read no current page.

> **Normative.** `StoryStore.write_page` takes in, for a rebuilt draft, every note and
> episode the draft names that the story holds when the write runs, pending or not, and
> each one it takes in stops being pending.

> **Normative.** A rebuilt draft naming a note or an episode the story does not hold is
> refused `not_held`, as any draft is (ADR-0302 §7).

> **Normative.** For a draft that is not rebuilt, `StoryStore.write_page` takes in
> exactly what ADR-0300 §3:8 and the contract state today: the named notes and episodes
> that were pending at `as_of`.

> **Normative.** The version log records whether each version is rebuilt.

> **Normative.** A version recorded before this decision reads as not rebuilt, and no
> store file is migrated for `rebuilt`.

Everything else a page write checks stands: `as_of`, `page_moved_on`, `over_cap`, the
flags' stories, and the other stories' page versions a draft names (ADR-0303 §4:2),
which no run names from this decision on.

### 6. The lookalike flag

> **Normative.** A story whose current page would be withheld from the tidy-up (§4) is
> not shown for the *looks like another story* flag: not its first line and not its
> label. A story with no page, or an empty one, is shown as before.

> **Normative.** The stories that share an episode with the run are still shown for the
> flag, first, as ADR-0303 §5:7 states, and the search's after them.

> **Normative.** The tidy-up's instruction states that the other stories are shown only
> to judge the *looks like another story* flag, and that nothing of theirs is copied
> onto this page.

> **Normative.** The tidy-up's instruction states that sharing an episode is not by
> itself a reason to raise the flag: it is raised for a separate story that looks like
> the same matter.

Understanding links one input into each matter it belongs to (ADR-0303 §8:1), so two
different matters routinely share an episode, while two stories of one matter, which is
what the flag is for, usually share one too. Showing them keeps the flag able to find a
duplicate; the instruction keeps the shared episode from being read as the reason.

### 7. A story is a referent

> **Normative.** An `S` label cited in `meaning_labels`, in a reference or in a
> relationship resolves to a **`story` referent**: `id` the story's id as the story
> store gave it, `source` the text `story`, and `excerpt` the first line of its page as
> its short view rendered it, cut on ADR-0276 §2:5's rule, or empty where the view
> rendered no line.

> **Normative.** An `S` label cited outside `story_labels` links nothing: a link is made
> only by `story_labels`, as ADR-0300 §6:7 states.

> **Normative.** A reading an `S` label supports is `supplied`, as for any label.

> **Normative.** An `S` label the stories section rendered is no label defect for being
> cited in `meaning_labels`, in a reference or in a relationship.

> **Normative.** The understanding stage's instruction states that an `S` label may be
> cited wherever a label may; that citing one outside `story_labels` links nothing; and
> that a story's page and notes are the assistant's own record, provisional and
> possibly out of date.

> **Normative.** The repair statement carries no rule on where an `S` label may be
> cited.

A `story` referent records which matter a phrase names, by the story store's own id, so
it stays intelligible after restart as ADR-0276 §2:5 asks; nothing resolves it on read,
and a story since merged or never read again is a dangling id, which is an ordinary
state. Its excerpt is what the short view rendered, so a withheld page gives an empty
excerpt and nothing withheld reaches the record.

### 8. Recorded reads, the wire and the records

> **Normative.** Nothing writes `StoryPageVersion.read_pages` from this decision on.

> **Normative.** A version written before keeps what it recorded in `read_pages` as
> history that no rule reads, and the field stays in both types, so no store file is
> migrated for it.

> **Normative.** `rebuilt` crosses no wire: neither `StoryPageDraft` nor
> `StoryPageVersion` is carried by an engine method, so it advances no
> `PROTOCOL_VERSION`.

> **Normative.** `UnderstandingReferent.kind`'s `story` changes the shape of
> `EpisodicMemory.processing_record`, so the change adding it advances
> `PROTOCOL_VERSION` on ADR-0280 §7:4's rule.

> **Normative.** A record written before the `story` kind validates unchanged, so its
> change alters no `schema_version` and does not advance the episode-record format
> marker, as for ADR-0300 §12:1.

A page that a test hub withholds today only because the walk reached another story's
page through `read_pages` is shown again once the walk stops following them; one with
a forgotten episode on its own log stays withheld until its next tidy-up rebuilds it.

### 9. Delivery

This section is guidance for the lanes, not a ruling. Each lane merges as it lands, and
all of it goes live with the phases in one cutover (ADR-0300 §13).

1. **The store** (`core` with `memory`): §5, `rebuilt` on the two types and
   `write_page`'s take-in for a rebuilt draft, as a `StoryStore` triad with the SQLite
   store (ADR-0137 §2). No migration and no `PROTOCOL_VERSION` step.
2. **The tidy-up and the walk** (`orchestration`: `story_tidy_up.py`,
   `story_privacy.py`, `stories.py`): §§2–4 and §6, the walk, the tidy-up as reader, the
   rebuild, the lookalike display and both instruction changes, and §8's first clause.
   It lands after lane 1.
3. **The referent kind** (`core` with `wire`): §7's `story` kind, advancing
   `PROTOCOL_VERSION`.
4. **Understanding** (`orchestration`: `understanding.py`): §7's resolution, its
   instruction and its repair statement. It lands after lane 3.

Lanes 1–2 and lanes 3–4 are independent of each other. The docstrings in `core/types.py`
that describe `read_pages` as what a run read may be corrected in lane 1.

### 10. Relationship to earlier decisions

| Earlier decision | What changes |
| --- | --- |
| ADR-0303 §3:3, §3:10, §4:1, §4:3, §5:1, §5:7 | As this ADR's header states |
| ADR-0303 §3:4, §3:7, §3:11, §3:12 | Nothing: the mark's rule, the page reaching a model as quoted data, and the privacy test stand; what a run reads and what stands behind a page are what change beneath them |
| ADR-0303 §4:2, §5:6, §5:8, §5:9, §8:1, §8:3 | Nothing: a named page version's check, the hub's checks, the outside-only rule, the interim run's start, one input's many links and the tidy-up's flags stand |
| ADR-0300 §3:8, §5:2 | As this ADR's header states |
| ADR-0300 §6:5, §6:7, §6:8 | Nothing: the `S` label scheme, the links and a story label's defects stand; an `S` label also resolves outside `story_labels` (§7) |
| ADR-0276 §2:5 | As this ADR's header states |
| ADR-0276 §3:4, §6:2, §6:4 | Nothing: a label outside the rendered sequences resolves to nothing, and the one repair and its recording stand |
| ADR-0281 §7:4, §7:5 | Nothing: `M` is the precedent `S` follows |

> **Normative.** This numbered draft records its replacements on the status lines and
> in a dated header note of ADR-0303, ADR-0300 and ADR-0276, atomically with this ADR
> under ADR-0070 and ADR-0082, preserving their ratified bodies. The replacements take
> effect on this ADR's ratification.

## Consequences

**What becomes possible.** A mark says something again: a page is marked where something
outside reached it through what its runs read, and a story shown beside it for a flag no
longer counts. Forgetting a conversation withholds only the pages that took it in, and
each of those is shown again once its next tidy-up rebuilds it, with the forgotten
content gone from the page and from what the tidy-up's model is shown. The walk behind a
page reads one story's log. Two different matters sharing an input stop costing two
flags by the instruction's wording. A phrase naming a matter records which matter, and
the third of understanding passes that paid a repair for it no longer do.

**What it costs.** A `StoryStore` contract change and its triad lane, a referent kind
and one `PROTOCOL_VERSION` step, four lanes on a milestone that was code-complete. A
rebuild reads every held note and episode of its story, so on a long story it is a
larger completion than an ordinary run, inside the same budget. A forgotten page stays
withheld until something new comes to its story. The tidy-up may now copy nothing from
a story it was shown for the flag; a line it wrote from one before this decision is on
a page whose walk no longer reaches that story.

**What stays open.**

- **Forgetting**, the rest of it: an immediate rebuild on forgetting, what forgetting
  does to notes, to a `story` or `episode` referent's excerpt in a later activation's
  record, and to anything else that copied text. The learning design (ADR-0300).
- **Privacy** beyond ADR-0303 §3's default.
- **Whether the flag still finds duplicates** that only the shared episode connected,
  once the instruction says sharing is not resemblance: the next acceptance run shows it.
- **A rebuild of a very long story**, which reads every held member under the existing
  bounds: ADR-0300's *very long matters*.
- **What planning reads of a `story` referent** once the phases hand the understanding
  to a model, under ADR-0276 §2:4's projection rule.

## Alternatives considered

- **Keep the lookalike display as a read and follow §3:10 only through the replaced
  page** (#2794's second option). The mark would still spread through the display, and
  the record would still say the run read a page it only glanced at; the owner ruled
  the display is not a read.
- **A later version stops inheriting what an earlier one took in once that is no longer
  on the page** (#2794's third option). Whether something is still on the page is a
  reading of its text, which no rule makes; the rebuild makes it true by construction.
- **Recognize a rebuild from what the version log already records**, with no contract
  change. Nothing recorded tells a rebuild apart: a version that takes in an episode an
  earlier one took in may be a rebuild or an episode linked again, and the store records
  only what was pending as taken in, so a rebuild could not record the older episodes it
  read, and a later forgetting of one of them would not withhold the page.
- **Rebuild as soon as a conversation is forgotten.** It needs forgetting to reach the
  story store, which the owner left to the learning design.
- **Drop `read_pages` from the types.** A stored version carrying it would no longer
  validate, which needs a store migration for a field no rule reads.
- **Show a withheld story to the flag as withheld.** A label with nothing behind it gives
  the flag nothing to judge, and still tells the model a story exists.
- **Stop showing the stories that share an episode.** Two stories of one matter usually
  share one, and the search passes over the run's own episodes, so it would rarely find
  them.
- **Drop an `S` label cited outside `story_labels` quietly, with no repair** (#2795's
  alternative). It removes the cost and keeps the rule that fights the model's reading,
  and loses which matter a phrase names; the owner chose to remove the rule.
- **Allow `S` in references and relationships but not in `meaning_labels`.** It keeps a
  special rule of the kind the owner removed, for no reason a reading gives.
- **A reading a story supports is `inferred`.** A story's page is quoted source data the
  model was shown, like a recalled memory, which ADR-0281 §7:4 grounds `supplied`.
