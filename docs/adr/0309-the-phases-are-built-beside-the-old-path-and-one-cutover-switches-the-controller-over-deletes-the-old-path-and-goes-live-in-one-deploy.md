# 309. The phases are built beside the old path, and one cutover switches the controller over, deletes the old path and goes live in one deploy

- Status: Partially superseded by ADR-0312 (§2:2's module naming: it names the phases, not their modules' file names) and ADR-0313 (§5:1's list, in classing `converse_spoken`, `grantable_decisions` and `establish_recipient_grant` as reworked; §5:11's naming of `converse_spoken`'s `SpokenTurn`)
- Date: 2026-10-11
- Scope: the phases after understanding ([#2723](https://github.com/leonapivato/ai-assistant/pull/2723)), milestone M43 ([#2815](https://github.com/leonapivato/ai-assistant/issues/2815)), the last of their four decisions: how the phases are built, the controller's table they run on, the lanes that build them, what retires, and the one cutover that takes them live. ADR-0306 decided capabilities, authorizing and acting, ADR-0307 planning, and ADR-0308 recall's second run and digesting.
- Dependency: [ADR-0306](0306-a-capability-declares-what-its-calls-do-every-call-is-checked-by-rule-and-acting-claims-and-records-what-it-does.md), [ADR-0307](0307-a-planning-round-is-one-model-response-that-writes-its-own-message-keeps-episode-notes-and-names-what-it-was-shown-by-label.md) and [ADR-0308](0308-recall-runs-again-on-what-understanding-found-and-outside-content-reaches-planning-only-as-a-digests-evidence.md), all Accepted and merged at `edd58306`, each of which waits on this decision before any lane implements it.
- Authorization: the owner accepted proposal #2723 on 2026-10-11 and, the same day, ruled this decision's content in a pass over it. The dispatcher assigned 0309. This ADR is the proposal's §0 and §7 converted under `docs/proposals/README.md` → "When it is decided". Those rulings authorize ratifying it once its reviews are green, for as long as it settles only what they leave open.
- **Changes `core`, so it is a contract-surface decision, and removes `Protocol`s and `Protocol` members: a breaking change under golden rule 5.** `ControllerStage` and `ControllerRule` lose the old path's members, as a recorded exception to *added to and never renamed*, and gain two each; `StageEntry` loses its two verdict fields; `AssistantEngine` and `PlanStore` lose members, and the `Protocol`s and type families of the goal and attempt model, routing, parks and deferred questions retire with their codecs and fakes (§5, §7). The removals change shapes the wire carries, so `PROTOCOL_VERSION` advances.
- **Supersedes**, each whole (§8):
  [ADR-0078](0078-a-deferred-memory-decision-is-a-durable-question.md),
  [ADR-0197](0197-an-ask-reaches-the-hubs-own-operations-through-a-routing-stage-and-a-routed-operation-is-never-re-read.md),
  [ADR-0198](0198-a-settled-parks-answer-is-restated-rather-than-refused-and-a-second-resume-performs-nothing.md),
  [ADR-0224](0224-the-episodic-supplement-is-thirty-at-parity-with-the-belief-budget.md),
  [ADR-0229](0229-a-citation-hop-reaches-the-record-its-label-names-as-well-as-that-records-evidence.md),
  [ADR-0248](0248-the-users-request-is-its-own-value-on-the-turn-and-the-goal-statement-stops-standing-in-for-it.md),
  [ADR-0249](0249-the-goal-carries-its-interpretation-the-attempt-carries-the-phase-and-the-planner-returns-its-understanding.md),
  [ADR-0250](0250-a-turn-finds-its-goal-before-it-plans-and-a-material-ambiguity-becomes-one-durable-question-bound-to-that-goal.md),
  [ADR-0251](0251-an-attempt-investigates-in-bounded-rounds-over-typed-read-outcomes-and-keeps-a-reserve-to-answer-with.md),
  [ADR-0252](0252-evidence-is-what-a-response-supports-sufficiency-to-act-is-four-mechanical-tests-and-a-refresh-supersedes-the-row-it-displaces.md),
  [ADR-0253](0253-the-plan-declares-what-a-step-waits-on-what-fills-its-arguments-and-what-must-be-evidenced-before-it-is-dispatched.md),
  [ADR-0254](0254-phase-4-validates-the-plan-in-code-and-route-d-authorises-a-concrete-call-against-fixed-values-and-permitted-ranges-from-recorded-acts.md),
  [ADR-0255](0255-the-driver-walks-a-plan-in-dependency-order-claims-each-step-under-its-attempt-and-stops-rather-than-acting-under-an-unfinished-one.md),
  [ADR-0256](0256-an-authorization-with-no-stated-instant-and-no-goal-deadline-takes-the-retention-window-its-acts-own-record-lives-under.md),
  [ADR-0258](0258-the-investigations-per-ask-outcome-is-named-read-ask-outcome-and-the-permission-trail-keeps-read-outcome.md),
  [ADR-0259](0259-an-effect-is-claimed-once-per-goal-before-it-is-dispatched-and-a-turn-start-pass-reconciles-what-an-earlier-turn-left-uncertain-or-unfinished.md),
  [ADR-0261](0261-a-cancellation-is-a-user-act-between-turns-that-ends-the-goals-attempt-and-an-effect-already-dispatched-is-reported-rather-than-withdrawn.md),
  [ADR-0262](0262-verification-compares-the-goals-criteria-with-what-the-record-establishes-at-a-strength-the-consequence-class-fixes-and-is-achieveds-only-producer.md),
  [ADR-0264](0264-a-turn-that-reached-outside-this-system-says-so-and-a-reply-cannot-deny-a-contact-the-trail-recorded.md),
  [ADR-0265](0265-an-intended-action-has-a-stable-identity-minted-once-and-linked-to-the-goal-elements-it-serves.md),
  [ADR-0266](0266-a-coverage-member-records-the-constraint-the-user-stated-and-the-bound-is-proved-against-the-quote-for-the-intended-action.md),
  [ADR-0267](0267-a-quote-is-a-record-the-goal-holds-in-order-read-from-the-output-its-declaration-names.md),
  [ADR-0268](0268-an-authorization-ends-when-its-goal-closes-and-the-retention-window-is-only-the-backstop.md),
  [ADR-0269](0269-a-serves-link-is-checked-against-every-revision-the-goal-holds-not-the-one-current-at-the-append.md),
  [ADR-0270](0270-the-policy-answers-whether-a-proposed-rows-coverage-is-met-and-that-answer-is-the-whole-of-what-crosses-the-seam.md) and
  [ADR-0271](0271-the-quote-a-dispatch-was-proved-against-is-pinned-to-that-dispatch-and-a-charge-that-disagrees-with-it-is-a-reported-finding.md).
- **Partially supersedes**:
  [ADR-0158](0158-an-episode-may-supplement-the-answering-prompt-and-never-shares-the-belief-budget.md) (every clause but §2:2);
  [ADR-0204](0204-a-record-carries-whether-the-supply-it-was-produced-over-held-withheld-content.md) (§2:1's site and timing);
  [ADR-0210](0210-the-withholding-fires-on-what-the-turn-was-retrieved-for-and-the-conversations-own-turns-fire-nothing.md) (§1:1–§1:2, in the set they name);
  [ADR-0260](0260-a-forecast-read-is-its-own-seam-at-a-configured-provider-and-what-it-mints-carries-the-extent-that-makes-it-evidence.md) (§7–§10, the forecast read's place in the turn loop);
  [ADR-0273](0273-a-simulated-booking-provider-is-a-reference-integration-declared-as-the-real-one-and-its-act-reaches-nothing-outside-this-deployment.md) (what it declares and reads for the goal model);
  [ADR-0274](0274-channel-input-and-reply-contract.md) (§7's informational processing, in its summary stage);
  [ADR-0280](0280-an-activation-controller-runs-the-stages-by-rules-and-records-every-choice-with-the-episode.md) (§1:4's resume clause; §2:1; §2:3's association limb; §3:3, for the round's step; §3:5 and §3:7, in the removed members and the additions; §4:1–§4:2, in the removal and the additions; §4:3's table; §4:5's composition sentence; §4:6's loop guard, for authorizing, acting and digesting; §4:7; §4:8's last sentence);
  [ADR-0284](0284-an-episode-is-the-experience-of-processing-its-activation.md) (§5:1–§5:2's verdict fields; §5:4–§5:5's resume record);
  [ADR-0292](0292-a-channel-is-the-spokes-facing-one-thing-and-the-assistants-edge-is-its-own.md) (§13:1, for `resume` alone).
- Partially superseded: 2026-10-11 by ADR-0312 — one scope. §2:2's module naming: it
  names the phases and not their modules' file names. The authorizing phase's module
  takes a name other than `authorizing`, chosen by the lane that builds it, so §5:3 binds
  it as written, and §2:3's `independence` contract covers it under that name. The
  controller stage keeps the name `authorizing`. Every other clause stands. This scoped
  replacement takes effect on ratification of ADR-0312. This reciprocal header record
  accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the
  ratified body below are preserved.
- Partially superseded: 2026-10-13 by ADR-0313 — two scopes. §5:1's list, in
  classing `converse_spoken`, `grantable_decisions` and `establish_recipient_grant`
  as reworked: `converse_spoken` retires by the owner's ruling that spoken
  conversation retires at the cutover, and the other two retire, the act §5:9
  retires being the whole of the one and the reason for the other (ADR-0313 §3:1,
  §5:1). §5:11's naming of `converse_spoken`'s `SpokenTurn` among the members that
  stay. Every other clause stands, §5:11 included, which ADR-0313 answers.
  This replacement takes effect on ratification of ADR-0313. This reciprocal header
  record accompanies the numbered draft under ADR-0070 and ADR-0082; prior
  supersessions and the ratified body below are preserved.

## Context

**The proposal.** #2723 sets out how an activation goes from understood to done, and how
the old turn loop gives way. ADR-0306, ADR-0307 and ADR-0308 decided the phases. Each says
no lane implements it until the cutover decision has merged (ADR-0306 §1:2, ADR-0307 §1:2,
ADR-0308 §1:2), and each leaves this decision a piece: where the planning, recall and
digesting rows sit in the controller's table (ADR-0307 §10:2, ADR-0308 §2), how the step
that runs a round's calls runs acting and its digests side by side (ADR-0308 §4), and
retiring the code for quotes, stated bounds, charges and the recipient grant's
establishing act (ADR-0306 §4:12).

**What is built, at `edd58306`.** The controller (ADR-0280) runs every channel activation
by its table: the conversation resolved, routing, the windows, recall, understanding, the
story links, then the old path's stages, which are the event summary, goal association,
disambiguation, reconciliation, the turn loop, the drive and the compose stage.
`AssistantEngine.resume` runs a parked step outside the controller and records its stages
(ADR-0284 §5). The phases' modules do not exist yet. The live hub runs this code with
M42's story pages undeployed.

**The owner's rulings, 2026-10-11.** Each clause below that records a ruling states it as
ruled. The clauses that settle what the rulings leave open are listed as such in the pull
request.

## Decision

We will build each phase as its own controller stage beside the old path, with nothing
switched on; check a thin path through all four on the test hub first; then switch the
controller over to the table below and delete the old path in several lanes; and take
M42, the phases and authority live together in one deploy on a fresh data directory.

### 1. Status, scope and delivery

> **Normative.** This document remains `Proposed` until the reviews
> `CONTRIBUTING.md` → "Finishing an ADR PR" requires have returned green on one tree
> and the owner's authorization to ratify stands; an assigned number or a green review
> alone does not change its status.

> **Normative.** The build lanes of ADR-0306, ADR-0307, ADR-0308 and this decision start
> once this decision has merged `Accepted`, and not before.

> **Normative.** Each decision §8 supersedes, whole or in part, keeps binding the old
> path's code it governs until the lane that removes that code merges, and no lane builds
> on it meanwhile.

### 2. How the phases are built

> **Normative.** Replace, don't adapt: the phases are built as new controller stages
> beside the old ones, and each lane merges with nothing switched on. The cutover switches
> the controller's rules over and deletes the old path.

> **Normative.** Each phase is one module in `orchestration/`, using ADR-0280 §3:2's stage
> interface: recall, understanding, planning, authorizing, acting and digesting. Phases
> meet only in the episode's working set
> ([#2598](https://github.com/leonapivato/ai-assistant/issues/2598)).

> **Normative.** An import-linter `independence` contract forbids one phase module
> importing another. The first build lane adds it over `orchestration.recall`,
> `orchestration.understanding` and the phase modules it builds, and each lane that adds a
> phase module adds that module to it.

> **Normative.** `engine.py` only builds the phases and hands them to the controller.
> Primitives inside `engine.py`, `loop.py` and `runner.py` move into their own modules, in
> the lanes that need them.

> **Normative.** One run of a phase is one short step, so a stop lands after the current
> step (ADR-0297).

> **Normative.** Until the switch lane merges, the composition root hands the controller
> §3's table only where an opt-in read from `Settings` is set, and it is unset by default.
> Only a test hub sets it. The switch lane makes §3's table the controller's only table and
> removes the opt-in.

### 3. The controller's table

> **Normative.** The controller the switch lane leaves runs these rules, in this order, and
> the first that answers decides (ADR-0280 §3:3):

| # | Rule | Answers when | Makes due |
| --- | --- | --- | --- |
| 1 | `conversation_unresolved` | As ADR-0280 §4:3 states | `begin_conversation` |
| 2 | `windows_unassembled` | As ADR-0282 §3 states | `windows` |
| 3 | `not_recalled` | As ADR-0281 §2:3 states | `recall` |
| 4 | `not_understood` | As ADR-0280 §4:3 states | `understanding` |
| 5 | `story_links_unrecorded` | As ADR-0300 §6:11 states | `story_links` |
| 6 | `understood_not_recalled` | As ADR-0308 §2:9 states | `recall` |
| 7 | `recall_undigested` | As ADR-0308 §4:5 states | `digesting` |
| 8 | `first_round_due` | As ADR-0307 §8 states | `planning` |
| 9 | `round_unauthorized` | The latest round has a call or text, and there is no authorizing decision for it | `authorizing` |
| 10 | `round_authorized` | The latest round's authorizing decision allows a call or its message, and there is no acting decision for that round | `acting`, with `digesting` beside it (§3:3) |
| 11 | `round_limit_reached` | As ADR-0307 §8 states | the end of the pass |
| 12 | `round_due` | As ADR-0307 §8 states | `planning` |
| 13 | `nothing_due` | Always | the end of the pass |

> **Normative.** `ControllerStage` gains `authorizing` and `acting`, and `ControllerRule`
> gains `round_unauthorized` and `round_authorized`. The working set gains, for each
> round, the authorizing decision and the acting decision, each present once its stage has
> run, whatever came of it (ADR-0280 §3:6).

> **Normative.** Under `round_authorized` the controller runs one step in which `acting`
> and `digesting` run side by side, where a call the round allows declares a result that
> may carry outside text, and `acting` alone otherwise. Acting adds each result it records
> to the working set (ADR-0308 §6:1), and digesting digests each one that carries outside
> text as soon as it is added (ADR-0308 §4:2), ending once acting has ended and every such
> result is digested or its deadline has passed (ADR-0307 §8:2).

> **Normative.** That step ends when both stages have ended, and each records its own stage
> entry, due `round_authorized`. Where acting fails or times out, digesting is cancelled
> and the step ends under the controller's fixed default (ADR-0280 §5:2); a digest that
> fails is digesting's own, which is failure-tolerant (ADR-0308 §4:12).

> **Normative.** Authorizing and acting each run at most once per round, and digesting at
> most once per round and once for recall's digest; ADR-0280 §4:6's guard ends a pass that
> would run one of them again for the same round or the same digest.

> **Normative.** `ControllerStage` loses `routing`, `event_summary`, `associate_goal`,
> `ask_disambiguation`, `reconcile`, `turn_loop`, `drive` and `compose`, and
> `ControllerRule` loses their rules, `route_unchecked`, `route_taken`,
> `event_unsummarized`, `association_due`, `disambiguation_raised`,
> `continuing_unreconciled`, `unplanned`, `plan_has_steps` and `reply_owed`, and
> `park_answered`, the rule that continues a parked `drive` or `routing` stage. Their
> removal is a recorded exception to *added to and never renamed*: the data directory is
> fresh, so nothing stored names them.

> **Normative.** `StageEntry` loses `step_disposition` and `route_outcome`, which are
> admitted on a `drive` or a `routing` entry alone, with those stages.

Every row the table keeps is placed as its own decision placed it; the old path's rows
leave from between them. Recall's second run and its digest come after the story links
because both read the understanding those links follow from, and before the first round
because planning reads both (ADR-0307 §8:6). Authorizing is a step of its own, so that the
stories a round's calls are matched against are taken once, before any call runs
(ADR-0306 §5:10), and so that its module never imports acting's. The round limit is read
before `round_due`, so a round past the limit ends the pass instead of running.

### 4. Delivery

> **Normative.** The first build lane is the thin path, on the test hub. It builds one
> planning round, authorizing, acting and digesting, with one capability of each effect
> kind, at least one of them able to carry outside text, and it is checked before the
> other phase lanes are built.

> **Normative.** The thin path's three capabilities are the web search, whose effect is
> none and whose result may carry outside text; remembering, whose effect is the
> assistant's own records (ADR-0306 §3:2); and the simulated booking provider's booking
> act (ADR-0273), whose effect is the world, configured on the test hub alone.

> **Normative.** Each triad ADR-0306 §6:1 and ADR-0307 §10:1 name lands in the lane they
> name, so the thin path lands those its four phases need.

> **Normative.** The other phase lanes are cut once the thin path has been checked.

> **Normative.** The cutover is several lanes. The switch lane switches the controller's
> rules over (§2:6), so the new path runs on the test hub. Deletion lanes then remove the
> old path by area: the engine surface, the CLI and the gateway; the orchestration
> modules; and the stores and types.

> **Normative.** Nothing deploys until every cutover lane has merged.

### 5. What retires

> **Normative.** What retires is the list in the proposal's §7, from its survey of
> `8fe54b36`. It is checked again against `main` when the cutover lanes start, and each
> item is confirmed by the lane that removes it. A lane that finds code only the old path
> uses, and the list does not name, removes it with its area and says so in its pull
> request.

The list, by area:

- **Engine surface.** Retire `converse`; `resume`, `pending_confirmations`, `cancel_read`;
  `goals`, `withdraw_clarification`, `abandon_goal`; `standing_authorizations`,
  `revoke_authorization`; and `answer` with `questions`, `interrupted_questions` and
  `forget_question`. Rework `converse_spoken`, `grantable_decisions`,
  `establish_recipient_grant`, `purge_expired` and `start`.
- **Orchestration.** Retire `loop`, `composing`, `goals`, `interpretation`, `questions`,
  `parked_reads`, `routing` (with `permissions/routing.py`), `reconciling`, `verification`,
  `charges`, `quotes`, `stated_bounds`, `validating`, `authorizing` and
  `authorization_surface`; in `planning/`, `associator` and `goals`. Rework `engine`,
  `runner`, `executor`, `reads`, `writes`, `consolidation`, `recipient_grants`, `effects`,
  `disclosure`, `chat`, `conversations`, `activation_state`, `speech`, `controller` and
  `understanding`.
- **Stores.** Retire the deferral store; parked reads; goal authorizations, quotes and
  coverage; the routing trail; and `PlanStore`'s goal, attempt, interpretation,
  intended-action, quote, question and evidence members. Rework `save_plan`, `get_plan`,
  `commit_transition` and `export`, the permission policy, and the audit trail's goal
  fields.
- **Types.** The goal, attempt, intended-action, quote, goal-authorization, park,
  turn-outcome, routing, deferral-question and verification families, with their codecs
  and fakes.
- **CLI.** `ask`, `resume`, `cancel-read`, `goals`, `withdraw-clarification`,
  `abandon-goal`, `questions`, `answer`, `forget-question`, `authorizations` and
  `revoke-authorization`.
- **Gateway.** The Ask, What happened, confirmations, questions, goals and authorizations
  panels and their routes.

> **Normative.** `PlanStore.claim_effect`, `EffectKey`, `EffectClaim` and `EffectRecord`
> retire with the goal-scoped claim, as ADR-0306 §6:1's table leaves them to; the phases
> claim through `claim_activation_effect`.

> **Normative.** No new phase module takes the name of a module this section retires.

> **Normative.** `ask` and the gateway's Ask panel retire. `assistant chat` and the
> gateway's chat (ADR-0293) are the way to talk to the assistant.

> **Normative.** `receive` stays (ADR-0292 §13:1), and an event runs through the phases
> like any activation. The event-summary stage retires.

> **Normative.** An event cannot message the user (ADR-0307 §3:8).

> **Normative.** The notification route, the upcoming-events producer and the delivery
> outbox survive the cutover.

> **Normative.** The interim tidy-up, `story_tidy_up_interim.py`, is deleted by the switch
> lane. Planning's tidy-up call replaces it (ADR-0307 §7).

> **Normative.** Of what ADR-0306 §4:12 leaves here, the `quotes`, `stated_bounds` and
> `charges` modules retire with their stores and types, and the recipient grant's
> establishing act retires from the engine surface's reworked grant members. The
> authority milestone redoes them.

> **Normative.** For an activation the phases plan, ADR-0204 §2's two terms are evaluated
> over the memory records and context facets the activation was given or obtained: its
> windows' records, what either recall run kept and what its calls returned, digested
> ones included. On a pass whose output channel's audience is unbounded the windows'
> records are left out, as ADR-0210 §1:1 leaves out the conversation's own turns, and on
> any other pass nothing is left out (ADR-0210 §1:5). The value is taken once, at
> capture, over every round, and written as ADR-0217 §3:12 writes it.

> **Normative.** Each `AssistantEngine` member that stays and whose signature or result
> carries a type §5 retires, `converse_spoken`'s `SpokenTurn` and `receive`'s
> `ChannelResult` among them, changes under its own ADR, merged before the lane that
> changes it (golden rule 5).

### 6. One cutover

> **Normative.** One deploy takes M42, the phases and the authority milestone live
> together, on a fresh data directory. Nothing on the live hub carries over.

> **Normative.** Until that deploy, the live hub keeps today's behaviour and is not
> redeployed.

> **Normative.** The deploy waits for the phases' acceptance run on the test hub (#2815)
> and for the authority milestone's.

> **Normative.** No lane writes a migration, a reader or a shim for a store written before
> the cutover.

> **Normative.** Learning follows the cutover as its own milestone. Until then, planning's
> remember call is the phases' one writer of beliefs, as nothing learns in the background
> today.

> **Normative.** Consolidation stays off by default. Its rework reads only an episode's
> text, never held results (ADR-0308 §6).

### 7. The code it binds

| Code | Change |
| --- | --- |
| `ControllerStage`, `ControllerRule` | Lose the members §3:6 names; gain `authorizing`, `acting`, `round_unauthorized` and `round_authorized` |
| `StageEntry` | Loses `step_disposition`, `route_outcome` and the validator admitting them |
| `orchestration/controller.py` | `ACTIVATION_RULES` becomes §3's table; a rule may name a stage run beside the one it makes due (§3:3) |
| `ActivationState` | The working set gains each round's authorizing and acting decisions, and loses the decisions of the stages §3:6 removes |
| `pyproject.toml` | A new import-linter `independence` contract over the phase modules (§2:3) |
| `Settings` | Gains the opt-in §2:6 names, which the switch lane removes |
| `story_tidy_up_interim.py` | Deleted by the switch lane |
| `AssistantEngine`, `PlanStore`, the `Protocol`s and types §5 lists | Retire or are reworked as §5 lists, in the deletion lane of their area |
| `receive` | Reworked: an event runs through the phases, and the event-summary stage retires |
| `PROTOCOL_VERSION` | Advances in each lane that changes a shape the wire carries (ADR-0124 §9) |

> **Normative.** The additions the table names land with the lane that first runs them:
> the thin path adds `authorizing`, `acting`, `round_unauthorized`, `round_authorized`,
> the working set's two decisions and the opt-in. The removals land in the cutover lane
> of their area. Each lands with the conformance suites and canonical fakes that cover
> what it changes.

### 8. Relationship to earlier decisions

| Earlier decision | What changes |
| --- | --- |
| ADR-0078, ADR-0197, ADR-0198 | Whole: deferred memory questions with `answer`, and routing with its parks, retire |
| ADR-0158 | Every clause but §2:2: the answering prompt's episodic supplement goes with the answering prompt; no caller mixes `EPISODIC` with belief kinds in one band read |
| ADR-0224, ADR-0229 | Whole: the supplement's size and the planner's citation hop go with the turn loop |
| ADR-0204 §2:1 | Its site and timing, for an activation the phases plan: §5:10 evaluates over what the activation was given or obtained, at capture; the two terms, the field and §§3–5 stand |
| ADR-0210 §1:1–§1:2 | The set they name, for an activation the phases plan: §5:10's set replaces the turn's relevance reads, and leaves the windows out on an unbounded pass as §1:1 leaves out the conversation's own turns. §1:3–§1:5 stand, the bounded pass's whole supply included |
| ADR-0248–ADR-0256, ADR-0258, ADR-0259, ADR-0261, ADR-0262, ADR-0264–ADR-0271 | Whole: the goal and attempt model retires |
| ADR-0257, ADR-0272 | Nothing: the mark grammar and the trail's configured-provider fact are not the goal and attempt model |
| ADR-0260 §7–§10 | The forecast read's place in the turn loop: its servicing, its outcome among ADR-0251's, its evidence row and the turn's statement. Its seam, records, egress and settings stand; whether it survives as a capability is [#2593](https://github.com/leonapivato/ai-assistant/issues/2593)'s |
| ADR-0273 | What it declares and reads for the goal model: the quote and verification outputs §2 declares with §2:19, §2:21 and §2:22, §4's ground in ADR-0259, and §7. The provider, its store and its other declarations stand |
| ADR-0274 §7 | Its informational processing, in its summary stage: an event runs through the phases |
| ADR-0280 §1:4 | Its resume clause: `resume` retires, and every channel activation runs through the controller |
| ADR-0280 §2:1, §2:3, §3:5, §3:7, §4:5, §4:7 | Routing, association, the old path's decisions and stages, the composition sentence and the attempt's bookkeeping go; the removed members' limbs alone, where a clause has others |
| ADR-0280 §3:3 | For the round's step: `acting` and `digesting` run side by side (§3:3–§3:4) |
| ADR-0280 §4:1–§4:3, §4:8 | The members §3:6 removes and §3:2 adds; §3's table replaces §4:3's; §4:8's *their enum members remain, unused* gives way to the removal |
| ADR-0280 §4:6 | The loop guard, for authorizing, acting and digesting: once per round each, and digesting once more for recall's digest (§3:5) |
| ADR-0284 §5:1–§5:2, §5:4–§5:5 | The verdict fields leave with `drive` and `routing`, and the resume record with `resume` |
| ADR-0292 §13:1 | For `resume` alone: it retires though the push its row names is not built, since the phases park nothing (ADR-0306 §4:8) |
| ADR-0306 §1:2, ADR-0307 §1:2, ADR-0308 §1:2 | Nothing: this is the decision they wait for |
| ADR-0306 §4:12, ADR-0307 §10:2, ADR-0308 §2, §4 | Nothing: §5:9, §3 and §3:3–§3:4 settle what they leave here |

Once the switch lane merges every activation is one the phases plan, so each replacement
ADR-0306, ADR-0307 and ADR-0308 make for such an activation reaches every activation, and
the clauses they replace bind only the old path's code until the deletion lanes remove it.

> **Normative.** This numbered draft records its replacements on the status lines and in a
> dated header note of each ADR this section names as changed, atomically with this ADR
> under ADR-0070 and ADR-0082, preserving their ratified bodies. The replacements take
> effect on this ADR's ratification.

## Consequences

**What becomes possible.**
- The phases are built and checked on a test hub while the live hub keeps working.
- The old path leaves in one switch and a few deletions, never half-adapted.
- One table says what an activation does next, with no stage that exists for one channel.

**What it costs.**
- Until the cutover deploy, nothing new reaches the live hub, M42 included.
- Nothing on the live hub carries over.
- A call that needs you is declined until the authority milestone, which the deploy waits
  for.

**What stays open.**
- Timers and watches, events as their own spokes, activations side by side, and
  authority, each its own milestone; learning follows the cutover as its own.
- The results of the `AssistantEngine` members that stay but carry a retiring type, each
  under its own ADR (§5:11).
- The numbers ([#2589](https://github.com/leonapivato/ai-assistant/issues/2589)).
- Which read capabilities survive
  ([#2593](https://github.com/leonapivato/ai-assistant/issues/2593)).

## Alternatives considered

- **Adapting the turn loop step by step.** Rejected: every step would keep goals, attempts
  and parks consistent with the new pieces.
- **One cutover lane.** Rejected: deleting the old path is too large for one change.
- **Carrying the live hub's data over.** Not done: the cutover starts fresh, as earlier
  cutovers did.
- **Learning in the cutover.** Not done: it would delay the cutover further, and
  remember-only is what the hub does today.
- **Keeping the old members, unused, under *never renamed*.** Rejected: nothing stored names
  them, and an unused member invites a rule to read it.
- **Authorizing and acting as one stage.** Rejected: the stage would carry two phases, one
  module would import the other, and the stories a round is matched against would be taken
  inside the step that runs its calls.
- **Digests as their own step after acting.** Rejected: a digest starts as soon as its
  result arrives (ADR-0308 §4:2), not after the slowest call.
