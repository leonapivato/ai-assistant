# 283. A channel's history is its episodes, and the turn index is retired

- Status: Partially superseded by ADR-0284 (§3:1's and §3:2's eligibility axis; §4:1's eligibility; §7:5's flag; §11:1's skip) and ADR-0285 (§6:1's and §6:8's `record_observed` member; §6:6; §11:1–§11:3) and ADR-0286 (§1:3's never-changed channel; §7:1's sequence; §7:3's and §7:4's treatment of the episode after a capture failure)
- Date: 2026-10-01
- Scope: [M36](https://github.com/leonapivato/ai-assistant/milestone/2), reopened 2026-09-30 for [#2613](https://github.com/leonapivato/ai-assistant/issues/2613); the first of three steps, the channel.
- Dependency: ADR-0275, ADR-0276, ADR-0280, ADR-0281 and ADR-0282, all implemented at `5d872812`.
- Authorization: the owner accepted proposal #2615 on 2026-10-01 and directed its conversion into this ADR, after ruling in conversation the same day that spoken delivery and the observer are moved with the least work, with no promise of their present behaviour. The dispatcher assigned 0283, the next number on `main`; the earlier draft that used it (#2614) was closed unmerged. That authorizes drafting and numbering, not ratification or implementation.
- Partially superseded: 2026-10-02 by ADR-0284 — four scopes. §3:1's and §3:2's
  eligibility axis: `channel_episodes` takes none, and `total` counts every live
  episode. §4:1's `episode_model_eligible=True`: history reads every episode. §7:5's
  `model_eligible=False`: the flag does not exist. §11:1's *skips ineligible episodes*:
  the observer reads every episode of its page. Every other clause stands. These scoped
  replacements will take effect on ratification of ADR-0284. This reciprocal header
  record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions
  and the ratified body below are preserved.
- Partially superseded: 2026-10-03 by ADR-0285 — the watermark is removed (ADR-0285 §4):
  §6:1's and §6:8's `record_observed` member, §6:6 entire and §11:1–§11:3 entire. Every
  other clause stands. These replacements take effect on ratification of ADR-0285. This
  reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082;
  prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-03 by ADR-0286 — three scopes. §1:3's *written with the
  record and never changed*: an episode whose channel is absent gains it by a later
  write, and its columns are written then; once written they never change (ADR-0286 §3,
  §12). §7:1's sequence: the episode is inserted at admission, and the archive entry and
  `record_turn` follow the write that freezes it (ADR-0286 §4). §7:3 and §7:4, in what
  the writer does to the episode: after a capture failure it deletes the episode
  whatever the conversation's state (ADR-0286 §5). §7:2's verification stands. Every
  other clause stands. These replacements take effect on ratification of ADR-0286. This
  reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082;
  prior supersessions and the ratified body below are preserved.
- **Partially supersedes** [ADR-0074](0074-conversation-is-an-entity-and-every-turn-is-an-episode.md) — **eight scopes.** **§2**, in its rule that a turn's existence *is* its index entry and that `last_turn_at` is set by the append: a turn is an episode on the conversation's channel, and `last_turn_at` is set by `record_turn` (§6 below). **§3's id derivation**, *"A captured episode's id is derived from the turn, not minted"* and the append that allocates, derives and writes: every episode's id is `activation:<activation_id>` (§2 below). **§3's durability**, *"A turn is recorded when its index entry lands"*: a turn is recorded when its episode lands. **§3's resume association**, through the store resolving a binding to its turn: the binding is resolved through the episode that parked it (§5 below). **§5's history read**, *"Turns are read through the index and fetched by id"*: history is the channel's episodes in number order (§4 below). **§7's reclaim**, *"no live turns"*: no live episode on the conversation's channel (§8 below). **§8's index-first protocol**: the index entry written first, step 2's *"deletes every episode the index names"*, step 3's drop of the index, and the rule that a refused append needs no compensation — deletion enumerates the conversation's channel, and the writer's `record_turn` is the verification (§7, §8 below). **§9's turn index and §10–§11's ordinal and membership**: `ConversationTurn`, the ordinal and its invariants, `append`, `turns`, `turns_after`, `turn_of_episode`, `turn_of_binding`, `episodes_to_purge`, the turns in `export`, the binding uniqueness §9.1 asks of `append`, and the rule that membership's one home is the index — membership is the episode's channel. The tombstone, the grace, the per-conversation exclusion over the mutations that remain, and every other clause stand.
- **Partially supersedes** [ADR-0076](0076-stamped-conversations-are-enumerable.md) — **two scopes.** **§1's and §4's naming of `turns`, the two reverse lookups and `episodes_to_purge`**: they are removed (§6 below). **§2's sweep, in its *`episodes_to_purge`* part alone**: the sweep pages the conversation's channel (§8 below). `stamped_conversation_ids` and every other clause stand.
- **Partially supersedes** [ADR-0077](0077-the-observer-proposes-beliefs-from-episodes.md) — **two scopes.** **§1's batch read through `ConversationStore.turns`** and **§8's premise that the index entry is durable and the episode best-effort**: the observer reads the conversation's episodes by number (§11 below). Every other clause stands.
- **Partially supersedes** [ADR-0205](0205-a-spoken-answers-delivery-is-a-fact-the-device-reports-and-an-unreported-answer-is-never-assumed-heard.md) — **one scope, read across fourteen clauses.** **§1:3, §1:6, §1:9, §3:1, §3:3–§3:7, §3:10, §3:11, §4:1, §4:2 and §5:4, in so far as they place the delivery on a `ConversationTurn` index row, write it through `append` or read it off `ConversationStore.turns`**: the delivery is a row the conversation store keys by episode id, written `UNKNOWN` by `record_turn`, stamped by `record_delivery`, which returns whether it stamped, and read by `deliveries` in one further call on the history path (§6, §10 below). The stamped-once rule, the refusals and every other clause stand.
- **Partially supersedes** [ADR-0212](0212-the-observation-cursor-is-a-per-conversation-watermark-on-the-conversation-index.md), [ADR-0218](0218-a-conversation-is-observed-once-it-goes-quiet-and-a-max-age-backstop-bounds-the-wait.md) and [ADR-0220](0220-the-watermark-driven-observation-walk-tiles-contiguously-and-forgoes-the-window-overlap.md) — **one scope each.** **Every clause, in so far as it names a turn ordinal, `ConversationStore.turns`, `turns_after` or `conversations_with_unobserved_turns`, or bounds the watermark by the conversation's highest ordinal**: §11 below substitutes an episode number, `MemoryStore.channel_episodes` and the conversations `recent` lists, and drops the upper bound. Every other clause stands, and parity with their behaviour is not a deliverable (§11 below).
- **Partially supersedes** [ADR-0225](0225-a-transcript-archive-keeps-the-exchange-as-text-and-nothing-but-the-user-reads-it.md) — **six scopes.** **§1:2's ordinal and §10:13 entire**: an entry carries no ordinal. **§2:1's order**: the episode first, then the archive entry, then the verification. **§2:4**: the verification runs when the episode landed, since the archive is not written otherwise. **§2:5's *address the store allocated for that turn* and §3:1's second sentence**: the address is the episode's `activation:<activation_id>`. **§5:1's and §5:4's index**: the reclaim and the deletion sweep are of the conversation's channel. **§7:6's last sentence and §10:12's ordinal clause**: a conversation's own read is by instant, then address. Every other clause stands.
- **Partially supersedes** [ADR-0244](0244-a-confirm-on-a-search-parks-as-a-durable-question-and-the-answer-runs-that-exact-read-once.md) — **one scope.** **§8:5's *"appends to the conversation"***: the resumed turn's episode is written on the conversation's channel (§7 below). Every other clause stands.
- **Partially supersedes** [ADR-0275](0275-an-episode-records-one-activation-after-processing-ends.md) — **nineteen scopes.** **§4:5's last sentence**: a conversational channel names the conversation the episode was written for. **§4:6's last sentence, in its *existing durable association* part**: the association is the parking episode's `links.parks` (§5 below). **§4's record shapes, in the addition alone**: `ActivationLinks.parks`. **§4:9's last sentence**: `occurred_at` is the reading `record_turn` also receives. **§6:2's first sentence**: every episode's address is `activation:<activation_id>`. **§6:3, in its *index* and *append* parts**: finalization writes on that conversation's channel and `record_turn` validates it. **§6:6's first two sentences**: deletion enumerates what the store holds on the conversation's channel through `channel_episode_ids`, and `record_turn` is the verification. **§7:5 entire** and **§7:6 entire**: the flag lives on the episode alone, and history filters there (§4 below). **§7:7's first sentence**: §11 below. **§7:8, in its *index row* part**: the delivery row. **§7:9**: `ConversationExport` carries no turns, at version 4. **§8:2's sequence**: §7 below. **§8:3, in its *index address* and *intent row* parts**, **§8:4 entire** and **§8:9's *final index-ID overhead***: the address is known from admission. **§8:6's *indexed instant***: the reading `record_turn` receives. **§8:8's *index-row address***: `SpokenTurn.episode_id` is the episode's id. **§9:1's *index* write** and **§9:3's *same conversational addresses***: the episode's address. **§12:3's *eligibility field***: the conversation schema is recognised by the format marker. Every other clause stands, §6:6's rule that a filtered history query never becomes the deletion enumeration and §11:6's included.

## Context

ADR-0074 made a conversation an entity and every turn an episode, and gave the
conversation store a **turn index**: one row per turn, holding the ordinal, the
episode's id, `model_eligible`, the parked binding, spoken delivery and, through
the conversation, the observer's watermark. The conversation's history, digest and
export are read from those rows, and its deletion enumerates them. ADR-0074 §9
chose this deliberately: *"The membership relation gets exactly one home"*, and the
index won over a conversation field on the episode.

ADR-0275 then recorded every activation's channel on its episode. A conversational
episode is written with `ChannelIdentity(channel_type="conversation",
instance_id=<conversation_id>)`. So the membership the index records is now on the
episode too, and the index is a second history of the same conversation. Episodes
on any other channel have no index at all, and are named another way
(`activation:<activation_id>` against `conv:<conversation_id>:<ordinal>`).

The two histories are written separately: index entry, archive entry, episode,
then verification (ADR-0275 §8:2). Every crash and deletion between those writes
needed a rule. The first draft of ADR-0283 (#2614) spent seven review rounds on
those rules while making the episode open at admission, and the owner judged the
machinery a sign that one event was being recorded in too many places. The design
discussion on #2613 split the cleanup into three steps: the channel (this ADR), a
channel-generic end entry, and the episode store as the one record. The owner put
the channel first.

What the code shows, at `5d872812`:

- `turn_of_episode` and `ConversationLifecycle.export` have no production caller,
  and `ConversationLifecycle.capture` is dead; `ActivationWriter` is the producer.
- The parked binding is on the turn row alone. The episode that parked a step does
  not record it; only a resumed episode records the binding it continues, in
  `ActivationLinks.parked`.
- The memory store's `records` table has `rowid INTEGER PRIMARY KEY AUTOINCREMENT`,
  never reissued, and no channel column; `MemoryStore.episodes` filters channel
  through `json_extract`.
- The observer is wired and scheduled. The owner judges it not to work as intended
  today, and its redesign is planned (#2528). Spoken delivery is likewise judged not
  to work end to end.

## Decision

### 1. Episodes are numbered, and indexed by channel

> **Normative.** The memory store gives every episodic record, when it inserts it,
> a **number**: a positive integer from one counter shared by every record the
> store holds, greater than every number it issued before, never reissued and never
> changed.

> **Normative.** A channel's order is its episodes' numbers, ascending. No reader
> orders a channel's history by timestamp or by id.

> **Normative.** The store keeps an episodic record's channel type, channel
> instance and number as indexed columns written with the record and never changed,
> and no read this ADR adds filters a channel through the record's JSON.

Episodes are still written once, when processing ends (ADR-0275 §8), so the
numbers follow the order passes finished in, as ordinals do today. The sqlite
store's `rowid` already has the counter's properties.

### 2. The episode's id is the activation's

> **Normative.** Every episode's id is `activation:<activation_id>`, on every
> channel, conversational and resumed episodes included. No component derives an
> episode's id from a conversation or an ordinal.

> **Normative.** The id is fixed at admission. Preflight sizing, the capture
> report, `SpokenTurn.episode_id` and `ActivationLinks.predecessor_episode_id`
> carry it, and no placeholder address is sized or reported.

### 3. Three memory-store reads

> **Normative.** `MemoryStore` gains `channel_episodes(channel: ChannelIdentity, *,
> after: int | None = None, limit: int, episode_model_eligible: bool | None = None)
> -> ChannelEpisodePage`. It reads the live episodes whose channel is `channel`,
> applies the eligibility axis as `search` does before any limit, and returns, in
> number order ascending, the newest `limit` of them when `after` is `None`, or the
> oldest `limit` numbered above `after` otherwise.

> **Normative.** `ChannelEpisodePage` carries `entries: tuple[ChannelEpisode,
> ...]` and `total: int`, the count of live episodes on the channel matching the
> eligibility axis; `ChannelEpisode` carries `number: int` and `record:
> EpisodicMemory`. `limit` is a strict integer in `[1, 1000]` and `after` a strict
> positive integer; other values raise `ValueError` before any I/O.

> **Normative.** `MemoryStore` gains `episode_parking(binding: ParkedBinding) ->
> EpisodicMemory | None`: the lowest-numbered live episode whose
> `processing_record.links.parks` equals `binding`, or `None`.

> **Normative.** `ActivationLinks` gains `parks: ParkedBinding | None = None`, the
> binding the activation's own step parked. The writer sets it from the pass's
> parked binding. `ActivationLinks.parked` keeps its meaning, the binding a resumed
> activation continues.

> **Normative.** `MemoryStore` gains `channel_episode_ids(channel: ChannelIdentity,
> *, after: int | None = None, limit: int) -> tuple[ChannelEpisodeId, ...]`, the
> enumeration of what the store physically holds on a channel: the number and id of
> every episodic record whose channel is `channel`, expired, not yet valid or
> ineligible included, the lowest `limit` numbered above `after` (or from the start
> where `after` is `None`), in number order. It returns identifiers alone, never a
> record's content; `limit` and `after` are bounded as `channel_episodes` bounds
> them.

> **Normative.** The three reads, their result types and `ActivationLinks.parks`
> are a breaking Protocol change, shipped as a triad: the Protocol, the memory-store
> conformance suite and the canonical fake together.

### 4. History, digest and export read episodes

> **Normative.** `ConversationLifecycle.history` reads the conversation's channel
> with `channel_episodes`, the replay bound as `limit` and
> `episode_model_eligible=True`, after a `get` that returns nothing for a stamped
> or absent conversation. It reads no turn from the conversation store.

> **Normative.** The digest's `recorded_turns` is the `total` of an unfiltered
> `channel_episodes` read of the conversation's channel, and its `last_turn_at` is
> the conversation's own.

> **Normative.** `ConversationExport` carries the conversations alone, with
> `schema_version` the literal `4`.

### 5. A resumed read finds its conversation through the parking episode

> **Normative.** A resume with a binding resolves its conversation as the channel
> instance of `episode_parking(binding)` where that episode's channel is a
> conversation, and relates that episode's id as its predecessor. Where the read
> returns `None`, or the conversation is stamped or absent, the resume keeps
> ADR-0275 §6:5's degraded, no-episode behaviour.

### 6. The conversation store keeps the conversation

> **Normative.** `ConversationStore` keeps `start`, `get`, `mark_active`,
> `record_delivery`, `record_observed`, `stamped_conversation_ids`, `recent`,
> `stamp_deleted`, `drop_if_eligible` and `export`, and gains `record_turn` and
> `deliveries`. It loses `append`, `turns`, `turns_after`, `turn_of_episode`,
> `turn_of_binding`, `episodes_to_purge` and `conversations_with_unobserved_turns`,
> and `ConversationTurn` is removed from `core`.

> **Normative.** `record_turn(conversation_id, *, episode_id, occurred_at,
> delivery: SpokenDelivery | None = None) -> Conversation | None`, as one step under
> the per-conversation exclusion, returns `None` and writes nothing where the
> conversation is absent or stamped deleted. Otherwise it sets `last_turn_at` to
> `occurred_at`, writes the delivery row for `episode_id` where `delivery` is given,
> and returns the conversation.

> **Normative.** `record_turn` refuses, with `ValueError` before any I/O, a
> `delivery` whose state is not `UNKNOWN`.

> **Normative.** `record_delivery(conversation_id, *, episode_id, delivery) ->
> bool` stamps the delivery row the conversation holds for `episode_id` where its
> state is `UNKNOWN`, and otherwise writes nothing and returns `False`. It keeps
> ADR-0205 §3:4's two refusals and §3:7's `ValueError`.

> **Normative.** `deliveries(conversation_id, *, episode_ids) -> Mapping[str,
> SpokenDelivery]` returns the delivery rows the conversation holds among at most
> 1000 `episode_ids`, and an empty mapping for a stamped or absent conversation.

> **Normative.** `record_observed` takes an episode number. It refuses a value
> below the recorded one, as today, and no longer bounds it by the conversation's
> turns. A stored watermark that is not a positive integer is discarded on read.

> **Normative.** `drop_if_eligible` keeps its grace and retention conditions and
> drops the conversation's record with its delivery rows. Whether the conversation's
> channel is empty is its caller's question, asked of the memory store (§8).

> **Normative.** The per-conversation exclusion covers `mark_active`,
> `record_turn`, `record_delivery`, `record_observed`, `stamp_deleted` and
> `drop_if_eligible`.

### 7. Writing a conversational episode

> **Normative.** A conversational finalization writes the episode, insert-if-absent,
> then the archive entry where one is owed, then `record_turn` with the episode's
> `occurred_at` and, on `converse_spoken`, `UNKNOWN` delivery. Standalone
> finalization writes the episode alone.

> **Normative.** `record_turn` is the deletion verification. Where it returns
> `None`, the writer deletes the episode, discards the archive entry, and reports
> the capture degraded; ADR-0275 §8:11's drain applies to this path.

> **Normative.** Where the episode write fails with an outcome known not to have
> committed, the writer writes no archive entry and calls no `record_turn`, and
> reports the capture degraded.

> **Normative.** Where the episode write's outcome is indeterminate, cancellation
> and timeout included (ADR-0060 §1), the writer writes no archive entry, re-reads
> the conversation, and deletes the episode by its id where the conversation is
> stamped or absent; it reports the capture degraded, and ADR-0275 §8:11's drain
> applies to this path.

> **Normative.** A conversational pass that ends before capture still writes its
> episode on the conversation's channel, with `model_eligible=False`, where a turn
> row was written before.

### 8. Deletion and reclaim sweep the channel

> **Normative.** Deleting a conversation stamps it, discards its archive entries,
> drops its parked reads, then deletes every episode `channel_episode_ids` returns
> for its channel, page by page until a read is empty, then calls
> `drop_if_eligible`. No read filtered by liveness, validity or eligibility is the
> deletion enumeration. Recovery repeats the same steps for every
> stamped conversation, at start and on schedule, as today.

> **Normative.** Reclaim drops a conversation idle past the horizon only where
> `channel_episode_ids` returns nothing for its channel, so an expired episode not
> yet purged, or one not yet valid, delays it.

### 9. The archive is addressed by episode id

> **Normative.** `TranscriptEntry` carries no ordinal. Its address is the episode's
> id, and the archive reads a conversation's entries by instant ascending, then
> address.

> **Normative.** The CLI renders a transcript entry's instant where it rendered its
> ordinal.

### 10. Spoken delivery, at the least cost

> **Normative.** History reads `deliveries` for the episodes it returns and pairs
> each with its episode, as ADR-0205 §5 pairs the fact from the turn row. That is
> one more conversation-store call on the history path.

> **Normative.** No test owed by this ADR asserts spoken delivery end to end. The
> conformance suite asserts §6's operations.

### 11. The observer, at the least cost

> **Normative.** The observer's watermark is an episode number. A pass reads the
> conversation's channel with `channel_episodes`, `after` the watermark, or the
> tail where there is none, and `limit` its batch size, skips ineligible episodes,
> and advances the watermark with `record_observed` to the highest number in the
> page.

> **Normative.** The observer's candidates are the conversations `recent` returns,
> bounded as today, whose channel holds an episode above the watermark; its age and
> fill tests read that page where they read turns.

> **Normative.** Parity with ADR-0212, ADR-0218 and ADR-0220's behaviour beyond
> these substitutions is not a deliverable, and no test owed by this ADR asserts
> observer behaviour beyond the read and the advance.

### 12. The cutover

> **Normative.** `EPISODE_RECORD_FORMAT` advances to 5 in the memory store and the
> conversation store, on ADR-0275 §12's mechanism. No migration or version-4 read
> path is a deliverable, and the hub moves to a fresh data directory.

> **Normative.** Each change that alters a shape crossing the wire advances
> `PROTOCOL_VERSION` in that change.

### 13. Relationship to earlier decisions

> **Normative.** This numbered draft records its scoped replacements on each
> affected ADR's status line and in a dated header note, atomically with this ADR
> under ADR-0070 and ADR-0082, preserving their ratified bodies. The replacements
> take effect on this ADR's ratification.

| Earlier clause | What changes |
| --- | --- |
| ADR-0074 §2, §3, §5, §7, §8, §9–§11 | The index goes; history, membership and deletion are the channel's episodes; the id is the activation's. |
| ADR-0076 §1, §2, §4 | The removed operations leave the suite; the sweep pages the channel. |
| ADR-0077 §1, §8 | The observer reads episodes by number. |
| ADR-0205 (fourteen clauses) | Delivery is a row keyed by episode id. |
| ADR-0212, ADR-0218, ADR-0220 | Ordinals become episode numbers; behaviour parity is not owed. |
| ADR-0225 §1:2, §2, §3:1, §5, §7:6, §10 | No ordinal; the episode first; the address is the episode's. |
| ADR-0244 §8:5 | The resumed episode is written on the channel. |
| ADR-0275 §4, §6, §7, §8, §9, §12 | As the header lists. |

### 14. Delivery

> **Normative.** Land this ADR ratified before any implementation lane. Then the
> implementation ships as separate PRs in this order:
>
> 1. **`core` with `memory`, the `MemoryStore` contract**: §1's numbers and
>    columns, §3's three reads, types and `ActivationLinks.parks`, their conformance
>    suite and canonical fake, the sqlite and in-memory stores, and format 5.
> 2. **`core` with `memory`, the `ConversationStore` contract, additive**:
>    `record_turn`, `deliveries` and the delivery rows, with `record_delivery`
>    stamping a delivery row where one exists and a turn row otherwise; the
>    conformance suite, the canonical fake and the sqlite store.
> 3. **`core` with `archive`, additive**: `TranscriptEntry.ordinal` becomes
>    optional and the conversation read orders by instant, then address.
> 4. **`orchestration`**: §2's id, §4, §5, §7, §8, §10 and §11.
> 5. **`interfaces`**: §9's rendering.
> 6. **`core` with `memory`, removal**: §6's removed operations, `ConversationTurn`,
>    the turn-row path of `record_delivery`, the export's turns and version 4.
> 7. **`core` with `archive`, removal**: `TranscriptEntry.ordinal`.
>
> Lanes 1–3 are additive and independent. Lane 4 depends on them, lane 5 on lane
> 3, and lanes 6 and 7 on lane 4.

> **Normative.** Lane 4's tests assert, through production composition: a
> conversational episode's id is `activation:<activation_id>` and its channel names
> the conversation; history returns the channel's eligible episodes in number
> order within the replay bound; a pass that ends before capture is on the channel
> and absent from history; a resume finds its conversation through the parking
> episode, and degrades where none is live; deleting a conversation deletes every
> episode on its channel, eligible or not, expired but unpurged, or not yet valid;
> an episode write that commits and then propagates cancellation, on a conversation
> deleted meanwhile, leaves no episode; a conversation deleted while a pass runs
> ends with neither that pass's episode nor its archive entry, and a degraded
> capture; reclaim keeps a conversation whose channel holds a live episode; and the
> digest counts the channel's episodes.

> **Normative.** The M36 addition's exit is ruled by the owner on #2613, with the
> tested revisions and live-hub evidence recorded there. A ratified ADR, merged
> lanes or a passing suite alone does not establish it.

## Consequences

- A conversation's history, membership and deletion have one source, the
  episodes. The conversation store holds the conversation and two small facts
  about it: delivery rows and the observer's watermark.
- Every episode is named the same way, so nothing outside the episode store needs
  to know an episode exists before it is written.
- A crash after the episode lands and before `record_turn` leaves the episode on
  its channel without `last_turn_at` moving. Where the conversation was stamped in
  that window, recovery's sweep finds the episode while the tombstone stands. Where
  `drop_if_eligible` also ran in that window, the episode names a conversation that
  no longer exists, and lives until its retention expires. Step three, which opens
  the episode at admission, closes this.
- A crash after the episode lands and before the archive write leaves no archive
  entry for that turn; the episode keeps the text until it expires.
- The observer and spoken delivery may stay broken. Their redesigns (#2528 for the
  observer) build on episodes by number rather than on turn rows.
- The archive renders instants rather than turn numbers.
- What follows, each its own proposal after this is implemented: a channel-generic
  end entry (`response_kind` derived, `model_eligible` retired, the step verdict
  moved onto the execution stage's entry, `content` built the same way on every
  channel), then the episode store as the one record.

## Alternatives considered

- **Keep the turn index and fix the write order** (#2614). It converged, but kept
  two histories and the crash and deletion rules between them. Rejected.
- **Order history by timestamp.** Ties and clock steps reorder history. Rejected.
- **A counter per channel.** Gap-free positions within a channel, but every write
  must read and lock its channel's last number. One store-wide counter orders every
  channel the same way, and the sqlite store already has one. Rejected.
- **Find the parking episode through `ActivationLinks.parked`.** That field means
  the binding a resumed activation continues; giving it a second meaning would make
  the resumed episodes and the parking one indistinguishable. Rejected for a new
  field.
- **Keep the ordinal in the archive** by reading the episode's number back after
  the write. One more read for a store step three retires. Rejected.
- **Put delivery on the episode.** It arrives after the episode is written, and
  episodes are written once. Rejected.
