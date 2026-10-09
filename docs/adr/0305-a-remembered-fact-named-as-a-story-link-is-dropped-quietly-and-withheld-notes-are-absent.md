# 305. A remembered fact named as a story link is dropped quietly, and withheld notes are absent

- Status: Accepted
- Date: 2026-10-09
- Scope: [M42](https://github.com/leonapivato/ai-assistant/milestone/9), after its focused re-check [#2805](https://github.com/leonapivato/ai-assistant/issues/2805): what becomes of a recalled fact that understanding names among an input's story links, and what understanding is told about a story's notes on a pass that may not be shown them. It decides [#2808](https://github.com/leonapivato/ai-assistant/issues/2808) and [#2807](https://github.com/leonapivato/ai-assistant/issues/2807).
- Dependency: ADR-0304, implemented at `4f7db56c`.
- Authorization: the owner ruled twice on 2026-10-09: on #2808, option (a), a recalled fact named as a story link is dropped quietly; and on #2807, option (b), on a pass that may not be shown a story's notes, understanding is told nothing about them. The dispatcher assigned 0305. Those rulings authorize ratifying this decision once its reviews are green, for as long as it settles only what they leave open.
- **Changes no `core` surface.** No Protocol, no type in `core/types.py`, no wire shape and no stored record changes (§5 below).
- **Partially supersedes** [ADR-0300](0300-a-story-keeps-a-page-of-notes-and-where-its-matter-stands-is-worked-out-from-records.md) — **two scopes.** **§6:8's *or a semantic record*, whole**: a story label naming a recalled semantic record is no label defect; it is dropped and counted, and takes no part in the repair completion (§3 below). **§6:2's *its newest pending entries*, for a pass on which a record placed for the owner alone may not be shown**: the short view renders nothing about its notes (§4 below). Every other clause stands, §6:7 and §6:8's other limbs included, as ADR-0301 and ADR-0303 left them.
- **Partially supersedes** [ADR-0281](0281-recall-runs-before-understanding-and-understanding-reads-what-it-found.md) — **one scope.** **§7:3's rendering of a recalled semantic record, in the addition alone**: it is also rendered marked as not linkable (§3 below). Every other clause stands, §7:4 and §7:5 included.

## Context

**The re-check.** M42's focused re-check (#2805) drove ADR-0304 on a scratch test hub at
`ec2a0839`. It found ADR-0304 §8 working: no understanding pass paid the repair for an
`S` label. It also found two things in understanding's stories section.

- **A recalled fact named as a story link still costs the repair** (#2808). The repair
  completion fired on 4 of 34 first passes (#2808 counted 4 of 31 when it was filed),
  every time for an `M` label naming a recalled *fact*, a semantic record, in
  `story_labels`. On *"Marco asked whether we should rent a drift boat for the fly
  fishing trip with him"* the reply named `["S5", "M1", "M2", "M3"]`. M1 and M2 were
  episodes, and M3 was the fact *"The user is planning a fly fishing trip …"*. A fact is
  not an episode, so it is no story member, and ADR-0300 §6:8 makes naming it a label
  defect: the label takes part in ADR-0276 §6:2's one repair completion, which is a
  second full model call on the user's critical path. All four repairs parsed on the
  second attempt.
- **The model is told that no note is waiting when a note is only withheld** (#2807).
  On a spoken pass, ADR-0303 §3:9 withholds every note, since a record placed for the
  owner alone may not be shown there. The short view then renders the empty list as
  *"missing: no note is waiting to be folded into this story's summary"*, which is false.
  With owner note #57 pending on the camping story (*"Plans changed again: we'll arrive
  at Riverside on Friday evening around 7pm after all."*), a `converse_spoken` turn asked
  when they arrive and was answered from the older plan. Answering without the note is
  right for that audience. Telling the model that no note exists is not.

**Why the model names a fact.** The instruction says `story_labels` names *"the S labels
of the stories, and the labels of the earlier episodes, that it belongs with as one
matter"*, and an earlier episode may be named by its `M` label. Recall renders facts and
episodes in one `M` series (ADR-0281 §7:2), and nothing marks a fact as unable to link.
A fact is often about a matter, as the fly-fishing fact plainly is, so the model's
reading is natural. The place window had the same shape, and ADR-0303 §7:5–§7:6 settled
it: an item that links to no activation is rendered marked not linkable, and a story
label naming one is dropped and counted with no repair.

**How memory treats a record an audience may not be shown.** ADR-0276 §4:9 withholds
every `OWNER`-placed record from understanding on a channel of unbounded audience, and
says what the withholding leaves behind:

> On a channel of unbounded audience the predicate withholds every `OWNER`-placed record
> from the stage, tail record included, and the withholding fires no deflection and sets
> no `withheld` fact, on ADR-0217 §2's own composition with ADR-0210 §1 […]. A withheld
> record reaches no rendering, no label, no referent and no version.

ADR-0281 §4 applies the same predicate to what recall keeps, and its account of the
unbounded pass is that *"the predicate withholds silently every semantic record it does
not place"*. A withheld memory is simply absent: nothing says *none*, and nothing says
*withheld*. Where recall then keeps nothing, the recalled section states that nothing
was recalled (ADR-0281 §7:4), a statement about this pass's recall that stays true,
since recall chooses after the predicate (ADR-0282 §2:5). *"No note is waiting to be
folded into this story's summary"* is a statement about the story, and on such a pass it
can be false.

**The owner's rulings, 2026-10-09.** This decision records them as ruled and settles only
what they leave open.

- **A. A recalled fact named as a story link is dropped quietly** (#2808, option (a)).
  It links nothing, is dropped and counted in `grounding_dropped`, takes no part in the
  repair completion, and calls for none. This mirrors ADR-0303 §7:6 for a place-window
  item that links to no activation, and ADR-0304 §8:2 for an `S` label cited outside
  `story_labels`, which links nothing and is never repaired. The principle across the
  three is one: a label that cannot link is dropped, never repaired.
- **B. Hidden notes are absent** (#2807, option (b)). A story's notes are part of the
  assistant's memory, and are largely invisible to the user. Where an audience may not
  be shown them, they are treated as memory treats its own withheld records: simply
  absent, said to be neither *none* nor *withheld*. The short view is the model's
  internal view, which the user never sees.
- **C. The summary's withheld statement stays** (ADR-0304 §4:2).
- **D. Connecting facts to stories is future work**, for the learning design
  ([#2811](https://github.com/leonapivato/ai-assistant/issues/2811)).

**The code at `4f7db56c`.**
- `_RecalledFact.rendering` renders a fact's label, attribution, last update and text,
  with no mark.
- `_validated` counts a story label as a defect unless it is a story member or names a
  channel item, so an `M` label naming a fact is a defect.
- `_resolved` already drops and counts every story label that is no story member, a fact
  included.
- `_short_view` renders `newest_notes` as the notes `SummaryVisibility.note` let through, or
  as `_NO_NOTES` where none did, whether the story holds none or holds some this
  audience may not be shown.

## Decision

We will render a recalled fact marked as not linkable, drop a story label naming one
quietly and count it, and say in the instruction that a remembered fact is never a story
link; and, on a pass that may not be shown a record placed for the owner alone, render
nothing about a story's notes. Every clause below stands alongside ADR-0300, ADR-0281,
ADR-0276, ADR-0303 and ADR-0304 except where this decision's header names a scope it
replaces.

### 1. Status and scope

> **Normative.** This document remains `Proposed` until the reviews
> `CONTRIBUTING.md` → "Finishing an ADR PR" requires have returned green on one tree
> and the owner's authorization to ratify stands; an assigned number or a green review
> alone does not change its status.

> **Normative.** No implementation implements this decision until this numbered ADR has
> merged `Accepted` under ADR-0015 §5.

### 2. The principle

A label that cannot link is dropped, never repaired. ADR-0303 §7:6 applies it to a
place-window item that links to no activation, ADR-0304 §8:2 to an `S` label cited
outside `story_labels`, and §3 below to a recalled fact. This decision applies it to
nothing else: ADR-0300 §6:8's other limbs stand, and *What stays open* names the one
case the principle reaches that no ruling has yet decided.

### 3. A remembered fact is never a story link

> **Normative.** A recalled semantic record is rendered marked as not linkable, on every
> pass that renders it.

> **Normative.** A story label naming a recalled semantic record links nothing. It is
> dropped and counted in `grounding_dropped`. It is no label defect: it takes no part in
> the repair completion and calls for none.

> **Normative.** The understanding stage's instruction states that a remembered fact is
> never a story link: its `M` label is marked not linkable and links nothing in
> `story_labels`.

The mark is the place window's (ADR-0303 §7:5), on the same key, and it renders on every
pass, as an item's does, so a record's projection does not depend on whether a stories
section rendered beside it. The instruction's sentence sits in the stories paragraph,
which renders only where there are candidate stories, beside the sentence ADR-0303 §7:8
requires for `H` labels.

A fact's label takes no part in the repair: the repair statement does not name it, and
it does not by itself call for the second completion. Where another defect calls for
one, a fact's label the second output still names is dropped and counted like any
other. Its `memory` referent, wherever the label is cited outside `story_labels`, is
unchanged (ADR-0281 §7:5).

### 4. Notes withheld from an audience are absent

> **Normative.** On a pass on which a record placed for the owner alone may not be
> shown, a story's short view renders nothing about its notes: no note, no statement
> that it has none, and no statement that any was withheld.

> **Normative.** The understanding stage's instruction is the same whether or not a
> pass may be shown a story's notes, and states nothing about notes being withheld.

On such a pass ADR-0303 §3:9 shows no note at all, so a short view never renders its
notes part there, whether the story holds pending notes or none: telling the two apart
by whether the part appears would say what the owner ruled is not said. On every other
pass nothing changes. The newest pending notes render as ADR-0300 §6:2 states, and where
none is pending the view says so, which there is true.

The summary keeps its own statement (ADR-0304 §4:2). On such a pass a view still says
that a summary exists and was withheld, says nothing about notes, and shows the latest
episodes the audience admits. ADR-0304 §8:5's sentence that a story's summary and notes
are the assistant's own record stays in the instruction on every pass.

### 5. Delivery

This section is guidance for the lane, not a ruling. The lane merges as it lands, and it
goes live with the phases in one cutover (ADR-0300 §13).

**One lane, in `orchestration`**: `understanding.py` and its tests. It renders the mark
on a recalled fact, passes over a fact's label when it decides whether the repair is
called for, adds the instruction's sentence, and leaves out the short view's notes part
on a pass on which a record placed for the owner alone may not be shown. Whether that
pass is such a pass is already known where the short views are read
(`admits_owner_placed`, which `story_links.py` reads to build `SummaryVisibility`). The
lane may carry it on `ShortView`, in `story_links.py`, or read it in the stage from the
audience the stage already receives. Either stays inside `orchestration`.

- **No Protocol change and no `core` change.** `ProposedActivationUnderstanding`,
  `ActivationUnderstanding` and `UnderstandingReferent` keep their shapes;
  `grounding_dropped` already counts a dropped story label.
- **No `PROTOCOL_VERSION` step.** No shape the wire carries changes, and no command it
  routes.
- **No `schema_version` change and no episode-record format marker.** The processing
  record a pass writes keeps its shape; only how often its repair is made changes.
- **Adversarial review alone** for the lane, since it touches no contract surface.

### 6. Relationship to earlier decisions

| Earlier decision | What changes |
| --- | --- |
| ADR-0300 §6:8 | Its *or a semantic record* limb, as this ADR's header states. A story label resolving to nothing, or naming an episode that records no activation, stays a label defect; a place-window item stays as ADR-0301 and ADR-0303 left it |
| ADR-0300 §6:2 | Its newest pending entries, on a pass that may not be shown a record placed for the owner alone, as this ADR's header states. On every other pass it stands |
| ADR-0300 §6:6, §6:7 | Nothing: a fact was never among what a story label resolves to |
| ADR-0281 §7:3 | The mark, in the addition alone, as this ADR's header states |
| ADR-0281 §7:2, §7:4, §7:5 | Nothing: facts and episodes share the `M` series, the section's statements stand, and a fact's label still resolves to a `memory` referent outside `story_labels` |
| ADR-0276 §4:9 | Nothing: §4 follows its treatment of a withheld record |
| ADR-0276 §6:2, §6:4 | Nothing: the one repair and its recording stand for every defect that remains a defect |
| ADR-0303 §3:9, §7:5–§7:8 | Nothing: a note's privacy stands, and §3 follows the place window's mark and drop |
| ADR-0304 §4:1–§4:4 | Nothing: the summary's privacy and its withheld statement stand |
| ADR-0304 §8 | Nothing: an `S` label still resolves wherever it is cited, and the instruction's three statements stand |

> **Normative.** This numbered draft records its replacements on the status lines and in
> a dated header note of ADR-0300 and ADR-0281, atomically with this ADR under ADR-0070
> and ADR-0082, preserving their ratified bodies. The replacements take effect on this
> ADR's ratification.

## Consequences

**What becomes possible.**
- A pass whose model names a remembered fact as a story link no longer pays a second
  completion for it. That was 4 of 34 first passes in the re-check.
- Fewer facts should be named at all, since the fact is marked and the instruction says
  why.
- On a spoken pass the model is no longer told something false about a story. A note it
  may not see is absent, as a withheld memory is.

**What it costs.**
- A fact the model named because it really is about the matter is dropped, so the link
  the model meant is lost. Today it is lost too, after a repair. #2811 is where a fact
  learns to reach its stories.
- One more mark in the recalled section, on every pass that recalls a fact.
- A summary and its notes are handled differently on a spoken pass: the view says a
  summary was withheld, and says nothing about notes. The owner ruled both.

**What stays open.**
- **Connecting remembered facts to stories** ([#2811](https://github.com/leonapivato/ai-assistant/issues/2811)),
  for the learning design: for example, a fact linking an input to the stories of the
  episodes it was learned from. Until then a fact is never a story link.
- **A story label naming an episode that records no activation**
  ([#2812](https://github.com/leonapivato/ai-assistant/issues/2812)). An episode stored
  before activations recorded themselves is the episode of nothing a story can hold, so
  its label cannot link either. ADR-0300 §6:8 still makes it a defect, and this decision,
  which the rulings scope to facts, leaves it one.
- **What planning is shown of a story's notes** on a pass that may not be shown a record
  placed for the owner alone. ADR-0300 §8's table gives planning a story's pending notes
  and how many are pending. The phases decide planning's views, and §4's rule is the
  precedent for them.
- **Privacy** beyond the owner-only minimum (ADR-0304).

## Alternatives considered

- **Keep the repair for a fact** (#2808's third option). It costs a second full
  completion on roughly one pass in eight, for a label the repair can only tell the
  model to remove.
- **Drop the label quietly with no mark and no instruction.** It removes the cost but
  leaves the model naming facts it is never told it cannot link. The mark and the
  sentence follow the place window's precedent.
- **Mark a fact not linkable only where a stories section renders.** It would make a
  record's projection depend on another section, which the place window's mark does not.
- **Say in the instruction alone that a fact is never a story link.** An unmarked `M`
  label leaves the model to work out from the attribution which labels are facts.
- **Tell the model that notes were withheld** (#2807's first suggestion), as for the
  summary. The owner ruled that hidden notes are absent, as memory's own withheld
  records are.
- **Say that no note of the story is shown**, true of the rendering as the view's other
  *missing* statements are. It still tells the model something about notes on a pass
  that may not be shown them.
- **Render the notes part only where the story holds no note.** Its presence or absence
  would then say whether a note is pending.
- **Leave the notes sentence out of the instruction on such a pass.** The instruction
  would vary with the audience, and ADR-0304 §8:5's statement about a story's notes
  stands on every pass.
- **Drop every label that cannot link, by one rule** (§2's principle as a clause). It
  would also decide the episode that records no activation, which no ruling covers.
