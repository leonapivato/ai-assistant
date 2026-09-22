# 275. An episode records one activation after processing ends

- Status: Partially superseded by ADR-0276 (§1's "automatic cross-channel continuity" exclusion; §4's `EpisodeProcessingRecord` field set and `ProcessingReason` values, in the additions alone; §7's eligibility-`True` rule on automatic model-facing reads, for the understanding stage's episode window alone; §9's exclusion of the trigger's raw input text from automatic model inputs, for that window alone)
- Date: 2026-09-18
- Scope: [M36](https://github.com/leonapivato/ai-assistant/milestone/2), [#2522](https://github.com/leonapivato/ai-assistant/issues/2522).
- Dependency: ADR-0274 and [M35](https://github.com/leonapivato/ai-assistant/milestone/1).
- Partially superseded: 2026-09-22 by ADR-0276 — four narrow scopes. §1's exclusion list
  loses one item, "automatic cross-channel continuity", for a bounded window of recent
  episodes read into one understanding call; §4's `EpisodeProcessingRecord` moves to
  `schema_version` `2` and gains `understanding`, `understanding_omitted` and `understanding_elided`,
  and `ProcessingReason` gains `understanding_failed`, every existing field, value and
  validator standing; §7's rule that all automatic model-facing episodic reads request
  eligibility `True` does not bind that window, every other read keeping it; and §9's
  exclusion of the trigger's raw input from automatic model inputs is lifted for that
  window and for the exact input text or transcript alone — attached context and every
  other raw or inspection-only field stay excluded. §8's capture-once rule, §10 and §11's
  inspection reads and every other section stand entire. These scoped replacements take
  effect on ratification of ADR-0276, which remains Proposed. This reciprocal header
  record accompanies the numbered draft under ADR-0070 and ADR-0082; the ratified body
  below is preserved.
- Authorization: the owner endorsed the proposal's direction and its interruption/parallelism fit, then requested this draft in clone `ai-assistant-2`. The owner assigned the next available ADR number, 0275. These instructions authorize drafting and numbering, not ratification or implementation.

## Context

M36's agreed unit is the input that activated the assistant, its source and
attached context, any response, and the processing outcome. Capture occurs
after processing ends. Conversation ownership is optional; live progress,
phase/tool histories, observer redesign and cross-channel model continuity are
excluded. The owner additionally asked for a general fit for interruptions and
parallelism without deciding their full policies.

The baseline inspected for this draft is `a42cff6c`. ADR-0274's receiver is
implemented there. `Engine._receive` and `Engine._dispatch_channel` in
`orchestration/engine.py` validate and dispatch channel inputs. The
`ResolvedChannelInput` in `orchestration/channels.py` retains source, modality
and supplied context per call. `InformationalEventStage.process` in
`orchestration/informational_events.py` returns a summary without writing it.

`ConversationLifecycle.capture` in `orchestration/conversations.py` writes the
conversation index, optional archive entry, and episode, then checks deletion.
The index allocates the episode address. `Engine._capture` supplies a legacy
rendering, reply and disposition; speech calls it before synthesis finishes.
`EpisodicMemory.outcome` in `core/types.py` means reply text, not processing
status. The owner declared all existing development state disposable and chose a fresh
data-directory cutover; reconstructing or migrating old records is out of scope.

The episode itself already lives in `MemoryStore`, independent of conversation
membership. ADR-0074 §3 deliberately makes the index the owner of membership;
it does not make every episode a conversation turn. Extending that record
preserves the current evidence-address scheme and data lifecycle. The cost is
explicit compatibility for consumers that previously saw only conversational
capture: failed/event records must not enter prompts or displace history merely
because they share the episodic kind.

## Decision

### 1. Status, scope, and terminology

> **Normative.** This document remains `Proposed` until the owner authorizes
> ratification after reviewing the completed contract; an assigned number,
> successful automated reviews, or approval of the earlier proposal alone does
> not authorize that status change.

> **Normative.** No implementation, canonical fake included, implements these
> changed contracts until a numbered, ratified ADR has merged separately under
> ADR-0015 §5. This draft changes no production code and dispatches no lane.

> **Normative.** An activation is one admitted input and its processing pass;
> its episode is the post-processing record. Neither requires a conversation,
> goal, response destination, or successful world action.

> **Normative.** M36 records input, attached channel context, produced text and
> processing outcome. It adds no live activation log, phase/tool history,
> scheduler, new production channel, goal association policy, observer
> scheduling policy, archive retrieval by a model, or automatic cross-channel
> continuity.

### 2. Admission and the end of a pass

> **Normative.** A channel activation starts once the receiver has snapshotted
> and validated its complete supported input/reply combination, checked the
> applicable input/audio bounds and required configured seams, and admitted the
> call to engine tracking. Validation or shutdown refusal before that point
> creates no episode and persists no rejected input.

> **Normative.** Allocate one opaque activation ID and take one injected-clock
> start reading at admission; retain them in call-local state, with no durable
> start row. ID/clock failure is a capture degradation and must not discard
> otherwise admissible processing; an incomplete activation envelope cannot be
> persisted and its report carries an absent activation ID where allocation failed.

> **Normative.** Transcription, optional playback-report application,
> conversation resolution/allocation and existing processing occur inside the
> admitted channel activation. A speech failure or no-words transcription can
> therefore have a record without allocating a new conversation.

> **Normative.** A pass ends after its processing and applicable speech
> synthesis decisions finish, or when it returns an outstanding
> question, raises, or acknowledges cancellation. Take its end reading then and
> perform §8's finalization once, before returning the result or propagating the
> original failure. Do not wait for a future answer to a question.

> **Normative.** Model retries, planning iterations, pulled readings, tool calls
> and internal continuations performed under that admission remain inside the
> same activation. A later admitted channel input starts another activation,
> including one answering a clarification.

> **Normative.** Preserve the existing non-channel `resume` surface. A call that
> resolves a valid unsettled park is a control activation with §4's control
> input, even after restart. An invalid token, pre-resolution validation refusal,
> or restatement of an already settled answer starts no control activation and
> retains its existing no-capture behavior. No other administrative operation or
> scheduler job becomes an activation here.

The distinction for `resume` avoids changing ADR-0198's idempotent restatement
into another exchange. The channel receiver still records an admitted channel
input that happens to request information about already settled work.

### 3. Parallelism and interruption

> **Normative.** Activation lifetimes may overlap, within one channel or across
> channels, and may finish out of arrival order. Input, context, processing
> facts, response and capture state remain with their own activation; no mutable
> assistant-wide current-activation slot supplies them to another call.

> **Normative.** Channel equality establishes neither causal relationship nor
> ownership of ongoing work. Multiple activations may refer to one goal, but
> that relation grants no concurrent-write permission and bypasses no existing
> claim, execution, permission or deletion fence.

> **Normative.** Stopping presentation, interrupting processing, and pausing or
> cancelling broader work are distinct. A stream disconnection alone follows
> ADR-0173 §9's completion rule. Only cancellation that actually ends processing
> records `interrupted`; interrupting a pass neither undoes committed effects nor
> implicitly changes its goal's lifecycle.

> **Normative.** A later resumption is a new activation and never rewrites the
> earlier episode's processing history. Use only relationships established by
> existing processing, never adjacency or the most recently finished episode,
> to associate it. Existing observer annotations and playback reports retain
> their separate mutation rules.

> **Normative.** This decision does not choose scheduling, preemption,
> shared-work serialization, interruption priorities, or new cancellation
> controls. Implementations must not infer that every new input interrupts the
> previous one or that admitting parallel calls makes shared work safe to mutate.

An essay and a cooking question can run in parallel or the cooking question can
follow interruption of the essay pass. Both produce independent episodes. A
later return to the essay uses surviving work state; these records do not
decide which policy should have interrupted it.

### 4. Public record shapes

> **Normative.** Add the following models and aliases to `core/types.py`.
> New models are frozen pydantic models with `extra="forbid"`; the tables define
> complete field sets, literal tags default to their listed values, and other
> defaults are explicit. Reuse existing scalar validators and typed immutable
> tuples; snapshot nested caller-owned data before the first processing await.

| Model | Fields |
| --- | --- |
| `RecordedTextInput` | `modality: Literal[Modality.TEXT]`; `text: EncodableText` |
| `RecordedSpeechInput` | `modality: Literal[Modality.SPEECH]`; `media_type: SpokenAudioFormat`; `transcript: EncodableText \| None` |
| `RecordedChannelTrigger` | `kind: Literal["channel_input"]`; `target: ChannelTarget`; `channel: ChannelIdentity \| None`; `payload: RecordedChannelPayload`; `context: ChannelContext`; `conversation: ConversationInputOptions \| None`; `reply: ReplyCapability \| None` |
| `RecordedResumeTrigger` | `kind: Literal["resume"]`; `channel: ChannelIdentity \| None`; `approved: bool`; `remember_recipients_until: UtcInstant \| None = None` |
| `ActivationLinks` | `predecessor_episode_id: Identifier \| None = None`; `question_id: Identifier \| None = None`; `read_park_id: Identifier \| None = None`; `parked: ParkedBinding \| None = None`; `goal_id: Identifier \| None = None`; `attempt_id: Identifier \| None = None` |
| `EpisodeProcessingRecord` | `schema_version: Literal[1]`; `activation_id: Identifier`; `started_at: UtcInstant`; `ended_at: UtcInstant`; `trigger: RecordedActivationTrigger`; `status: ProcessingStatus`; `reason: ProcessingReason`; `response_kind: EpisodeResponseKind`; `reply_degraded: bool = False`; `spoken_degraded: bool = False`; `model_eligible: bool`; `links: ActivationLinks =` a fresh empty value |
| `EpisodeCaptureReport` | `activation_id: Identifier \| None`; `episode_id: Identifier \| None`; `state: Literal["recorded", "degraded"]` |

| Alias or enum | Complete values |
| --- | --- |
| `RecordedChannelPayload` | `RecordedTextInput \| RecordedSpeechInput`, discriminated by `modality` |
| `RecordedActivationTrigger` | `RecordedChannelTrigger \| RecordedResumeTrigger`, discriminated by `kind` |
| `ProcessingStatus` | String values `completed`, `waiting`, `failed`, `interrupted` |
| `EpisodeResponseKind` | String values `none`, `conversation_reply`, `informational_summary` |
| `ProcessingReason` | String values `returned`, `no_content`, `confirmation`, `clarification`, `disambiguation`, `timeout`, `transcription_failed`, `composition_failed`, `output_oversized`, `processing_failed`, `internal_error`, `cancelled` |

> **Normative.** Add `EpisodicMemory.processing_record:
> EpisodeProcessingRecord | None = None`; absence denotes an episode from
> another supported producer, not a historical-migration promise or a record
> whose missing activation fields may be inferred from text. Keep `outcome`, `disposition`, `capture` and all existing field meanings
> except the explicitly added informational-summary role below.

> **Normative.** For a processing record, `response_kind=none` requires
> `EpisodicMemory.outcome=None`; either other kind requires nonblank encodable
> text in `outcome`. That is the sole stored response text. A conversational
> reply and an informational adapter summary remain distinguishable; no new
> nested field stores a second copy. Episodes without a processing record retain their existing validators.

> **Normative.** A channel trigger preserves exact admitted text and supplied
> context, separately from normalized planning text and legacy `content`.
> For speech it keeps the exact transcript if obtained; `None` means none was
> obtained, while an empty or whitespace-only value records that exact no-words
> transcript. Persist no original audio, synthesized audio, audio hash, or token.

> **Normative.** Preserve the original target even when it is
> `NewConversation`. Set the stored resolved `channel` only from the accepted
> event identity or successful conversation lifecycle/capture resolution; never
> report an unvalidated conversational target as resolved. A non-`None`
> conversational channel must name the conversation indexing that episode.

> **Normative.** Recorded channel shapes obey ADR-0274's admitted combination
> rules with speech bytes replaced by the descriptor/transcript; a resume
> trigger has no invented channel-input envelope or user utterance. Its channel
> is recovered from the existing durable association, never supplied by the
> continuation caller.

> **Normative.** References in `ActivationLinks` are identifiers already
> established by processing. A predecessor is supplied only by a resolved
> explicit reference or durable parked binding; sharing a goal alone supplies
> no predecessor. Absence and dangling references remain legible, and no lookup
> on their authority recreates deleted material or grants permission.

> **Normative.** Record raw attached context without fetching its local item
> IDs or assigning model roles. Do not add retrieved memory, plans, tool
> histories, provider diagnostics or context-provider state to this snapshot.

> **Normative.** `started_at` and `ended_at` are injected UTC readings, not a
> monotonic duration. Do not reject reversed readings after a wall-clock
> adjustment or use them as a proof of causal order. Existing `occurred_at`
> remains the single capture-time reading shared with the conversation index.

### 5. Response and outcome classification

> **Normative.** Preserve the whole composed reply or informational summary,
> including a partial text that was the whole of what a failed stream produced.
> Persist no silent prefix, summary or elision in its place. The episode records
> produced text, not whether a client received or a person heard it.

> **Normative.** Routed data accounts/listings remain excluded under ADR-0197
> §10. Their disposition and established references may be recorded, alongside
> the composed conversational text, but this episode is not a duplicate of every
> data view the interface rendered. Spoken fixed park prompts remain delivery
> behavior, not a fabricated composed reply.

> **Normative.** The engine selects status and reason from the actual terminal
> branch according to the following ordered table. It does not infer them from
> model text, conflate them with `ExchangeDisposition`, or use `completed` to
> assert goal achievement or successful execution of every requested action.

| Priority | Observed end condition | Status / reason |
| --- | --- | --- |
| 1 | Cancellation actually ended processing | `interrupted / cancelled` |
| 2 | A processing deadline expired, or a classified provider timeout ended the pass | `failed / timeout` |
| 3 | Transcription failed with a non-timeout classified failure | `failed / transcription_failed` |
| 4 | Public output could not fit after the existing permitted audio degradation | `failed / output_oversized` |
| 5 | Owed reply composition failed, including a partial stream or enforced stream ceiling | `failed / composition_failed` |
| 6 | Another declared operational error, or an existing returned routed `FAILED` outcome | `failed / processing_failed` |
| 7 | An unexpected exception ended processing | `failed / internal_error` |
| 8 | An outstanding returned read/step/routed confirmation | `waiting / confirmation` |
| 9 | An outstanding returned clarification | `waiting / clarification` |
| 10 | An existing goal-disambiguation result asks the user to choose | `waiting / disambiguation` |
| 11 | Speech produced no words | `completed / no_content` |
| 12 | Any other ordinary result, including a denial, unsupported capability, abandoned goal, or informational summary | `completed / returned` |

> **Normative.** A branch uses the most specific applicable failure reason
> above. Capture failure itself changes no processing status. Retain established
> question/work links when a failure takes precedence over waiting, and do not
> fabricate a durable question ID for an unpersisted disambiguation.

> **Normative.** Optional retrieval loss or failed synthesis with an otherwise
> usable required text result keeps the ordinary completed/waiting status with
> the existing degradation facts. Copy `reply_degraded` and `spoken_degraded`
> from production results; neither is a playback receipt or a capture flag.

> **Normative.** Store no exception message, traceback, arbitrary exception
> class string, provider body or continuation token in status/reason fields.
> The original outward exception and cancellation semantics remain intact;
> recording `internal_error` does not swallow or translate the exception.

### 6. Identity, origin, and deletion

> **Normative.** Use injected UUID4 generation for activation IDs, validated as
> canonical lowercase UUID text before use; no caller supplies the ID. Repeated
> submissions receive different IDs even if channel, text and clock readings
> coincide. Internal provider retry retains the same ID. This is not an
> idempotency key, admission ledger, receipt-replay or exactly-once mechanism.

> **Normative.** Conversation capture retains the episode address allocated by
> `ConversationStore.append` under its current address scheme. Standalone
> capture uses `activation:<activation_id>`; reserve that namespace to this
> capture producer. Consumers treat both addresses as opaque and never derive
> membership from their spelling. A collision fails capture without overwrite,
> a new address, a processing retry or a second insert attempt.

> **Normative.** If a conversation was allocated during the pass or the input
> targeted an existing conversation, finalization must use that conversation's
> index. Even a no-words/failed speech pass naming a conversation attempts a
> capture-only append there; append validates existence atomically. Its refusal
> degrades capture and does not change the no-words result into an unknown-
> conversation exception. Do not fall back to standalone storage after refusal.

This adds a recording-time existence check for no-words input naming a
conversation, while preserving no allocation and the public empty speech
shape. It is the deliberate compatibility change that prevents an unknown or
deleted conversation's supplied context escaping its deletion fence.

> **Normative.** A `NewConversation` speech input that fails or produces no
> words before allocation, and an informational event, use standalone capture.
> `NewConversation` is preserved as a request, never relabeled as a fabricated
> conversation identity.

> **Normative.** A control activation whose original conversation cannot be
> resolved retains the existing degraded/no-episode behavior. Do not copy the
> parked request, response or context into a standalone record to compensate.
> A missing association and a deleted association are both conservative
> misses here; no new tombstone or origin-reconstruction scheme is introduced.

> **Normative.** Conversation deletion keeps index-first capture, deletion
> stamping, post-write verification/compensation and restart recovery. Its index
> enumerates inspection-only episodes as well as model-eligible episodes.
> A filtered history query must never become the deletion enumeration.

### 7. Compatibility eligibility and contract changes

> **Normative.** Set `processing_record.model_eligible=True` exactly for an
> existing conversational/resumption capture path that can provide its existing
> canonical rendering and disposition; set it `False` for newly captured events,
> pre-result failures, interruptions, and no-words speech. Callers and models
> cannot choose this flag. Episodes from other supported producers without a
> processing record retain their existing eligibility.

An existing partial/degraded composition already had a conversational episode;
it remains eligible even when §5 now describes its processing as failed. The
new exclusion is for previously uncaptured failure-only material, not a removal
of existing conversational evidence.

> **Normative.** Add keyword-only `episode_model_eligible: bool | None = None`
> to both `MemoryStore.search` and `MemoryStore.select`. `None` leaves the axis
> unapplied. Otherwise, non-episodic records pass unchanged and episodic records
> pass only when their effective eligibility equals the requested value; absence
> of `processing_record` has effective value `True`.

> **Normative.** Apply this predicate before every lexical/vector candidate
> ceiling, ranking cut and structured-read limit, under ADR-0128 §1. New
> inspection-only episodes must neither enter nor displace eligible results.
> Preserve all existing filters and capped-result semantics.

> **Normative.** All automatic model-facing episodic reads request eligibility
> `True`; direct owner inspection/export may request all. History, observer,
> planning and composing inputs use explicit legacy projections excluding
> `processing_record`, its raw input and attached context. Never serialize an
> enriched whole record into a prompt, embedding input, or trace.

> **Normative.** Add `ConversationTurn.model_eligible: bool = True` and
> keyword-only `model_eligible: bool = True` to `ConversationStore.append`.
> Persist it atomically with the index row and copy the same value onto its
> episode. The index flag is immutable and is not inferred from content that
> may later expire or fail to write.

> **Normative.** Add keyword-only `model_eligible_only: bool = False` to
> `ConversationStore.turns`. When true, filter before selecting the page's last
> `limit` rows and then return those rows in ordinal order. Conversation history
> requests true so inspection-only captures consume no replay-window slots.
> The unfiltered default, ordinal allocation, and backward cursor semantics
> remain unchanged; ordinals in a filtered result need not be consecutive.

> **Normative.** `turns_after` and the observer's scheduling/watermark remain
> unfiltered. The observer skips ineligible rows and treats them like unresolved
> episodes for the existing advance calculation; it makes no model call for an
> all-ineligible/unresolved page. Such rows can be passed by the watermark and
> cannot stall observation. Do not change batch size or scheduling to mine them.

> **Normative.** Keep conversation index delivery semantics: a real spoken
> turn records `UNKNOWN` even on an existing degraded/parked result. New
> no-words or pre-turn-failure records carry no delivery. Playback continues to
> identify the index row by episode address and changes no processing history.

> **Normative.** Change `ConversationExport.schema_version` from literal `2`
> to literal `3` for the added index flag. Fresh stores export version 3.
> M36 adds no version-2 import or conversion path; the existing export surface
> gains no import operation, and no older export hides the added distinction.

### 8. Capture sequence and result reporting

> **Normative.** One orchestration coordinator owns finalization of each
> admitted activation, including compatibility wrappers and explicit `resume`.
> Existing `_capture` sites prepare rendering/disposition/work facts for that
> coordinator instead of writing an early episode followed by a second final one.
> The event processor retains no store capability; the coordinator captures its
> returned summary through injected contracts.

> **Normative.** After the pass ends, conversational finalization performs one
> index append, then the existing archive write if owed, then one
> `MemoryStore.write_atomic` insert-if-absent, then the existing deletion
> verification/compensation. Standalone finalization performs only the single
> memory insert. No proposal/disposition policy or model completion runs for
> capture, and no captured processing envelope is updated in place afterward.

> **Normative.** Finalization performs the last public-output validation after
> the index has supplied its actual address and before archive/episode content
> writes. Use the worst of the possible capture-report shapes for this check;
> recording success changes only its same-sized state label or removes absent
> addresses. An output refusal records `failed / output_oversized` where the
> episode itself fits and propagates the existing outward refusal. The index
> remains the permitted intent row; no model, synthesis or world action resumes.

> **Normative.** Size the stored-record preflight using the maximum encoded
> address length admitted by the existing conversation-ID/ordinal contract,
> without predicting or reserving an ordinal. After append, substitute the real
> address and validate again before writing content. This final metadata check
> is part of recording an ended pass, not a durable live-progress record.

> **Normative.** Keep existing conversational `content`, `disposition` and
> archive `asked`/`replied` projections on their prior paths. For inspection-only
> records use the constant content `Recorded activation; inspect its processing
> record.` and `disposition=None`; the actual input and status live in the
> structured record and are not embedded. Their response, if produced, remains
> in `outcome` under §4. Write no new archive entry for those paths.

> **Normative.** Take the capture timestamp once, reuse it for the indexed
> instant, episode occurrence and retention stamping, and retain the existing
> confidence, provenance and capture stamps where their producers apply. A
> standalone/inspection-only record uses observed source, confidence `0.9`,
> empty evidence and participants, open validity, no confirmation time,
> importance zero and the original channel modality (text for a control trigger).

> **Normative.** Add required `capture: EpisodeCaptureReport` to
> `ChannelResult`. Every successfully returned channel result supplies it,
> including events and empty speech. `recorded` requires non-`None` activation
> and episode IDs and a confirmed episode write plus successful required
> verification; `degraded` means a required capture step failed, was suppressed
> by a deletion fence, or has uncertain completion. An address alone proves no
> record exists. Archive failure also degrades the report when an archive write
> was owed, even if the episode itself landed.

> **Normative.** Old conversational methods retain their signatures and result
> shapes. Fold recording loss into their existing `capture_degraded` where a
> `TurnOutcome` exists; preserve `SpokenTurn.episode_id` as the index-row address,
> not a durability receipt. Empty legacy speech has no such carrier and reports
> recording loss only through content-free operational telemetry. `resume`
> retains its existing public result and no-restatement-capture behavior.

> **Normative.** Reserve the actual public terminal projection's capture-report
> and final index-ID overhead before checking result size or yielding stream
> chunks. `recorded` and `degraded` must fit that same reservation. Finalization
> cannot turn an already bounded successful stream into an oversized terminal
> frame by adding its report. Legacy calls measure their legacy projections;
> the new report does not reduce their previously allowed payload room.

> **Normative.** Run finalization within a five-second monotonic cleanup budget,
> separate from the processing timeout. Shield this cleanup from the original
> cancellation, retain it in engine shutdown tracking, and propagate the
> original cancellation afterward. On budget expiry cancel and await cleanup;
> a second cancellation or process death may prevent recording. Do not abandon
> an untracked background writer or promise a hard wall-clock exit for a
> nonconforming dependency that refuses cancellation.

> **Normative.** Once a conversational content write might have committed,
> finalization's exit path drains the existing deletion verification and
> compensation even on cleanup timeout/cancellation. This safety cleanup stays
> tracked and can outlast the five-second ordinary-write budget; do not close
> its stores or report a verified capture while it is outstanding. A verification
> store failure retains the existing degraded result and recovery obligations.

> **Normative.** Recording failure never replaces a completed answer or the
> original exception, repeats processing, retries a world action, or inserts at
> a replacement address. Log capture stage and code-owned reason without input,
> context, response, identifiers or exception content. Unexpected processing
> exceptions continue to propagate after this best-effort cleanup.

> **Normative.** Restart never fabricates interrupted episodes, replays input,
> or infers that missing episodes mean no action occurred. It continues existing
> deletion recovery. The durability guarantee is survival of successfully
> committed live records, not lossless capture across abrupt termination.

### 9. Bounds, retention, and disclosure

> **Normative.** For a capture running with effective public payload limit `P`,
> bound its complete canonical stored episode encoding to `8 * P + 65536`
> bytes. Measure before any index/archive/content write; an excess degrades
> capture without truncation. This is a write bound, not a new admission limit
> or a read-time reason to hide committed records after deployment limits shrink.

The multiplier accommodates admitted input/context, existing rendering and
response copies, speech transcript and metadata without narrowing ordinary
supported calls. It is a defensive bound, not a guarantee for arbitrary
unbounded provider output or another producer's records. Boundary tests must demonstrate
the supported near-limit inputs rather than assuming the multiplier proves it.

> **Normative.** Use the existing `episode_retention` horizon at capture for the
> whole enriched record. It applies to raw input and attached context as well
> as reply text. A changed setting does not move existing deadlines; individual
> memory deletion, export, backup and whole-owner deletion include all fields.

> **Normative.** The transcript archive remains its separate existing product:
> same conversational addresses, optional writes, retention and deletion rules;
> no informational, attached-context, silence or failure-only archive extension.
> Episode retention expiry leaves its archive entry intact. Explicit
> `forget(record_id)` discards the archive entry first, even when the episode is
> absent, and only then deletes the memory record, under ADR-0225 §5; an archive
> discard failure prevents the later memory deletion. Its return value keeps
> reporting whether memory was deleted. Inspection distinguishes expiry from
> explicit forgetting and does not reconstruct expired episode details from
> the archive.

> **Normative.** Preserve the existing audience/disclosure and placement rules
> under ADR-0199, ADR-0204, ADR-0210 and ADR-0217. Carry the turn's existing
> supply evaluation and any applicable inherited restriction into capture.
> Where no existing placement ground applies, use the existing default
> `Placement()`. Attached context, standalone identity and inspection-only
> eligibility are not new grounds for `OWNER / DERIVED`; capture neither adds a
> setter nor widens an existing restriction. Existing owner acts, model
> proposals, derivation precedence and disclosure floors retain their rules.

> **Normative.** Preserve existing permission, egress-authorization and
> prompt-injection defenses under ADR-0098 and the applicable action contracts.
> Capture, persistence, inspection and later permitted recall grant no authority
> to record contents and create no consent or authorization. Recorded approvals
> and work links are historical facts; continuation still resolves against
> existing work and authorization state. Preserve existing external-origin
> facts on their defined paths; never treat storage in an episode as evidence
> that content is an owner instruction or trusted authorization.

> **Normative.** The raw input/context in the processing record and new
> inspection-only material retain §7's exclusion from automatic model inputs.
> Owner inspection/export retain their existing access boundaries. Neither a
> default placement nor an inspection method admits these added fields to
> shared-output or model-facing paths; existing consumers retain their explicit
> legacy projections and disclosure checks. Admitting this additional material
> to those paths requires a separate contract decision.

> **Normative.** Existing selected-supply external-origin semantics remain
> unchanged on legacy conversational capture. A standalone event retrieves no
> supply and records `derived_from_external=False` under that field's existing
> meaning; it does not mean the event text originated with the owner. Its trigger
> records the supplied channel attribution. A channel label never authenticates
> a sensor, asserts owner authorship, changes confidence to 1, or supplies an
> egress authorization. Context remains untrusted supplied material.

### 10. Inspection data and store surface

> **Normative.** Add the following frozen `extra="forbid"` models in
> `core/types.py`; their tables define their complete shapes. Integer limits
> reject booleans and coercible strings, and text uses existing UTF-8 validators.

| Model | Fields |
| --- | --- |
| `EpisodePosition` | `occurred_at: UtcInstant`; `episode_id: EncodableText` |
| `EpisodeCursor` | `schema_version: Literal[1]`; `after: EpisodePosition`; `channel: ChannelIdentity \| None`; `status: ProcessingStatus \| None` |
| `EpisodeSummary` | `position: EpisodePosition`; `activation_id: Identifier \| None`; `channel: ChannelIdentity \| None`; `modality: Modality`; `status: ProcessingStatus \| None`; `response_kind: EpisodeResponseKind \| None`; `has_processing_record: bool` |
| `EpisodePage` | `items: tuple[EpisodeSummary, ...]`; `next_cursor: NonBlankEncodableText \| None` |
| `EpisodeChunk` | `episode_id: EncodableText`; `version: NonBlankEncodableText`; `offset: int` in `[0, 2**63)`; `text: EncodableText`; `next_offset: int \| None` in `[0, 2**63)` when present; `total_bytes: int` in `[0, 2**63)` |

> **Normative.** Add exactly these two operations to `MemoryStore` and
> `AssistantEngine` (the same names, arguments and return types at both seams).
> All store I/O goes through the Protocol; interfaces hold no concrete store.

```text
async def episodes(
    self,
    *,
    channel: ChannelIdentity | None = None,
    status: ProcessingStatus | None = None,
    cursor: NonBlankEncodableText | None = None,
    limit: int = 50,
) -> EpisodePage

async def episode_chunk(
    self,
    episode_id: EncodableText,
    *,
    version: NonBlankEncodableText | None = None,
    offset: int = 0,
    max_bytes: int = 65536,
) -> EpisodeChunk | None
```

> **Normative.** `episodes` accepts `limit` in `[1, 100]`, filters by effective
> read-time liveness, episodic kind and each supplied exact channel/status, then
> orders by `(occurred_at, episode_id)` descending. Identifiers break equal-time
> ties by Unicode code-point order. Capture timestamps need not reflect arrival
> order. Channel filtering compares both normalized identity fields.

> **Normative.** Inspection episode addresses preserve exactly the stored
> `MemoryBase.id`, including empty strings and leading/trailing whitespace.
> This follows the current store contract, including other supported producers;
> it requires no pre-M36 migration. No summary, position, cursor, detail lookup,
> chunk or CLI adapter strips, rejects as blank, case-folds or otherwise
> normalizes that address. This is a
> scoped exception to ADR-0085 §3c for `episode_chunk.episode_id`; other existing
> engine identifier arguments retain their contracts. New capture still mints
> canonical addresses under §6.

> **Normative.** Its opaque cursor is the unpadded URL-safe base64 of an
> `EpisodeCursor` encoded using the canonical JSON rule below. It carries the
> last returned position, the channel/status filter pair and version `1`; reject
> a spelling that does not round-trip through that encoding. All fields are validated
> before store I/O. A mismatched filter or malformed/unknown cursor version
> raises `ValueError`. Resume strictly below that position; cursor possession
> grants no access. Return `next_cursor` only when another matching row existed
> at that read. Insertions ahead of the cursor appear on refresh; this is not a
> snapshot and expiry/deletion can shorten subsequent pages.

> **Normative.** Summaries set `has_processing_record` according to whether
> the episode carries that record. If absent, activation, channel, status and
> response kind are absent; modality uses the existing capture field. Do not
> infer activation facts from an ID namespace, prose or disposition. A
> status/channel filter does not match those unknowns. This supports current
> non-activation producers, not import of pre-M36 state.

> **Normative.** Detail encoding is the entire validated `EpisodicMemory`
> serialized from JSON-mode fields with sorted keys, compact separators,
> `ensure_ascii=True` and `allow_nan=False`, encoded as UTF-8. `version` is the
> lowercase SHA-256 hex digest of those bytes. This includes mutable annotations,
> so their change invalidates an in-progress read rather than silently mixing
> two versions. Playback is not part of these bytes.

> **Normative.** `episode_chunk` accepts `max_bytes` in `[1, 65536]`. Its first
> call uses `version=None, offset=0`; later calls supply the exact version and
> next byte offset. Versionless nonzero offsets, malformed digests and offsets
> beyond the current encoding raise `ValueError`. A nonmatching supplied valid
> version raises `StaleEpisodeReadError(AssistantError)`, whose message is fixed
> application text and has no content-bearing fields.

> **Normative.** Each detail call rereads and validates a live episodic record;
> missing, expired or non-episodic IDs return `None`. Slice at most `max_bytes`
> canonical bytes, with `next_offset=None` exactly when the returned chunk
> reaches the end. ASCII escaping makes every byte boundary safe. An offset
> exactly at the end returns an empty final chunk. Hold no cross-call content
> snapshot or continuation cache that could survive deletion.

> **Normative.** The store operations return detached values and retain
> `MemoryStoreError` for store/corruption failures. Invalid arguments are refused
> before I/O. Eligibility filters in §7 do not apply to these owner-inspection
> reads; per-read liveness and applicable owner access still do.

### 11. Engine and CLI inspection

> **Normative.** Both inspection methods participate in ordinary authenticated
> engine/wire admission, owner access, shutdown tracking and size checks. They
> invoke no model, create no activation, write no episode and perform no archive
> fallback. Keep the normal no-speech-result channel invariant unchanged.

> **Normative.** Before returning an episode page, the engine fits a leading
> prefix plus its next cursor within the effective public payload bound, using
> the last returned position and original filters to construct that cursor. If
> it cannot fit even the first summary and cursor, raise `OversizedValueError`;
> never skip that row or return an empty success with no progress. A naturally
> empty page has `items=()` and `next_cursor=None`.

> **Normative.** Before returning a detail chunk, the engine counts JSON/wire
> escaping and the actual wrapper. It may shorten the chunk and adjust
> `next_offset` to the first omitted byte; it never changes `version`,
> `total_bytes` or content. If no positive-length progress can fit where bytes
> remain, raise `OversizedValueError`. A transport-sized chunk is not a
> truncation of the stored record; its continuation remains explicit.

> **Normative.** Expose thin CLI commands `assistant episodes` for summaries
> and `assistant episode <episode-id>` for detail. Listing accepts limit, cursor
> and optional paired channel-type/channel-instance and status filters. Detail
> reassembles chunks, verifies the version digest and parses the record before
> rendering; a stale/missing continuation discards the incomplete assembly and
> reports the condition, rather than displaying a complete-looking partial one.

> **Normative.** Human rendering labels absent activation fields unavailable, makes
> informational summaries distinct from conversational replies, and describes
> processing completion separately from goal achievement or playback. Provide
> `--json` for complete canonical detail; no new browser timeline, event endpoint
> or model-query operation is introduced.

> **Normative.** Existing `forget(record_id)` deletes a newly captured enriched
> episode through the archive-first sequence in §9. No delete-by-channel
> operation is added. Existing conversation deletion also retains its archive
> destruction sequence; dedicated archive-only deletion remains available.
> The CLI explains the distinction between retention expiry and explicit
> forgetting and does not present a normalized alias as an exact stored ID.

### 12. Fresh-state cutover, wire compatibility, and architecture

> **Normative.** M36 starts in a fresh development data directory. The owner
> declared all pre-M36 development state disposable. The cutover carries no
> memory, conversation index, archive, parked continuation, goal/work state,
> grant or audit record into the new directory; it is not an episode-only purge.
> Deployment configuration and credentials remain subject to their existing
> setup rules. No migration, backfill, re-embedding of old data or import of
> pre-M36 exports/backups is an M36 deliverable.

> **Normative.** Stop the old hub and use a new empty data directory for the
> cutover. An old directory may be retained separately as a rollback copy; never
> merge it into the new state. Startup neither deletes nor silently upgrades
> pre-M36 stores. No automatic reset occurs on ordinary restart. Document and
> verify this cutover during implementation acceptance; this ADR itself performs
> no data deletion or deployment operation.

> **Normative.** Create the M36 episode/query and conversation-index schemas
> directly in fresh stores, with atomic per-store initialization. Persist an
> episode-record format marker in a dedicated metadata table, distinct from
> embedding identity. Before mutation, reject an existing pre-M36 memory store
> lacking that marker, an existing conversation schema lacking the eligibility
> field, or an unsupported newer format with `IncompatibleStateError`. Explain
> the fresh-directory requirement without erasing the rejected files. Empty
> newly created databases may initialize; a failed initialization must be safe
> to retry. No mixed-version upgrade path is required.

> **Normative.** After cutover, ordinary restart, retention, deletion, export,
> backup/restore and re-embedding preserve the current-format records and their
> references. Supported writers preserve the full processing envelope during
> observer labelling, placement changes and other legitimate updates; they may
> not drop, rewrite or reinterpret immutable fields. Re-embedding and restoration
> retain the format marker and full structured payload. Reject pre-M36 restored
> stores on open before admitting work; do not add a backup-conversion path.

> **Normative.** Writable downgrade of an M36 directory is unsupported. An old
> binary may use its separately retained pre-cutover directory, never the M36
> one; no replay or reconciliation between the two is promised. A marker cannot
> make an older binary check it, so documentation and tests must not claim that
> it mechanically prevents every old writer from opening new state.

> **Normative.** `MemoryWriter.ingest` refuses a supplied proposal carrying a
> non-`None` processing record before any write or policy action. Only the
> deterministic capture producer introduces one. Store updates to a record
> already carrying one preserve that record's activation envelope and response
> text; an attempted removal/change raises `MemoryStoreError` atomically.
> Explicit deletion remains allowed. This does not prevent legitimate changes
> to annotations, placement, validity or other existing mutable metadata.

> **Normative.** Advance the existing wire version for the changed shared
> shapes and methods, and maintain same-build client/server deployment. Extend
> the surface/type closure, error registry, canonical fake and shared engine,
> memory and conversation conformance suites together with their contract
> changes. Do not claim old wire binaries support the new results.

> **Normative.** Keep adapters thin, shared types/Protocols in `core`, memory
> implementations behind their Protocols, capture coordination in
> `orchestration`, and concrete construction in `app`. Introduce no additional
> cross-subsystem Protocol or runtime dependency solely to record an activation.

### 13. Relationship to earlier decisions

> **Normative.** This numbered draft records the scoped replacements in this
> table on each affected ADR's status line and dated header note, atomically
> with ADR-0275 under ADR-0070 and ADR-0082. Preserve earlier supersessions and
> ratified bodies. The replacements take effect on ratification; their reciprocal
> records are required while this decision remains Proposed.

| Decision | Replaced scope and what remains |
| --- | --- |
| ADR-0074 §3, §9 | Extend capture from returned conversation outcomes to admitted activation endings; permit failed/interrupted and standalone capture, separate activation identity, and add the eligibility flag/history filter. Preserve existing indexed episode ID derivation, membership authority, index-first ordering, deletion and retention. |
| ADR-0075 §2 | Extend the direct deterministic-capture exemption to this coordinator's admitted channel/control activations, including event summaries recorded as generated text. Preserve insert-if-absent and at-most-once capture; no belief proposal gains the exemption. |
| ADR-0085 §1, §3c, §8 | Add the two inspection methods/report/error shapes and explicit chunked detail semantics; preserve exact `EncodableText` addresses on `episode_chunk` rather than the general identifier normalization. Preserve canonical transport, authentication, other identifier arguments and legacy public projection limits. |
| ADR-0200 §4 | Replace no-capture for no-words/transcription-failure inputs and move final episode writing after synthesis/output decisions. Preserve no new conversation for no words, transient audio, transcription errors, speech degradation and original processing budgets. |
| ADR-0205 §1, §4 | Preserve real spoken-turn index addresses and delivery semantics while allowing a later post-processing capture; new no-turn speech episodes do not claim a playback row on the old public result. |
| ADR-0212 §3–§6, §8 | Permit observer advance past inspection-only index rows using the existing unresolved-row rule and move the conversation export to version 3; no redesign of progress, batch size or scheduling. |
| ADR-0221 §1, §2, §5, §8, §14 | Add a separately discriminated adapter-summary role for `outcome`, the optional processing record, and explicit model-eligibility filtering. Preserve current disposition strings and distinguish other producers; no model gains raw context/summary access. |
| ADR-0237 §1 | Add the episodic-eligibility axis to search/select before cuts. All existing structured filters and matching rules remain. |
| ADR-0274 §1, §3, §5–§8 | Permit post-processing persistence of event/context and new speech endings, add required capture reporting and bounded recording cleanup; the informational processor itself still owns no writer and performs the same one completion. Existing input/reply combinations and processing policies remain. |

> **Normative.** ADR-0173 §9's transport-disconnect completion behavior,
> ADR-0197 §10's routed-account exclusion, ADR-0198's settled-answer restatement,
> ADR-0217's placement discipline and ADR-0225's archive semantics remain binding
> except where a replacement is explicitly named above. Recording processing
> failure grants no authority to retry or undo effects under the planning ADRs.

### 14. Delivery and acceptance evidence

> **Normative.** Land the ratified contract separately before implementation.
> Then sequence implementation by the memory/query and conversation-index
> contracts, orchestration coordinator and consumer adaptation, application
> wiring, and thin CLI inspection. Each changed Protocol carries its updated
> conformance suite and canonical fake; no implementation slice delegates
> unresolved contract decisions to its consumer.

> **Normative.** Before milestone acceptance, demonstrate every scenario below
> through production composition with deterministic collaborators where needed,
> retain existing text/voice/stream/continuation regressions, and provide
> proportionate live-model and spoken-delivery evidence.

| Scenario | Required evidence |
| --- | --- |
| Text and supplied context | Existing interface crosses the receiver; stored exact input, context, reply and status match its activation; compatibility wrappers capture once. |
| Voice | Transcript/modality and produced reply survive; audio does not; synthesis degradation and playback retain their separate facts. |
| Informational event | Exact supplied event/context and tagged summary survive without conversation, goal, archive entry, tool call or user-facing reply. |
| Restart | Same committed live records, IDs and canonical content are inspectable after hub restart. |
| Waiting and continuation | Waiting episode remains unchanged; later input/control resolution has a distinct activation, only justified links and no duplicated parking utterance as its new input. |
| Concurrency | Barrier-overlap two channels and two calls in one channel; reverse completion order; verify isolated text, context, identity, result, index eligibility and capture report. |
| Interruption | Disconnect alone preserves completion; cancellation records interruption when cleanup succeeds, does not imply rollback/goal cancellation, and leaves subsequent resumption a new activation. |
| Speech without a turn | New-conversation silence/failure allocates no conversation; a named conversation uses capture-only index validation; missing/deleted targets never become standalone content. |
| Failures | Timeout, transcription, reply-composition, output-size, routed failure and unexpected exception classifications preserve outward behavior; no diagnostics leak into records/logs. |
| Retries/restatements | Two channel submissions create two activations; provider retry creates one; settled `resume` restatement retains no new activation/capture. |
| Capture faults | Index/archive/memory/verification failure, five-second cleanup expiry, second cancellation and crash preserve honest degraded reports and never retry work or promise a missing episode. |
| Deletion race | Pause capture before and after each durable write, delete the conversation, restart recovery, and prove no detached fallback/resurrection; standalone deletion removes all enriched content. |
| Consumer isolation | Event/failure-only rows never enter or crowd model retrieval/history; raw context never enters embeddings/prompts; observer advances past ineligible rows without mining them. |
| Audience-policy preservation | Existing supply-derived restrictions and owner/model precedence survive capture; attached context or standalone/inspection-only status alone adds no restriction; default placement admits no raw field to model/shared-output paths. |
| Authority-policy preservation | Persist and inspect instruction-like external content and historical approval text without creating authorization; permitted legacy recall retains its external-origin facts; continuation uses existing authorization state. |
| Fresh-state cutover | Fresh directory creates empty current-format stores; ordinary restart preserves new state; existing pre-M36 and restored old stores are refused without mutation, migration or automatic deletion; no old references enter the new state. |
| Current store addresses and other producers | Newly captured IDs retain the current index/standalone scheme; other supported producers' exact store-valid IDs, including empty and whitespace-distinct values, survive inspection; absent activation metadata is not invented. |
| Mutations | Observer labels, placement updates, re-embedding and restore preserve the entire processing record; unsupported future versions fail clearly. |
| Bounds/inspection | Near-limit old/new input and output, multibyte text, report overhead, page byte cuts, malformed cursors, equal-time ordering, stale detail versions and deletion/expiry between chunks. |
| Data lifecycle | Retention, individual/conversation deletion, export, backup and whole-owner deletion cover added fields; expiry preserves archive while explicit forgetting destroys archive first, even for an absent episode. |

> **Normative.** Record tested revisions, reachable interface evidence,
> residuals and the owner's exit ruling on #2522. A draft, ratified ADR, merged
> implementation or passing suite alone does not establish milestone acceptance.

## Consequences

An inspectable episode can represent an event, a conversational exchange or a
resumption without treating a channel as owner of memory or ongoing work.
Concurrent activations have independent identities; interruption describes a
pass without pretending it reversed an action or cancelled a goal.

The design keeps evidence and deletion in the existing store, but adds query
eligibility, an index flag, a changed export version, a capture report and two
bounded inspection methods. Conversation capture moves later, increasing the
interval in which a crash can lose its episode; that follows the agreed
post-processing scope. Capture can add up to its cleanup budget to normal
operation latency, subject to cooperative dependency cancellation.

No live progress, lossless crash log or automatic event learning follows from
these records. Episode retention is finite unless the owner configures otherwise;
restart durability is not indefinite archival retention. The fresh-state cutover
drops pre-M36 data-migration work without weakening post-cutover durability or
current processing compatibility. Older binaries cannot be made safe by a
format marker they were never written to read.

## Alternatives considered

- **A separate content store:** isolates new inspection records but duplicates
  conversational content and adds another evidence/retention/deletion sequence.
- **Give every event a conversation:** contradicts the input-only exit and
  makes conversation ownership an accidental prerequisite.
- **Replace the indexed episode-ID scheme:** changes the current index
  invariant without buying more independence than a separate activation ID.
- **Migrate disposable development state:** adds old-schema conversion and
  cross-store compatibility work without retaining data the owner needs. The
  selected cutover starts the complete development state afresh.
- **Filter after top-k/history selection:** lets excluded records crowd out
  eligible material and changes conversational behavior despite hiding content.
- **Persist starts and update a running record:** improves crash accounting but
  exceeds the agreed capture-after-processing scope.
- **Let new events enter observation immediately:** expands M36 into deferred
  continuity and learning policy merely because records now exist.

## Review and authorization record

The owner approved the proposal's direction, including general interruption and
parallelism fit, and requested this draft. Its exact contract elaborations,
especially the capture-only check for named no-words speech, model-eligibility
flag, bound and inspection signatures, are presented for review here.
The owner additionally directed that M36 preserve existing audience, permission
and prompt-injection policies; the blanket owner-only rule for attached context
and standalone/inspection-only records has been removed. Architecture and
adversarial review evidence will be recorded separately. The owner also declared
all existing development state disposable and selected a fresh-directory cutover
instead of historical-data migration.
No ratification or implementation acceptance is claimed.
