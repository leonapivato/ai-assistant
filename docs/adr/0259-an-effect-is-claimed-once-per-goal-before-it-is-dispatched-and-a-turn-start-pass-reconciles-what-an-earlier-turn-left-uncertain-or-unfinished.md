# 259. An effect is claimed once per goal before it is dispatched, and a turn-start pass reconciles what an earlier turn left uncertain or unfinished

- Status: Proposed
- **Depends on [ADR-0265](0265-an-intended-action-has-a-stable-identity-minted-once-and-linked-to-the-goal-elements-it-serves.md),
  which is cited and superseded in nothing.** §6 of that decision states four obligations over *"a decision that lands
  the claim"* — the row keyed on the goal, the intended action and the effect key; an answer for a completed act of
  **this** intended action carrying a different key; the claiming plan's `targets_revision` on the record; and the three
  reuse conditions stated as necessary and **not sufficient** — and this decision discharges all four (§2, §9, §13). §4
  of that decision leaves one question here by name, *"whether an effect-bearing dispatch must name one"*, and §2
  answers it **yes**. Every lane of ADR-0265 lands before every lane of this decision (§11).
- **Partially supersedes [ADR-0014](0014-planning-model.md), in three scopes** — **§4's transition
  table** and **§5's `PlanStore` member enumeration, `PlanExport` shape and `delete_goal`
  cascade**, and **§3's `StepExecution` record** in the marks it requires of a `SUCCEEDED` step — and §13 shows the
  working for each. That table gains three rows — `INDETERMINATE → SUCCEEDED`,
  triggered by a reconciliation that established the effect, and `PENDING → SUCCEEDED` and `AWAITING_APPROVAL →
  SUCCEEDED`, triggered by a step being satisfied by an effect its goal already completed; each also setting `output`
  and `finished_at`, none incrementing `attempts` — because a reader holding only §4, which states that *"every legal
  move is enumerated in §4 and enforced by `PlanExecution`"*, builds a tracker that refuses both the move by which an
  uncertain effect is resolved and the move by which a completed one is reused. **Every other move in that table
  binds entire**, and so do §4's terminal `SUCCEEDED`/`SKIPPED` rule, its *"`FAILED` is terminal
  unless retried"* rule and `FAILED → RUNNING` row, its every-claim-carries-an-`approval_ref`
  rule, its claim-before-invocation ordering, its recovery paragraph and its *"We do not claim
  exactly-once execution"* statement — which §3 of this document quotes as its own ground.
  **§5's second scope** is the roster gaining `claim_effect`, `PlanExport` gaining `effects` with
  its `schema_version` moving by one, §5's closure rule extending to those rows'
  references and `delete_goal`'s cascade reaching them — the same shape ADR-0249 and ADR-0250
  each took to that enumeration. **§5's compare-and-swap discipline, its commands-not-snapshots
  rule and its local-residency, export-completeness and deletion obligations bind entire**, and
  **§§1-2, §6 and §7 are untouched**. §7's deferral of idempotency keys and `INDETERMINATE`
  resolution is **fired rather than replaced**, which earns no record (§13).
- **Partially supersedes [ADR-0255](0255-the-driver-walks-a-plan-in-dependency-order-claims-each-step-under-its-attempt-and-stops-rather-than-acting-under-an-unfinished-one.md),
  in two scopes and in nothing else. The first is the identity §7's and §12's at-most-once
  obligation is stated over.** §7 rules that an effect *"[is] performed **at most once across every plan of that goal**"* and
  §12 states the acceptance requirement over *"a plan whose step would perform **the same
  effect**"*. §§1-2 land an identity in two parts — the **intended action** the step is an attempt
  at, which the row is scoped to, and the **authorised call** within it — so the guarantee is
  narrower than *"the same effect"* in one direction, because two calls meaning one thing while
  spelling it differently carry two keys, and deliberately narrower in another, because two
  intended actions carrying one key are two acts and both happen. A reader holding only §7 reads
  its obligation more widely than it now holds. **Every other clause of §7 and §12 binds entire** —
  §7's keeps-everything-it-recorded rule, its extension of ADR-0228 §5's not-driven rule, its
  sweep and that sweep's stated residual, its one-plan-per-walk rule and its
  no-licence-to-repeat prohibition; §12's every other entry, both acceptance requirements' other
  halves, and its firing conditions — and §10 books the canonical effect-input identity that
  would close the difference. **The second is §11's `core/types.py` clause, in its *"Nothing
  else"* closure over `StepTransition` alone**: §9 adds `satisfied_by_execution`,
  `satisfied_by_step` and `satisfied_by_key` to it, the only stated route by which §2's
  satisfaction reaches the committed `StepExecution` and the only one by which the store can
  verify it. **Every other clause of §11 binds entire** (§13).
- **Partially supersedes [ADR-0192](0192-an-authorisation-is-spent-by-the-act-it-authorises-and-the-trail-gains-an-invocation-row.md),
  in §3's firing clause alone, and in nothing else.** That section rules that the ADR landing
  automated reconciliation *"is fired by a tool contract that offers a **lookup by idempotency
  key** — until a tool can be asked whether a key was already acted on, reconciliation has nothing
  to read."* §3 lands it with no such lookup, on a **read alone** — a `ToolDefinition` that is not
  `side_effecting`, whose recorded decision carries **no `egress_binding`** — where the call **is**
  the read, and where ADR-0192 §1 rules the authorisation not spendable so its further-claim
  admission covers it. **§1's spendability
  rule and its further-claim enumeration bind verbatim** and are what §3 cites and §10 books
  behind; **no clause here widens either, adds an admission, or changes any signature on
  `InvocationLedger`**; and §3's own no-reconciliation-here statement, its recovery-scan clause
  and its spending-on-`INDETERMINATE` argument all bind entire.
- **Partially supersedes [ADR-0037](0037-joining-selection-permission-and-execution.md),
  in steps 4 and 5 of §4's resume sequence alone**, and only where the binding already carries a
  recorded resolution. There `resume` takes neither step — it calls no `ActionPolicy.resolve` and
  records nothing — and proceeds to §4's step 6 with the decision the trail already holds, because
  a reader holding only §4 builds a `resume` that authors a second resolution the audit trail's
  single-resolution index refuses, leaving the stranded ruling permanently unrecoverable.
  **Steps 1-3 and step 6 bind entire**, as do §4's requirement that the step be
  `AWAITING_APPROVAL` in the *stored* execution and the reason it gives for it, its
  *"the turn never answers on the user's behalf"* rule, §2's decide, record, read back, claim
  order, and §6's *"This object disposes of one step, once"* and `PENDING`-only entry. §§1-3 and
  §§5-6 are untouched.
- Date: 2026-09-13

## Context

### Where this comes from

The owner approved A0–A10 as the working delivery breakdown for the six-phase task lifecycle (#2255). **A8 is two decisions,
and this is the first.** The fit report's A8 row reads *"The three-case retry policy, reconciliation, `EFFECT_UNRESOLVED`,
and **modify-before-replace**"*, with *"**Takes ADR-0014 §7's idempotency/`INDETERMINATE`-resolution deferral**"*. This
decision takes the reconciliation half — **how an uncertain effect is resolved, how an unfinished write is finished, and how
an effect is kept to at most once across the plans of one goal**. The retry policy the driver applies **once reconciliation
has told it what happened** is the second, and §10 names it with what fires it.

The requirement register's phase-5 rows are the demand. **R43**: *"A **known failure** and an **unknown outcome** are
different states and are never collapsed."* **R44**: *"An unknown outcome is reconciled — the effect's status established —
**before** any further attempt; a timeout never becomes a blind retry that duplicates the effect."* **R45**: *"Where the
integration cannot establish the outcome at all, an explicit unknown state is preserved and reported."* **R46**: *"A
completed effect and its evidence survive recovery, restart and replanning; nothing is automatically replayed."* **R80**:
*"No claim is made that local persistence alone gives exactly-once remote effects; reconciliation is defined and
integration-supported idempotency is used where available."* **R81**: *"A restart during clarification, approval or recovery
preserves task identity, usable evidence, permission state and completed/uncertain effects, and revalidates what requires
it."* And **R41**: *"The actual response, the identifier the integration supplied, errors and uncertainty are all
recorded."*

The report's own assessment is the starting point and is not repeated as a finding: R41, R43, R45 and R80 **satisfy as
stated** on the corpus already, R46 satisfies *"as stated at the store"* and is **absent across a replan**, and R44 **needs
a producer, not a bend** — *"ADR-0014 §7 defers 'Idempotency keys and `INDETERMINATE` resolution … Automated reconciliation
of an `INDETERMINATE` step waits on it', and `Idempotency` already exists in `core/types.py` on the tool declaration."* This
decision is that producer.

The owner's addendum requirement 5 sets the posture: *"Keep 'do not blindly retry an uncertain effect'; drop 'nothing
auto-retries, ever'."* The owner's decision 3 sets what a late answer gets: *"briefly restate the understanding, recheck
evidence and authorization, then proceed"* — which this decision reaches by making the recheck ADR-0255 §5's, not a second
one.

### What ADR-0255 §12 books here, by name

ADR-0255 books seven things to A8 and states **two acceptance requirements** for this lane so it *"inherit[s] them rather
than invent[s] them"*. They are quoted rather than paraphrased, because they are what this decision is measured against:

1. **At most once across two plans of one goal, and the arm.** *"a plan driven to a `SUCCEEDED`
   and verified step, superseded on a later turn by a plan whose step would perform the same
   effect, where the later step is **not dispatched**; and the paired case over an
   **`INDETERMINATE`** first step, where it is likewise not dispatched, because an effect that
   may have happened is not an effect to repeat."*
2. **The durable recovery of a resolved-but-unapplied answer.** *"a resolved confirmation whose
   claim was refused is durably recoverable — the step is re-askable or the answer is
   re-appliable — demonstrated over a paused attempt that later resumes"*, with *"**The
   superseded-plan ground is excluded by name**"*.
3. **Repairing an attempt left `RUNNING` beside an `INDETERMINATE` step**, where ADR-0255 §6's
   second write did not land.
4. **Completing a supersession sweep that stopped part-way**, *"from either source status —
   `PENDING` and `AWAITING_APPROVAL` alike"*.
5. **Whether the startup recovery scan writes `EFFECT_UNRESOLVED`** on the attempt of a step it
   found `RUNNING`.
6. **The automatic re-drive of a stopped walk** — *"continuing a plan after an `INDETERMINATE`
   step is resolved"*.
7. **Retry across turns, reconciliation, idempotency keys, modify-before-replace, and how an
   `INDETERMINATE` step is resolved**, on ADR-0014 §7's own deferral.

Two further items arrive with the lane: **#2309**, the evidence-to-claim window, which ADR-0255 §13 makes a prerequisite of
the Q4 wiring gate in its own right and §12 assigns to no lane; and **#2317**, a contended resumed park whose engagement
stamp is left unwritten, which ADR-0250 §17's preamble sends *"retry and reconciliation to **A8**"*.

### What the tree holds today, read rather than assumed, at `origin/main` `f4143601`

Five facts decide most of this document, and each is read off the tree rather than recalled.

- **`Idempotency` is already a declaration, with a window.** `core/types.py` carries
  `Idempotency` closed at `NONE`, `NATURAL` and `KEYED`, documented as *"A guarantee, not the
  presence of a parameter"*, and `ToolDefinition.idempotency_window`, which a validator requires
  to be present and strictly positive **iff** `idempotency` is `KEYED`.
- **A key is already derived and already recoverable.** `ToolCall.idempotency_key` is
  `decision.id` for a `KEYED` tool and `None` otherwise (ADR-0029 §5). Its third property is
  what this decision leans on: *"a restarted executor reads `StepExecution.approval_ref`, loads
  the decision from the durable trail, and derives the identical key."*
- **The classification of an interrupted call is already one intrinsic test.**
  `ToolDefinition.interrupted_outcome` returns `FAILED` *"when the tool is not `side_effecting`,
  **or** its `idempotency` is `NATURAL`; otherwise `INDETERMINATE`"*, and its docstring records
  why it is declared once rather than per consumer.
- **The by-binding lookup #257 named already exists and has no consumer.**
  `AuditTrail.resolution_of(execution_id=…, step_id=…)` is on the Protocol (ADR-0059 §2),
  documented as existing *"so a step stranded `AWAITING_APPROVAL` with its ruling durable but its
  disposition transition uncommitted (#257) can be driven to the disposition already decided —
  idempotently, authoring nothing new"*. Nothing in `src/` calls it with an execution and a step.
  ADR-0059's own close-out says so in terms: *"#257 is **unblocked**, not closed here"*, and
  *"The recovery **operation** that consumes it is a later orchestration wave."*
- **A plan already names its goal.** `ActionPlan.goal_id` is a declared field, so the store can
  resolve an execution to its plan to its goal without any caller threading one.

### The gap this closes, stated as the failure the corpus has today

A reader holding the corpus without this decision builds a system in which: a replan of a goal whose first plan already
booked a campsite **books it again**, because ADR-0255 §7 states the obligation and says in terms *"this decision lands no
mechanism that could enforce it"*; an `INDETERMINATE` step **stays `INDETERMINATE` for ever**, because ADR-0014 §4 requires
explicit resolution and no component performs one; an attempt left `RUNNING` beside such a step **stays `RUNNING`**, so the
durable record says the attempt is working while it holds an effect it cannot account for; a supersession sweep that lost a
compare-and-swap **leaves a `PENDING` step on a plan nobody will drive**; and a user who answered *yes* at the instant their
attempt paused has **spent their one answer on nothing**, with the ruling durable in the trail and no code path that reads
it.

### What this decision is not allowed to settle

Golden rule 5 and ADR-0015 put a `core` contract change behind a ratified ADR of its own, and this **is** that ADR for the
surface §9 names. It is not one for anything else. **It decides no retry policy** (§10), **no verification** (A10), **no
cancellation semantics** (A9), **no user surface** for anything it records (A9), and **no parallel execution** (ADR-0014
§7's second half and ADR-0253 §1, untouched).

## Decision

### 1. The effect key: what tells same action, same arguments from same action, different ones

ADR-0255 §7 states the obligation this section makes mechanical, and states honestly that it could not: *"A step whose
effect the goal records as completed or as uncertain is never dispatched a second time … **Across two plans of one goal this
decision lands no mechanism**."* Its reason is the record that did not exist — *"a goal records no completed effect that a
driver could compare against"*. This section mints that record.

> **Normative.** `core/types.py` gains **`EffectKey`**, a frozen model with `extra="forbid"` whose fields are exactly these
> five, with these annotations and defaults: **`tool_id: VisibleIdentifier`**, carrying `ToolDefinition.id`'s own annotation;
> **`parameters_digest: Sha256Hex`**, carrying `PermissionDecision.parameters_digest`'s; **`egress_account: BoundAccount |
> None = None`**; **`egress_endpoint`**, the annotation `_EgressBindingBase.transport_endpoint` carries, `| None = None`; and
> **`egress_destinations: tuple[CanonicalDestination, ...] = ()`**. **It carries no sixth field**: no step id, no execution
> id, no plan id, no decision id, no goal id, no instant and no attempt — **and no intended action id**, which is the row's
> *other half* (§2) and never a field of the key. **A reader who adds it here breaks the one case this decision exists to tell
> apart**: the goal whose booking moves from Saturday to Sunday carries one intended action and two keys, and a key that
> carried the action id would make the two rows unequal in the same way two unrelated acts are unequal, so the revision would
> dispatch a second booking instead of meeting §2's `COMPLETED_OTHERWISE` answer.

> **Normative — a model validator admits exactly two shapes and no mixture.** Either **`egress_account` and `egress_endpoint`
> are both `None` and `egress_destinations` is empty** — the no-binding shape — **or both are present and
> `egress_destinations` is non-empty**. A key carrying an endpoint without an account, or destinations without either, is
> **unconstructable**, so one effect cannot be split across two unequal rows by a partial projection. The non-empty limb is
> not a new rule: `canonical_destination_set` is documented as *"therefore **never empty**"*, and the validator refuses the
> shape that declaration already excludes.

> **Normative — the key is what `PermissionDecision.authorises` compares, less the two ids a replan mints afresh and less the
> binding's provenance, and that is the rule a later conjunct is read against.** `authorises` compares five values — the tool,
> `parameters_digest`, `step_id`, `execution_id` and `egress_binding`, the last *"compared whole and by value"* (ADR-0150 §9).
> `EffectKey` drops `step_id` and `execution_id`, which describe **where the call was made from** and which a re-plan mints
> anew — ADR-0253 §8's own reason, *"A re-plan mints new step ids"* — **and what those two ids could not have supplied is
> supplied by something else rather than by nothing**: the durable identity of the *act* a step is an attempt at is
> `IntendedAction.id` (ADR-0265 §1), minted once by `orchestration` and retained unchanged across a revision, and **the row
> carries it** (§2). So this clause fixes the key's reach over **arguments** and nothing more, and no lane reads it as the
> whole of the identity an at-most-once claim is scoped to. The key takes from the binding **only the three facts that
> describe where the effect goes**: `account`, `transport_endpoint` and the derived `canonical_destination_set`, each declared
> on `_EgressBindingBase` and therefore present on **every** member of the union `PermissionDecision.egress_binding` admits.
> **A later decision that adds a conjunct to `authorises`, or a field to the binding, adds the matching field to `EffectKey`
> in the same change unless it states in its own text why that value does not change what the remote system does.**

> **Normative — the binding's provenance and authorisation-posture fields are excluded by name, and the exclusion errs toward
> blocking.** `planned_with_external_content`, `coverage`, `closed_loop` and `spans` are **not** in the key. The first three
> record how the call was reasoned about rather than what it does, so two replans of one goal that differ only in them would
> otherwise carry two keys and **dispatch the same effect twice** — the failure this section exists to stop. `spans` is
> excluded because `canonical_destination_set` is its canonicalisation: ADR-0150 §9 names that set as a thing `authorises`
> deliberately does *not* compare, precisely because *two different decompositions can canonicalise to one destination set*,
> and for effect identity that is the property wanted rather than the one refused. **Where the *projection* is wrong it is
> wrong toward `HELD`, `COMPLETED`, `COMPLETED_OTHERWISE` or `UNCERTAIN`** — two distinct effects treated as one, which stalls
> a plan — which is the asymmetry ADR-0014 §4 chooses in every other place it is faced with one. **The key's own reach is
> narrower than that and is stated in the next clause rather than implied by this one.**

> **Normative — the tool is projected to its `id`, a third narrowing stated here rather than left to be discovered.**
> `authorises`'s first conjunct is `request.tool == self.tool`, a **whole `ToolDefinition`** compared by value, and
> `EffectKey` carries **`tool_id` alone**. The reason is the provenance exclusion's: a definition carries a description, a
> schema, a risk level and declarations a deployment can revise **without changing what the call does**, and a key over the
> whole definition would mint a fresh key on every such revision and **dispatch the effect twice**. **The cost is stated
> rather than hidden.** ADR-0016 spends an id *"for the life of the process"* over a registry *"rebuilt from scratch each
> run"*, so a deployment that changes a definition's code and restarts may bind a **materially different** tool to a spent id
> while these rows are durable across it — and there the projection errs in the direction above, the new call meeting the old
> row and being **suppressed** rather than dispatched twice. Arm 4 asserts the collapse deliberately, and §10 books the
> identity that would close it.

> **Normative — what the key recognises is the *same authorised call*, and two calls that mean the same thing without being
> the same call are not recognised.** `parameters_digest` is ADR-0021 §1's digest over the canonical encoding of the
> **supplied** arguments, so two calls whose arguments differ in spelling while naming one thing — a recipient written
> `alice@Example.com` in one plan and `alice@example.com` in the next — carry **two** digests and therefore **two keys**.
> **What that now costs is stated over the scoping and not over the goal.** Under **one** intended action the second call is
> `COMPLETED_OTHERWISE` (§2) rather than `COMPLETED`, so it is **not dispatched**: what the unrecognised equivalence costs is
> a **spurious modify-before-replace investigation** of an act that in fact needs no modifying. Under **two** intended actions
> it is `CLAIMED` and dispatched, which is correct and is not a cost at all — two acts the user asked for. **Neither case is a
> double dispatch of one act**, which is what the paragraph above said before the scoping landed and what no longer follows
> from it. **This decision does not close the equivalence itself**, and §10 books it with what fires it. **No lane reads the
> guarantee more widely than it is stated**: an effect is performed at most once **per intended action per authorised call**
> within one goal, which is the identity the permission stage already fixes and the only one this system can compute without
> interpreting a tool's arguments — which ADR-0145 §5 and ADR-0016 §2 both put outside `core`.

> **Normative.** `ToolCall` gains **`effect_key`**, a **property** returning `EffectKey | None`, derived from the call and
> **never minted, supplied, configured or carried as a field**. It is **`None` if and only if `decision.tool.side_effecting`
> is false**, and otherwise an `EffectKey` built from **`decision.tool.id`**, **`decision.parameters_digest`** and, where
> `decision.egress_binding` is not `None`, that binding's `account`, `transport_endpoint` and `canonical_destination_set`.

> **Normative — the `None` limb is `side_effecting` alone, and it is deliberately not `ToolDefinition.interrupted_outcome`'s
> two-limb test.** That test asks what an **interrupted** call means and exempts `NATURAL`, because a repeat of one is
> harmless. **This test asks whether an effect exists to be claimed at all**, and ADR-0255 §7's requirement is stated over
> **dispatch** — *"the later step is **not dispatched**"* (§12) — not over what the remote system does with a second call.
> **So a side-effecting `NATURAL` tool has an effect key and is held to at-most-once exactly as a `KEYED` or `NONE` one is**,
> and no lane reads its declaration as an exemption from this section.

> **Normative — the two keys are two values and no lane collapses them.** `ToolCall.idempotency_key` stays as ADR-0029 §5
> derives it — `decision.id` for a `KEYED` tool — the **tool-facing** key, *"distinct for a distinct intent"*. `effect_key` is
> the **goal-facing** key with the opposite property: **identical across two authorisations of the same concrete call**, which
> is what lets a later plan's step be recognised as the earlier plan's effect. **Neither is computed from the other, neither
> is substituted for the other, and no `ToolInvoker`, tool or component outside this system is ever passed `effect_key`** —
> the one seam it crosses is `PlanStore.claim_effect` (§2).

> **Normative — every value is read from the `PermissionDecision` and none from `ToolCall.request`.** `PermissionDecision`
> carries `tool`, `parameters_digest` and `egress_binding` as its own fields, so the key needs nothing from the request.
> `ToolCall.idempotency_key`'s reason binds verbatim — the decision's copy is *"the one the trail holds, which is the copy a
> restart reconstructs from"* — and answers the same threat the same way: ADR-0018 §3 puts a post-construction `__dict__`
> mutation inside the threat model, `ToolCall`'s docstring records that `frozen=True` *"does nothing about
> `call.__dict__["request"]`"*, and a key derived from the mutable half could be persisted for one effect while another was
> invoked. **Reading the decision closes that**, and ADR-0034 §1's direction of caution binds too: a declaration mutated
> mid-flight must not turn a side-effecting call into one this section exempts.

> **Normative — no digest of the key is minted, and none is pinned.** `EffectKey` is compared **by value**, field by field,
> exactly as `authorises` compares the values it is built from. **No clause of this decision composes, concatenates or hashes
> its fields into a single string**, so there is no encoding to disagree about and no algorithm to pin. **How a store indexes
> the key is below this contract**, so long as two equal keys are one row and two unequal keys are not.

**Deriving it rather than declaring it is what makes it a key nobody can get wrong, and the argument is ADR-0029 §5's.**
That section rejected a field because *"It would be a value some caller computed, two callers could compute differently, and
a retry path could forget to carry"* — all three apply unchanged, and a `ToolDefinition` field saying *"this is the same
effect as that one"* would additionally be a **tool author's** claim about a **goal's** history.

**And the values it is built from are the values the permission stage already ruled on.** `parameters_digest` is computed on
the request rather than accepted from a caller, and ADR-0148 §1 requires the request a policy rules on to be complete —
*"Nothing in it is resolved, canonicalised, defaulted, expanded or added after `ActionPolicy.decide` has been reached"*. So
at the moment the key exists the arguments are **fixed, canonical and authorised**, which is the only moment at which two
calls can be compared at all; reference resolution has already happened (ADR-0253 §6), so *"book the campsite the previous
step found"* is a concrete value.

**Taking `authorises`'s own conjuncts rather than inventing a list is what keeps the key honest as the corpus grows, and the
egress binding is why it matters today.** ADR-0150 §9 makes that binding a conjunct *"compared whole and by value"*, so two
calls of one tool with identical parameters and **different connected accounts** are two different authorised calls and
therefore two different effects; a key over the tool and the parameters alone would refuse the second as a duplicate.
Stating the rule as *"what `authorises` compares, less what the clauses above name"* makes that fall out, and makes the next
conjunct's obligation explicit rather than a thing a later lane discovers.

**This is not the identity ADR-0255 §7 refused, and the difference is the scope.** That section warns that *"A driver that
compared capability and parameters would be inventing an identity nobody declared"*. Three things separate this key from
that comparison. It is over a **`ToolDefinition.id`**, not a planner-supplied capability string — ADR-0249 §7's asymmetry
observed rather than cited. It is over the **canonicalised, resolved arguments a policy ruled on** together with the binding
it ruled under, not over a plan's parameter mapping. And it is scoped to **one intended action of one goal**, which is an
identity ADR-0265 §1 declares rather than one this document derives. What remains is narrow and defensible: *within one
intended action, the same tool called with the same concrete arguments under the same binding is the same effect*.

### 2. The effect claim: one indivisible write in the store, taken immediately before the step's claim

> **Normative.** `PlanStore` gains **`claim_effect`**, an **`async`** member — it is I/O-bound like every other member of that
> Protocol — whose complete signature is **`async def claim_effect(self, *, execution_id: str, step_id: str, effect_key:
> EffectKey) -> EffectOutcome`**, taking `execution_id` and `step_id` with the annotations `PlanStore.commit_transition`'s
> neighbours already use for them and returning an **`EffectOutcome`** and nothing else. The store resolves **both halves of
> the row's scope** itself — the goal from the execution's plan's `goal_id`, and the **intended action** from
> `PlanStep.intended_action` of that plan's step (ADR-0265 §4) — so **no entry point of `orchestration` gains a `goal_id`
> argument for it and none gains an intended-action one**, and the signature above carries neither.

> **Normative — the row's identity is ADR-0265 §6's triple, and the store keeps at most one row per goal and intended
> action.** A row is identified by **`(goal_id, intended_action_id, effect_key)`** — §6's own keying, *"not on the pair"* —
> and names the `(execution_id, step_id)` currently holding it together with the key it was taken under. **The store
> additionally keeps at most one row per `(goal_id, intended_action_id)`**, not as a competing constraint but as an invariant
> of the write rules below: the only writes are the first claim and a **re-point onto a dead holder**, and a re-point
> **re-keys** the row rather than leaving the dead key's row beside it. `claim_effect` therefore **resolves the row by the
> pair and compares the effect key within it**, which is the lookup §6's second clause requires — *"a completed effect claimed
> under **this** intended action whose key is **not** this call's key"* is a state a triple-keyed lookup could not ask about,
> finding no row at all. **No lane scopes this claim to a goal and an argument key alone** (§6).

> **Normative — a side-effecting call whose step names no intended action is not dispatched, and this is the answer ADR-0265
> §4 leaves here.** That section rules that *"a step naming no intended action is held to nothing by this decision"* and that
> *"whether an effect-bearing dispatch must name one is decided where the effect claim is taken"*. It must. Where `effect_key`
> is not `None` (§1) and the step's `intended_action` is `None`, **`claim_effect` is not called**, nothing is committed, the
> step **keeps the status it was entered at**, the walk **stops**, and the stage returns **`Disposition.EFFECT_UNSCOPED`**.
> Dispatching there would perform an effect **no row could ever recognise**, so every later plan of the goal would answer
> `CLAIMED` and repeat it — ADR-0255 §7's obligation unmet, and the fail-open direction ADR-0265 §4 refuses for a dropped
> condition label. **A call that is not side-effecting is untouched.**

> **Normative — the window is closed at the store as well as at the stage, and what the refusal reaches is bounded.**
> `claim_effect` **raises `PlanningError` and writes nothing** where the step the ids name carries no `intended_action`,
> beside the two reference refusals below — ADR-0265 §4's own construction, *"a window is closed at the store rather than
> trusted to close itself"*, taken one member over. Every plan written before ADR-0265 lands carries `None` on every step, so
> a side-effecting step of such a plan stalls rather than dispatching; **what bounds that is ADR-0255 §13's Q4 rule**, no
> consequential capability being wired, so the stalls are of controlled fakes and the alternative direction would be a silent
> unclaimed effect. **No lane invents an intended action for a stored plan** to lift the stall, which is ADR-0265 §5's *"an
> act nothing declared is an act no claim was ever scoped to"*.

> **Normative.** `core/types.py` gains **`EffectClaim`**, a `StrEnum` valued by lower-cased member name and **closed at
> exactly five members**: `CLAIMED`, `COMPLETED`, `COMPLETED_OTHERWISE`, `UNCERTAIN` and `HELD`. The vocabulary is added to
> and never renamed.

> **Normative — `COMPLETED_OTHERWISE` is the state ADR-0265 §6 requires an answer for, and this is that answer.** It means
> **this goal's row for this intended action names a `SUCCEEDED` holder whose key is not this call's key** — the act was
> performed, with different arguments. §6 rules that *"the answer is neither claimed nor completed: the step is **not
> dispatched**, and the work returns to investigation — modify-before-replace, which A8's second ADR owns"*, and that is
> exactly what it does here: nothing is dispatched, nothing is committed, no authorisation is spent, the step keeps its entry
> status and the walk stops. **This decision routes no investigation and opens none** — it makes the state *distinguishable*,
> which is what §6 asks of it, and §10 books the act that consumes it with what fires it.

> **Normative — the answer carries the holder where the caller must act on it, and nowhere else.** `core/types.py` gains
> **`EffectOutcome`**, a frozen `extra="forbid"` model whose fields are exactly **`claim: EffectClaim`** and
> **`execution_id`** and **`step_id`**, each `DurableIdentifier | None` defaulting to `None` and carrying the annotations
> `EffectRecord` uses. **Both are non-`None` if and only if `claim` is `COMPLETED`**, enforced by a model validator, because
> that is the one answer whose caller has work to do with the holder — §5's satisfaction reads that step's `output`.
> **`CLAIMED`, `COMPLETED_OTHERWISE`, `UNCERTAIN` and `HELD` carry neither**: a caller that cannot act on the holder is not
> handed one, so no lane grows a habit of reading rows through this member. **`COMPLETED_OTHERWISE` is deliberately among
> them** — the modify-before-replace investigation that consumes it needs the earlier act's *arguments* and not only its ids,
> which is a bounded lookup §10 requires A8's second ADR to add and argue for rather than inherit here unreviewed.

> **Normative — what each answer means, decided by the stored status of the step the row names, by whether that step is this
> one, and by whether the row's key is this call's key, in this order and over nothing else.** `claim_effect` reads the row
> for the `(goal_id, intended_action_id)` pair and returns:
>
> 1. **`CLAIMED`**, writing the row with this call's key, where **no row exists** for the pair.
> 2. Otherwise, read the stored `StepExecution.status` of the step the row names:
>    - **`SUCCEEDED`** → **`COMPLETED`** where the row's key **equals** this call's key;
>      **`COMPLETED_OTHERWISE`** where it does not. Writing nothing in either.
>    - **`RUNNING`** or **`INDETERMINATE`** → **`UNCERTAIN`**, writing nothing, **whether or not the
>      keys are equal**: what is uncertain is whether this intended action was performed at all, and
>      a differently-argued call under an action that may already have been performed is the one
>      thing a modify-before-replace investigation must not be started from.
>    - **`SKIPPED`** → **`CLAIMED`**, re-pointing the row at this step **and re-keying it to this
>      call's key**.
>    - **`FAILED` on a step of a plan that a stored plan supersedes** → **`CLAIMED`**, re-pointing
>      the row at this step **and re-keying it**, whichever step asks. **The store decides the
>      supersession itself**, from the holder's execution's plan and the plans it holds, inside the
>      same indivisible step as the write — `orchestration` neither computes it nor asks for it, and
>      **no member is added** for it.
>    - **`FAILED`**, **`PENDING`** or **`AWAITING_APPROVAL`** → **`CLAIMED`**, writing nothing,
>      where the row names **this same `(execution_id, step_id)`** **and** its key equals this
>      call's key; **`HELD`**, writing nothing, in every other case.
>
> **The second limb is total: each of `StepStatus`'s seven members, crossed with whether the row's key equals this call's key
> and with whether the row names this step, has exactly one answer, and no input is left undecided.** The statuses under which
> the step the row names may still dispatch are exactly three, and the exemption for them is stated over **this same step** —
> a row naming this step at `SUCCEEDED`, `RUNNING` or `INDETERMINATE` answers `COMPLETED`, `COMPLETED_OTHERWISE` or
> `UNCERTAIN` like any other, because this step has then already acted. **No further answer exists.**

> **Normative — the same-step exemption is not widened to the intended action, and the ground is `StepExecutor.execute`.** It
> would be the natural reading once steps have a stable identity — let a later plan's step inherit the claim of an earlier
> step carrying the same intended action, and no supersession test is needed. **It is refused.** That loop commits `RUNNING →
> FAILED` through `_run_once` and then calls `_claim` again, which is the tree's single `to_status=StepStatus.RUNNING`
> construction, so a `FAILED` holder's next act may be **a second dispatch of the same call inside the same turn**; a later
> plan's step that took the key on the ground that it shares the intended action would dispatch beside it, on a different
> `ExecutionState` record that no compare-and-swap orders against the first. **Two dispatches of one effect is the failure
> this section exists to prevent**, so the exemption stays `(execution_id, step_id)` and the supersession branch above stays
> the route by which a later plan takes over a dead holder. **The intended action scopes the row; it does not license a second
> holder of it.**

> **Normative — the references are checked before anything is written, inside the same indivisible step.** `claim_effect`
> **raises `PlanningError` and writes nothing** where no execution with `execution_id` is stored, or where `step_id` is not
> the id of a step of **that** execution, so **no row is written that §9's export closure could not satisfy** and a later
> claim always finds a holder whose status it can read. The check is the store's because only there is it atomic.

> **Normative — the read, the comparison and the write are one indivisible step**, on ADR-0014 §5's existing compare-and-swap
> discipline and for ADR-0255 §3's reason: two turns of one conversation are not serialized, so **there is no separate read on
> which a decision is taken** before the write.

> **Normative — where it is taken, when it is not taken at all, and what it is not.** The claim is taken **inside the stage
> that holds the authorised `ToolCall`**, after ADR-0037 §2's *decide → record → read back* and **immediately before** the
> `PENDING → RUNNING` (or `AWAITING_APPROVAL → RUNNING`) commit — and **it is not taken at all where `effect_key` is `None`**
> (§1), so a call of a tool that is not `side_effecting` reaches `claim_effect` never, writes no row, and is held to nothing
> by this section. **A side-effecting call always takes it**, whatever its `Idempotency`. It is **not a fifth evaluation of
> the driver's** (ADR-0255 §1), and **`StepRunner.run`, `StepRunner.resume` and `StepExecutor.execute` gain no argument** —
> the key is derived from a value that stage already holds and the row's scope is resolved by the store.

> **Normative — `StepExecutor` gains no collaborator.** It takes the claim through the `PlanStore` it already holds
> (ADR-0058), and `ToolRegistry`, `ActionPolicy` and `AuditTrail` each keep the role they have.

> **Normative — the ordering is effect-claim-then-step-claim, and what its failure leaves is stated rather than glossed.** A
> failure between the two leaves a row naming a step still at its entry status. **That step re-claims its own key on the next
> walk** and dispatches; **every other step of that goal under the same intended action is `HELD` until that step is disposed
> of** — by its own dispatch, or by §4's sweep once its plan is superseded — and **where its plan is never superseded and
> never driven again, that hold does not lift**. The reverse order would leave a dispatched effect with **no row at all**, so
> the ordering trades a hold that can stall an act for a gap that could double one.

> **Normative — `COMPLETED` dispatches nothing and **satisfies** the step from the work the goal already did, and the walk
> continues.** The stage makes **no call**, claims no invocation and spends no authorisation; it reads the holder the answer
> names through the `PlanStore` it already holds and commits that step **`→ SUCCEEDED`** from the status it was entered at;
> **the store sets `output` from the holder's own row and `finished_at` at that instant** (§9), and the stage neither. **`attempts` is not incremented**
> and **the walk goes on to this step's dependents**, which read that `output` under ADR-0253 §2 like any other. **This is the
> whole of what `COMPLETED` does**: it is not a skip, no `SkipReason` is written, and **no lane reads it as licence to copy an
> output between goals, or between two acts of one goal** — the row is scoped to this goal **and this intended action** (§2)
> and the holder is an execution of this same goal, kept by ADR-0255 §7.

> **Normative — a satisfied step is recorded as satisfied and never as executed, and `StepExecution` gains the two fields that
> make that representable.** `_claimed_step_is_authorised` requires of every `SUCCEEDED` step an `approval_ref`, a
> `bound_tool`, a `started_at` and `attempts >= 1`, and a satisfied step has none of them: nothing ran under it. So
> `core/types.py` gains **`satisfied_by_execution`** and **`satisfied_by_step`**, both `DurableIdentifier | None` defaulting
> to `None`, **non-`None` together and only on a `SUCCEEDED` step reached by this clause**, naming the holder whose act it
> was. **The claim marks are then not required and none is present** — `attempts` stays `0`, `started_at` and
> `approval_ref` stay `None`, and **`bound_tool` is cleared by the commit**, since an `AWAITING_APPROVAL` source carries
> one from its park and a satisfied step made no call with it. The correlation ADR-0004 §7 wants is to the act that
> happened, which these two fields carry. **A `SUCCEEDED` step carrying neither is unchanged and still requires all four.** ADR-0014 §3's *"what
> actually happened"* reading is **honoured rather than bent**: the record says the work was done elsewhere in this goal and
> names where, instead of claiming a tool call this step never made. §13 carries the record that scope owes.

> **Normative — the reuse is conditional, and the conditions are checked at the instant it is taken.** A `COMPLETED` answer
> satisfies the step **only where all three hold**: the **intended action is the same and the keys are equal**, which
> `claim_effect` establishes together — it reads the row at the `(goal_id, intended_action_id)` pair and answers `COMPLETED`
> only where the row's key is this call's key, so a completed act under a *different* action is never seen here at all and one
> under **this** action with different arguments is `COMPLETED_OTHERWISE` rather than a reuse. **Both conjuncts are needed and
> each fails differently**: without the action, *"book another one just like it"* would be satisfied by the first booking
> (ADR-0265 §10's arm 1); without the key, a changed request would be satisfied by the unchanged act; **every member of the
> step's own `when` is satisfied** for the goal at that instant, on ADR-0252 §6's four tests as ADR-0253 §5 requires of a
> dispatch, because a step whose evidential preconditions no longer hold must not be completed from an older act any more than
> it may be dispatched; and the step's **`verifies` predicate holds over the borrowed `output`** (ADR-0253 §4). **Where any
> fails, nothing is written**: the step keeps its entry status, the walk stops with `EFFECT_ALREADY_CLAIMED`, and no lane
> records a satisfaction it could not justify.

> **Normative — ADR-0252 §6's tests are necessary here and are not sufficient by themselves.** Those four are about the
> **goal's evidence** — whether a proposition is supported, by a row recent and applicable enough to act on — and say nothing
> about whether an act performed earlier answers the request being made now; the key equality says that, and `verifies` says
> the result is usable. **A lane that checked only §6's tests would reuse a result for a changed request**; one that checked
> only the key would reuse one whose grounds had gone.

> **Normative — and all of them together are still necessary rather than sufficient, which ADR-0265 §6 states and this clause
> adopts.** None of the three asks **whether the completed act satisfies the current interpretation**: that is verification
> against the goal's criteria, it is **A10's by name**, and ADR-0253 §4 says in terms that `verifies` is *"never verification
> against the goal's criteria"*. **So no lane reads this section as establishing that the reuse was right** — it bounds the
> reuse, and the decision that verifies it is the one §10 names.

> **Normative — `COMPLETED_OTHERWISE`, `UNCERTAIN` and `HELD` dispatch nothing, commit no transition, and stop the walk.**
> There, and there only, the stage returns **`Disposition.EFFECT_ALREADY_CLAIMED`** and the step **keeps the status it was
> entered at** — **`PENDING`** where `StepRunner.run` took the claim, **`AWAITING_APPROVAL`** where `StepRunner.resume` did,
> which is the second commit the clause above admits. **It is the entry status rather than `PENDING` because no transition is
> committed**: a resumed step is `AWAITING_APPROVAL` in the store, and naming `PENDING` there would demand a move ADR-0014
> §4's table does not admit. `ActionPolicy.decide`'s recorded ruling stands in the trail as ADR-0037 §2 already permits for a
> claim that did not land — **a resumed step's replayed `ALLOW` therefore stays replayable** (§5) — and **no step is moved to
> `SKIPPED` on this ground, with any `SkipReason`**. ADR-0014 §4's `PENDING → SKIPPED` row is untouched and **no lane widens
> it**.

> **Normative — the turn says so, once per satisfied step.** `TurnOutcome` gains **exactly one** field,
> **`satisfied_from_earlier`**, typed `tuple[DurableIdentifier, ...] | None` defaulting to `None`: `None` on every turn that
> satisfied no step this way, otherwise the ids of the steps this turn satisfied, in walk order, **carried by value from what
> the stage computed and never a second computation**. That is ADR-0242 §9's shape exactly, `reply`'s own enumeration
> untouched.

> **Normative — "once" is **at most** once per *step*, it is best-effort, and it needs no durable announcement state.** A step
> is satisfied at most once, because satisfaction commits it `→ SUCCEEDED` and §7 admits no move out. So the turn that
> satisfies a step reports it and **no later turn reports that step again**; a later turn that satisfies a **different** step
> from the same effect reports **that** step, which is correct rather than a repetition — different work was completed. **No
> effect row carries an announced flag, no lane adds one**, and ADR-0250 §5's announcement discipline is met by the step's own
> one-way transition. **The wording and the channel stay A9's** (§10); what this decision fixes is the field, its type, and
> that a silent reuse is not conforming.

> **Normative — the window in which a satisfaction is never announced is named rather than closed.** `satisfied_from_earlier`
> rides on `TurnOutcome`, one turn's value; a failure **after** the `→ SUCCEEDED` commit and **before** the turn returns
> leaves the step durably terminal and **unreported**, and no later walk reconstructs the announcement, because ADR-0255 §5
> passes over a `SUCCEEDED` step. **So the guarantee is at most once and not at least once** — ADR-0014 §4's *"We do not claim
> exactly-once execution"* posture applied to the report rather than the act — and no lane reads the field as a delivery
> guarantee. **What the window does not cost is the fact**: `StepExecution.satisfied_by_execution` and `satisfied_by_step` are
> committed in the same write, so the record always says the step was satisfied and names the act it was satisfied from;
> nothing is lost but one turn's sentence. **No lane adds an announced flag, an outbox or a redelivery pass on this decision's
> authority** — that is a reply-surface mechanism and the reply surface is **A9's** (§10).

> **Normative.** `Disposition` gains exactly **two** members — **`EFFECT_ALREADY_CLAIMED`**, returned for
> `COMPLETED_OTHERWISE`, `UNCERTAIN`, `HELD` and a `COMPLETED` whose reuse conditions fail, and **`EFFECT_UNSCOPED`**,
> returned for a side-effecting call whose step names no intended action. **Which `EffectClaim` member produced
> `EFFECT_ALREADY_CLAIMED` is not carried on the disposition**, and what the turn tells the user about either is **A9's
> report** (§10). They are two members and not one because they are two different facts about the world — *this goal has
> already claimed this act* against *this plan cannot say which act this step is* — and a client that could not tell them
> apart could not tell a user which of the two it was, while the second is a defect in the plan and the first is not. Adding a
> member is additive on the wire under ADR-0084 §4, exactly as `INVALID_PARAMETERS` and `EGRESS_UNBINDABLE` were.

> **Normative — a step already disposed of never re-claims, and the guarantee is the conjunction of this section and ADR-0255
> §5.** Within one execution ADR-0037 §6's *"`run` enters only at `PENDING`"* stops a re-dispatch and ADR-0255 §5's walk
> *"passes over"* `SUCCEEDED`, `FAILED` and `SKIPPED`; **across plans of one goal the effect claim stops it**, and neither
> does the other's work.

**The blocking set is `{SUCCEEDED, RUNNING, INDETERMINATE}` and is written out rather than referred to a private constant.**
`core/types.py` carries `_CLAIMED_STATUSES` over those three **and `FAILED`**, for a different question — which statuses
mean a tool call may have happened at all. `FAILED` is deliberately outside the blocking set on ADR-0034 §1's ground, that
*"nothing could have run under it" is a fact the executor **holds***, so it answers neither `COMPLETED` nor `UNCERTAIN`;
binding the rule to `_CLAIMED_STATUSES` would call a proven failure uncertain and refuse the holder's own second attempt,
which is R43 read backwards.

**`FAILED` is nonetheless an *occupied* status rather than a free one, and `StepExecutor.execute` is the reason.** That loop
commits `RUNNING → FAILED` through `_run_once` and then, where ADR-0029 §5's two conjuncts both hold, calls `_claim` again —
the tree's one `to_status=StepStatus.RUNNING` construction — so a `FAILED` step is one whose **next act may be a second
dispatch of the same call, inside the same turn**. Re-pointing the row away from such a holder would let a later plan's step
take the key while that retry was still coming, and both would invoke: two claims, on two `ExecutionState` records, which no
compare-and-swap orders against each other. **So `FAILED` takes the shape `PENDING` takes** — its own holder re-claims it,
nothing else does, and the key is freed by that holder being disposed of.

**`RUNNING` is grouped with `INDETERMINATE` rather than with `SUCCEEDED`, and ADR-0014 §4 is why.** A step durably `RUNNING`
is precisely the state that decision calls indistinguishable — *"a crash between a tool's side effect and the commit of
`RUNNING → SUCCEEDED` … cannot, from planning's vantage point, be distinguished from a crash before the effect"* — and it is
the state the startup scan moves to `INDETERMINATE`. Calling it `COMPLETED` would assert what nobody knows; calling it
`HELD` would invite a caller to wait for a step that may never move. `UNCERTAIN` is the honest member, and it is the one R45
asks to be preserved.

**`HELD` exists because `PENDING` is a claim in progress rather than an absence, and a `FAILED` holder may still retry.** A
row naming a `PENDING` step was written by a turn that is about to dispatch that step, and two turns of one conversation are
not serialized. Treating `PENDING` as re-claimable would let the second turn take the key and dispatch beside the first. The
cost is stated rather than hidden: a step whose row was written and whose own claim then failed is re-claimable by
**itself** and by nothing else, until the plan holding it is superseded and §4's pass sweeps it to `SKIPPED`, at which point
the key is free again — that is why the sweep and the key are one decision rather than two. **A `FAILED` holder is the same
shape with one more way out**: it is re-claimable by itself while its plan stands, so `StepExecutor.execute`'s own retry
proceeds; and once a stored plan supersedes that plan the holder can never retry (ADR-0255 §7), so §2's table frees the row
to whichever step asks. **A goal is therefore never stuck behind a dead claim**, and the one case that stays held is a
`FAILED` holder on a live plan — which is exactly the case where the retry may still come.

**And what `HELD` now blocks is one intended action rather than one goal, which is the whole of what the scoping buys
here.** Before ADR-0265 the row was the goal's, so a live hold on any effect held every step of the goal carrying that key;
now it holds only the steps that are attempts at **the same act**. A goal whose user asked for two rooms has two rows and
neither holds the other, and a goal pursuing two unrelated acts that happen to resolve to one tool and one digest — the
collision §1's key alone could not tell from a repeat — has two rows as well. **The live-plan hold survives unchanged inside
an intended action**, and it is the same trade §2 fixed: a hold that can stall one act, rather than a gap that could double
it.

**The store decides it rather than the caller, for ADR-0255 §3's reason and no other.** That section refuses a
caller-supplied revision because *"a check with an extra step"* is a check the world can move under; the compared value
belongs where the write is, so the answer is a **store** answer and a loser of the race is told it lost rather than
discovering it later. `claim_effect` is a **command, not a snapshot**, on `PlanStore`'s own stated discipline. **The holder
it returns on `COMPLETED` is not a relaxation of that**: it is two identifiers, returned on the one answer whose caller must
finish work rather than stall, and the caller reads the execution through existing members.

**What this does not buy, said plainly — and one thing it used to not buy, which ADR-0265 has bought.** Two turns driving
**two steps of one plan** that carry the same intended action and the same effect key can still each reach `claim_effect`,
and the first to write wins while the second gets `HELD` — which is correct, because they are two attempts at one act.
**What used to be a defect here and is not one now** is the plan that books two identical rooms: its two steps are two
`PlanStep.intended_action` values, so they read **two rows**, and **both dispatch**. That is the owner's *"an earlier
booking must not count as fulfilling 'book another one'"* met by construction rather than booked, and it is the single
clearest thing the identity changed about this section. What **remains** unclosed is narrower and is a genuine plan defect:
a planner that emitted the same concrete call twice **under one intended action** — two steps that are attempts at *the same
act*, which is a plan saying the act should happen twice while saying it is one act. The second step is then permanently
`HELD` and the walk stops at it; it is visible in the durable record as a `HELD` disposition rather than as a double
booking, and §10 names what would fire a plan-time refusal of it.

### 3. Resolving an uncertain effect: reconciling with the tool, where the tool declared that can be done

ADR-0014 §4 fixes both routes out of `INDETERMINATE` and neither is a guess: it *"is never auto-retried and must be resolved
explicitly — by reconciling with the tool or by asking the user"*. ADR-0029 §5 repeats the pair — *"Both remain resolvable
by asking the user or by reconciling with the tool, which is the explicit resolution ADR-0014 §4 requires"*. This section
implements the **first** route and explains why the second is not taken here.

> **Normative — a step is reconcilable exactly where the `ToolDefinition` recorded for its committed `bound_tool` is **not
> `side_effecting`** *and* the `PermissionDecision` its `approval_ref` names carries **no `egress_binding`** — the complete
> conjunction, never one half of it, wherever this rule is summarised.** **The call this section admits is a read**, and
> nothing else. That second conjunct is the corpus's own mark for an egress call — the field is *"`None` for every decision
> about a non-egress call"*, which is the same test `ToolInvocationRow.egress_call` is declared over. **Every other
> `INDETERMINATE` step is uncheckable** — every side-effecting step whatever its `Idempotency`, `NATURAL` included, and
> **every egress step whatever its declaration** — for the reasons stated below and booked in §10, and **no `ToolDefinition`
> field is added to say so**: the existing declarations are that test already.

> **Normative — the first conjunct is strictly narrower than ADR-0192 §1's non-spendability and is its own test rather than a
> borrowed one.** That section rules an authorisation spendable *"when the decision's `ToolDefinition` is `side_effecting` and
> its `idempotency` is not `NATURAL`"*, so the non-spendable set is **two** declarations — a read **and** a side-effecting
> `NATURAL` tool — and only the first is admitted here. **The relation that matters is one way and is relied on**: every call
> admitted is non-spendable, so `InvocationLedger`'s further-claim admission covers it and **no clause here widens ADR-0192
> §1, adds an admission, or changes any signature on it**. **No lane reads non-spendability as the test.**

> **Normative — the side-effecting `NATURAL` tool is excluded, and the ground is that its declaration is about the effect and
> not about the answer.** ADR-0016 §4 declares `NATURAL` as *"the operation is idempotent by nature (a read; set-to-a-value)"*
> — **a guarantee about what a repeat does to the world, and about nothing else**. **Nothing in this corpus declares that a
> repeat returns what the first call returned**, and a write that sets a value is free to answer with the value it replaced: a
> tool that moved a setting from `home` to `away` and answered `home` answers `away` to the reconciliation, and §3 would
> commit `away` as the step's `output` for a dependent reading it as the value to restore. **That is an `output` no clause
> here could justify**, so the step is left uncertain instead — ADR-0014 §4's own direction, that *"guessing would not be"*
> the deterministic answer. §10 books it with what fires it.

> **Normative — and the exclusion is what makes act 4 need no supersession test.** ADR-0255 §7 rules that a plan superseded
> after driving drives nothing further, and a reconciliation that **acted** for a superseded plan would breach it — a user who
> moved a booking to Sunday would get the Saturday one made to find out whether it had been. **A read performs nothing**, so
> remaking it neither drives the plan nor changes the world whatever the plan's status; §4's act 4 therefore reconciles a
> superseded plan's step like any other and **ADR-0255 §7 is not reached rather than scoped**. **A later decision admitting a
> call that acts states its own supersession rule first**, and §10 books that with the route.

> **Normative — and *drives nothing further* is read as ADR-0255 defines it, not as a prohibition on every later call.** That
> decision's §3 says in terms what its own phrase means: *"a walk that had already run when the supersession was recorded is
> not undone — what this conjunct refuses is the **next** claim, which is what "drives nothing further" says."* §3 of this
> document **takes no claim**, makes no `→ RUNNING` transition and is not the driver (§4), so the conjunct it would be refused
> by is never reached. **And ADR-0255 expects exactly this**: §6's override keeps an `INDETERMINATE` step **out of** §7's
> sweep, so such a step on a superseded plan is deliberately left standing, and §12 books *"how an `INDETERMINATE` step is
> resolved"* to A8 by name. A reading under which a superseded plan's `INDETERMINATE` step could never be reconciled would
> leave it, and its attempt's `EFFECT_UNRESOLVED`, standing for ever with no decision named to resolve them — which is the
> strand this document exists to close.

> **Normative — the `KEYED`-inside-its-window route is not taken, and no lane takes it on this decision's authority.**
> `InvocationLedger.claim_invocation` refuses a further **spendable** claim where **any** claim under that decision carries
> the outcome `INDETERMINATE` (ADR-0192 §1), and an `INDETERMINATE` step is exactly a step whose ledger claim was completed
> that way — by the seam on a deadline (ADR-0029 §4) or by the recovery scan (ADR-0192 §3). So a `KEYED` reconciliation call
> **cannot reach the tool through `ToolInvoker.invoke`**, and **this decision adds no second invocation seam, no
> reconciliation admission on `InvocationLedger` and no parameter to any existing member**. **No implementation of this
> decision calls a `KEYED` tool to reconcile a step**, and §10 carries the route with what fires it.

> **Normative — the reconciliation call is the authorised call rebuilt from durable state, and the rebuild is proved rather
> than trusted.** The `ActionRequest` is rebuilt the way `StepRunner` builds one — the step read from the plan, its `resolves`
> resolved from the stored `ExecutionState`, which ADR-0253 §6 makes *"a total function of two values both read from the
> `PlanStore`"* and therefore reproducible after any restart — and the `PermissionDecision` is the one the step's
> `approval_ref` names, read through `AuditTrail.get`. **The rebuilt request is checked against that decision by
> `PermissionDecision.authorises` and the call is made only where it returns true**; **where it returns false the step stays
> `INDETERMINATE`, nothing is written and no call is made.** **No new `ActionPolicy.decide` is taken, no new decision is
> recorded and no new authority is sought.**

> **Normative — it is a reconciliation and not a retry.** ADR-0029 §5's exclusion binds verbatim and is **not relaxed**: an
> `INDETERMINATE` outcome is never **auto-retried**. What this section performs is the route ADR-0014 §4 names beside that
> exclusion, and only on a read. **A lane that reads this as licence to re-call a side-effecting tool of any declaration has
> read the opposite of the rule.**

> **Normative — this is automated reconciliation landing without the lookup ADR-0192 §3 names as its trigger, and the
> difference is recorded rather than glossed.** That section rules that *"The ADR that lands automated reconciliation is fired
> by a tool contract that offers a **lookup by idempotency key**"*. **This decision lands it without one, on a non-egress read
> alone** — the conjunction above — and §13 carries the partial supersession that fact owes. **The side-effecting `KEYED` case
> that section was written about is untouched and still waits**, for that lookup or for the ledger admission §10 books. **No
> lane reads this clause as licence to reconcile a spendable authorisation.**

> **Normative — what its result writes, and what it does not.** Where the call returns a successful `ToolResult`, the step is
> committed **`INDETERMINATE → SUCCEEDED`**, setting `output` from that result and re-stamping `finished_at` at the
> reconciliation's own instant, and **clearing `failure`** as ADR-0039 §2 requires of a `SUCCEEDED` step. **`attempts` is not
> incremented** — the call established what happened and was not an attempt at the effect. Where the call returns anything
> else — a failure, a timeout, an `INDETERMINATE` of its own — **or where the call cannot be built at all**, because the step
> carries no `approval_ref` or the decision it names cannot be read, **the step stays `INDETERMINATE`, nothing is written, and
> neither a failed reconciliation nor an unbuildable one is ever read as establishing that the effect did not happen.**

> **Normative — at most one reconciliation call per step per turn**, taken inside §4's pass, on the turn's own deadline
> (ADR-0255 §9). **No lane loops, backs off, schedules a second, or re-calls a step the same turn already reconciled.**

> **Normative — the reconciliation call is gated on the turn's remaining budget, under §4's rule for the whole pass.** The
> remainder is read immediately before the call and passed as its `timeout`; a non-positive one makes no call and leaves the
> step `INDETERMINATE`. §4 states that gate once, over every act of the pass.

> **Normative — the seam's *declared refusals of this call* end the pass and never the turn; everything else propagates, and
> the two are not one case.** `ToolInvoker.invoke` names the exceptions it raises instead of returning a `ToolResult`, and
> **exactly six of them are refusals of this call that a later turn could meet differently**: `ToolBindingError`,
> `SpendCeilingError`, `SpendUndeterminedError`, `AuthorisationSpentError`, `UnrecordedAuthorisationError` and
> **`AuditError`**. A restart makes the first ordinary, since the tool a stored decision names need not be registered by the
> process that comes back; and the last is **the invocation-claim append failing**, which its own declaration calls a
> *"**pre-callable**"* exit — a store failure at the seam, and therefore §4's store-failure case reached through a different
> door rather than a second rule about it. **On those six the reconciliation writes nothing, the step stays `INDETERMINATE`,
> the pass ends at act 4, what earlier acts landed stands, nothing is retried inside the turn, none of them escapes into the
> turn's own work, and the turn does not fail.**

> **Normative — an *undeclared* exception is a defect and is not swallowed.** **Any exception the seam's contract does not
> name** is propagated unchanged out of the pass, and so is a **`ValueError`**, which that contract raises only for a
> `timeout` that is not a strictly positive `timedelta` — a value this pass computes from the turn's own deadline, so raising
> it is this system's bug and not the seam's refusal. A seam that raises where its contract says it returns is broken, and
> catching it would repeat one silent failure on **every** engagement of the goal for ever while the record read as merely
> uncertain — the opposite of what a pass whose whole subject is uncertainty should do. **`CancelledError` propagates too**,
> as at every other await in this system, and is not counted among the six. **No lane widens the six by catching a base
> class**, retries the call, translates any exception into a step transition, or reads a raised seam as establishing that the
> effect did not happen.

> **Normative — the reconciliation call takes no step claim, ADR-0014 §4's claim-before-invocation rule is untouched, and the
> concurrency this leaves is bounded rather than denied.** That rule is stated over the **`→ RUNNING` transition** — *"The `→
> RUNNING` transition is a claim, and must be committed before the tool is invoked"* — and a reconciliation **makes no such
> transition**: the step is `INDETERMINATE`, it stays `INDETERMINATE` until the call returns, and §7 admits only
> `INDETERMINATE → SUCCEEDED` out of it. **No lane invents a claim for it, moves the step to `RUNNING` first, or reads this as
> licence to invoke a `PENDING` step without one.** Two turns engaging one goal at once can therefore each make the call, and
> **that is admitted rather than overlooked**: the call §3 admits is a read whose authorisation ADR-0192 §1 rules
> non-spendable, where *"no claim under it is ever refused on the ground that it is spent"* — the corpus already contemplating
> the same authorised read being made as often as the pipeline needs it — and where ADR-0029 §4 rules a repeat changes
> nothing. **What is not concurrent is the record**: both turns' `→ SUCCEEDED` commits are compare-and-swaps on one
> `ExecutionState`, so **exactly one lands** and the loser writes nothing, which is ADR-0014 §5's discipline doing here what
> it does everywhere else. **ADR-0148 §9's *"There is no egress outside a claimed step"* is not reached at all**, because the
> test above admits no call carrying an egress binding, so nothing this section performs is a transmission through the
> designated seam.

> **Normative — an uncheckable effect stays uncertain, is told once, and is never repeated.** Its step stays
> **`INDETERMINATE`**, its attempt stays **`EFFECT_UNRESOLVED`** (§4), its effect key answers **`UNCERTAIN`** to every later
> claim (§2), and **no lane moves it to `SUCCEEDED`, `FAILED` or `SKIPPED`, reconciles it by inference, or dispatches its
> effect again.** **That the user is told, and once, is A9's report** (§10); this decision fixes only that the record the
> report reads is preserved, which is R45 exactly.

> **Normative — the user's word does not resolve a step under this decision.** ADR-0253 §2 evaluates a producing step's
> `verifies` predicate *"over its `output`"*, so a step committed `SUCCEEDED` is one whose dependents read an output, and a
> user can assert that a booking happened without supplying the reservation it returned. **So no clause here takes a user's
> assertion as a step transition**, and the route ADR-0014 §4 names second is **booked, not refused** (§10).

**The read is the one call the corpus makes harmless to repeat in *both* senses — it changes nothing, and its answer is the
state rather than a transition — which is why the test is over `side_effecting` rather than over spendability.** ADR-0029 §4
states it in the same breath as the classification this section's subject comes from — *"A read that timed out changed
nothing and there is nothing to be ambiguous about"* — so the call establishes the step's status whether or not the first
one landed, which is what R44 asks for. `claim_invocation` states the permission: *"An **authorisation is spendable** when
the decision's `ToolDefinition` is `side_effecting` and its `idempotency` is not `NATURAL`"*, and on any other *"no claim
under it is ever refused on the ground that it is spent"*. Such a reconciliation therefore reaches the callable with **no
ledger *contract* change and no signature change** — and **not** with no ledger *write*: `ToolInvoker.invoke` appends its
invocation claim before the callable and its completion after, exactly as it does for every other call, so the
reconciliation's outcome and cost are in the trail like any other act's. What the non-spendable authorisation buys is that
the **further** claim is *admitted*, and ADR-0192 §1's requirement that every call carry one **binds entire and is relied on
here**.

**An egress step is excluded because ADR-0148 §9 rules the seam it would go through, and its two sentences admit no wording
around them.** That section states *"**There is no egress outside a claimed step**"*, and of the recovery path by name,
*"**A designated seam adds no reconciliation path of its own**, relaxes none of ADR-0014 §4's treatment of `INDETERMINATE`,
and never resolves a pending attempt by guessing."* §3's call takes **no** `→ RUNNING` claim, so an egress reconciliation
would be a transmission outside a claimed step **and** a reconciliation path a designated seam added — each forbidden on its
own. **This decision excludes the case rather than superseding either sentence**, leaving ADR-0148 entire (§13); §10 books
the shape a later decision would take and what fires it.

**A side-effecting `KEYED` tool has the harmlessness and not the permission.** Inside its window such a call carrying the
first call's key returns the first call's outcome and performs the effect at most once — the better guarantee of the two,
and the only declaration in the corpus that is answer-stable as well as effect-stable. But `claim_invocation` admits a
**further** claim only where *"**no** claim under it carries the outcome `SUCCEEDED` or `INDETERMINATE`"*, and an
`INDETERMINATE` step is exactly one whose ledger claim was completed that way. That floor was written for a **retry** and
catches a **reconciliation**; §10 books lifting it — R45's requirement and not R44's.

**A read reaches this section only through a crash, and that is why the test is worth having at all.**
`ToolDefinition.interrupted_outcome` classifies an interrupted call of a tool that is not `side_effecting` as `FAILED`, so a
timeout or a cancellation never produces an `INDETERMINATE` read step. What does is the startup recovery scan (§6), which
moves any step left `RUNNING` by a dead process to `INDETERMINATE` **without consulting a declaration**. Leaving reads out
would therefore strand exactly those steps — uncertain for ever, and the attempt `EFFECT_UNRESOLVED` for ever with them,
because §7 admits no other move out — for the sake of a caution spent against the one outcome nobody doubts. **A read
carries no effect key at all** (§1), so nothing is blocked by a later plan's claim either way; what the reconciliation buys
is the record, and the record is what R45 asks be preserved and R44 asks be established.

**Rebuilding the request rather than storing it is what makes a restart survivable, and the rebuild is checked rather than
assumed.** ADR-0253 §6 makes the resolution *"a total function of two values both read from the `PlanStore`"*, so the
concrete mapping is reproducible — and `PermissionDecision.authorises` is the check that it **was** reproduced, comparing
the tool, the digest, the step, the execution and the binding before anything is called. A rebuild that drifted — a plan
edited, a reference whose producer's output changed, a binding no longer available — fails that comparison and the step
stays uncertain, which is the safe direction, and it is why §3 needs no durable carrier for a parameter mapping.

**Holding the tool to its window is already a two-sided obligation, so this reads a declaration rather than trusting one.**
ADR-0029 §5 puts both sides in the conformance suites. What this section adds is a **reader** of the declaration at the one
moment it decides something: whether an uncertain effect can be established at all. The window is read at the instant of the
call, on ADR-0026's clock discipline, from the definition recorded for the **committed `bound_tool`** — never from a
registry lookup that a mutated declaration could answer differently, which is `interrupted_outcome`'s own stated reason.

**An `Idempotency.NONE` side-effecting tool is where this system's honesty is spent, and it is spent deliberately.** R80 is
satisfied *as stated* on the corpus precisely because ADR-0014 §4 and ADR-0148 §9 *"both refuse the exactly-once claim"*.
Nothing in this decision converts local persistence into a remote guarantee. What it converts is the **consequence** of not
having one: before, an uncertain effect was a state nothing could resolve and nothing could stop being repeated; after, it
is a state that resolves where the integration supports it, and that is **durably un-repeatable** where it does not.

### 4. The reconciliation pass: at the start of one turn, over one goal, finishing writes and starting no job

> **Normative.** `orchestration` gains a **reconciliation pass**: a concrete collaborator run **inside a turn**, **after that
> turn has engaged its goal** (ADR-0250 §1) and **before the turn's first `Planner.plan` call**, **over that one goal and no
> other**. It stamps **no `AttemptPhase`** (ADR-0249 §6's writer clause), opens **no attempt** (ADR-0249 §5: an attempt is
> opened only by a user act), writes **no `GoalStatus`**, **opens no walk and dispatches no `PENDING` step**. **It reaches a
> dispatch through exactly one of its acts — act 2's replay of an authority the trail already holds — and through no other**,
> and §3's reconciliation call is not a dispatch of a step but the remaking of a call already made.

> **Normative — it performs exactly five acts, in this order, and no sixth.** Over the goal the turn engaged:
>
> 1. **Complete a supersession sweep.** For every plan of that goal that a stored plan supersedes, each step standing
>    **`PENDING`** or **`AWAITING_APPROVAL`** is committed **`→ SKIPPED`** with **`skip_reason=SUPERSEDED`**, which is
>    ADR-0255 §7's own sweep, from its own two source statuses. **This act releases no effect row and deletes none**: a
>    row is reached only through `claim_effect` (§9), and freeing the claim of a `FAILED` holder whose plan is superseded
>    is that member's own branch (§2), decided in the store because only there is it atomic with the write.
> 2. **Apply a recorded resolution.** For every step standing `AWAITING_APPROVAL` on a plan
>    **no** stored plan supersedes whose binding `AuditTrail.resolution_of` answers: a **`DENY`**
>    commits **`AWAITING_APPROVAL → SKIPPED`** with **`skip_reason=APPROVAL_DENIED`**, naming that
>    decision; an **`ALLOW`** is replayed through `StepRunner.resume` under §5, after ADR-0255
>    §5's three predicates have been re-evaluated and only where every one of them holds. **This
>    act is the only caller of that replay**, and where a predicate refuses, `resume` is not
>    called, nothing is resolved and the step stays parked (ADR-0255 §5).
> 3. **Repair the attempt's state.** For every attempt of that goal whose `state` is **`RUNNING`** and one of whose
>    executions holds a step standing **`INDETERMINATE`**, commit it **`EFFECT_UNRESOLVED`** through `commit_attempt`.
> 4. **Reconcile.** For every **reconcilable** `INDETERMINATE` step of that goal (§3), take one
>    reconciliation call and write what §3 says it writes.
> 5. **Release the attempt.** Where an attempt stands `EFFECT_UNRESOLVED` and **no** step of any
>    of its executions stands `INDETERMINATE` or `RUNNING`, commit it **`RUNNING`** (§7).
>
> **Acts 1 and 2 apply ADR-0255 §6's override**: no step of an `INDETERMINATE` branch and no step behind an `INDETERMINATE`
> step is swept, and a sweep that meets one **is not thereby partial**.

> **Normative — the pass is authorised to complete these writes, and that is stated rather than derived.** ADR-0255 §6 and §7
> each forbid a lane retrying their partial writes *"from a later turn **on its own authority**"* and each names the exception
> in the next clause — *"repairing that residual is A8's"*, *"A8's reconciliation … is the **only** one that may complete a
> sweep"*. **This decision is that authority**, and it is the only one: **no other lane, and no implementation of any other
> decision, completes a sweep, repairs an attempt's state, or reconciles a step.**

> **Normative — the pass charges the turn's budget, and every one of its acts is gated on the remainder exactly as any other
> act of the turn is.** ADR-0255 §9 rules that *"immediately before it begins **any** of them"* — *"every unit of work the
> walk starts"* — the remainder is read from that turn's **monotonic** source and nothing is started where it is **not
> strictly positive**. **This pass reads that remainder immediately before each of its five acts and starts none of them
> where it is not strictly positive**: the step or attempt keeps the state it stood at, **the pass ends there** with what
> earlier acts landed standing, and **the turn does not fail**. **No enumeration of which acts are units of work is made or
> needed** — §9 is applied to the pass as a whole, so nothing turns on classifying one act. **An act already begun runs to
> its own completion**, §9's own posture, so a compare-and-swap the pass has reached lands rather than being abandoned.
> **Where the act takes a `timeout`** — act 2's `ALLOW` replay through `StepRunner.resume`, and act 4's reconciliation
> call — **the remainder just read is what is passed**, and **no lane passes the turn's whole figure to more than one act
> or fixes a second deadline inside the pass**. The gate is also what keeps §3's propagating `ValueError` a statement about
> **defects**: `invoke` and `StepRunner` each
> refuse a non-positive `timeout`, so without it an exhausted turn would raise one and fail on the most ordinary event this
> pass can meet. **Its cost is one turn's delay** on a repair the next turn redoes, which is what every other early end in
> this section already produces.

> **Normative — the pass makes every write as a compare-and-swap and stops at the first that loses.** A stale
> `expected_version` or a store failure ends the pass for that turn; **what landed stands, nothing is undone, nothing is
> retried within the turn**, and the next turn that engages the goal runs it again over whatever is then residual. **A pass
> that ends early does not fail the turn** — every act is a repair of a record, not a prerequisite of the turn's work. **An
> undeclared exception is the one thing that does escape it** (§3).

> **Normative — it infers nothing.** `EFFECT_UNRESOLVED` is **written** by act 3 and never derived at read time (ADR-0255 §6,
> ADR-0249 §6); `SUPERSEDED` is committed by act 1 and never inferred from a `supersedes` chain. **No status of any record is
> computed from another record by any consumer.**

> **Normative — it is bounded by the turn and by the goal, and it is not a background pass.** It runs only on a turn the user
> initiated, only over the goal that turn engaged, only under that turn's deadline, and **nothing schedules it, queues it,
> retries it out of band or runs it for a goal no turn engaged** — ADR-0255 §12's outside-a-turn entry left exactly where it
> stands.

**ADR-0250 §12's clause binds here and is satisfied rather than scoped, and the working is this.** Its *"no scheduler, no
job and no background pass **is added**"* is stated as the consequence of settling an expiry *"at the first operation that
reads it"* — ADR-0244 §10's shape, where the settling work is done by whoever next looks. **This pass is that shape, not
its opposite**: the first operation that reads the residual, inside an owner-initiated turn, over that turn's goal, on its
budget. Nothing is scheduled, polls or wakes, and ADR-0083 §7's *"no job gets new store surface"* is not reached —
`claim_effect` is reached by a dispatch, not a job. So the clause is **relied on and not superseded** (§13).

**And it runs before planning rather than after, because planning is what reads it**, which the owner's decision 3 requires
a late answer to. A planner handed a goal whose superseded plan still shows a `PENDING` step, or whose attempt still reads
`RUNNING` beside an uncertain effect, reasons from a record the system knows is stale; running first also lets §2's key be
free by the time the walk reaches a step whose predecessor was swept.

### 5. The resolved-but-unapplied answer: the recorded ruling is replayed, and nothing is re-asked

ADR-0255 §12 states the residual and leaves the choice open — *"the step is re-askable or the answer is re-appliable"*.
**This decision takes re-appliable**, and it takes it with the query ADR-0059 §2 already landed for exactly this.

> **Normative.** **The answer is re-appliable and the step is never re-asked.** No second `CONFIRM` is minted for a binding
> that already carries a resolution, `AuditTrail.record`'s single-resolution rule and ADR-0044 §2(b)'s per-binding rule bind
> **verbatim and untouched**, and **no clause of this decision authors any permission record at all.**

> **Normative — `StepRunner.resume` replays a recorded resolution instead of authoring one.** Where
> `AuditTrail.resolution_of(execution_id=…, step_id=…)` returns a decision for the binding, `resume` **skips ADR-0037 §4's
> steps 4 and 5** — it calls **no** `ActionPolicy.resolve` and records **nothing** — and proceeds to that section's **step 6**
> with the returned decision: an `ALLOW` is read back and executed, a `DENY` commits `AWAITING_APPROVAL → SKIPPED` with
> `skip_reason=APPROVAL_DENIED`. **Every other step of that sequence is unchanged**, steps 1–3 included, and `_check_parked`'s
> binding of the confirmation's tool to the reloaded step's `bound_tool` binds entire.

> **Normative — the caller's answer does not override a recorded one.** Where a resolution exists, the disposition is **the
> recorded decision's ruling** and not the `approved` value the caller passed. A second answer to an answered binding
> **decides nothing**, which is ADR-0044 §2(b)'s refusal *"reaching the caller as an answer instead of as an error"*, in
> ADR-0198 §3's own words.

> **Normative — the replayed dispatch is a dispatch and takes every check one takes, and §4's act 2 is its only caller.**
> ADR-0255 §5's three predicates are re-evaluated before `resume` is called with an `ALLOW` — the dependency rule, every
> member of `when`, and the resolvability of every `resolves` — ADR-0255 §3's claim conjuncts bind at the `→ RUNNING` commit,
> and §2's effect claim is taken immediately before it. **A denial is gated on none of them**, exactly as ADR-0255 §5 rules.
> **No walk calls this replay**: ADR-0255 §5's rule that an `AWAITING_APPROVAL` step *"stops the walk where it stands"* binds
> verbatim, which is why the replay belongs to a pass that runs **before** the walk and leaves the step disposed of by the
> time one reaches it.

> **Normative — the superseded-plan ground is excluded by name.** Where a stored plan supersedes the step's plan, §4's act 1
> sweeps that step to `SKIPPED`/`SUPERSEDED` and **the resolution is never replayed**, because the approval authorises nothing
> there (ADR-0255 §3, §7). **No lane replays a resolution onto a step of a superseded plan.**

> **Normative — the one-shot approval is spent exactly once, and that is what re-applying buys.** The user's answer authorises
> **one** dispatch; replaying the same recorded `ALLOW` reaches that dispatch without a second record, so ADR-0036 §2's unique
> index is never approached and the answer is neither lost nor doubled. **No lane reads a replay as a fresh authority**, and
> ADR-0254 §13's comparison at `ActionPolicy.decide` is taken at the dispatch as it is at every dispatch.

**Re-asking was the available alternative and it is rejected on a rule, not a preference.** ADR-0044 §3 states that where a
binding carries a resolution *"the binding is decided and no further resolution may be recorded"*, and ADR-0198 §3 records
that a direct retry *"re-enters resolution and meets the trail's single-resolution index"*. So re-asking would need either a
second binding for one step — which ADR-0044 §2 forbids by making the binding the unit — or a relaxation of the
single-resolution rule, which would make *"did the user answer this"* un-answerable. **Neither is a narrowing; both are new
rules.**

**This closes #257's first half and leaves its second exactly where ADR-0255 §12 puts it.** #257 names two closures: *"Find
the recorded ruling for a parked step"* and *"Make the pair atomic"*. The first landed as `resolution_of` (ADR-0059 §2) and
gets its consumer here. **The second is not taken** — it *"needs `PlanStore` to accept more than one transition in a
commit"* — and §10 carries it with what fires it. **The two instances of #257 that still exist close on the first**:
`resume`/`ALLOW` and `resume`/`DENY`, by the replay above. The third #257 named — an initial `DENY` at `run` whose skip
failed — **is already gone and is not closed here**, because ADR-0037 §5 says so in terms: *"The third window #257 named …
is gone: §5's denial is now a single commit over ADR-0041's direct edge, so there is no gap on that path to strand in."* Act
2 could not reach it in any case: `resolution_of` answers *"the ALLOW or DENY whose `resolves` names a CONFIRM"*, and a
`DENY` recorded at `run` resolves nothing.

**And it is driven by §4's act 2 rather than by a new façade method, which is the budget ADR-0059 §2 asks for.** That
section rules that driving a stranded binding *"belong[s] to `resume` … or to a distinct, explicitly-budgeted recovery
operation, **never** to `pending_confirmations`"*. §4's pass is the second of those, budgeted by the turn's own deadline.
**`AssistantEngine` gains no member and no enumeration changes** (§9), so ADR-0052's presentation question is untouched —
this decision neither surfaces a stranded park nor changes what any enumerator returns.

### 6. The startup scan, and the engagement stamp

> **Normative — the startup recovery scan writes no attempt state.** It keeps ADR-0014 §4's behaviour entire — it scans
> `active_executions()`, completes every open invocation claim (ADR-0192 §3) and moves a stranded step `RUNNING →
> INDETERMINATE` — and **writes no `AttemptState`, reads no `GoalAttempt`, and takes no reconciliation call.** **It gains no
> collaborator and no argument.**

> **Normative — the attempt is repaired when the goal is next engaged, and not before.** §4's act 3 is the producer for the
> residual the scan leaves, which is the same producer as for the residual ADR-0255 §6's second write leaves. **There are
> exactly two producers of `EFFECT_UNRESOLVED` in the corpus after this decision** — the driver, for a step it drove (ADR-0255
> §6), and §4's act 3 — and **no third is added by any lane.**

> **Normative — the residual #2317 records needs no repair mechanism, and none is added.** A resumed park whose `engage_goal`
> lost its compare-and-swap leaves `last_engaged_at` unmoved; **§4's pass does not write it**, because writing it would make
> the pass a fifth act that engages a goal, and ADR-0250 §1 closes that enumeration at four. **The next engagement of that
> goal writes the stamp**, which is ADR-0250 §1's own mechanism doing its own job.

**Giving the scan an attempt would be the wrong shape, and ADR-0255 §12 says why in its own firing condition.** That entry
is *"Fired by the lane that gives the scan an attempt to write to"*, and this decision declines to be that lane. The scan
*"runs outside a turn with no attempt in hand"*; reaching one would mean walking execution → plan → goal → attempt at
startup, for every stranded step across every goal, with no user present and no deadline — a background pass in all but
name, the thing ADR-0250 §12's prose declines, and a **third** writer on a state ADR-0249 §5 gives one authority. The repair
is owed to the **goal's next turn**, the first moment anybody reads the attempt.

**The cost of deferring it is one stale field on a record nobody is reading, and it is bounded.** Between the restart and
the goal's next engagement, an attempt may read `RUNNING` while one of its steps is `INDETERMINATE`. Nothing dispatches on
that: the step's status is *"the authoritative record of the uncertainty"* (ADR-0255 §6) and is the value §2's effect claim
reads, so the effect is un-repeatable throughout the interval whatever the attempt says. What the interval costs is the
attempt's own summary being less informative for exactly as long as nobody looks at it.

**#2317 is answered rather than mechanised, and the reason is what the value is for.** ADR-0250 §1 derives focus on every
read and stores it nowhere; the issue's own analysis says *"the next engagement of that goal repairs it; nothing is lost but
the ordering of one candidate set"*. A repair mechanism for a hint that the next read repairs is machinery bought for
nothing, and it would need the pass to take an act ADR-0250 §1 enumerates as a user's. **What would reopen it** is a
measured case in which the stamp stays unwritten **across** turns — which would be a fault in M3's bounded retry rather than
a missing reconciliation act, and would be that lane's to fix.

### 7. After a resolution: no automatic re-drive is added, and the turn's own route is unchanged

ADR-0255 §12 books *"An automatic re-drive of a stopped walk — continuing a plan after an `INDETERMINATE` step is resolved"*
to A8 as *"the lane that resolves an `INDETERMINATE` step and is the only one with something new to drive on"*. **This
decision answers it by adding no route**, and states why the resolution is nonetheless what makes the branch drivable again.

> **Normative — no automatic re-drive is added, and ADR-0255 §2's closed list stays closed.** That section's clause binds
> verbatim: *"A stopped walk is re-entered by **exactly one** route: `StepRunner.resume` answering a park of that plan …
> **There is no sweep, no timer, no queue, no background continuation and no automatic re-drive** of a plan the walk stopped
> on any of the other four triggers. A later turn of the same attempt **plans again** — which produces a **new** plan, driven
> over a **new** execution."* **No clause of this decision re-enters a stopped walk, selects a plan for a turn, walks a plan
> the turn was not handed, or resumes a walk over a superseded one**, and ADR-0255 §7's *"one plan is driven per walk, and it
> is the plan the turn holds"* is untouched.

> **Normative — what the resolution buys is the order and the record, and not a claim.** §4's pass runs **before** the turn's
> first `Planner.plan` call, so a step reconciled to `SUCCEEDED` is `SUCCEEDED` before the turn plans and before anything is
> walked: the planner reads a goal whose uncertain step is settled, its attempt is releasable by act 5, and the dependents of
> that step are evaluated under ADR-0253 §2 like any others wherever the turn's walk reaches them. **What it does not buy is a
> `COMPLETED` answer to a later plan, and that is stated rather than assumed.** §3 admits a **read** alone; §1 gives a read
> **no effect key**; so no row is written for it, `claim_effect` is never called for it (§2), and **a fresh plan that reads
> the same thing again is dispatched and reads it again**. That costs nothing — a read changes nothing, and a second read is
> fresher — and it is why the reconciliation is worth taking for a record rather than for a claim. **No second walk is
> scheduled, no walk is re-entered inside one turn on account of a resolution, and no `Planner.plan` call is taken on account
> of one.**

> **Normative — the attempt returns to `RUNNING` only when nothing is outstanding.** §4's act 5 commits `EFFECT_UNRESOLVED →
> RUNNING` **only** where no step of any of that attempt's executions stands `INDETERMINATE` or `RUNNING`. `EFFECT_UNRESOLVED`
> is not terminal (ADR-0249 §5), so the move is legal; **no lane moves an attempt out of a terminal state**, and **no lane
> moves it to `RUNNING` while an uncertain effect stands.**

> **Normative.** ADR-0014 §4's transition table gains exactly three rows and **no other**: **`INDETERMINATE → SUCCEEDED`**,
> trigger *reconciliation established the effect*; and **`PENDING → SUCCEEDED`** and **`AWAITING_APPROVAL → SUCCEEDED`**,
> trigger *satisfied by an effect this goal already completed* (§2). Each also sets `output` and `finished_at`, and none
> increments `attempts`. **Two rows rather than one for the satisfaction, because §2 takes the claim on both entries** —
> `StepRunner.run`'s and `StepRunner.resume`'s — and a resumed step is `AWAITING_APPROVAL` in the store, so a single `PENDING`
> row would leave the resumed case with no legal move and the walk stalled at exactly the step this decision exists to
> unstall. `INDETERMINATE → FAILED`, `INDETERMINATE → RUNNING`, `INDETERMINATE → SKIPPED` and every other move stay
> **illegal**, and `PlanExecution` refuses each with `PlanningError` as today.

**One row *out of `INDETERMINATE`* rather than two is a consequence of §3's mechanism, not a gap in it.** A reconciliation
that establishes *"the effect did not happen"* would want `INDETERMINATE → FAILED`. Under the one route §3 admits, that
outcome does not arise: the call is a **read**, which has no effect to have failed to happen, so a returning reconciliation
ends at `SUCCEEDED` and a non-returning one leaves the step where it stood. The transition that would record a proven
non-effect has **no producer**, and adding a row nothing writes would be the vocabulary-with-no-producer problem ADR-0249 §5
names. §10 carries it: the decision that takes a second reconciliation route is the decision that adds the row.

**`FAILED` stays terminal-unless-retried and this decision does not reach it.** ADR-0014 §4's *"`FAILED` is terminal unless
retried"* and its `FAILED → RUNNING` row are untouched; **whether and when a `FAILED` step is retried across turns is the
retry policy**, and that is the next ADR's (§10). What this decision settles about `FAILED` is one thing only: which step
may take the key of a row a `FAILED` step holds (§2) — that step itself, so its own retry proceeds, and no other.

### 8. The evidence-to-claim window is booked, not closed, and the ground is stated

> **Normative.** **This decision does not close the evidence-to-claim window** ADR-0255 §1 states and §12 books as #2309, and
> **no lane reads any clause here as having closed it.** ADR-0255 §13's second added prerequisite to the Q4 wiring gate
> therefore **stands undischarged** by this decision, and remains a prerequisite in its own right.

> **Normative — what fires it, and what a lane may not do meanwhile.** It is fired by **a decision that chooses between the
> two mechanisms ADR-0255 §12 names** — a value the claim carries, or ADR-0252 §6's four tests evaluated inside
> `commit_transition` — or by **the wiring of the first consequential capability**, whichever is first. **No lane adds either
> mechanism on its own authority**, which is ADR-0255 §12's clause binding unchanged.

> **Normative — this decision adds no prerequisite to that gate**, and ADR-0255 §13's own count of **two** stays true of that
> decision. **The gate's total is not two**: ADR-0265 §6 added a containment for a wrongly minted intended action, which is
> why ADR-0255 §15 item 19 now enumerates **six** conditions and not five. **Its own guarantees are the reconciliation half of
> the gate's first three** and are discharged by the lanes §11 cuts.

**Booking it rather than taking it is a judgement about what the two mechanisms are, and it is argued rather than
asserted.** Both close a window about **authority to act**, not about **an act already taken**. The first — an evidence
token compared by the store — is a new value on `StepTransition` that ADR-0255 §3's argument against a caller-supplied
revision applies to unchanged. The second puts **a clock and a plan's `when` conditions inside `PlanStore`**, duplicating
the driver's own predicate in a second place free to disagree with it. Taking either inside a decision whose subject is
effects that have already happened would make this ADR's review the review of a mechanism nobody had reasoned about in its
own terms — and ADR-0255 §12 is explicit that the choice between them *"is a decision of its own"*.

**What holds meanwhile is stated rather than assumed.** ADR-0255 §13's Q4 rule binds: no consequential capability is wired
until the guarantees for its class are implemented and demonstrated, and the window is one of its named prerequisites. So
the interval in which this decision lands and #2309 stands open is an interval **with no real consequential integration in
it** — the same construction ADR-0255 §7 uses for cross-plan at-most-once.

### 9. The `core` surface, the stored shapes, and the wire

> **Normative.** `core/types.py` gains exactly five declarations — **`EffectKey`** (§1), **`EffectClaim`** with its five
> members and **`EffectOutcome`** (§2), **`EffectRecord`** (below) and **`ToolCall.effect_key`**, a property and **not a
> `computed_field`** — for `idempotency_key`'s own recorded reason, that a computed field enters `model_dump()` and ADR-0018
> §4's registration rebuild runs against `extra="forbid"`. **`Disposition` gains exactly two members**,
> `EFFECT_ALREADY_CLAIMED` and `EFFECT_UNSCOPED` (§2); **`PlanExport` gains exactly one field**, `effects`; **`StepExecution`
> gains exactly two**, `satisfied_by_execution` and `satisfied_by_step` (§2), **and `StepTransition` gains exactly three**,
> that pair and `satisfied_by_key` (below); and **`TurnOutcome` gains exactly one**, `satisfied_from_earlier`, in ADR-0242
> §9's shape.

> **Normative.** `EffectRecord` is a frozen model with `extra="forbid"` whose fields are exactly **seven**: **`goal_id:
> Identifier`**, carrying the annotation `ActionPlan.goal_id` uses; **`intended_action_id: Identifier`**, carrying the
> annotation `IntendedAction.id` uses (ADR-0265 §1) and **never `None`**, since §2 refuses the claim of a step that names no
> action; **`key: EffectKey`**; **`execution_id: DurableIdentifier`** and **`step_id: DurableIdentifier`**, carrying the
> annotations `PermissionDecision.execution_id` and `PermissionDecision.step_id` use for the same two values;
> **`targets_revision: int`**, constrained `ge=1` and carrying `ActionPlan.targets_revision`'s own annotation less its `None`;
> and **`claimed_at`**, a `UtcInstant` **read from the store's own injected clock at each write that lands** — so a first
> claim stamps it, a re-point after a `SKIPPED` holder **restamps** it at the new holder's instant, and every no-write outcome
> (`COMPLETED`, `COMPLETED_OTHERWISE`, `UNCERTAIN`, `HELD`, and the same-step `CLAIMED`) **leaves it exactly as it stands**.
> **No record ever carries an instant earlier than its current holder's claim**, and the clock is injected on ADR-0026's
> discipline rather than read from the wall.

> **Normative — `targets_revision` is recorded and compared by nothing, and ADR-0265 §6 is why it is on the row at all.** That
> section rules that *"the effect record names the interpretation revision the claiming plan targeted … so that 'the
> understanding moved since this act' is a mechanical fact a later turn reads rather than a judgement it makes"*, and that
> **"it is not a second identity"**. So the store reads it from the claiming execution's plan itself — the same resolution it
> already makes for `goal_id` — **no caller threads it**, **no clause of this decision compares it**, it **scopes no claim**,
> it is **never part of the row's identity**, and it is **restamped with the row on every re-point**, because the value has to
> describe the claim that stands rather than one that was released. `ActionPlan.targets_revision` is `None` only on a plan
> `save_plan` would refuse, so a claiming plan always carries one and the field needs no absent case. **The decision that
> reads it is A8's second ADR** (§10), which is the one that asks whether to modify rather than repeat.

> The row is what `claim_effect` keeps and the value `PlanExport.effects` carries; **no `EffectRecord` is returned by
> `claim_effect`**, which returns an `EffectOutcome` and nothing else, and **no member of any Protocol takes or returns an
> `EffectRecord`** outside the export document.

> **Normative.** **`ToolDefinition` gains no field**, **`ActionRequest` gains no field**, **`ToolCall` gains no field** (it
> keeps the two ADR-0029 §2 gives it and the absences that section calls *"the design"*), **`ExecutionState` gains no field**,
> **`PlanStep` gains no field** — it carries `intended_action` already, from ADR-0265 §4, and this decision **reads** it and
> adds nothing beside it — **`Goal` gains no field**, **`GoalAttempt` gains no field**, and **`AttemptTransition` gains no
> field.** The effect row is the store's own record, reached only through `claim_effect`.

> **Normative — `StepTransition` gains exactly three fields, and they are how §2's satisfaction reaches the committed row.**
> `satisfied_by_execution` and `satisfied_by_step`, both `DurableIdentifier | None` defaulting to `None`, and
> **`satisfied_by_key`, an `EffectKey | None` defaulting to `None`** — the key of the call this step is being satisfied
> from. **The validator requires all three non-`None` together and only on a `→ SUCCEEDED` transition**, refusing any of
> them on a transition to any other status and refusing a transition carrying some but not all — ADR-0255 §11's constructor
> limb for `attempt_id`, applied to this trio, **and forbidding `output` on a transition carrying them** because the store
> writes it (below); and **`commit_transition` persists the two identifiers exactly as given onto the committed
> `StepExecution`**, the strengthening of an existing member §11 itself distinguishes from a new one.
> **`satisfied_by_key` is compared and not stored**: the row carries the key already, so `StepExecution` gains two and not three.

> **Normative — `commit_transition` gains one further claim condition, decided in the store atomically with the write, and
> it has five limbs.** A `→ SUCCEEDED` transition carrying the trio is accepted **only where** the named **execution is an
> execution of this step's own goal**, the named **step is a step of that execution and stands `SUCCEEDED`**, the goal's
> **effect row for the target step's intended action names that execution and step as its holder**, **that row's `key`
> equals `satisfied_by_key`**, and the **stored source status is `PENDING` or `AWAITING_APPROVAL`** — §2's two entry
> statuses and the two rows §4's table gains for this route, so a **`RUNNING` or `INDETERMINATE` source is refused** and no
> row carries execution marks and satisfaction marks together. It refuses on the **non-stale `PlanningError`** ADR-0255 §3
> fixes for its own conjuncts, and for that section's reason: no re-read makes one goal's execution another's, one key
> another, or a run that happened one that did not. **The fourth limb closes the same-action, different-arguments
> case** the Sunday booking makes, which §2 forbids and arm 14 asserted only at the stage.

> **Normative — and on a satisfaction the store writes `output` and `finished_at` itself.** It copies `output` from the
> **holder row it has just verified**, stamps `finished_at` from its own clock and **clears `bound_tool`**, which an
> `AWAITING_APPROVAL` source carries and a satisfied step must not; **the transition carries none of the three, and the
> validator refuses one that does**. **A value the caller never supplies cannot be mis-stated**, which is why §2's
> copy-the-holder's-output rule needs no further limb. **So every value a satisfaction lands is verified against a store
> row or written by the store**, and §2's reuse identity is **mechanical rather than advisory** in all three of its
> directions. **The satisfaction itself is never derived** — a different thing, and that would need the
> store to know which commits are satisfactions and to hold the `ToolCall` the key comes from, neither of which is its.
> **This reopens ADR-0255 §11's *"Nothing else"* closure in that one scope** (§13).

> **Normative — this is a BREAKING contract change under golden rule 5, and it is flagged here rather than inferred from a
> version number.** `PlanStore` gains exactly one member, **`claim_effect`** (§2), so **every implementation and every fake
> gains it before this decision's L2 lands**; the change extends ADR-0014 §5's member enumeration exactly as ADR-0249 §12's
> and ADR-0250's additions did, and it is BREAKING for the same reason each of those was. **`AuditTrail` gains none** — §5
> consumes `resolution_of`, which ADR-0059 §2 already landed. **`ToolInvoker`, `ActionPolicy`, `ToolRegistry`, `Planner` and
> `AssistantEngine` each gain none**, and **no Protocol member changes signature** — `commit_transition` gains **two
> strengthenings**, the persistence and the claim condition above, in ADR-0255 §11's own sense of that word. **A
> strengthening adds no member**, so ADR-0014 §5's enumeration is untouched by the pair and §13 owes them no record.

> **Normative — the effect rows are the goal's durable data and carry its obligations.** `PlanExport` gains **`effects`**, a
> possibly-empty `tuple[EffectRecord, ...]`; ADR-0014 §5's **closure rule extends to it, and it is stated over one holder
> rather than over three ids** — an included row's `execution_id` resolves to an execution in the document, its `step_id`
> names a step **of that execution**, and that execution's plan carries the row's **`goal_id`**, so a row cannot name a step
> that exists only in some other execution while every id still resolves. **The same closure is owed of a satisfied step's
> pair**: its `satisfied_by_execution` resolves to an execution of the **same goal** in the document and its
> `satisfied_by_step` to a step **of that execution**. And `PlanExport.schema_version` **moves by exactly
> one**, because the document's shape changed and an older reader's `extra="forbid"` must refuse it. **The pair of numbers is
> read off the tree by the lane that lands it and is deliberately not fixed here**: the value is **12** on `origin/main`
> today, ADR-0265 §5 moves it once more for `Goal`'s shape, and §11 puts that decision's lanes ahead of this one's — so L1
> writes **13 → 14** unless a decision between moves it again, and a lane that trusted a number in this sentence over the
> constant in front of it would ship a document two readers disagree about. Rows are **deleted by `delete_goal`'s cascade**
> with the goal they belong to, **cleared by `clear`**, and **stored locally only**. **A row references an execution and a
> step by id and inlines neither**, which is ADR-0014 §3's pattern.

> **Normative — the migration creates the table empty, and the guarantee is delimited to effects claimed under this
> decision.** **No lane reconstructs a row for an execution that predates the migration**: doing so would need the tool,
> digest and binding of a decision the **audit trail** holds, and `planning` reaching into `permissions` to build its own rows
> is what golden rule 1 forbids. **So an effect performed before the migration is not claimed, is not recognised, and a later
> plan repeating it answers `CLAIMED` and dispatches.** What bounds that is ADR-0255 §13's Q4 rule: no consequential
> capability has been wired into a production deployment, so there is no legacy real effect for the gap to expose — the same
> construction ADR-0253 §3 and ADR-0255 §7 each use, applied to the one window a migration opens.

> **Normative — the wire.** `Disposition` reaches a client, and ADR-0084 §4 makes adding a member additive rather than
> breaking. **`PROTOCOL_VERSION` is moved once, by L1** (§11), and by no other lane of this decision. **No envelope shape
> changes**, and `ExchangeDisposition` gains a mirror member **iff** the archive rendering requires one for the new
> disposition, which L1 establishes against the rendering rather than assuming either way.

### 10. What this decision does not decide, by name, each with what fires it

> **Normative.** This decision settles nothing about the following, and no lane cites it toward any of them. Each is named so
> that a reader cannot mistake this ADR's silence for a ruling, and each carries the condition that fires it.

- **The retry policy** — the three cases, **modify-before-replace**, and the rule that a known failure and
  integration-supported safe retry are treated differently from an uncertain effect. **A8's second ADR.** This
  decision establishes *what happened*; that one decides *what to do next*, and the owner's addendum requirement 5 is
  its brief: *"Keep 'do not blindly retry an uncertain effect'; drop 'nothing auto-retries, ever'"*, and *"For 'make
  it Sunday', investigate **modifying** the existing reservation first"*. It inherits the vocabulary this decision
  mints — `EffectClaim`'s **five** members, `Disposition.EFFECT_ALREADY_CLAIMED`, `Disposition.EFFECT_UNSCOPED` and §3's
  **reconcilable** test — and **`COMPLETED_OTHERWISE` is the state it is owed an act for**: this decision makes *"the
  same intended action, different arguments"* a distinguishable answer and stops there, and ADR-0265 §6 assigns the
  investigation that follows it to that decision by name. It also owes the reading of `EffectRecord.targets_revision`,
  which this decision records and compares nowhere (§9). **It does
  not inherit a general way to read an effect row**: `claim_effect` returns an `EffectOutcome`, whose holder is
  populated on `COMPLETED` alone and for §2's satisfaction alone, and §9 puts `EffectRecord` on the export document
  only, so a modify-first strategy that needs to find the earlier reservation
  adds the bounded lookup it needs and argues for it there rather than inheriting one nobody has reviewed. **It also inherits what §2
  leaves open about a `FAILED` holder**: while its plan stands, the row answers `HELD` to every step but the holder's
  own, so **a later plan cannot re-perform that effect until the holding plan is superseded** — the narrow cost §2
  states, taken because `StepExecutor.execute`'s retry makes the alternative a double dispatch. A decision that lands
  a **cross-turn retry of a `FAILED` step on a plan nothing supersedes** is the one that says how ownership passes
  there, and it establishes it **atomically with** `FAILED → RUNNING` rather than beside it. **Fired by this ADR
  landing.**
- **Resolving an uncertain effect on the user's word.** **Not decided**, and §3 states the ground:
  a `SUCCEEDED` step carries an `output` its dependents read under ADR-0253 §2, and a user cannot
  supply one. **Fired by a decision that states what `output` such a resolution carries and where
  the user is asked** — which is the same surface A9 owns.
- **Reconciling a `KEYED` step inside its `idempotency_window`.** **Not decided**, and §3 states
  the blocker: `InvocationLedger.claim_invocation` admits a further claim only where *"**no**
  claim under it carries the outcome `SUCCEEDED` or `INDETERMINATE`"* and the last is completed
  `FAILED`, which is a floor written for a **retry** that catches a **reconciliation** with it.
  Closing it needs either a reconciliation admission on that member or a widening of ADR-0192 §1's
  further-claim enumeration, each a change to a safety floor and each carrying its own
  supersession — **neither is taken here, and no lane adds either on this decision's authority**.
  **Fired by a decision that takes one of the two**, which is also the decision that first makes
  this system's best uncertain-effect guarantee reachable.
- **Reconciling an uncertain effect at the designated egress seam.** **Not decided**, and §3
  states the ground: ADR-0148 §9 rules *"There is no egress outside a claimed step"* and *"A
  designated seam adds no reconciliation path of its own"*, while §3's call takes no step claim.
  **This is the consequential case**, so the shape a later decision would most plausibly take is
  named **without being decided**: the reconciliation made as a **claimed read step of the goal's
  next attempt** — planned and serviced as one of ADR-0251 §1's rounds, dispatched under its own
  committed `→ RUNNING` claim so §9 is **satisfied rather than bent**, its answer recorded as an
  ADR-0252 §1 `GoalEvidence` row and the `INDETERMINATE` step resolved from that row — and **never
  a direct invoke taken by §4's pass**. **No lane builds it on this decision's authority**: it
  needs a producer from an evidence row to a step transition that neither ADR-0252 nor this
  decision has. **Fired by A8's second ADR** (the retry policy, which must say what to do about an
  uncertain egress effect) **or by the wiring of the first consequential capability through the
  seam ADR-0154 §1 designated, whichever is first.**
- **Reconciling a side-effecting `Idempotency.NATURAL` step.** **Not decided**, and §3 states both blockers rather
  than one. `NATURAL` is ADR-0016 §4's guarantee about **the effect** — *"the operation is idempotent by nature (a
  read; set-to-a-value)"* — and **no declaration in this corpus says a repeat returns what the first call returned**,
  so a repeat's result cannot be committed as the interrupted step's `output` for a dependent to read. And the call
  **acts**, so a reconciliation of a step on a plan a stored plan supersedes would drive a superseded plan, which
  ADR-0255 §7 forbids. **The decision that takes it owes both**: a `ToolDefinition` declaration that a repeat is
  answer-stable, and a supersession rule for a reconciliation that acts. **Fired by that declaration landing**, or by
  the first measured case in which a crashed side-effecting `NATURAL` step strands a goal.
- **A third reconciliation route** — a declared reconciliation read on `ToolDefinition`, or an
  integration that can report an effect's status without performing it. **Not decided.** It would
  also be the producer of the `INDETERMINATE → FAILED` row §7 declines to add, and it is the same
  `ToolDefinition` surface the entry above needs. **Fired by an
  integration that offers such a read.**
- **What the user is told** about an uncertain effect, an `EFFECT_ALREADY_CLAIMED` disposition, a
  completed sweep or a replayed answer. **A9**, which is ADR-0249 §13's own division and ADR-0255
  §12's for the same class of question. §3 fixes that the record is preserved and *"told once"* is
  a property of the report; this decision fixes no reply, no phrasing and no channel. **Fired by
  this ADR landing.**
- **A dedicated `satisfy_step` store member.** **Not decided.** A member taking the execution, step, expected version and
  trio would make the invalid states **unrepresentable** rather than refused, drop all three fields from `StepTransition`
  and **retire this decision's ADR-0255 §11 scope**. **Fired by** a finding that the five limbs still admit a satisfaction.
- **A canonical effect-input identity** — one that would recognise two authorised calls whose
  arguments mean the same thing while differing in spelling, so that `alice@Example.com` in one
  plan and `alice@example.com` in the next carried one key rather than two. **Not decided**, and
  §1 states the limit rather than implying it away. **This is a different question from the
  identity of the act**, and no lane reads ADR-0265 as having closed it or this entry as
  reopening what ADR-0265 closed: that decision fixes *which act a step is an attempt at*, and it
  leaves *which arguments spell one call* exactly where it found it. Under one intended action
  two equivalent-but-differently-spelled calls carry two keys and answer `COMPLETED_OTHERWISE`
  rather than `COMPLETED` — so what the gap costs is now a spurious modify-before-replace
  investigation rather than a duplicate act, which is a smaller and safer failure than the one
  §1 wrote this entry against. Closing it needs a canonicalisation of a
  tool's **arguments**, which is a different thing from the canonicalisation of a **destination**
  ADR-0148 §2 already lands: arguments are arbitrary JSON against a schema ADR-0145 §5 has this
  system **read** and never interpret, so a general one would put a second canonicaliser in
  `core` with no tool-independent rule to follow, and a per-tool one would be a declaration a
  tool author could get wrong in the unsafe direction. **Fired by a measured case in which a
  replan of one goal produces an equivalent-but-differently-spelled call**, or by a decision that
  gives a tool a way to declare its own effect identity and states how a wrong declaration is
  contained.
- **An effect identity that survives a tool's redefinition under one id.** **Not decided**, and §1 states the
  projection and which way it errs. `EffectKey` carries `tool_id` rather than the whole `ToolDefinition` that
  `authorises` compares, so a deployment that changes a definition's code and restarts — the only route ADR-0016 leaves,
  since an id is spent *"for the life of the process"* and the registry is *"rebuilt from scratch each run"* — can bind a
  materially different tool to an id this decision's durable rows already name. The error is toward **suppression**, not
  repetition. Closing it needs a durable identity for what a tool *does* rather than for what it is called, which is a
  `ToolDefinition` surface and a registry rule this decision touches neither of. **Fired by a registry that admits
  re-registration of a materially different definition under a spent id, or by the wiring of the first consequential
  capability, whichever is first.**
- **How a user asks for the same effect twice on purpose.** **The identity half is closed and the modify half is
  not**, and the two are separated here so that a reader does not take the booking for more than it now covers.
  **Closed**: a second action the user asked for is a **second `IntendedAction`** (ADR-0265 §1), so it reads a second
  row and **dispatches** (§2, arm 13) — *"an earlier booking must not count as fulfilling 'book another one'"* is met
  by construction rather than deferred, and the acceptance requirement this entry used to carry is discharged.
  **Still booked to A8's second ADR**: *"change the one I have"* — the same intended action with different arguments,
  which §2 answers `COMPLETED_OTHERWISE` and which that decision must turn into a modification of the act already
  performed rather than a repeat of it. The acceptance requirement is restated over what remains: *a request that
  revises an act the goal has already performed reaches a modify-before-replace investigation and never a second
  dispatch, and the investigation is opened from the recorded claim rather than from a model's declaration that the
  two are the same act (ADR-0249 §7).* **No lane tells a user to open a second goal to get a second action, and no
  clause of this decision offers that as a route** — it never needed to, and it needs to less now. **Fired by A8's
  second ADR.**
- **A plan-time refusal of a plan carrying the same concrete call twice *under one intended action*.** **Not
  decided**, and §2 states what such a plan does instead: the second step is `HELD` and the walk stops. **The
  qualifier is the whole of what ADR-0265 changed about this entry**: a plan carrying the same concrete call twice
  under **two** intended actions is not a defect at all and must not be refused — it is two rooms, and refusing it is
  the failure the identity exists to prevent. Refusing it
  at phase 4 would need the resolved arguments at validation time, which ADR-0254 §14 owns and
  ADR-0253 §6 resolves later than. **Fired by a decision that gates phase 4 on resolved values.**
- **#257's remaining half — making the ruling and the transition atomic.** **Not decided**, on
  ADR-0255 §12's own terms: it *"needs a `PlanStore` that accepts more than one transition in a
  commit"*, which #257 calls *"arguably the wrong shape for a store whose whole write API is a
  single compare-and-swap"*. §5 closes #257's other half. **Fired by an ADR that takes it.**
- **The evidence-to-claim window (#2309).** **Not decided** (§8), and ADR-0255 §13's prerequisite
  stands. **Fired by a decision that chooses between ADR-0255 §12's two mechanisms, or by the
  wiring of the first consequential capability.**
- **Whether an attempt's executions are projected into the planner's input.** **Not decided**, and
  ADR-0255 §12's entry stands unchanged — it is *"an aid rather than the guarantee"*, and this
  decision lands the guarantee, which is that entry's own firing condition read the other way.
  §2's key means a planner that repeats an effect produces a stalled step rather than a double
  booking. **Fired by a measured planner failure that this decision's key does not already
  prevent.**
- **Verification against the goal's criteria, and which `AttemptOutcome` an attempt earns.**
  **A10**, exactly as ADR-0255 §12 books it. §4's act 5 returns an attempt to `RUNNING` and writes
  **no** `outcome`; a non-terminal state with no outcome is the shape ADR-0249 §5's validator
  requires. **Fired by A10 landing.**
- **Cancellation's semantics, and which write wins against a dispatch.** **A9**, unchanged.
  §2's effect claim is one more write inside the window a cancellation bites, and this decision
  states no rule about which wins. **Fired by A9 landing.**
- **Parallel execution of two steps.** ADR-0014 §7's second half and ADR-0253 §1's clause,
  **untouched**. §2's `HELD` member bounds what a second concurrent dispatcher could do to one
  effect and is not a licence to have one. **Fired by a decision that takes it.**

### 11. The lane cut

> **Normative.** This decision is implemented in **three lanes**, in this order, each one subsystem plus its tests.

> **Normative — every lane of ADR-0265 lands before L1 of this decision, and no lane of this decision implements any part of
> that one.** `IntendedAction`, `Goal.intended_actions`, `PlanStep.intended_action`, the `A` label space and
> `PlanStore.record_intended_actions` are ADR-0265's, cut into lanes by its own §9, and **L1 reads them and adds nothing to
> them**. A lane of this decision that finds itself minting an intended action, resolving an `A` label or touching `GoalBrief`
> has left its fence. **The ordering is a hard prerequisite rather than a preference**: until `PlanStep.intended_action`
> exists and a planner can select one, §2's row cannot be scoped and §2's `EFFECT_UNSCOPED` refusal stalls every
> side-effecting step.

- **L1 — the contract and the store.** `core/types.py`'s `EffectKey`, `EffectClaim` with its five members,
  `EffectOutcome`, `EffectRecord` with its seven fields and `ToolCall.effect_key`, `Disposition`'s **two** members and
  `PlanExport`'s `effects` field with its `schema_version` move, `TurnOutcome.satisfied_from_earlier` and
  `StepTransition`'s three satisfaction fields with their validator, and `commit_transition`'s persistence of the two
  identifiers and its five-limbed satisfaction claim condition (§9);
  `core/protocols.py`'s
  `claim_effect`; `planning`'s
  `PlanExecution` transition-table row (§7) and the `PlanStore` implementation with its schema
  migration, export entry and `delete_goal` cascade; the **shared conformance suite** for
  `claim_effect` — including arm 4's two-writer case — and the **canonical fake** in
  `ai_assistant.testing`, which is `CONTRIBUTING.md`'s Protocol triad landing as one unit.
  **L1 moves `PROTOCOL_VERSION`** (§9). Arm 4.
- **L2 — the effect claim at dispatch, and satisfaction from a completed one.** `orchestration`'s executor takes the
  claim between the read-back and the `→ RUNNING` commit and derives the key from the `ToolCall` it holds. On
  **`CLAIMED`** it dispatches; on **`COMPLETED`** it checks §2's three reuse conditions and, where they hold,
  satisfies the step from the holder's `output` and lets the walk continue; on **`UNCERTAIN`**, **`HELD`** and a
  `COMPLETED` whose conditions fail it returns `EFFECT_ALREADY_CLAIMED` and stops; on **`COMPLETED_OTHERWISE`** it
  likewise returns `EFFECT_ALREADY_CLAIMED` and stops, and it refuses to call `claim_effect` at all for a side-effecting
  step naming no intended action, returning **`EFFECT_UNSCOPED`**. Arms 1–3 and 13–14.
- **L3 — the reconciliation pass, the replay and the attempt's release.** `orchestration`'s pass
  (§4), the `resolution_of` replay in `StepRunner.resume` (§5), the reconciliation call (§3) and
  the release of the attempt (§7). Arms 5–12.

> **Normative — no lane of this decision wires a consequential capability**, registers a booking integration, or enables
> anything in a production deployment. ADR-0255 §13's rule binds entire and §12's arms are stated over **controlled fakes**
> for that reason.

> **Normative — L1 lands before L2 and L2 before L3**, and no later lane's arm is demonstrated against an earlier lane's
> absence. **No lane of this decision implements the retry policy** (§10), and a lane that finds itself needing one has left
> its fence.

### 12. The arms this decision owes

> **Normative.** **Exactly fourteen arms** are owed. The first three are ADR-0255 §12's acceptance requirement for
> at-most-once written as that section demands — *"demonstrated over **both** a plan that modifies the earlier one and a plan
> produced afresh"*, and *"the paired case over an **`INDETERMINATE`** first step"*.

1. A plan driven to a **`SUCCEEDED`** step, superseded by a plan that **modifies** it and whose step would perform the
   same effect: the later step is **not dispatched** — `ToolInvoker.invoke` is not reached and no invocation is
   claimed — `claim_effect` answers **`COMPLETED`** naming the holder, and the step is **satisfied**: committed
   `PENDING → SUCCEEDED` with **the holder's `output`**, `attempts` unchanged, **its dependents then driven**, and the
   turn's outcome carrying the told-once fact. **The committed row is asserted to carry the holder's own `execution_id`
   and `step_id` in `satisfied_by_execution` and `satisfied_by_step`**, read back from the store rather than from the
   stage's return. **The arm asserts the continuation and not only the non-dispatch**,
   because a stalled walk was the defect this route closes.
2. The same over a plan **produced afresh** rather than by modification, **and the same again from
   `AWAITING_APPROVAL`**: a resumed step whose replayed `ALLOW` meets a `COMPLETED` answer is committed
   `AWAITING_APPROVAL → SUCCEEDED` the same way, with no second permission record and its recorded ruling unspent.
   **And the refusals are a table in the same arm, one row per reuse condition** (§2): a `COMPLETED` answer whose
   step has a `when` member that no longer holds, and one whose `verifies` predicate rejects the borrowed `output`.
   Each asserts **no transition**, **no invocation**, the step at its **entry status**, the walk **stopped** with
   `EFFECT_ALREADY_CLAIMED`, `satisfied_from_earlier` **carrying nothing for it**, and the holder's own record
   untouched. An implementation that marked every `COMPLETED` answer `SUCCEEDED` fails this table.
3. The paired case over an **`INDETERMINATE`** first step, demonstrated over **both** plan shapes
   in the one arm: `claim_effect` answers `UNCERTAIN` and the later step is not dispatched, for
   the modifying plan and for the fresh one alike.
4. **`EffectKey`'s construction and `claim_effect`'s contract each hold in full**, demonstrated
   in `core`'s own tests and in the shared conformance suite respectively, and therefore against
   every implementation. **`EffectKey` is table-driven** over: the **two admissible shapes** and
   **every rejected mixture** (an endpoint without an account, destinations without either, an
   account and endpoint with empty destinations); `ToolCall.effect_key` **`None` for a
   non-`side_effecting` tool and present for every side-effecting one whatever its
   `Idempotency`**; **unchanged under a post-construction mutation of `call.request`** and changed
   by the same mutation of the decision; and **equality moving** with `tool_id`, `parameters_digest`,
   `egress_account`, `egress_endpoint` and `egress_destinations` while **staying equal** across
   `planned_with_external_content`, `coverage`, `closed_loop`, two `spans` decompositions that canonicalise alike, **and
   two `ToolDefinition`s that share an `id` and differ in every other field** — the projection §1 declares, asserted
   deliberately so that a later lane that widened the key to the whole definition would fail this row rather than
   silently double-dispatch on a harmless re-registration.
   **`claim_effect` is table-driven over §2's second limb** — each of `StepStatus`'s seven members, crossed with the
   row naming **this** step and a **different** one, **and crossed again with the row's key being this call's key and
   not being it** — and asserts for each both the returned member **and** whether the row moved **and, where it moved,
   that its key moved with it**. **The `SUCCEEDED` pair is the Sunday case at the store**: equal keys answer
   `COMPLETED`, unequal keys answer `COMPLETED_OTHERWISE`, and neither writes. **The `SKIPPED` and superseded-`FAILED`
   rows are asserted to re-key**, which is what keeps at most one row per `(goal_id, intended_action_id)`. **The `FAILED` pair is what stops `StepExecutor.execute`'s retry racing a later plan**: this step answers
   `CLAIMED`, a different one `HELD`, and the row moves in neither. It adds: **durable re-pointing** after a `SKIPPED`
   holder, with **`claimed_at` and `targets_revision` both restamped** to the new holder's; **both preserved** on every
   no-write outcome, under an injected clock, and **both asserted on the initial claim** — the pair together on every
   path, because a stale revision surviving a re-point hands §10's modify-before-replace decision a false account; the
   **refusal** paths — an unknown `execution_id`, a `step_id` that is not a step of that execution, and a `step_id`
   whose stored step carries **no `intended_action`** — each raising `PlanningError` with **no row written**; the
   **satisfaction marks**, where a `→ SUCCEEDED` `StepTransition` carrying the two identifiers persists **both exactly as
   given** onto the committed `StepExecution` with `attempts` at `0` and `started_at`, `approval_ref` and **`bound_tool`
   all `None`** — the last **cleared**, asserted from an `AWAITING_APPROVAL` source that carried one — the validator's own
   refusals sitting in `core`'s construction table (§9) — **and the claim condition's six refusals**: a trio naming **another goal's** execution, a
   step **not of** that execution, a step **not standing `SUCCEEDED`**, one the goal's **effect row does not name as
   holder**, one whose **`satisfied_by_key` is not the row's key** — the Sunday case at the store — and one whose **stored
   source status is `RUNNING` or `INDETERMINATE`**, each raising the **non-stale `PlanningError`** with **no write**, and
   staying refused across a re-read, **and the store's own writes**: the row's `output` is the **holder's**, its
   `finished_at` the injected clock's, and the claim marks absent. **The export closure is armed
   too**: a valid satisfaction pair resolves, while a **dangling** `satisfied_by_execution`, a `satisfied_by_step` of
   **another execution**, and an execution of **another goal** are each **rejected**; and
   **atomicity under contention**, where two writers claim one
   `(goal_id, intended_action_id)` concurrently, **over both write paths** — **no row**, and an existing **`SKIPPED`** holder
   two callers would each re-point, because a uniqueness constraint on insertion passes the first and leaves the second
   racing. In each, **exactly one** receives `CLAIMED`, the other `HELD`, and exactly one durable row names a holder.
   The store under test is not permitted to pass either by serialising the two calls in the test's own control flow. It adds one **upgrade** case: a store written before this decision opens with an **empty**
   effects table, exports and deletes cleanly, and answers **`CLAIMED`** for the key of a legacy `SUCCEEDED`
   side-effecting step — the delimited guarantee §9 states, asserted rather than discovered.
5. A resolved confirmation whose claim was refused, over a **paused attempt that later resumes**: the `ALLOW` is
   **replayed**, no second permission record is authored, and the step reaches its dispatch exactly once. **And the
   replay is withheld wherever it must be**, in a table over ADR-0255 §5's three predicates — a dependency that no
   longer holds, a `when` member that no longer holds, an unresolvable `resolves` — each asserting that
   **`StepRunner.resume` is not called**, `ToolInvoker.invoke` is not reached, **no transition lands**, no effect is
   claimed, and the step stays **`AWAITING_APPROVAL`** at its stored version with its resolution still unspent. **One
   further row takes the replay all the way to a refused effect claim**: `resume` is called, `claim_effect` answers
   `HELD`, and the step stays **`AWAITING_APPROVAL`** — not `PENDING` — with no transition committed and its `ALLOW`
   still unspent and replayable on a later turn.
6. The **`DENY`** counterpart: §4's act 2 commits `AWAITING_APPROVAL → SKIPPED` with
   `APPROVAL_DENIED` naming the recorded decision, and nothing is authored.
7. A supersession sweep that landed one step and not the rest is **completed** by the pass, from a **`PENDING`**
   source status. **And the progress case is the same arm's second half**: plan `P`'s step `A` is **`FAILED`** and
   holds the goal's effect row; `P` is superseded by `P2` whose step would perform that same effect; `P2`'s step
   answers **`CLAIMED`**, the row re-points to it, and it **dispatches exactly once**. Asserted against the negative
   in the same arm: with `P` **not** superseded, `P2`'s step answers **`HELD`** and dispatches nothing, while `A`'s
   own execution still answers `CLAIMED` for its retry — so the supersession is shown to be what unsticks the goal,
   and the live-plan hold is shown to survive.
8. The same from an **`AWAITING_APPROVAL`** source status, with the park's live confirmation
   disposed of by the sweep and no approval spent. **And the act-1-before-act-2 ordering is pinned
   in the same arm**, over a superseded plan whose `AWAITING_APPROVAL` step already carries a
   recorded **`ALLOW`**: it is committed `SKIPPED`/`SUPERSEDED` by act 1, **`StepRunner.resume` is
   not called**, no effect is claimed, `ToolInvoker.invoke` is not reached, and the recorded
   resolution stays in the trail unspent. An implementation that read recorded resolutions before
   sweeping would replay that `ALLOW` and dispatch an obsolete action, and arms 5 and 6 cannot
   catch it because both are stated over a plan **no** stored plan supersedes.
9. An attempt left **`RUNNING`** beside an `INDETERMINATE` step is repaired to
   **`EFFECT_UNRESOLVED`** by the pass, and the startup scan is shown to have written no attempt
   state.
10. A step left `INDETERMINATE` by the recovery scan is reconciled to **`SUCCEEDED`** and its
    attempt returns to **`RUNNING`**, over the one reconcilable declaration — a tool that is
    **not `side_effecting`** — over a
    request **rebuilt from stored plan and execution state after a restart** and accepted by
    `PermissionDecision.authorises`. **And the superseded case is a row of the same arm**: the
    same step on a plan a stored plan supersedes reconciles identically, because a read drives
    nothing. **The arm asserts nothing about a later walk**: the reconciled step belongs to
    the earlier execution, ADR-0255 §2 sends the later turn to plan again over a new one (§7), and
    a later plan matching that read is **dispatched and reads again** — it carries no effect key, so `claim_effect` is
    never called for it and it does **not** enter arms 1–3, whose outcomes all require a row.
11. **Every way a reconciliation does not resolve a step leaves it exactly as it stood**, in one table: a
    **side-effecting** `Idempotency.NONE` step, a side-effecting **`KEYED`** step, a side-effecting **`NATURAL`**
    step — the row that pins §3's exclusion, and the one an implementation reading `NATURAL` as reconcilable would
    fail — and a step whose recorded decision carries an **`egress_binding`**, which can only be a side-effecting tool
    because ADR-0148 §8 rules that a tool registered at the seam declares a *"**non-empty `discloses`**"* and
    `core/types.py` refuses *"a tool that discloses data off-device is side-effecting"*, so that row pins a conjunct
    the first already implies and is kept for it; each takes **no call**. A
    step whose `approval_ref` is absent, whose decision the trail cannot return, or whose rebuilt request
    `PermissionDecision.authorises` rejects takes **no call**. And a reconcilable step whose call returns a failure, a
    timeout or an `INDETERMINATE` of its own takes **one**, as does one whose call **raises**. **The raising rows are
    two tables and not one**: each of §3's **six declared refusals** — `ToolBindingError` (the registry no longer
    holding the recorded definition after a restart), the two spend errors, the two authorisation errors and
    `AuditError` (the invocation-claim append failing) — ends the pass at act 4 with the earlier acts' writes
    **standing** and **the turn not failing**; while a `ValueError`, a bare `RuntimeError` from a broken invoker and a
    `CancelledError` are each asserted to **propagate out of the pass unchanged**. An implementation catching a base
    class fails the second table. In **every**
    row the step stays **`INDETERMINATE`**, `attempts` is **unchanged**, no transition is committed, the attempt stays
    **`EFFECT_UNRESOLVED`**, and **no second call is made in that turn**. **The key is asserted per row rather than
    across them**, because §1 gives one only to a side-effecting tool: a **side-effecting** row's key answers
    **`UNCERTAIN`** to a later plan's claim, and the reconcilable row's `ToolCall.effect_key` is **`None`**
    and `claim_effect` is **never called for it**.
12. The pass's **boundaries**, in one arm, over a **controlled monotonic source**. **The deadline gate is asserted over
    every act**: a remainder already non-positive **before** it, over act 1's `→ SKIPPED`/`SUPERSEDED` sweep commit, act
    2's `DENY → SKIPPED` branch and its `ALLOW` replay, acts 3's and 5's `commit_attempt` writes and act 4's reconciliation
    call, and **between two** of them wherever an act recurs in one pass. In each, **nothing is started** for the ungated
    step or attempt — **no transition and no attempt state is committed**, `ToolInvoker.invoke` is **not reached** and
    `StepRunner.resume` is **not called** — the
    step keeps the status it stood at, the pass **ends**, earlier acts' writes **stand**, and the **turn does not fail**;
    an implementation that passed the turn's whole figure to more than one act, or passed a non-positive remainder
    through, fails these rows with the `ValueError` §3 propagates, and one that gated only the acts that make a call
    fails the sweep and `DENY` rows. It touches **only the goal the turn engaged**:
    a
    second goal carrying the same three residuals is **unchanged**, and nothing runs for it until
    a turn engages it. And a **store failure injected at each act boundary** stops it there: what
    landed **stands**, every later act is **not taken**, **no write is retried inside that turn**,
    **the turn itself does not fail**, and the next turn that engages the goal runs the pass again
    over whatever is then residual. **And the stale compare-and-swap §3's admitted concurrency
    produces is a distinct row of this arm, driven by a barrier rather than by an injected store
    error**: two turns reconcile one `INDETERMINATE` step at once and both calls return, one
    `INDETERMINATE → SUCCEEDED` commit **lands** and the other loses on a stale
    `expected_version` — after which the winner's `SUCCEEDED`, its `output` and its `finished_at`
    **stand unchanged**, the loser **writes nothing**, **retries nothing**, takes **no later act**
    of its pass and makes **no second reconciliation call**, and **the losing turn does not
    fail**. The store under test is not permitted to pass this row by serialising the two passes
    in the test's own control flow.

13. **Two intended actions, one goal, two dispatches** — the owner's *"book two identical rooms"*, and the arm that
    would have been impossible before ADR-0265. One goal holds **two** `IntendedAction`s; one plan carries two steps
    naming one each, whose bound tool, resolved arguments and binding are **identical**, so their `EffectKey`s are
    **equal**. Both steps reach `claim_effect`, **both answer `CLAIMED`**, **two durable rows** exist — one per
    `(goal_id, intended_action_id)` — **`ToolInvoker.invoke` is reached twice**, and neither step is `HELD`,
    satisfied, or carries `EFFECT_ALREADY_CLAIMED`. **Asserted against the negative in the same arm**: the same two
    steps naming **one** intended action dispatch **once**, the second answering `HELD` — so the arm shows that the
    scoping and not the key is what separates the two cases, and an implementation that keyed the row on
    `(goal_id, effect_key)` fails the first half while passing the second.
14. **One intended action, different arguments — the Sunday case, end to end.** A plan is driven to a **`SUCCEEDED`**
    step under intended action `A`; the goal's interpretation is revised and a later plan carries a step naming **the
    same `A`** whose resolved arguments differ, so its `EffectKey` differs. `claim_effect` answers
    **`COMPLETED_OTHERWISE`**; the step is **not dispatched** — `ToolInvoker.invoke` is not reached and no invocation
    is claimed — **no transition is committed**, the step **keeps its entry status**, the walk **stops** with
    `Disposition.EFFECT_ALREADY_CLAIMED`, `satisfied_from_earlier` carries **nothing** for it, the holder's own record
    is **untouched**, and **the row does not move and is not re-keyed**. **And the unscoped case is the same arm's
    second half**: a side-effecting step whose `intended_action` is `None` reaches **no `claim_effect` call**, commits
    nothing, keeps its entry status and returns **`Disposition.EFFECT_UNSCOPED`**, while a non-side-effecting step
    carrying `None` is driven exactly as before. An implementation that answered `CLAIMED` to the revised step fails
    the first half and double-books; one that answered `COMPLETED` fails it by satisfying a changed request from an
    unchanged act.

> **Normative — no arm of this decision requires a real integration, a scheduler or a restart loop.** Arms 1–3 and 10–11 are
> stated over a controlled `ToolInvoker` whose declaration and returned outcome the arm fixes, and arms 13 and 14 over the
> same; **no arm mints an intended action outside `orchestration`** — each takes the goal's actions through ADR-0265 §5's own
> member, so none of them is a test of this decision's that depends on a shape ADR-0265 did not land. Arm 4 is stated over the
> store alone; arm 9's residual is produced by a store failure the arm injects, and arm 11's rows are driven by a controlled
> trail and invoker rather than by a real integration. **No arm requires a stopped walk to be re-entered**, and none asserts
> that a dependent of a reconciled step runs — §7 adds no route to one and ADR-0255 §2's closed list is what it leaves in
> place.

### 13. Records owed on earlier ADRs, under ADR-0082 §1

**Exactly four documents are partially superseded, in seven scopes — ADR-0014 in three, ADR-0255 in two, ADR-0192 in one and
ADR-0037 in one** — and the entries below show the working for those and for each other document a reader would expect to be
superseded and is not. ADR-0082 §1's test is applied to each earlier ADR's **text**: would a reader holding only it now act
differently, or read one of its clauses more widely than it holds?

**ADR-0014 §4 — partially superseded in its transition table, and the scope is on this document's `Status` line.** §4 states
that *"every legal move is enumerated in §4 and enforced by `PlanExecution`"*, and its table carries no row leaving
`INDETERMINATE` and no row reaching `SUCCEEDED` except from `RUNNING`. A reader holding only it builds a `PlanExecution`
that raises `PlanningError` on `INDETERMINATE → SUCCEEDED`, so §7's reconciliation cannot be committed at all, **and on
`PENDING → SUCCEEDED` and `AWAITING_APPROVAL → SUCCEEDED`, so §2's satisfaction of a step from an effect its goal already
completed cannot be committed either**. That is ADR-0070 §1's test met and **partial** in ADR-0070 §3's sense: the scope is
the table's enumeration of moves **out of an uncertain step and into a successful one**, and nothing else. **Every other
move in that table binds entire** — `PENDING → SKIPPED` and `AWAITING_APPROVAL → SKIPPED` included, which no clause here
widens — and so do §4's every-claim-carries- an-`approval_ref` rule, its claim-before-invocation ordering, its terminal
`SUCCEEDED`/`SKIPPED` and `FAILED`-unless-retried rule, its recovery paragraph and its *"We do not claim exactly-once
execution"* statement — which this decision quotes as its own ground rather than weakening.

**ADR-0014 §3 — partially superseded in the marks it requires of a `SUCCEEDED` step, and that scope is on this document's
`Status` line.** `_claimed_step_is_authorised` requires an `approval_ref`, a `bound_tool`, a `started_at` and `attempts >=
1` of every step in `_CLAIMED_STATUSES`, `SUCCEEDED` among them. §2's satisfied step has none: no tool was bound for it, no
authorisation was spent on it, nothing started and nothing was attempted. A reader holding only §3 therefore builds a record
that **cannot represent a satisfied step at all**, which is ADR-0070 §1's test met and **partial** in ADR-0070 §3's sense —
the scope is that one requirement, on a `SUCCEEDED` step carrying `satisfied_by_execution` and `satisfied_by_step`, and
nothing else. **Every other clause of §3 binds entire**, including its *"what actually happened"* reading, which the two new
fields keep rather than bend: the record says the act happened elsewhere in this goal and names where, instead of claiming a
call this step never made.

**ADR-0014 §5 — partially superseded in its `PlanStore` member enumeration, its `PlanExport` shape and `delete_goal`'s
cascade, and that scope is on this document's `Status` line too.** §5's code block enumerates the store's members and its
`PlanExport` its document's fields; §9 adds `claim_effect` to the first and `effects` to the second, extends §5's closure
rule to the new rows' three references, moves `schema_version` by one, and reaches those rows with `delete_goal`'s cascade.
A reader holding only §5 builds a store with no member that can claim an effect and an export document whose
`extra="forbid"` refuses the field this decision's rows are carried in, so ADR-0070 §1's test is met. **This is the third
time that enumeration has been extended in the same shape** — ADR-0249 §12 added five members and the `attempts` field,
ADR-0250 added eight and reached `delete_goal`'s cascade to a goal's questions — and it is written the same way for the same
reason. **Every other clause of §5 binds entire and several are the grounds this decision reasons from**: its
compare-and-swap discipline, its commands-not-snapshots rule, and its local-residency, export-completeness and deletion
obligations, which §9 takes for the effect rows. **§§1-2, §6 and §7 are untouched.**

**ADR-0014 §7's deferral is fired and earns no record, and the distinction is ADR-0082 §1's own.** That section defers
*"Idempotency keys and `INDETERMINATE` resolution … Automated reconciliation of an `INDETERMINATE` step waits on it"*.
Firing a deferral **contradicts no sentence** the earlier ADR wrote — a reader holding §7 reads that the work is deferred,
and it was, until now. ADR-0082 §1 calls that a **stacked addition**: *"it is recorded in the ADR that makes it, and nowhere
else."* ADR-0255 §17 is the corpus's own precedent, taking four deferrals and recording none of them — *"what it takes it
takes by **firing deferrals** rather than by replacing clauses"*.

**ADR-0037 §4 — partially superseded in one step of the resume sequence, and the scope is on this document's `Status`
line.** §4's numbered sequence has `resume` always take step 4, *"`policy.resolve(confirmed, approved=…)`"*, and step 5,
*"record the resolving decision with `resolves` set"*. A reader holding only it builds a `resume` that, on a binding already
carrying a resolution, authors a second one — which ADR-0036 §2's unique index refuses, leaving the strand
#257 describes permanently unrecoverable. **That reader acts differently**, so ADR-0070 §1's test
is met and the supersession is **partial**: the scope is steps 4 and 5 in the case where the binding already carries a
resolution, and nothing else. **Every other clause of ADR-0037 binds entire and is relied on**: §2's decide → record → read
back → claim order, §4's steps 1–3 and 6, its execution-and-step check and the reason it gives for checking the *stored*
execution, §4's *"the turn never answers on the user's behalf"* rule, and §6's *"This object disposes of one step, once"*
and `PENDING`-only entry.

**ADR-0255 §7 and §12 — partially superseded in the identity their at-most-once obligation is stated over, and the scope is
on this document's `Status` line.** §7 rules that *"an effect a `SUCCEEDED` and verified step produced, and an effect an
`INDETERMINATE` step may have produced, are each performed **at most once across every plan of that goal**"*, and §12 states
the acceptance requirement over *"a plan whose step would perform **the same effect**"*. §§1-2 land an identity in two parts
— the **intended action** the step is an attempt at (ADR-0265 §1), which the row is scoped to, and the **authorised call**
within it, identified by the bound tool's **id**, the digest of the supplied arguments and the binding's reach — and state
in terms that two calls meaning one thing while spelling it differently carry two keys, so under one intended action the
second is `COMPLETED_OTHERWISE` and under two it is dispatched. **A reader holding only ADR-0255 §7 therefore reads its
obligation more widely than it now holds**: they expect A8's mechanism to make the *effect* at most once and get one that
makes **one authorised call under one intended action** at most once — narrower than *effect* in one direction, because a
differently-spelled equivalent is not caught, and **deliberately narrower in another**, because two intended actions
carrying one key are two acts and both happen. That is ADR-0070 §1's test met, and **partial** in ADR-0070 §3's sense — the
scope is the identity, and nothing else. **Every other clause of §7 and §12 binds entire**: §7's
keeps-everything-it-recorded rule, its extension of ADR-0228 §5's not-driven rule, its sweep and the sweep's stated
residual, its one-plan-per-walk rule and its no-licence-to-repeat prohibition; §12's every other entry, its two acceptance
requirements' *other* halves — the modifying-and-fresh demonstration, the paired `INDETERMINATE` case, and the
resolved-but-unapplied answer entire — and its firing conditions. §10 books the canonical effect-input identity that would
close the difference, with what fires it.

**ADR-0255 §11 — partially superseded in its `core/types.py` clause's closure alone, and the scope is on this document's
`Status` line.** That clause adds *"**One field**: `StepTransition.attempt_id`"* and closes the type — *"**Nothing
else**"*. §9 adds **three more** — `satisfied_by_execution`, `satisfied_by_step` and `satisfied_by_key` — the only stated
route by which the holder's identifiers reach the committed `StepExecution`, which `commit_transition` writes from a
`StepTransition` and nothing else, and by which the store can check the key it is being satisfied under; so a reader
holding only §11 cannot carry §2's satisfaction at all — ADR-0070 §1's test met, and **partial**
in ADR-0070 §3's sense: the scope is that closure, and nothing else. **Every other clause of §11 binds entire** —
`attempt_id` and its validator, the no-new-model/enumeration/constant rule, the no-widening list, its three-member and
four-strengthening classification of what *that* decision changed, which §9's two strengthenings add to, the triad
obligation, and its `PROTOCOL_VERSION` and `PlanExport.schema_version` clauses (§9).

**Every other clause of ADR-0255 is relied on and not superseded, and the working is that its own clauses name this lane.**
A reader would expect records on §6 and on §12's residual entries, because this decision writes `EFFECT_UNRESOLVED` from a
later turn and completes a sweep those sections leave residual. They get none. §6's prohibition reads *"no lane … retries
the attempt write from a later turn **on its own authority**"* and its next clause reads *"repairing that residual is
**A8's**"*; §7's reads *"No lane retries the sweep, resumes it from a later turn"* and its next clause reads *"A8's
reconciliation … is the **only one** that may complete a sweep"*. **A reader holding only ADR-0255 therefore reads exactly
what this decision does** — that a named later lane completes them — and acts no differently. §12's entries are deferrals,
fired, which ADR-0082 §1 makes a stacked addition. And §6's *"the driver is `EFFECT_UNRESOLVED`'s one producer, **for a step
it drove**"* is scoped by its own trailing clause, which §6's very next paragraph confirms by handing the unwritten case to
A8. **Every other clause of ADR-0255 binds entire and is relied on**, §1's four evaluations and its no-parameter-mapping
rule, §2's stop rule and its closed re-entry list, §3's claim conjuncts, §5's re-walk-from-the-first-position rule and its
three re-evaluated predicates, §9's budget and §13's Q4 rule included.

**ADR-0192 §3 — partially superseded in its firing clause alone, and the scope is on this document's `Status` line.** That
section rules *"The ADR that lands automated reconciliation is fired by a tool contract that offers a **lookup by
idempotency key** — until a tool can be asked whether a key was already acted on, reconciliation has nothing to read."* §3
of this document lands automated reconciliation **with no such lookup**, on a **read alone** — a `ToolDefinition` that is
not `side_effecting`, whose decision carries **no `egress_binding`**, and whose interrupted call *"changed nothing"*
(ADR-0029 §4). There the call **is** the read — it establishes the step's status by performing the only thing the step was
for — so the premise *"reconciliation has nothing to read"* does not hold, and a reader holding only §3 would wait for a
contract this decision does not need. That is ADR-0070 §1's test met and **partial** in ADR-0070 §3's sense: the scope is
that firing clause, and nothing else.

**ADR-0192's other clauses bind entire and several are the grounds this decision reasons from.** §1's spendability rule is
**relied on for the further-claim admission** rather than used as §3's eligibility test — the admitted set is strictly
narrower — and §1's further-claim enumeration — *"**no** claim under it carries the outcome `SUCCEEDED` or `INDETERMINATE`"*
— binds **verbatim** and is what §10 books the `KEYED` route behind, so **no clause here widens it, adds an admission, or
changes any signature on `InvocationLedger`**. §3's *"This ADR lands no automated reconciliation of an `INDETERMINATE` act
and mints no idempotency mechanism"* stays true of ADR-0192; its recovery-scan clause is relied on by §6 and §3 alike; and
its spending-on-`INDETERMINATE` argument is the reason the side-effecting cases stay uncheckable here.

**ADR-0029 §5 — relied on entire and not superseded, and §3's reconciliation is not a relaxation of its retry rule.** A
reader would expect a record, because §5 says an `INDETERMINATE` outcome is not auto-retried. It gets none, and the working
is this: §5 states two things beside each other — *"Neither is an `INDETERMINATE` outcome, which ADR-0014 §4 already places
outside automatic retry and which this does not relax"*, and, in the same breath, *"Both remain resolvable by asking the
user or **by reconciling with the tool**, which is the explicit resolution ADR-0014 §4 requires."* §3 performs the second
and leaves the first untouched: no `INDETERMINATE` step is retried under §5's clause-2 conjunction, and the one call §3
admits is the reconciliation §5 itself names, on the one declaration under which a repeat is not a second effect. **A reader
holding only ADR-0029 §5 already knows reconciliation with the tool is available**, and acts no differently. §5's derivation
of `idempotency_key`, its three properties and its two-sided window obligation are relied on as the ground of §§1 and 3, and
ADR-0029 §4's `interrupted_outcome` rule is relied on as the ground of §1's `None` limb.

**ADR-0250 §12 — relied on and not superseded, and the no-background-pass clause is satisfied.** A reader would expect a
record, because §4 adds a pass. It gets none. That clause is **unmarked prose**, it is stated in the form *"no scheduler, no
job and no background pass **is added**"* about that decision's own additions, and it is stated as the **consequence** of
ADR-0244 §10's shape — settling *"at the first operation that reads it"*. §4's pass is that shape: it is the first operation
that reads the residual, it runs inside an owner-initiated turn, over the one goal that turn engaged, on that turn's
deadline, and nothing schedules or wakes it. So a reader holding ADR-0250 §12 reads no sentence that becomes false, and
ADR-0083 §7's *"no job gets new store surface"* is not reached. **§12's own marked clauses bind entire** — the
settle-on-read rule, the paused-and-resumable rule, `withdraw_clarification`, `SUPERSEDED`'s single producer, the
no-terminal-disposition-from-silence rule and the three user acts that open an attempt — and §4 writes no question state,
settles no question and opens no attempt.

**ADR-0148 §9 — relied on entire and not superseded, and the exclusion is why.** A reader would expect a record, because §3
makes a tool call outside a `→ RUNNING` claim. It gets none: §3's reconcilable test admits **no** call carrying an
`egress_binding`, so nothing here is a *"transmission through the seam"*, and a reader holding only §9 goes on believing
there is no egress outside a claimed step and that a designated seam adds no reconciliation path of its own — **both still
true after this decision lands**, which is ADR-0070 §1's test failed. §10 books the case that would need a record, and
requires its route to **satisfy** §9 rather than supersede it.

**ADR-0059 §2 — relied on and not superseded, and its own close-out is why.** That section adds `resolution_of` and says
*"the recovery **operation** that consumes it is a later orchestration wave"* and *"#257 is **unblocked**, not closed
here"*. §5 is that wave. A reader holding ADR-0059 §2 expects a consumer to arrive and acts no differently when one does;
its budget rule is obeyed rather than bent (§5), and its refusal-to-present routing and its `pending_confirmations` rule are
untouched, because this decision changes no enumeration. **ADR-0044 §§2–3 are relied on entire** — the binding as the unit,
§2(b)'s one-resolution-per-binding rule and §3's two-step query — and §5 is stated so that none of them is approached.

**ADR-0265 — relied on entire, cited throughout, and superseded in nothing, and its §6 is the reason there is no record to
write.** A reader would expect one, because this decision keys its row on that decision's identity, adds a member to an enum
for a state that decision named, and takes a question §4 hands it. They get none, and the working is that **§6 is written as
an obligation on a decision that did not yet exist**: it states that *"a decision that records a goal's completed effects
keys its row on the `(goal, intended action, effect key)` triple"*, that *"**a decision that lands the claim owes an answer
for this state**"*, that such a decision *"carries on that record the `targets_revision` … of the plan the claim was taken
under"*, and that the three reuse conditions *"bound reuse and do not establish it"*. **This decision is that decision and
it discharges all four** — §2's row and its pair-lookup, `COMPLETED_OTHERWISE`, §9's `targets_revision` field and §2's A10
clause — so a reader holding only ADR-0265 §6 reads that an at-most-once claim owes these things, watches one arrive that
does, and **acts no differently**. That is ADR-0070 §1's test **failed**, which is what makes a record wrong rather than
merely unnecessary. **§6's own prohibition is observed rather than bent**: *"No lane cites this section as authority for
dispatching a step, for refusing one, for writing a `GoalStatus`, or for reading an effect row"* — every dispatch rule,
every refusal and every read in this document stands on §2 and §3 of **this** decision, and §6 is cited only for what it
obliges. **§4's last clause is answered rather than superseded**: it says in terms that *"whether an effect-bearing dispatch
must name one is decided where the effect claim is taken"*, so answering it is the thing that clause asks for, and §2's
`EFFECT_UNSCOPED` is the answer. **§1's three-field `IntendedAction`, §3's stale-link rule, §4's `A` label space, its
selection-never-invention rule and its two refusals, §5's store member and its three refusals, and §7's deferrals all bind
entire**, and §11 puts every lane of that decision ahead of every lane of this one.

**ADR-0253 §5 — relied on and not superseded, and this decision is what its sentence names.** It rules *"**Nothing in this
decision makes an act at-most-once** … Making an intended effect happen at most once is a different mechanism entirely — it
is the idempotency key and the `INDETERMINATE` reconciliation ADR-0014 §7 defers and **A8** takes."* This is A8, and a
reader holding ADR-0253 §5 reads that and acts no differently. **ADR-0253 §2's dependency rule and its `INDETERMINATE`
branch-stopping clause bind entire**, and §7 relies on them for what happens after a resolution.

**The records land in the same change as this document** (ADR-0082 §7): **ADR-0014's, ADR-0255's, ADR-0192's and ADR-0037's
`Status` records**, each carrying its scope with no `ADR-NNNN` token inside the parentheses under ADR-0070 §4's extraction
invariant and each accumulating beside the pairs those lines already carry, together with **the appended dated note each
carries**, which ADR-0082 §1 makes *"the invariant half of the record"*. That is the atomic pair ADR-0082 §7 permits while
this decision stands `Proposed`, and it is why this PR touches **five** files.

### 14. This ADR classified under ADR-0070 §1 and ADR-0082 §1

**A reader acts differently, so this is a decision and not a clarification.** A reader holding the corpus without it builds
a system that re-books a campsite on a replan, that can never resolve an `INDETERMINATE` step, that leaves an attempt
reading `RUNNING` while it holds an effect it cannot account for, that leaves a `PENDING` step on a plan nobody will drive,
and that spends a user's one *yes* on a dispatch that never happened while the ruling sits durable and unread in the trail.
That is ADR-0070 §1's test met, and a new ADR is the instrument — as it must be in any case, since `core/types.py` and
`core/protocols.py` both change (golden rule 5, ADR-0015).

**It is a partial supersession of exactly four documents in seven scopes** (ADR-0070 §3) — ADR-0014 in §4's transition
table, in §5's member enumeration, `PlanExport` shape and `delete_goal` cascade, **and** in §3's `StepExecution` record;
**ADR-0255** in the identity §7's and §12's at-most-once obligation is stated over **and** in §11's *"Nothing else"*
closure over `StepTransition`; **ADR-0192** in §3's firing clause; and
ADR-0037 in §4's resolution step — and §13 shows the working for each and for the six documents a reader would expect and
that get no record — ADR-0148, ADR-0029, ADR-0250, ADR-0059, ADR-0253 and **ADR-0265**, whose §6 states the obligations this
decision discharges and whose §4 hands it one question, neither of which a reader acts differently on once this lands.
**Every other ADR it touches is relied on**, and what it takes it takes by **firing deferrals** rather than by replacing
clauses: ADR-0014 §7's, ADR-0255 §12's seven entries — two of which carry the acceptance requirements stated there —
ADR-0059 §2's named later wave, and ADR-0253 §5's named mechanism.

## Consequences

**An effect becomes a thing the system can recognise, and the record that recognises it is one row.** *"Has this goal
already done this"* is answerable by a store lookup rather than by a planner's memory or a reviewer's attention, and it is
answerable **at the one moment it matters** — after the arguments are concrete and authorised, and before the claim.

**`INDETERMINATE` stops being a terminal sink for the one call the corpus lets us make twice without asking anything of the
answer.** That is a **read**, and only where the decision carries no egress binding: its repeat changes nothing *and*
returns the state rather than a transition, so the step is established on the goal's next turn, before that turn plans, and
whatever it then plans and walks reads a settled record. Everywhere else — every side-effecting step whatever its
`Idempotency`, and every egress step — the uncertainty is preserved exactly as R45 asks, and it — this is the new part —
**cannot be repeated**, because the key refuses every later claim. A read carries no key and needs none. **The
side-effecting `NATURAL` case is the one this decision gave up on deliberately** (§10): its effect is safe to repeat and its
*answer* is not declared to be, and committing an output nobody guaranteed is worse than saying we do not know.

**The `KEYED` case is the one this decision wanted and could not have.** It is the better guarantee — answer-stable as well
as effect-stable — and ADR-0192 §1's further-claim rule, written for a retry, refuses the call that would use it. Until a
decision lifts that floor (§10), no side-effecting uncertain effect is checkable at all.

**Two residuals ADR-0255 left durable are finished by the first turn that looks.** A part-way sweep and an attempt stranded
`RUNNING` are both repaired by a pass that runs on the goal the user came back to, with no scheduler, no job and no
background pass — which is the shape ADR-0250 §12 and ADR-0244 §10 already chose for expiry.

**A user's *yes* stops being losable.** The resolution was already durable and already findable; what was missing was the
one code path that reads it, and §5 is that path. The one-shot approval is spent once, and neither re-asked nor doubled.

**A replan repeating a completed effect finishes rather than either double-acting or stalling, and that is the shape this
decision takes on purpose.** A step whose key answers **`COMPLETED`** is satisfied from the earlier step's own `output` and
its dependents are driven, so the revised workflow completes with the work done once and the user told once (§2). What still
stops is **`UNCERTAIN`**, **`HELD`** and **`COMPLETED_OTHERWISE`**: there the earlier act's result is not known, or belongs
to a step still able to use it, or was produced by different arguments under the act now being revisited, and there is
nothing honest to inherit — the walk stops, its dependents wait, and ADR-0014 §4's ground is the one this decision stands
on, that *"guessing would not be"* the deterministic answer.

**A deliberate second action is no longer a residual, and a revision is no longer a duplicate.** The at-most-once rule is
scoped to the intended action ADR-0265 mints, so a goal that asked for two rooms holds two rows and dispatches twice, and a
goal whose booking moves to Sunday meets `COMPLETED_OTHERWISE` rather than a fresh claim. **What is left is one booking and
not two residuals**: the modify-before-replace investigation that `COMPLETED_OTHERWISE` must open, which §10 books to A8's
second ADR with the acceptance requirement it owes. The cost of the scoping is stated too, and it is ADR-0265 §6's own: an
intended action minted **wrongly** makes an otherwise duplicate claim fresh, which is why that decision adds a sixth
condition to ADR-0255 §15 item 19's gate rather than leaving it at five.

**A second cost is that reconciliation reaches a callable, though never the designated egress seam.** §3's call is the one
act this decision takes outside the store, it is taken only under a declaration that makes a repeat not a second effect,
only where the decision carries **no egress binding** so ADR-0148 §9 is not reached, only once per step per turn, only over
a request rebuilt from durable state and accepted by `PermissionDecision.authorises`, and only under the authority already
recorded. That is a narrower licence than a retry and it is stated as one; a lane that widens it has left the fence.

**Revisit when** the retry policy lands (does `EffectClaim` give it what a modify-first strategy needs?), when a measured
case shows a `KEYED` window too short to reconcile within, or an `Idempotency.NONE` integration that could report its own
effect (§10's third reconciliation route), when the route §10 books for an uncertain **egress** effect is taken, when a
legitimate repeated effect inside one goal is refused (§10), when
#2309 is closed (ADR-0255 §13's second prerequisite), or when the first consequential capability
is wired and the Q4 gate is read for real.

## Alternatives considered

- **A declared idempotency key on `ToolDefinition`.** Rejected. A tool author's declaration cannot
  express *"this call is the same effect as that earlier call of this goal"*, because the tool sees
  neither goal nor history. It would also be a field, which ADR-0029 §5 rejected for three reasons
  that apply unchanged — a value some caller computed, two callers could compute differently, and
  a retry path could forget to carry.
- **A step's capability and its plan parameters as the key.** Rejected on ADR-0255 §7's own
  ground — *"A driver that compared capability and parameters would be inventing an identity
  nobody declared"* — and on ADR-0249 §7's asymmetry, since a capability string is the planner's
  word. §1 takes the **bound tool's id**, the **canonicalised arguments a policy ruled on** and
  the **account, endpoint and canonical destination set it ruled under** instead, which are
  values code fixed rather than a model proposed.
- **Canonicalising the parameters before digesting them, so equivalent spellings share a key.**
  Rejected **here** and booked in §10. It is the right answer to a real residual and it is a
  mechanism of its own: `parameters_digest` is ADR-0021 §1's, computed at the request and
  compared by `authorises`, and a second digest over a *different* canonicalisation would be a
  second identity for one call, computed in a second place, free to disagree with the one the
  permission stage rules on. §1 states what the key reaches instead of quietly widening it.
- **A single hashed string as the key.** Rejected in §1. A composed digest needs an algorithm, a
  byte encoding, a domain separator and an output representation pinned, and every one of those is
  a thing two conforming implementations could differ on — after which a restart misses a row and
  dispatches the effect again. A frozen model compared by value needs none of them:
  `parameters_digest` is already ADR-0021 §1's `sha256` and the other two fields are values.
- **Exempting `Idempotency.NATURAL` from the key.** Rejected. It was the first draft's rule,
  reusing `interrupted_outcome`'s two-limb test, and it is wrong because ADR-0255 §7's requirement
  is stated over **dispatch** — *"the later step is **not dispatched**"* — while `NATURAL` is a
  promise about what the **remote system** does with a second call. A tool's declaration about its
  own effect cannot discharge an obligation about whether we dispatch, and §3 does not exempt it
  either.
- **Reconciling a side-effecting `NATURAL` step.** Rejected in §3 and booked in §10. It was this
  document's rule through thirteen rounds. `NATURAL` guarantees the **effect** is safe to repeat
  and guarantees nothing about the **answer**, so the repeat's result cannot be committed as the
  interrupted step's `output`; and the call acts, so reconciling a superseded plan's step would
  drive a plan ADR-0255 §7 stopped. Both need declarations the corpus does not have.
- **Omitting the egress binding from the key.** Rejected. ADR-0150 §9 makes it `authorises`'s
  fifth conjunct, *"compared whole and by value"*, so two calls of one tool with identical
  parameters under different connected accounts are two different authorised calls — and a key
  that collapsed them would refuse the second as a duplicate of the first.
- **Taking the whole `EgressBinding` into the key.** Rejected, and it was the second draft's
  rule. The binding carries `planned_with_external_content`, `coverage` and `closed_loop`, which
  record how a call was reasoned about rather than what it does; two replans of one goal
  differing only in those would carry two keys and dispatch one effect twice — the failure the
  key exists to stop, reintroduced by being too faithful to a comparison written for a different
  question. §1 projects the three facts that describe where the effect goes instead, and states
  which way the projection errs.
- **Deriving the key from `ToolCall.request`.** Rejected. `frozen=True` *"does nothing about
  `call.__dict__["request"]`"*, and ADR-0018 §3 puts that mutation inside the threat model, so a
  key read from the request could be persisted for one effect while another was invoked.
  `PermissionDecision` carries every value the key needs, and it is the copy the trail holds and
  the copy `invoke` re-checks against.
- **A durable carrier for the authorised parameter mapping.** Rejected. `ActionRequest.parameters`
  is not stored, and adding a field to carry it would duplicate, in a second place free to drift,
  something ADR-0253 §6 already makes *"a total function of two values both read from the
  `PlanStore`"*. §3 rebuilds it and proves the rebuild with `PermissionDecision.authorises`, which
  is the check a carrier would have needed anyway.
- **Reusing `ToolCall.idempotency_key` as the effect key.** Rejected, and the two keys are stated
  side by side in §1 so the temptation is visible. `idempotency_key` is `decision.id`, whose
  declared property is that it is *"distinct for a distinct intent"* — it is **different** for a
  replan's authorisation, which is exactly when the effect key must be the **same**.
- **A field on `StepExecution` or `Goal` recording the effect.** Rejected. A field on
  `StepExecution` cannot be queried across plans without an index, and a field on `Goal` would
  put a compare-and-swap on the goal into every dispatch, contending with `engage_goal` and every
  interpretation revision. The row is the store's, keyed by the goal and the intended action that have to be looked up.
- **Blocking on `_CLAIMED_STATUSES`.** Rejected. That constant includes `FAILED`, and ADR-0034 §1 makes a `FAILED`
  step one where *"nothing could have run under it" is a fact the executor holds*. Blocking on it would answer
  `UNCERTAIN` about a proven failure and refuse the holder's own retry, which is R43 read backwards.
- **Treating `PENDING` or `FAILED` as re-claimable by another step.** Rejected. Two turns of one conversation are not
  serialized, so a row naming a `PENDING` step names a dispatch in progress and one naming a `FAILED` step names a
  retry `StepExecutor.execute` may still take; re-claiming either would let the second turn dispatch beside the first.
  The `HELD` member and §4's sweep are what make the key free again without that.
- **A user's word resolving an `INDETERMINATE` step.** Rejected **here** and booked in §10. A
  `SUCCEEDED` step carries the `output` its dependents read under ADR-0253 §2, and a user cannot
  supply one; taking the assertion without the output would make `verifies` unevaluable on a step
  the system had just declared successful.
- **Adding `INDETERMINATE → FAILED` to the transition table.** Rejected as a row with no producer.
  Under the one route §3 admits, a call that meets no earlier effect performs it, so the
  outcome is `SUCCEEDED`; a transition nothing writes is the vocabulary-with-no-producer problem
  ADR-0249 §5 names, and §10 says which decision earns the row.
- **Giving the startup recovery scan an attempt to write to.** Rejected in §6. It would walk every
  stranded step to its goal's attempt at startup, outside any turn and under no deadline — a
  background pass in all but name — and would put a third writer on a state ADR-0249 §5 gives one
  authority.
- **A background reconciliation job.** Rejected. It is what ADR-0250 §12's prose declines and what
  ADR-0244 §10's settle-on-read shape exists to avoid. The pass does the same work at the first
  moment anybody looks, which is the only moment at which the result can be reported to anyone.
- **Letting an ordinary walk replay a stranded `ALLOW`.** Rejected. ADR-0255 §5 rules that an
  `AWAITING_APPROVAL` step *"stops the walk where it stands"*, and changing that would supersede a
  clause this decision otherwise relies on entire. §4's act 2 runs **before** the walk instead, so
  the step is disposed of by the time one reaches it and the walk rule never has to bend.
- **Re-entering a stopped walk after a resolution.** Rejected in §7. ADR-0255 §2 closes the
  re-entry routes at one and says a later turn *"plans again — which produces a **new** plan,
  driven over a **new** execution"*. Adding a second route would supersede that clause for a
  benefit the ordering already delivers: resolving before the turn plans is what makes the
  branch drivable. **The fresh plan may re-read what the reconciliation read** — a read carries no
  key (§1) — which is the honest consequence of §3 admitting reads alone and costs nothing.
- **A new `AssistantEngine` member to drive a stranded binding.** Rejected. ADR-0059 §2 permits it
  — *"a new budgeted façade method with its own result contract"* — and it is unnecessary: the
  pass is already explicitly budgeted by the turn, and adding a member would move
  `PROTOCOL_VERSION` for a capability no interface asks for.
- **Making the effect claim a conjunct of `commit_transition`.** Rejected. It would put a second
  refusal ground on the one write every claim goes through, for a value only a side-effecting
  keyed call has, and it would make the claim's failure mode indistinguishable from a stale
  version. A separate member taken immediately before, in the safe order §2 fixes, leaves the
  transition graph exactly as it stands.
- **Keying the row on the goal and the effect key alone.** Rejected, and it was this document's rule through eleven
  rounds of review. It fails in two opposite directions at once, which is ADR-0265's own diagnosis: two identical rooms
  are one tool, one digest and one binding, so the second is satisfied from the first and the user who asked twice is
  booked once; and a booking moved to Sunday carries a different digest, so the rule sees no earlier effect, dispatches
  a second booking and leaves the first standing. **ADR-0265 §6 forbids it in terms** — *"No lane scopes such a claim
  to a goal and an argument key alone"* — and §2 keys on the intended action instead.
- **Scoping the row to the goal element the step serves, rather than to an intended action.** Rejected, and the ground
  is ADR-0253 §7: *"A **restated** element is a new element and is minted a new id"*, so *"make it Sunday"* reworded
  into the element would mint a new id, free the key and dispatch a second booking — the modify case defeated by the
  mechanism meant to serve it. ADR-0265 §1 mints an identity that is **retained** across a revision instead, and §3 of
  that decision makes `serves` a link that identifies nothing.
- **Carrying the intended action id inside `EffectKey`.** Rejected in §1. It reads like the tidier shape — one value,
  one comparison — and it destroys the only distinction this decision was extended to make: two rows that differ only
  in their key under one action would be as unequal as two unrelated acts, so `COMPLETED_OTHERWISE` could never be
  answered and the Sunday case would dispatch. The action scopes the row; the key is compared **within** it.
- **Letting a step naming no intended action dispatch unclaimed.** Rejected in §2. It is the fail-open direction: the
  effect would be performed with no row, so every later plan of the goal would answer `CLAIMED` and repeat it, which
  is ADR-0255 §7's obligation unmet rather than delimited. `EFFECT_UNSCOPED` stalls the step instead, and ADR-0255
  §13's Q4 rule bounds what that can cost while no consequential capability is wired.
- **Taking #2309 here.** Rejected in §8. Both mechanisms close a window about authority to act,
  not about an act already taken, and ADR-0255 §12 states the choice between them is a decision of
  its own.
