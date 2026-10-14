# 318. The old path's vocabulary leaves the episode record, the decision row and the grant uses

- Status: Accepted
- Date: 2026-10-14
- Scope: the phases after understanding, milestone M43 ([#2815](https://github.com/leonapivato/ai-assistant/issues/2815)), the cutover's stores-and-types residue: the decision [ADR-0309](0309-the-phases-are-built-beside-the-old-path-and-one-cutover-switches-the-controller-over-deletes-the-old-path-and-goes-live-in-one-deploy.md) §5:11 asks for on the `AssistantEngine` members that stay and whose results still carry what only the old path produced, which [ADR-0313](0313-spoken-conversation-retires-at-the-cutover-an-event-returns-how-it-ended-and-the-establishing-act-leaves-the-engine.md) did not reach: the episode record `episode_chunk` carries, the processing status `episodes` and `story` carry, the decision row `recent_decisions` and `export_decisions` return, and the grant uses the grant and read members take and return.
- Dependency: ADR-0309 and ADR-0313, both Accepted.
- Authorization: the owner ruled that the whole old path is deleted before the deploy (ADR-0309 §4:5–§4:6, §5). The dispatcher assigned 0318 and authorized ratifying this decision once its reviews are green.
- **Changes `core`, so it is a contract-surface decision: a breaking change under golden rule 5.** No `Protocol` gains or loses a member, and every `AssistantEngine` member keeps its signature and its result type (§2:1). `EpisodeProcessingRecord` loses `links` and `response_degraded`, its trigger is a `RecordedChannelTrigger` alone, and its `schema_version` advances; `RecordedResumeTrigger`, `ActivationLinks` and `ParkedBinding` leave `core`; `ProcessingStatus`, `ProcessingReason`, `UnderstandingOmission` and `GrantScope` lose members; `EpisodeProjection` loses its verdicts and `core` its two verdict phrase tables; `PermissionDecision` and `ActionRequest` lose `step_id` and `execution_id`. The changes cross the wire, so `PROTOCOL_VERSION` advances (§7:3).
- **Supersedes**, whole:
  [ADR-0044](0044-durable-confirmation-binding-and-recovery.md).
- **Partially supersedes**:
  [ADR-0021](0021-permission-decisions-and-the-audit-trail.md) (`step_id` on `PermissionDecision` and `ActionRequest`, and the match on it, wherever §1, §3 and §4 name them);
  [ADR-0133](0133-a-producers-read-is-a-third-use-of-a-source-and-the-user-grants-it-separately.md) (§2:3's subset, in `FACET`);
  [ADR-0177](0177-the-browsers-control-surface-is-thirty-operations-and-a-credential-is-entered-only-on-a-loopback-origin.md) (§6:2's `FACET`);
  [ADR-0275](0275-an-episode-records-one-activation-after-processing-ends.md) (§4:1's `RecordedResumeTrigger` and `ActivationLinks` rows, its `RecordedActivationTrigger` alias, and its `waiting`, `confirmation`, `clarification`, `disambiguation` and `composition_failed` values; §4:7; §5:3's rows 5, 8, 9 and 10 and row 6's routed limb; §5:5's `reply_degraded`);
  [ADR-0276](0276-an-activation-is-understood-before-it-is-associated-and-the-understanding-is-retained-with-its-episode.md) (§2:1's `UnderstandingOmission` row, in `routed` and `no_input`);
  [ADR-0283](0283-a-channels-history-is-its-episodes-and-the-turn-index-is-retired.md) (§3:4);
  [ADR-0284](0284-an-episode-is-the-experience-of-processing-its-activation.md) (§4:2's `response_degraded`; §8:1's stage verdicts; §8:6's verdict phrases);
  [ADR-0294](0294-readers-no-longer-ingest-into-memory-and-what-they-wrote-stays.md) (§2:2's request-path facets; §4:3's and §4:6's `FACET`).

## Context

**What obliges it.** ADR-0309 §5:11 rules that each `AssistantEngine` member that stays and
whose signature or result carries a type its §5 retires "changes under its own ADR, merged
before the lane that changes it". ADR-0313 answered it for the members its survey found.
ADR-0309 §3:6 and §3:7 already decide that `ControllerStage` and `ControllerRule` lose the
old path's members and that `StageEntry` loses its two verdicts; that the stages and rules
leave is not reopened here.

**What ADR-0313's survey did not reach.** It walked each member's annotations through the
declared fields of the types they reach. `episode_chunk` returns an `EpisodeChunk` whose
`text` is a slice of an episode's canonical JSON, built by `detail_of` in
`core/episode_encoding.py`, and the command line reassembles the slices and validates them
whole as an `EpisodicMemory` (`read_detail` in `interfaces/episode_inspection.py`). The
episode record therefore crosses the wire as data, and has been treated so: each change to
it has advanced `PROTOCOL_VERSION` (ADR-0284 §9:2, ADR-0315 §5:1). Through it the surface
reaches `StageEntry`'s verdicts, a `Disposition` and a `RouteOutcome`, from the turn-outcome
and routing families; `ActivationLinks.parked` and `parks`, each a `ParkedBinding`, from the
park family; and `RecordedResumeTrigger`, the record of the `resume` ADR-0309 §5 retires.
ADR-0313 listed `episodes` and `episode_chunk` as reaching nothing.

**The survey, at `630b9860`**, after the cuts that deleted the old path's orchestration
modules. Each candidate was checked for a producer that still runs and for where the
surface reaches it.

| Candidate | Producer that still runs | On the wire through | Read by |
| --- | --- | --- | --- |
| `StageEntry.step_disposition`, `route_outcome` (ADR-0309 §3:7) | None: the controller's stages carry no verdict, and `run_recorded`, the resume path's recorder, has no caller | The record's stages | The episode projection; the activation viewer's step |
| `EpisodeProjection.step_dispositions`, `route_outcomes`; `STEP_DISPOSITION_PHRASES`, `ROUTE_OUTCOME_PHRASES` | None: always empty, as there is no verdict to read | Not carried | Understanding's and planning's episode renderings |
| `RecordedResumeTrigger` | `admit_resume`, which has no caller | The record's trigger | The record's resume-only validator; the restart close |
| `ActivationLinks`, all seven fields | None: `relate` is called with `parks` alone, from `CaptureFacts.parked`, which the phases set to `None` | The record's links | `MemoryStore.episode_parking` and its index, which ADR-0309 §5 retires |
| `ProcessingStatus`'s `waiting`; `ProcessingReason`'s `confirmation`, `clarification` and `disambiguation` | None: `terminal_status` reads them off a `TurnOutcome` only `observe_result` sets, and it has no caller | `episodes`'s `status`, `EpisodeSummary.status`, `story`; the record | The conversation's ending map; the command line's status option |
| `ProcessingReason`'s `composition_failed`; `EpisodeProcessingRecord.response_degraded` | None: both are set from the compose stage's degradation, which `composition` and `observe_result` alone report, and neither has a caller | The record | Nothing |
| `UnderstandingOmission`'s `routed` and `no_input` | None: they classify a taken route and a resume trigger | The record | Nothing |
| `PermissionDecision.step_id`, `execution_id`; `ActionRequest`'s two | None: the authorizer builds its `ActionRequest` with neither, and only the old path's executor set them | `recent_decisions`, `export_decisions` | `authorises`; the audit trail's resolution invariant and `pending_confirmation` |
| `GrantScope.FACET` | None: no read is gated on it since the request-path facets left with `context/`; the gated reads are `NOTIFY`'s | `grant`, `revoke`, `standing_grants`, `recent_grants`, `grantable_sources`, `recent_reads`, `export_reads` | The command line's phrase; the gateway's grant form, which offers it as "Look at it while answering you" |

**What the survey keeps.**
- `ControllerRule`'s `no_text_input`, `UnderstandingOmission`'s `no_text`, `ProcessingReason`'s
  `no_content` and `transcription_failed`, `RecordedSpeechInput` and `output_degraded` have no producer
  either, because `receive` refuses speech before admission (ADR-0313 §4:1). They are what a
  spoken activation records, and voice returns as its own decision (ADR-0313 §3:8,
  [#2889](https://github.com/leonapivato/ai-assistant/issues/2889)). `transcription_failed`
  was checked against the transcriber ADR-0313 §3:7 keeps: the seam stays, but no activation
  transcribes, and nothing classifies as a transcription failure since `converse_spoken`
  retired.
- `ProcessingReason`'s `timeout` still has a producer: a classified model timeout that ends the
  pass.
- `TurnOutcome`, and `MemoryUpdateProposal` with the `UserConfirmation` its `confirmation` holds, are reached from the
  surface neither through a declared field nor through the record. They retire under
  ADR-0309 §5 in lanes that move no shape the wire carries, and nothing here decides them.

## Decision

We will take out of `core` what only the old path produced and the surface still carries: the
episode record's verdicts, resume trigger, links, waiting reasons and compose stage's
degradation; a decision's step and execution; and the facet grant use. The episode record's
version advances, nothing written before it is read, and one lane makes every change with
ADR-0309 §3:6–§3:7's removals under one `PROTOCOL_VERSION` advance.

### 1. Status, scope and delivery

> **Normative.** This document remains `Proposed` until the reviews
> `CONTRIBUTING.md` → "Finishing an ADR PR" requires have returned green on one tree
> and the dispatcher's authorization to ratify stands.

> **Normative.** No lane implements this decision until it has merged `Accepted`.

> **Normative.** Each clause this decision replaces keeps binding the old path's code it
> governs until the lane that removes or changes that code merges.

### 2. What stays as it is

> **Normative.** No `AssistantEngine` member is added or removed, and every member keeps
> its signature and its result type; the types they reach lose the members §3–§6 name.

> **Normative.** Every member of `ControllerStage`, `ControllerRule`, `ProcessingStatus`,
> `ProcessingReason` and `UnderstandingOmission` that neither ADR-0309 §3:6 nor §3–§5 below
> names stays, the phases' stages, rules and reasons among them.

> **Normative.** The record of a spoken activation stays as it is, for voice's own decision
> to keep or change: `RecordedSpeechInput`, `output_degraded`, `ControllerRule`'s
> `no_text_input`, `UnderstandingOmission`'s `no_text`, and `ProcessingReason`'s
> `no_content` and `transcription_failed`.

### 3. The stage verdicts

> **Normative.** `EpisodeProjection` loses `step_dispositions` and `route_outcomes`, and
> `core` loses `STEP_DISPOSITION_PHRASES` and `ROUTE_OUTCOME_PHRASES`. A rendering of an
> episode states its status and reason, and no verdict.

> **Normative.** `Disposition`, `RouteOutcome` and `admitted_route_outcomes` leave `core` in
> the lane §7:2 names, with whatever of their families (ADR-0309 §5) still names them then.

### 4. The trigger and the links

> **Normative.** `RecordedResumeTrigger` and the `RecordedActivationTrigger` alias leave
> `core`. `EpisodeProcessingRecord.trigger` is a `RecordedChannelTrigger`, and the record's
> rule that a resume carries no recall result leaves with the resume trigger.

> **Normative.** `ActivationLinks` leaves `core`, and `EpisodeProcessingRecord` loses
> `links`.

> **Normative.** `ParkedBinding` leaves `core` in the lane §7:2 names, with whatever of the
> park family (ADR-0309 §5) still names it then.

### 5. How an activation ended

> **Normative.** `ProcessingStatus` loses `waiting`, and `ProcessingReason` loses
> `confirmation`, `clarification`, `disambiguation` and `composition_failed`.

> **Normative.** ADR-0275 §5:3's table loses rows 5, 8, 9 and 10, and row 6's condition
> reads "another declared operational error" alone. The remaining rows keep their order.

> **Normative.** `EpisodeProcessingRecord` loses `response_degraded`.

> **Normative.** `UnderstandingOmission` loses `routed` and `no_input`.

> **Normative.** Each member this decision removes from a closed enumeration is a recorded
> exception to *added to and never renamed*: the data directory is fresh (ADR-0309 §6:1),
> so nothing stored names it.

### 6. The decision row and the grant uses

> **Normative.** `PermissionDecision` loses `step_id` and `execution_id`, and `ActionRequest`
> loses the two fields they are transcribed from. `PermissionDecision.authorises` and the
> audit trail's resolution invariant stop comparing them, and go on comparing every other
> field they compare.

> **Normative.** `GrantScope` loses `FACET`. A new grant's scope is `NOTIFY` alone, and a
> surface offering the uses for a new grant offers `NOTIFY` alone, named in words.

> **Normative.** `INGEST` stays a member as ADR-0294 §4:4 keeps it, and `grant` refuses a
> scope naming it as ADR-0294 §4:3 does.

### 7. The record's version and delivery

> **Normative.** `EpisodeProcessingRecord.schema_version` advances by one, and the memory
> store's episode format marker with it. No record stored before it is read, and no lane
> writes a reader for one (ADR-0309 §6:4).

> **Normative.** One lane implements this decision, in the same change as ADR-0309
> §3:6–§3:7's removals, as the cutover lane of their area (ADR-0309 §7:1): the M43 residue
> lane T3, or core lane P4 where T3 is folded into it. It lands with the conformance suites
> and canonical fakes covering what it changes.

> **Normative.** That lane advances `PROTOCOL_VERSION` once (ADR-0124 §9:2). Where it is
> P4, or lands in one change with P4, P4's one advance covers both.

### 8. The code it binds

| Code | Change |
| --- | --- |
| `EpisodeProcessingRecord` | Loses `links`, `response_degraded` and the resume-only recall rule; `trigger` is a `RecordedChannelTrigger`; `schema_version` advances |
| `RecordedResumeTrigger`, `RecordedActivationTrigger`, `ActivationLinks`, `ParkedBinding` | Leave `core` (§4) |
| `StageEntry`, `ControllerStage`, `ControllerRule`, `ENDING_CONTROLLER_RULES` | Lose what ADR-0309 §3:6–§3:7 name, in the lane §7:2 names |
| `EpisodeProjection`, `project_episode`, `STEP_DISPOSITION_PHRASES`, `ROUTE_OUTCOME_PHRASES` | The projection loses its verdicts; the tables leave (§3:1) |
| `Disposition`, `RouteOutcome`, `admitted_route_outcomes` | Leave `core` (§3:2) |
| `ProcessingStatus`, `ProcessingReason`, `UnderstandingOmission` | Lose the members §5 names |
| `PermissionDecision`, `ActionRequest` | Lose `step_id` and `execution_id`; `authorises` stops comparing them |
| `GrantScope` | Loses `FACET`; `GRANTABLE_SCOPES` follows |
| `core/episode_encoding.py` | `episode_extends`, `_settled_trigger` and `_settled_links` lose what names a removed field or the resume trigger |
| `orchestration/controller.py` | `Verdict`, `NO_VERDICT`, the verdict of `StageResult` and `Stage`, and `run_recorded` leave |
| `orchestration/activation_state.py` | `admit_resume`, `relate`, `observe_result`, `composition`, `CaptureFacts.parked` and the removed rows of `terminal_status` leave; the resume arms of `_omission` and `_stage_record` leave |
| `orchestration/activation_writer.py` | `_closed_omission` loses its resume and routing arms; the writer sets no links |
| `orchestration/conversations.py` | The ending map loses `waiting`'s row |
| `orchestration/understanding.py`, `orchestration/planning.py` | Their episode renderings state no verdict |
| `memory/_episode_format.py`, the memory store's `links.parks` index | The format marker advances; the index leaves with `episode_parking` where an earlier lane has not removed it |
| `permissions/audit.py` | Stores and compares no `step_id` or `execution_id` |
| `interfaces/cli.py`, the gateway's grant form | Offer and phrase no `FACET`; the episode status option offers no `waiting` |
| `scripts/activation_viewer.py` | Its step shows no disposition or route |
| `testing/activation.py`, `testing/engine.py` | Lose the removed arms and the `FACET` default |
| `PROTOCOL_VERSION` | Advances once (§7:3) |

### 9. Relationship to earlier decisions

| Earlier decision | What changes |
| --- | --- |
| ADR-0021 §1, §3, §4 | `step_id` leaves `PermissionDecision` and `ActionRequest`, and the match on it leaves (§6:1); every other field and the match on it stand |
| ADR-0044 | Whole: every section binds a parked `CONFIRM` to a plan execution, and plan executions retire (ADR-0309 §5); `execution_id` leaves (§6:1) |
| ADR-0133 §2:3 | Its subset, in `FACET`: a scope names a non-empty subset of `INGEST` and `NOTIFY`, and a new grant names `NOTIFY` alone (§6:2–§6:3); the members' independence stands |
| ADR-0177 §6:2 | Its `FACET`: the browser offers no facet use (§6:2) |
| ADR-0275 §4:1 | The `RecordedResumeTrigger` and `ActivationLinks` rows and the `RecordedActivationTrigger` alias leave (§4); `ProcessingStatus` and `ProcessingReason` lose the values §5:1 names |
| ADR-0275 §4:7 | Whole: there are no links (§4:2) |
| ADR-0275 §5:3 | Rows 5, 8, 9 and 10, and row 6's routed limb (§5:2) |
| ADR-0275 §5:5 | Its `reply_degraded`, which ADR-0284 renamed `response_degraded` (§5:3); the spoken half stands |
| ADR-0275 §2:6, §4:6, §5:4, §6:5, §8:1, §8:6, §8:8 | Nothing: their resume limbs rule a control activation, and `resume` retired (ADR-0309 §5) |
| ADR-0276 §2:1 | The `UnderstandingOmission` row, in `routed` and `no_input` (§5:4) |
| ADR-0276 §5:2–§5:4 | Nothing: their routed and resume limbs rule a taken route and a resume, which ADR-0309 retired |
| ADR-0281 §6:2–§6:3, ADR-0308 §7 | Nothing: their resume limbs rule a record no trigger now makes |
| ADR-0283 §3:4 | Whole: `ActivationLinks.parks` leaves with the links (§4:2) |
| ADR-0284 §2:4 | Nothing: it rules a type that leaves |
| ADR-0284 §4:2 | Its `response_degraded` (§5:3); `output_degraded` stands |
| ADR-0284 §8:1, §8:6 | The projection carries no stage verdict, and the phrase table leaves; a rendering states status and reason (§3:1) |
| ADR-0286 §3:3 | Nothing: a field the record no longer has takes no value |
| ADR-0294 §2:2 | Its request-path facets: no request path reads a facet under a grant use (§6:2); the upcoming-event producer stands |
| ADR-0294 §4:3, §4:6 | Their `FACET`: a new grant's scope is `NOTIFY` alone (§6:2); the refusal of `INGEST` stands |
| ADR-0097 §5:2, §5a:7; ADR-0185 §5:1 | Nothing: their `FACET` limbs name a use that leaves, and their other limbs stand |
| ADR-0309 §3:6–§3:7, §7:1 | Nothing: §7:2 lands those removals in the cutover lane ADR-0309 §7:1 calls for |
| ADR-0309 §5:11 | Nothing: this decision answers it for `episodes`, `episode_chunk`, `story`, `recent_decisions`, `export_decisions` and the grant and read members |
| ADR-0313 §2:1 | Nothing: each member keeps its signature and its result type, as §2:1 has it; the types they reach lose members, the distinction ADR-0313 §5:3–§5:4 draw |
| ADR-0313 §3:7–§3:8 | Nothing: the speech shapes stay for voice (§2:3) |
| ADR-0124 §9:2; ADR-0309 §6:4 | Nothing: §7:1 and §7:3 apply them |

> **Normative.** This numbered draft records its replacements on the status lines and in a
> dated header note of ADR-0021, ADR-0044, ADR-0133, ADR-0177, ADR-0275, ADR-0276, ADR-0283,
> ADR-0284 and ADR-0294, atomically with this ADR under ADR-0070 and ADR-0082, preserving
> their ratified bodies. The replacements take effect on this ADR's ratification.

## Consequences

**What becomes possible.**
- The episode record holds what the phases do and nothing a reader could mistake for an
  activation still waiting on a question, a park or a route.
- The grant form stops offering a use nothing honours, so a user is not told the assistant
  will look at a source while answering when it will not.
- The residue lanes delete the old path's types without one of them stranded behind a field
  the wire still carries.

**What it costs.**
- A peer at the old `PROTOCOL_VERSION` and one at the new cannot talk, as with every
  record change.
- The stored record moves one version, and nothing written before it is read; the deploy
  starts on a fresh data directory (ADR-0309 §6:1).
- `ParkedBinding`, `Disposition` and `RouteOutcome` stay in `core` until this decision's
  lane, even where their family's lane runs first.

**What stays open.**
- The record of a spoken activation, which voice's decision keeps or changes (#2889).
- `INGEST`, which no new grant may name and ADR-0294 §4:4 keeps for stored grants.
- The trigger's recorded reply capability, which keeps every shape ADR-0274 admits.

## Options considered

- **Keep the old members unused, under *added to and never renamed*.** Rejected for the
  reason ADR-0309 gives for the controller's: nothing stored names them, and an unused member
  invites a rule to read it.
- **Retire the speech record too.** Not chosen: ADR-0313 kept speech's shapes on the surface
  for voice's design, and a record member that is never produced costs nothing until then.
- **Each family's type lane makes its own wire change.** Not chosen: each would advance
  `PROTOCOL_VERSION` for a part of one record, and one lane advances it once.
- **Keep `FACET` for a later request-path reading.** Rejected: no reading is gated on it, and
  a grant it names promises something nothing does.
