# 313. Spoken conversation retires at the cutover, an event returns how it ended, and the establishing act leaves the engine

- Status: Partially superseded by ADR-0321 (§5:2 whole; §8's ADR-0235 row's *the authority milestone redoes the act*)
- Date: 2026-10-13
- Scope: the phases after understanding, milestone M43 ([#2815](https://github.com/leonapivato/ai-assistant/issues/2815)): the decision [ADR-0309](0309-the-phases-are-built-beside-the-old-path-and-one-cutover-switches-the-controller-over-deletes-the-old-path-and-goes-live-in-one-deploy.md) §5:11 asks for, on each `AssistantEngine` member that stays and whose signature or result reaches a type its §5 retires, and the owner's ruling that spoken conversation retires at the cutover.
- Dependency: ADR-0306, ADR-0307, ADR-0308, ADR-0309 and ADR-0312, all Accepted.
- Authorization: the dispatcher assigned 0313. The owner ruled on 2026-10-13 that spoken conversation retires at the cutover and returns later as its own design under the channel model ([#2889](https://github.com/leonapivato/ai-assistant/issues/2889)), and that the gateway page may stop speaking notifications meanwhile. The dispatcher authorized ratifying this decision once its reviews are green.
- **Changes `core`, so it is a contract-surface decision, and changes `AssistantEngine` and `ConversationStore`: a breaking change under golden rule 5.** `converse_spoken`, `grantable_decisions` and `establish_recipient_grant` leave the engine surface; `SpokenTurn`, the spoken delivery report and its fact, `ConversationInputOptions`, `TextChannelResult` and `SpokenChannelResult` leave `core`; `ConversationStore` loses its delivery members; `InformationalEventResult` loses `summary` and gains `ended`; four result types lose the members of retiring families (§5:4). The changes cross the wire, so `PROTOCOL_VERSION` advances (§6:4).
- **Supersedes**, each whole:
  [ADR-0205](0205-a-spoken-answers-delivery-is-a-fact-the-device-reports-and-an-unreported-answer-is-never-assumed-heard.md) and
  [ADR-0207](0207-a-parked-spoken-turn-says-one-fixed-sentence-naming-the-screen.md).
- **Partially supersedes**:
  [ADR-0130](0130-a-notification-is-a-proposal-and-only-a-perishable-one-earns-an-interruption.md) (§2:1's `Goal` reference);
  [ADR-0200](0200-a-spoken-turn-is-one-operation-on-the-promoted-surface-and-speech-is-two-seams-beside-the-model-provider.md) (§2–§4, §6:2, §7 and §10, as they decide the spoken turn);
  [ADR-0206](0206-a-notification-is-spoken-where-the-poll-asked-and-the-placement-admits-and-a-withheld-one-arrives-unspoken.md) (§2:2–§2:3, the gateway's formats; §8:12–§8:15, the page's playback);
  [ADR-0235](0235-the-establishing-act-rides-an-answer-to-a-confirmation-live-or-recorded-and-a-refused-search-reaches-the-user-as-history-and-not-as-work.md) (§3, whole; §9:1's `assistant remember-recipients`);
  [ADR-0274](0274-channel-input-and-reply-contract.md) (the conversational combinations and their shapes: §3:1's `ConversationInputOptions`, `TextChannelResult` and `SpokenChannelResult`, §4:2's conversational rows, §4:3–§4:4's conversational limbs, §4:6 and §8:4; and for an event, §3:1's `InformationalEventResult`, §7:6–§7:7 and §8:6–§8:7);
  [ADR-0275](0275-an-episode-records-one-activation-after-processing-ends.md) (§7:8's delivery semantics);
  [ADR-0283](0283-a-channels-history-is-its-episodes-and-the-turn-index-is-retired.md) (§6's delivery members, argument and rows: §6:1's `record_delivery` and `deliveries`, §6:2's `delivery`, §6:3–§6:5, §6:7's delivery rows and §6:8's `record_delivery`);
  [ADR-0309](0309-the-phases-are-built-beside-the-old-path-and-one-cutover-switches-the-controller-over-deletes-the-old-path-and-goes-live-in-one-deploy.md) (§5:1's list, in classing `converse_spoken`, `grantable_decisions` and `establish_recipient_grant` as reworked; §5:11's naming of `converse_spoken`'s `SpokenTurn`).
- Partially superseded: 2026-10-15 by ADR-0321 — §5:2 whole, since the grant listing and revoke members leave; and §8's ADR-0235 row's *the authority milestone redoes the act*, since the act is replaced by scoped delegations and not redone (ADR-0321 §7:1). Every other clause stands. This replacement takes effect on ratification of ADR-0321. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.

## Context

**What obliges it.** ADR-0309 §5:11 rules that each `AssistantEngine` member that stays and
whose signature or result carries a type §5 retires "changes under its own ADR, merged
before the lane that changes it", naming `converse_spoken`'s `SpokenTurn` and `receive`'s
`ChannelResult`. What retires is the proposal's §7 list (ADR-0309 §5:1).

**The owner's ruling.** Spoken conversation retires at the cutover. Voice comes back later
as its own design under the channel model, with its medium, place and sensor (#2889), and
nothing is built for it now, since it is not settled that today's voice machinery fits that
model. The speech seams and what renders through them stay for that design to reuse. The
gateway page may stop speaking notifications until then.

**The survey.** At `f7952737` `AssistantEngine` has 80 members. Each was walked from its
annotations through every field of every `core` type they reach, and the reached types
checked against the families ADR-0309 §5 retires: goal, attempt, intended action, quote,
goal authorization, park, turn outcome, routing, deferral question and verification, with
the coverage, stated-bound and charge declarations ADR-0309 §5:9 retires beside them.

| Members | Under ADR-0309 §5 | What reaches a retiring family | Decided |
| --- | --- | --- | --- |
| `converse`, `resume`, `pending_confirmations`, `cancel_read`, `goals`, `withdraw_clarification`, `abandon_goal`, `standing_authorizations`, `revoke_authorization`, `answer`, `questions`, `interrupted_questions`, `forget_question` | Retire | (they retire) | Nothing here |
| `converse_spoken` | Listed as reworked; retires by the owner's ruling | `SpokenTurn.outcome`, a `TurnOutcome` | §3:1 |
| `receive` | Stays (§5:5) | `ChannelResult`: `TextChannelResult.outcome` and `SpokenTurn.outcome`, each a `TurnOutcome`; the argument's `ConversationInputOptions.reference`, a `TurnReference` naming a goal or a question | §4 |
| `grantable_decisions`, `establish_recipient_grant` | Reworked, losing the establishing act (§5:9) | `PermissionDecision` and `RecipientGrant`, as the rows below | §5:1 |
| `recent_decisions`, `export_decisions` | Stay | `PermissionDecision.intended_action`; `PermissionRuling.authorised_goal` and `proved_quote`, an `ActionQuote`; `PermissionDecision.tool`, as the next row | §5:4 |
| `standing_recipient_grants`, `recent_recipient_grants`, `revoke_recipient_grant` | Stay | `RecipientGrant.tool`: `ToolDefinition.bounded_arguments`, `quoted_output`, `charged_output` and `postconditions` | §5:4 |
| `notifications`, `next_notification` | Stay | `NotificationCandidate.goal_id` | §5:4 |
| `stop_activation`, `episodes`, `episode_chunk`, `create_story`, `link_story`, `unlink_story`, `merge_stories`, `split_story`, `story`, `story_log`, `stories`, `activation_stories`, `story_summary`, `story_standing`, `add_story_note`, `move_story_members`, `beliefs`, `belief`, `forget`, `guard`, `unguard`, `dismiss_notification`, `forget_notification`, `notification_preferences`, `set_notification_preferences`, `recent_conversations`, `conversation`, `forget_conversation`, `start_conversation`, `my_devices`, `set_my_devices`, `set_conversation_devices`, `write_message`, `delete_message`, `delete_conversation`, `transcript`, `chat_changes`, `follow_chat`, `grantable_sources`, `grant`, `revoke`, `recent_grants`, `standing_grants`, `establish_destination_trust`, `standing_destination_trust`, `revoke_destination_trust`, `connect_account`, `reprovision_account`, `disconnect_account`, `connected_accounts`, `recent_connection_acts`, `recent_reads`, `export_reads`, `recent_invocations`, `export_invocations`, `spend_totals` | Stay | Nothing | Nothing here |

`purge_expired` and `start`, which ADR-0309 §5:1 lists as reworked engine surface, are not
`AssistantEngine` members: they are the concrete engine's maintenance and lifecycle, which
the Protocol leaves out on purpose (ADR-0084 §5). §5:11 does not reach them, and their
rework is the deletion lanes' under §5:1, needing no contract decision.

**What spoken conversation is, at `10c7d02c`.** `converse_spoken` and `receive`'s
conversational speech combination run a turn from a recording and return a `SpokenTurn`
wrapping its `TurnOutcome` (ADR-0200, ADR-0274). The gateway reaches `converse_spoken`
through `POST /ask/spoken`, driven by the page's "Hold to talk" control; no command-line
command runs a spoken turn. A device reports what it played of an earlier spoken answer as
a `SpokenDeliveryReport`, which the conversation store keeps as a delivery row (ADR-0205,
ADR-0283 §6).

**What spoken notifications are.** `next_notification` renders a notification's summary
through the wired `SpeechSynthesizer` where the poll names formats in `plays` (ADR-0206),
calling nothing of `converse_spoken`. The gateway's poll names every format (ADR-0206
§2:2), and the page plays a rendering only through an audio context the "Hold to talk"
press builds, since a browser starts audio only inside a gesture (ADR-0206 §8:12). With
push-to-talk gone, the page could never play one.

**What the phases already decide for an event.** An event runs through the phases as one
activation; its place takes no message, so its rounds' text is written nowhere (ADR-0307
§3:8, ADR-0309 §5:5–§5:6). The recipient grant's establishing act retires from the engine
surface, and the authority milestone redoes it (ADR-0306 §4:12, ADR-0309 §5:9).

## Decision

We will retire spoken conversation at the cutover, keeping the speech seams and the hub's
notification rendering for voice's own design; have an event return how its activation
ended and nothing it wrote; take the establishing act and the listing that offers it off the
surface; and leave every other member's signature as it stands, its result types losing the
members of the families that retire.

### 1. Status, scope and delivery

> **Normative.** This document remains `Proposed` until the reviews
> `CONTRIBUTING.md` → "Finishing an ADR PR" requires have returned green on one tree
> and the dispatcher's authorization to ratify stands.

> **Normative.** No lane implements this decision until it has merged `Accepted`.

> **Normative.** Each clause this decision replaces keeps binding the old path's code it
> governs until the lane that changes that member, type or surface merges (§6).

### 2. What stays as it is

> **Normative.** Every member the survey lists as reaching nothing keeps its signature and
> its result, and this decision changes none of them.

### 3. Spoken conversation retires

> **Normative.** `converse_spoken` leaves `AssistantEngine`, and `SpokenTurn` leaves
> `core` with its codec, its canonical fake and its conformance coverage.

> **Normative.** `receive`'s conversational combination, a conversation with speech and a
> spoken reply, retires (§4:1).

> **Normative.** The spoken delivery report retires: `SpokenDeliveryReport`,
> `SpokenDelivery` and `SpokenDeliveryState`; `ConversationStore.record_delivery` and
> `ConversationStore.deliveries`; `record_turn`'s `delivery` argument; and the
> conversation store's delivery rows, wherever it keeps or exports them.

> **Normative.** The gateway's push-to-talk retires: the `POST /ask/spoken` route, the
> "Hold to talk" control, and the page script that records, sends and renders a spoken
> turn.

> **Normative.** The page plays no spoken notification: its playback retires with
> push-to-talk, and a notification is shown as text.

> **Normative.** The gateway's poll asks for no rendering: its `plays` is empty, so the
> hub renders none for it (ADR-0206 §1:2), and the `spoken` member of the value it writes
> on a delivery stream is `null` on every value (ADR-0206 §8:2).

> **Normative.** The speech seams, `SpeechTranscriber` and `SpeechSynthesizer`, their
> implementations and their model artifacts, and `next_notification`'s rendering path stay
> unchanged, and a poll that names formats in `plays` is rendered for as ADR-0206 decides.

> **Normative.** No lane builds anything for voice under this decision. Voice returns as
> its own decision under the channel model.

### 4. `receive`

> **Normative.** `receive` keeps its arguments and admits one combination, an event with
> text and no reply. Any other is refused before processing, as ADR-0274 §4:2 refuses a
> combination outside its table.

> **Normative.** `ChannelInput` loses `conversation`, and `ConversationInputOptions`
> leaves `core`: its `reference` names a goal or a question, and its `delivery` is the
> report §3:3 retires.

> **Normative.** An event runs through the phases as one activation whose place takes no
> message, and nothing its rounds wrote is returned.

> **Normative.** `InformationalEventResult` loses `summary` and gains `ended`, an
> `ActivationEnding` (ADR-0293 §8:3, ADR-0295 §3:4).

> **Normative.** An event's `timeout` is its activation's budget. An event whose
> activation cannot finish, by a phase's failure, the round limit or its budget running
> out, returns its result with `ended` reading couldn't finish, and
> `ChannelProcessingError` and `ChannelProcessingTimeoutError` leave with the
> event-summary stage.

> **Normative.** `ChannelOutcome` is `InformationalEventResult` alone: `TextChannelResult`
> and `SpokenChannelResult` leave with `converse` and `converse_spoken`, and
> `ChannelResult`'s check that a conversational result names its conversation leaves with
> them.

### 5. The grant, decision and notification members

> **Normative.** `grantable_decisions` and `establish_recipient_grant` leave
> `AssistantEngine`, and `assistant remember-recipients` leaves the command line with
> them.

> **Normative.** `standing_recipient_grants`, `recent_recipient_grants` and
> `revoke_recipient_grant` keep their signatures and their results.

> **Normative.** `recent_decisions`, `export_decisions`, `notifications` and
> `next_notification` keep their signatures and their result types.

> **Normative.** The types §5:2–§5:3's members return lose these members, each with its
> family, and nothing replaces them: `PermissionDecision.intended_action`;
> `PermissionRuling.authorised_goal` and `PermissionRuling.proved_quote`;
> `ToolDefinition.bounded_arguments`, `quoted_output`, `charged_output` and
> `postconditions`; and `NotificationCandidate.goal_id`.

### 6. Delivery

> **Normative.** The lane that takes an event through the phases builds §4:3–§4:5, with
> `AssistantEngine`'s conformance suite and canonical fake.

> **Normative.** Where that lane merges before the switch lane, the old path's event, which
> still answers where the opt-in is unset (ADR-0309 §2:6), returns §4:4's shape too,
> projected at the engine's boundary with nothing in the old event path changed.

> **Normative.** The cutover's engine-surface, command-line and gateway lane builds §3:1,
> §3:2, §3:4–§3:6, §4:1, §4:2, §4:6 and §5:1, and its stores-and-types lane builds §3:3
> and §5:4, each with the conformance suites and canonical fakes covering what it changes.

> **Normative.** Each lane §6 names advances `PROTOCOL_VERSION` (ADR-0124 §9:2).

### 7. The code it binds

| Code | Change |
| --- | --- |
| `AssistantEngine.converse_spoken`, `SpokenTurn` | Leave, with codec, canonical fake and conformance coverage |
| `SpokenDeliveryReport`, `SpokenDelivery`, `SpokenDeliveryState` | Leave |
| `ConversationStore.record_delivery`, `.deliveries`; `record_turn`'s `delivery` | Leave, with the store's delivery rows and their export |
| Gateway: `POST /ask/spoken`, "Hold to talk", the page's spoken-turn and notification playback | Leave |
| Gateway: `GATEWAY_PLAYS` | Empty: the poll asks for no rendering |
| `SpeechTranscriber`, `SpeechSynthesizer`, their implementations and artifacts; `next_notification` | Unchanged |
| `ChannelInput`, `ConversationInputOptions` | `ChannelInput` loses `conversation`; `ConversationInputOptions` leaves |
| `ChannelOutcome`, `TextChannelResult`, `SpokenChannelResult` | The two results leave; the union is `InformationalEventResult` |
| `InformationalEventResult` | Loses `summary`; gains `ended: ActivationEnding` |
| `ChannelResult` | Loses its conversational-result check |
| `ChannelProcessingError`, `ChannelProcessingTimeoutError` | Leave with the event-summary stage |
| `AssistantEngine.grantable_decisions`, `.establish_recipient_grant`; `assistant remember-recipients` | Leave |
| `PermissionDecision`, `PermissionRuling`, `ToolDefinition`, `NotificationCandidate` | Lose the members §5:4 names |
| `PROTOCOL_VERSION` | Advances in each lane §6 names |

### 8. Relationship to earlier decisions

| Earlier decision | What changes |
| --- | --- |
| ADR-0130 §2:1 | Its optional `Goal` reference: `NotificationCandidate` loses `goal_id` (§5:4) |
| ADR-0200 §2–§4, §6:2, §7, §10 | As they decide the spoken turn: the composition, `converse_spoken`, its arguments and `SpokenTurn`, the withholding inside the turn, and the browser's `POST`, retire (§3:1, §3:4). §1, §5, §6:1, §6:3, §8, §9 and §11–§13 stand, and so do §3's format choice, §4's translation and degradation rules and §6's rendering bound as ADR-0206 applies them to a notification's rendering (§3:7) |
| ADR-0205 | Whole: the report, its argument, its fact and its reading by the composing stage retire (§3:3) |
| ADR-0206 §2:2–§2:3 | The gateway's `plays` names no format, so no rendering reaches it (§3:6); §2:1's rule that the gateway's `plays` is its own stands |
| ADR-0206 §8:12–§8:15 | The page plays no spoken notification (§3:5); §8:1–§8:11 and §8:16 stand, `spoken` being `null` on every value |
| ADR-0207 | Whole: its operation retires, and the phases park nothing (ADR-0306 §4:8) |
| ADR-0235 §3, §9:1 | The recorded `CONFIRM`'s establishing act and its listing leave the surface, with their command (§5:1); the authority milestone redoes the act |
| ADR-0274 §3:1, §4:2–§4:4, §4:6, §8:4 | The conversational combinations, their options and their results retire (§4:1–§4:2, §4:6); the event's row and refusals stand |
| ADR-0274 §3:1, §7:6–§7:7, §8:6–§8:7 | For an event: no summary is returned, and an activation that cannot finish is a result (§4:3–§4:5) |
| ADR-0275 §7:8 | Its delivery semantics: no turn records a delivery (§3:3) |
| ADR-0283 §6:1–§6:5, §6:7, §6:8 | The delivery members, argument and rows leave (§3:3); every other member and clause stands |
| ADR-0309 §5:1 | `converse_spoken` retires by the owner's ruling, and `grantable_decisions` and `establish_recipient_grant` retire, the act being the whole of the one and the reason for the other (§3:1, §5:1) |
| ADR-0309 §5:11 | Its naming of `converse_spoken`'s `SpokenTurn` among the members that stay (§3:1); `receive`'s `ChannelResult` is §4's |
| ADR-0309 §5:9; ADR-0306 §4:12 | Nothing: §5:1 here is §5:9's retirement |
| ADR-0199, ADR-0203, ADR-0276 §4:13 | Nothing: rules for a channel of unbounded audience, which no operation reaches until voice returns |
| ADR-0124 §9:2 | Nothing: §6:4 applies it |

> **Normative.** This numbered draft records its replacements on the status lines and in a
> dated header note of ADR-0130, ADR-0200, ADR-0205, ADR-0206, ADR-0207, ADR-0235,
> ADR-0274, ADR-0275, ADR-0283 and ADR-0309, atomically with this ADR under ADR-0070 and
> ADR-0082, preserving their ratified bodies. The replacements take effect on this ADR's
> ratification.

## Consequences

**What becomes possible.**
- Voice is designed fresh under the channel model, reusing the speech seams and the hub's
  notification rendering, with no old surface to keep consistent.
- `receive` is the event path alone, and every member that stays carries no type of the
  retired goal model.

**What it costs.**
- Nothing is spoken to or by the assistant between the cutover and voice's return.
- The gateway page shows notifications as text only, and the hub renders none for it.
- No recipient grant can be made until the authority milestone, so the three remaining
  grant members list nothing on the fresh data directory.

**What stays open.**
- Voice, under the channel model (#2889).
- The establishing act and its surface (the authority milestone).

## Options considered

**Spoken conversation.** Earlier drafts reworked `converse_spoken` into the phases and
left two choices open: whether a pass with several messages returns once at its end, returns
its first message with the rest through the delivery outbox, or returns its first message
with the rest fetched by a new member; and whether the words heard are written into the
conversation's transcript. The owner ruled that spoken conversation retires at the cutover,
so neither arises.

**Spoken notifications on the gateway page.** The page's playback needs an audio context
built inside a user gesture, and the "Hold to talk" press is the only gesture that builds
one today.

- **(a) A page-wide first-gesture listener** that builds the context, keeping the player.
  The fewest lines that keep notifications spoken.
- **(b) An explicit "Speak notifications" control.** The same, with a control the owner did
  not ask for.
- **(c) The page stops speaking notifications** until voice returns, and the hub renders
  none for it. The owner ruled (c).

**The stream value's `spoken` member.** Kept, `null` on every value: the delivery stream's
shape does not move, and voice's design decides what a device is given.

**Dropping `receive`'s `reply` argument.** Not done: a refused argument costs nothing, and
voice's design decides what a spoken reply is.

**The grant members until the authority milestone.** Nothing a user sees turns on it,
since ADR-0306 §4:12 already keeps the act out of the phases, so the simple option is
taken.

- **Retire both** (taken): the act is the whole of `establish_recipient_grant`, and
  `grantable_decisions` exists only to offer what the act rides (ADR-0235 §3:12).
- **Keep both, refusing every call**: members that do nothing and that a surface would
  still render.
- **Retire all five recipient-grant members**: the three that list and revoke cost nothing
  to keep and are what the authority milestone's grants will be read and revoked through.
