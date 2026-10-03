# 286. An episode is open while its activation runs, and frozen when it ends

- Status: Accepted
- Date: 2026-10-03
- Scope: [M36](https://github.com/leonapivato/ai-assistant/milestone/2), reopened 2026-09-30 for [#2613](https://github.com/leonapivato/ai-assistant/issues/2613); step 3a of the plan recorded there on 2026-10-03, the open episode, behind the cutover that steps 2 and 3 share.
- Dependency: ADR-0284 and ADR-0285, implemented at `6b41b305`.
- Authorization: the owner directed on 2026-09-30 (#2613) that the working episode and the saved episode be the same thing, ruled the minimum on 2026-10-03, agreed the shape and its recommendations in conversation the same day, accepted proposal #2657 ("lgtm, convert it to the ADR") and directed its conversion into this ADR. The dispatcher assigned 0286, the next number on `main`. That authorizes drafting and numbering, not ratification or implementation.
- **Partially supersedes** [ADR-0114](0114-the-store-contract-carries-the-walk.md) — **one scope, read across two clauses.** **§1:2's *in the store's own insertion order* and §1:7's *nothing left to examine*, at an open episode alone**: a chunk examines no record at or past the lowest-keyed open episode, and a chunk that carries no position because that episode is next means nothing is left to examine for now (§6 below). Every other clause stands, §1:3's never-reissued key included.
- **Partially supersedes** [ADR-0204](0204-a-record-carries-whether-the-supply-it-was-produced-over-held-withheld-content.md) — **one scope, read across three clauses.** **§2:5, §2:6 and §5:5, for an open episode alone**: until it freezes, an episode carries reach `OWNER` and setter `DERIVED` whatever the evaluation will find, and the write that freezes it writes the evaluation's value in place of that, clearing it where the evaluation is `False` (§6 below). The evaluation, its terms, its site and its value at freeze stand, and every other clause stands.
- **Partially supersedes** [ADR-0217](0217-a-record-carries-who-may-receive-it-and-a-model-may-only-narrow-it.md) — **one scope, read across two clauses.** **§1:3 and §3:3, for an open episode alone**: an open episode is written with reach `OWNER` and setter `DERIVED` though no evaluation has found anything yet, and the write that freezes it replaces that placement with the derivation's, wider or not (§6 below). Every other clause stands.
- **Partially supersedes** [ADR-0223](0223-a-captured-episode-carries-the-externality-of-the-supply-its-turn-ran-over.md) — **one scope.** **§3:1's partition, in the addition alone**: an episode a restart closes is a fourth capture site, and keeps the `Provenance.derived_from_external` its stored episode carries, which the writer carries into each append from the latest value the pass holds, computed or retained from a parked turn, or `False` where the pass held none (§4, §7 below). Every other clause stands.
- **Partially supersedes** [ADR-0275](0275-an-episode-records-one-activation-after-processing-ends.md) — **eleven scopes.** **§1:4's *no live activation log***: the episode is written at admission and extended as stages end (§2, §3 below). **§2:2's *with no durable start row***: the admission write is one. **§4:1's record shapes, in the changes alone**: `status`, `reason` and `ended_at` are `None` while a record is open, `ProcessingReason` gains `hub_stopped`, and `schema_version` is 6 (§1, §7, §13 below). **§5:3's table, in the addition alone**: a restart's close records `interrupted` / `hub_stopped` (§7 below). **§8:2's sequence, and its *no captured processing envelope is updated in place afterward***: the episode is inserted at admission and replaced at each stage end and at freeze (§2–§4 below). **§8:4's last sentence**: an open episode is a durable record of a pass in progress. **§8:6's capture timestamp, in when it is taken**: by the admission write (§2 below). **§8:13's first sentence, in its *interrupted* member**: a restart closes an episode admission wrote as `interrupted` (§7 below). **§9:4, for an open episode alone**: the open state is a ground for `OWNER` / `DERIVED`, and the write that freezes it may widen that placement (§6 below). **§11:5's *unavailable* label, for an open episode's end fields alone**: they are labelled in progress (§11 below). **§12:6's immutability, for an open episode alone**: its processing record and response may be replaced by a record that extends them (§3, §12 below). Every other clause stands, §2:4's single finalization, §3:4, §6:2's collision rule and §9:1's bound included.
- **Partially supersedes** [ADR-0276](0276-an-activation-is-understood-before-it-is-associated-and-the-understanding-is-retained-with-its-episode.md) — **two scopes.** **§7:1's *exactly one*, for an open record**: an open record carries no `understanding_omitted` and may carry no understanding (§1 below). **§7:3's *written once, at capture* and *no captured record is updated in place afterward***: versions are written as the stage that records them ends (§3 below). §7:3's last clause, that a later activation never rewrites an earlier episode's understanding, and every other clause stand.
- **Partially supersedes** [ADR-0280](0280-an-activation-controller-runs-the-stages-by-rules-and-records-every-choice-with-the-episode.md) — **four scopes.** **§4:2's member set, in the addition alone**: `ControllerRule` gains `hub_stopped` (§7 below). **§6:2's appenders**: a restart's close appends an end entry too (§7 below). **§6:5 entire**: entries are written as stages end (§3 below). **§7:1's validator, for an open record**: an open record's stages carry no end entry (§1 below). Every other clause stands.
- **Partially supersedes** [ADR-0281](0281-recall-runs-before-understanding-and-understanding-reads-what-it-found.md) — **one scope.** **§6:4's *written once, at capture***: the recall result is written when the recall stage ends (§3 below). Every other clause stands.
- **Partially supersedes** [ADR-0283](0283-a-channels-history-is-its-episodes-and-the-turn-index-is-retired.md) — **three scopes.** **§1:3's *written with the record and never changed***: an episode whose channel is absent gains it by a later write, and its columns are written then; once written they never change (§3, §12 below). **§7:1's sequence**: the episode is inserted at admission, and the archive entry and `record_turn` follow the write that freezes it (§4 below). **§7:3 and §7:4, in what the writer does to the episode**: after a capture failure it deletes the episode whatever the conversation's state (§5 below). Every other clause stands, §7:2's verification included.
- **Partially supersedes** [ADR-0284](0284-an-episode-is-the-experience-of-processing-its-activation.md) — **five scopes.** **§5:5's validator, for an open record**: it carries no end entry (§1 below). **§6:2's last sentence, for an open episode**: the store passes over it on the reads that feed models, before any reader sees it (§6 below). **§7:1's *the writer sets every processing-record episode's `content` from it*, in when**: at freeze, and an open episode's `content` is empty (§1, §4 below). **§7:4's pass, for an open episode**: the pass leaves it. **§9:1's values**: `schema_version` is `Literal[6]` and the format 7 (§13 below). Every other clause stands.

## Context

The owner directed on 2026-09-30 that "the working episode and the saved episode
should be the same thing", and ruled its minimum on 2026-10-03: the episode is open
from admission, appended as each stage ends and frozen by its end entry, and a resume
follows the same rule (#2613).

Today they are two things. ADR-0282's working episode is the activation's state,
held in memory, and the stages read it. The saved episode is written once, after
processing ends (ADR-0275 §8:2): an activation cut short by the process ending leaves
nothing, and a restart never invents one (ADR-0275 §8:13).

What the code shows, at `6b41b305`:

- `orchestration/activation_writer.py` writes the episode after the pass ends with one
  `MemoryWriteMode.INSERT_IF_ABSENT` write, then the archive entry, then
  `ConversationStore.record_turn` as the deletion check (ADR-0283 §7). The address is
  already fixed at admission, `activation:<activation_id>` (ADR-0283 §2). The writer
  marks a capture in flight when `forget` names its address, so that the capture
  destroys what it wrote.
- `ActivationState` already fills the record in as the pass runs: the speech
  transcript, the resolved channel, the links, the understanding versions, the recall
  result and the stage entries. Each is set where it is learned, and nothing set is
  changed afterwards.
- `MemoryWriteMode.IF_UNCHANGED` (ADR-0219 §2) replaces a stored row only while it
  carries the revision the caller read, and refuses a row deleted meanwhile (§3).
  `MemoryStore.write_atomic` returns ids, not revisions.
- The memory store refuses any write that changes a stored episode's processing record
  or response ("recorded processing and response are immutable", ADR-0275 §12:6) or
  its channel ("an episode's channel is immutable", ADR-0283 §1:3), and embeds a
  record's `content` on every write.
- `EpisodeProcessingRecord.status`, `reason` and `ended_at` are required, and its
  validators require exactly one end entry, last, and exactly one of an understanding
  and an omission.
- Consolidation reads episodes through `MemoryStore.walk_records`, in the store's
  insertion order, and never revisits a record below its position (ADR-0114 §1).
- The engine's first call to `start` runs ADR-0014 §4's recovery scan once, before the
  hub accepts any call. The owner's placement acts decline a record whose setter is
  `DERIVED` and write nothing to it.

Writing at admission meets each of these. The episode is inserted before its channel
is resolved, so the channel arrives later. A model read must not see half a pass, and
its reads must not lose a slot to the activation's own open episode. Consolidation
must not walk past an episode before it is frozen. And a restart must tell the
episodes a dead process left open from the ones a live writer holds.

## Decision

### 1. Open and frozen

> **Normative.** A processing record is **open** while its `status` is `None`, and
> **frozen** once it is set. `EpisodeProcessingRecord.status`, `reason` and `ended_at`
> become optional: all three are `None` while the record is open, and all three are
> set once it is frozen. An episode is open or frozen as its processing record is.

> **Normative.** The record's validators hold an open record to this: its stages carry
> no end entry, and it carries no `understanding_omitted`. A frozen record keeps every
> validator it has today: exactly one end entry, last, and exactly one of a non-empty
> understanding and an omission.

> **Normative.** A validator on `EpisodicMemory` holds an open episode to an empty
> `content` and to reach `OWNER` with setter `DERIVED`. The writer stamps that
> placement with the admission write's reading.

An open record is read by its status and not by the absence of an end entry, so
ADR-0280 §6:2's rule that no meaning is carried by the absence of an entry still
holds.

### 2. Admission writes the episode

> **Normative.** Once an activation is admitted (ADR-0275 §2:1), and before any of its
> processing runs (ADR-0275 §2:3), the writer inserts its episode at `activation:<activation_id>` with
> `MemoryWriteMode.INSERT_IF_ABSENT`. The record carries what admission holds: the
> trigger as admitted, `started_at`, the links already established, and no stage
> entry.

> **Normative.** The admission write takes the capture timestamp once. The episode's
> `occurred_at`, its `expires_at` under `episode_retention`, and the instants
> `record_turn` and the archive entry carry, all reuse it.

> **Normative.** A resume's admission write follows the resolution of its conversation
> through the parking episode (ADR-0283 §5:1). A resume whose conversation is not
> resolved writes no episode, as ADR-0275 §6:5 rules.

> **Normative.** An `INSERT_IF_ABSENT` collision at admission is a capture failure that
> writes nothing at the address and deletes nothing there, because the record at the
> address is not this activation's (ADR-0275 §6:2).

A trigger's channel is set at admission only where ADR-0275 §4:5 already sets it then,
from an accepted event identity. A conversational target is not resolved at admission,
so its channel is absent until a later write carries it.

### 3. Each stage appends; nothing is rewritten

> **Normative.** When a stage ends, the writer replaces the stored episode with a
> record that extends it, under `MemoryWriteMode.IF_UNCHANGED`. The new record adds
> the stage's entry and whatever the stage produced into the record's own fields.

> **Normative.** `core` gains a pure `episode_extends(stored: EpisodicMemory, revision:
> EpisodicMemory) -> bool`, decided from the two records' processing records and
> `outcome` alone. It holds exactly where both carry a processing record with one
> `activation_id`, the stored one is open, the two differ in their processing record or
> `outcome`, and every such difference is one the next clause admits. No other field
> of the episode enters it.

> **Normative.** A revision may differ from the stored record only by: a field at its
> unset value taking a value, for the trigger's `channel`, the speech trigger's
> `transcript`, each field of `links`, `recall`, `outcome`, `response_degraded` and
> `output_degraded`; entries appended at the end of `understanding` and of `stages`,
> each under its bound (ADR-0276 §7:4, ADR-0280 §6:6), with its elided count grown by
> exactly what the bound dropped; and, in the one revision that freezes it, the end
> entry with `status`, `reason`, `ended_at` and `understanding_omitted`. A field that
> carries a value keeps it.

Both bounds keep a fixed head and a sliding tail, so the bound applied to the stored
entries followed by the appended ones equals the bound applied to every entry the pass
recorded. A record frozen through appends therefore equals the record one write at the
end would have stored.

> **Normative.** Before each write after the first, the writer reads the stored
> episode with `MemoryStore.get` and conditions its write on that read's revision. It
> continues where the stored record carries exactly the record it last wrote, or,
> after a write whose outcome it does not know, exactly the record that write carried.
> Anything else, no record included, is a mismatch (§5).

> **Normative.** Where the freezing write's outcome is not known, the writer makes the
> same read once, before the archive entry: a stored record carrying exactly the
> freezing revision confirms the freeze, and anything else is a mismatch.

> **Normative.** ADR-0275 §9:1's bound is measured before every write of the episode,
> on the whole record that write would store. An append that would exceed it is a
> capture failure (§5). No bound is set on one stage's append beyond it.

Bounding the whole record bounds every append, since an append is what one record
adds to the last, and both sequences an append grows are bounded already. A separate
per-stage bound could only refuse what the whole bound refuses, or cut what ADR-0275
§9:1 forbids cutting.

> **Normative.** An append runs inside the pass's own deadline, and its failure never
> fails processing, replaces an answer or repeats a stage (ADR-0275 §8:12).

> **Normative.** Appends go through the fields ADR-0280 and ADR-0284 already define. No
> field is added for a stage's result, and the working episode keeps out of the saved
> one everything ADR-0282 §1:2 keeps out of it.

### 4. The end entry freezes it

> **Normative.** Finalization (ADR-0275 §2:4, §8:10) writes the freezing revision, the
> end entry and its fields, as the last append. Nothing appends to a frozen episode.

> **Normative.** The freezing write sets the fields capture derives from the pass:
> `content` from `episode_content` (ADR-0284 §7:1), the placement from ADR-0204 §2's
> evaluation under ADR-0217 §1:3, `Provenance.derived_from_external`, and the capture
> modality.

> **Normative.** Once the pass holds ADR-0223's value for its episode — computed under
> ADR-0223 §3:2, or retained from a parked turn under ADR-0223 §3:3 — the writer
> carries the latest value it holds into `Provenance.derived_from_external` on each
> append after that, and the freezing write carries the value capture threads, as
> today.

> **Normative.** A conversational finalization writes the archive entry where one is
> owed and then calls `record_turn`, in ADR-0283 §7:1's order, once the freezing write
> is confirmed. ADR-0283 §7:2's verification and its drain apply unchanged.

These fields are not judged by `episode_extends`, which reads the processing record
and `outcome` alone; what bounds them on an open episode is §1's validator, and the
freezing write is what lifts it. The response is `outcome`, as ADR-0284 §4:1 defines
it, appended by the stage that produces it or by the freezing write. Delivery stays a
row the conversation store keeps (ADR-0283 §6), and annotates the episode without
writing it.

### 5. A capture failure ends capture

> **Normative.** A mismatch is a capture failure, logged with code-owned vocabulary
> alone (ADR-0275 §8:12). The writer does not retry the write.

> **Normative.** Any capture failure after the admission write and before the freeze is
> confirmed ends capture for the activation: the writer makes no further append,
> writes no archive entry, calls no `record_turn`, deletes the episode by its id
> through a drain as ADR-0275 §8:11's, and reports the capture degraded.

> **Normative.** Once the freeze is confirmed, a failure of the archive entry or of
> `record_turn` is handled as ADR-0275 §8:7 and ADR-0283 §7:2 handle it today, and does
> not delete a frozen episode on a conversation that stands.

Nothing else writes an open episode: the owner's placement acts decline a `DERIVED`
setter, and the observer's labelling is retired (ADR-0285). What does reach one is a
deletion, by a conversation's sweep (ADR-0283 §8:1), by retention or by `forget`, and
a retry after a deletion could only fail again or re-create what was deleted. Any
other mismatch is a defect, and a retry would hide it.

Deleting the episode keeps a capture failure what it is today: no episode, and a
degraded report. Leaving it open would have the next restart close it as
`interrupted` / `hub_stopped`, a false account of a pass whose processing may have
completed (ADR-0275 §5:4). Where the deletion itself fails, the episode stays open and
the next restart closes it; Consequences names that residue.

### 6. An open episode is owner-only and never a model input

> **Normative.** `MemoryStore.search`, `MemoryStore.select` and
> `MemoryStore.channel_episodes` never return an open episode, and apply that predicate
> before every candidate ceiling, ranking cut and limit, under ADR-0128 §1.
> `ChannelEpisodePage.total` counts no open episode.

> **Normative.** `MemoryStore.walk_records` examines no record at or past the
> lowest-keyed open episode the store holds. A chunk stops before it. Where it is the
> next record to examine, the chunk examines nothing and carries no position, which
> tells its caller that nothing is left to examine for now; the walk's recorded
> position has not passed the open episode, so a later read resumes there.

> **Normative.** `ConsolidationStage` keeps its handling of a chunk with no position:
> it ends the run, reports it exhausted, and advances nothing, so its next run reads
> from the same position.

> **Normative.** A reader that feeds a model and fetches by id — the citation hop, the
> understanding phase's fetch (ADR-0282 §5:1) and any other `get` or `get_many` on such
> a path — treats an open episode as an id with no record (ADR-0282 §2:6).

> **Normative.** `MemoryStore.get`, `get_many`, `episodes`, `episode_chunk`,
> `channel_episode_ids`, `episode_parking`, `export` and the deletions reach open
> episodes as they reach any other.

Every read that feeds a model therefore passes over open episodes: conversation
history, the episode window, recall, the loop's and the structured reads, the citation
hop and consolidation. The store does it on the reads that take a limit, so the
activation's own open episode, which is on its channel for as long as it runs, takes no
history slot. Consolidation is held at the oldest open episode rather than passed over
it, because its walk never returns below its position, and an episode passed over while
open would never be consolidated once frozen. Making other activations' open episodes
visible, once activations run concurrently, is not built here.

Owner-only is the narrowest placement, and `DERIVED` is the setter the type admits for
a narrowing no act or proposal made: until freeze, nothing an open episode holds can
reach anyone the finished episode would not.

### 7. A restart closes what it finds open

> **Normative.** `ProcessingReason` gains `hub_stopped`, and `ControllerRule` gains
> `hub_stopped`.

> **Normative.** On the first call of `Engine.start`, guarded as ADR-0014 §4's scan is
> guarded and before the deletion sweep, the engine closes every open episode the store
> holds that no writer of this process holds. It appends an end entry due `hub_stopped`
> with outcome `done`, with `status` `interrupted`, `reason` `hub_stopped`, and its own
> clock reading as `ended_at` and as both of the entry's readings.

> **Normative.** The close is the freezing write for that episode, with four
> differences. The placement stays reach `OWNER`, setter `DERIVED`, because the
> evaluation that could widen it died with the process. `Provenance.derived_from_external`
> stays as the stored episode carries it: the latest value §4 carried into an append,
> or `False` where the pass held none. No archive entry is written, because no
> capture facts survive. And `record_turn` is called, with no delivery, only where the
> episode is on a conversation's channel, and a `None` from it deletes the episode as
> ADR-0283 §7:2 rules.

> **Normative.** A store failure during the close propagates from `start`, as the
> sweeps' failures do.

A restart's close is a capture site ADR-0223 §3's partition did not have, which is
why ADR-0223 §3:1 is recorded as partially superseded in its addition: the value is
neither recomputed at the close nor defaulted, but read off the episode the pass
itself wrote.

The close invents no episode, and ADR-0275 §8:13's other clauses stand: the episode
was written at admission, and the restart records only how it ended, replaying nothing
and inferring nothing about effects. `ended_at` is when the restart closed the episode,
not when processing stopped, which nothing recorded (ADR-0275 §4:9). The hub calls
`start` before it accepts any call, so the close runs before the first admission; the
in-flight guard keeps it correct for an engine that admits first.

### 8. Forgetting an open episode

> **Normative.** `forget` on the address of an open episode marks the capture in
> flight there, as it does today, and then discards and deletes in ADR-0225 §5:3's
> order, in the same call.

> **Normative.** At its next write after the mark, the writer writes nothing: it
> deletes the episode by its id, ends capture under §5, and reports the capture
> degraded.

The proposal had the writer delete the episode at its next append. `forget` deletes it
at once instead, because ADR-0225 §5:2 makes a record-scoped destruction one act,
"neither performed by halves", and a long stage would otherwise keep stored the text
the user was told was gone. The race the mark exists for stays closed: a write after
the deletion is an `IF_UNCHANGED` against a row that no longer exists, which ADR-0219
§3 refuses, so nothing re-creates the episode. The mark lives in the process, so a
restart finds no marked episode: `forget` has already deleted it.

Refusing to forget an open episode was considered: "forget that" would fail during a
long activation.

### 9. Resumes

> **Normative.** A resume's episode is open from its admission write (§2), its stages
> are appended as they end (ADR-0284 §5:4), and its end entry freezes it, under every
> rule of this decision that governs a channel activation's episode.

A resume is its own activation, and nothing about the episode it continues changes
(ADR-0275 §3:4).

### 10. The working episode

ADR-0282's working episode stays the stages' input, held in memory. The open episode
is its durable copy, written as stages end. Having the controller and the stages read
the stored episode instead is #2598's work.

### 11. Inspection

> **Normative.** The CLI's episode list and detail show an open episode with a label
> saying it is in progress, in place of its absent status and end time. The label's
> wording is the interfaces lane's.

An open episode's detail `version` changes as it grows, so a chunked read of one may go
stale; ADR-0275 §11:4's handling of a stale read applies unchanged.

### 12. The memory-store contract

> **Normative.** `MemoryStore` gains `open_episodes(*, after: int | None = None,
> limit: int) -> tuple[ChannelEpisode, ...]`: every open episode the store physically
> holds, expired and not yet valid included, the lowest `limit` numbered above
> `after` (or from the start where `after` is `None`), in number order, each record
> carrying its stored revision. `limit` and `after` are bounded and refused as
> ADR-0283 §3:2 bounds them.

> **Normative.** The memory store refuses, with `MemoryStoreError` and nothing
> written, a write replacing a stored episode that carries a processing record where
> the written record's processing record or `outcome` differs from the stored one's,
> unless the stored record is open and `episode_extends` holds of the two. A frozen
> episode's processing record and response therefore stay immutable.

> **Normative.** The guard judges no other field. A write that leaves an episode's
> processing record and `outcome` as stored is admitted as ADR-0275 §12:6 admits it,
> the owner's placement acts (ADR-0217 §7) and ADR-0284 §7:4's re-derivation of a
> frozen episode's `content` included; §1's validators still bound what an open
> episode may carry.

> **Normative.** The store keeps whether an episode is open as an indexed column,
> written with every write of the record. An episode's channel columns are written by
> the first write that carries its channel, and never changed by a later one.

> **Normative.** The store embeds no open episode. The write that freezes an episode
> embeds its `content`.

> **Normative.** §6's store predicates and walk rule, `open_episodes` and the write
> guard are a breaking Protocol change, shipped as a triad: the Protocol, the
> memory-store conformance suite and the canonical fake together.

`MemoryStore.write_atomic` keeps its signature. Returning the revisions it stored
would save the writer's read before each append, at the cost of changing a method every
writer calls.

### 13. The cutover

> **Normative.** `EpisodeProcessingRecord.schema_version` becomes `Literal[6]` and
> `EPISODE_RECORD_FORMAT` advances to 7, on ADR-0275 §12's mechanism. No migration or
> earlier read path is a deliverable.

> **Normative.** Each change that alters a shape crossing the wire advances
> `PROTOCOL_VERSION` in that change.

> **Normative.** This decision deploys nothing of its own. Its implementation rides the
> one cutover #2613's steps share, onto a fresh data directory.

### 14. Relationship to earlier decisions

> **Normative.** This numbered draft records its scoped replacements on each affected
> ADR's status line and in a dated header note, atomically with this ADR under
> ADR-0070 and ADR-0082, preserving their ratified bodies. The replacements take
> effect on this ADR's ratification.

| Earlier clause | What changes |
| --- | --- |
| ADR-0114 §1:2, §1:7 | The walk stops at the oldest open episode, and waits there. |
| ADR-0204 §2:5, §2:6, §5:5 | An open episode is placed owner-only; freeze writes the evaluation's value over it. |
| ADR-0217 §1:3, §3:3 | As ADR-0204, in the placement's terms. |
| ADR-0223 §3:1 | A restart's close keeps the externality its last append recorded. |
| ADR-0275 §1:4, §2:2, §4:1, §5:3, §8:2, §8:4, §8:6, §8:13, §9:4, §11:5, §12:6 | Written at admission, extended per stage, frozen at the end; closed on restart. |
| ADR-0276 §7:1, §7:3 | Versions written as recorded; an open record carries no omission. |
| ADR-0280 §4:2, §6:2, §6:5, §7:1 | Entries written as stages end; the restart's end entry. |
| ADR-0281 §6:4 | The recall result is written when recall ends. |
| ADR-0283 §1:3, §7:1, §7:3, §7:4 | The channel is set once, later; the sequence; a failed capture deletes. |
| ADR-0284 §5:5, §6:2, §7:1, §7:4, §9:1 | Open validators; the store passes over open episodes; `content` at freeze; format 7. |

ADR-0282 is unchanged: nothing it adds to the working episode is saved, and the open
episode carries only fields that were saved at the end before.

### 15. Delivery

> **Normative.** Land this ADR ratified before any implementation lane. Then the
> implementation ships as separate PRs in this order:
>
> 1. **`core`, additive**: §1's optional fields and validators, with every writer
>    still freezing in one write; `episode_extends`; `ProcessingReason.hub_stopped`
>    and `ControllerRule.hub_stopped`.
> 2. **`core` with `memory` and `testing`, the `MemoryStore` contract**: §6's store
>    predicates and walk rule and §12 entire, with the conformance suite, the
>    canonical fake, and the sqlite and in-memory stores; `schema_version` 6 and
>    format 7.
> 3. **`orchestration`**: §2's admission write, §3's appends, §4's freeze, §5, §6's
>    by-id readers, §7's close, §8 and §9.
> 4. **`interfaces`**: §11's label.
>
> Lane 2 depends on lane 1, lane 3 on lane 2, and lane 4 on lane 1.

> **Normative.** Lane 2's conformance suite asserts that `walk_records` does not pass
> an open episode and returns it once frozen, that the reads §6 names never return an
> open episode and do not count it against a limit, and that the write guard admits an
> extending revision of an open episode, refuses every other change to an episode's
> processing record or `outcome`, open or frozen, and admits a placement-only change
> to a frozen episode.

> **Normative.** Lane 3's tests assert, through production composition: an episode is
> stored open before the first stage of a typed turn, a spoken turn, an informational
> event and a resume; each stage's end leaves one more entry on the stored record; a
> frozen record's processing record equals the one the pass would have written in one
> write; history, recall and the episode window never return an open episode, and the
> running activation's own episode takes no history slot; an engine started over an
> open episode closes it `interrupted` / `hub_stopped`, owner-only, with no archive
> entry, and a second `start` closes no episode this engine admitted; a resume of a
> parked turn whose value is true, cut off after it composes, is closed with
> `derived_from_external` true, and a pass that held no value is closed with it false; `forget` during
> a pass leaves no episode and no archive entry, and the pass's later stages write
> nothing; a conversation deleted during a pass leaves no episode; a forced mismatch
> reports the capture degraded and leaves no episode; and an `INSERT_IF_ABSENT`
> collision at admission deletes nothing.

> **Normative.** The M36 addition's exit is ruled by the owner on #2613, with the
> tested revisions and live-hub evidence recorded there. A ratified ADR, merged lanes
> or a passing suite alone does not establish it.

## Consequences

What a reader of the wiki's
[Episodes](https://github.com/leonapivato/ai-assistant/wiki/Episodes) page would find
different:

- "Written once" becomes **built while the activation runs and frozen when it ends**.
  The end entry is the last change, and a later activation still never rewrites it.
- "An activation cut short by a crash may leave no episode" becomes **a crash leaves the
  episode as far as it got, closed as interrupted on restart**. "A restart never invents
  one" still holds: it closes only an episode that admission wrote. Effects and timers
  are still not left to the episode (#2584).

And in the system:

- The episode has its identity in the store from admission, which is what stories,
  notes and in-progress views can point at.
- A channel's order, its episodes' `occurred_at` and the archive's instants are all
  admission order, since the store numbers an episode when it inserts it
  (ADR-0283 §1:1) and the capture timestamp is now taken then.
- Every stage end costs a read and a conditional write, where a pass writes once today.
- Consolidation waits for the oldest open episode. An episode left open by a failed
  deletion after a capture failure holds it until the next restart closes that
  episode; the capture loss is in the log.
- A conversation's digest counts its frozen episodes, not the one in progress.
- An episode the restart closes stays owner-only, even where the finished pass would
  have been placed for anyone, and is marked as resting on external content only as
  far as its last append recorded.
- What follows: step 3b, episodes kept until forgotten and the archive retired; then
  effects written into the open episode as they happen (#2584), and other activations'
  open episodes made visible once activations run concurrently.

## Alternatives considered

- **An append table merged on read.** Each stage end inserts a row, and readers
  assemble the episode. It gives the same guarantee with more machinery, and every
  reader pays for the merge.
- **Keep writing once, and add a crash marker.** A small "activation started" row,
  turned into a stub episode on restart. That is the `EpisodeEnding` approach of the
  first ADR-0283 draft, closed unmerged (#2614). It leaves two records, and the episode
  still has no identity in the store until the end.
- **Real placement from admission.** Evaluate placement as the supply grows. That ties
  every append to the disclosure rules, which #2643 has not settled. Owner-only until
  freeze is the narrowest choice and defers nothing that matters.
- **Retry once on a revision mismatch.** Nothing but a deletion reaches an open
  episode, so a retry either fails again or re-creates a record the user or a sweep
  deleted, and any other mismatch is a defect a retry would hide.
- **Leave an episode open after a capture failure.** The next restart would close it as
  interrupted by a stopped hub, which is false of a pass that completed.
- **Let the writer delete a forgotten open episode at its next append.** The proposal's
  form. It splits a forget into halves, against ADR-0225 §5:2, and keeps forgotten text
  stored for as long as a stage runs.
- **A keyword on the reads to include open episodes.** No reader that feeds a model
  wants them, and the readers that do have their own operations.
- **Bound each stage's append.** The whole-record bound already bounds it, and a
  per-stage bound could only refuse the same appends or truncate them.
