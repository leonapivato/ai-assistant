# 313. A spoken pass returns its messages and how it ended, an event returns how it ended, and the establishing act leaves the engine

- Status: Proposed
- Date: 2026-10-12
- Scope: the phases after understanding, milestone M43 ([#2815](https://github.com/leonapivato/ai-assistant/issues/2815)): the decision [ADR-0309](0309-the-phases-are-built-beside-the-old-path-and-one-cutover-switches-the-controller-over-deletes-the-old-path-and-goes-live-in-one-deploy.md) §5:11 asks for, on each `AssistantEngine` member that stays and whose signature or result reaches a type its §5 retires.
- Dependency: ADR-0306, ADR-0307, ADR-0308, ADR-0309 and ADR-0312, all Accepted.
- Authorization: the dispatcher assigned 0313. The owner reviews this decision before it is ratified; the choices §Options considered lists as the owner's are recorded there with the recommendation this text takes.
- **Changes `core`, so it is a contract-surface decision, and changes `AssistantEngine`: a breaking change under golden rule 5.** `SpokenTurn` loses `outcome` and gains four members; `InformationalEventResult` loses `summary` and gains one; `TextChannelResult` and `ConversationInputOptions.reference` leave; `grantable_decisions` and `establish_recipient_grant` leave the surface; four result types lose the members of retiring families (§5:4). The changes cross the wire, so `PROTOCOL_VERSION` advances (§6).
- **Supersedes** [ADR-0207](0207-a-parked-spoken-turn-says-one-fixed-sentence-naming-the-screen.md), whole.
- **Partially supersedes**:
  [ADR-0130](0130-a-notification-is-a-proposal-and-only-a-perishable-one-earns-an-interruption.md) (§2:1's `Goal` reference);
  [ADR-0200](0200-a-spoken-turn-is-one-operation-on-the-promoted-surface-and-speech-is-two-seams-beside-the-model-provider.md) (§3:4's expiry during the turn; §4:1's members; §4:2, §4:6–§4:8 and §4:10–§4:14, in their subject, the turn's outcome);
  [ADR-0205](0205-a-spoken-answers-delivery-is-a-fact-the-device-reports-and-an-unreported-answer-is-never-assumed-heard.md) (§1:3's count of `SpokenTurn`'s members; §5:1's composing stage and replay tail);
  [ADR-0235](0235-the-establishing-act-rides-an-answer-to-a-confirmation-live-or-recorded-and-a-refused-search-reaches-the-user-as-history-and-not-as-work.md) (§3, whole; §9:1's `assistant remember-recipients`);
  [ADR-0274](0274-channel-input-and-reply-contract.md) (§3:1's shapes of `ConversationInputOptions`, `TextChannelResult` and `InformationalEventResult`; §4:3's and §4:4's reference limbs; §7:6–§7:7; §8:6–§8:7, for an event);
  [ADR-0307](0307-a-planning-round-is-one-model-response-that-writes-its-own-message-keeps-episode-notes-and-names-what-it-was-shown-by-label.md) (§6:1, in the addition alone: an earlier spoken pass's delivery fact);
  [ADR-0309](0309-the-phases-are-built-beside-the-old-path-and-one-cutover-switches-the-controller-over-deletes-the-old-path-and-goes-live-in-one-deploy.md) (§5:1's list, in classing `grantable_decisions` and `establish_recipient_grant` as reworked: they retire).

## Context

**What obliges it.** ADR-0309 §5:11 rules that each `AssistantEngine` member that stays and
whose signature or result carries a type §5 retires "changes under its own ADR, merged
before the lane that changes it", naming `converse_spoken`'s `SpokenTurn` and `receive`'s
`ChannelResult`. What retires is the proposal's §7 list (ADR-0309 §5:1).

**The survey.** At `f7952737` `AssistantEngine` has 80 members. Each was walked from its
annotations through every field of every `core` type they reach, and the reached types
checked against the families ADR-0309 §5 retires: goal, attempt, intended action, quote,
goal authorization, park, turn outcome, routing, deferral question and verification, with
the coverage, stated-bound and charge declarations ADR-0309 §5:9 retires beside them.

| Members | Under ADR-0309 §5 | What reaches a retiring family | Decided |
| --- | --- | --- | --- |
| `converse`, `resume`, `pending_confirmations`, `cancel_read`, `goals`, `withdraw_clarification`, `abandon_goal`, `standing_authorizations`, `revoke_authorization`, `answer`, `questions`, `interrupted_questions`, `forget_question` | Retire | (they retire) | Nothing here |
| `converse_spoken` | Reworked | `SpokenTurn.outcome`, a `TurnOutcome` | §3 |
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

**What the phases already decide for these members.** A spoken pass and an event each run
through the phases as one activation. A round's text is written into the input's place as
soon as the round is recorded, a pass may write several messages, and a report follows the
calls in a later round (ADR-0307 §3:1, §3:4–§3:5). Each message is claimed and recorded
with its position (ADR-0306 §5:3). An event's place takes no message, so its rounds' text
is written nowhere (ADR-0307 §3:8, ADR-0309 §5:6). On a spoken pass, records placed for
the owner alone stay out of what other readers are shown (ADR-0307 §6:4, ADR-0312 §4:3).
Nothing parks: a call that needs the user goes back to planning, which says it cannot be
done yet (ADR-0306 §4:8, ADR-0307 §9:4). The recipient grant's establishing act retires
from the engine surface, and the authority milestone redoes it (ADR-0306 §4:12, ADR-0309
§5:9). A device reports what it played of a spoken answer, and an unreported answer is
never assumed heard (ADR-0205).

**What is built.** The thin path runs a chat turn through the phases behind the test-hub
opt-in (ADR-0309 §2:6). Today `converse_spoken` and `receive`'s spoken combination run the
old turn and return a `SpokenTurn` wrapping its `TurnOutcome`, and `receive`'s event
combination returns the event-summary stage's `InformationalEventResult.summary`.

## Decision

We will have a spoken pass return its activation, its episode, the messages it wrote into
its place and how it ended, rendered as one answer once the activation has ended; have an
event return how its activation ended and nothing it wrote; take the establishing act and
the listing that offers it off the surface; and leave every other member's signature as it
stands, its result types losing the members of the families that retire.

### 1. Status, scope and delivery

> **Normative.** This document remains `Proposed` until the reviews
> `CONTRIBUTING.md` → "Finishing an ADR PR" requires have returned green on one tree
> and the owner's authorization to ratify stands.

> **Normative.** No lane implements this decision until it has merged `Accepted`.

> **Normative.** Each clause this decision replaces keeps binding the old path's code it
> governs until the lane that changes that member or type merges (§6).

### 2. What stays as it is

> **Normative.** Every member the survey lists as reaching nothing keeps its signature and
> its result, and this decision changes none of them.

### 3. `converse_spoken`

> **Normative.** `converse_spoken` keeps its five arguments, their meanings and their
> local refusals (ADR-0200 §3, ADR-0205 §1:1).

> **Normative.** A spoken pass's place is the conversation `conversation_id` names, or
> the one the call starts where it is `None`, and its messages are written there as
> ADR-0307 §3:1 decides.

> **Normative.** The words heard are the activation's input, recorded with its episode,
> and are not written into the conversation's transcript.

> **Normative.** The call returns once the activation has ended, carrying every message it
> wrote.

> **Normative.** `SpokenTurn` has eight members: `heard`, the transcript, a
> `NonBlankEncodableText | None`; `conversation_id`, the pass's place, an
> `Identifier | None`; `activation_id`, an `Identifier | None`; `episode_id`, the episode
> recording the pass, an `Identifier | None`; `messages`, a
> `tuple[NonBlankEncodableText, ...]`; `ended`, an `ActivationEnding | None`; `spoken`, a
> `SpokenAudio | None`; and `spoken_degraded`, a `bool`. It has no `outcome`.

> **Normative.** `heard` is `None` exactly when `ended` is `None`, and that is the
> recording that carried no words. Its activation is admitted and captured as ADR-0275
> §2:1–§2:3 decide, and `receive` reports that capture, but nothing past transcription
> runs: no planning, no conversation started and no message. The result names none of
> that activation: its record carries no delivery (ADR-0275 §7:8), so there is nothing a
> later report could name. `conversation_id`, `activation_id`, `spoken` and `episode_id`
> are `None`, `messages` is empty and `spoken_degraded` is `False`.

> **Normative.** Beside a `heard`, `conversation_id` is `None` only where the pass ended
> before its place was resolved, and then `messages` is empty and `ended` is not done;
> `activation_id` is `None` only where its allocation failed (ADR-0275 §2:2).

> **Normative.** `episode_id` is `None` beside an activation only where capture recorded no
> episode for it, and it is the name a later `delivery` gives back (ADR-0205 §1:2).

> **Normative.** `messages` holds the text of each message the activation wrote into its
> place whose effect record reads done (ADR-0306 §5:5), in the order written, the fixed
> *couldn't finish* message included (ADR-0307 §3:7). A message not done or whose outcome
> is unknown is not on it.

> **Normative.** Nothing else the activation wrote or read is on the result: no episode
> note, evidence, story note or summary.

> **Normative.** `ended` is how the activation ended, by `ActivationEnding`'s members
> (ADR-0293 §8:3, ADR-0295 §3:4).

> **Normative.** `spoken` is one rendering of the messages joined in order by a blank
> line, the text ADR-0307 §10's table gives `EpisodicMemory.outcome`, and is `None` where
> `messages` is empty.

> **Normative.** `spoken_degraded` is `True` exactly when `messages` is not empty and
> speaking them did not complete, in ADR-0200 §4:11's four cases and no others, and
> ADR-0200 §4:12–§4:14 bind with the result less its rendering in place of the
> `TurnOutcome`.

> **Normative.** A pass that cannot finish, by a phase's failure, the round limit or the
> call's budget running out, returns its result with `ended` reading couldn't finish; it
> is not raised. A transcription failure still fails the call (ADR-0200 §4:15).

> **Normative.** A `delivery` report names an earlier pass by its `episode_id` and states
> what the device played of that pass's one rendering. ADR-0205 §1 binds it with *turn*
> read as *pass*.

> **Normative.** Wherever planning is shown an earlier spoken pass, its place window
> included, it is told that pass's delivery fact, as ADR-0205 §5 told the composing
> stage, with planning in that stage's place and what it is shown in the replay tail's.

### 4. `receive`

> **Normative.** `receive` keeps its arguments and its two admitted combinations,
> conversation with speech and a spoken reply, and event with text and no reply. The
> `ConversationInputOptions` its input carries loses `reference` and keeps `delivery`.

> **Normative.** The spoken combination runs a spoken pass as §3 decides, and its result
> is a `SpokenChannelResult` carrying §3's `SpokenTurn`.

> **Normative.** An event runs through the phases as one activation whose place takes no
> message, and nothing its rounds wrote is returned.

> **Normative.** `InformationalEventResult` loses `summary` and gains `ended`, an
> `ActivationEnding`.

> **Normative.** An event's `timeout` is its activation's budget. An event whose
> activation cannot finish, its budget included, returns its result with `ended` reading
> couldn't finish, and `ChannelProcessingError` and `ChannelProcessingTimeoutError` leave
> with the event-summary stage.

> **Normative.** `TextChannelResult` leaves `ChannelOutcome`: no admitted combination
> produces it once `converse` retires.

> **Normative.** `ChannelResult`'s check that a conversational result names its
> conversation reads `SpokenTurn.conversation_id`, and a spoken result whose
> `conversation_id` is `None` carries no channel, as a no-words result does today.

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

> **Normative.** The lane that takes a spoken pass and an event through the phases builds
> §3 and §4, with `AssistantEngine`'s conformance suite and canonical fake.

> **Normative.** Where that lane merges before the switch lane, the old path's spoken turn
> and event, which still answer where the opt-in is unset (ADR-0309 §2:6), return §3's
> and §4's shapes too, projected at the engine's boundary with nothing in the old turn
> loop changed.

> **Normative.** The cutover's engine-surface lane builds §5:1, and its stores-and-types
> lane builds §5:4, each with the conformance suites and canonical fakes covering what it
> changes.

> **Normative.** Each of those lanes advances `PROTOCOL_VERSION` (ADR-0124 §9:2).

### 7. The code it binds

| Code | Change |
| --- | --- |
| `SpokenTurn` | Loses `outcome`; gains `conversation_id`, `activation_id`, `messages` and `ended`; its validator states the shapes §3:6, §3:7, §3:8, §3:12 and §3:13 admit |
| `AssistantEngine.converse_spoken` | Signature unchanged; returns §3's `SpokenTurn`; a pass that cannot finish is a result |
| `ConversationInputOptions` | Loses `reference` |
| `ChannelOutcome`, `TextChannelResult` | `TextChannelResult` leaves the union and the module |
| `InformationalEventResult` | Loses `summary`; gains `ended: ActivationEnding` |
| `ChannelResult` | Its conversation check reads `SpokenTurn.conversation_id` |
| `ChannelProcessingError`, `ChannelProcessingTimeoutError` | Leave with the event-summary stage |
| `AssistantEngine.grantable_decisions`, `.establish_recipient_grant`; `assistant remember-recipients` | Leave |
| `PermissionDecision`, `PermissionRuling`, `ToolDefinition`, `NotificationCandidate` | Lose the members §5:4 names |
| Planning's inputs | Carry an earlier spoken pass's delivery fact wherever they show that pass (§3:16) |
| `PROTOCOL_VERSION` | Advances in each lane §6 names |

### 8. Relationship to earlier decisions

| Earlier decision | What changes |
| --- | --- |
| ADR-0130 §2:1 | Its optional `Goal` reference: `NotificationCandidate` loses `goal_id` (§5:4) |
| ADR-0200 §3:4 | Its expiry during the turn: the pass ends couldn't finish and is returned (§3:14) |
| ADR-0200 §4:1, §4:2, §4:6–§4:8, §4:10–§4:14 | `SpokenTurn`'s members are §3:5's; the no-words pair is `heard` with the activation (§3:6); `spoken` renders the messages (§3:12); the degradation ladder reads the messages as the answer (§3:13). §4:3–§4:5, §4:9 and §4:15–§4:29 stand |
| ADR-0205 §1:3 | Its count: `SpokenTurn` has eight members, and `episode_id` names the pass's episode (§3:8) |
| ADR-0205 §5:1 | Planning is told the delivery fact wherever it is shown the earlier pass, its place window included (§3:16); §5:2–§5:9 bind it |
| ADR-0207 | Whole: the phases park nothing, so no fixed sentence is spoken for a park; planning's message says what cannot be done yet (ADR-0307 §9:4) |
| ADR-0235 §3, §9:1 | The recorded `CONFIRM`'s establishing act and its listing leave the surface, with their command (§5:1); the authority milestone redoes the act |
| ADR-0274 §3:1, §4:3, §4:4 | `ConversationInputOptions` loses `reference`, with the reference limbs; `TextChannelResult` leaves; `InformationalEventResult` is §4:4's |
| ADR-0274 §7:6–§7:7, §8:6–§8:7 | For an event: no summary is returned, and an activation that cannot finish is a result (§4:3–§4:5) |
| ADR-0307 §6:1 | In the addition alone: the delivery fact rides whatever shows planning an earlier spoken pass (§3:16) |
| ADR-0309 §5:1 | `grantable_decisions` and `establish_recipient_grant` retire rather than being reworked, the act being the whole of the one and the reason for the other (§5:1) |
| ADR-0309 §5:9, §5:11; ADR-0306 §4:12 | Nothing: this is the decision §5:11 asks for, and §5:1 here is §5:9's retirement |
| ADR-0124 §9:2 | Nothing: §6:4 applies it |

> **Normative.** This numbered draft records its replacements on the status lines and in a
> dated header note of ADR-0130, ADR-0200, ADR-0205, ADR-0207, ADR-0235, ADR-0274,
> ADR-0307 and ADR-0309, atomically with this ADR under ADR-0070 and ADR-0082, preserving
> their ratified bodies. The replacements take effect on this ADR's ratification.

## Consequences

**What becomes possible.**
- A spoken pass answers with everything the activation said, the line before its calls and
  the report after them, in one rendering a device plays.
- A device keeps reporting what it played, and planning still knows when an answer was cut
  short.
- Every member that stays carries no type of the retired goal model.

**What it costs.**
- A spoken pass with a web search is heard only once the activation has ended, as a spoken
  turn with reads is today, so the line before the calls arrives with the report.
- The transcript of a conversation spoken to holds the assistant's messages and not the
  words heard.
- No recipient grant can be made until the authority milestone, so the three remaining
  grant members list nothing on the fresh data directory.

**What stays open.**
- A spoken pass's first message reaching the device before the activation ends (§Options
  considered), for a later decision.
- The establishing act and its surface (the authority milestone).

## Options considered

**How a spoken pass with several messages reaches the device.** The owner's choice: a
pass with a web search takes seconds, and latency is what turns on it.

- **A. Return when the activation has ended, carrying every message** (taken, and
  recommended). One call, one rendering, one delivery report per pass, and the device's
  flow unchanged. A spoken turn with reads already returns only once the turn has finished,
  so this is no slower than today. The cost: the line before the calls is heard together
  with the report, not seconds ahead of it.
- **B. Return the first message; deliver later ones through the delivery outbox**
  (ADR-0130, ADR-0131). The first line is heard at once. But a message would become a
  notification candidate under a policy that may hold, drop or delay it, the outbox is a
  mechanism ADR-0292 §13 retires once writing into places is built, and a delivery report
  would need a subject for each message.
- **C. Return the first message; the device asks for the rest by a new member** naming the
  activation. The first line is heard at once without the outbox's policy, at the cost of
  a new member, a second request per pass and a delivery report per message. It can be
  added later without changing A's shape, since `messages` is already a tuple.

**One rendering or one per message.** One, taken: the device plays one answer and reports
one delivery, as today. One per message multiplies synthesis calls and the payload, for a
device that plays them back to back anyway.

**The words heard in the transcript.** The owner's choice, since what a chat device shows
turns on it.

- **Not written** (taken, and recommended): a message in is a device's act whose author
  is the user, established, so it carries the user's authority (ADR-0293 §4:1, §4:8),
  while a voice counts toward establishing the user only where the user set that up
  (ADR-0292 §5:10). Writing the words as the user's message would grant speech an
  authority it does not have. The words stay in the episode, as today.
- **Written as the user's message**: the transcript reads as a dialogue, but speech then
  carries the user's authority in every later window.

**The grant members until the authority milestone.** Not the owner's: nothing a user sees
turns on it, since ADR-0306 §4:12 already keeps the act out of the phases, so the simple
option is taken.

- **Retire both** (taken): the act is the whole of `establish_recipient_grant`, and
  `grantable_decisions` exists only to offer what the act rides (ADR-0235 §3:12).
- **Keep both, refusing every call**: the names stay for the authority milestone, as
  members that do nothing and that a surface would still render.
- **Retire all five recipient-grant members**: the three that list and revoke cost nothing
  to keep and are what the authority milestone's grants will be read and revoked through.

**What a message on the result is.** The text, taken: each message's effect record and
its position stay in the plan store and the transcript, and a device speaking the pass
needs neither. Carrying `TranscriptMessage` or `ActivationEffect` would put the medium's
or acting's bookkeeping on a channel of unbounded audience for no reader.

**Renaming `SpokenTurn`.** Not done: the name is on the wire and in every device, and a
rename changes nothing a reader relies on.
