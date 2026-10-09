# 303. A story's page is free notes rewritten whole, and the place window links each item to its activation

- Status: Proposed
- Date: 2026-10-08
- Scope: [M42](https://github.com/leonapivato/ai-assistant/milestone/9), after its acceptance run [#2772](https://github.com/leonapivato/ai-assistant/issues/2772): what a story's page is, how its marks and privacy are decided, how notes move, which place-window items understanding may link, what a flag is, and what planning's story calls are. It closes [#2773](https://github.com/leonapivato/ai-assistant/issues/2773), [#2774](https://github.com/leonapivato/ai-assistant/issues/2774), [#2777](https://github.com/leonapivato/ai-assistant/issues/2777) and [#2771](https://github.com/leonapivato/ai-assistant/issues/2771).
- Dependency: ADR-0300, ADR-0301 and ADR-0302, implemented at `f1dace5a`.
- Authorization: the acceptance run #2772 found the page's design wrong at the root (#2773). On 2026-10-08 the owner ruled each point this decision records, walking through each with the dispatcher, who assigned 0303. That authorizes drafting and numbering, not ratification or implementation.
- **Changes a `core` surface.** `StoryStore`'s page operations and its `split`, `move` and `leave_flag` change, `AssistantEngine`'s `split_story` and `move_story_members` gain a keyword, and the story page's types, `StoryDecision` and `StoryPageView` change (§§4, 6, 8 and 10 below): a Protocol change under golden rule 5, merged ratified before anything implements it.
- **Partially supersedes** [ADR-0300](0300-a-story-keeps-a-page-of-notes-and-where-its-matter-stands-is-worked-out-from-records.md) — **these scopes.** **§2:2's third precedence, in its reason alone**: the episodes take precedence over the page because the page is written from them, not because it cites them. **§2:4's *"the fields §3 lists"***: the fields §§2–4 below list. **§3:1's *"what it rests on"* and §3:3, whole**: a note records the activation it was written during as plain history (§2 below). **§3:5, whole**: no supersession mark. **§3:6's *"the entries it came from by identity, and whether it is marked"* and its first line's being required**: a line is its text, the page carries one mark, and a page may be empty (§4 below). **§3:7's citations, safety-net entries and supersession marks**: the version records what it took in, its flags and its mark (§4 below). **§3:10's *"together with its safety-net entries"***. **§3:13 and §3:14's *"and moves every entry resting on a moved activation"***: a note goes with a split or a move only where the change names it (§6 below). **§3:17's second sentence**: the cap binds every line. **§4:3, whole; §4:4, whole; §4:5's and §4:6's *line* and *entry*, for the page**: the mark is the page's, decided by rule (§3 below). **§5:2's reads, in the addition alone**: an episode's notes are read with it. **§5:4's *"safety-net entries"* and *"supersession marks"***. **§5:5, whole**. **§5:6, whole**: the instruction §5 below states. **§5:7, whole**: the checks §5 below states. **§5:9, whole**. **§5:12's *"for each story into which the story-links stage (§6) links an activation"***: the run starts when that activation's episode is frozen. **§6:3's second sentence**: the page and its notes are shown under §3 below. **§6:1's sources and their order**: the place window's stories come first (§7 below). **§6:7's resolution and §6:8, for place-window items**: as §7 below states. **§8:5's *"Lines and entries"***: the page and its notes. **§9:1's *"Planning starts one only by its start call (§10)"***: planning also starts one by a split or a grouping. **§9:2's second sentence, whole**. **§9:5's *"The moved episode's entries go with it (§3)"*, and its list of who fixes a link, in the addition alone**: planning fixes one too. **§10:2's *"resting on the activation's episode"***. **§10:3's last sentence and §10:5's table, in the additions alone**: planning's further story calls (§9 below). **§10:6's *"a marked line"***: a marked page. **§10:8's *"and no other record holds them"***. **§11:1, whole**: §3 below. Every other clause stands, §3:8, §3:9, §3:12, §4:1, §4:2, §4:7, §5:3, §5:8, §5:10, §5:11, §6:12 and §12 included.
- **Partially supersedes** [ADR-0301](0301-a-story-label-may-name-an-earlier-episode-the-channel-window-shows.md) — **four scopes.** **§1:2 and §1:3, for what becomes of the label**: a story label naming an item that resolves to no activation is dropped quietly and counted, and is no label defect (§7 below). **§1:3's list, for a transcript message the reader's bookkeeping records**: it resolves (§7 below). **§1:4, in the addition alone**: the resolution also reads the place window's link records, which the window brings with it. **§1:6, whole**: the instruction §7 below states. §1:1's resolution stands, as the record of which activation took in a tail record or a one-exchange item, and so do §1:5, §2 and §3.
- **Partially supersedes** [ADR-0302](0302-the-matters-pass-records-what-it-decides-and-a-page-write-refuses-what-its-story-does-not-hold.md) — **six scopes.** **§2:2, whole, and §2:3's understanding arm**: understanding raises no flag (§8 below). **§3:3's members, in the addition alone**: `not_applied`. **§4:1's operation, in the addition alone**: `leave_flag` also records `not_applied`. **§5:2, whole, and §5:3's understanding arm**. **§5:6's first sentence's *"records the flag `left`"***: it records `not_applied`. **§7:2's and §7:4's safety-net arm**: there are no safety-net notes. Every other clause stands, §2:1, §2:4, §3:1, §3:2, §3:4–§3:6, §4:2–§4:6, §5:1, §5:4, §5:5, §6, §7:1, §7:3 and §7:5 included.
- **Partially supersedes** [ADR-0292](0292-a-channel-is-the-spokes-facing-one-thing-and-the-assistants-edge-is-its-own.md) — **one scope.** **§10:1, in the addition alone**: a kind whose medium holds a history but no stable item ids may declare an episode window instead (§7 below). Every other clause stands, §10:2 included.

## Context

**The run.** M42 was code-complete at `afcaab9d`, and its acceptance run on a test hub
(#2772) found that the page was wrong at its root, not at its edges.

- **Lines had to cite notes** (ADR-0300 §3:6, §5:7). Before the phases nothing writes a
  `planning` note, so a story with no note of the user's could get a page only through
  a safety-net note the model invented first. The model cited episodes instead and its
  output was refused: the camping story's first three runs, and every one of the
  thermostat story's six. Once a note existed, every line cited it whatever it said, so
  the marks (§4:4), the privacy default (§11:1) and which notes a split carried
  (§3:13) all rode citations that were not true (#2773).
- **The user's own note outlived the user.** A tidy-up recorded the user's clear later
  statement as superseding a note and kept the note's text as a line, because the
  check required every *other* owner note verbatim and nothing refused one superseded;
  the page went on saying showers were required and the long run was on Saturdays
  (#2774).
- **A conversation's own earlier turns could not be linked on the chat path** once the
  episode window had moved past them: the transcript is the one place they are always
  shown, and its messages are neither linkable nor a source of candidates (#2777,
  which ADR-0301's *What stays open* named).
- **A split never took the user's own notes**, because the matters pass is never shown
  them by label (#2771, which the owner ruled on 2026-10-08: the pass may move them).

**The owner's rulings, 2026-10-08.** Each was walked through with the dispatcher and
is recorded here as ruled; this decision writes them as one design and settles only
the details they leave open.

- **A. The page is a free page of notes**, the owner's idea from the 2026-10-06 design
  session. Anything working on the matter may write a note: planning through its
  calls, the user directly (rarely), and the tidy-up, which rewrites the current page.
  Writing a note is always discretionary, at the episode level and at the story level:
  a story may have an empty page, and a tidy-up may write nothing. Page lines cite
  nothing, safety-net notes are retired, and notes are not tied to an episode; *written
  during activation X* stays as plain history nothing depends on. A note is marked when
  it is written if its writer's activation read outside content, from the hub's records
  and never the model's judgment; the page is marked if any marked note or outside
  episode fed it, and the lines' words say which part. Privacy is page-level: the page
  is shown only where everything behind it may be shown.
- **B. All notes are equal.** A note the user writes directly is treated as if the user
  had said it through the assistant. The owner-note special rules are retired: the
  verbatim check, supersession marks, the cap exemption and its own privacy clause. A
  direct note is never marked as outside content. The tidy-up's instruction says the
  user's newer statement wins, the user's stated requirements stay until the user
  changes them, and finished next steps and answered questions drop off.
- **C. Moving notes.** A split or a move does not carry notes by their episode; whoever
  makes the change names the notes that go. A merge carries all of the absorbed story's
  notes, because a merge says the two are one matter: the owner ruled so on 2026-10-08,
  correcting a first wording of C that named merges too.
- **D. The place window.** An item in it links to the activation that took it in or
  wrote it; the records use the medium's own item ids; the candidates are those
  activations' stories, this place's first, then the episode window's, then recall's; an
  unresolvable item is shown as not linkable, and naming one is dropped quietly and
  counted with no repair call; a running activation may be linked; and a kind whose
  medium has no stable item ids may declare an episode window. ADR-0292 §10:2: *"The
  window belongs to the place"*.
- **E. Outside-only stories are allowed.** They form by the same rule, and their page is
  not tidied while only outside content has touched it.
- **F. Planning holds the control.** Organizing episodes into stories is mostly invisible
  to the user unless they look. Planning's story calls gain unlink, move, merge, split
  and group under a larger story, each an inside action declaring its properties.
  Understanding's links stay additive bookkeeping, and the matters pass stays
  background maintenance.
- **G. Flags only by judgment.** One input linked to two stories is two links, not a
  flag. The tidy-up's *looks like another story* considers likely lookalikes found by
  search, not only stories sharing an episode. *Looks like two matters* stays.
- **H. Smaller rulings.** The story list shows each story's first line. The story
  commands stay CLI-only for M42. A next step may sit in a page note, an episode note or
  a timer. The tidy-up is told the page cap and condenses to fit, the store's refusal
  staying as a backstop. The interim tidy-up starts when the triggering activation's
  episode is frozen. A change the store refuses is recorded honestly as *couldn't
  apply*, not `left`, and is still not retried on nothing new.
- **I. Episode notes**, planning's notes for an activation, belong to the phases'
  proposal [#2723](https://github.com/leonapivato/ai-assistant/pull/2723): they live
  with the episode and are read wherever it is read.

**The code at `f1dace5a`.** `StoryNote` carries `rests_on`; `StoryPageLine` carries
`cites` and `outside`; `StoryPageVersion` records each line's citations, the safety-net
notes, the supersession marks and the flags; `StoryPageDraft` carries `safety_net` and
`supersessions`. `StoryStore.split` moves every note resting on a moved activation and
the `owner` notes it names, `move` every note resting on a moved activation, and
`merge` every note. The chat's reader keeps its bookkeeping in
`ConversationStore.taken_in`, keyed by a message's position in its conversation
(ADR-0293 §6:6). `UNDERSTANDING_STORY_CANDIDATES` is 5 in `app/composition.py`.

## Decision

We will make a story's page a free page of notes that anything working on the matter may
write and that the tidy-up rewrites whole, with no citations, one page-level mark and
page-level privacy; let notes move only where whoever moves members names them; let
understanding link any place-window item to the activation that took it in or wrote it;
keep flags to the tidy-up's judgment; and give planning the whole set of story calls.
Every clause below stands alongside ADR-0300, ADR-0301, ADR-0302 and ADR-0292 except
where this decision's header names a scope it replaces.

### 1. Status and scope

> **Normative.** This document remains `Proposed` until the reviews
> `CONTRIBUTING.md` → "Finishing an ADR PR" requires have returned green on one tree
> and the owner's authorization to ratify stands; an assigned number or a green review
> alone does not change its status.

> **Normative.** No implementation, canonical fake included, implements this decision
> until this numbered ADR has merged `Accepted` under ADR-0015 §5.

> **Normative.** Where this decision states what the phases build (§9) or how an
> episode's notes are read (§§5, 8), it binds the decision that converts #2723, and binds
> no lane before that decision is ratified.

### 2. The page is a free page of notes

A story's page is still two records the story store keeps beside the story, its
**notes** and its **current page**, with a **version log** (ADR-0300 §3). What changes
is what ties them together: nothing does, except that the tidy-up reads the notes and
writes the page.

> **Normative.** A note may be written by planning, through its note call and its start
> and grouping calls (§9), or by the user directly, through the story commands. The
> tidy-up writes no note: it rewrites the current page.

> **Normative.** No rule requires a note to be written, by planning for an activation or
> for a story, or by any other writer. A story may have no note and an empty page.

> **Normative.** A note carries its text, within a bound on its length; who wrote it;
> the activation it was written during, where it was written during one; whether it is
> marked; and the store's clock reading when it was written. None of these changes once
> it is written, and no note is removed.

> **Normative.** The activation a note was written during is history. No rule reads it:
> not a merge, a split or a move, not the mark, not privacy, not what is pending, and
> not the tidy-up's checks.

> **Normative.** A note the user wrote directly records no activation, and every other
> note records the activation it was written during.

> **Normative.** A note the user writes directly is read, rendered and weighed exactly as
> what the user says through the assistant is, and no rule treats it otherwise: no
> check requires its text on the page, nothing marks it superseded, the cap counts the
> lines that came from it, and its privacy is every note's (§3).

> **Normative.** The **current page** is zero or more short lines, the first of them,
> where there is one, saying what the matter is. A line carries its text and nothing
> else, and cites nothing.

> **Normative.** Open questions, next steps and who is doing what may be noted on the
> page, and may also sit in an episode's notes or in a timer; no rule requires them in
> one record rather than another.

Lines still carry their nuance in their words: "You're leaning against Saturday, not
decided." "A parks notice said the lower loop closes on the 15th." A line that came from
outside content says so in its words, and the page's mark (§3) says that some line does.

### 3. Marks and privacy

> **Normative.** A note is marked when it is written where the activation its writer
> wrote it during read outside content, by the hub's record of what that activation
> read, and never by the writer's judgment. A note the user wrote directly is never
> marked.

> **Normative.** An **outside episode** is one whose trigger's `origin` is `outside`
> (ADR-0284 §2:1), or whose activation's record of what it read shows outside content.

> **Normative.** The pages a tidy-up's run **reads** are the current page it replaces
> and each other story's page it is shown for its flags (§5), each as the version that
> wrote it.

> **Normative.** The current page is **marked** where the run that wrote it read a
> marked note, an outside episode, or a marked page. The hub sets the mark by that rule,
> never by the model's output.

A marked page stays marked through every later tidy-up, because each run reads the page
it replaces: provenance travels, and a page that once took in "the email said" keeps
saying that something on it came from outside.

> **Normative.** The tidy-up's instruction states that a line resting on outside content
> says so in its words.

> **Normative.** A marked page or a marked note that planning reads counts as outside
> content in that activation's record of what it read, under ADR-0300 §4:5's rule.

> **Normative.** The page and every note reach a model as quoted source data under
> ADR-0098 §2, attributed by their records, the page as the tidy-up's and marked or not,
> a note by who wrote it and whether it is marked, and never by their text. A marked one
> is shown as outside content and never as the user's words.

> **Normative.** Every view shows the page's mark and each note's mark.

**Privacy, for now.** ADR-0300 §11:1 decided a line's privacy from the notes it cited
and a note's from the episode it rested on. A line cites nothing and a note rests on
nothing, so neither test survives.

> **Normative.** Until privacy is designed, a note is shown to a reader only where a
> record placed for the owner alone may be shown to that reader, whoever wrote it.

> **Normative.** What stands **behind** a page version is every note and every episode
> it took in, and what stands behind each page version its run read: so, through the
> page each run replaced, everything every earlier version of that story took in, and
> through each other story's page a run was shown, everything behind that page's
> version, however many stories that reaches.

> **Normative.** Until privacy is designed, the current page is shown to a reader only
> where everything behind it may be shown to that reader. Otherwise none of it is
> shown, and the reader is told that a page was withheld.

> **Normative.** An episode or a note behind a page that the reader's caller cannot
> establish may be shown, because it is open, forgotten, no longer held or not looked
> up, withholds the page.

The test reads the version logs' identities and the reader's own answers about episodes
and the owner's records, as `PageVisibility` does today; it reads no line's text. It is
cumulative because each run reads the page it replaces, so whatever any version took in
may still be on the page; and it follows the other stories' pages a run was shown,
because a line shown for a flag may still have been copied onto the page. A story's page
can reach its own earlier versions through another's, so the walk visits each version
once.

### 4. The store

> **Normative.** A page write takes the new current page's lines, the notes and episodes
> its run read and so takes in, the other stories' page versions its run read, its
> flags and its mark, and writes no note.

> **Normative.** An other story's page version a page write names is checked only as an
> identity the store holds, refused `unknown_story` where the store holds no such story
> and malformed, a `ValueError`, where it names the story written or a version that
> story has not reached. It is never a member, so ADR-0302 §7's `not_held` does not
> apply to it.

> **Normative.** The **version log** stays append-only, identities, instants and
> enumerations only. Each version records when it was written, the notes and the
> episodes it took in, the other stories' page versions its run read (§3), the flags it
> raised, and whether the page it wrote is marked.

> **Normative.** `StoryStore.write_page` refuses as ADR-0300 §3:10 and ADR-0302 §7 state,
> less what this decision retires: no line cites a note, so it answers `unknown_note`
> for no line, and `not_held` only for an episode or a note named as taken in.

> **Normative.** A page write is refused `over_cap` where its lines together exceed the
> current page's cap, every line counted.

> **Normative.** `StoryNoteAuthor` keeps its members. Nothing writes a note as `tidy_up`
> from this decision on, and a note written so before stays a note like any other.

> **Normative.** `StoryStore.append_note` takes the activation a note was written
> during in place of what it rests on, under §2's rule for who records one.

> **Normative.** The store's file is migrated in place under a new layout version: every
> note is kept, its resting activation becoming the activation it was written during;
> every version and the current page's text are kept; what a version recorded of each
> line's citations, its safety-net notes and its supersession marks is dropped; a
> version written before records no other story's page version; and the current page
> is marked where any of its lines was.

Nothing of ADR-0300 is live outside a test hub until the phases' cutover (ADR-0300
§13), so no record outside a test hub carries what the migration drops.

### 5. The tidy-up

> **Normative.** A tidy-up of a story reads what ADR-0300 §5:2 states, and with each
> episode it reads, that episode's notes, where the phases' decision gives episodes
> notes.

> **Normative.** The tidy-up's one completion produces the new current page's lines and
> its flags, and nothing else. It may produce no line.

> **Normative.** An output with no line is written as an empty page, a version that
> takes in what the run read like any other, so what it read stops being pending.

> **Normative.** The tidy-up's instruction states: the user's newer statement wins over
> an older one, whether either was said in an episode or written as a note; the user's
> stated requirements stay on the page until the user changes them; and a next step
> that is done, and a question that has been answered, drop off.

> **Normative.** The tidy-up's instruction states the current page's cap, and that the
> page is condensed to fit within it.

> **Normative.** The hub checks the output by rule before writing it: it parses, every
> flag names what it may, and the lines fit the cap. An output that fails is refused
> whole under ADR-0300 §5:8, and the store's `over_cap` stays the backstop.

> **Normative.** For its *looks like another story* flag, the tidy-up is shown, beside
> the other stories its episodes belong to, the stories of the episodes a search of the
> memory store finds, as recall searches it (ADR-0281), with a query built from what the
> run reads; each story is shown by its current page's first line, and no more than a
> composition-root constant counts them all. Each page so shown is a page the run read
> (§3), and its version is recorded with the version the run writes.

> **Normative.** A tidy-up does not start on a story to which nothing but outside
> content has come: every activation member's trigger `origin` is `outside`, and every
> note it holds is marked. What is pending there stays pending, and the first run after
> anything else comes to the story takes it all in.

> **Normative — before the phases.** The engine's interim tidy-up (ADR-0300 §5:12)
> starts when the episode of an activation the story-links stage linked into a story is
> frozen, for each story the stage linked it into on whose page anything is pending,
> and not when the link is written.

An episode's notes are #2723's to decide: what they are, who writes them and when. This
decision states only that the tidy-up, and the matters pass (§8), read them with their
episode.

### 6. Moving notes

> **Normative.** A split or a move carries no note by the activation it was written
> during. It carries exactly the notes it names, each of them a note the story it moves
> from holds.

> **Normative.** `StoryStore.split` and `StoryStore.move` each take the notes that go,
> defaulting to none. Each named note the story moved from holds moves to the other
> story in the operation's transaction and is pending there; a named note it does not
> hold is passed over, as `split` passes one over today.

> **Normative.** A merge carries every note the absorbed story holds to the story it is
> merged into, in the merge's transaction, as ADR-0300 §3:12 states, because a merge
> says the two stories are one matter. It names no note.

> **Normative.** An unlink moves no note.

> **Normative.** Whoever makes a split or a move names the notes that go: planning in
> its call (§9), the matters pass in its reply (§8), or the user in the story command
> (§10).

A user's note moved by planning or the pass keeps its words; only the story it sits on
changes, and the change log shows the move, as the owner ruled on #2771.

### 7. The place window

The window belongs to the place (ADR-0292 §10:2). ADR-0276 calls it the channel window;
this decision calls it the **place window**, and changes no rendering of it but the mark
below.

> **Normative.** An item of the place window links to the activation that **took it
> in**, by the record its sensor keeps, or that **wrote it**, by acting's effect record
> once the phases build it.

> **Normative.** The records an item links by name it by the medium's own item id: a
> conversation's message by its position (ADR-0293 §6:6), and a stored episode by its
> stored id.

> **Normative.** The sensor brings, with the place window, the activation each item
> links to where its records hold one, so the understanding phase reads no further store
> to resolve an item.

So the chat's reader brings, with each transcript message, the activation its
bookkeeping records as having taken the message in. A tail record and a one-exchange
item link to the activation the stored episode records, as ADR-0301 §1:1 resolves them.

> **Normative.** In `story_labels`, an `H` label naming a place-window item that links
> to an activation resolves to that activation as an activation member, as a `P` label
> naming that activation's episode does.

> **Normative.** A place-window item that links to no activation is rendered marked as
> not linkable.

> **Normative.** A story label naming a place-window item that links to no activation is
> dropped and counted in `grounding_dropped`. It is no label defect: it takes no part in
> the repair completion and calls for none.

> **Normative.** An item may link to an activation still running, and the story-links
> stage links to it as to any other (ADR-0300 §6:12).

> **Normative.** The instruction states that a story label may name any place-window
> item that is not marked not linkable.

> **Normative.** Before the understanding stage renders, the candidates are assembled
> up to `UNDERSTANDING_STORY_CANDIDATES`: first the stories of the activations the place
> window's items link to, newest item first; then the stories the episode window's
> episodes belong to, in the window's order; then the stories recall's kept episodes
> belong to, as ADR-0300 §6:1 orders them. A story already a candidate is not repeated.

> **Normative.** A kind whose medium holds a history but has no stable item ids may
> declare an episode window: its place window is then the recent episodes on that
> channel and place, and each links to the activation it records.

Before the phases, nothing records which activation wrote an assistant message, so an
assistant message in the transcript is rendered not linkable; the user's message before
it, which the same activation took in, links.

### 8. Flags and the matters pass

> **Normative.** Understanding linking one input to two or more stories raises no flag.
> It is that many links, and no rule reads it as anything else.

> **Normative.** The matters pass reads no understanding flag, and the store holds none:
> a write answering a flag named by an activation is refused `unknown_flag`, under
> ADR-0302 §4:4. A `decided` line already answering one stays in the change log and is
> rendered as before.

> **Normative.** A tidy-up's flags are the only flags: *looks like two matters* and
> *looks like another story*, as ADR-0300 §9:2's first sentence states.

> **Normative.** `StoryDecision` gains `not_applied`: the decider chose a change the
> store refused, and no story changed.

> **Normative.** `StoryStore.leave_flag` takes the outcome it records, `left` by default
> or `not_applied`; any other outcome is malformed, a `ValueError`.

Both outcomes record that no story changed, which is why one operation may write either:
ADR-0302's alternative of one operation taking any outcome was rejected because it could
record a merge where nothing merged, and neither of these records a change.

> **Normative.** Where the store refuses the change the matters pass chose for a reason
> other than `unknown_flag` or `already_decided`, the stories stay as they are and the
> pass records the flag `not_applied`.

A `not_applied` decision answers its flag as `left` does: the store's `already_decided`
check holds for it, so the pass does not retry it, and a later flag raised on something
new is decided shown it (ADR-0302 §5:4).

> **Normative.** For a split or a move, the matters pass is shown the notes of
> the story the change moves from, each by a label of the run's, newest first, up to a
> composition-root constant, and its reply names by label the notes that go.

> **Normative.** The hub checks by rule that each note the pass names is one the story
> moved from holds, and a name that is not is dropped before the write.

> **Normative.** The matters pass reads an episode's notes with the episode, where the
> phases' decision gives episodes notes.

### 9. What the phases build for stories

> **Normative.** Planning's story calls are those ADR-0300 §10 lists and also: unlink, to
> remove an activation or a story from a story; move, of activation members from one
> story to another; merge, of one story into another; split, of members off a story into
> a new one; and group, of stories under a new larger one.

> **Normative.** Each further call is an inside action under ADR-0292 §12:1–§12:2, as
> ADR-0300 §10:5 states for the story calls, and is declared as the table below states,
> in the declaration form the phases' decision gives capabilities.

| Call | Takes | Safe to repeat |
| --- | --- | --- |
| **Unlink from a story** | A story, and an activation or a story it holds | Yes: a member the story no longer holds is passed over |
| **Move members** | The story moved from, the story moved to, the activation members, and the notes that go | Yes: a repeat names members the first story no longer holds and is refused, changing nothing |
| **Merge stories** | The story absorbed and the story it joins; every note of the absorbed story goes with it | Yes: a repeat names a merged story and is refused, changing nothing |
| **Split a story** | The story, the members that leave, and the notes that go | Yes: a repeat names members the story no longer holds and is refused, changing nothing |
| **Group under a larger story** | The stories grouped; optionally the larger story's first notes | No: a second identical grouping in one activation is refused as already done |

> **Normative.** A note call writes a note by `planning` recording the activation it was
> written during, with the mark §3 gives it.

> **Normative.** Planning names the notes that go with a move or a split by the
> labels the view it was given renders, and the phases' decision says how that view
> labels them.

Planning's story calls change stories; understanding's links stay bookkeeping that only
adds (ADR-0300 §6:14), and the matters pass stays background maintenance (ADR-0300
§9:3). A split and a grouping start a story, as a start call does.

### 10. The story commands and the views

> **Normative.** `AssistantEngine`'s `split_story` and `move_story_members` each take
> the notes that go, defaulting to none, and pass them to the store as §6 states.
> `merge_stories` is unchanged, and its merge carries every note.

> **Normative.** The story page view carries the current page's lines and its mark, or
> that it was withheld; the story's notes, newest first up to a composition-root
> constant, each with its id, its mark and whether it is pending, and the count of those
> beyond it; and when the page was last tidied.

> **Normative.** The CLI's story list shows, beside each story, its current page's first
> line where it has one, read through the engine's story page command, so neither the
> engine surface nor the store gains a read for it.

> **Normative.** The CLI's split and move commands take the notes that go.

> **Normative.** The story commands stay CLI-only for M42. No browser or gateway surface
> carries them under this decision, and ADR-0289 §5:4 and ADR-0300 §8:4 stand.

The story page view no longer says which note a line came from, because no line came
from one by record. It lists the notes so that the user can name them in a command.

### 11. The wire and the episode record

> **Normative.** The change that alters a story type the engine's story methods carry
> (`StoryNote`, the current page and its lines, `StoryPageView`, and `StoryDecision`
> through `StoryLogLine`) advances `PROTOCOL_VERSION` in that change, on ADR-0300
> §12:2.

> **Normative.** The change that gives `split_story` and `move_story_members` their
> notes advances `PROTOCOL_VERSION` in that change.

> **Normative.** The place window's linking changes no shape the wire carries and no
> shape of `EpisodicMemory.processing_record`: `story_links` holds the same
> `StoryMember` values and `grounding_dropped` the same count. It advances no
> `PROTOCOL_VERSION`, changes no `schema_version` and does not advance the
> episode-record format marker.

`StoryPageDraft`, `StoryDraftLine` and `StorySafetyNetNote` cross no wire; they change or
go with the store.

### 12. Delivery

This section is guidance for the lanes, not a ruling. Each lane merges as it lands, and
all of it goes live with the phases in one cutover (ADR-0300 §13).

1. **The store** (`core` with `memory`): §§2, 4, 6 and §8's `StoryDecision` and
   `leave_flag`, every story type this decision changes, as a `StoryStore` triad with the
   SQLite store and its migration (ADR-0137 §2), advancing `PROTOCOL_VERSION`. Where a
   type it changes would leave a consumer unbuildable, it changes that consumer only as
   far as building and this decision require, as ADR-0302 §10:1 let its store lane.
2. **The tidy-up** (`orchestration`): §5 and §3's marks: its reads, its output, its
   instruction, its checks, the lookalike search, the outside-only rule and the interim
   run's start.
3. **The views and the privacy filter** (`orchestration`, with the CLI's rendering):
   §3's privacy, in the short views, the story page and where the matter stands, and
   §10's page view.
4. **The matters pass** (`orchestration`): §8, the notes it names, and an episode's
   notes once they exist.
5. **The place-window linking** (`orchestration`): §7, with the chat's reader bringing
   its bookkeeping.
6. **The story commands and the CLI's list** (`orchestration`, `wire`, `interfaces`):
   §10's keywords and options and the list's first line, advancing `PROTOCOL_VERSION`.

Planning's calls (§9) are built by the phases.

### 13. Relationship to earlier decisions

| Earlier decision | What changes |
| --- | --- |
| ADR-0300 §§2–6, §§8–11 | As this ADR's header states |
| ADR-0300 §3:8, §3:9, §3:12, §5:3, §5:8, §5:10, §5:11 | Nothing: pending, the cap's existence, a merge carrying every note, the rendering, the refusal of a failed output, one run at a time and nobody waiting stand |
| ADR-0300 §6:12, §6:14, §7, §12 | Nothing: the links' writing, their being bookkeeping, recall's stories and the wire rule stand |
| ADR-0301 §1:2–§1:4, §1:6 | As this ADR's header states |
| ADR-0301 §1:1, §1:5, §2 | Nothing: §1:1 is the record a tail or one-exchange item links by |
| ADR-0302 §2:2, §2:3, §3:3, §4:1, §5:2, §5:3, §5:6, §7:2, §7:4 | As this ADR's header states |
| ADR-0302 §3:4–§3:6, §4:2–§4:6, §5:1, §5:4, §5:5, §6 | Nothing: decisions are lines, written in the change's transaction, decided once, and shown to the tidy-up and the pass |
| ADR-0292 §10:1 | As this ADR's header states |
| ADR-0292 §10:2–§10:4, §12 | Nothing: the window is the place's, keeps its authors and never authorizes, and the story calls are inside actions |
| ADR-0293 §6:4–§6:8 | Nothing: the reader's bookkeeping is the record a transcript message links by, and the reader brings it with the window it already brings |
| ADR-0276 §3, §6 | Nothing: the label scheme, one exchange and the repair stand; §7's not-linkable mark is data the stage holds |
| ADR-0289 §4, §5:4 | Nothing: the engine's writes still carry `owner`, and no browser or gateway surface carries the story commands |

> **Normative.** This numbered draft records its replacements on the status lines and
> in a dated header note of ADR-0300, ADR-0301, ADR-0302 and ADR-0292, atomically with
> this ADR under ADR-0070 and ADR-0082, preserving their ratified bodies. The
> replacements take effect on this ADR's ratification.

## Consequences

**What becomes possible.** A story's first page can be written from its episodes alone,
so the thermostat story gets one. The user's newer statement replaces the older one on
the page, whether either was a direct note. A conversation's own earlier turns link on
the chat path however far the episode window has moved, and their stories are the first
candidates. Notes move where whoever moves the members says they go, the user's included.
Planning can undo any grouping it or understanding made, and a flag is raised only by
judgment. A refused change is recorded as what happened.

**What it costs.** Every guarantee that rode a line's citation now rides the page as a
whole: one mark for the page, sticky across versions, and a privacy test over everything
behind it, the other stories' pages its runs were shown included, which withholds a
whole page where ADR-0300 withheld a line. An activation that reads a marked page counts
as having read outside content, so the notes it writes are marked too. Notes
are shown to a reader only where the owner's own records are, so a reader on a wider
audience sees no note. The page loses the user's verbatim notes as a guarantee and keeps
them as an instruction.
A `StoryStore` triad, a store migration, two `PROTOCOL_VERSION` steps, and six rework
lanes on a milestone that was code-complete.

**What stays open.**

- **Privacy** beyond §3's default, which withholds every note from a reader on a wider
  audience than the owner's own records and a whole page with it; and the cost of the
  page's test, which walks everything behind the page, other stories' pages included.
  If the test hub shows the cost, a version may record what its run established.
- **Forgetting**, all of it, now including what forgetting an episode a page took in does
  to the page, which §3's test withholds.
- **Whether a page's mark can ever be cleared.** It is cleared only by a decision that
  says when a page no longer carries outside content.
- **Episode notes** (#2723): what they are and who writes them; this decision reads them
  where they exist.
- **How planning sees notes to name them** in a move or a split: the phases' view.
- **Notes beyond the page view's bound** cannot be named from the CLI until a read pages
  them.
- **Searching pages themselves** for lookalikes, rather than episodes: the tidy-up's
  search runs over the memory store, and a search over pages would need an index of its
  own.
- **Supplied windows** whose sensor keeps no record of what it took in by item id: their
  items stay not linkable except as ADR-0301 §1:1 resolves them.
- **Assistant messages** link once acting's effect record exists.
- What ADR-0300 left open and this decision does not decide: facts that become past,
  how lasting knowledge reaches beliefs, small stories cluttering, the numbers, very long
  matters, how a later understanding corrects a wrong link, and planning forgetting to
  tidy.

## Alternatives considered

- **Lines cite episodes as well as notes** (#2773's third option). The citations would
  still be the model's, and whether one is right is what no check can see; the owner
  ruled citations out.
- **Keep the user's notes verbatim and fix the supersession check** (#2774). It keeps a
  class of note the page must carry unchanged, which the owner retired.
- **A note's privacy from the episode it was written during.** It makes *written during*
  something a rule depends on, which the owner ruled it is not.
- **A page's mark from what the latest run took in alone.** A page carrying an earlier
  run's outside content would lose its mark on the next run that took in nothing
  outside, though the content is still on it.
- **The understanding phase reading the conversation store** to resolve transcript
  messages. The reader already brings the window and keeps the bookkeeping, so bringing
  both together reads no further store.
- **A label naming a not-linkable item stays a label defect.** It costs a repair
  completion on the user's critical path (#2776) for a label that cannot be repaired.
- **A merge naming the notes that go**, as a split and a move do. A merge says the two
  stories are one matter, so every note is about the story it joins; one left behind
  would sit on a story nothing reads again.
- **A new operation for `not_applied`.** It would be a second operation recording that no
  story changed; `leave_flag` already is one.
- **The story list's first line through the store.** It widens `StoryStore` and the
  engine surface for a CLI convenience the existing page command already answers.
