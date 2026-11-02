# 306. A capability declares what its calls do, every call is checked by rule, and acting claims and records what it does

- Status: Partially superseded by ADR-0307 (§6:1's `ActivationEffect`, in the addition alone: it also names the round whose call or message it claims) and ADR-0312 (§2:5's first limb: a side-effecting declaration with effect none validates where it writes nothing and discloses something) and ADR-0321 (§4:3's planning limb; §4:8, in the addition alone; §4:12's *the authority milestone redoes them*; §5:3, in the addition alone; §5:9, §5:11 and §5:13 for a deliberate repeat matching an unknown or unwritten effect; §6:1's `ActivationEffect` and `ActivationEffectClaim` rows and §6:2's claim, in the additions alone) and ADR-0329 (§3:2 whole; §4:3 in what remains in force; §4:8's and §4:9's limbs for a memory `MemoryPolicy` rules on) and ADR-0332 (§5:1, in the addition alone: a round a join set aside runs none of its calls) and ADR-0350 (§4:7, for an activation the Task Scheduler starts; §5:6's *never resolved by guessing* and §5:13's *never retried, done another way*, for that activation's message alone; §6:4, in the addition alone) and ADR-0351 (§4:5 and §4:6, each in the addition alone: the relay mark) and ADR-0356 (§4:7's *the round's own message* and §5:3–§5:5's *message*, each in its subject alone: a `text` call) and ADR-0361 (§4:7's *the place the input came from*, in the addition alone: or a place an input taken by a take came from) and ADR-0364 (§4:7's one place, outside a task's work and an approval's; §4:8's *needing you* and §4:9's *not done*, each in the outcome planning is shown)
- Date: 2026-10-11
- Scope: the phases after understanding ([#2723](https://github.com/leonapivato/ai-assistant/pull/2723)), milestone M43 ([#2815](https://github.com/leonapivato/ai-assistant/issues/2815)), the first of their four decisions: what a capability declares, how the assistant's own records are declared, how authorizing checks a call until the authority milestone, and how acting runs, claims and records calls. The planning decision, the digesting decision and the cutover decision are the other three.
- Dependency: the story calls ADR-0300 §10, ADR-0303 §9 and ADR-0304 §9 declare, and ADR-0297's stop, all implemented at `5166d5bc`.
- Authorization: the owner accepted proposal #2723 on 2026-10-11 and, the same day, ruled this decision's content in a pass over it. The dispatcher assigned 0306. This ADR is the proposal's §4 and §5 converted under `docs/proposals/README.md` → "When it is decided". Those rulings authorize ratifying it once its reviews are green, for as long as it settles only what they leave open.
- **Changes `core`, so it is a contract-surface decision.** `ToolDefinition` gains five required fields and `PermissionDecision` one; `PlanStore` gains three members and `PlanExport` one field; four types are new. `ToolDefinition` crosses the wire, so `PROTOCOL_VERSION` advances (§6).
- **Partially supersedes**, each for the calls the phases run alone (§1:3), except the first, which reaches every declaration:
  [ADR-0016](0016-tool-definition-and-registry.md) (§1's `ToolDefinition` field list, in the addition alone);
  [ADR-0037](0037-joining-selection-permission-and-execution.md) (§4: a `CONFIRM` parks the step);
  [ADR-0052](0052-durable-resume-of-a-parked-confirmation.md) (§§1–4: a parked confirmation is resumed on the answer);
  [ADR-0148](0148-an-egress-call-is-authorised-as-one-whole-and-nothing-in-it-moves-after-the-ruling.md) (§8:1's *reached by a `CONFIRM` that parks the step … and answered through an interface*, and §9:1–§9:4's claimed plan step as the egress attempt);
  [ADR-0208](0208-recall-memory-leaves-the-default-tool-set-and-the-turns-supply-is-retrieved-at-one-site.md) (§1:1's *no memory tool is among them*, §1:2, §1:3 and §1:5);
  [ADR-0244](0244-a-confirm-on-a-search-parks-as-a-durable-question-and-the-answer-runs-that-exact-read-once.md) (§1's parked read, and every clause that holds, lists, answers or runs one);
  [ADR-0254](0254-phase-4-validates-the-plan-in-code-and-route-d-authorises-a-concrete-call-against-fixed-values-and-permitted-ranges-from-recorded-acts.md) (§6:1's route (d) and §6:3's setting of `goal`);
  [ADR-0259](0259-an-effect-is-claimed-once-per-goal-before-it-is-dispatched-and-a-turn-start-pass-reconciles-what-an-earlier-turn-left-uncertain-or-unfinished.md) (§1's effect key and §2's claim, in their goal scope);
  [ADR-0265](0265-an-intended-action-has-a-stable-identity-minted-once-and-linked-to-the-goal-elements-it-serves.md) (§6: an effect claim keyed on the intended action);
  [ADR-0292](0292-a-channel-is-the-spokes-facing-one-thing-and-the-assistants-edge-is-its-own.md) (§7:2's choice of place, until the timers and proactivity milestone);
  [ADR-0297](0297-a-stop-is-marked-on-the-activation-and-recorded-where-claims-are-decided.md) (§2:11's *and at no other write*, in the addition alone).
- Partially superseded: 2026-10-11 by ADR-0307 — one scope. §6:1's `ActivationEffect`, in
  the addition alone: it gains `round`, the round whose call or message it claims, `None`
  only on the *couldn't finish* message, and lands with §6:1's triad (ADR-0307 §10). Every
  other clause stands. This scoped replacement takes effect on ratification of ADR-0307.
  This reciprocal header record accompanies the numbered draft under ADR-0070 and
  ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-11 by ADR-0312 — one scope. §2:5's first limb: a
  declaration whose `side_effecting` is true while its effect is none validates where its
  `writes` is empty and its `discloses` is not, so that its one side effect is disclosure,
  as the web search and the forecast are. Its second limb, refusing an effect that is not
  none on a declaration that is not side-effecting, stands, and every other clause stands.
  The build lane builds §2:5 as corrected. This scoped replacement takes effect on
  ratification of ADR-0312. This reciprocal header record accompanies the numbered draft
  under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are
  preserved.
- Partially superseded: 2026-10-15 by ADR-0321 — §4:3's planning limb: a remember `MemoryPolicy` asks about is written on the user's yes, and consolidation's limb stands (ADR-0321 §5). §4:8, in the addition alone: *needs you* is answered by a yes to a question that showed the call, in a new activation, so *nothing resumes it* stands (ADR-0321 §4). §4:12's *the authority milestone redoes them*: the establishing act is replaced by scoped delegations, and quotes, stated bounds and charges are not redone (ADR-0321 §7:1). §5:3, in the addition alone: every call that runs under an approval gets an effect record (ADR-0321 §4:10). §5:9, §5:11 and §5:13: a deliberate repeat matching an unknown or unwritten effect needs the user, its claim passes under an approval, and *never retried* is the assistant's own initiative (ADR-0321 §6). §6:1's `ActivationEffect` and `ActivationEffectClaim` rows and §6:2's claim, in the additions alone: the part key and its refusal (ADR-0321 §4:9, §9). Every other clause stands. This replacement takes effect on ratification of ADR-0321. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-18 by ADR-0329 — §3:2 whole: `remember` records a candidate, and its declaration is restated (ADR-0329 §3:7). §4:3 in what remains in force, and §4:8's and §4:9's limbs for a memory `MemoryPolicy` rules on: no `remember` call passes `MemoryPolicy`, and the observer's writes do (ADR-0329 §5:6, §12:2). Every other clause stands. This replacement takes effect on ratification of ADR-0329. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-21 by ADR-0332 — §5:1, in the addition alone: where acting's commitment step finds joined input the round's understanding does not cover, it dispatches none of the round's calls and not its message (ADR-0332 §3:5, §3:7). Every other clause stands. This replacement takes effect on ratification of ADR-0332. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-25 by ADR-0350 — §4:7, for an activation the Task Scheduler starts: each of its messages goes into the one place on its place list it names, none goes off that list, and with an empty list it writes none (ADR-0350 §6:7). §5:6's *never resolved by guessing* and §5:13's *never retried, done another way*, for that activation's message alone: after a restart, a message whose outcome is unknown or unwritten is confirmed from its place's medium where the place's kind can confirm delivery, and is otherwise tried once more, marked, never a third time and never past the push limit (ADR-0350 §8:6, §8:8, §8:11). §6:4, in the addition alone: a message's record whose outcome is unknown or unwritten may be settled once more, by a `PlanStore` member of its own, to done with its position or to not done, from its place's confirmation (ADR-0350 §8:11, §12:3); `finish_activation_effect` stays write-once. Every other effect keeps both clauses, and every other clause stands. This replacement takes effect on ratification of ADR-0350. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-25 by ADR-0351 — §4:5, in the addition alone: an activation has also read outside content where understanding marks one of its inputs relayed, from the understanding version that marks it (ADR-0351 §5:13). §4:6's *never from a value a model, a tool or a plan emits*, for the relay mark alone: that value, which understanding's reply proposes and code records, can only set the fact and never clear it (ADR-0351 §5:8, §5:13). Every other clause stands. This replacement takes effect on ratification of ADR-0351. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-30 by ADR-0356 — §4:7's *the round's own message* and §5:3–§5:5's *message*, each in its subject alone: a round's text is no message, and the message they govern is a `text` call, checked by its place alone and claimed and recorded as a message, with its place, its position and its round (ADR-0356 §7:7, §7:8). An `email` call is a call in the world, as `send_email` is (ADR-0356 §7:9). Every other clause stands. This replacement takes effect on ratification of ADR-0356. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-31 by [ADR-0361](0361-approvals-are-cards-the-person-taps-and-a-yes-is-a-one-time-ticket-for-the-exact-call.md) — §4:7's *the place the input came from*, in the addition alone: a message may also go into the place an input the activation took by a take came from, where that place takes a message (ADR-0361 §7:3). Every other clause stands. This replacement takes effect on ratification of ADR-0361. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-11-01 by [ADR-0364](0364-tools-describe-themselves-in-four-parts-every-result-opens-with-its-outcome-and-connections-replace-the-place-list.md) — §4:7's one place: a work may send a text into any connection it was shown that takes one, except a task's work and an approval's, which keep their lists (ADR-0364 §9:3–§9:4). §4:8's *needing you* and §4:9's *not done*, each in the outcome planning is shown alone: both come back refused, and the recorded outcome is unchanged (ADR-0364 §6:3). Every other clause stands. This replacement takes effect on ratification of ADR-0364. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.

## Context

**The proposal.** #2723 sets out how an activation goes from understood to done: planning
proposes a round of native tool calls, authorizing checks each call by rule, acting runs
the allowed ones, digesting turns outside content into evidence, and the old turn loop
gives way. The owner accepted it on 2026-10-11, to be converted into four ADRs in order.
This is the first, and carries the proposal's §4 (authorizing) and §5 (acting). What a
round is, what a digest does and how lanes are cut are the other three's.

**What is built, at `5166d5bc`.**

- `ToolDefinition` (ADR-0016) declares a tool's risk, reversibility, whether it is
  side-effecting, the data tiers it reads, writes and discloses, its cost and its retry
  guarantee (`idempotency`). Every field a permission decision reads is required.
- `ActionPolicy` (ADR-0021 §3) rules `ALLOW`, `CONFIRM` or `DENY` on an `ActionRequest`.
  `ThresholdActionPolicy` implements it over thresholds, standing recipient grants, the
  configured search and forecast destinations, and the goal-scoped authorizations and
  quotes (`GoalAuthorizations`, ADR-0254; `GoalQuotes`, ADR-0267 §5) that route (d) reads.
  `MemoryPolicy` disposes of a proposed memory: accept, reject, ask the user and the rest.
- Selection picks one tool (ADR-0144); the decision is recorded and read back before the
  claim (ADR-0037 §2–§3). A `CONFIRM` parks the step (ADR-0037 §4) and the user's answer
  resumes it (ADR-0052, ADR-0148 §8:1, and ADR-0244 for a search).
- A call planned over recorded external content carries `planned_with_external_content`
  on its `EgressBinding` (ADR-0181 §2–§4), and no standing permission covers it (ADR-0181
  §5:2), except a search at the configured provider (ADR-0247 §3).
- An effect is claimed once per goal and intended action by `PlanStore.claim_effect`,
  under an `EffectKey`, answered by an `EffectClaim` and kept as an `EffectRecord`
  (ADR-0259, ADR-0265).
- A stop is recorded in the plan store and refuses the step claim (ADR-0297).

**What the phases need instead.** No goal, no plan step and no park. Planning's calls are
offered by capability (ADR-0211), and the story calls M42 built wait for "the declaration
form the phases' decision gives capabilities" (ADR-0300 §10:6, ADR-0303 §9:2). Authority,
meaning reading your yes and tracing where a value came from, is its own next milestone; until
then the built lineage rule stands in for it, and a call that needs you is declined plainly.

**The owner's rulings, 2026-10-11.** Each clause below that records a ruling states it as
ruled. The clauses that settle what the rulings leave open are listed as such in the pull
request.

## Decision

We will declare five more properties on every tool and read every rule from them; check
every call by rule, in a fixed order, with the built lineage rule standing in for
authority; and run a round's allowed calls in parallel, claiming those in the world and
the messages before they run, recording each effect against the activation that made it,
and refusing a repeat its capability says is unsafe.

### 1. Status, scope and delivery

> **Normative.** This document remains `Proposed` until the reviews
> `CONTRIBUTING.md` → "Finishing an ADR PR" requires have returned green on one tree
> and the owner's authorization to ratify stands; an assigned number or a green review
> alone does not change its status.

> **Normative.** No lane implements this decision until it has merged `Accepted` and the
> cutover decision has merged. Its lanes are cut then, and the first build lane is the
> thin path the cutover decision names.

> **Normative.** Every earlier clause this decision replaces, except ADR-0016 §1's field
> list, is replaced for the calls the phases run and for no other. The old turn loop
> keeps those clauses until the cutover decision removes it.

### 2. What a capability declares

| Property | Values |
| --- | --- |
| **Effect** | none / the assistant's own records / the world |
| **Leaves the hub** | yes / no |
| **Result** | none / no outside text / may carry outside text |
| **Outcome can be unknown** | yes / no |
| **Safe to repeat** | yes / no |

> **Normative.** Each tool's declaration, `ToolDefinition` (ADR-0016), declares the five
> properties the table names, each with exactly the values the table gives, beside the
> risk, reversibility, data tiers, cost and retry guarantee it declares already, which
> the permission policy keeps reading.

> **Normative.** All five are required, with no default: a declaration missing one does
> not validate, so an undeclared tool is never offered to planning.

> **Normative.** Safe to repeat is its own property and not the retry guarantee: no rule
> reads `idempotency` for whether a call may be repeated with the same values, and no
> rule reads safe to repeat for whether one call may be retried.

> **Normative.** The hub writes the declarations. A tool's own description of itself,
> such as an MCP server's annotations once MCP exists, is a hint to whoever writes the
> declaration, and no rule reads it.

> **Normative.** A declaration whose `side_effecting` is true while its effect is none,
> or false while its effect is not none, does not validate.

> **Normative.** A declaration whose outcome cannot be unknown, whose effect is not the
> assistant's own records, and whose `interrupted_outcome` is `indeterminate` does not
> validate.

> **Normative.** Every tool satisfying one capability declares the same five properties,
> and the hub offers planning no capability whose tools disagree.

> **Normative.** Planning is offered capabilities, as ADR-0211 decides. Tool selection
> picks the tool before authorizing, and every rule this decision states reads that
> tool's declaration.

> **Normative.** The hub adds to each capability it offers planning a required *looking
> for* argument where its result may carry outside text, and a *deliberate repeat* mark
> where it is not safe to repeat.

> **Normative.** The hub removes the *looking for* argument and the *deliberate repeat*
> mark before the tool is invoked. Neither, nor any argument the declaration names in
> `system_supplied`, is among the values §5's backstop compares.

The table is what every rule below reads. Effect decides claims, effect records and what
is reported as done in the world; leaving the hub decides the outside-content stand-in;
the result decides the *looking for* argument and where a result goes; an unknown outcome
is never retried; safe to repeat decides the backstop. The last two clauses before this
paragraph keep one capability's offered arguments true whichever tool selection picks, and
keep a value no planner wrote from making two equal calls look different.

### 3. The assistant's own records

> **Normative.** The story calls ADR-0300 §10, ADR-0303 §9 and ADR-0304 §9 declare have
> the assistant's own records as their effect, never leave the hub, and never have an
> unknown outcome. Starting a story and grouping stories are not safe to repeat, and every
> other story call is. Reading a story returns no outside text and shows its marks, and
> every other story call returns none.

> **Normative.** Remembering has the assistant's own records as its effect and is not
> safe to repeat, so §5's backstop stops the same memory being written twice in a matter.
> It never leaves the hub, its outcome is never unknown, and it returns none.

> **Normative.** A call whose effect is the assistant's own records, and a read of them,
> runs directly against the store it reaches (ADR-0292 §12:1, §12:3), not through
> `ToolInvoker`. No deadline or cancellation cuts it short: it is awaited to its end, and
> its outcome is what that store answered.

> **Normative.** A memory search, and a pull such as the calendar, each declare a result
> that may carry outside text. This is the decision ADR-0208 §1:2 asks for: planning may
> call a memory search.

`interrupted_outcome` classifies a call the invocation seam cut short (ADR-0029 §4,
ADR-0031 §1). A call to the assistant's own records is never such a call, which is how
*never unknown* holds for a story start or a remembered fact that is not safe to repeat.
§2's validator keeps every other declaration honest against that classification.

Reading a story is declared with the class's effect, as ADR-0300 §10:5 already declares
it. The read writes no effect record, being safe to repeat and not in the world, so the
property moves nothing for it. A memory search's and a pull's other four properties are
each declaration's, under §2. Which read capabilities survive is open (#2593).

### 4. Authorizing

> **Normative.** Every call, the assistant's own records included, is checked by rule
> with no model, in this order: the policy; the outside-content stand-in; and, for a
> message, the message place. A call runs only where every check that applies to it
> allows it.

> **Normative.** The policy is `ActionPolicy`. It rules allow, confirm or deny, with
> standing grants counting, and a deny runs nothing and asks nothing.

> **Normative.** Remembering also passes `MemoryPolicy`. Memory it rules to ask about is
> not written, by planning or by consolidation, until the authority milestone.

> **Normative.** The stand-in is the built lineage rule, ADR-0181 §5:2 with ADR-0247 §3's
> exception for a search at the configured provider: a call to a capability that leaves
> the hub, planned in an activation that has read outside content, gets no standing
> permission and needs the user, with its values shown.

> **Normative.** An activation has read outside content when its record says so: an
> outside trigger, digested evidence, or a marked summary or note (ADR-0303 §3).

> **Normative.** That fact reaches the policy as `planned_with_external_content` on the
> call's `EgressBinding`, computed under ADR-0181 §4 over the activation's whole record,
> every round included, and never from a value a model, a tool or a plan emits.

> **Normative.** The round's own message is checked by its place alone: it goes only into
> the place the input came from, and the outside-content rule never applies to it.

> **Normative.** Confirm means *needs you*. A call the policy rules confirm, one the stand-in
> sends to the user, and a memory `MemoryPolicy` rules to ask about each runs nothing,
> parks nothing and goes back to planning as needing you; nothing resumes it.

> **Normative.** A call the policy denies, and a memory `MemoryPolicy` rejects, runs
> nothing and goes back to planning as not done, with the reason.

> **Normative.** Tool selection runs first, and the decision is recorded and read back
> before anything runs, as ADR-0037 §2–§3 decide.

> **Normative.** The policy reads no goal authorization and no goal quote: a call the
> phases run carries no `goal` and no `intended_action` on its `ActionRequest`, and the
> policy the phases are built with holds neither `GoalAuthorizations` nor `GoalQuotes`.

> **Normative.** No lane carries quotes, stated bounds, charges or the recipient grant's
> establishing act into the phases. The authority milestone redoes them, and retiring
> their code is the cutover decision's.

What planning says about a call that needs you, which is that it cannot be done yet, is
the planning decision's. The authority milestone gives that call an answer, and its values
are what the user is shown when they are asked. Until then, a story
keeps its mark ([#2798](https://github.com/leonapivato/ai-assistant/issues/2798)), so
every call that leaves the hub in a matter outside content once touched needs you. That
is expected. The message is held to its place and not to the stand-in because otherwise
every answer after a web search would need you.

### 5. Acting

> **Normative.** A round's allowed calls run in parallel, with no model, and each outcome
> is done, not done with its reason, or unknown.

> **Normative.** Calls in the world, and messages, are claimed before they run, under
> ADR-0297's stop: a stop refuses what is not yet claimed, what is claimed finishes, and
> nothing new starts.

> **Normative.** An effect record is written durably as each effect happens, pointing at
> the activation that made it (ADR-0300 §8:2): for every call in the world; for every
> message, with its position in the place, so the place window links it to its activation
> (ADR-0303 §7:1); and for every call to a capability that is not safe to repeat.

> **Normative.** A call or a message that gets an effect record is claimed by writing that
> record before it runs, with no outcome and, for a message, no position, in one
> indivisible plan-store step that also decides the stop and §5's backstop.

> **Normative.** When the effect happens, its outcome is written onto the record, and for a
> message the medium recorded, so is the position the medium returned for it. A message
> not done, or whose outcome is unknown, carries no position.

> **Normative.** A claimed record given no outcome, as after a crash, is never resolved by
> guessing and never reported as done. How it is recovered in detail is #2584's; for a
> call to the assistant's own records, the recovery reads the store the call wrote.

> **Normative.** A call that leaves the hub transmits as ADR-0231 §6 decides for a search:
> its attempt and its outcomes are its `InvocationLedger` claim and completion (ADR-0192
> §3), taken from the recorded decision, and no plan step is claimed.

> **Normative.** Where such a call also gets an effect record, that record is claimed before
> the invocation, names the deciding `PermissionDecision`, which names the record, and
> carries the outcome the invocation completed with.

> **Normative.** A call to a capability that is not safe to repeat is refused as *already
> done* where its capability and values match an effect of this activation or of the
> activations of the episodes in this activation's stories, unless planning marks it a
> deliberate repeat and every matching effect is done. An activation in no story is matched
> against its own effects alone.

> **Normative.** The stories a round's calls are matched against are this activation's
> stories as they stand when the round's calls are authorized. A story call in the same
> round changes them from the next round on.

> **Normative.** For that match an unknown outcome counts as done, and so does an effect
> claimed whose outcome is not yet written; an effect not done does not count. A deliberate
> repeat never passes a matching effect that is unknown or not yet written.

> **Normative.** For a call that leaves the hub, its values include its binding's
> `account`, `transport_endpoint` and `canonical_destination_set`, the three facts
> `EffectKey` takes from it (ADR-0259 §1), so the same arguments sent to another account
> or destination are another effect.

> **Normative.** An unknown outcome is never retried, done another way, or reported as
> done.

> **Normative.** A result that may carry outside text is routed record by record, by who
> wrote the text: text someone other than the user or the assistant wrote goes to a
> digest (the digesting decision), and the rest goes to planning. For a web search that is
> all of it; for a memory search it is the records whose stored source is outside. A
> result declared to carry no outside text goes to planning whole.

> **Normative.** A record whose writer is not known counts as outside. A result returned
> through `ToolInvoker` is one record whose writer is not known.

> **Normative.** A direct read of the assistant's own records is routed by each record's
> stored provenance: a memory record's source is outside where ADR-0106 §1's
> `rests_on_recorded_external_content` holds for it, and a record that carries no
> provenance is outside.

> **Normative.** No lane adds a lock under this decision; locks come with the concurrency
> milestone.

The backstop is ADR-0259 and ADR-0265's effect key, scoped by the stories' episodes
instead of the goal. An effect points at its activation and never at a story, so a split,
a merge, a move or a corrected link carries it with its episode, and a second booking in
a split-off matter is still caught. Counting an unfinished claim as done is what catches
two equal calls in one round, which run in parallel. With no activations side by side
until the concurrency milestone, only the round's own story calls can move its stories
while it runs, and taking the stories once, when the round is authorized, makes the match
the same however the round's calls interleave. What that leaves is a merge, move or link
in one round and, in the same round, a repeat of an effect the joining story already
holds. Planning was shown both stories to make that change, with what each has done
(ADR-0300 §8:1), and the next round's calls are matched against the joined stories.

A claim names its activation and is decided in the plan store, where ADR-0297 records a
stop, so the stop and the backstop are one decision with the write. A message has no
position until the medium has recorded it, since the user may write into the place while
the activation runs (ADR-0293 §6), so the position joins the record with the outcome.
The phases run no plan steps, so the egress attempt ADR-0148 §9 asks for is the
invocation ledger's claim, as ADR-0231 §6 already made it for a search; the effect record
is acting's own, beside it.

### 6. The code it binds

| Code | Change |
| --- | --- |
| `ToolDefinition` | Gains `effect: CapabilityEffect`, `leaves_hub: bool`, `result: CapabilityResult`, `outcome_can_be_unknown: bool` and `safe_to_repeat: bool`, all required (§2:1–§2:2), and the validators §2:5–§2:6 state |
| `CapabilityEffect`, `CapabilityResult` | New closed enumerations: `none`, `own_records`, `world`; and `none`, `no_outside_text`, `may_carry_outside_text` |
| `ActivationEffect` | New frozen record: its id; its activation; for a call, the capability, a digest of its values and the deciding decision's id; for a message, its place and, once the medium has recorded it, its position; its `ToolOutcome` once known (`succeeded` is done, `failed` not done, `indeterminate` unknown); the reason where not done; and when it was claimed |
| `PlanStore` | Gains `claim_activation_effect`, `finish_activation_effect` and `activation_effects`, as §6:2–§6:5 state |
| `PlanExport` | Gains `activation_effects`; `schema_version` advances by one |
| `PlanStore.claim_effect`, `EffectKey`, `EffectClaim`, `EffectRecord` | Unchanged; the old path keeps them until the cutover decision retires them, and the phases do not call them |
| `PermissionDecision` | Gains `effect: DurableIdentifier \| None`, the id of the `ActivationEffect` a phases call is claimed under, minted before the ruling and set on every decision about a call that gets one (§5:7); `authorises` does not compare it |
| `ActionRequest`, `EgressBinding` | Unchanged; a phases call sets no `goal` and no `intended_action`, and its binding's `planned_with_external_content` is §4:6's |
| `ActionPolicy`, `ThresholdActionPolicy`, `MemoryPolicy` | No member changes; the phases build `ThresholdActionPolicy` without `authorizations` and `quotes` |

> **Normative.** The `core` types and `PlanStore` members the table names change, or are
> added, as the table states, and land as one Protocol triad with the conformance suite
> and the canonical fake, in the lane that builds acting.

> **Normative.** `PlanStore.claim_activation_effect(effect: ActivationEffect, /, *,
> match: tuple[str, ...] | None, deliberate_repeat: bool = False) ->
> ActivationEffectClaim` is `async` and writes `effect`, carrying no outcome, in one
> indivisible step: it raises `ClaimStopped` where the store holds a stop record for the
> effect's activation, answers `already_done` and writes nothing where `match` is a tuple
> and a record of an activation it names carries the same capability and values digest
> and an outcome of unknown or none yet, or of done unless `deliberate_repeat` is set, and
> otherwise writes the record and answers `claimed`. A claim of an id the store already
> holds is refused with `PlanningError`, writing nothing.

> **Normative.** Orchestration supplies `match`, and the plan store reads no story: for a
> call to a capability that is not safe to repeat it is this activation's id and the
> activations of the episodes in its stories, collected from the story store when the
> round is authorized, with `deliberate_repeat` set where planning marked it; for every
> other claim it is `None`.

> **Normative.** `PlanStore.finish_activation_effect(effect_id: str, /, outcome:
> ToolOutcome, *, reason: str | None = None, position: int | None = None) -> None` is
> `async` and writes the outcome, the reason where not done, and a message's position, once.
> A record it does not hold, a record already finished, a reason on an outcome other than
> not done, and a position on anything but a message done are refused with
> `PlanningError`, writing nothing.

> **Normative.** `PlanStore.activation_effects(activation_ids: Sequence[str], /) ->
> tuple[ActivationEffect, ...]` is `async` and returns the records of the named
> activations, finished or not, in the order they were claimed.

> **Normative.** The change that adds the five fields to `ToolDefinition` advances
> `PROTOCOL_VERSION`, on ADR-0124 §9's rule, as does any change here to another shape the
> wire carries.

> **Normative.** No stored record written before these fields existed is read under this
> decision; the cutover decision's fresh data directory is what the phases start on.

### 7. Relationship to earlier decisions

| Earlier decision | What changes |
| --- | --- |
| ADR-0016 §1 | The field list gains §2's five, all required; the required-field clause binds them with no exception, and every other clause stands |
| ADR-0037 §4 | For the phases' calls a `CONFIRM` parks nothing and goes back to planning (§4:8); §2–§3's decide, record, read back and claim stand |
| ADR-0052 §§1–4 | For the phases' calls there is no park to resume |
| ADR-0148 §8:1 | Its *reached by a `CONFIRM` that parks the step … and answered through an interface*, for the phases' calls; the user stays the approver, and §3's routes and §8's other clauses stand |
| ADR-0148 §9:1–§9:4 | For the phases' calls the attempt is the call's `InvocationLedger` claim and not a plan step's, as ADR-0231 §6 decides for a search; a call with an effect record also claims it before the invocation, and the record and the decision name each other (§5:7–§5:8) |
| ADR-0181 §4, §5:2 | Nothing: §4:6 computes the fact under §4 over the activation's record, and §5:2 is the stand-in |
| ADR-0208 §1:1, §1:2, §1:3, §1:5 | A memory search is a capability planning may call, so a memory tool is offered, a turn's records are read for relevance at that call as well, and a phase obtains records by a call |
| ADR-0211 | Nothing: planning is offered capabilities |
| ADR-0244 | §1's parked read, and every clause that holds, lists, answers or runs one, for the phases' searches |
| ADR-0247 §3 | Nothing: its exception stays the stand-in's |
| ADR-0254 §6:1, §6:3 | Route (d), and `orchestration` setting `goal`, for the phases' calls; with route (d) goes the policy's only read of a goal quote (ADR-0266 §7, ADR-0267 §5) |
| ADR-0259 §1, §2 | The effect key and the claim, in their goal scope, for the phases' calls; §5:9 matches capability and values within the stories' episodes |
| ADR-0265 §6 | An effect claim keyed on the intended action, for the phases' calls |
| ADR-0292 §7:2 | A message goes only into the place the input came from, until the timers and proactivity milestone |
| ADR-0292 §12:1–§12:3 | Nothing: the assistant's own records are inside actions and direct reads |
| ADR-0297 §2:11 | In the addition alone: the phases' claim is also refused on a stop record (§5:4) |
| ADR-0300 §8, §10; ADR-0303 §7, §9 | Nothing: §3 gives the story calls the declaration form they wait for, and §5:3 is the effect record they read |

> **Normative.** This numbered draft records its replacements on the status lines and in
> a dated header note of ADR-0016, ADR-0037, ADR-0052, ADR-0148, ADR-0208, ADR-0244,
> ADR-0254, ADR-0259, ADR-0265, ADR-0292 and ADR-0297, atomically with this ADR under
> ADR-0070 and ADR-0082, preserving their ratified bodies. The replacements take effect
> on this ADR's ratification.

## Consequences

**What becomes possible.**
- Every rule about a call reads one declaration, written by the hub, so a tool cannot
  talk its way past a check.
- The story calls and remembering are checked and recorded like any other call.
- A duplicate that would cost money or send something twice is stopped mechanically,
  across every episode of the matter, however its story is later split or merged.
- A stop lands cleanly: what is claimed finishes, and nothing new starts.

**What it costs.**
- Until the authority milestone, nothing that needs you can be done: confirm is
  answered with "not yet", and in a matter outside content once touched, every call that
  leaves the hub needs you.
- Every tool declaration and fixture writes five more fields.
- Quotes, stated bounds, charges and the recipient grant's establishing act are out of
  the phases until the authority milestone redoes them.
- A record whose writer is not known is digested, so a tool that does not say who wrote
  its records costs a digest.

**What stays open.**
- How a value's source is traced, replacing the stand-in, and approvals, including those
  found through a story that later merges or splits, and whether the lineage rule should
  relax toward the owner's principle for outside content recorded on #2747. These are
  the authority milestone's.
- Durability of effects and unknown outcomes in detail
  ([#2584](https://github.com/leonapivato/ai-assistant/issues/2584)).
- Which read capabilities survive, and the unbounded-audience gate on reads
  ([#2593](https://github.com/leonapivato/ai-assistant/issues/2593)).
- Locks (the concurrency milestone).
- Timers and watches pointing at what set them and found through the story, as effects
  now are (the timers milestone).
- Finer declarations, such as an invite's title shown marked instead of digested.

## Alternatives considered

- **Safe to repeat read from the retry guarantee.** Rejected: repeating a call with the
  same values is a different question from retrying one call.
- **Taking a tool's own annotations as its declaration.** Rejected: a declaration a tool
  writes for itself is one it can write to get past a check.
- **Effects pointing at the story.** Rejected: a split would leave them behind and let the
  duplicate backstop miss a second booking.
- **Leaving duplicates to planning alone.** Rejected: a mistake costs money or sends
  something twice.
- **Tracing each value's source in this milestone.** Moved to the authority milestone,
  where asking you is designed; the built lineage rule stands in.
- **Authority in this milestone.** Moved to its own milestone, next.
- **The outside-content rule on the round's own message.** Rejected: every answer after a
  web search would need you.
- **A result's shape, structured or unstructured, deciding what is digested.** Replaced by
  who wrote the text: shape mislabels your own free-text notes and an invite's outside
  title.
- **Reworking `claim_effect` in place.** Rejected: the old path keeps its goal-scoped claim
  until the cutover, and the phases are built beside it.
