# 284. An episode is the experience of processing its activation

- Status: Partially superseded by ADR-0285 (the observer's member of §6:2, §8:3 and §8:7) and ADR-0286 (§5:5's validator, for an open record; §6:2's last sentence, for an open episode; §7:1's timing of the content; §7:4's pass, for an open episode; §9:1's values) and ADR-0287 (§5:3's second sentence)
- Date: 2026-10-02
- Scope: [M36](https://github.com/leonapivato/ai-assistant/milestone/2), reopened 2026-09-30 for [#2613](https://github.com/leonapivato/ai-assistant/issues/2613); the second of three steps, the episode's end entry.
- Dependency: ADR-0283, implemented at `f5993b40`.
- Authorization: the owner agreed the definition this ADR rests on in conversation on 2026-10-01, accepted proposal #2624 on 2026-10-02 and directed its conversion into this ADR, ruling the same day that resumes record their stages, that every model-facing rendering of an episode reads one projection, and that what is embedded is a recipe below this decision's invariants. The dispatcher assigned 0284, the next number on `main`. That authorizes drafting and numbering, not ratification or implementation.
- Partially superseded: 2026-10-03 by ADR-0285 — §6:2, §8:3 and §8:7 lose the observer
  from the readers and renderers they name (ADR-0285 §1). Every other member and clause
  stands. These replacements take effect on ratification of ADR-0285. This reciprocal
  header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior
  supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-03 by ADR-0286 — five scopes. §5:5's validator, for an
  open record: it carries no end entry (ADR-0286 §1). §6:2's last sentence, for an open
  episode: the store passes over it on the reads that feed models (ADR-0286 §6). §7:1's
  *the writer sets every processing-record episode's `content` from it*, in when: at
  freeze, and an open episode's `content` is empty (ADR-0286 §1, §4). §7:4's pass, for
  an open episode: the pass leaves it. §9:1's values: `schema_version` is `Literal[6]`
  and the format 7 (ADR-0286 §13). Every other clause stands. These replacements take
  effect on ratification of ADR-0286. This reciprocal header record accompanies the
  numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body
  below are preserved.
- Partially superseded: 2026-10-03 by ADR-0287 — one scope. §5:3's second sentence:
  `ExchangeDisposition` leaves now with the transcript archive, as that sentence foresaw
  (ADR-0287 §2). §5:3's first sentence stands, and so does every other clause. These
  replacements take effect on ratification of ADR-0287. This reciprocal header record
  accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and
  the ratified body below are preserved.
- **Partially supersedes** [ADR-0221](0221-an-episode-carries-the-reply-a-typed-disposition-and-how-the-turn-was-captured.md) — **two scopes.** **§2:1's field**, `EpisodicMemory.disposition`: it is removed, and the step's and the route's verdicts are on their stage entries (§5 below); `ExchangeDisposition` stays, for `TranscriptEntry.disposition` alone, and §2:2–§2:5 stand for it. **§3:1 and §3:2 entire**: every model-facing rendering of an episode reads the one projection in `core`, and the verdict phrases are one table there (§8 below). §3:3 and every other clause stand.
- **Partially supersedes** [ADR-0222](0222-the-stored-reply-is-read-back-in-the-conversation-tail-and-by-the-observer.md) — **three scopes.** **§1:1, §1:2, §2:1 and §3:1, in their condition and their phrase line alone**: *"carries both a `disposition` and an `outcome`"* reads *"carries a response"*, and the line the response line follows is the projection's (§8 below); which records render the response, its ceiling, its elision and its counts stand. **§1:3 entire**: the record line changes. **§2:2 entire**: benchmark prompts change with the planner's record line. Every other clause stands.
- **Partially supersedes** [ADR-0227](0227-a-record-the-citation-hop-reached-renders-its-reply-and-the-test-that-says-so-runs-the-real-renderer.md) — **two scopes.** **§1:1 and §1:2, in their condition and their phrase line alone**, as for ADR-0222 above. **§1:5's last two sentences' byte rule**: the record line changes; the reply line is still emitted by the caller. Every other clause, and ADR-0229's amendments, stand.
- **Partially supersedes** [ADR-0223](0223-a-captured-episode-carries-the-externality-of-the-supply-its-turn-ran-over.md) — **one scope.** **§4:3's last sentence**, that no lane extracts the three prompts' phrases into a `core` mapping: the verdict phrases are one table in `core` beside the projection (§8 below). §4:1 and §4:2's episodic origin phrase stand, rendered from the projection, and §4:3's first sentence stands.
- **Partially supersedes** [ADR-0275](0275-an-episode-records-one-activation-after-processing-ends.md) — **eight scopes.** **§4:1's record shapes**: `EpisodeProcessingRecord` loses `response_kind` and `model_eligible`, renames `reply_degraded` and `spoken_degraded` to `response_degraded` and `output_degraded`, and is `schema_version` 5; `RecordedChannelTrigger` loses `conversation` and gains `origin`; `EpisodeResponseKind` is removed (§2–§4, §6 below). **§4:3 entire**: `outcome` is the response or `None`. **§4:6's first sentence**: admission alone enforces the dispatch table (§3 below). **§7:1–§7:4 entire, and §7:7 in what remains of it**: the eligibility flag and axis are retired (§6 below). **§8:1, in its *rendering/disposition* facts**, and **§8:5 entire**: `content` is derived by one rule (§7 below). **§9:6, for the user's own input alone**: a user's own input text reaches model-facing renderings through the projection, as it reached them through `content` before (§8 below). **§10's `EpisodeSummary.response_kind`**: removed. Every other clause stands.
- **Partially supersedes** [ADR-0276](0276-an-activation-is-understood-before-it-is-associated-and-the-understanding-is-retained-with-its-episode.md) — **three scopes.** **§3:1's *"on ADR-0221's existing rendering"***: a tail record renders through the projection. **§4:6's projection**: it is the projection in `core`, with the same parts and the stage verdicts added. **§4:8's last sentence, in its test**: an episode is rendered as a report received where its trigger's `origin` is `outside`, not where its channel is an event channel. Every other clause stands.
- **Partially supersedes** [ADR-0280](0280-an-activation-controller-runs-the-stages-by-rules-and-records-every-choice-with-the-episode.md) — **four scopes.** **§1:4's last sentence** and **§7:1's resume clause**: a resume records the stages it runs (§5 below). **§6:1's field set and `ControllerRule`, in the additions alone**: `StageEntry` gains two verdict fields and `ControllerRule` gains `park_answered`. **§6:3, for those two fields alone**: a `drive` or `routing` entry carries the verdict it reached. Every other clause stands.
- **Partially supersedes** [ADR-0281](0281-recall-runs-before-understanding-and-understanding-reads-what-it-found.md) — **two scopes.** **§4:4's and §6:3's test**, *"an episode whose trigger arrived on the informational event channel"*: an episode whose trigger's `origin` is `outside`. Every other clause stands.
- **Partially supersedes** [ADR-0283](0283-a-channels-history-is-its-episodes-and-the-turn-index-is-retired.md) — **four scopes.** **§3:1's and §3:2's eligibility axis**: `channel_episodes` takes none, and `total` counts every live episode on the channel. **§4:1's `episode_model_eligible=True`**: history reads every episode. **§7:5's `model_eligible=False`**: the flag does not exist. **§11:1's *"skips ineligible episodes"***: the observer reads every episode of its page. Every other clause stands.

## Context

The owner and the dispatcher agreed on 2026-10-01 what an episode is: **the
experience of processing one activation** — what arrived and how it arrived, what
processing understood, recalled, decided and did, what went out, and how it ended.
Three kinds of thing sit beside an experience rather than in it: indexes derived
from it (its search text), its disclosure, derived from where it arrived and what
processing read, and annotations the world adds afterwards (spoken delivery). The
mechanics of a pass belong to the trace store.

ADR-0283 made a channel's history its episodes. This ADR applies the definition to
the parts of today's episode that name a channel type, carry a read policy, or
restate other fields. The third step, the episode store as the one record, applies
it to the rest, among them the belief-shaped fields an episode inherits from
`MemoryBase`.

What the code shows, at `f5993b40`:

- **The record names channel types.** `EpisodeResponseKind` has the values
  `conversation_reply` and `informational_summary`, and restates the record: `none`
  is an empty `outcome`, a summary is an `informational_event` channel, a reply is
  the rest. Its only reader that branches is the validator pairing it with
  `outcome`. `RecordedChannelTrigger._supported_combination` repeats ADR-0274 §4's
  dispatch table, and every trigger carries `conversation` options that no reader of
  a stored episode reads.
- **Readers test one channel type for who the input came from.** Recall marks an
  episode outside provenance, and keeps its raw input out of excerpts, where the
  channel type is `informational_event`; understanding attributes an input as "a
  report … never something the user said" on that type and as the user's message on
  `conversation`. A second outside channel would be read as the user's own words.
- **The step's verdict is conversational and off the stage.**
  `EpisodicMemory.disposition` is the only record of what became of a step or a
  route, set only where a conversational capture ran. The `drive` stage's entry
  records that it ran, not what it concluded. A resume, which runs the step the user
  approved, records no stages at all (ADR-0280 §1:4).
- **`model_eligible` is a read policy.** ADR-0275 §7 made it a compatibility flag so
  that model reads from before M36 kept seeing what they saw; it is false exactly
  where a pass never reached the conversational capture: every event, cancellation,
  transcription failure, wordless speech and failure before capture. The owner ruled
  on 2026-09-27 that the compatibility is no longer needed.
- **`content` is two things.** For a conversational turn it is a template the engine
  fills at capture (`"The user asked: …"`, the plan's rationale, the selected tool);
  for any other episode it is the latest understanding's meaning or a constant. It
  is embedded and searched, and it is also what the composer, the planner and the
  observer render as the episode, beside a phrase for `disposition`. None of the
  three renders an episode's status, so once failures reach them a failed request
  would read as an ordinary exchange. Understanding's episode window already renders
  an episode from its parts (ADR-0276 §4:6). A disambiguation episode's `content` is
  empty today, because the template has nothing to fill.

## Decision

### 1. What an episode records

> **Normative.** A field is added to `EpisodeProcessingRecord` only where it records
> what arrived and how, what processing understood, recalled, decided or did, what
> went out, or how processing ended. An index derived from the episode, its
> disclosure, and an annotation made after it ended are kept beside it, and a pass's
> mechanics are kept in the trace store.

### 2. Where the input came from

> **Normative.** `core/types.py` gains the closed enum `InputOrigin`, with the values
> `user` and `outside`, and `RecordedChannelTrigger` gains `origin: InputOrigin`.

> **Normative.** Admission sets `origin` from what the channel declares about its
> input, and the value is fixed on the episode. Until channels carry their
> declarations (#2578), the declaration lives with the channel dispatch in
> `core/channel_validation.py`: the conversation channel declares `user`, the
> informational event channel declares `outside`, and a channel type with no
> declaration is refused at admission.

> **Normative.** No reader of a stored episode branches on its channel type. A
> reader that needs to know who the input came from reads `origin`; recall's
> provenance and excerpt and understanding's attribution are such readers.

> **Normative.** A `RecordedResumeTrigger` carries no origin: a resume has no input.

### 3. The trigger records how the input arrived

> **Normative.** `RecordedChannelTrigger.conversation` is removed.

> **Normative.** The trigger's validator checks no combination per channel type.
> Which payloads, reply shapes and options a channel accepts is checked at admission
> by `core/channel_validation.py`, the one dispatch table. Where the trigger's target
> is a `ChannelIdentity` and its `channel` is set, the two are equal.

### 4. The response is what went out on the channel

> **Normative.** `EpisodeResponseKind`, `EpisodeProcessingRecord.response_kind` and
> `EpisodeSummary.response_kind` are removed. `outcome` is the text the activation
> sent back on its channel, nonblank, or `None` where it sent none.

> **Normative.** `reply_degraded` and `spoken_degraded` are renamed
> `response_degraded` and `output_degraded`, with their meanings unchanged.

> **Normative.** The CLI's episode rendering labels an episode by whether it has a
> response, and reads no field this section removes.

### 5. The verdict is part of the stage that reached it

> **Normative.** `StageEntry` gains `step_disposition: Disposition | None = None` and
> `route_outcome: RouteOutcome | None = None`. A validator admits
> `step_disposition` on a `drive` entry alone and `route_outcome` on a `routing`
> entry alone.

> **Normative.** A `drive` entry carries the `Disposition` of the step it drove where
> the step reached one. A `routing` entry carries the `RouteOutcome` of the route it
> took where the route reached one. Every channel records them the same way.

> **Normative.** `EpisodicMemory.disposition` is removed. `ExchangeDisposition`
> remains for `TranscriptEntry.disposition` alone, produced as today from the same
> verdict, and leaves with the archive in the third step.

> **Normative.** A resume records the stages it runs. `ControllerRule` gains
> `park_answered`. A resume's record carries, in order, an entry for the stage that
> continues the parked work — `drive` for a parked step, `routing` for a parked
> routed operation — due `park_answered` and carrying its verdict; an entry for
> `compose` where the resume composes, due `reply_owed`; and one end entry, last,
> due the rule that ended it. A resume that continues no stage records the end entry
> alone.

> **Normative.** The resume path is not run by the controller. It records its
> entries through the stage record the controller uses, under ADR-0280 §6's
> bounds, and the record's validator holds a resume to the rule it holds a channel
> activation to: exactly one end entry, last. A resume still carries no recall
> result (ADR-0281 §6:2).

### 6. `model_eligible` is retired

> **Normative.** `EpisodeProcessingRecord.model_eligible`, `admits_model_eligibility`
> and `check_eligibility` are removed, and `MemoryStore.search`, `MemoryStore.select`
> and `MemoryStore.channel_episodes` lose `episode_model_eligible`.
> `ChannelEpisodePage.total` counts every live episode on the channel.

> **Normative.** Conversation history, retrieval, the loop's reads, structured reads,
> the citation hop and the observer read every episode their reads return, failed,
> interrupted and outside episodes included. A reader that should pass over an
> unfinished or failed episode reads its status.

> **Normative.** The removal of the axis is a breaking Protocol change, shipped as a
> triad: the Protocol, the memory-store conformance suite and the canonical fake
> together.

### 7. `content` is derived by one rule

> **Normative.** `core/episode_encoding.py` gains `episode_content(record:
> EpisodicMemory) -> str`, a pure function of the record's processing record. The
> writer sets every processing-record episode's `content` from it, and nothing else
> composes an episode's `content`: `CaptureFacts.content` and the content lines of
> `_exchange_of` and `_routed_exchange_of` are removed.

> **Normative.** The rule is the same on every channel. It never includes the input
> text of a trigger whose `origin` is `outside`.

> **Normative.** No model is shown an episode's `content` as the episode. It is the
> episode's search text; models are shown the projection (§8).

The rule this ADR starts with is a recipe, not a ruling: the latest understanding's
`meaning`, or, where the activation has no understanding, one line of its status and
reason; followed, where `origin` is `user`, by the input text or transcript. So a
conversational episode is found by its sense and by the exact names and numbers in
the user's words, an outside report by its sense alone, and a disambiguation episode
is no longer empty.

> **Normative.** Changing what `episode_content` derives amends no clause of this
> ADR, provided §7's other clauses hold. Such a change ships with a pass that
> re-derives and re-embeds the `content` of stored episodes, and `content` is the one
> field of a stored episode that pass may rewrite.

### 8. One projection for every model-facing rendering

> **Normative.** `core` gains a frozen `EpisodeProjection` and a pure
> `project_episode(record, *, excerpt_chars: int, admit_outside_input: bool =
> False)`. The projection carries the episode's `occurred_at`; its channel, or its
> capture modality where it has no processing record; its `origin`; its input text,
> where `origin` is `user`, or `outside` and `admit_outside_input` is true; the
> latest understanding's `meaning`, `meaning_ground` and `unresolved`; the stage
> verdicts; its response; its status and reason; and its
> `Provenance.derived_from_external`. Input and response are cut to
> `excerpt_chars`, and the cut is carried in the projection.

> **Normative.** For an episode without a processing record, which ADR-0275 §4:2
> still admits from other producers, the projection's input is the record's
> `content`, as ADR-0276 §4:6 already renders it, and it carries no origin, no
> understanding, no verdict and no status. This is the one path on which a model is
> shown an episode's `content`.

> **Normative.** Every rendering of a stored episode into a model prompt — the
> composer's, the planner's, the observer's and the understanding stage's channel
> and episode windows and its recalled episodes — reads the episode through
> `project_episode` and renders no other field of it. None renders `content` other
> than through the projection's input for an episode without a processing record.

> **Normative.** The composer renders ADR-0223 §4's episodic origin phrase from the
> projection's `derived_from_external`; ADR-0223 §4:1 and §4:2 stand. `origin` and
> `derived_from_external` are different facts — who the input came from, and whether
> processing read material resting on external content — and no renderer derives one
> from the other.

> **Normative.** `admit_outside_input` is true for the understanding stage's episode
> window and its recalled episodes alone, the two renderings ADR-0276 §4:6 and
> ADR-0281 §7:3 admit an outside input's text to, and false for every other caller.

> **Normative.** A rendering states the episode's status and reason, and the phrase
> for each verdict it carries. The phrases are one table in `core`, beside the
> projection, of one phrase per member of `Disposition` and of `RouteOutcome`.

> **Normative.** Which records render their response stays as ADR-0222 and ADR-0227
> rule it, with their condition read as *the record carries a response*: the
> conversation tail, the records the citation hop reached and the observer's batch
> render it, under ADR-0222 §4's ceiling, §5's elision and the counts; the retrieved
> group renders none. Each site keeps its own ceiling constant.

The phrase tables were three because ADR-0221 §3:2 and ADR-0223 §4:3 kept each
subsystem from importing another's. `core` is importable by all three, and a projection every
reader shares is the point of this section; three copies of a table one projection
names would be three places for it to drift.

### 9. The cutover

> **Normative.** `EpisodeProcessingRecord.schema_version` becomes `Literal[5]` and
> `EPISODE_RECORD_FORMAT` advances to 6, on ADR-0275 §12's mechanism. No migration
> or earlier read path is a deliverable, and the hub moves to a fresh data directory.

> **Normative.** Each change that alters a shape crossing the wire advances
> `PROTOCOL_VERSION` in that change.

### 10. Relationship to earlier decisions

> **Normative.** This numbered draft records its scoped replacements on each affected
> ADR's status line and in a dated header note, atomically with this ADR under
> ADR-0070 and ADR-0082, preserving their ratified bodies. The replacements take
> effect on this ADR's ratification.

| Earlier clause | What changes |
| --- | --- |
| ADR-0221 §2:1, §3:1, §3:2 | `disposition` leaves the episode; one projection and one phrase table. |
| ADR-0223 §4:3 | The phrases are one table in `core`. |
| ADR-0222 §1:1–§1:3, §2:1, §2:2, §3:1 | The condition is *carries a response*; the record line is the projection's. |
| ADR-0227 §1:1, §1:2, §1:5 | As ADR-0222. |
| ADR-0275 §4:1, §4:3, §4:6, §7, §8:1, §8:5, §9:6, §10 | The record's shapes; eligibility retired; `content` derived; user input through the projection. |
| ADR-0276 §3:1, §4:6, §4:8 | The projection in `core`; the report test reads `origin`. |
| ADR-0280 §1:4, §6:1, §6:3, §7:1 | Verdicts on stage entries; resumes record their stages. |
| ADR-0281 §4:4, §6:3 | The outside test reads `origin`. |
| ADR-0283 §3:1, §3:2, §4:1, §7:5, §11:1 | No eligibility axis; history and the observer read every episode. |

### 11. Delivery

> **Normative.** Land this ADR ratified before any implementation lane. Then the
> implementation ships as separate PRs in this order:
>
> 1. **`core`, additive**: `InputOrigin` and `RecordedChannelTrigger.origin`,
>    optional until lane 6; the channel declarations; `StageEntry`'s verdict fields
>    and validator; `park_answered` and the resume stage rule; `episode_content`;
>    `EpisodeProjection`, `project_episode` and the phrase table. The record's
>    validator admits a resume with no stages, as today, or with stages ending in
>    exactly one end entry.
> 2. **`orchestration`**: admission sets `origin`; the controller and the resume path
>    record verdicts, and the resume path its stages; the writer sets `content` from
>    `episode_content`; recall and understanding read `origin`; the composer and the
>    understanding windows render through the projection; no read requests
>    eligibility.
> 3. **`planning`**: the planner renders through the projection.
> 4. **`learning`**: the observer renders through the projection, and its system
>    prompt names the projection's lines.
> 5. **`interfaces`**: the CLI's response label.
> 6. **Removal, `core` with `memory` and `testing`, and the last producer references
>    in `orchestration`**: §4's, §5's, §6's and §3's removals and renames; `origin`
>    required; a resume's stages required, ending in exactly one end entry;
>    `schema_version` 5 and format 6.
>
> Lanes 2–5 depend on lane 1, and lane 6 on lanes 2–5.

> **Normative.** Lane 2's tests assert, through production composition: a
> conversational episode's `origin` is `user` and an event's is `outside`; an event
> episode renders as a report received and recall labels it `outside` with no
> channel-type test; a driven step's `drive` entry carries its `Disposition` and a
> routed pass's `routing` entry its `RouteOutcome`; a resume of an approved step
> records a `drive` entry due `park_answered` with its verdict, and one end entry; a
> failed pass on a conversation appears in that conversation's history with its
> status; and `content` is the meaning and the words for a conversational episode,
> the meaning alone for an event, and a status line for a pass with no
> understanding.

> **Normative.** The M36 addition's exit is ruled by the owner on #2613, with the
> tested revisions and live-hub evidence recorded there. A ratified ADR, merged
> lanes or a passing suite alone does not establish it.

## Consequences

- An episode records an activation the same way on every channel. A new channel
  declares where its input comes from, and every reader follows; a new outside
  channel is not read as the user's words.
- What the assistant experienced reaches the observer and the composer whole:
  events, failures and interruptions included, each with its status.
- Every verdict is recorded, on every channel and on a resume, where today only a
  conversational capture keeps one.
- Models see an episode's parts, laid out once, rather than a template written at
  capture. Prompts carrying history grow by a few lines per episode.
- Conversational episodes are searched by their meaning and the user's words rather
  than by the template; outside content by its meaning alone. The recipe can change
  with recall's tuning (#2601) without an ADR.
- The hub moves to a fresh data directory again.
- What follows: the episode store as the one record — episodes kept until forgotten,
  the archive retired, ids everywhere else, forgetting as one delete, the episode
  off `MemoryBase` with its search text and disclosure beside it.

## Alternatives considered

- **Look the origin up from the channel when reading.** Fewer fields, but an
  episode's reading would change with its channel's configuration. The origin is
  how the input was perceived, so it is fixed at admission.
- **Delete the verdict with `disposition`.** Nothing else on the episode records it.
- **Keep the verdict on the episode, renamed.** It would stay a summary of the pass
  beside the stages, where the stage that reached it is its natural place.
- **Keep the renderers on `content`.** Models would be shown a search index as the
  episode, and failures would carry no status.
- **Keep `content` as the user's raw words.** Preserves today's retrieval, but keeps
  a per-channel composition and leaves the disambiguation episode empty.
- **Rule the embedding recipe.** Every tuning of recall would need an ADR; the
  invariants in §7 are what must not drift.
- **Take the episode off `MemoryBase` here.** The full form of the definition, but it
  touches every reader that treats an episode as a memory record, and the third
  step restructures the store anyway.
