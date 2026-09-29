# 282. Phases read and write the working episode, and recall searches past the windows

- Status: Accepted
- Date: 2026-09-29
- Scope: [M39](https://github.com/leonapivato/ai-assistant/milestone/6), [#2607](https://github.com/leonapivato/ai-assistant/issues/2607).
- Dependency: ADR-0281 and ADR-0280, both implemented at `d974519b`; ADR-0276.
- Authorization: the owner accepted proposal #2606 on 2026-09-29, choosing its option A (the working episode kept in memory, the saved episode unchanged), and directed its conversion into this ADR and the start of the work. Option B, saving each phase's reads with the episode, is [#2608](https://github.com/leonapivato/ai-assistant/issues/2608). The dispatcher assigned the next available number, 0282. That authorizes drafting and numbering, not ratification or implementation.
- **Partially supersedes** [ADR-0276](0276-an-activation-is-understood-before-it-is-associated-and-the-understanding-is-retained-with-its-episode.md) — **one scope.** **§4:1's wiring**, in its *wires into the stage* and *it receives the selector's records* parts alone: the selector runs in §3's windows stage, which records the window's ids, and the understanding stage receives the window's records as §5 below fetches them. The selector itself, its walls (§4:2–§4:4), the disclosure predicate (§4:9–§4:13) and the rendering stand. Every other clause stands.
- **Partially supersedes** [ADR-0280](0280-an-activation-controller-runs-the-stages-by-rules-and-records-every-choice-with-the-episode.md) — **two scopes.** **§3:5's working set and §4:1–§4:3's enums and table, in the additions alone**: the window decision, the stage `windows`, the rule `windows_unassembled` and its row. **§3:7's list of wrapped stages, for understanding alone**: understanding runs over the working episode as §5 below states, with the same effects. Every other clause stands.
- **Partially supersedes** [ADR-0281](0281-recall-runs-before-understanding-and-understanding-reads-what-it-found.md) — **four scopes.** **§3:2's `limit`**: each band's search asks for §4's search limit instead of `RECALL_ITEM_LIMIT`. **§3:3's filling rule, in the addition alone**: a record the windows already hold is not kept. **§7:1's first sentence, in its *receives the records recall kept* part alone**: the understanding stage receives them as §5 below fetches them. **§6:4's last sentence**, *"The records the search returned are held on `ActivationState` for the pass for the understanding stage to render"*: recall's part holds §4:3 below's ids and scores and no record; the recall result held on `ActivationState` and written once at capture, and every other part of §6:4, stand. Every other clause stands, `RECALL_ITEM_LIMIT` as the number kept included.

## Context

ADR-0281 put recall ahead of understanding. On the redeployed hub (`d974519b`),
"My dentist is Dr Rao." followed, in a new conversation, by "Remind me, who is my
dentist?" recorded `Recall: found` with the Dr Rao episode, yet recall added nothing:
both episodes it found were already in the episode window, rendered as `P1` and
`P2`. Three things in the build cause that.

- **The episode window is fetched inside understanding, after recall.** ADR-0276
  §4:1 wires the episode selector into the understanding stage, which calls it while
  building its prompt. When recall runs the window does not exist yet, so recall
  cannot search past it; overlap is found only afterwards, when understanding drops
  an `M` record already shown as `P` (ADR-0281 §7:2).
- **Recall's slots fill before the overlap is known.** Each band's search asks for
  `RECALL_ITEM_LIMIT` (3) results (ADR-0281 §3:2) and filters afterwards. When the
  window's episodes are the closest matches, they take the slots, and a further,
  useful match is never returned.
- **Recall's result exists twice.** The working set holds the full records recall
  kept, for the pass only, beside `ActivationRecall`, the summary that is saved; the
  engine passes the full records to understanding as an argument. What understanding
  acts on is not what the episode records.

The owner's direction on the wiki's
[Episodes](https://github.com/leonapivato/ai-assistant/wiki/Episodes) page (read
2026-09-29, direction and not ratified) is that the episode is "a log, read through
current views": each phase's result is added in the order it arrived and nothing is
overwritten. The [Controller](https://github.com/leonapivato/ai-assistant/wiki/Controller)
page says the controller reads only what the phases added to the episode. In
discussing #2606 the owner set the rule this decision states: phases know nothing of
each other or of the workflow, they are functions of the working set, and the working
set is then also an auditable log of what happened. Recall records memory ids, and a
later phase fetches what it needs.

Three ways for phases to get their inputs were weighed. **Arguments**, as today: the
engine reads the working set and passes each stage its inputs. It keeps stages
testable on their own, but every new phase needs engine wiring, a stage can fetch out
of sight (the window), and a stage run again on new cues (#2591) has no way to see
what is new. **Full records on the working set**: nothing is fetched twice, but the
working set then carries a copy of memory that is not what the episode saves, which
is the double record above. **Ids, and fetch what you need**: one record of what
happened, at the cost of one local `MemoryStore.get_many`, and a phase sees a
memory's current version rather than the one found. The third is decided.

Four ways for recall to search past the window were weighed. **Excluding ids in the
query** is exact, but `MemoryStore.search` would gain a parameter, a Protocol change
with its own ADR first (`CLAUDE.md`, golden rule 5). **Searching only episodes older
than the window** is approximate, since the window is a count, not a span of time.
**Searching semantic records only** would find nothing until consolidation produces
facts. **Asking for more, then dropping** needs no contract change, and the window
holds at most `UNDERSTANDING_EPISODE_LIMIT` (10) episodes, so the extra rows are few.
The last is decided.

Window assembly could be part of preparing the pass rather than a stage. As a stage
it is recorded in the stage record like any other step, a failure takes the fixed
default through the controller as a failed window fetch inside understanding does
today, and the rule reading its decision is one more row. The cost is one member on
each of two enums the processing record carries, which advances `PROTOCOL_VERSION`
(ADR-0280 §7:4) but changes neither `schema_version` nor the format marker, as
ADR-0281 §8:1's first step did for `recall`.

## Decision

### 1. Scope

> **Normative.** §2's rule governs the windows stage, recall and understanding as
> this decision changes them, and every stage added after it. The legacy stages
> ADR-0280 §3:7 wraps other than understanding (beginning the conversation, routing,
> the event summary, association, disambiguation, reconciliation, the turn loop,
> driving and composing) are not rewritten to it; they keep their inputs until they
> retire.

> **Normative.** Nothing this decision adds to the working episode is saved with
> the episode. `EpisodeProcessingRecord` and `ActivationRecall` keep their fields,
> `schema_version` stays `Literal[4]`, and `EPISODE_RECORD_FORMAT` stays **4**.

### 2. Phases are functions of the working episode

The **working episode** is ADR-0280 §3:5's working set, as ADR-0281 extended it and
M39 implemented it (`_ActivationPass`): everything the pass holds before capture.

> **Normative.** A stage reads its inputs from the working episode and writes its
> result into its own part of it. It names no other stage and reads no fact about
> which stages have run or will run; which stage runs is the controller's.

> **Normative.** Each part of the working episode has exactly one stage that writes
> it. Any stage may read it. A stage never writes another stage's part.

> **Normative.** Where a stage's result concerns records of the `MemoryStore`, its
> part holds their stored `MemoryBase.id` values exactly as stored, with the fields
> this decision names beside them, and never a copy of the records. Content that
> arrived with the activation, and the channel window as §3 holds it, are not
> `MemoryStore` records and are held as they are.

> **Normative.** A stage that needs the contents of records another stage chose
> fetches them with `MemoryStore.get_many`, over ids the working episode holds, and
> fetches no other record. `MemoryStore` gains no member and no signature.

> **Normative.** A stage whose result is a choice of records makes the reads that
> choose them, and only those: the windows stage its selector's reads (§3), recall
> its band searches (§4). The ids such a stage writes are the records it chose, after
> the audience predicate below.

> **Normative.** A fetch returns each record's current version. An id with no record
> is not an error: the stage goes on without it.

> **Normative.** A stage that fetches writes into its own part the ids it fetched and
> the ids that returned no record, before it returns.

> **Normative.** An id enters the working episode only after
> `admitted_to_understanding` has admitted its record for the pass's audience, and a
> stage applies the same predicate again to what it fetches. A record the second
> application refuses is treated as an id with no record.

### 3. The windows stage

> **Normative.** `ControllerStage` gains the member `windows` and `ControllerRule`
> the member `windows_unassembled`, on ADR-0280 §4:1–§4:2's *added to and never
> renamed* rule. The working episode gains the **window decision**: present once the
> windows stage has made it.

> **Normative.** ADR-0280 §4:3's table gains one row immediately before
> `not_recalled`: `windows_unassembled` answers when *the understanding stage is
> wired and there is no window decision*, and makes `windows` due. No other row's
> order changes; the rows after it are renumbered by one.

> **Normative.** The windows stage writes the window decision: the channel window
> exactly as ADR-0276 §3:1 defines it for the pass, and the episode window as the
> ids of the records ADR-0276 §4's selector returns, in the selector's order, after
> ADR-0276 §4:9's predicate. On a pass that takes no episode window (ADR-0276 §4:13)
> the decision records that there is none, and the selector is not called.

> **Normative.** The selector runs in the windows stage unchanged: the same bound,
> order, reads and walls as ADR-0276 §4:2–§4:4 set. The composition root wires it
> there, and the understanding stage holds no selector.

> **Normative.** The windows stage is not failure-tolerant. A failure or a timeout in
> it takes ADR-0280 §5:2's fixed default.

### 4. Recall searches past the windows

> **Normative.** Recall reads the window decision's episode ids and the stored ids of
> the channel window's items, and keeps no record whose id is among them.

> **Normative.** Each of recall's band searches asks for a **search limit** of
> `RECALL_ITEM_LIMIT` plus the number of ids recall reads under the clause above,
> and recall still keeps at most `RECALL_ITEM_LIMIT` records in all, filling them in
> band order under ADR-0281 §3:3.

> **Normative.** Recall's part of the working episode is its `ActivationRecall` and,
> for each kept item, its search score, and nothing else. It holds no record.

### 5. Understanding reads what the working episode holds

> **Normative.** Before the understanding stage renders, the understanding phase
> fetches the window decision's episode ids and recall's kept ids in one
> `MemoryStore.get_many` under §2's rules, and hands `UnderstandingStage` the
> fetched records: the episode window's in the window's order, recall's in recall's
> order. `UnderstandingStage` itself reads no store.

> **Normative.** A window episode or a recalled record whose id returned no record is
> not rendered and takes no label; the rest keep their order. The rendering,
> labels, attribution and resolution of ADR-0276 §3, §4 and ADR-0281 §7 are
> otherwise unchanged, ADR-0281 §7:2's rule included.

### 6. The wire

> **Normative.** The two enum members of §3 change the shape of
> `EpisodicMemory.processing_record`, so the change adding them advances
> `PROTOCOL_VERSION` on ADR-0280 §7:4's rule. It adds no validator, changes no
> `schema_version` and does not advance the format marker, so a data directory
> written at protocol 63 opens unchanged.

### 7. Delivery

> **Normative.** Land this ADR ratified before any implementation lane. Then the
> implementation ships as separate PRs in this order:
>
> 1. **`core` with `wire`, additive only**: §3's two enum members and the
>    `PROTOCOL_VERSION` advance, with the stage wired nowhere.
> 2. **`orchestration`, the windows stage and understanding**: §3's stage, rule and
>    row, and §5's fetch, with §2's record of what was fetched.
> 3. **`orchestration`, recall**: §4, and recall's part reduced to §4's.
>
> Step 2 depends on step 1, and step 3 on step 2.

> **Normative.** Step 2's tests assert, for each activation kind, that a `windows`
> entry appears immediately before `recall` wherever recall is due, and that a
> window episode forgotten between the windows stage and understanding is not
> rendered and is recorded as returning no record. Step 3's tests assert that a
> record the episode window holds is not kept by recall and does not take a slot,
> and that a further match below it in the same band is kept in its place.

## Consequences

- Recall's three slots go to memories understanding does not already see, which is
  what the M39 probe showed was missing.
- The working episode records, for the pass, which windows were assembled, what
  recall kept and scored, and what understanding fetched and found missing. It is
  lost at the end of the pass until #2608 saves it; until then inspection shows the
  stage record, recall's saved items and understanding's citations.
- A redeploy of this change is a protocol bump without a fresh data directory.
- Recall running again on understanding's cues (#2591) builds on §2: a rerun reads
  what the working episode holds when it runs.
- `RECALL_ITEM_LIMIT` is worth revisiting once the window no longer takes its slots,
  together with the threshold under #2601.
- How the planner reads understanding and recall is the planner design's question.
  It follows §2's rule as a new stage.

| Superseded clause | What changes |
| --- | --- |
| ADR-0276 §4:1 | The selector runs in the windows stage, which records the window's ids; understanding receives the records §5 fetches. |
| ADR-0280 §3:5, §4:1–§4:3 | The window decision, `windows`, `windows_unassembled` and its row are added. |
| ADR-0280 §3:7 | Understanding runs over the working episode, with the same effects. |
| ADR-0281 §3:2 | Each band search asks for the search limit. |
| ADR-0281 §3:3 | A record the windows hold is not kept. |
| ADR-0281 §6:4 | Recall's part holds ids and scores, not the records the search returned. |
| ADR-0281 §7:1 | Understanding receives recall's records as §5 fetches them. |
