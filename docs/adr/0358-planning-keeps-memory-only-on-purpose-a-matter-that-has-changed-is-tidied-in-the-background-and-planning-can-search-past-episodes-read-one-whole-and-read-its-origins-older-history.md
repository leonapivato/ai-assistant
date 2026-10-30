# 358. Planning keeps memory only on purpose, a matter that has changed is tidied in the background, and planning can search past episodes, read one whole and read its origin's older history

- Status: Proposed
- Date: 2026-10-30
- Scope: what planning keeps and reorganises on its own account, and what it can look up. Planning records a candidate only on purpose (§2) and reorganises a matter only when asked (§3). A matter that has changed is tidied by a scheduled run (§4). A person's preferences have the person block as their home, and their defaults wait (§5). Planning gains three look-ups and a reading of a matter it was not shown (§6–§10). The episode record keeps what came of each call (§11). These are changes 8, 10 and 11 of proposal [#3526](https://github.com/leonapivato/ai-assistant/pull/3526), with change 7's episode look-up. ADR-0356 converts its changes 1, 2, 3, 6, 7's short view and 12, and ADR-0357 its changes 4, 5 and 9.
- Dependency: [ADR-0329](0329-the-observer-is-memorys-one-writer-it-commits-what-an-episode-leaving-the-window-shows-and-planning-records-candidates-for-it.md), [ADR-0346](0346-the-observer-reads-only-the-episode-keeps-then-corrects-and-frames-each-memory-before-placing-it-among-what-is-stored.md), [ADR-0300](0300-a-story-keeps-a-page-of-notes-and-where-its-matter-stands-is-worked-out-from-records.md), [ADR-0302](0302-the-matters-pass-records-what-it-decides-and-a-page-write-refuses-what-its-story-does-not-hold.md), [ADR-0303](0303-a-storys-page-is-free-notes-rewritten-whole-and-the-place-window-links-each-item-to-its-activation.md), [ADR-0307](0307-a-planning-round-is-one-model-response-that-writes-its-own-message-keeps-episode-notes-and-names-what-it-was-shown-by-label.md), [ADR-0338](0338-a-person-sets-their-profile-and-pins-what-aether-always-keeps-in-mind-their-style-is-learned-as-memories-and-each-reaches-the-models-for-that-persons-activations.md) and [ADR-0284](0284-an-episode-is-the-experience-of-processing-its-activation.md), as their status lines leave them; ADR-0356, for the short view and the core of tools, and ADR-0357, for where a tool's rules are worded.
- Authorization: the owner accepted proposal #3526 on 2026-10-30, verbatim: "accept it, convert to the ADRs". On `remember`, the owner's ruling of 2026-10-30, verbatim: "it shouldnt be kept for sure, thats observers choice because it may already be there or other reasons… saying things like saved or ill remember is fine, since it will effectively remember." The owner agreed that the observer side reviews this decision, which is written here. The coordinator assigned 0358 and ratifies it under the owner's delegation once its reviews are green. §4's trigger and its figures, §7's and §9's shapes and §11's record are this lane's choices within the proposal, not owner rulings.
- **Changes `core`, so it is a contract-surface decision. No `Protocol` changes,** so it is not a breaking change under golden rule 5. `core/types.py`'s `EpisodeProcessingRecord` gains one field, the outcomes of its calls (§11:1), and `project_episode` gains the full view behind one keyword (§11:6). The record crosses the wire, so `PROTOCOL_VERSION` advances (§11:8). No `StoryStore`, `MemoryStore` or `AssistantEngine` member changes.
- **Partially supersedes**, in the clauses §13's first table names: ADR-0284, ADR-0300, ADR-0307 and ADR-0329.

## Context

In this document a bare section reference, such as §4:2, is to this decision's own clauses.
Every other ADR's are written with its number, such as ADR-0329 §6:2.

### What the owner ruled

Planning is the system's deliberate thought (proposal #3526, "The idea"). Everything that is
not deliberation moves out of it, and incidental memory is one of those things: what is worth
keeping from a piece of work is gathered by the observer after it ends. The owner ruled that
an explicit request to remember is not kept for sure either: whether to keep it is the
observer's call, which sees duplicates and provenance. Reorganising a matter nobody asked
about goes to background work. On the 2026-10-28 role walk the owner asked whether such work,
moved to the observer, "wouldnt be current"; the answer taken was that planning still does
memory work when it is the task or the work needs it now, and short-term memory bridges the
gap until the background runs.

Style is the person's, as data. The five habits the old instruction set as house style
become default preferences, and the owner said their values wait for the user model and
persistent identity, while the space for them must exist now.

Planning is told its context is only part of what the system knows, and that it can look
up more (ADR-0356). For that to be true it needs look-ups it lacks.

### What is there today

Checked against `main` at `58987ea15`.

- **The observer gathers what is worth keeping without planning.** An episode is due to it
  once it has left the episode window (ADR-0329 §7:1). The scout reads the episode's record
  "with the leaving episode's candidates as hints" (ADR-0329 §9:1), a finding "may come from a
  candidate or from the record alone", and its instruction
  (`orchestration/observer/observer_scout.txt`) tells it to propose "any request to remember and
  any correction, in a person's own words", whether or not a candidate names it. It must
  account for every candidate (ADR-0346 §4:6), which constrains what it does with a
  candidate and does not make it need one.
- **Planning is told to record candidates eagerly.** ADR-0329 §6:2: "be eager for what is
  about the user and their world". §6:1 and §6:3 add what would stay true after the matter
  ends, and anything new a memory's use revealed. §6:5 has the reply never say a fact is saved.
- **The matters pass runs in the background,** as the `matters_pass` row of `jobs_for` in
  `service/scheduler.py`, on `consolidation_interval`, which is unset, so disabled, by
  default. It decides merges, splits, moves, groupings, or leaving the stories as they are
  (ADR-0300 §9:3).
- **It decides only a tidy-up's flags** (ADR-0303 §8:3), and the only caller of
  `StoryTidyUp.run` is planning's tidy-up call (`StoryCalls._tidy` in
  `orchestration/story_calls.py`). The engine's interim tidy-up by rule, from before the phases
  (ADR-0300 §5:12), was deleted at the cutover (ADR-0319). So when planning does not tidy, no
  flag is raised and the matters pass has nothing to decide.
- **Planning's look-ups** are a memory search over semantic records, the full view of a
  story it has been shown, and the follow-up on a held result (`orchestration/lookups.py`,
  ADR-0307 §6:6), with ADR-0349's look-up of a running activation's findings. It cannot
  search episodes, cannot find a matter it was not shown, and cannot read its origin's history
  past its place window.
- **The episode record keeps each round's calls as proposed, and not what came of them.**
  `PlanningRound` holds the calls, and a round is never edited. A call's effect is in its
  effect record (ADR-0306 §5), a result with outside text is never saved (ADR-0308 §6:4), and
  nothing records the result of a call with no effect, such as a look-up. The labels
  planning was shown are on the record (`EpisodeProcessingRecord.labels`), but not which call
  showed them.
- **A person's style already has a home.** ADR-0338 §5 keeps a style preference as a memory
  the observer learns and marks, §6 shows the marked ones in the kept-in-mind slot of the
  person block, and §7:3 gives the whole slot to every planning round. No field, setting or
  dial holds a style (ADR-0338 §5:2).

### Words

A **candidate** is ADR-0329 §3's: what a `remember` call records for the observer. A
**matter** is a story (ADR-0300). The **short view** is the selection of an episode's parts
that short-term memory and recall show, ADR-0356's; the **full view** is §10's. The
**origin** is the place an activation's input came from (ADR-0349 §2:1), and its **place
window** is ADR-0303 §7's. A **scheduled tidy-up** is §4's run, as against planning's
**tidy-up call**.

## Decision

We will have planning record a candidate, and reorganise a matter, only when someone asks or
the work in hand needs it now, and leave the rest to the observer and to a scheduled tidy-up
that runs on any matter that has changed enough or gone quiet. A person's preferences live in
the person block, with their defaults left for later. Planning gains a search over past
episodes that also names the matters they belong to, a reading of its origin's older history,
and a look-up of one episode's full record, filtered part by part as the short view is, for
which the episode record starts keeping what came of each call.

### 1. Status, scope and delivery

> **Normative.** This document remains `Proposed` until the reviews `CONTRIBUTING.md` →
> "Finishing an ADR PR" requires have returned green on one tree and the authorization to
> ratify stands. An assigned number or a green review alone does not change its status.

> **Normative.** No lane implements this decision before it merges `Accepted` (ADR-0015 §5).

> **Normative.** The implementation is the lanes §12 sets out, cut under ADR-0137, and each
> keeps the gate green.

> **Normative.** No lane of this decision that renders an episode's short view, or touches
> `EpisodeProcessingRecord` or `project_episode`, is briefed before ADR-0356 merges
> `Accepted`.

### 2. What planning keeps

> **Normative.** Planning records a candidate only where a person asked for something to be
> kept, or where the work in hand needs something kept now, such as a fact a task it sets for
> later will rely on.

> **Normative.** Planning records no candidate for anything else: what was said, chosen or
> observed in passing, what would stay true after the matter ends, and what using a memory
> revealed about it are the observer's to find in the episode.

A candidate stays what ADR-0329 §3 makes it, a hint and never a memory: recording one keeps
nothing, and the observer decides whether and how it is kept (ADR-0329 §9:1). An explicit
request is kept or not by that same judgment, which weighs what is already held and where the
fact came from. Planning still notes on a matter what the matter needs now, as ADR-0329 §6:1's
note limb has it, and still asks in the moment where a candidate's lookup shows a conflict that
matters to what is being done (ADR-0329 §6:4).

> **Normative.** Nothing tells planning not to say a fact is saved: a reply to a request to
> remember may say it is saved, or that the assistant will remember it.

That is true at the system level, since the observer reads every episode once it leaves the
window.

> **Normative.** No lane of this decision changes the observer, its prompts or what it reads.

The words that carry §2:1–§2:3 to planning sit where ADR-0357 places `remember`'s rules, in
the tool's description or the instruction. This decision rules what they say, not where they
sit, and `remember`'s declaration, lookup and confirmation (ADR-0329 §3–§5) do not change.

### 3. Reorganising a matter

> **Normative.** Planning tidies, moves, merges, splits, groups or unlinks a matter only where
> a person asked for it, or where the work in hand needs it now.

Starting a matter, noting on one and linking to one stay planning's ordinary calls, and every
story call keeps its declaration (ADR-0300 §10:5, ADR-0303 §9:2). Reorganising nobody asked for
is the matters pass's (ADR-0300 §9:3), fed by §4. The words that carry §3:1 sit as §2's do.

### 4. The scheduled tidy-up

> **Normative.** The scheduler's job table gains one row, the scheduled tidy-up, on
> `consolidation_interval`, immediately before the `matters_pass` row in ADR-0083 §7's fixed
> order, and disabled wherever that setting is unset, as the matters pass is.

> **Normative.** A story is due to the scheduled tidy-up where the count ADR-0307 §6:3 names,
> its notes and episodes pending, has reached a threshold, or where that count is at least one
> and the newest of what is pending on it is older than a quiet period.

> **Normative.** The threshold, the quiet period and the most stories one run tidies are
> composition-root constants, initially 5, 24 hours and 10, and a run is also bounded by
> `scheduler_run_budget`, as the matters pass's is.

> **Normative.** A run takes the due stories in the order of their oldest pending note or
> episode, oldest first, except that a story whose tidy-up failed earlier in this process goes
> after every story that has not, so a reply that never parses does not hold the front of the
> queue on every run.

> **Normative.** Each tidy-up a run makes is the operation ADR-0300 §5, ADR-0303 §5 and
> ADR-0304 decide, on consolidation's route as planning's call already uses it (ADR-0285 §5),
> with nothing about what it reads, writes, checks or flags changed.

> **Normative.** A story the tidy-up does not start on, because it is merged, is already being
> tidied (ADR-0300 §5:10) or has had nothing but outside content come to it (ADR-0303 §5:8), is
> passed over and does not count toward the run's bound.

> **Normative.** A scheduled tidy-up is background maintenance, as the matters pass's changes
> are, not an action under ADR-0292 §12:1–§12:2: it starts no activation, records no episode,
> and tells nobody.

> **Normative.** The run reads the stories and what is pending on them through the members
> `StoryStore` already has. Its operation is a public method of the concrete `Engine` taking no
> argument, as `decide_story_flags` is, and `AssistantEngine` gains nothing.

Planning keeps its tidy-up call (ADR-0300 §10:4, ADR-0307 §7), now for a person who asks. A
tidy-up skipped or late still loses nothing: every reader of a summary is given what is pending
on it (ADR-0300 §5).

**Why two arms.** A count alone leaves a matter with one misfiled episode untidied for ever,
since nothing more comes to it; its flag, *looks like another story*, is then never raised,
and the matters pass never moves it. A quiet period alone tidies a busy matter only when it
pauses. The count catches a matter while it is moving, and the quiet period every matter once
it settles. The figures are this lane's guess, set where the matters pass's are, and the owner's
hub tunes them by a code change.

### 5. Where a person's preferences live

> **Normative.** A person's preferences about how things are done reach planning in the person
> block's kept-in-mind slot, as ADR-0338 §5–§7 decide, and no other home is made for them: no
> field, setting or separate block.

> **Normative.** No lane of this decision sets, seeds or ships a default preference.

Five defaults are to come, each a matter of taste: how much to say; whether to confirm what was
done; whether to report what was not done or is not known; whether to say which reading was
taken; and everyday words over technical ones. Their values wait for the user model and
persistent identity (§14). The rules nobody would want reversed, that a preference never
changes what is true, that no outcome is claimed before it is known and that no label is used
outside the work, are the instruction's, ADR-0356's.

### 6. The look-ups, in common

§7 to §10 add to what planning may look up (ADR-0307 §6:6).

> **Normative.** Each look-up this decision adds is a read of the assistant's own records: it
> is declared with that effect, never leaves the hub, never has an unknown outcome, is safe to
> repeat, writes nothing, and runs directly against the store it reads (ADR-0306 §3:3).

> **Normative.** Each runs under the pass's audience, inside the scope planning's other
> look-ups run in (`LookUps.scope`), and a look-up run outside one reads nothing and is not
> done.

> **Normative.** Every record a look-up shows passes `admitted_to_understanding` for the
> pass's audience before it is shown (ADR-0282 §2:7), and a record it refuses, or that the
> store no longer holds, is left out with nothing said about it.

> **Normative.** A look-up shows no raw outside content (ADR-0307 §9:2). Where it shows a
> marked note, digested evidence or an outside episode, the activation has read outside
> content (ADR-0306 §4:5).

> **Normative.** Each thing a look-up shows takes the activation's label for it the first
> time it is shown (ADR-0307 §5:1). A thing planning already holds a label for is named by
> that label and not shown again.

> **Normative.** A result longer than a page, a composition-root constant, comes in pages:
> the call names a page, the first where it names none, and the result says whether there are
> more.

The look-ups are part of the core of tools ADR-0356 offers every round, and their names and
descriptions are ADR-0357's.

### 7. Searching past episodes

> **Normative.** Planning may search past episodes by a query of its own: one memory-store
> search per band for episodic records, as recall's band searches are made (ADR-0281
> §3:2–§3:3), keeping what the recall threshold and §6:3 keep, up to a composition-root
> limit.

> **Normative.** Each episode the search finds is shown as its short view, ADR-0356's, with
> the filters that view applies.

> **Normative.** On a pass of unbounded audience the search asks for no episode, as recall's
> do (ADR-0281 §4:2), and its result says it found none.

A search by when, such as "last week", would need a filter `MemoryStore.search` does not have,
and an eligibility filter binds before the ranking cut (ADR-0128 §1), so it is not added here
(§14).

### 8. A matter planning was not shown

> **Normative.** With each episode an episode search or the episode look-up shows, the result
> names the matters the episode belongs to, read by `StoryStore.stories_of`, each by its `S`
> label and, the first time it is shown, its summary's first line, under ADR-0307 §6:4's
> rules for what an audience may be shown of a story.

> **Normative.** Planning's read of a story's full view (ADR-0307 §6:6) reads any story
> planning holds an `S` label for, a story a look-up's result named included.

So a matter planning was not shown is found by what happened in it, as the tidy-up finds a
story like another (ADR-0303 §5:7), and read whole by the call that reads any other.

### 9. The origin's older history

> **Normative.** Planning may read its origin's older history: the items of the place its
> input came from that are older than the oldest its place window showed, newest page first.

> **Normative.** The older history is read from where the place window came from: the
> medium's history, where its kind's window is read from the medium, and the earlier episodes
> on that channel and place, each by its `E` label and short view, where its window is the
> place's recent episodes (ADR-0323 §10:1).

> **Normative.** Each older item is shown as the place window shows an item: by its author,
> linked to its activation's episode where its records link one, a forward or another item
> whose author the kind does not establish withheld as the window withholds it, and a deleted
> message not at all.

> **Normative.** Where the place's kind has no window, or its history cannot be read through a
> member its store already has, the look-up comes back saying the place's older history
> cannot be read here; where the window already showed all its source holds, it says there is
> nothing older.

### 10. An episode's full record

> **Normative.** Planning may read one episode's full record by its `E` label, wherever it was
> shown: the episode window, recall, a matter's view, an episode search, the older history or
> another look-up.

> **Normative.** The look-up reads only a frozen episode (ADR-0286). For an episode still open
> it says the work is still running, and ADR-0349's look-up of a running activation's findings
> is the one that reads it.

> **Normative.** The full view holds, in the order they happened, every part the short view
> shows and every part it leaves out: each version of understanding the record holds; what
> both recall runs found; each round's notes and its calls with their arguments; what came of
> each call (§11); the digests' evidence; each offer taken in; and how the work ended.

> **Normative.** The full view applies the short view's filters, part by part, and no other:
> it withholds nothing the short view shows, and shows nothing a filter withholds from the
> short view.

> **Normative.** A part placed for someone other than the reader is left out, with nothing
> said about it, as ADR-0307 §6:4 leaves out what an audience may not be shown.

> **Normative.** A record the episode shows by reference, a memory, a story or another
> episode, is read again when the look-up runs, its current version (ADR-0282 §2:6) under §6:3,
> so a memory forgotten since is left out, and nothing of a record is shown from a copy.

> **Normative.** A record shown again says that it is shown as it is now held, not as it was
> then: a memory as planning is shown any memory, a story by its label and its summary's first
> line, and an episode by its label alone.

> **Normative.** Outside content is never shown raw: an outside input is withheld as the short
> view withholds it, beside its understood meaning; a result that carried outside text appears
> only through its digests; and digested evidence and marked notes are shown marked.

> **Normative.** Where the record no longer keeps a part the full view would show, because it
> was recorded before §11:1's field, was elided when it was recorded, or was purged by a later
> retention rule, the look-up says that part is no longer kept. Where the store no longer holds
> the episode, the look-up says its record is no longer kept.

> **Normative.** The full view shows no thinking, raw or summarised, and the look-up reads no
> diagnostic record (ADR-0314 §3:1).

Planning's notes are the thinking a work chose to keep, and they are in the full view. A model's
own thinking is a stream rather than conclusions, unreliable across models, and large, and it is
on no episode record (ADR-0329 §8:4). ADR-0355's summaries stay in the diagnostic record.

### 11. What the record keeps of each call

> **Normative.** `EpisodeProcessingRecord` gains one field, appended as each call's outcome
> becomes known: one entry per call, naming its round and its call by id.

> **Normative.** An entry holds the call's outcome as planning was shown it, done, failed,
> refused, needing the person or unknown, with its reason.

> **Normative.** For a call that was done and whose result carries no outside text, the
> entry holds the result as planning was shown it, in which each record the result showed is
> held by its kind and id, and a story also by the summary version it showed, never by a copy of
> its content.

> **Normative.** For a call whose result carries outside text, the entry holds nothing of
> the result: the digests that answered it are on the record already, and the held result is
> never saved (ADR-0308 §6:4).

> **Normative.** An entry's own text is cut to a composition-root bound, and the cut is
> carried on the entry.

> **Normative.** `project_episode` (ADR-0284 §8:1) gains one keyword, false by default, under
> which the projection also carries the parts §10:3 names, and only the episode look-up sets
> it.

> **Normative.** A record written before the field validates unchanged, and its full view
> says its calls' results were not kept (§10:9).

> **Normative.** `PROTOCOL_VERSION` advances in the lane that adds the field.

> **Normative.** Where ADR-0356 also records a call's outcome on the episode record, the two
> are one entry per call, and the lane that builds second extends the entry the first built.

Keeping a record by id rather than by copy is ADR-0282 §2:3's rule for a stage's part, applied
to what a call showed. It is what lets §10:6 hold: a memory forgotten since the episode cannot
come back through an old result, because the old result never held its words.

### 12. Delivery

The lanes, each after this decision merges `Accepted`, and §1:4's after ADR-0356's:

1. **M1, the record and the projection** (§11): the field, its entries and the projection's
   keyword, with their tests.
2. **M2, the recording and the look-ups**, briefed against merged M1: appending each call's
   entry where acting's outcomes are known (§11:1–§11:5), the look-ups (§6–§10), and their
   composition-root constants.
3. **M3, the scheduled tidy-up** (§4): the engine's operation, the scheduler's row and its
   constants. It depends on nothing else here and may run beside M1.

The behaviour §2 and §3 rule ships in the words ADR-0356's instruction and ADR-0357's
descriptions carry, and has no lane of its own.

> **Normative.** M1 may touch `core/types.py` and its tests, and no other file.

> **Normative.** M2 may touch `orchestration/` outside `orchestration/observer/`,
> `app/composition.py` for the look-ups' constants alone, and their tests.

> **Normative.** M3 may touch `orchestration/engine.py`, `orchestration/story_tidy_up.py`,
> `service/scheduler.py`, `app/composition.py` for §4:3's constants alone, and their tests.

### 13. Relationship to earlier decisions

Superseded in part. Every clause the middle column does not name stands:

| Earlier decision | What it replaces | By |
| --- | --- | --- |
| ADR-0329 | §6:1's *record a candidate for what would still be true and useful if the matter ended or were forgotten*: a candidate is recorded only as §2:1 says, and the story-note limb stands. §6:2, whole. §6:3's *when using a memory reveals anything new about it, record a candidate naming it by its `M` label*: what a memory's use revealed is the observer's to find. §6:5's *and never that it is saved*: a reply may say a fact is saved | §2:1, §2:2, §2:3 |
| ADR-0307 | §6:6, in the addition alone: planning may also search past episodes, read an episode's full record by its `E` label and read its origin's older history, and its read of a story's full view reaches any story it holds a label for. §7:1's first sentence, *made from when the summary was last tidied and how many changes have come since*: planning makes the call only as §3:1 says, and a scheduled run also tidies | §3:1, §4:1, §7:1, §8:2, §9:1, §10:1 |
| ADR-0300 | §10:4's first sentence, *The tidy-up is a call planning chooses*, in the addition alone: a scheduled run also starts it | §4:1, §4:5 |
| ADR-0284 | §8:1's projection, in the addition alone: under one keyword, false by default, it also carries the full view's parts, for the episode look-up alone | §11:6 |

Read through and not superseded:

| Earlier decision | What changes |
| --- | --- |
| ADR-0329 §3, §4, §5, §9:1 | Nothing: a candidate's shape, its lookup and its confirmation stand, and the scout still takes candidates as hints |
| ADR-0346 §4:6 | Nothing: the scout accounts for every candidate, and fewer candidates leave it less to account for |
| ADR-0345, ADR-0348 | Nothing: neither says anything of candidates or of planning |
| ADR-0300 §5, §9:2, §9:3; ADR-0303 §5, §8; ADR-0302 §5 | Nothing: the tidy-up, its flags and the matters pass are unchanged; the flags now also come from scheduled runs |
| ADR-0083 §7 | Nothing: the row is added on its shape, as the observer's and the matters pass's were |
| ADR-0306 §3:3, §4:5 | Nothing: the look-ups are declared and counted under them |
| ADR-0281 §3, §4; ADR-0282 §2 | Nothing: the episode search searches as recall does, and every look-up applies the audience predicate |
| ADR-0308 §6:4 | Nothing: a held result is still never saved |
| ADR-0314 §3:1 | Nothing: no look-up reads the diagnostic record |
| ADR-0338 §5, §6, §7 | Nothing: they are the home §5:1 names |
| ADR-0349 | Nothing: its look-up of a running activation's findings is the one §10:2 points at |

> **Normative.** This numbered draft records its replacements on the status lines and in a
> dated header note of ADR-0284, ADR-0300, ADR-0307 and ADR-0329, atomically with this ADR
> under ADR-0070 and ADR-0082, preserving their ratified bodies. The replacements take effect
> on this ADR's ratification.

### 14. What this decision does not decide

| Not decided here | Where it goes |
| --- | --- |
| The five default preferences' values, and how a default squares with ADR-0338 §5:1–§5:2, under which a style is a learned memory | A later decision, with the user model and persistent identity |
| A search of episodes by when | A later decision: it adds a filter to `MemoryStore.search`, a contract change |
| Whether the observer is shown §11's entries | The observer's own decision; §2:4 changes nothing there |
| Thinking summaries in the full view, clearly marked | A later decision, if planning needs its old reasoning |
| A retention rule that purges an episode's full detail while its short view remains | A later decision; §10:9 says only what the look-up shows once one exists |
| Whether planning is still shown when a matter was last tidied and how many changes came since | ADR-0356, which decides what planning's context holds |
| The look-ups' names and the wording of every rule §2 and §3 give planning | ADR-0357 |

> **Normative.** Each item the table names takes a decision of its own before any lane builds
> it.

## Consequences

**Easier.** Planning's instruction loses its rules on what to record and when to tidy, and a
round no longer spends calls on candidates and tidy-ups nobody asked for. Matters are tidied,
and so reorganised, whether or not planning thinks of it. A later stimulus can find out what an
earlier work did, an email sent or a booking refused, by reading that work whole, and can find a
work it was not shown by searching for it.

**Harder.** The scheduled tidy-up spends a completion on consolidation's route for every matter
that changes enough or goes quiet, where today a matter nobody tidies costs nothing. The episode
record grows by an entry per call. A memory or story shown again in the full view is shown as it
is now, so the view is not a faithful replay of what planning saw then. The person's own words
are now kept only through the observer, so a fact the person states is in long-term memory only
once its episode has left the window, about one activation later, and short-term memory carries
it until then.

**Follow-on.** M1, then M2; M3 beside them (§12). The words §2 and §3 rule ship with ADR-0356's
instruction and ADR-0357's descriptions. The observer front confirms that the scout does not
depend on candidates for what it finds.

**Revisit when** the observer misses what a person asked to keep more often than it did with
planning's candidates, a scheduled tidy-up's cost shows in consolidation's spend, or planning
reaches for a look-up §14 leaves out.

## Alternatives considered

- **Keep an explicit "remember this" for sure.** Declined by the owner: whether to keep it is
  the observer's call, which sees duplicates and provenance.
- **Keep planning recording candidates eagerly, as hints.** Rejected: the observer reads the
  whole episode anyway and already proposes requests and corrections from the record, so eager
  candidates cost planning a call each and tell the observer little it does not see.
- **Have the observer tidy matters.** Rejected: the observer is memory's writer (ADR-0329 §2)
  and runs once per episode leaving the window; a tidy-up is a matter's, on its own count, and
  the operation already exists on consolidation's route beside the matters pass.
- **Tidy inside the matters pass's own run.** Rejected: the pass decides flags, and folding the
  tidy-up into it would change ADR-0300 §9:3's and ADR-0302 §5's operation. A row of its own
  keeps both operations as they are, and the fixed order runs the tidy-up first.
- **Trigger on the count alone, or on the quiet period alone.** Rejected for §4's reasons.
- **A search over matters' summaries.** Rejected: a summary is not a memory record, so it would
  need a `StoryStore` search member, a contract change. Finding a matter through the episodes in
  it is how the tidy-up already finds a story like another.
- **Fold the episode search into the memory search.** Rejected: the two return different
  things, memories and short views with their matters, and recall's split between episodic and
  semantic records is the same split.
- **Record each result as planning was shown it, records copied.** Rejected: an old result would
  bring a forgotten memory back, which the proposal's filters forbid.
- **Show whole episodes in short-term memory and recall.** Rejected by the proposal: it is
  large, brings back forgotten memories through old results, and shows stale results as if
  current. The full view is a look-up, and §10:6 and §10:7 meet the last two.
