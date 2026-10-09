# 304. A story's page is its summary, shown where owner records are; a lookalike is not read, and a story is a referent

- Status: Accepted
- Date: 2026-10-09
- Scope: [M42](https://github.com/leonapivato/ai-assistant/milestone/9), after its second acceptance run [#2792](https://github.com/leonapivato/ai-assistant/issues/2792) and the owner's review of the milestone: what a story's page is called, what a tidy-up's run reads, who may be shown a summary, what forgetting reaches, what the *looks like another story* flag is shown and told, what an `S` label resolves to outside `story_labels`, and whether a note may move on its own. It decides [#2794](https://github.com/leonapivato/ai-assistant/issues/2794), [#2793](https://github.com/leonapivato/ai-assistant/issues/2793), [#2796](https://github.com/leonapivato/ai-assistant/issues/2796) and [#2795](https://github.com/leonapivato/ai-assistant/issues/2795).
- Dependency: ADR-0303, implemented at `5b0b094b`.
- Authorization: the owner ruled four times on 2026-10-09: on #2794 and #2793 (option A, with #2796 folded in); on #2795 (a story is a referent); after reviewing M42 against the design, a re-scope; and that a note may move on its own. The re-scope keeps the first ruling's lookalike and flag parts, replaces its forgetting part with the owner-only minimum for privacy and with stories not supporting forgetting for now, and renames a story's page its summary. The dispatcher assigned 0304. That authorizes drafting and numbering, not ratification or implementation.
- **Changes a `core` surface.** Every name that carries a story's page is renamed for the summary, `StoryStore`'s and `AssistantEngine`'s included (§2 below), `StoryStore.move` and `AssistantEngine.move_story_members` take a move of notes alone, `StoryRefusalReason` gains `no_notes`, and `StoryChange` and `StoryLogLine` record a carried note (§9 below); and `UnderstandingReferent.kind` gains `story` (§8 below). A Protocol change under golden rule 5, merged ratified before anything implements it.
- **Partially supersedes** [ADR-0303](0303-a-storys-page-is-free-notes-rewritten-whole-and-the-place-window-links-each-item-to-its-activation.md) — **five scopes.** **§3:3, whole**: a run reads only the summary it replaces (§3 below). **§3:10, §3:11 and §3:12, whole**: a summary is shown where a record placed for the owner alone may be, and nothing behind it withholds it (§4 below). **§5:7's last sentence, whole**: a story shown for the flag is not one the run read, and nothing of its version is recorded (§3 below). **The names its clauses give the page and what carries it, in the renaming alone** (§2 below). **§6:2, §9:2's table's move row, §10:1 and §10:4, in the additions alone**: a move may carry notes and no member, and a note a split or a move carries is logged on both stories (§9 below). Every other clause stands, §3:4, §3:6, §3:7, §3:9, §4:1–§4:3, §5:8, §8:1 and §8:3 included.
- **Partially supersedes** [ADR-0302](0302-the-matters-pass-records-what-it-decides-and-a-page-write-refuses-what-its-story-does-not-hold.md) — **one scope.** **The names its clauses give the page and what carries it, in the renaming alone** (§2 below). Every other clause stands.
- **Partially supersedes** [ADR-0300](0300-a-story-keeps-a-page-of-notes-and-where-its-matter-stands-is-worked-out-from-records.md) — **two scopes.** **The names its clauses give the page and what carries it, in the renaming alone** (§2 below). **§3:14 and §9:3's *move members*, in the additions alone**: a move may carry notes and no member, and a note it carries is logged on each story (§9 below). Every other clause stands.
- **Partially supersedes** [ADR-0276](0276-an-activation-is-understood-before-it-is-associated-and-the-understanding-is-retained-with-its-episode.md) — **one scope.** **§2:5's referent kinds, in the addition alone**: a fourth kind, `story` (§8 below). Every other clause stands, §3:4, §6:2 and §6:4 included.
- **Extends, and replaces no sentence of,** [ADR-0289](0289-a-story-store-holds-which-experiences-belong-to-the-same-matter.md). §2:5's enumeration of what happened gains two members under its own *"added to and never renamed"*, and a line recording a carried note carries one field beside those §2:4 lists, as ADR-0302's `decided` line does. §2:7 stands: the new field is an identity, never free text.

## Context

**The run.** M42's second acceptance run (#2792) drove ADR-0303 on a scratch test hub at
`5b0b094b`. It found the page's privacy and its mark working as ruled, and doing what no
one meant.

- **The mark and the withholding spread through the lookalike display** (#2794). Under
  ADR-0303 §5:7 a story shown for the *looks like another story* flag is a page the run
  read. Under §3:4 a page is marked where its run read a marked page, and under §3:10
  everything behind every page a run read stands behind the page it writes, *"however
  many stories that reaches"*. On a nine-story hub, one parks notice linked into the
  camping story marked five of the six stories with a page within about 35 minutes. One
  of them was an empty page about a cancelled fishing trip. Forgetting one three-turn
  conversation then withheld every page. Because what stands behind a page is
  cumulative, it also withheld every page those stories would ever write.
- **Forgotten content reached the tidy-up's model and was written forward** (#2793).
  After `assistant forget-conversation`, the owner's view and understanding's short views
  withheld the fishing story's page, as §3:11 and §3:12 rule. The tidy-up was still shown
  the page whole, wrote both lines back unchanged as the next version, and showed its
  first line to another story's tidy-up.
- **Sharing an episode brought back the flag pair ADR-0303 §8:1 removed** (#2796). One
  input linked into the camping and the half-marathon stories raised no flag, as §8:1
  rules. The two tidy-ups that followed each raised `like_another` naming the other,
  each shown the other only because *"an episode read here also belongs to it"*. The
  matters pass then spent two completions deciding both `left`.
- **A third of understanding passes paid the repair for an `S` label** (#2795). Fourteen
  of thirty-nine passes made ADR-0276 §6:2's second completion, every one because the
  model cited an `S` label in `references` or `relationships`. There it resolves to
  nothing: ADR-0276 §2:5 and ADR-0281 §7:5 give no referent a story could resolve to.

**The owner's rulings, 2026-10-09.** This decision records them as ruled and settles only
what they leave open.

- **A. A summary shown only for the lookalike flag is not read.** A run reads only the
  summary it replaces. Another story's first line, shown for the flag, is there to judge
  the flag and is not material for this summary. It spreads no mark, the tidy-up copies
  nothing from it, and the instruction says so. The ground is the owner's standing test
  for outside content: a careful human assistant who glances at another folder's label
  to see whether it is a duplicate has not taken material from it.
- **B. Forgetting is not supported by stories for now.** Forgetting a conversation does
  not reach a story's notes, its summary or its version log. A summary may keep text from
  a forgotten conversation, and the tidy-up and the matters pass may read it. Keeping
  `forget-conversation`'s promise for stories does not matter for now. The forgetting
  machinery belongs to the learning design (ADR-0300: *"Forgetting and privacy can
  wait"*).
- **C. Privacy is the minimum.** A story's notes and its summary are records placed for
  the owner alone, whoever wrote them. That is ADR-0303 §3:9's rule for a note, extended
  to the summary. The walk over *what stands behind* a summary, and the withholding it
  decides, retire. The background jobs apply no rule.
- **D. Sharing an episode is not resemblance** (#2796). The instruction says that sharing
  an episode is not by itself a reason to flag: the flag is for a separate story that
  looks like the same matter.
- **E. A story is a referent** (#2795). An `S` label cited in a reference or a
  relationship resolves to that story, as an `M` label resolves to a recalled memory.
  Take "Change of plan for Riverside": what "Riverside" refers to is the story shown as
  `S1`. The rule against citing it fought the model's natural reading, and it threw away
  what the phases' planning will want. The owner chose to remove the rule, not to
  enforce it more cheaply.
- **F. The page is renamed its summary.** Notes stay notes, and episode notes stay
  episode notes. The tidy-up keeps its name. The code, the wire and the CLI follow.
- **G. Outside-content marks are unchanged, deliberately.** The summary-level mark stays
  sticky (ADR-0303 §3:4). What that costs later actions is deferred to the authority
  milestone (#2798).
- **H. A note may move on its own.** A move may name no member and one or more notes:
  the note keeps its words and its author, only its story changes, both change logs
  record it, and it is pending where it lands. Whoever may already move may make one:
  planning's move call, the matters pass and the owner's CLI. #2792 left a fishing note
  on the dentist story after a split, and the pass could not fix it without moving an
  episode.

**The code at `5b0b094b`.**
- `StoryPageVersion.read_pages` records the other stories' page versions a run was shown.
- `story_privacy.behind` walks them and every earlier version.
- `PageVisibility` withholds a page from understanding's short views and the owner's view
  by that walk.
- The tidy-up's `_Reading.outside()` counts a marked other story's page toward the mark.
- Its instruction introduces the other stories right after the flag, with why each is
  shown.
- The understanding stage resolves no `S` label outside `story_labels`.
- `UnderstandingReferent.kind` is `input`, `channel_item`, `episode` or `memory`.
- `StoryStore.move` refuses an empty member list `no_members`, whatever notes it names.
- A note a split or a move carries changes its story row and writes no change-log
  line, so a story's log does not show which notes came or went, though ADR-0303 §6's
  account of the owner's ruling on #2771 says the change log shows the move.

## Decision

We will call a story's page its summary; have a tidy-up read only the summary it
replaces; show a summary wherever a record placed for the owner alone may be shown,
with nothing behind it deciding; leave forgetting out of stories for now; show the
lookalike flag other stories as material for the flag and nothing else; let an `S`
label resolve to its story wherever a label may be cited; and let a note move on its own,
logged on both stories. Every clause below stands
alongside ADR-0303, ADR-0302, ADR-0300 and ADR-0276 except where this decision's header
names a scope it replaces.

### 1. Status and scope

> **Normative.** This document remains `Proposed` until the reviews
> `CONTRIBUTING.md` → "Finishing an ADR PR" requires have returned green on one tree
> and the owner's authorization to ratify stands; an assigned number or a green review
> alone does not change its status.

> **Normative.** No implementation, canonical fake included, implements this decision
> until this numbered ADR has merged `Accepted` under ADR-0015 §5.

### 2. The summary

> **Normative.** A story's current page is called its **summary**. Its notes are still
> called notes, an episode's notes are still called episode notes, and the tidy-up keeps
> its name.

> **Normative.** Where ADR-0300 to ADR-0303 say *page* or *current page* for a story's
> page, they mean its summary, and their ratified bodies keep their wording.

> **Normative.** Every name in the code, the wire and the CLI whose *page* means a
> story's page takes *summary* in its place. That covers the story types that carry the
> page, `StoryStore`'s page operations, the engine's `story_page` and its wire command,
> the composition root's page constants, the CLI's `story page`, which becomes `story
> summary`, and the text of the views and of the model instructions.

> **Normative.** A name whose *page* means a page of a paged read keeps it:
> `MAX_STORY_PAGE`, `StoryPage`, `StoryViewPage`, `StoryLogPage` and `check_story_page`
> among them.

> **Normative.** A stored table, column or record key whose rename would need a store
> migration may keep its name, `pages` and `read_pages` among them.

> **Normative.** The change that renames a shape the wire carries, or a command it
> routes, advances `PROTOCOL_VERSION` in that change, on ADR-0124 §9's rule.

From here on this decision says *summary*, and where it cites an earlier clause about the
page, the clause means the summary.

### 3. What a run reads

> **Normative.** The only summary a tidy-up's run **reads** is the one it replaces, as
> the version that wrote it.

> **Normative.** Another story shown to a run for its *looks like another story* flag
> (§6) is not a summary the run read. It marks nothing under ADR-0303 §3:4, and the run
> records nothing of it.

> **Normative.** Nothing writes `StoryPageVersion.read_pages`, under whatever name §2
> gives it, from this decision on.

> **Normative.** A version written before this decision keeps what it recorded in
> `read_pages` as history that no rule reads.

So the summary's mark comes from the summary the run replaces and from the notes and
episodes the run reads, as ADR-0303 §3:4 states, and never from a story shown for a flag.
The mark stays sticky across versions, as before. ADR-0303 §4:1–§4:3 stand: the store
still accepts the other stories' versions a draft names, and no run names any.

### 4. Privacy is the minimum

> **Normative.** Until privacy is designed, a story's summary is shown to a reader only
> where a record placed for the owner alone may be shown to that reader, whoever wrote
> it, as ADR-0303 §3:9 states for a note.

> **Normative.** Where a summary may not be shown to a reader, none of it is shown, and
> the reader is told that a summary was withheld.

> **Normative.** Nothing behind a summary decides whether it is shown. No rule walks a
> version log to decide it, and no episode or note a version took in withholds it,
> forgotten or not.

> **Normative.** The tidy-up and the matters pass apply no reader's rule. They read the
> notes and the summaries they read today.

So the owner's own view always shows the summary. Understanding's short views show it on
a channel of bounded audience. On a channel of unbounded audience, a spoken path, they
withhold it and say so, exactly as they treat every note (ADR-0303 §3:9). Planning's
views will follow the same rule once the phases build them.

### 5. Forgetting does not reach a story

> **Normative.** Until the learning design decides forgetting for stories, forgetting a
> conversation reaches no story's notes, summary or version log.

That includes what a summary says. A summary may keep text from a forgotten
conversation, and the tidy-up and the matters pass may read it and carry it forward. The
episodes forgetting destroys stay members of their stories as forgotten members, as the
resolved view already shows them (ADR-0289). *What stays open* lists what forgetting must
later reach.

### 6. The lookalike flag

> **Normative.** The stories that share an episode with the run are still shown for the
> flag, first, as ADR-0303 §5:7 states, and the search's after them.

> **Normative.** The tidy-up's instruction states that the other stories are shown only
> to judge the *looks like another story* flag, and that nothing of theirs is copied
> onto this summary.

> **Normative.** The tidy-up's instruction states that sharing an episode is not by
> itself a reason to raise the flag: it is raised for a separate story that looks like
> the same matter.

Understanding links one input into each matter it belongs to (ADR-0303 §8:1), so two
different matters routinely share an episode. Two stories of one matter, which are what
the flag is for, usually share one too. Showing them keeps the flag able to find a
duplicate, and the instruction keeps the shared episode from being read as the reason.

### 7. What the tidy-up's instruction carries

The two sentences below are in the running instruction today. ADR-0303 retired the
clauses they came from, ADR-0300 §5:9 and §4:4, together with the machinery around them,
which was supersession marks and line citations. It did not retire the points
themselves, which the owner agreed in the 2026-10-06 and 2026-10-07 design. This section
states them again so that this text and the instruction agree.

> **Normative.** The tidy-up's instruction states that a vague later remark leaves an
> earlier statement of the user's standing: only the user's later, clear words replace
> it.

> **Normative.** The tidy-up's instruction states that a line resting on outside content
> says only what its source reported, and does not blend sources in one line.

### 8. A story is a referent

> **Normative.** An `S` label cited in `meaning_labels`, in a reference or in a
> relationship resolves to a **`story` referent**: `id` the story's id as the story
> store gave it, `source` the text `story`, and `excerpt` the first line of its summary
> as its short view rendered it, cut on ADR-0276 §2:5's rule, or empty where the view
> rendered no line.

> **Normative.** An `S` label cited outside `story_labels` links nothing: a link is made
> only by `story_labels`, as ADR-0300 §6:7 states.

> **Normative.** A reading an `S` label supports is `supplied`, as for any label.

> **Normative.** An `S` label the stories section rendered is no label defect for being
> cited in `meaning_labels`, in a reference or in a relationship.

> **Normative.** The understanding stage's instruction states three things: an `S` label
> may be cited wherever a label may; citing one outside `story_labels` links nothing; and
> a story's summary and notes are the assistant's own record, provisional and possibly
> out of date.

> **Normative.** The repair statement carries no rule on where an `S` label may be
> cited.

> **Normative.** `UnderstandingReferent.kind`'s `story` changes the shape of
> `EpisodicMemory.processing_record`, so the change adding it advances
> `PROTOCOL_VERSION` on ADR-0280 §7:4's rule.

> **Normative.** A record written before the `story` kind validates unchanged, so its
> change alters no `schema_version` and does not advance the episode-record format
> marker, as for ADR-0300 §12:1.

A `story` referent records which matter a phrase names, by the story store's own id, so
it stays intelligible after a restart, as ADR-0276 §2:5 asks. Nothing resolves it on
read, and a story since merged is a dangling id, which is an ordinary state. Its excerpt
is what the short view rendered, so a withheld summary gives an empty excerpt.

### 9. A note may move on its own

> **Normative.** A **note move** is a move that names no activation member and one or
> more notes. It carries exactly the named notes the story moved from holds, as ADR-0303
> §6:2 states, and nothing else.

> **Normative.** `StoryStore.move` and `AssistantEngine.move_story_members` take their
> activation members defaulting to none. A move naming no member and no note is
> refused `no_members`, as one naming no member is refused today.

> **Normative.** `StoryRefusalReason` gains `no_notes`: a note move none of whose named
> notes the story moved from holds is refused `no_notes`, and changes nothing.

> **Normative.** A note move is refused for its stories as any move is, `unknown_story`
> or `merged_story` for either side, the first story first; then `no_notes`; then
> `unknown_flag` or `already_decided` where it answers a flag.

> **Normative.** A move that names members as well passes over a named note the story
> moved from does not hold, as ADR-0303 §6:2 states.

> **Normative.** Each note a split or a move carries is logged on both stories:
> `StoryChange` gains `note_moved_out`, on the story it leaves, and `note_moved_in`, on
> the story it reaches. Each line names the note and the other story, and carries the
> change's actor and trigger.

> **Normative.** `StoryLogLine` gains `note`, a note id present exactly on a
> `note_moved_out` or `note_moved_in` line. A line written before has none, and
> validates unchanged.

> **Normative.** A note a move carries keeps its text, its author, the activation it was
> written during, its mark and when it was written. Only the story it sits on changes,
> and it is pending on the story it reaches (ADR-0303 §6:2).

> **Normative.** Whoever may make a move may make a note move: planning, by its move call,
> which takes the story moved from, the story moved to, the activation members if any,
> and the notes that go; the matters pass, whose move may name notes by label and no
> episode (ADR-0303 §8:7); and the owner, by the CLI's `story move` naming notes and no
> member.

> **Normative.** The change that adds `no_notes`, the two log kinds and `note` alters
> shapes the wire carries, so it advances `PROTOCOL_VERSION` in that change, on ADR-0124
> §9's rule.

A repeated note move names notes the first story no longer holds, so it is refused
`no_notes` and changes nothing; that is the safe-to-repeat property ADR-0303 §9's table
states for a move. Where the matters pass names no episode and every note it names is one
the hub's check drops (ADR-0303 §8:8), the move reaches the store with no member and no
note and is refused `no_members`. Where its notes survive the check but the story no
longer holds them by the write, it is refused `no_notes`. Either way the pass records the
flag `not_applied` (ADR-0303 §8:6). A merge still carries every note and logs `absorbed`
and `merged_into`, with no line for each note: a merge says the two stories are one
matter, and every note goes.

### 10. Delivery

This section is guidance for the lanes, not a ruling. Each lane merges as it lands, and
all of it goes live with the phases in one cutover (ADR-0300 §13).

1. **The rename** (`core`, `memory`, `wire`, `orchestration`, `interfaces`, `testing`
   and the composition root), first. It is §2, mechanical and sanctioned as
   cross-cutting, and changes no behaviour. It renames `StoryStore`'s operations, so it
   is a Protocol change and owes both lenses. It advances `PROTOCOL_VERSION` once.
2. **Note moves** (`core`, `memory`, `testing`, with the engine, `wire` and the CLI),
   right after the rename. It is §9's store and engine change, as a `StoryStore` triad
   with the SQLite store (ADR-0137 §2), with `move_story_members`, the canonical fake
   engine, the CLI's `story move` and the log's rendering. It owes both lenses and
   advances `PROTOCOL_VERSION`.
3. **The tidy-up, privacy and the matters pass** (`orchestration`: `story_tidy_up.py`,
   `story_privacy.py`, `stories.py`, `story_links.py`, and the matters pass). This is
   §3, §4, §6, §7 and §9's matters-pass move: the run's reads and mark, no `read_pages`
   written, the walk and its withholding removed, the owner-only rule for the summary,
   the instruction's sentences, and a pass move naming notes and no episode. It lands
   after lane 2. It takes no `PROTOCOL_VERSION` step.
4. **The referent kind** (`core` with `wire`): §8's `story` kind, advancing
   `PROTOCOL_VERSION`. Then **understanding** (`orchestration`: `understanding.py`):
   §8's resolution, its instruction and its repair statement.

Lane 2 is not folded into the rename. The rename is reviewed as a change of names that
changes no behaviour, and a semantic change inside it would sit in a large mechanical
diff where that check no longer holds. It follows the rename directly instead, so it
writes against the settled names and touches the same files only after the rename has
landed.

Lane 4 starts once the rename has merged, and it runs in parallel with lanes 2 and 3.
It shares no file with lane 3. Lane 3 changes how a short view decides `withheld` in
`story_links.py`, and lane 4 reads a short view's rendered first line in
`understanding.py`, which lane 3 leaves as it is. Lane 4's referent step and lane 2 both
change `core/types.py` and advance `PROTOCOL_VERSION`, on different types, so whichever
merges second rebases and takes the next number. If lane 2 runs long, lane 3's
matters-pass move can be cut into a small lane of its own after lane 2, so that the
tidy-up and privacy go first.

### 11. Relationship to earlier decisions

| Earlier decision | What changes |
| --- | --- |
| ADR-0303 §3:3, §3:10–§3:12, §5:7, and the page's names | As this ADR's header states |
| ADR-0303 §3:4, §3:6, §3:7, §3:9 | Nothing: the mark's rule and its stickiness, a marked summary counting as outside content, the summary reaching a model as quoted data, and a note's privacy stand; §4 extends §3:9's rule to the summary |
| ADR-0303 §4:1–§4:3, §5:6, §5:8, §5:9, §8:1, §8:3, §10:2 | Nothing: the store's fields, the hub's checks, the outside-only rule, the interim run's start, one input's many links, the tidy-up's flags and the view's *withheld* stand |
| ADR-0302, ADR-0300 | Their names for the page, as this ADR's header states; nothing else |
| ADR-0300 §4:4, §5:9 | Retired whole by ADR-0303, as before. §7 restates the two instruction sentences they carried as this decision's own clauses, without their marks or supersession records |
| ADR-0300 §6:5, §6:7, §6:8 | Nothing: the `S` label scheme, the links and a story label's defects stand. An `S` label also resolves outside `story_labels` (§8) |
| ADR-0300 §3:14, §9:3; ADR-0303 §6:2, §9:2's table, §10:1, §10:4 | As this ADR's header states: a move may carry notes and no member, and a carried note is logged on both stories |
| ADR-0303 §6:1, §6:3–§6:5, §8:6–§8:8 | Nothing: no note moves by its activation, a merge carries every note, an unlink moves none, whoever moves names the notes, and the pass's labels and check stand |
| ADR-0289 §2:4, §2:5, §2:7 | Extended, as this ADR's header states |
| ADR-0276 §2:5 | As this ADR's header states |
| ADR-0276 §3:4, §6:2, §6:4 | Nothing: a label outside the rendered sequences resolves to nothing, and the one repair and its recording stand |
| ADR-0281 §7:4, §7:5 | Nothing: `M` is the precedent `S` follows |

> **Normative.** This numbered draft records its replacements on the status lines and
> in a dated header note of ADR-0303, ADR-0302, ADR-0300 and ADR-0276, atomically with
> this ADR under ADR-0070 and ADR-0082, preserving their ratified bodies. The
> replacements take effect on this ADR's ratification.

## Consequences

**What becomes possible.**
- A mark says something again: a summary is marked where something outside reached it
  through what its runs read, and a story shown beside it for a flag no longer counts.
- No summary is withheld because another story was shown beside it, and none is withheld
  for good because a conversation was forgotten.
- Whether a summary may be shown is one question about the reader, answered without
  reading any log.
- Two different matters sharing an input stop costing two flags by the instruction's
  wording.
- A phrase naming a matter records which matter, and the third of understanding passes
  that paid a repair for it no longer do.
- The code says *summary* for what the owner calls one.
- A note left on the wrong story, such as #2792's fishing note on the dentist story,
  can be moved on its own by planning, the matters pass or the owner, and a story's log
  shows which notes came and went.

**What it costs.**
- `forget-conversation`'s promise does not hold for stories. A summary, a note and a
  version log keep what a forgotten conversation contributed, and the tidy-up and the
  matters pass go on reading it.
- A spoken path is never shown a summary.
- One cross-cutting rename lane with a `PROTOCOL_VERSION` step, a note-move contract
  change and a referent kind with one each, and the lanes after them, on a milestone
  that was code-complete.

**What stays open.**

- **Forgetting, for stories.** The learning design owns the forgetting machinery
  (ADR-0300), and it must later reach:
  - a story's notes, which are never rewritten or removed (ADR-0300 §3:1, ADR-0303 §2:3),
    whose activation is history no rule reads (ADR-0303 §2:4), and which include the safety-net
    notes a migrated test-hub store still holds (ADR-0303 §4:6, §4:8);
  - its summaries, current and earlier;
  - the identities its version log records;
  - the excerpts that `episode` referents and, from §8, `story` referents copy into later
    activations' records.
- **The outside-content mark's reach** ([#2798](https://github.com/leonapivato/ai-assistant/issues/2798)),
  which the owner deferred to the authority milestone. A sticky mark on the whole
  summary (ADR-0303 §3:4), a marked summary counting as outside content in what planning
  reads (ADR-0303 §3:6), and ADR-0181 §5:2 together mean that every outward action on a
  matter outside content once touched needs a one-off approval, for ever. The direction
  to evaluate there is line-level marks by the tidy-up's judgment, under a floor the hub
  keeps.
- **Privacy** beyond the owner-only minimum, for notes and summaries alike.
- **Whether the flag still finds duplicates** that only a shared episode connected, now
  that the instruction says sharing is not resemblance. The next acceptance run shows it.
- **What planning reads of a `story` referent** once the phases hand the understanding
  to a model, under ADR-0276 §2:4's projection rule.

## Alternatives considered

- **Rebuild a summary the tidy-up may not see from what the story still holds**, the
  first draft of this decision under the owner's first ruling. A rebuild could not be
  told apart in the version log, and `write_page` takes in only what was pending. So it
  needed a `rebuilt` field and a `StoryStore` contract change, and it still left notes
  from a forgotten conversation in place. The owner ruled that keeping forgetting's
  promise for stories does not matter yet, and dropped it.
- **Keep the walk, following §3:10 only through the replaced summary** (#2794's second
  option). It keeps a per-reader test over a log whose only use was forgetting, which is
  now out of scope, and the owner retired the walk.
- **Make the tidy-up a reader**, withheld from by the walk. The background jobs work on
  the owner's own records, and once the walk retires there is nothing for them to be
  withheld from.
- **Hide from the lookalike display a story whose summary would be withheld**, which the
  owner's first ruling asked. Under the minimum the tidy-up applies no reader's rule, so
  no summary is withheld from it, and the clause has nothing to act on.
- **Line-level marks now.** A mark set by the tidy-up's judgment needs the hub floor
  #2798 is to evaluate, and the owner deferred it to the authority milestone.
- **Keep the word *page*.** The owner ruled the rename. The code keeping a different
  word from the one the owner uses would put the two vocabularies side by side.
- **Stop showing the stories that share an episode.** Two stories of one matter usually
  share one, and the search passes over the run's own episodes, so it would rarely find
  them.
- **Drop an `S` label cited outside `story_labels` quietly, with no repair** (#2795's
  alternative). It removes the cost but keeps the rule that fights the model's reading,
  and it loses which matter a phrase names. The owner chose to remove the rule.
- **Allow `S` in references and relationships but not in `meaning_labels`.** It keeps a
  special rule of the kind the owner removed, for no reason a reading gives.
- **Fold the note move into the rename lane.** It would put the one semantic change
  inside a diff reviewed as changing no behaviour; §10 sequences it right after
  instead.
- **A separate `move_note` operation.** A move already carries the notes it names, so a
  second operation would duplicate it and widen the surface.
- **A note move naming no held note succeeds and changes nothing.** It would report a
  change that did not happen, and a repeat could not be told from a first move.
- **Log only a note move's notes.** A note carried with members would then still leave
  no trace, against the account of #2771's ruling ADR-0303 §6 gives.
- **A reading a story supports is `inferred`.** A story's summary is quoted source data
  the model was shown, like a recalled memory, which ADR-0281 §7:4 grounds `supplied`.
