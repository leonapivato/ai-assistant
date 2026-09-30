# 283. An episode is open while its activation runs, and frozen when it ends

- Status: Proposed
- Date: 2026-09-30
- Scope: [M36](https://github.com/leonapivato/ai-assistant/milestone/2), reopened 2026-09-30 for [#2613](https://github.com/leonapivato/ai-assistant/issues/2613); folds in [#2608](https://github.com/leonapivato/ai-assistant/issues/2608) and [#2592](https://github.com/leonapivato/ai-assistant/issues/2592).
- Dependency: ADR-0275, ADR-0276, ADR-0280, ADR-0281 and ADR-0282, all implemented at `5d872812`.
- Authorization: the owner accepted proposal #2614 on 2026-09-30, after ruling its seven decisions, its bounds and deletion options and its three additions in conversation the same day, and directed its conversion into this ADR. The dispatcher assigned the next available number, 0283. That authorizes drafting and numbering, not ratification or implementation.
- **Partially supersedes** [ADR-0074](0074-conversation-is-an-entity-and-every-turn-is-an-episode.md) — **one scope.** §3's rule that *"A captured episode's id is derived from the turn, not minted"*, with the paragraph after it in its *derives the id* part alone: a turn's episode id is its activation's episode id (§1 below), which the caller supplies; the store still allocates the ordinal, the index row still names the episode before the episode is final, and §3's insert-not-upsert rule, its no-retry rule and §8's deletion protocol stand entire.
- **Partially supersedes** [ADR-0275](0275-an-episode-records-one-activation-after-processing-ends.md) — **twenty scopes.** **§1:3**, in its *its episode is the post-processing record* part alone: the episode is the activation's record from admission, open until processing ends. **§1:4's exclusion list, in one item**: *"live activation log"* is no longer excluded; the open episode is that log, and §1:4's other exclusions stand. **§2:2**, in its *call-local state, with no durable start row* part alone: the activation ID and start reading are written durably in the open episode at admission. **§4's record shapes, in the additions alone**: §2, §6, §9 and §11 below's status, reasons, fields and trigger flag; every existing field, value and validator stands. **§4:9's last sentence**: `occurred_at` is the admission reading (§2 below). **§6:2**, in its *address allocated by `ConversationStore.append`* part alone: every episode's address is `activation:<activation_id>`; the namespace's reservation to the capture producer stands. **§6:3's last sentence**, for a turn-row write refused at admission alone (§11 below). **§7:5**, in its *persist atomically with the index row* and *immutable* parts alone: the flag is set once, at the freeze (§5 and §7 below), and is immutable from then. **§7:4's eligibility-`True` rule and §9:6's exclusion of the trigger's raw input text, for one consumer and one field**: the channel window's open turns of other activations (§8 below) are rendered from their trigger's exact input text or transcript; attached context and every other field stay excluded. **§8:2**'s sequence, in its *after the pass ends* and ordering parts alone: §2–§5 below's sequence replaces it; a frozen record is still never updated in place. **§8:4**'s last sentence, *"not a durable live-progress record"*. **§8:6**'s capture timestamp, in its *capture* reading alone: the reading is the admission reading. **§8:8**, in its *index-row address* part alone: `SpokenTurn.episode_id` is the episode's id. **§8:13**'s first sentence, in its *fabricates interrupted episodes* part alone: restart freezes an episode left open (§6 below) and still fabricates none. **§9:1**, in its *before any index/archive/content write* part alone: each write of the open record is measured (§10 below). **§9:2**, in its *at capture* part alone: the horizon is stamped at admission. **§10:3**'s and **§10:9**'s read-time liveness, for an open episode alone: it is live whatever its expiry until it is frozen (§4 below). **§12:6**'s third sentence, for §4 below's `advance_episode` and `freeze_episode` on an open episode alone. Every other clause stands.
- **Partially supersedes** [ADR-0276](0276-an-activation-is-understood-before-it-is-associated-and-the-understanding-is-retained-with-its-episode.md) — **four scopes.** **§3:1's conversation-channel tail, in the addition alone**: it also carries the other activations' open turns in the conversation (§8 below). **§4:3's selection, in the addition alone**: the selector passes over the pass's own episode (§8 below). **§7:1's exactly-one validator, for an open record alone**: an open record may carry neither understanding nor an omission (§2 below). **§7:3**, in its *written once, at capture* part alone: versions are written through as §3 below states. Every other clause stands, §7:4's bound included, applied at the freeze.
- **Partially supersedes** [ADR-0280](0280-an-activation-controller-runs-the-stages-by-rules-and-records-every-choice-with-the-episode.md) — **three scopes.** **§4:1–§4:2's enums, in the addition alone**: `ControllerRule` gains `hub_stopped`. **§6:5**, in its *written once, at capture* and *nothing is written durably before finalization* parts alone: entries are written through as §3 below states. **§7:1's validator, for an open record alone**: an open record carries no end entry (§2 below). Every other clause stands, §6:6's bound included, applied at the freeze.
- **Partially supersedes** [ADR-0281](0281-recall-runs-before-understanding-and-understanding-reads-what-it-found.md) — **three scopes.** **§6:1's `RecalledItem`, in the addition alone**: it gains `score` (§9 below). **§6:4**, in its *written once, at capture* part alone: recall's result is written through as §3 below states. **§6:5's `schema_version` literal alone**: it becomes `Literal[5]`. Every other clause stands.
- **Supersedes** [ADR-0282](0282-phases-read-and-write-the-working-episode-and-recall-searches-past-the-windows.md) **§1:2 entire**: §9 below saves what the windows stage chose and what each stage fetched, and advances `schema_version` and the format marker. Every other clause of ADR-0282 stands; §2's working episode is still held in memory, and the stored episode records ids, never records.

## Context

Today an activation has two records. While it runs, `ActivationState` and its
`_ActivationPass` hold the working episode in memory (ADR-0282 §2). When it ends,
`ActivationCoordinator.finish` saves the episode once (ADR-0275 §8), and the
stores refuse every later change to it (ADR-0275 §12:6). For a conversation turn,
the saved episode's address is only allocated then, by `ConversationStore.append`
(ADR-0275 §6:2, ADR-0074 §3).

That split costs four things the design now needs:

- **No identity until the end.** Nothing can point at an episode while its
  activation runs. Stories' mechanical links (M40), effects written as they
  happen (#2584) and notes to self all want to name the episode as soon as the
  activation starts.
- **Nothing visible while running.** The concurrency direction on the wiki's
  [Controller](https://github.com/leonapivato/ai-assistant/wiki/Controller) page
  (read at wiki revision `ea98b15`, direction and not ratified) has other channels
  see activations still in progress. There is nothing stored for them to see.
- **A crash leaves nothing.** ADR-0275 §8:13 accepts that an activation cut short
  by process death may leave no episode.
- **What each phase read is lost.** ADR-0282 §1:2 keeps the window ids, fetches and
  recall scores for the pass alone. Debugging a bad reading on the live hub needs
  them afterwards (#2608), and tuning recall's threshold needs the scores (#2601).

The wiki's [Episodes](https://github.com/leonapivato/ai-assistant/wiki/Episodes)
page (same revision) already describes the episode as "a log, read through current
views": each phase's result is added in the order it arrived and nothing is
overwritten. On 2026-09-30 the owner directed that the working episode and the
saved episode be one thing, open while the activation runs and frozen when it ends,
and that it be done now, before stories build on the split, under M36 because it is
the same topic.

## Decision

### 1. One identity, from admission

> **Normative.** Every episode an activation produces has the address
> `activation:<activation_id>`, allocated at admission with the activation ID
> (ADR-0275 §2:1, §6:1), for a channel activation and for a control activation
> alike. No producer allocates an episode address from a conversation ordinal.

> **Normative.** A conversation turn row keeps its own position,
> `(conversation_id, ordinal)`, which `ConversationStore` allocates. Its
> `episode_id` is the episode's address, which the caller supplies. The store no
> longer derives an episode address from the ordinal or checks a stored address
> against one.

### 2. The episode is written at admission, open

> **Normative.** `ProcessingStatus` gains `open`, and `ProcessingReason` gains
> `in_progress` and `hub_stopped`. A processing record whose status is `open` carries reason
> `in_progress`, `ended_at` equal to `started_at`, `response_kind` `none`, no
> `outcome`, `model_eligible=False`, no end stage entry, and may carry neither
> understanding nor an omission. A record
> with any other status carries neither `open` nor `in_progress`.

> **Normative.** At admission the activation writes its episode with status `open`,
> holding the activation ID, `started_at`, the trigger, `occurred_at` and the
> expiry, with ADR-0275 §8:5's constant `content` and `disposition=None` until the
> freeze. `occurred_at` is the admission reading, equal to `started_at`, and it is
> shared with the conversation turn row. The expiry is stamped then from
> `episode_retention` measured from `occurred_at`.

> **Normative.** The trigger is fixed at admission, except two fields, each written
> once. Its resolved `channel` is written at admission for an input naming an
> existing conversation, and when the begin stage allocates the conversation for a
> new one. A speech trigger's transcript, `None` at admission, is written when
> transcription ends: the exact transcript where one was obtained, including an
> empty or whitespace-only one, and left `None` where transcription failed.

> **Normative.** A failed admission write degrades capture and does not stop
> processing. The pass then writes nothing further to the store for its episode,
> and its capture report is `degraded`.

### 3. Written through as each stage ends

> **Normative.** When a stage ends, the pass writes its episode's new open version
> before the next stage starts. That version adds what the stage produced — its
> stage entry, an understanding version or omission, recall's result, links,
> §9's saved reads — after what the episode already holds, and changes nothing
> already written.

> **Normative.** A failed write-through degrades capture and does not fail the
> stage or the pass. Because each write carries the whole open version, a later
> successful write carries what a failed one did not.

> **Normative.** Only the activation's own pass writes its open episode, apart
> from §6's restart freeze and deletion.

### 4. The store's operations on an open episode

> **Normative.** `MemoryStore` gains three members. `open_episode` inserts an
> episodic record whose processing record is `open`, as an insert-if-absent; a
> present address raises `MemoryStoreConflictError`. `advance_episode` replaces an
> open episode with a later open version. `freeze_episode` replaces an open episode
> with its frozen version, whose status is not `open`.

> **Normative.** `advance_episode` and `freeze_episode` raise a new
> `EpisodeNotOpenError(MemoryStoreError)` when the stored record is absent or not
> `open`. Both refuse, with `MemoryStoreError`, a new version that changes the
> address, `activation_id`, `started_at`, `occurred_at`, the expiry or the trigger
> other than §2's one write of its `channel` and one write of its transcript.

> **Normative.** `advance_episode` refuses a version in which any stored entry of
> the stage record, the understanding versions or §9's saved reads is changed,
> removed or reordered. `freeze_episode` permits only the trimming §10 states.

> **Normative.** Every other `MemoryStore` update path refuses an open episode.
> Deletion, forgetting and retention's own rules are §6's.

> **Normative.** `MemoryStore.search` and `MemoryStore.select` never return an
> open episode. `get_many` and `episodes` return it; `episodes` accepts `open` as a
> status filter. The store computes no embedding for an open episode.

> **Normative.** An open episode is live whatever its expiry: `get_many`,
> `episodes` and retention purge treat it as unexpired until it is frozen, and from
> the freeze its expiry applies as to any record. An episode whose expiry passed
> while it was open is frozen by §6's restart freeze and then purged by the next
> purge.

### 5. Frozen by one last write

> **Normative.** When the pass ends (ADR-0275 §2:4), finalization writes the
> frozen version: the status and reason chosen under ADR-0275 §5, `ended_at`, the
> response, the end stage entry, `model_eligible`, the conversational `content` and
> `disposition` projections, and the capture stamps. The store embeds the frozen
> version's content as it embeds any written episode.

> **Normative.** A conversational freeze writes, in order: the archive entry where
> one is owed, addressed by the episode's address; `freeze_episode`; the turn row's
> freeze; then ADR-0275 §8:11's verification and compensation. A standalone freeze
> writes `freeze_episode` alone.

> **Normative.** After `freeze_episode` succeeds, the episode is as immutable as
> ADR-0275 §12:6 makes any record carrying a processing record.

> **Normative.** Finalization keeps ADR-0275 §8:10's five-second budget, §8:12's
> rule that recording failure never replaces an answer or repeats processing, and
> §8:3's output check before the archive write. A `recorded` capture report means
> the frozen version was written and verified.

### 6. Restart, and deletion while open

> **Normative.** Before the hub admits its first activation, it freezes every open
> episode with status `interrupted`, reason `hub_stopped`, no response, and
> `model_eligible=False`, keeping everything already written. A channel
> activation's record gains an end stage entry whose `due` is the new
> `ControllerRule` member `hub_stopped`. A record with neither understanding nor an
> omission takes the omission `not_reached`. `ended_at` is the latest reading the
> record already holds. The turn row, where there is one, is frozen with it.

> **Normative.** The restart then freezes every conversation turn row still open,
> whatever became of its episode: with the episode's `model_eligible` where the
> episode is frozen, and with `model_eligible=False` where no episode with its
> address exists. It writes no episode and no binding for such a row.

> **Normative.** The restart freeze replays no input, resumes no work, writes no
> archive entry and invents no field the record did not hold, other than those the
> clause above names. An activation that died before its admission write still
> leaves no episode.

> **Normative.** Forgetting an episode, or deleting its conversation, while it is
> open deletes the open episode as it deletes a frozen one. The pass's later writes
> then raise `EpisodeNotOpenError`, which degrades capture under §3 and §5 and
> changes nothing else.

> **Normative.** Conversation deletion finds open episodes through the
> conversation's turn rows, exactly as it finds frozen ones, under ADR-0275 §6:6's
> unfiltered enumeration. `ConversationStore` gains no lookup for it and
> `MemoryStore` gains no query by conversation.

### 7. The turn row is written when the conversation is known

> **Normative.** `ConversationTurn` gains `open: bool`, and its `model_eligible`
> becomes `bool | None`, `None` exactly when the row is open. `ConversationStore`
> gains `open_turn`, which allocates the next ordinal and writes an open row naming
> a supplied episode address; `freeze_turn`, which marks a row frozen and writes,
> once, its `model_eligible`, its parked binding where the pass established one,
> and its delivery fact where one is owed; and `open_turns`, which lists every open
> row. `freeze_turn` refuses a row that is absent or already frozen.

> **Normative.** A parked binding written by `freeze_turn` keeps ADR-0074's
> uniqueness across the whole index: a binding another row already holds is
> refused atomically, the row stays open, and capture is degraded. The restart
> freeze of §6 then freezes the row without a binding.

> **Normative.** For an input naming an existing conversation, the pass writes its
> open turn row at admission, before `open_episode`, so the row names the episode
> before it exists. For a new conversation, it writes the row when the begin stage
> allocates the conversation.

> **Normative.** `ConversationStore.turns` excludes open rows unless the new
> keyword `include_open` is `True`. Conversation history and export read frozen
> rows only. `turns_after` returns open rows, and the observer's watermark does not
> advance past a row that is still open.

> **Normative.** `ConversationExport.schema_version` becomes literal `4`.

### 8. What each reader sees of an open episode

> **Normative.** The episode selector (ADR-0276 §4) passes over the pass's own
> episode. Another activation's open episode is in the window on the same terms as
> any other, and the projection renders its status as in progress, its input, and
> no response.

> **Normative.** For the conversation channel, the channel window's tail is
> followed by the other activations' open turns in the conversation, in ordinal
> order, each rendered with its trigger's exact input text or transcript as the
> user's half and marked in progress, with no assistant half. The pass's own turn
> is never in it.

> **Normative.** The planner, the observer, consolidation and export read frozen
> episodes only. Owner inspection (ADR-0275 §10, §11) reads open ones with their
> status.

### 9. What each phase read is saved (#2608)

> **Normative.** `EpisodeProcessingRecord` gains `windows: ActivationWindows | None
> = None`, written by the windows stage: `channel_ids`, the stored ids of the
> channel window's items the audience predicate admitted, in window order; and
> `episode_ids`, the episode window's ids in the selector's order, or `None` where
> the pass takes no episode window.

> **Normative.** `EpisodeProcessingRecord` gains `fetches: tuple[StageFetch, ...] =
> ()`, one entry per stage run that fetched by id under ADR-0282 §2: `stage`, the
> `ControllerStage` that fetched; `fetched`, every id it asked for, in order, each
> once; and `missing`, the ids that returned no record or that the audience
> predicate refused. `fetches` holds at most `STAGE_RECORD_LIMIT` entries.

> **Normative.** Each saved tuple of ids holds at most `SAVED_READ_IDS_MAX`, a
> `core` constant with value **64**. Where more were read, it keeps the first
> `SAVED_READ_IDS_MAX` in order, and a sibling count named for it with the suffix
> `_elided` (`channel_ids_elided`, `episode_ids_elided`, `fetched_elided`,
> `missing_elided`) counts the ids dropped. A window or a fetch is never refused or
> cut short because its saved record is.

> **Normative.** `RecalledItem` gains `score: float`, finite, the search score
> recall kept the item on, as `MemoryStore.search` returned it.

> **Normative.** No saved read carries a record's content. The ids are the stored
> `MemoryBase.id` values exactly as stored.

### 10. Bounds

> **Normative.** While an episode is open, its stage record and understanding
> versions are written through in full. The freeze trims them to ADR-0280 §6:6's
> and ADR-0276 §7:4's shapes, with their elided counts, and the restart freeze
> trims them the same way.

> **Normative.** An open episode takes at most four times `STAGE_RECORD_LIMIT`
> stage entries and four times `UNDERSTANDING_VERSION_LIMIT` understanding
> versions. Past either ceiling, further entries of that kind are held in memory
> only, and the freeze writes them into the trimmed record as though they had been
> written through.

> **Normative.** Each write of the open version is measured against ADR-0275
> §9:1's bound before it is written. A write over the bound is not made and
> degrades capture under §3. The freeze's final check keeps ADR-0275 §8:4's form.

### 11. A turn naming a conversation that does not exist (#2592)

> **Normative.** Where the admission turn-row write is refused because the named
> conversation does not exist, the episode is still written, standalone, with no
> resolved `channel`. Its trigger keeps the target the input named and records the
> new field `context_withheld=True`, with an empty `context`: the context the
> client attached is not stored.

> **Normative.** That episode is processed and frozen as any other: the refusal the
> pass already raises (ADR-0074 §1) chooses its status and reason under ADR-0275 §5.

### 12. The cutover

> **Normative.** `EpisodeProcessingRecord.schema_version` becomes `Literal[5]`,
> and the episode-record format marker (`EPISODE_RECORD_FORMAT`) advances, on
> ADR-0275 §12's mechanism. The conversation index schema changes with §7, and its
> store refuses a pre-change file with `IncompatibleStateError` on the same
> mechanism. No migration, backfill or version-4 read path is a deliverable, and
> the hub moves to a fresh data directory.

> **Normative.** Each change that alters a shape crossing the wire advances
> `PROTOCOL_VERSION` in that change, on ADR-0280 §7:4's rule.
> `ChannelResult.capture`, `TurnOutcome` and `SpokenTurn` carry the episode's
> address.

### 13. Relationship to earlier decisions

> **Normative.** This numbered draft records the scoped replacements in its header
> on each affected ADR's status line and in a dated header note, atomically with
> this ADR under ADR-0070 and ADR-0082, preserving their ratified bodies. The
> replacements take effect on this ADR's ratification.

### 14. Delivery

> **Normative.** Land this ADR ratified before any implementation lane. Then the
> implementation ships as separate PRs in this order:
>
> 1. **`core` with `memory`, the `MemoryStore` contract**: §2, §4 and §9's types,
>    the three members and `EpisodeNotOpenError`, their conformance suite and
>    canonical fake, the sqlite implementation, format 5 and the protocol advance.
> 2. **`core` with `memory`, the `ConversationStore` contract**: §7's fields and
>    members, `include_open`, `open_turns`, their conformance suite and canonical fake, the
>    sqlite implementation, the schema change and export version 4.
> 3. **`orchestration`**: admission, write-through, the freeze, the restart freeze,
>    deletion while open, §8's readers, §9's saved reads, §10's bounds and §11.
> 4. **`interfaces`**: `assistant episode` renders open episodes and §9's saved
>    reads, and the episodes list takes the `open` filter.
> 5. **`core` with `memory`, removal only**: the members lanes 1 and 2 replace, and
>    the unused `ConversationLifecycle.capture` path.
>
> Lanes 1 and 2 are additive: what they add sits beside what it replaces until
> lane 3 stops calling it and lane 5 removes it. Lane 3 depends on lanes 1 and 2,
> and lanes 4 and 5 on lane 3.

> **Normative.** Lane 3's tests assert, through production composition: a speech pass saves its
> transcript into the open trigger, and a failed transcription leaves it `None`; a
> restart after an open episode's expiry finds, freezes and then purges it; a
> restart freezes a turn row whose episode is already frozen, and one whose
> episode never landed; a parked binding written at the freeze is found by its
> binding after a restart; a window of more than `SAVED_READ_IDS_MAX` items saves
> its first ids and the elided count; another
> activation's open episode is in the episode window marked in progress and the
> pass's own is not; recall never returns an open episode; a hub restart freezes
> an open episode as `interrupted` / `hub_stopped` keeping its written entries;
> deleting a conversation mid-pass deletes the open episode and degrades the
> capture; a turn naming an unknown conversation leaves a standalone failed episode
> with `context_withheld=True`; a pass over a cap freezes to exactly today's
> trimmed shape; and §9's saved reads appear in the episode's detail.

> **Normative.** The M36 addition's exit is ruled by the owner on #2613, with the
> tested revisions and live-hub evidence recorded there. A ratified ADR, merged
> lanes or a passing suite alone does not establish it.

## Consequences

- The activation ID and the episode's address are one name from admission.
  Stories (M40), effects (#2584) and notes can point at an episode while its
  activation runs, and M40's members need no change.
- Other channels see in-progress activations through the two windows, which the
  concurrency direction needs.
- A crash after admission leaves an interrupted episode holding everything written
  so far. The wiki's Episodes page, which says a crash may leave no episode, is
  out of date once this is implemented.
- Each stage end costs one local write of the whole open version, bounded by
  ADR-0275 §9:1.
- Turn ordinals follow arrival order, not finish order.
- `hub_stopped` means the hub stopped with the episode still open. It also covers
  an episode whose freeze failed while the hub kept running, until the next start.
- The capture report cannot yet say which of the admission write, a write-through
  or the freeze failed. #1075 asks for that distinction; it stays open.
- Revisit the ceilings of §10 and `SAVED_READ_IDS_MAX` on evidence from live runs.

| Superseded clause | What changes |
| --- | --- |
| ADR-0074 §3 | The turn's episode id is the activation's, supplied by the caller; the store still allocates the ordinal. |
| ADR-0275 §1:3, §1:4 | The episode is the record from admission; the open episode is a live activation log. |
| ADR-0275 §2:2 | The ID and start reading are stored at admission. |
| ADR-0275 §4, §4:9 | New status, reasons, fields and trigger flag; `occurred_at` is the admission reading. |
| ADR-0275 §6:2, §6:3 | Every address is `activation:<id>`; a refused admission row falls back to standalone without context. |
| ADR-0275 §7:5 | The turn's eligibility is set once, at the freeze. |
| ADR-0275 §7:4, §9:6 | The channel window renders other activations' open turns from their exact input. |
| ADR-0275 §8:2, §8:4, §8:6, §8:8, §8:13 | Write-through and the freeze replace capture once; restart freezes open episodes. |
| ADR-0275 §9:1, §9:2 | Each write is bounded; expiry is stamped at admission. |
| ADR-0275 §12:6 | Two store operations change an open episode. |
| ADR-0275 §10:3, §10:9 | An open episode is live whatever its expiry until it is frozen. |
| ADR-0276 §3:1, §4:3 | Windows show other activations' open work, never the pass's own. |
| ADR-0276 §7:1, §7:3 | An open record may carry no understanding yet; versions are written through. |
| ADR-0280 §4:1–§4:2, §6:5, §7:1 | `hub_stopped` rule; entries written through; an open record has no end entry. |
| ADR-0281 §6:1, §6:4, §6:5 | `score` on each item; recall written through; schema 5. |
| ADR-0282 §1:2 | What the phases read is saved. |

## Alternatives considered

**Keep the working episode in memory and save it once, adding #2608's reads.** It
is the cheapest and it is built. But nothing is visible or durable before the end,
and the episode has no name until capture, so every later feature that needs one
would build around that, and the longer that goes on the more there is to undo.

**A separate live journal beside the episode, which is still written once.** It
keeps ADR-0275 §8 intact, at the cost of two records of one activation: readers
would choose between them, and the journal would need its own lifecycle, retention
and deletion copied from the episode's.

**Keep `conv:<cid>:<ordinal>` for conversational episodes.** It gives episodes two
naming schemes, and an activation that starts a new conversation would have no
address until the begin stage, which is after the episode has to exist.

**The capped lists.** Writing the first half as it happens and the tail at the
freeze loses the tail in a crash and hides recent entries from an open reader.
Keeping only the first N drops the latest understanding, which ADR-0276 §7:4 never
drops. Ending the pass at the cap keeps the record strictly append-only but ends
passes that run today and needs a new end reason. Writing in full and trimming at
the freeze changes nothing a reader of a frozen record sees.

**Deleting a conversation mid-activation.** A store query by conversation adds a
second way for deletion to find episodes. Cleaning up at the freeze leaves the
deleted conversation's content readable in the open episode for the rest of the
pass. Cancelling the conversation's running activations first ties deletion to
concurrency work not yet designed. Writing the turn row when the conversation is
known keeps one enumeration and the deletion guarantee throughout.

**A turn naming an unknown conversation.** Deleting the open episode keeps ADR-0275
§6:3's rule whole and leaves #2592 unfixed. Keeping it without the attached context
records the failure while storing only what arrived with this input.
