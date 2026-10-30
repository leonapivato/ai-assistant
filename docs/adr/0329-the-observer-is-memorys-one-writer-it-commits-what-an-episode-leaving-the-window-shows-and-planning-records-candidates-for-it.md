# 329. The observer is memory's one writer: it commits what an episode leaving the window shows, and planning records candidates for it

- Status: Partially superseded by ADR-0333 (§15:1, in the addition alone: the observer also holds a `DiagnosticSink` or `None`) and ADR-0336 (§13:1, in the addition alone: a `policy_ask` is raised on each stored memory the ingest result names as contradicted) and ADR-0338 (§8:1, §9:1, §9:3, §9:4, §9:6, §12:4 and §15:1, in the additions alone, and §11:1 for a finding that only restates a profile field: the person model's fields, suggestions, style marks and pin supports) and ADR-0345 (§9:7, in the addition alone: an `observer_inference` support is also added as `against` where a placed write records a dispute; §13:2, for a `recheck` a placed write raises) and ADR-0346 (§8:1, §8:2, §8:3 and §8:6; §9:3 and §9:4; §9:7, for the observer's own writes; §10:1 and §10:2, in their reach and in what a round's message may support; §11:1, in its "always kept"; §11:4, §11:5 and §11:6; §12:3 and §12:4; §14, until a decision on how recall ranks; §9:1, in the additions, in its one claim per finding, and in a candidate giving no finding unaccounted) and ADR-0350 (§13:6, in the addition alone: an activation the Task Scheduler starts writes its messages into places on its place list) and ADR-0357 (§6:1–§6:5 and §6:8, each in where the line is said alone: the descriptions of `remember`, of the story calls and of `note_reliance`, not planning's instruction) and ADR-0358 (§6:1's and §6:3's candidate limbs, §6:2 whole, and §6:5's *and never that it is saved*: planning records a candidate only on purpose)
- Date: 2026-10-18
- Scope: who writes memories once the observer exists, and when. Planning's side — `remember` repurposed to record a candidate, the lookup that answers it, asking the user to confirm a wording, noting reliance, planning's instruction and what it is shown — and the observer's side: its trigger, what it reads, its two steps, its keep rules and evidence bar, its writes, open questions, the track record, where it lives, its limits and records, the catch-up, and what the user sees. Batch [#3148](https://github.com/leonapivato/ai-assistant/issues/3148), lane L-β, for milestone 3, "Learning v1: the observer" (acceptance [#3154](https://github.com/leonapivato/ai-assistant/issues/3154)).
- Dependency: ADR-0328, which this decision builds on and changes only where §20 names a clause; ADR-0276, ADR-0284, ADR-0292, ADR-0306, ADR-0307, ADR-0309, ADR-0321 and ADR-0326, as their status lines leave them.
- Authorization: the owner ruled this design in the learning walk of 2026-10-17 and 2026-10-18 ("Observer walk", "Planner's side", "Keeping memories right") and approved it on 2026-10-18. This decision writes those rulings down and settles only what they leave open, each such point named where it is settled. The dispatcher assigned 0329. The owner reads it before it is ratified (§1:1).
- **Contract-surface decision.** It changes `core/protocols.py` (`PlanStore` gains the observation record's members; `MemoryWriter` gains a track-record member and a proposal that may retire; `AssistantEngine` gains a read of pending candidates) and `core/types.py` (the observation record's types, the writer `observer`, `EpisodeProjection`'s candidates). It is a breaking change under golden rule 5. The episode record gains no field (§3:3).
- **Partially supersedes**, in the clauses §20's first table names: ADR-0050, ADR-0284, ADR-0285, ADR-0292, ADR-0294, ADR-0306, ADR-0309, ADR-0319, ADR-0321 and ADR-0328.
- Partially superseded: 2026-10-20 by ADR-0333 — §15:1, in the addition alone: the observer also holds by injection a `DiagnosticSink`, or `None` where `diagnostic_record` is false, and writes ADR-0333 §2's entries through it (ADR-0333 §2:7). Every other clause stands. This replacement takes effect on ratification of ADR-0333. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; the ratified body below is preserved.
- Partially superseded: 2026-10-21 by ADR-0336 — §13:1, in the addition alone: a `policy_ask` is raised on each stored memory the ingest result names as an assertion the proposal contradicts, and on no other (ADR-0336 §7:1, §7:4). Every other part stands. This replacement takes effect on ratification of ADR-0336. This reciprocal header record lands with ADR-0336 under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-21 by ADR-0338 — §8:1 and §9:3, in the additions alone: the observer also reads the five profile fields of the leaving episode's person, and both the scout and the commit step are given them (ADR-0338 §9:1). §9:1 and §9:4, in the additions alone: the scout may propose a field suggestion, and the commit step may record a style mark and propose a pin suggestion (ADR-0338 §9:2, §9:4, §9:5). §9:6, in the addition alone: a support the observer adds may point at a pin, added by a pass at the start of each run (ADR-0338 §9:6). §12:4, in the addition alone: before a write that retires a memory, the observer first adds the `pinned` support of every pin on it that lacks one, and reads it again (ADR-0338 §9:9, §9:10). §11:1, for a finding that only restates a profile field: it is not kept as a memory (ADR-0338 §9:3). §15:1, in the addition alone: the observer also holds the person-model store (ADR-0338 §9:8). Every other clause stands. This replacement takes effect on ratification of ADR-0338. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-23 by ADR-0345 — §9:7, in the addition alone: an `observer_inference` support is also added, as `against` and backing nothing, where a placed proposal's write records a dispute (ADR-0345 §3:8). §13:2, for a `recheck` a placed proposal's write raises: the question rests on the memory's own backing supports and adds none, so a memory worth checking is not shown as disputed (ADR-0345 §5:9). Every other clause stands. This replacement takes effect on ratification of ADR-0345. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-21 by ADR-0346 — §8:1, §8:2, §8:3 and §8:6: the observer reads the leaving episode's record and what it points at, and nothing else, renders its understanding, shows no later episode, and makes one scout call per episode (ADR-0346 §2–§4). §9:3 and §9:4: the commit step is a framing call given only the finding's parts and annotations, then code's retrieval and a placement call per memory, written as a placed proposal (ADR-0346 §5, §6; ADR-0345 §4, §5). §9:7, for the observer's own writes: it adds no observer's inference. §10:1 and §10:2, in their reach and in what a round's message may support: a round's message is evidence of what the assistant said, where and when, and never that it is true, about anything and not only the user; what it claims is kept only where a person asked to keep it, agreed or confirmed; any memory may cite it, and it backs a record of the saying (ADR-0346 §7:7–§7:9; ADR-0345 §2:4). §11:1, in its "always kept": a request or a correction is kept unless the person said not to keep it (ADR-0346 §7:3). §11:4, §11:5 and §11:6: an occasion is kept as a memory marked `occasion`, and the observer creates no inference (ADR-0346 §7). §12:3 and §12:4, for a framed memory: a restatement, a question and a retirement are each written by the placed proposal's write, following the placement and the holder rule, not by the operation member or a separate retiring proposal (ADR-0345 §3, §5; ADR-0346 §6). §14, until a decision on how recall ranks: the observer records no track-record entry until that decision decides what counts as a memory serving well and how it is judged, and planning still notes reliance (ADR-0346 §8). §9:1, in the additions alone: a finding carries the scout's annotations (ADR-0346 §4). §9:1, in its one claim per finding: a finding is one thing worth keeping and may hold several claims that share its annotations, which framing turns into single claims (ADR-0346 §4:2, §5:3). §9:1, in a candidate giving no finding unaccounted: the scout accounts for every candidate, naming it by a finding or declining it with a reason (ADR-0346 §4:6). Every other clause stands. This replacement takes effect on ratification of ADR-0346. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-25 by ADR-0350 — §13:6, in the addition alone: an activation the Task Scheduler starts writes its messages into places on its place list, and no other background work messages the user (ADR-0350 §6:7). Every other clause stands. This replacement takes effect on ratification of ADR-0350. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-30 by ADR-0357 — §6:1–§6:5 and §6:8, each in where the line is said alone: what §6:1–§6:5 have planning's instruction say is said in `remember`'s description, and §6:1's story-note limb in the story calls' too, and what §6:8 has it say is said in `note_reliance`'s (ADR-0357 §7:1–§7:3). What each line says is unchanged by ADR-0357. Every other clause stands as its other records leave it. This replacement takes effect on ratification of ADR-0357. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-30 by ADR-0358 — §6:1's *record a candidate for what would still be true and useful if the matter ended or were forgotten*, §6:2 whole, and §6:3's *when using a memory reveals anything new about it, record a candidate naming it by its `M` label*: planning records a candidate only where a person asked for something to be kept or the work in hand needs something kept now, and records none for anything else (ADR-0358 §2:1, §2:2). §6:1's story-note limb stands. §6:5's *and never that it is saved*: a reply to a request to remember may say it is saved (ADR-0358 §2:3). Every other clause stands. This replacement takes effect on ratification of ADR-0358. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.

## Context

### What the owner ruled

ADR-0328 decided what a memory is and left who writes one to this decision (ADR-0328
§17). The walk settled the rest. On who writes: planning never writes memories; one
observer does, and a later store-maintenance pass maintains them. On planning's side:
`remember` records a **candidate** — one self-contained fact, what it rests on, a short
why, and optionally a memory it was shown with a note — of one kind with no flags; code
looks up similar memories when one is recorded and returns them in the same round;
planning asks the user in the moment only for a real conflict that matters; planning may
also write a story note, each for its own purpose; when using a memory reveals anything
new about it, planning records a candidate pointing at it, and otherwise nothing; and
planning notes which memories it relied on. On the observer: it runs when an episode
**leaves the episode window**, reads around that episode with hindsight, proposes in a
broad **scout** step and commits in a narrow **commit** step that sees only what a
finding rests on, keeps by explicit rules with an evidence bar for inferences, is a
background stage rather than an activation, and works within limits that make it
idempotent, ordered, budgeted and never lossy. On keeping memories right: open questions
live on the memory and reach planning when the memory comes up; the observer records a
track record of reliance with hindsight; and nothing messages the user in the background.
On sequencing: planning's side and the observer ship together.

### What is there today

Surveyed at `cbb0f160`.

- **`remember`** (`orchestration/remembering.py`, `REMEMBER`) is planning's one route to
  memory (ADR-0306 §3:2, ADR-0309 §6:5). Authorizing hands its proposal to
  `MemoryPolicy`; an ask comes back *needs you*, and a yes writes it under a
  `UserConfirmation` built from the approval (ADR-0321 §5:1–§5:2). ADR-0328 §13 has it
  write the new memory record until this decision is built.
- **Nothing learns from episodes in the background.** The old observer retired with no
  successor (ADR-0285 §1:2), and the consolidation stage retires under ADR-0328 §14:2.
- **An `ASK_USER` ruling on the write stage** is logged and dropped
  (`orchestration/writes.py`, `DEFERRED_EVENT`, ADR-0319 §5:1).
- **The episode window** is the `UNDERSTANDING_EPISODE_LIMIT` (10) most recent episodes
  across every channel, by occurrence (ADR-0276 §4:1–§4:3; `RecentEpisodes` in
  `app/composition.py`). Every activation adds one episode, a timer's or a push's
  included, and nothing leaves the window except by newer episodes arriving.
- **A round records its proposed calls with their arguments** (`PlanningRound.calls`,
  each a `ProposedCall`), and the episode records the labels planning was shown with the
  ids they name (`EpisodeProcessingRecord.labels`, ADR-0307 §5:7). An effect record
  (`ActivationEffect`, ADR-0306 §5:3) is written for every call to a capability that is
  not safe to repeat, `remember` among them.
- **The plan store** (`PlanStore`) holds an activation's stop record and its effect
  records, and carries ADR-0004 §6's export and clear.
- **Episodes reach a model only through `project_episode`** (ADR-0284 §8:1, §8:3), with
  outside input admitted for understanding's two renderings alone (ADR-0284 §8:5).
- **Writing a memory is an inside action** that planning chooses and authorizing checks
  (ADR-0292 §12:1–§12:2). ADR-0300 carved the hub's own story bookkeeping out of that
  rule; nothing carves out a background memory writer.
- **`learning/`** holds no module since `RuleBasedFeedbackProcessor` retired under
  ADR-0328 §14:1, and keeps its import-linter contracts.

### Words

A **candidate** is §3's. A **finding** is one thing the scout proposes about one
episode (§9). The **leaving episode** is the episode a run of the observer is about. An
episode is **processed** when §16's record marks it so. **Standing**, **support**,
**origin**, **operation**, **open question** and **track record** are ADR-0328's.

## Decision

We will make the observer memory's one writer. Planning's `remember` records a candidate
in the round, which the episode already keeps, and code answers it with similar
memories. When an episode leaves the episode window, a background stage reads it with
what came after, proposes findings, commits each through the memory write path from
only the parts it rests on, and records what it did beside the episode. Planning's side
and the observer go live in one deploy, and until then ADR-0328 §13's interim holds.

### 1. Status, scope and delivery

> **Normative.** This document remains `Proposed` until the reviews `CONTRIBUTING.md` →
> "Finishing an ADR PR" requires have returned green on one tree and the owner, having
> read it, has authorized its ratification. An assigned number or a green review alone
> does not change its status.

> **Normative.** No lane implements against this decision before it merges `Accepted`
> (golden rule 5, ADR-0015 §5), and none before the lanes that implement ADR-0328 have
> merged.

> **Normative.** The implementation is cut into lanes by the dispatcher under ADR-0137, as
> §19 sets out, and each lane keeps the gate green.

### 2. One writer

> **Normative.** Once this decision is implemented, the observer (§§7–18) is the one
> writer of memories beside ADR-0328 §16's upgrade. Planning writes no memory, by
> `remember` or by any other route.

> **Normative.** ADR-0328 §5:9's closed set of writers gains `observer`. Every operation,
> support, track-record entry and open question the observer writes names it.

> **Normative.** The writer `remember` writes nothing once this decision is implemented.
> What it wrote stays as written, and ADR-0328 §13 governs it until then.

> **Normative.** Store maintenance, the later successor of consolidation (ADR-0328 §14:2),
> writes memories only under a decision of its own, which names its writer.

### 3. Candidates

A candidate is what planning records for the observer: a hint about what is worth
keeping, never a memory and never a support.

> **Normative.** `remember` records a candidate. Planning writes, for each call: one fact,
> self-contained, in its own words; what it rests on, one or more of the activation's
> input, a message of an earlier exchange named by that episode's `E` label and whether
> it is the user's message or the assistant's, and a result named by its `R` label; a
> short why; and, optionally, one memory it was shown, named by its `M` label, with a note
> in words on how the fact bears on it. Exact argument names are the implementing lane's.

> **Normative.** A candidate has one kind. No argument, mark or field classifies it as a
> request, a correction, an observation or anything else: the observer reads that from
> the parts it rests on (§9).

> **Normative.** A candidate is the `remember` call as its round records it
> (`PlanningRound.calls`), read with the episode's labels (ADR-0307 §5:7) and joined to
> its effect record (ADR-0306 §5:3). A `remember` that runs under an approval is proposed
> by its approved-action label (ADR-0321 §4:2), so its candidate is the asked call the
> effect record's question part names, as the asking round records it (ADR-0321 §2:8),
> read with the asking episode's labels. Either way it is a candidate of the episode whose
> effect record shows it done, and exactly where it does. No episode field, record or
> store is added for candidates, and `EpisodeProcessingRecord` keeps its schema.

> **Normative.** The hub fills `remember`'s episode and its rests-on-outside-content as
> today (`system_supplied`, ADR-0254 §3), and a call naming a label planning was not shown
> is refused as ADR-0307 §5:3 refuses one.

> **Normative.** A single observation — a choice the user made, a reaction, a detail of
> their world — is recorded as a candidate like any other.

> **Normative.** No support the observer adds points at a candidate. A support points at a
> part a finding rests on (§9:6). ADR-0328's remember-call part and the origins
> `remembered` and `remembered_over_outside` stay on the supports the interim wrote
> (ADR-0328 §13:2) and are written by no one after it.

> **Normative.** `remember`'s effect is the assistant's own records, it is not safe to
> repeat, it never leaves the hub, its outcome is never unknown, and its result carries no
> outside text (§4:3). ADR-0306 §5's backstop refuses the same candidate twice in a
> matter, as it refuses any repeated call to such a capability.

### 4. The lookup

> **Normative.** When `remember` records a candidate, code searches the memory store for
> memories similar to its fact, by relevance alone (ADR-0328 §7:10), and the call's result
> returns them to planning in the same round, each under an `M` label and labelled as
> §6:6 says. How many it returns is a composition-root constant.

> **Normative.** The lookup returns only memories that do not rest on outside content
> (ADR-0328 §7:5). A memory that does reaches planning only through a digest (ADR-0328
> §15:6), and the lookup digests nothing.

> **Normative.** `remember`'s declaration states that its result carries no outside text,
> so its result goes to planning whole (ADR-0306 §5:14).

> **Normative.** A lookup that fails leaves the candidate recorded. The result says the
> similar memories could not be read, and the call is done.

> **Normative.** The lookup writes nothing and decides nothing. The observer's own search
> (§8) is the one that decides how a finding relates to what is stored.

### 5. Asking the user to confirm a wording

"You confirmed this wording" is the user's yes to text the system rendered (ADR-0328 §4:5).
Today that yes comes from `MemoryPolicy`'s ask; once `remember` no longer passes the policy,
the ask comes from planning, through the same question and approval.

> **Normative.** `remember` takes one further argument, *confirm*, which planning sets
> where it wants the user's yes to the fact's wording before the fact is kept, as in "want
> me to remember you prefer window seats?". It is an ordinary argument of the
> declaration: it is among the values ADR-0306 §5's backstop compares and among those
> ADR-0321 §2:5's exact line shows.

> **Normative.** Authorizing rules, by rule and with no model, that a `remember` call with
> *confirm* set needs you. It runs nothing and goes back to planning as needing the user's
> yes (ADR-0321 §2:10), and planning asks as ADR-0321 §2 decides.

> **Normative.** Under a yes, that call runs as ADR-0321 §4 decides for any approved call,
> *confirm* now being a source of *needs you* beside the policy's confirm and the
> stand-in's (ADR-0321 §4:4), with the policy's recorded allow as the deciding decision
> (ADR-0321 §4:17). It records the candidate in the yes's activation, under the approval,
> and nothing else.

> **Normative.** A no, a change or an unanswered question records nothing, as ADR-0321
> §5:4 has it.

> **Normative.** For a candidate recorded under an approval, the observer adds a support
> with the origin `confirmation`, pointing at the yes's episode and the approved question
> part (ADR-0328 §4:5). The memory it backs as worded carries exactly the fact the part
> showed (ADR-0328 §4:6), and the commit step does not reword it.

> **Normative.** No `remember` call passes `MemoryPolicy`. The observer's writes do (§12).

> **Normative.** No `UserConfirmation` is built for a candidate. The confirmation support
> carries the user's yes on the record (ADR-0328 §4:5), and a memory it backs as worded is
> in band `ASSERTED`, which is what `MemoryPolicy` reads (ADR-0328 §12).

### 6. Planning's instruction, and what it is shown

> **Normative.** Planning's standing instruction says: record a candidate for what would
> still be true and useful if the matter ended or were forgotten, and write a story note
> for what matters to this matter (ADR-0300's test between the page and memory); both may
> be written for one thing, each for its own purpose, with nothing copied from one to the
> other.

> **Normative.** It says: record single observations as candidates; be eager for what is
> about the user and their world — people, places, preferences, constraints, plans — and
> strict for trivia.

> **Normative.** It says: when using a memory reveals anything new about it, record a
> candidate naming it by its `M` label, and otherwise record nothing about it; a
> judgment that a memory is still true, or may not be, is never recorded as evidence by
> itself.

> **Normative.** It says: after a candidate's lookup, ask the user in the moment only
> where a similar memory conflicts with the candidate and the conflict matters to what is
> being done.

> **Normative.** The reply to a request to remember says that the assistant will remember
> it, as "got it, I'll remember" does, and never that it is saved. Planning's instruction
> says so, and `remember`'s result tells planning the candidate is recorded and pending.

> **Normative.** Planning's label for a memory carries what ADR-0328 §15:5 says and, beside
> it, each unresolved open question on the memory in words (§13).

> **Normative.** Planning notes the memories it relied on by a call to a capability of its
> own, naming each by its `M` label and saying in words what the reliance shaped. The
> capability's effect is none, it is safe to repeat, it never leaves the hub, its outcome
> is never unknown, and it returns no outside text. The round records the call, and
> nothing else records it.

> **Normative.** Planning's instruction says: note reliance for a memory that shaped a
> suggestion, an answer or an action, and not for one mentioned in passing.

> **Normative.** Where an episode that is not processed is shown in the episode window, the
> candidates its own rounds record as `remember` calls are shown with it, each by its fact
> and marked pending. A candidate recorded under an approval is shown in the question that
> asked it, whose exact line carries its fact (ADR-0321 §2:5). No other rendering shows a
> candidate.

### 7. The trigger

> **Normative.** An episode is due to the observer once it has left the episode window:
> once the episode selector ADR-0276 §4:1 wires, whatever its rule, run as for the next
> activation, does not return it. The first time an episode is due is the only time it is
> processed automatically: an episode that returns to the window after it was processed is
> not processed again.

> **Normative.** An episode stays in the window until newer episodes push it out, however
> long that takes. A quiet hub keeps its last episodes in the window, where the next
> activation sees them.

> **Normative.** Every activation's episode counts toward the window, a timer's and a
> push's included, as ADR-0276 §4:3 counts them.

> **Normative.** The observer is not an activation. It records no episode, links nothing
> to a story, and adds nothing the episode selector reads.

> **Normative.** An episode that occurred before 2026-10-16T00:00:00Z is never due. A
> composition-root constant holds that instant.

> **Normative.** A run starts when an activation's episode is frozen (ADR-0286), without
> the activation waiting on it, and on a scheduler row whose interval a setting holds
> (ADR-0083 §7), armed by default, so that a retry is not held for the next activation.

### 8. What the observer reads

> **Normative.** For a leaving episode the observer reads: the episode's whole record; the
> episodes still in the window that occurred after it; for each story the episode's
> activation belongs to, its summary and its most recent episodes, up to a composition-root
> bound; and past episodes, their candidates and memories related to the episode, found by
> relevance search over the memory store, up to a composition-root bound.

> **Normative.** It commits only findings that come from the leaving episode, and
> inferences that the leaving episode completes. A later episode only corrects or qualifies
> such a finding; what is new in a later episode waits until that episode is due.

> **Normative.** Several episodes due in one run may be read together in one scout call.
> Each finding names the one episode it comes from, and each episode is processed and
> recorded on its own (§16).

> **Normative.** The observer reads no held result (ADR-0308 §6) and no model's hidden
> thinking, which no episode records. The diagnostic record stays unread (ADR-0314 §3:1).

> **Normative.** Every span the observer renders reaches its model as quoted source data
> under ADR-0098 §2, attributed from the record — whose message, which round, which
> digest, outside or not — and never from the text.

> **Normative.** The observer's two steps render an episode's parts as this section and §9
> name, outside input and digested evidence included, each marked outside where it is. They
> render an episode's `content` only as ADR-0284 §8:2 renders it for an episode without a
> processing record, and no other field (ADR-0284 §8:3 and §8:5, as §20 supersedes them for
> the observer).

### 9. Scout and commit

> **Normative.** The **scout** is one model call over what §8 names, with the leaving
> episode's candidates as hints. It proposes findings: each states one claim in words,
> names the episode it comes from, and names the parts of episodes it rests on. A finding
> may come from a candidate or from the record alone, and a candidate may give no finding.

> **Normative.** The scout writes nothing. Its findings and the outcome of each are
> recorded on the leaving episode's observation record (§16).

> **Normative.** The **commit step** is one model call per finding, given only: the claim;
> the parts the finding rests on, each rendered with the message it answers where it is a
> reply; and the memories the observer's search finds similar to the claim, with their
> supports and open questions.

> **Normative.** The commit step decides the memory's wording, which supports to add and,
> for each, its direction, whether it backs the claim as worded, how sure the reading is,
> its about-when and its note; and which of ADR-0328 §5's operations to apply, or that
> nothing is kept. Its decisions follow §§10–11.

> **Normative.** Code, never a model, sets each support's origin (ADR-0328 §4:2), its
> `when` (ADR-0328 §4:12), its source details (ADR-0328 §4:13), and its added at and by;
> checks that every part a support points at resolves in a stored episode; and checks
> §11:5's floor. A decision that fails a check is not written, and the finding's outcome
> says so.

> **Normative.** A support the observer adds points at the input or one of its messages, a
> round's message, an evidence item or a confirmation (ADR-0328 §4's part table), or is an
> observer's inference (§9:7). A finding resting on a result points at the evidence items
> of the digests of that result; a result no digest recorded supports nothing.

> **Normative.** ADR-0328 §4's part table gains one part, **an observer's inference**,
> addressed by the episode whose processing drew it, and its origin table one origin,
> `observer_inference`, which ranks at inference and is not outside. The observer adds
> such a support, `for` and backing the claim as worded, only to a memory whose claim is its
> own reading of the other supports it adds with it, which are `for` and do not back the
> claim as worded, as a preference drawn from several choices is; and `against` only to a
> memory that the ingest creating that memory retires (§12:4). Its how sure is the commit
> step's, its `when` is that episode's `occurred_at`, and it carries no source details.

> **Normative.** A memory from a source is worded as what its source said — which source,
> and as of when — and never as the fact itself.

> **Normative.** Two settings name the scout's model and the commit step's. Each route is
> built from its setting where it is set and from `default_model` where it is not, and
> neither falls back (ADR-0285 §5:3's rule). The scout is meant for a capable model and the
> commit step for a cheaper one; the settings, not this decision, choose them.

### 10. The assistant's own words

> **Normative.** The assistant's own words are never evidence about the user. A support
> pointing at a round's message (`assistant_message` or `assistant_message_over_outside`)
> is added to a memory about the user only where the user, in the leaving episode or a
> later one the observer read, asked to keep what that message said or confirmed it; and
> the user's message that did so is then added beside it.

> **Normative.** Without such a request or confirmation, a round's message backs no claim
> about the user and counts toward no evidence bar, whatever the user did not object to.
> Silence is not confirmation.

> **Normative.** This is an admission rule. ADR-0328's origin table ranks the origins
> unchanged.

### 11. Keep rules and the evidence bar

> **Normative.** An explicit request to remember, or a correction, in the user's own words
> is always kept: where no stored memory states it, the observer creates one, and where
> one does, it adds the user's message as a support. Only the write path's refusal (§12)
> stops it, and §13 says where that refusal raises an open question.

> **Normative.** A fact the user said in passing is kept where it is worth keeping by
> §6:2's test.

> **Normative.** A report — what a source said — is kept where it is worth knowing later
> and not cheap to read again from its source, worded as §9:8 says.

> **Normative.** A single observation is evidence only. It is not kept as a memory by
> itself; it waits as a candidate on its episode, where a later run's search finds it.

> **Normative.** The observer creates a memory whose standing would be inference only where
> its counted `for` supports other than an observer's inference point at at least three
> distinct episodes, and it carries fewer counted `against` supports than `for` ones. Code
> checks both before the write.

> **Normative.** Beside that floor, the commit step judges that the supports bear the
> claim as independent occasions — several exchanges of one sitting count once — that no
> clear majority of the evidence is against it, newer evidence weighing more, and that the
> wording claims no more than the supports span.

> **Normative.** A memory the user confirmed, or one resting on what the user said, needs
> no bar: §11:5 binds a memory at inference alone.

> **Normative.** A sensitive topic — health, money, relationships, mood, beliefs — is kept
> or inferred under the same rules as any other. Nothing tags it, and no guard applies
> beyond the write path's own rules.

### 12. The observer's writes

> **Normative.** Every write the observer makes goes through the orchestration write stage
> (`MemoryWriteStage`), never to the store or a `MemoryWriter` directly (ADR-0106 §6:8).

> **Normative.** Every memory the observer creates is proposed through
> `MemoryWriter.ingest` and ruled on by `MemoryPolicy` (ADR-0328 §11:4).

> **Normative.** Where the commit step finds that a stored memory already states the claim
> as worded, the observer adds the finding's supports to it by ADR-0328 §11:3's operation
> member, one add support each. A raise question and a resolve question are written by that
> member too. A create that `MemoryPolicy` rules `REINFORCE` adds its supports to the
> target as ADR-0328 §11:6 decides.

> **Normative.** A finding that ends, marks wrong or replaces a stored memory is one
> proposal to `ingest` carrying the new memory and that one retiring operation, citing a
> counted `for` support of the new memory that backs it as worded, added to the retired one
> as `against`, so the cited support never ranks above the new memory's standing and an
> inference retires only a memory at inference. A confirmation is cited only where ADR-0328
> §4:6 lets that ingest retire the memory, and otherwise another support backing the new
> memory as worded is cited, or nothing is retired. `MemoryPolicy` rules on the new memory over
> every conflict but the memory it retires. On an `ACCEPT` the ingest
> installs the new memory and applies the operation in one atomic write, each naming the
> other (ADR-0328 §5:6). On a `REINFORCE` of an end or a mark wrong, it adds the supports
> to the target and applies the operation naming no successor, in one atomic write. On a
> `REINFORCE` of a replace, which must name its replacement, and on any other ruling, it
> writes nothing, and the finding's outcome says so.

> **Normative.** ADR-0328 §6:5 refuses a retiring operation whose cited support ranks below
> the memory's standing, and the whole proposal with it. The writer also refuses a
> proposal whose retiring operation cites a support that is not a counted `for` support of
> the new memory backing it as worded, with nothing written.

> **Normative.** A memory the observer writes takes the narrowest placement over every
> record its run was supplied — the scout's supply included — as ADR-0217 §3:3 and §3:5
> decide for a producer deriving a record, and a fold takes the meet as the write path
> does.

> **Normative.** Every write the observer makes adds to the record — a memory, a support, an
> operation, a track-record entry, an open question — and none removes anything (ADR-0328
> §5:5). Processing an episode again, after a clear or by an explicit re-run, follows the
> same rules as processing it the first time, against the store as it then stands; a
> support already on a memory changes nothing (ADR-0328 §4:8), so it adds nothing twice.
> Nothing rebuilds the memory store automatically.

### 13. Open questions

> **Normative.** The observer raises an open question (ADR-0328 §9) in exactly three cases:
> `conflict`, where a write is refused because a support ranks below the standing of the
> memory it would change (§12:5); `policy_ask`, where `MemoryPolicy` rules `ASK_USER` on a
> proposal, on each stored memory the ruling names; and `recheck`, where the commit step
> finds evidence that bears on a memory without establishing a change.

> **Normative.** The question rests on one of the finding's supports, added to the memory by
> the raise question operation (ADR-0328 §5:3), `against` for a conflict or an ask and as
> the commit step judges for a re-check. It is never a confirmation, which ADR-0328 §4:6
> adds to no memory but the one it backs or one its ingest retires, nor an observer's
> inference (§9:7): for a confirmation the question rests on the yes's input instead, and
> for an observer's inference on the supports that inference reads.

> **Normative.** An `ASK_USER` ruling that names no stored memory writes nothing and raises
> nothing. The finding's outcome records the ask, and its candidate waits on its episode.

> **Normative.** A question reaches planning beside its memory wherever the memory reaches
> planning — recall, a memory search, a lookup — in its label (§6:6). Nothing else lists
> open questions, and planning asks only where the question is relevant and the user is
> present.

> **Normative.** The user's answer is an ordinary input, and planning records it as a
> candidate naming the memory. The observer resolves the question with a resolve question
> operation citing the support it adds from that answer, and applies whatever operation the
> answer warrants by §§11–12.

> **Normative.** No background work messages the user, for an open question or anything
> else, until a decision on proactivity says otherwise (ADR-0328 §9:3). An `ASK_USER`
> ruling on the write stage is never logged and dropped.

### 14. The track record

> **Normative.** The observer records a track-record entry (ADR-0328 §8) for a memory that
> a call of §6:7 in the leaving episode named, when that episode is due, and only where
> that reliance shaped something the user acted on (ADR-0328 §8:2).

> **Normative.** The commit step decides it, given the reliance call, the memory and the
> parts of the later episodes the finding rests on. It records held up where those parts
> show the suggestion accepted, the action run or the answer used, with nothing
> contradicting the memory; and let down where they show the user correcting what the
> memory said. Where they show neither, it records nothing.

> **Normative.** A correction the user makes is also a finding under §11:1. Acceptance that
> bears on the memory's claim may be added as a support where §10 admits it, and the entry
> itself is never a support.

> **Normative.** An entry is written by a `MemoryWriter` member of its own, conditionally
> on the revision read (ADR-0219 §2), and changes nothing where the memory already carries
> an entry for that episode (ADR-0328 §8:3).

### 15. Where the observer lives

> **Normative.** The observer is a background stage in `orchestration/`: its scout, its
> commit step, its trigger and its run. It holds by injection its two model routes, the
> memory store, the write stage, the plan store, the story store and the episode selector,
> and is built by the composition root.

> **Normative.** No `Protocol` is added for the observer, and nothing of it is placed in
> `learning/`, which keeps its import-linter contracts.

> **Normative.** The observer is handed the episode selector the composition root wires
> into understanding (ADR-0276 §4:1), so the window it tests is the window understanding is
> shown.

> **Normative.** An import-linter contract forbids the observer's modules importing
> `orchestration.held_results`.

> **Normative.** The observer's writes are background maintenance of the assistant's
> records, not actions: planning does not choose them, authorizing does not check them,
> and they run on no channel (ADR-0292 §12:1–§12:2, as §20 supersedes them for the
> observer, after ADR-0300's carve-out for the hub's own story changes).

> **Normative.** A model call the observer makes is processing (ADR-0292 §12:4), through
> `models/` and its egress rule.

> **Normative.** The observer logs stage and code-owned reasons only, never a fact, a
> wording or an identifier that may carry personal data (ADR-0004 §5, ADR-0275 §8).

### 16. Limits, and the observation record

> **Normative.** The plan store keeps one **observation record** per processed or attempted
> episode, keyed by the episode's id: its state (processed, skipped, waiting or stuck), its
> attempts with their instants and the model calls each made, when it may next be
> attempted, the scout's findings, and each finding's outcome — what was written, with the
> memory ids and operations, or why nothing was. Exact shapes are the implementing lane's.

> **Normative.** The queue is a query, never a store: the episodes that are due (§7), have
> no observation record marked processed, skipped or stuck, and may be attempted now.

> **Normative.** Due episodes are processed in the order they occurred, by `(occurred_at,
> episode id)`, oldest first.

> **Normative.** An attempt that fails is retried with a backoff, doubling from a
> composition-root base to a cap. A finding whose outcome is recorded is not committed
> again on a retry; a retry runs what has no outcome.

> **Normative.** An episode whose attempts reach a composition-root count is marked stuck
> and set aside, and later episodes proceed. A stuck episode is kept, logged under a
> code-owned reason, and processed again only by an explicit re-run.

> **Normative.** The hub runs at most one observer run at a time. ADR-0219 §2's conditional
> write is the backstop.

> **Normative.** An episode whose input carries no message, the user's or from outside,
> whose rounds record no candidate, and whose digests hold no evidence item is skipped by
> rule, with no model call, and marked skipped.

> **Normative.** A run processes at most a composition-root number of episodes, so a
> scheduled run stays bounded on the scheduler's serial loop (ADR-0083 §7). What is left
> waits for the next run.

> **Normative.** A setting bounds the observer's model calls in any 24 hours, with an
> initial value of 300. A run that would exceed it stops, and the episodes left wait; none
> is dropped. An outage likewise leaves episodes waiting.

> **Normative.** `PlanStore` gains members that write an observation record, read one by
> episode id and read the model calls made since an instant. Its export carries the
> observation records and its clear erases them with the rest (ADR-0004 §6). An episode
> whose record a clear erased is processed again, additively (§12:7), and an episode whose
> effect records a clear erased carries no candidate (§3:3).

> **Normative.** The plan store's schema change ships its upgrade and its test of a file the
> previous release wrote (ADR-0326 §4:1–§4:2), and raises the plan store's `Store.shape`
> in `scripts/upgrade_stores.py` with a carry from the shape it replaces (ADR-0326 §7).

### 17. The catch-up

> **Normative.** The first run takes every due episode since §7:5's instant, oldest first,
> under §16's budget. It is the observer's ordinary run over a long queue and takes no
> mechanism of its own.

> **Normative.** A legacy memory (ADR-0328 §16) whose claim a finding backs as worded gains
> the finding's supports, and so stops being legacy (ADR-0328 §7:8) and stands as they make
> it. A legacy memory no finding backs stays as it is.

> **Normative.** Nothing is deleted by the catch-up, a legacy memory and its legacy support
> included.

### 18. What the user sees

> **Normative.** The belief panel shows the pending candidates — those of episodes not yet
> processed — each by its fact, marked as pending, to the owner alone.

> **Normative.** `AssistantEngine` gains a read of the pending candidates, which the panel
> calls, and the change advances `PROTOCOL_VERSION` (ADR-0124 §9).

> **Normative.** Nothing more is shown by this decision. A view of the observer's outcomes,
> of open questions and of the track record is a later interfaces decision's.

### 19. Delivery

| Lane | What it lands | Where |
| --- | --- | --- |
| 1 | The observation record: its types, `PlanStore`'s members, the conformance suite, the canonical fake, the SQLite plan store and its upgrade (§16) | `core`, `planning`, `testing` |
| 2 | `MemoryWriter`'s track-record member and the proposal that may retire (§12:4, §14:4), with the writer `observer`, the origin `observer_inference` (§9:7), the suite, the fake, `MemoryIngestor` and the memory store's carry for the new members | `core`, `memory`, `testing` |
| 3 | Planning's side: `remember` repurposed, the lookup, *confirm*, the reliance capability, the instruction, the labels and the projection's candidates (§§3–6), behind a composition switch that is off | `orchestration`, `core` |
| 4 | The observer stage, its settings, its composition and scheduler row, and the switch turned on (§§7–17) | `orchestration`, `app`, `service`, `core` |
| 5 | The pending candidates' read, the wire and the panel (§18) | `orchestration`, `wire`, `interfaces` |

> **Normative.** Lanes 1 and 2 merge before lane 4, and lane 3 before lane 4. Each lane
> that consumes a contract is briefed after the lane landing it has merged (ADR-0137 §4:1).

> **Normative.** The lanes run back to back in one milestone, with no other design waited
> on between them, and planning's side and the observer go live together in the deploy
> after the last of them, as ADR-0323 §15:1 has a line go live.

> **Normative.** No build in which `remember` records candidates while the observer does
> not run is deployed to a person's hub. Lane 3's switch stays off until lane 4 turns it on,
> and lane 4 turns it on in the change that wires the observer.

> **Normative.** Until that deploy, ADR-0328 §13's interim governs `remember` and its yes
> path.

> **Normative.** The catch-up (§17) runs on the hub after that deploy, under the deploy's
> backup (ADR-0326 §6), and no lane runs it.

### 20. Relationship to earlier decisions

Superseded in part; every clause the middle column does not name stands:

| Earlier decision | What it replaces | By |
| --- | --- | --- |
| ADR-0050 | Its deferral of assertion against assertion, as it reaches the memory a proposal's retiring operation names (§12:4) | The retiring operation, guarded by ADR-0328 §6:5 |
| ADR-0284 | §8:1's projection, in the addition alone: an episode's candidates (§6:9); §8:3 and §8:5, for the observer's two steps | §6:9, §8:6 |
| ADR-0285 | §1:2 | The observer is the producer of memories from episodes that §1:2 waited for (§2). Under §1:3 it adopts none of the clauses ADR-0285 superseded |
| ADR-0292 | §12:1's and §12:2's reach, for the observer's writes | §15:5 |
| ADR-0294 | §1:2's second sentence | A source's content reaches memory only through an episode, as the observer commits it from what the episode recorded, never from a source read (§§8–9) |
| ADR-0306 | §3:2 whole; §4:3 in what remains in force; §4:8's and §4:9's limbs for a memory `MemoryPolicy` rules on | §3:7, §5:6 and §12:2 |
| ADR-0309 | §6:5 | §2 |
| ADR-0319 | §5:1–§5:3 | §13 |
| ADR-0321 | §4:4's and §4:17's `MemoryPolicy` limbs, replaced by *confirm* as a source of *needs you*; §5:1, §5:2, §5:5, §5:6 and §5:7 | §5, §12, §13 |
| ADR-0328 | §4:2's origin table and §4:12, in the additions alone: the observer's inference, its part, origin and `when`; §11:3, in the addition alone: the track-record member; §11:4, in the addition alone: a proposal that may retire; §15:5, in the addition alone: open questions in planning's label | §9:7, §14:4, §12:4, §6:6 |

Read through and not superseded:

| Earlier decision | What changes |
| --- | --- |
| ADR-0328 §13, §17 | Nothing: the interim governs until this decision is implemented, and this decision is the one §17 names |
| ADR-0217 §3:3, §3:5 | Nothing: the observer is a producer deriving a record (§12:6) |
| ADR-0106 §6:1, §6:8 | Nothing: the taint floor rules on what the observer proposes, and its writes go through the write stage |
| ADR-0276 §4 | Nothing: the selector decides the window, and the trigger follows whatever it decides (§7) |
| ADR-0300 §2 | Nothing: its test between the page and memory is planning's instruction (§6:1) |
| ADR-0321 §2–§4, §5:4 | Nothing beyond the table above: *confirm* asks, and a yes approves, as any question does |
| ADR-0326 | Nothing: lane 1 carries the plan store's upgrade, and lane 2 any stored enumeration's |

> **Normative.** This numbered draft records its replacements on the status lines and in a
> dated header note of each ADR this section's first table names, atomically with this ADR
> under ADR-0070 and ADR-0082, preserving their ratified bodies. The replacements take
> effect on this ADR's ratification.

## Consequences

**What becomes possible.**
- The hub learns from use: what the user asks it to keep, what they say in passing, what
  sources report that is worth keeping, and inferences with enough independent evidence,
  each with supports pointing at the episodes it rests on.
- One writer: every memory change has one author, one route through the policy, and an
  outcome recorded beside the episode that caused it.
- Planning stops spending a turn on writing memory and stops being asked about writes;
  it asks only for a conflict that matters, or for a wording it wants confirmed.
- Hindsight: an episode is committed only after the next activations have had their say,
  so a "never mind", a correction or a sarcastic aside is read before anything is kept.
- Open questions and the track record get their writer.

**What it costs.**
- A model call per due episode for the scout and one per finding for the commit step,
  bounded by the daily budget; and embedding searches per run.
- A memory appears only after its episode leaves the window, about ten activations later.
  Meanwhile the episode window and recall carry it, and the panel shows it as pending.
- A missed candidate is a missed memory unless the scout catches it in the record. A
  re-run can sweep later.
- A clear of the plan store makes every episode since §7:5's instant due again, and the
  observer spends its budget re-reading them, adding nothing twice.
- Two interfaces of the observer are new prompts, owed to the owner's reading as every
  prompt is.

**What stays open.**
- Store maintenance and #829's default; strength with use and fading; forgetting;
  credibility per source; the surface that starts a re-run or reprocesses a stuck episode;
  a view of outcomes, questions and the track record; diagnostic entries for the
  observer's calls; history import as activations.

## Alternatives considered

- **A typed candidate list on the episode record.** Not chosen: the round already records
  the call with its arguments and the episode its labels, and a new field is a schema
  change ADR-0326 charges a migration for. The candidate is the call as recorded.
- **Two candidate flags, "you asked" and "worth keeping".** Rejected by the owner: the
  observer reads whether the user asked from the user's own words, more safely than
  planning can.
- **The observer as an activation.** Rejected: its episodes would enter the window, push
  real episodes out faster and be observed in turn.
- **Running on every episode as it freezes, or on story changes.** Rejected by the owner:
  too much, and with no hindsight. Leaving the window is the boundary between "in the
  window" and "long-term".
- **Per-channel learning postures.** Withdrawn by the owner: channels stay about media,
  and planning judges what is worth keeping in context.
- **One broad call that also commits.** Rejected: the commit step sees only what a
  finding rests on, so a manipulated or confused scout can propose but cannot launder
  content into a memory it does not rest on.
- **Markers in a new store.** Not chosen: the plan store already holds per-activation
  bookkeeping and its data rights, and a new store would add a file, a triad and an
  upgrade path for no gain.
- **Dropping the yes path with nothing in its place.** Not chosen: "you confirmed this
  wording" would then have no producer once `remember` stops passing the policy. *confirm*
  keeps it on the question and approval that already exist.
- **Reliance in episode notes.** Not chosen: episode notes carry no citations (ADR-0307
  §4:1), and a call names its memories by label where code resolves them.
